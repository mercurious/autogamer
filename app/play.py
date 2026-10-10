#!/usr/bin/env python3
# Runs on the handheld: a reflex player for Activision Tennis (Atari 2600, stella) from RAM over RetroArch's UDP ports.
# The swing is automatic, so playing = standing where the ball will be; fire only serves.
# RAM (0x80-0xFF): 90 ball x, B7 ball depth (shadow; big = top of screen),
# 91 ball height, 9A/98 TOP player x/y, 9B/99 BOTTOM player x/y, D0 = 0 when player 1 (pink) is the top player,
# 1 after the players change ends. C5/C6 points and C7/C8 games, pink/blue.
# x units ~8.1 px, depth units ~4.8 px at 1080p. Top baseline y 142-148, bottom 2-7, net at depth 85.
# Usage: play.py SECONDS [DX|aim] [DY|none] [log.tsv]     (tennis_llm.py imports decide() and passes its own DX)
#   aim: per shot, hit with the racket's left part (ball goes right) when the opponent is left of centre, else the right part
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from ra import RA; from pad import Pad
T = float(sys.argv[1]); DXA = sys.argv[2] if len(sys.argv) > 2 else "-4"; DYA = sys.argv[3] if len(sys.argv) > 3 else "-9"
LOG = sys.argv[4] if len(sys.argv) > 4 else None
NET, DEAD = 85, 2          # depth of the net; dead zone in RAM units
MID = 81                   # opponent x when standing on the centre line (screen x 617 px)
AIM_R, AIM_L = -12, -2     # DX that sends the ball right (offset ball-player +12) / left (+2); measured 2026-10-09 (top end)
DX_SERVE = -4              # an aimed serve goes out
LEAD = float(os.environ.get("LEAD", "10"))   # polls ahead to aim y at the ball's coming depth (0 = chase it)
# per end: our x/y bytes, opponent x byte, home y, serve-toss depth, which side of the net is ours
END = {0: dict(x=0x1A, y=0x18, opp=0x1B, home=142, toss=143, ours=lambda d: d > NET),
       1: dict(x=0x1B, y=0x19, opp=0x1A, home=7, toss=7, ours=lambda d: d < NET)}

def decide(r, DX, vd=0.0, dxa=None):
    dxa = dxa or DXA
    e = END[r[0x50] & 1]
    bx, bd, px, py = r[0x10], r[0x37], r[e["x"]], r[e["y"]]
    if dxa == "aim":
        if not e["ours"](bd): DX = AIM_R if r[e["opp"]] < MID else AIM_L   # decide while the ball is on their side
    else: DX = float(dxa)
    if bd == e["toss"]: DX = DX_SERVE
    tx = bx + DX
    ty = bd + vd * LEAD + float(DYA) if DYA != "none" and e["ours"](bd) else e["home"]   # ball on our side: meet it; else go home
    btns = []
    if px < tx - DEAD: btns.append("right")
    elif px > tx + DEAD: btns.append("left")
    if DYA != "none":
        if py < ty - DEAD: btns.append("up")
        elif py > ty + DEAD: btns.append("down")
    return btns, DX

if __name__ == "__main__":
    ra, pad = RA(timeout=0.2), Pad()
    if "PAUSED" in (ra.cmd("GET_STATUS") or ""): ra.cmd("PAUSE_TOGGLE", reply=False)
    log = open(LOG, "w") if LOG else None
    t0 = time.time(); n = 0; DX = -4; prev = None; set_over = None
    try:
        while time.time() - t0 < T:
            r = ra.ram(0x80, 128)
            if not r: continue
            vd = 0.0 if prev is None or abs(r[0x37] - prev) > 10 else r[0x37] - prev; prev = r[0x37]
            btns, DX = decide(r, DX, vd)
            if (n // 20) % 2 == 0: btns.append("b")  # fire on and off: serves when it is our serve, ignored otherwise
            gp, gb = r[0x47], r[0x48]
            if max(gp, gb) >= 6 and abs(gp - gb) >= 2:            # set over: the game waits for a reset
                set_over = set_over or time.time()
                if time.time() - set_over > 10: btns = ["start"]; set_over = None
            pad.hold(btns)
            if log: log.write("%.3f\t%s\t%s\n" % (time.time() - t0, "+".join(btns) or "-", r.hex()))
            n += 1; time.sleep(0.012)
    finally:
        pad.release_all()
        if os.environ.get("KEEP_RUNNING") != "1": ra.cmd("PAUSE_TOGGLE", reply=False)   # an idle player loses games
        if log: log.close()
    print("%d polls in %.0f s (%.0f Hz)" % (n, time.time() - t0, n / (time.time() - t0)))
