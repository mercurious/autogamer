#!/usr/bin/env python3
# gauntlet.py: reading the players, walls, routes and what blocks a player, on a made-up maze with the shape of the
# deadlock seen on the device (no game data). Usage: python3 test/test_gauntlet.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import gauntlet as g

n = bad = 0
def ok(cond, what):
    global n, bad
    n += 1; bad += not cond; print(("ok   " if cond else "FAIL ") + what)

def state(players, walls=(), hp=None, exits=()):
    m = bytearray(g.P_SIZE)
    for i, (x, y) in enumerate(players):
        o = g.STRIDE * i
        m[o + g.OX:o + g.OX + 2] = (x & 0xffff).to_bytes(2, "big")
        m[o + g.OY:o + g.OY + 2] = (y & 0xffff).to_bytes(2, "big")
        m[o + g.OHP:o + g.OHP + 2] = (2000 if hp is None else hp[i]).to_bytes(2, "big")
    grid = bytearray(g.W * g.W)
    for r, c in walls: grid[r * g.W + c] = g.WALL
    for r, c in exits: grid[r * g.W + c] = g.EXIT
    return g.State(bytes(m), bytes(grid))

# a wall down column 6 with a gap in rows 3-5, as on the device
WALLS = [(r, 6) for r in range(32) if not 3 <= r <= 5]
DEAD = [(112, 258), (80, 82), (112, 274), (80, 66)]      # Warrior, Valkyrie, Wizard, Elf
st = state(DEAD, WALLS)

ok(st.x(2) == 112 and st.y(2) == 274 and st.hp(0) == 2000, "players read at their stride")
ok(state([(-3, 5)] * 4).x(0) == -3, "coordinates are signed")
ok(st.cell(1) == (5, 5), "a player's cell is the one its middle is in")
ok(st.span() == (224, 48), "the group fills the screen")
ok(st.blocked(1, "right") == "wall", "2 px too low for the gap: the wall stops Valkyrie")
ok(st.blocked(1, "up") == 3, "Elf stops Valkyrie going up")
ok(st.blocked(3, "down") == 1, "Valkyrie stops Elf going down")
ok(st.blocked(3, "up") == "screen", "the screen stops Elf going up")
ok(st.blocked(2, "down") == "screen", "the screen stops Wizard going down")
ok(st.blocked(3, "right") is None, "the way out: Elf goes right")
ok(st.blocked(2, "up") == 0, "Warrior stands in Wizard's way up")
ok(st.blocked(0, "up") is None, "Warrior can step back up")
ok("right" in st.free(3) and "right" not in st.free(1), "free directions")
ok(any("blocked by Elf" in l for l in g.describe(st)), "the description names the blockers")

# the corner: right of a wall cell a player stops flush against it
wall = state([(192, 30)] * 1 + [(0, 300)] * 3, [(r, 13) for r in range(32)])
ok(wall.hits_wall(193, 30) and not wall.hits_wall(192, 30), "a 16 px box stops at x 192 before a wall at column 13")

# routes
p = g.route(st, (20, 2), (20, 8))
ok(p and p[0] == (20, 2) and p[-1] == (20, 8) and all(q[1] != 6 or 3 <= q[0] <= 5 for q in p), "a route goes through the gap")
ok(g.route(st, (20, 2), (20, 8), avoid=[(3, 6), (4, 6), (5, 6)]) is None, "players filling the gap close the route")
ok(g.route(st, (4, 5), (4, 7))[1] == (4, 6), "the route takes the free cell when it can")
ok(g.route(st, (20, 2), (20, 6)) is not None, "a target in a wall cell can be reached")
sealed = state(DEAD, [(r, 6) for r in range(32)])
ok(g.route(sealed, (20, 2), (20, 8)) is None, "no way through a sealed wall")
ok(state(DEAD, WALLS, exits=[(31, 1)]).exits() == [(31, 1)], "exits")

# the dead do not block or stretch the screen
hurt = state(DEAD, WALLS, hp=[2000, 2000, 0, 2000])
ok(hurt.group() == [0, 1, 3] and hurt.blocked(3, "up") is None, "a dead player is out of the group")

print("%d checks, %d failed" % (n, bad))
sys.exit(1 if bad else 0)
