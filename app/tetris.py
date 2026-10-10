#!/usr/bin/env python3
# Runs on the handheld: plays NES Tetris (fceumm) from RAM over RetroArch's UDP ports, in real time.
# RAM (NES CPU addresses): 40 piece x, 41 piece y, 42 orientation id (0-18), 48 play state (1 = piece under
# control, 10 = game over), BF next piece, C0 game mode (4 = in game), 0400-04C7 playfield 10x20 (EF = empty),
# 50/51 lines (BCD), 53-55 score (BCD, low byte first), 64 level.
# Placement: every rotation x column scored with Yiyuan Lee's weights (height, lines, holes, bumpiness).
# Control: closed loop on RAM: toggle A until the orientation matches, toggle left/right until the column
# matches, then hold down.  Usage: tetris.py SECONDS [log.jsonl]
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from ra import RA; from pad import Pad
# 4 cells (dx, dy) per orientation id, read from the ROM's orientation table at $8A9C
SHAPES = [[(-1,0),(0,0),(1,0),(0,-1)], [(0,-1),(0,0),(1,0),(0,1)], [(-1,0),(0,0),(1,0),(0,1)], [(0,-1),(-1,0),(0,0),(0,1)],
          [(0,-1),(0,0),(-1,1),(0,1)], [(-1,-1),(-1,0),(0,0),(1,0)], [(0,-1),(1,-1),(0,0),(0,1)], [(-1,0),(0,0),(1,0),(1,1)],
          [(-1,0),(0,0),(0,1),(1,1)], [(1,-1),(0,0),(1,0),(0,1)], [(-1,0),(0,0),(-1,1),(0,1)],
          [(0,0),(1,0),(-1,1),(0,1)], [(0,-1),(0,0),(1,0),(1,1)],
          [(0,-1),(0,0),(0,1),(1,1)], [(-1,0),(0,0),(1,0),(-1,1)], [(-1,-1),(0,-1),(0,0),(0,1)], [(1,-1),(-1,0),(0,0),(1,0)],
          [(0,-2),(0,-1),(0,0),(0,1)], [(-2,0),(-1,0),(0,0),(1,0)]]
GROUP = [range(0,4)]*4 + [range(4,8)]*4 + [range(8,10)]*2 + [range(10,11)] + [range(11,13)]*2 + [range(13,17)]*4 + [range(17,19)]*2
W_H, W_L, W_HO, W_B = -0.510066, 0.760666, -0.35663, -0.184483

def fits(board, o, x, y):
    for dx, dy in SHAPES[o]:
        cx, cy = x + dx, y + dy
        if cx < 0 or cx > 9 or cy > 19 or (cy >= 0 and board[cy][cx]): return False
    return True

def evaluate(board):
    full = [r for r in board if all(r)]; rows = [r for r in board if not all(r)]
    b = [[False] * 10 for _ in full] + rows
    hts = []; holes = 0
    for c in range(10):
        top = next((r for r in range(20) if b[r][c]), 20); hts.append(20 - top)
        holes += sum(1 for r in range(top, 20) if not b[r][c])
    return W_H * sum(hts) + W_L * len(full) + W_HO * holes + W_B * sum(abs(hts[i] - hts[i + 1]) for i in range(9))

def best(board, ori, y0):
    choice = None
    for o in GROUP[ori]:
        for x in range(10):
            if not fits(board, o, x, y0): continue
            y = y0
            while fits(board, o, x, y + 1): y += 1
            nb = [row[:] for row in board]
            for dx, dy in SHAPES[o]:
                if y + dy >= 0: nb[y + dy][x + dx] = True
            s = evaluate(nb)
            if choice is None or s > choice[0]: choice = (s, o, x)
    return choice

def bcd(b): return (b >> 4) * 10 + (b & 15)

if __name__ == "__main__":
    T = float(sys.argv[1]); LOG = open(sys.argv[2], "a") if len(sys.argv) > 2 else None
    ra, pad = RA(timeout=0.2), Pad()
    if "PAUSED" in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
    t0 = time.time(); target = None; last_state = None; held = set(); pieces = 0; tick = 0; menu_t = 0; stuck_t = None
    try:
        while time.time() - t0 < T:
            z = ra.ram(0x40, 0x10); hi = ra.ram(0xBF, 2)
            if not z or not hi: continue
            mode, state = hi[1], z[8]
            stuck = mode != 4 or state in (0, 10)     # menus, game over, high-score name entry
            if not stuck: stuck_t = None
            elif stuck_t is None: stuck_t = time.time()
            if stuck and (mode != 4 or time.time() - stuck_t > 1.5):   # Start (level 0, A-type); in play it would pause
                target = None
                if time.time() - menu_t > 1.0: pad.tap("start", 0.1); menu_t = time.time()
                time.sleep(0.05); continue
            x, y, ori = z[0], z[1], z[2]
            if state != 1 or ori > 18: pad.hold([]); held = set(); last_state = state; continue
            if target is None or last_state != 1 or ori not in GROUP[target[1]]:    # a new piece is under control
                f = ra.ram(0x400, 200)
                if not f: continue
                board = [[f[r * 10 + c] != 0xEF for c in range(10)] for r in range(20)]
                c = best(board, ori, y)
                target = (c[2], c[1]) if c else (x, ori); pieces += 1
                if LOG:
                    st = ra.ram(0x50, 6) or bytes(6)
                    LOG.write(json.dumps({"t": round(time.time() - t0, 2), "piece": ori, "next": hi[0], "target": target,
                                          "lines": bcd(st[1]) * 100 + bcd(st[0]), "score": bcd(st[5]) * 10000 + bcd(st[4]) * 100 + bcd(st[3]),
                                          "stack": max((20 - r for r in range(20) for cc in range(10) if board[r][cc]), default=0)}) + "\n"); LOG.flush()
            last_state = state; tx, to = target; want = set()
            if ori != to and "a" not in held: want.add("a")
            if x < tx and "right" not in held: want.add("right")
            if x > tx and "left" not in held: want.add("left")
            if ori == to and x == tx: want.add("down")
            held = want; pad.hold(sorted(want)); tick += 1
            time.sleep(0.012)
    finally:
        pad.release_all()
        if os.environ.get("KEEP_RUNNING") != "1": ra.cmd("PAUSE_TOGGLE", reply=False)
        if LOG: LOG.close()
    print("%d pieces in %.0f s" % (pieces, time.time() - t0))
