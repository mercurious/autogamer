#!/usr/bin/env python3
# Runs on the handheld: sample the 2600's 128 bytes of RAM (0x80-0xFF) and report which bytes change.
# Usage: ramwatch.py SECONDS [HZ] [out.tsv]   (tsv: t, then 128 hex bytes)
import sys, time
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")); from ra import RA
T = float(sys.argv[1]); HZ = float(sys.argv[2]) if len(sys.argv) > 2 else 30; out = sys.argv[3] if len(sys.argv) > 3 else None
ra = RA(); rows = []; t0 = time.time()
while time.time() - t0 < T:
    b = ra.ram(0x80, 128)
    if b: rows.append((time.time() - t0, b))
    time.sleep(1 / HZ)
if out:
    with open(out, "w") as f:
        for t, b in rows: f.write("%.3f\t%s\n" % (t, b.hex()))
print("%d samples" % len(rows))
for i in range(128):
    vals = [b[i] for _, b in rows]; u = sorted(set(vals))
    if len(u) > 1:
        ch = sum(1 for a, c in zip(vals, vals[1:]) if a != c)
        print("%02X  n=%-3d changes=%-4d min=%3d max=%3d  last=%s" % (0x80 + i, len(u), ch, u[0], u[-1], " ".join("%d" % v for v in vals[-8:])))
