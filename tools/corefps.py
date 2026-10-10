#!/usr/bin/env python3
# Game speed from the game's own frame counter (one byte, +1 per frame) read over RetroArch's UDP port.
# Usage: corefps.py ADDR_HEX SECONDS      (NES Tetris: B1; Activision Tennis: 84; SMB: 09)
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")); from ra import RA
ra = RA(timeout=0.3); A = int(sys.argv[1], 16); T = float(sys.argv[2])
def rd():
    r = ra.ram(A, 1)
    return r[0] if r else None
last = rd(); t0 = time.time(); n = 0
while time.time() - t0 < T:
    time.sleep(0.5); v = rd()
    if v is None or last is None: last = v; continue
    n += (v - last) % 256; last = v
print("%.3f frames/s over %.0f s" % (n / (time.time() - t0), time.time() - t0))
