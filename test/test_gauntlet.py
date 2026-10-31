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

# the follower: the way out of the deadlock is its own, with no model
f = g.Follower(3); f.last = st.pos(3); f.pressed = True; f.still = f.STUCK - 1
ok(f.step(st) == ["right"] and f.note == "give way", "pinned Elf gives way to the only free side")
ok(g.Follower(1).toward(st, (5, 6)) == ["up"], "a wall ahead: line up first")
ok(g.Follower(2).step(state([(112, 258), (0, 300), (112, 274), (0, 332)], WALLS)) == [], "beside the leader it stands still")
ok("down" in g.Follower(2).step(state([(112, 400), (0, 300), (112, 200), (0, 332)], WALLS)), "far from the leader it walks to it")
fh = g.Follower(3); fh.step(state(DEAD, WALLS, hp=[2000] * 4)); fh.pressed = True
fh.step(state(DEAD, WALLS, hp=[1999] * 4))
ok(fh.still == 1, "health falling is not moving")
leave = state([(0, 496), (0, 464), (0, 300), (0, 300)], [], exits=[(31, 0)])
ok(g.Follower(1).step(leave) != [] , "the leader on the exit: followers go in after it, however near")

# shooting
open_room = state([(100, 100), (0, 300), (0, 332), (0, 364)])
ok(g.aim(open_room, 0, [(150, 100, 0x2190)]) == ["b", "right"], "a monster to the right: fire right")
ok(g.aim(open_room, 0, [(140, 140, 0x2190)]) == ["b", "right", "down"], "on the diagonal: both directions")
ok(g.aim(open_room, 0, [(300, 100, 0x2190)]) is None, "out of reach: no shot")
behind = state([(64, 200), (0, 300), (0, 332), (0, 364)], [(r, 6) for r in range(32)])
ok(g.aim(behind, 0, [(120, 200, 0x2190)]) is None, "behind a wall: no shot")
fs = g.Follower(0); fs.pressed = True; fs.last = open_room.pos(0); fs.still = 5
ok(fs.step(open_room, 1, [(150, 100, 0x2190)]) == ["b", "right"] and fs.still == 0, "standing to shoot is not being stuck")
rec = bytearray(g.OBJ_END - g.OBJ_BASE); o = g.OBJ_FIRST - g.OBJ_BASE
rec[o:o + 2] = (300).to_bytes(2, "big"); rec[o + 2:o + 4] = (64).to_bytes(2, "big")
rec[o + 8:o + 10] = (0x41c6).to_bytes(2, "big")
ok(g.objects(bytes(rec)) == [(300, 64, 0x41c6)], "a monster's tile in another palette is a monster")
rec[o + 8:o + 10] = (0x050b).to_bytes(2, "big")
ok(g.objects(bytes(rec)) == [] and len(g.objects(bytes(rec), g.FIXTURE)) == 1, "a fixture's tile is not a monster")
rec[o + 8:o + 10] = (0x21c6).to_bytes(2, "big")
lv = g.Live(); m0 = bytes(rec)
ok(lv.update(m0, 10.0) == [], "first sight: not yet shown alive")
rec[o:o + 2] = (301).to_bytes(2, "big"); m1 = bytes(rec)
ok(lv.update(m1, 10.2) == [(301, 64, 0x21c6)], "a record that moved is a live monster")
ok(lv.update(m1, 11.0) != [] and lv.update(m1, 12.0) == [], "a record that stops changing is a dead one")
sp = g.Follower(0); foe = [(150, 100, 0x2190)]
for k in range(g.SPEND): sp.step(open_room, 1, foe)
ok(sp.step(open_room, 1, foe) == [] or sp.note != "shoot", "a spot that never dies is left alone")

# firing lines: a pillar two cells left of the target, as at the generators on the device
pil = state([(300, 112), (0, 400), (0, 432), (0, 464)], [(7, 27)])
fc = g.firing_cells(pil, (7, 29))
ok((7, 26) not in fc and (7, 28) not in fc, "no line through the pillar, and no shot from point blank")
ok(fc[(3, 29)] == ["b", "down"] and fc[(7, 31)] == ["b", "left"], "from above and from the right")
ok(fc[(5, 27)] == ["b", "right", "down"], "on the diagonal")
ok((4, 27) not in fc, "no cell off the eight directions")
on = state([(464, 48), (0, 400), (0, 432), (0, 464)], [(7, 27)])
ok(g.Follower(0).assault(on, (7, 29))[0] == ["b", "down"], "on a firing cell: fire down the line")
go = g.Follower(0); b, c = go.assault(state([(300, 48), (0, 400), (0, 432), (0, 464)], [(7, 27)]), (7, 29))
ok(b and "b" not in b and c in fc, "away from one: walk to the nearest")
drs = bytearray(st.grid); drs[20 * g.W + 6] = 0x08; drs[3 * g.W + 6] = 9; drs[4 * g.W + 6] = 9; drs[5 * g.W + 6] = 9
dst = g.State(st.m, bytes(drs))
ok(dst.solid(20, 6) and g.route(dst, (20, 2), (20, 8)) is None, "a closed door closes the way")
ok(g.route(dst, (20, 2), (20, 8), doors=True) is not None, "with a key the door is a way")

# the squad
sq = g.Squad((1, 2, 3))
gr = bytearray(rec); gr[o:o + 2] = (464).to_bytes(2, "big"); gr[o + 2:o + 4] = (112).to_bytes(2, "big"); gr[o + 8:o + 10] = (0x050b).to_bytes(2, "big")
sq.update(bytes(gr), 1.0)
ok(list(sq.gens) == [(7, 29)], "a generator on an exact cell")
walled = [(r, c) for r in range(5, 10) for c in range(27, 32) if r in (5, 9) or c in (27, 31)]
near = state([(400, 112), (300, 112), (300, 128), (300, 144)], walled)
sq.step(near, ("kill", (7, 29)), 2.0)
ok((7, 29) not in sq.gens or True, "a walk to a walled generator does not crash")
sealedg = bytearray(near.grid)
for c in range(32):
    for r in range(32):
        if r < 5 or r > 9 or c < 27: pass
for r in range(4, 11):
    for c in (26, 32 - 1): sealedg[r * g.W + c] = 9
for c in range(26, 32): sealedg[4 * g.W + c] = 9; sealedg[10 * g.W + c] = 9
sq2 = g.Squad((1, 2, 3)); sq2.update(bytes(gr), 1.0)
sq2.step(g.State(near.m, bytes(sealedg)), ("kill", (7, 29)), 2.0)
ok((7, 29) in sq2.dead, "a generator nobody can reach a line on is crossed off")
sq3 = g.Squad((1, 2, 3)); sq3.update(bytes(gr), 1.0)
held = state([(464, 48), (464, 48), (464, 48), (464, 48)])
sq3.hit[(7, 29)] = 1.0
sq3.step(held, ("kill", (7, 29)), 2.0); ok((7, 29) not in sq3.dead, "firing: not given up at once")
sq3.step(held, ("kill", (7, 29)), 6.0); ok((7, 29) in sq3.dead, "firing with no change for seconds: crossed off")

# the captain's question
import gauntlet_llm as cap
cg = bytearray(state(DEAD).grid)
for c in range(32): cg[28 * g.W + c] = 0x09
cg[31 * g.W + 31] = g.EXIT; cg[28 * g.W + 20] = 0x08; cg[2 * g.W + 3] = g.KEY
csq = g.Squad((1, 2, 3)); csq.gens = {(7, 12): 0x50b}; csq.active = {(7, 12): 0.0}; csq.now = 1.0
cst = g.State(state(DEAD).m, bytes(cg)); opt = cap.choices(cst, csq)
ok(opt[0][0] == ("kill", (7, 12)), "a near generator comes first")
ok(any(o[0][0] == "key" for o in opt) and not any(o[0][0] == "exit" for o in opt), "exit shut, no key held: get one")
ok(opt[-1][0] == ("follow",) and cap.rule(cst, csq) == ("kill", (7, 12)), "stay with player 1 is always there; the rule kills first")
mk = bytearray(cst.m); mk[g.STRIDE * 3 + g.OKEY] = 1; kst = g.State(bytes(mk), bytes(cg))
ok(any(o[1].startswith("OPEN") and "Elf" in o[1] for o in cap.choices(kst, csq)), "a key held: open the door, and who holds it")
ok(not any("Warrior" in o[1] and not o[1].startswith(("OPEN", "STAY")) for o in opt), "no choice orders Player 1 about")
ok(cap.pick("PICK C", 4) == 2 and cap.pick("pick", 4) is None and cap.pick("PICK F", 3) is None, "reading the answer")
ok(cap.still_good(kst, csq, ("kill", (7, 12))) and not cap.still_good(kst, csq, ("kill", (1, 1))), "a dead target's call has run out")
ok("Nobody has moved" in cap.facts(cst, csq, ["a"], "kill", 5, 3) and "blocked by" in cap.facts(cst, csq, ["a"], "kill", 5, 3), "frozen: the question names the blockers")

# a generator counts only while it makes monsters
act = g.Squad((1, 2, 3)); act.gens = {(7, 12): 0x50b, (8, 3): 0x502}; act.now = 100.0; act.active = {(7, 12): 95.0}
ok(act.alive_gens(state(DEAD)) == [(7, 12)], "a quiet record is not offered")
act.now = 120.0
ok(act.alive_gens(state(DEAD)) == [], "nor one that has gone quiet")
blv = g.Live(); rb = bytearray(g.OBJ_END - g.OBJ_BASE); po = g.OBJ_FIRST - g.OBJ_BASE
rb[po + 8:po + 10] = (0x21c6).to_bytes(2, "big"); rb[po:po + 2] = (100).to_bytes(2, "big"); rb[po + 2:po + 4] = (100).to_bytes(2, "big")
blv.update(bytes(rb), 1.0); rb[po:po + 2] = (300).to_bytes(2, "big"); blv.update(bytes(rb), 1.1)
ok(blv.births == [(300, 100)], "a record that jumps across the map is a new monster")
rb[po:po + 2] = (302).to_bytes(2, "big"); blv.update(bytes(rb), 1.2)
ok(blv.births == [], "one that walks is not")

# the pick: the player's pad goes to the hero's port
ok(g.remap(0).count("remap_port") == 0 and 'device_p1 = "1537"' in g.remap(0) and 'device_p2 = "0"' in g.remap(0), "Warrior: only the Team Player")
ok('input_remap_port_p1 = "2"' in g.remap(2) and 'input_remap_port_p3 = "0"' in g.remap(2), "Wizard: swap the ports as measured")
ok([g.pad_of(h, 2) for h in range(4)] == [2, 1, 0, 3], "the users that drive the heroes after the swap")
ok(all(g.pad_of(k, k) == 0 and sorted(g.pad_of(h, k) for h in range(4)) == [0, 1, 2, 3] for k in range(4)), "the player is always user 0")

# orders
for w, key in (("kill the generator", "kill"), ("destroy it", "kill"), ("get the key", "key"), ("open the door", "door"), ("unlock it", "door"),
               ("head for the exit", "exit"), ("stay with me", "follow"), ("come here", "follow"), ("hold on", "hold"), ("wait", "hold"),
               ("let's go", "go"), ("your call", "yourcall"), ("nice shot", None)):
    ok(cap.order_of(w) == key, "order: %r" % w)
csq.dead = set()
ok(cap.resolve("kill", cst, csq, 0) == ("kill", (7, 12)) and cap.resolve("key", cst, csq, 0) == ("key", (2, 3)), "an order finds its nearest target")
ok(cap.resolve("door", state(DEAD), g.Squad(), 0) is None, "nothing to act on: no call")
ok(g.Squad((1, 2, 3)).step(state(DEAD), ("hold",), 0) == {1: [], 2: [], 3: []}, "hold: they stand")
ok("Valkyrie, Wizard and Elf" in cap.system(0) and "Warrior, Valkyrie and Elf" in cap.system(2), "the question knows who the human plays")

wait = state([(100, 100), (0, 0), (0, 0), (0, 0)], hp=[2000, 2000, 0, 0])
ok(wait.joined(1) and not wait.alive(1) and wait.group() == [0], "joined, waiting at 0, 0: not yet in the level")

print("%d checks, %d failed" % (n, bad))
sys.exit(1 if bad else 0)
