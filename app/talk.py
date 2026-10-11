#!/usr/bin/env python3
# Runs on the handheld: push-to-talk for the player. Hold R1 and talk; let go and the words come back as text.
# The pad is read alongside RetroArch (evdev, not grabbed: the game still gets every button; NES games have no
# R1). The microphone stays open (PipeWire takes ~1.5 s to open a capture on the Flip 2, so a capture opened on
# the press loses the first word); a press marks a span of it, with a little pre-roll. The game's sound is turned
# down while R1 is held, so the built-in mic hears the player rather than the speaker. Speech recognition is
# Qwen3-ASR-0.6B in a llama-server (port 8091). Adapted from retro-voice-chat (same author, MIT).
# A WAV file put at INJECT is heard as if said with R1 held (a test without a person; any rate, 16-bit mono).
# Usage: talk.py   (prints what it hears, for a test)   env: AG_ASR (default http://127.0.0.1:8091), AG_MIC
import array, io, json, os, struct, subprocess, threading, time, urllib.request, uuid, wave
ASR = os.environ.get("AG_ASR", "http://127.0.0.1:8091")
ENV = dict(os.environ, XDG_RUNTIME_DIR=os.environ.get("XDG_RUNTIME_DIR", "/run/0-runtime-dir"))
RATE = 16000; CHUNK = 1600                  # 50 ms of s16 mono
PRE_S, POST_S, MIN_S, MAX_S = 0.25, 0.15, 0.3, 8.0
EV_KEY, R1 = 1, 0x137
INJECT = "/dev/shm/autogamer/talk.wav"
EVENT = struct.Struct("qqHHi")              # struct input_event on 64-bit: timeval, type, code, value
PADS = ("Retroid Pocket Gamepad", "Sony Interactive Entertainment DualSense Wireless Controller",
        "Microsoft X-Box", "Xbox Wireless Controller")   # the Flip 2's own controls come through InputPlumber as a DualSense

def pads():
    out = []
    for ev in sorted(os.listdir("/sys/class/input")):
        try:
            if ev.startswith("event") and open("/sys/class/input/%s/device/name" % ev).read().strip() in PADS:
                out.append("/dev/input/" + ev)
        except OSError: pass
    return out

def pactl(*a):
    try: return subprocess.run(["pactl"] + list(a), capture_output=True, text=True, timeout=5, env=ENV).stdout
    except (OSError, subprocess.TimeoutExpired): return ""

def source():
    """the microphone: AG_MIC, a USB or Bluetooth one, else the handheld's own (its Mic port, or the headset's)"""
    if os.environ.get("AG_MIC"): return os.environ["AG_MIC"]
    names = [l.split("\t")[1] for l in pactl("list", "short", "sources").splitlines() if "\t" in l]
    real = [n for n in names if not n.endswith(".monitor")]
    for n in real:
        if "usb" in n.lower() or "bluez" in n.lower(): return n
    return real[0] if real else None

def game_volume(pct):
    """RetroArch's own stream to pct % (its sink input), so a duck never touches the spoken lines"""
    block = None
    for line in pactl("list", "sink-inputs").splitlines() + ["Sink Input #end"]:
        if line.startswith("Sink Input #"):
            if block and "retroarch" in block[1].lower(): pactl("set-sink-input-volume", block[0], "%d%%" % pct)
            block = [line.split("#")[1].strip(), ""]
        elif block: block[1] += line

class Mic:
    """parec into a ring buffer; start() marks, stop() returns what came since (with PRE_S before)"""
    def __init__(self):
        self.lock = threading.Lock(); self.ring = bytearray(); self.base = 0; self.total = 0; self.mark = None
        self.proc = None; self.last = 0.0; self.src = None

    def ensure(self):
        if self.proc and self.proc.poll() is None and time.time() - self.last < 2: return
        if self.proc:
            try: self.proc.kill()
            except OSError: pass
        self.src = source()
        if not self.src: self.proc = None; return
        self.proc = subprocess.Popen(["parec", "--raw", "--format=s16le", "--rate=%d" % RATE, "--channels=1",
                                      "--device=" + self.src, "--latency-msec=50", "--client-name=autogamer-mic"],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=ENV)
        self.last = time.time()
        threading.Thread(target=self.pump, args=(self.proc,), daemon=True).start()

    def pump(self, proc):
        while proc.poll() is None:
            b = proc.stdout.read(CHUNK)
            if not b: break
            with self.lock:
                self.ring += b; self.total += len(b); self.last = time.time()
                cap = int((MAX_S + 5) * RATE * 2)
                if len(self.ring) > cap: drop = len(self.ring) - cap; del self.ring[:drop]; self.base += drop

    def start(self):
        with self.lock: self.mark = max(self.base, self.total - int(PRE_S * RATE) * 2)

    def stop(self):
        time.sleep(POST_S)
        with self.lock:
            if self.mark is None: return b""
            seg = bytes(self.ring[self.mark - self.base:]); self.mark = None
        return seg[:int(MAX_S * RATE) * 2]

def wav(pcm):
    b = io.BytesIO(); w = wave.open(b, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
    w.writeframes(pcm); w.close(); return b.getvalue()

def transcribe(data, language=None):
    """the words, or "". Qwen3-ASR names the language it heard first ("language English<asr_text>..."): anything
    else is heard again with an English hint (a short English word can come back as Portuguese)"""
    bd = uuid.uuid4().hex; parts = []
    for k, v in [("model", "asr"), ("response_format", "json")] + ([("language", language)] if language else []):
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (bd, k, v)).encode())
    parts.append(('--%s\r\nContent-Disposition: form-data; name="file"; filename="u.wav"\r\nContent-Type: audio/wav\r\n\r\n'
                  % bd).encode() + data + b"\r\n")
    parts.append(("--%s--\r\n" % bd).encode())
    req = urllib.request.Request(ASR + "/v1/audio/transcriptions", b"".join(parts),
                                 {"Content-Type": "multipart/form-data; boundary=" + bd})
    text = json.loads(urllib.request.urlopen(req, timeout=20).read()).get("text", "")
    if "<asr_text>" in text:
        head, text = text.split("<asr_text>", 1)
        lang = head.replace("language", "").strip()
        if lang not in ("English", "None", "") and not language: return transcribe(data, "en")
    return text.strip()

class Talk(threading.Thread):
    """R1 down: on_listen(); R1 up: on_text(words, seconds to hear them), or on_text("", 0, why) when nothing came"""
    def __init__(self, on_listen, on_text, duck=25):
        super().__init__(daemon=True); self.on_listen, self.on_text, self.duck = on_listen, on_text, duck
        self.mic = Mic(); self.fds = {}; self.down = False; self.t_down = 0

    def ok(self):
        try: return urllib.request.urlopen(ASR + "/health", timeout=2).status == 200
        except Exception: return False

    def run(self):
        self.mic.ensure(); scan = 0
        while True:
            if time.time() - scan > 3:                          # pads come and go (a Bluetooth pad); the mic too
                scan = time.time(); self.mic.ensure(); found = pads()
                for p in list(self.fds):
                    if p not in found: os.close(self.fds.pop(p))
                for p in found:
                    if p not in self.fds:
                        try: self.fds[p] = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
                        except OSError: pass
            got = False
            if os.path.exists(INJECT):
                try: data = open(INJECT, "rb").read(); os.remove(INJECT)
                except OSError: data = b""
                if data: self.on_listen(); self.heard(data)
            for fd in list(self.fds.values()):
                try: data = os.read(fd, EVENT.size * 64)
                except (BlockingIOError, OSError): continue
                for k in range(0, len(data) - EVENT.size + 1, EVENT.size):
                    _, _, typ, code, val = EVENT.unpack_from(data, k)
                    if typ == EV_KEY and code == R1 and val in (0, 1): got = True; self.r1(val == 1)
            if not got: time.sleep(0.01)

    def r1(self, down):
        if down == self.down: return
        self.down = down
        if down:
            self.mic.start(); self.t_down = time.time(); game_volume(self.duck); self.on_listen()
            return
        pcm = self.mic.stop(); game_volume(100)
        if not self.mic.src: return self.on_text("", 0, "no microphone")
        if len(pcm) < MIN_S * RATE * 2: return self.on_text("", 0, "too short: hold R1 while you talk")
        a = array.array("h", pcm[:len(pcm) // 2 * 2])
        if max((abs(x) for x in a), default=0) < 64: return self.on_text("", 0, "the mic sent silence")
        self.heard(wav(pcm))

    def heard(self, data):
        t = time.time()
        try: words = transcribe(data)
        except Exception as ex: return self.on_text("", 0, "speech recognition failed (%s)" % ex.__class__.__name__)
        self.on_text(words, time.time() - t, "")

if __name__ == "__main__":
    t = Talk(lambda: print("listening...", flush=True), lambda w, s, why="": print("heard %r in %.1f s %s" % (w, s, why), flush=True))
    print("ASR up" if t.ok() else "ASR not answering on %s" % ASR, "| pads", pads(), "| mic", source(), flush=True)
    t.start()
    while True: time.sleep(1)
