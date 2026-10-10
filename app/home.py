#!/usr/bin/env python3
# Runs on the handheld beside RetroArch (run.sh): HOME alone quits. Watches every gamepad node that has BTN_MODE
# (ROCKNIX's InputPlumber shows the Flip 2's own controls as a virtual DualSense; a real pad works too) and sends
# SIGTERM to RetroArch when HOME is pressed and released with no other button in between, so RetroArch's own
# HOME combos (HOME+START quit, HOME+X menu) still work. Reads only; never grabs the device.
# Usage: home.py RETROARCH_PID
import os, select, signal, struct, sys, time
EV_KEY, BTN_MODE = 1, 316
EXCLUDE = ("touchpad", "motion sensor", "headset", "battery", "keyboard")   # DualSense sibling nodes

def pads():
    out = []
    for e in sorted(os.listdir("/sys/class/input")):
        if not e.startswith("event"): continue
        try:
            name = open("/sys/class/input/%s/device/name" % e).read().strip().lower()
            keys = open("/sys/class/input/%s/device/capabilities/key" % e).read().split()
        except OSError: continue
        bits = int("".join("%016x" % int(w, 16) for w in keys), 16) if keys else 0
        if bits >> BTN_MODE & 1 and not any(x in name for x in EXCLUDE) and os.path.exists("/dev/input/" + e):
            out.append("/dev/input/" + e)
    return out

if __name__ == "__main__":
    PID = int(sys.argv[1]); fds, seen, held = {}, 0, None
    while True:
        try: os.kill(PID, 0)
        except OSError: sys.exit(0)
        if time.time() - seen > 5:                       # pads come and go (Bluetooth, InputPlumber re-creating nodes)
            for p in pads():
                if p not in fds.values():
                    try: fds[os.open(p, os.O_RDONLY | os.O_NONBLOCK)] = p
                    except OSError: pass
            seen = time.time()
        r, _, _ = select.select(list(fds), [], [], 1.0)
        for fd in r:
            try: data = os.read(fd, 24 * 64)
            except OSError: os.close(fd); fds.pop(fd, None); continue
            for i in range(0, len(data) - 23, 24):
                _, _, typ, code, val = struct.unpack("qqHHi", data[i:i + 24])
                if typ != EV_KEY: continue
                if code == BTN_MODE and val == 1: held = "clean"
                elif code == BTN_MODE and val == 0:
                    if held == "clean":
                        os.kill(PID, signal.SIGTERM); sys.exit(0)
                    held = None
                elif val == 1 and held: held = "combo"
