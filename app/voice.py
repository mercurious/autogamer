#!/usr/bin/env python3
# Speak a line with Pocket TTS (tts-server on 8093) through pacat, one line at a time, in a background thread.
# Synthesis comes first, so a caption passed as show= appears when the voice starts (as in narrate.py).
import json, os, subprocess, threading, urllib.request
TTS = "http://127.0.0.1:8093"; ENV = dict(os.environ, XDG_RUNTIME_DIR="/run/0-runtime-dir")
_lock = threading.Lock()

def _run(text, show, ra):
    with _lock:
        try:
            req = urllib.request.Request(TTS + "/v1/audio/speech", json.dumps({"input": text, "response_format": "pcm"}).encode(),
                                         {"Content-Type": "application/json"})
            pcm = urllib.request.urlopen(req, timeout=60).read()
        except Exception: pcm = b""
        if show and ra: ra.cmd("SHOW_MSG " + show, reply=False)
        if pcm: subprocess.run(["pacat", "--raw", "--format=s16le", "--rate=24000", "--channels=1"], input=pcm, env=ENV)

def say(text, show=None, ra=None):
    threading.Thread(target=_run, args=(text, show, ra), daemon=True).start()
