#!/usr/bin/env python3
# Runs on the handheld: a run-and-jump bot for Super Mario Bros (fceumm) from RAM, in real time.
# RAM: 0E player state (8 = normal, 0B/06 dying), 1D float state (0 ground, 1 jump, 2 falling, 3 flagpole),
# 6D/86 player page/x (world x = 256 page + x), CE player y (top of sprite; 176 = standing on the ground row),
# 0F-13 enemy active, 16-1A enemy type, 6E-72/87-8B enemy page/x, CF-D3 enemy y, 0754 size (0 big),
# 075A lives, 075F/075C world/level (0760 also counts the x-2 pipe intros), 0770 mode (0 title/demo, 1 playing, 3 game over). Tiles: 0500-069F, two 16x13 pages, a tile row's
# top at y = 16 + 16 row; column = (world x / 16) mod 32.
# Usage: smb.py SECONDS [log.jsonl]     env: SMB_LOOK (tiles ahead for walls/gaps, default 2)
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from ra import RA; from pad import Pad
LOOK = int(os.environ.get("SMB_LOOK", "2")); JUMP_S = 0.40

def tile(t, col, row):
    if row < 0 or row > 12: return 0
    col %= 32
    return t[(col // 16) * 0xD0 + row * 16 + (col % 16)]

if __name__ == "__main__":
    T = float(sys.argv[1]); LOG = open(sys.argv[2], "a") if len(sys.argv) > 2 else None
    TRACE = open(sys.argv[2] + ".trace", "w") if len(sys.argv) > 2 and os.environ.get("SMB_TRACE") else None
    ra, pad = RA(timeout=0.3), Pad()
    if "PAUSED" in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
    last_mode = None; last_lives = None; t0 = time.time(); prog_t = time.time(); prog_x = -1; unstick = None; jump_t = None; a_ready = True; best = 0; deaths = 0; was_dying = False; menu_t = 0; why = ""
    try:
        while time.time() - t0 < T:
            z = ra.ram(0x00, 0x100); m = ra.ram(0x750, 0x30)
            if not z or not m: continue
            if m[0x20] != last_mode:
                if LOG: LOG.write(json.dumps({"t": round(time.time() - t0, 1), "event": "mode", "mode": m[0x20], "lives": m[0x0A], "world": "%d-%d" % (m[0x0F] + 1, m[0x0C] + 1)}) + "\n")
                last_mode = m[0x20]
            if m[0x20] != 1:                                   # 0770: title/demo or game over: Start, then give the
                if time.time() - menu_t > 4: pad.tap("start", 0.1); menu_t = time.time()   # intermission time to pass
                time.sleep(0.05); continue
            t = (ra.ram(0x500, 0xD0) or bytes(0xD0)) + (ra.ram(0x5D0, 0xD0) or bytes(0xD0))
            state, flt, y = z[0x0E], z[0x1D], z[0xCE]
            wx = z[0x6D] * 256 + z[0x86]; best = max(best, wx)
            dying = state in (0x0B, 0x06)
            lost = last_lives is not None and m[0x0A] != last_lives and m[0x0A] in ((last_lives - 1) & 255,)
            last_lives = m[0x0A]
            if lost:                                           # a pit death never shows the dying state: count lives
                deaths += 1
                if LOG: LOG.write(json.dumps({"t": round(time.time() - t0, 1), "event": "death", "wx": wx, "world": "%d-%d" % (m[0x0F] + 1, m[0x0C] + 1), "fell_pit": z[0xB5] > 1 or y > 200, "why_last_jump": why}) + "\n"); LOG.flush()
            was_dying = dying
            big = m[0x04] == 0; top_row = (y - 16) // 16; feet_row = top_row + (2 if big else 1)
            col = (wx + 8) // 16
            btns = ["right", "b"]
            if wx > prog_x + 8 or dying or flt == 3: prog_x, prog_t = wx, time.time()
            if unstick is None and time.time() - prog_t > 3: unstick = time.time()   # blocked: wait for a lift, back up, run at it
            if unstick is not None:
                u = time.time() - unstick
                if u < 1.0: btns = []
                elif u < 1.6: btns = ["left", "b"]
                else: unstick = None; prog_t = time.time()
            on_ground = flt == 0
            trigger = ""
            for k in range(1, LOOK + 1):
                c = col + k
                if any(tile(t, c, r) for r in range(top_row, feet_row)): trigger = "wall"; break
                if feet_row <= 12 and not tile(t, c, feet_row): trigger = "gap"; break
            if not trigger:
                for i in range(5):
                    if not z[0x0F + i]: continue
                    ex = z[0x6E + i] * 256 + z[0x87 + i]; ey = z[0xCF + i]
                    if 0 < ex - wx < 56 and abs(ey - y) < 28: trigger = "enemy"; break
            if jump_t is not None:                             # hold A while rising, for a full-height jump;
                if time.time() - jump_t < JUMP_S and flt != 2 and not (on_ground and time.time() - jump_t > 0.1):
                    btns.append("a")                           # let go once falling, so a landing can jump again
                else: jump_t = None
            elif on_ground and trigger and a_ready:
                jump_t = time.time(); btns.append("a"); a_ready = False; why = trigger
                if LOG: LOG.write(json.dumps({"t": round(time.time() - t0, 1), "event": "jump", "why": trigger, "wx": wx}) + "\n")
            if "a" not in btns: a_ready = True                  # A must be released before the next jump
            pad.hold(btns)
            if TRACE:
                near = min(((z[0x6E + i] * 256 + z[0x87 + i] - wx, z[0xCF + i] - y, z[0x16 + i]) for i in range(5) if z[0x0F + i]),
                           key=lambda e: abs(e[0]), default=None)
                TRACE.write("%d-%d\t%.2f\t%d\t%d\t%d\t%d\t%d\t%s\t%s\t%s\n" % (m[0x0F] + 1, m[0x0C] + 1, time.time() - t0, wx, y, flt, state, z[0xB5], z[0x57],
                                                                    near, trigger + ("+A" if "a" in btns else "")))
            time.sleep(0.012)
    finally:
        pad.release_all()
        if os.environ.get("KEEP_RUNNING") != "1": ra.cmd("PAUSE_TOGGLE", reply=False)
        if LOG: LOG.close()
    print("best world x %d, deaths %d, in %.0f s" % (best, deaths, time.time() - t0))
