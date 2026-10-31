#!/usr/bin/env python3
# Gauntlet IV (Tengen, 1993; Genesis, genesis_plus_gx) from RAM: the four players, the maze, routes through it, and
# what stops each player moving. The map below was read off the running game on car12, Gauntlet IV (USA, Europe),
# CRC32 3bf46dce.
#
# Four players need a Team Player, and RetroArch 1.22.2 ignores input_libretro_device_pN in an appended config: it
# takes effect from a per-game remap file only (auto_remaps_enable, input_remapping_directory, then
# "Genesis Plus GX/<ROM basename>.rmp"). Port 1 is 1537 (3-button Team Player) and port 2 is 0 (Empty): with port 2
# on Joypad Auto the fourth slot reads a fifth user. 4-WayPlay gives no third pad. Users 0-3 are then the Warrior,
# Valkyrie, Wizard and Elf slots, on network remote ports 55400-55403. The game's Options > Controller Test shows
# every pad's bits live.
#
# RAM (68k addresses, FF0000 + offset; READ_CORE_RAM gives the 64 KB work RAM word-swapped: the byte at A is at A^1).
# Player records repeat every 0x2C4: +0042 x, +0044 y (the top left of a 16 px box, world px, y grows down), +00F8
# health (a binary word), +0108 score, +010D keys held. The maze is 32 x 32 bytes from E246, row by row, 16 px cells, written there for each level:
# 00 floor, 09 wall, 04 exit; players stack on an exit, and the level ends only when all of them are on it (one alone waited 38 s). Other codes (doors, keys, treasure, food, generators) are not decoded yet.
#
# B fires and holding it stops a player walking. The objects are a table of 0x26-byte records (see OBJ_*): their
# attribute word is the sprite's, so the same monster shows in three palettes. A dead object's record stays, so a
# record's presence says nothing: Live counts only those that change. Cell code 1B is a key and 08 and 07 doors: a
# player spends a key on touching one, and a run of door cells goes at once, and a door stays shut for a player with no
# key. Generators are tile 0x50B and such: monsters appear beside them. Fire steps one down the tiles until it goes; four
# heroes took 2-3 s each. Its record can also stay after it dies, so one that does not change under fire is crossed off.
#
# All four players share one screen and cannot walk through each other. Each taking its own shortest route is how a
# group deadlocks: on Level 2 two players ran down a corridor until the screen stopped them at 224 px from the top of
# the highest player, which pinned that player, which stopped a third lining up with a gap. So blocked() names what
# stops each player, and that goes into the model's question. Health falls all the time: never read a change in it
# as a player moving.
import collections, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PLAYERS = ("Warrior", "Valkyrie", "Wizard", "Elf")
STRIDE = 0x2c4
P_BASE, P_SIZE = 0x0000, 0x0c00      # one read covers the four records
OX, OY, OHP = 0x42, 0x44, 0xf8
OKEY = 0x10d                         # keys held: up on a pickup, down on a door, for two players on the device
MAZE, W = 0xe246, 32
FLOOR, WALL, EXIT = 0x00, 0x09, 0x04
DOORS, KEY = (0x07, 0x08), 0x1b
CELL = BOX = 16
VIEW_H = 224                         # measured: the group's top to its bottom when the screen stopped them
VIEW_W = 208                         # the playfield's width on the screen; the side limit is not measured yet
STEP = 2                             # px a probe looks ahead
DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}

OBJ_BASE, OBJ_END, OBJ_SIZE = 0x8000, 0xa800, 0x26      # the objects: x at +0, y +2, sprite attribute +8
OBJ_FIRST = 0x8000 + (0x9dc0 - 0x8000) % OBJ_SIZE
TILES = 0x07ff                                          # the attribute's tile; the bits above are palette and priority
MONSTER = range(0x180, 0x300)                           # monsters' tiles, in any palette
FIXTURE = range(0x500, 0x520)                           # generators: still, on exact cells
REACH = 72                                              # px a player stops to shoot at
SPEND = 90                                              # polls a player shoots at one spot before leaving it
BIRTH, ACTIVE = 32, 15                                  # px from a generator a new monster counts as its own; seconds that lasts

def _swap(b): return bytes(b[i ^ 1] for i in range(len(b)))

def _sw(m, a):
    v = m[a] * 256 + m[a + 1]
    return v - 0x10000 if v & 0x8000 else v

class State:
    """one poll: m = the player records in the game's own (big-endian) order, grid = the maze (read less often)"""
    def __init__(self, m, grid): self.m = m; self.grid = grid

    def x(self, i): return _sw(self.m, STRIDE * i + OX)
    def y(self, i): return _sw(self.m, STRIDE * i + OY)
    def hp(self, i): return _sw(self.m, STRIDE * i + OHP)
    def alive(self, i): return self.hp(i) > 0
    def keys(self, i): return self.m[STRIDE * i + OKEY]
    def pos(self, i): return self.x(i), self.y(i)
    def cell(self, i): return cell_of(self.x(i), self.y(i))
    def group(self): return [i for i in range(4) if self.alive(i)]

    def code(self, r, c): return self.grid[r * W + c] if 0 <= r < W and 0 <= c < W else WALL
    def wall(self, r, c): return self.code(r, c) == WALL
    def solid(self, r, c): return self.code(r, c) == WALL or self.code(r, c) in DOORS

    def exits(self): return [(i // W, i % W) for i in range(W * W) if self.grid[i] == EXIT]

    def hits_wall(self, x, y):
        """a player's box at x, y overlaps a wall cell"""
        return any(self.solid(r, c) for r in range(y // CELL, (y + BOX - 1) // CELL + 1)
                   for c in range(x // CELL, (x + BOX - 1) // CELL + 1))

    def span(self, who=None):
        """the group's height and width on the screen, top of the highest to bottom of the lowest, in px"""
        who = self.group() if who is None else who
        if not who: return 0, 0
        ys, xs = [self.y(i) for i in who], [self.x(i) for i in who]
        return max(ys) - min(ys) + BOX, max(xs) - min(xs) + BOX

    def blocked(self, i, d):
        """what stops player i going d: None, "wall", "screen", or the other player's index"""
        dx, dy = DIRS[d]; x, y = self.x(i) + dx * STEP, self.y(i) + dy * STEP
        if self.hits_wall(x, y): return "wall"
        for o in self.group():
            if o != i and abs(self.x(o) - x) < BOX and abs(self.y(o) - y) < BOX: return o
        others = [o for o in self.group() if o != i]
        if dy and others:
            ys = [self.y(o) for o in others]
            if max(max(ys), y) - min(min(ys), y) + BOX > VIEW_H: return "screen"
        return None

    def free(self, i): return [d for d in DIRS if self.blocked(i, d) is None]

def cell_of(x, y): return (y + CELL // 2) // CELL, (x + CELL // 2) // CELL

def route(st, src, dst, avoid=(), doors=False):
    """the cells from src to dst, walls and avoid closed, or None. avoid: cells other players stand in. doors=True:
    through closed doors too (for whoever holds a key)"""
    block = st.wall if doors else st.solid
    q = collections.deque([src]); prev = {src: None}; closed = set(avoid) - {src, dst}
    while q:
        c = q.popleft()
        if c == dst:
            path = []
            while c is not None: path.append(c); c = prev[c]
            return path[::-1]
        r, k = c
        for n in ((r, k + 1), (r + 1, k), (r, k - 1), (r - 1, k)):
            if n not in prev and n not in closed and (not block(*n) or n == dst) and 0 <= n[0] < W and 0 <= n[1] < W:
                prev[n] = c; q.append(n)
    return None

EIGHT = {(0, 1): ("down",), (0, -1): ("up",), (1, 0): ("right",), (-1, 0): ("left",), (1, 1): ("right", "down"),
         (1, -1): ("right", "up"), (-1, 1): ("left", "down"), (-1, -1): ("left", "up")}

def clear_shot(st, x, y, tx, ty):
    """no wall or door between two boxes' middles, looked at every 4 px"""
    n = max(abs(tx - x), abs(ty - y)) // 4 + 1
    return not any(st.solid(*cell_of(x + (tx - x) * k // n, y + (ty - y) * k // n)) for k in range(1, n))

def firing_cells(st, target, reach=8):
    """{cell: buttons} where a shot flies down one of the eight directions into target, a cell, nothing solid between.
    Shots do not fly at any other angle, so a clear line alone does not make a hit"""
    out = {}
    for (dx, dy), press in EIGHT.items():
        for n in range(2, reach + 1):
            c = (target[0] - dy * n, target[1] - dx * n)
            between = (target[0] - dy * (n - 1), target[1] - dx * (n - 1))
            if st.solid(*c) or st.solid(*between): break
            out[c] = ["b"] + list(press)
    return out

def aim(st, i, foes, reach=None):
    """the buttons that shoot at the nearest foe in reach with a clear line, or None. Holding fire stops a player
    walking, so it holds only with a foe in reach: the eight directions, nearest to the line"""
    reach = reach or REACH; x, y = st.pos(i); best = None
    for fx, fy, _ in foes:
        d = max(abs(fx - x), abs(fy - y))
        if d <= reach and (best is None or d < best[0]) and clear_shot(st, x, y, fx, fy): best = (d, fx - x, fy - y)
    if not best: return None
    _, dx, dy = best; btn = ["b"]
    if abs(dx) * 2 >= abs(dy) and dx: btn.append("right" if dx > 0 else "left")
    if abs(dy) * 2 >= abs(dx) and dy: btn.append("down" if dy > 0 else "up")
    return btn

def describe(st, names=PLAYERS):
    """one line a player: where it can go and what stops it, for the model's question"""
    def what(b): return b if isinstance(b, str) else names[b]
    lines = []
    for i in st.group():
        stop = ["%s blocked by %s" % (d, what(st.blocked(i, d))) for d in DIRS if st.blocked(i, d) is not None]
        lines.append("%s at %d,%d: %s; %s." % (names[i], st.x(i), st.y(i), "free " + ", ".join(st.free(i)) if st.free(i)
                                               else "cannot move", ", ".join(stop) or "nothing in the way"))
    return lines

class Follower:
    """a reflex hero for player i: stays near the leader by a route around the others. Pressed and not moved for STUCK
    polls, it gives way: it walks a free direction for a moment, so whoever it was jammed against can pass. self.stuck
    counts the polls in a row it has been pinned, for the model's question. Position alone says whether it moved."""
    NEAR = 3          # cells from the leader that are close enough
    STUCK = 15        # polls pressed and not moved before giving way
    AWAY = 18         # polls of giving way

    def __init__(self, i):
        self.i = i; self.last = None; self.pressed = False; self.still = 0; self.stuck = 0; self.away = []; self.note = ""; self.spent = {}

    def toward(self, st, c):
        """the buttons for the next cell: along the route, or only lining up where the route's way is walled off"""
        x, y = st.pos(self.i); tx, ty = c[1] * CELL, c[0] * CELL; h = []; v = []
        if abs(tx - x) > 1: h.append("right" if tx > x else "left")
        if abs(ty - y) > 1: v.append("down" if ty > y else "up")
        if h and v:
            if st.hits_wall(x + DIRS[h[0]][0] * STEP, y): return v
            if st.hits_wall(x, y + DIRS[v[0]][1] * STEP): return h
        return h + v

    def shoot_close(self, st, foes, reach=40):
        """fire at what is close, unless this spot has had its share: a stale record must not hold a player"""
        i = self.i
        ok = [f for f in foes if self.spent.get(f[:2], 0) < SPEND]
        btn = aim(st, i, ok, reach)
        if not btn: return None
        near = min(ok, key=lambda f: max(abs(f[0] - st.x(i)), abs(f[1] - st.y(i))))
        self.spent[near[:2]] = self.spent.get(near[:2], 0) + 1
        self.note = "shoot"; self.pressed = False; self.last = st.pos(i); self.still = 0
        return btn

    def go(self, st, goal, foes=(), doors=False):
        """walk to a cell, shooting what is close, giving way when jammed"""
        i = self.i
        if not st.alive(i): self.note = "out"; self.pressed = False; return []
        shot = None if self.away else self.shoot_close(st, foes)
        if shot: return shot
        p = st.pos(i)
        self.still = self.still + 1 if self.pressed and p == self.last else 0
        self.stuck = self.stuck + 1 if self.still else 0
        self.last = p
        if self.away: self.note = "give way"; self.pressed = True; return [self.away.pop()]
        if self.still >= self.STUCK:
            ways = st.free(i); self.still = 0
            if ways: self.away = [ways[0]] * self.AWAY; self.pressed = True; return [self.away.pop()]
        me = st.cell(i); avoid = [st.cell(o) for o in st.group() if o != i]
        path = route(st, me, goal, avoid, doors) or route(st, me, goal, doors=doors)
        self.note = "go"
        btn = self.toward(st, path[1] if path and len(path) > 1 else goal)
        self.pressed = bool(btn)
        return btn

    def assault(self, st, target, foes=(), taken=()):
        """go to a cell with a true shot at target, a cell, and fire from it; shoot what is close on the way. taken:
        cells other players have. Returns (buttons, cell it fires from or walks to)"""
        i = self.i; me = st.cell(i); cells = firing_cells(st, target)
        if not cells: self.note = "no line"; return [], None
        x, y = st.pos(i)
        if me in cells and abs(me[1] * CELL - x) <= 3 and abs(me[0] * CELL - y) <= 3:
            self.note = "fire"; self.last = st.pos(i); self.still = 0; self.pressed = False
            return cells[me], me
        close = aim(st, i, foes, 40)
        if close: self.note = "shoot"; self.pressed = False; self.last = st.pos(i); self.still = 0; return close, me
        best = None
        for c in cells:
            if c in taken: continue
            p = route(st, me, c)
            if p and (best is None or len(p) < len(best)): best = p
        if not best: self.note = "no way"; return [], None
        p0 = st.pos(i); self.still = self.still + 1 if self.pressed and p0 == self.last else 0; self.last = p0
        if self.still >= self.STUCK * 2:         # jammed: fire ahead, something may be in the way
            self.still = 0; return ["b"] + self.toward(st, best[1] if len(best) > 1 else best[0])[:1], best[-1]
        self.note = "to the line"; btn = self.toward(st, best[1]) if len(best) > 1 else self.toward(st, best[0])
        self.pressed = bool(btn)
        return btn, best[-1]

    def step(self, st, leader=0, foes=()):
        i = self.i
        if not st.alive(i): self.note = "out"; self.pressed = False; return []
        shoot = None if self.away else aim(st, i, [f for f in foes if self.spent.get(f[:2], 0) < SPEND])
        if shoot:                             # standing to shoot is not being stuck
            near = min(foes, key=lambda f: max(abs(f[0] - st.x(i)), abs(f[1] - st.y(i))))
            self.spent[near[:2]] = self.spent.get(near[:2], 0) + 1
            self.note = "shoot"; self.pressed = False; self.last = st.pos(i); self.still = 0
            return shoot
        p = st.pos(i)
        self.still = self.still + 1 if self.pressed and p == self.last else 0
        self.stuck = self.stuck + 1 if self.still else 0
        self.last = p
        if self.away:
            self.note = "give way"; self.pressed = True
            return [self.away.pop()]
        me, lead = st.cell(i), st.cell(leader)
        if self.still >= self.STUCK:
            ways = st.free(i); self.still = 0
            if ways:
                def left(d):      # the way that leaves the shortest walk to the leader
                    c = (me[0] + DIRS[d][1], me[1] + DIRS[d][0]); path = route(st, c, lead)
                    return len(path) if path else W * W
                self.away = [min(ways, key=left)] * self.AWAY; self.note = "give way"; self.pressed = True
                return [self.away.pop()]
            self.note = "pinned"; self.pressed = False; return []
        avoid = [st.cell(o) for o in st.group() if o not in (i, leader)]
        path = route(st, me, lead, avoid) or route(st, me, lead)
        near = 0 if st.code(*lead) == EXIT else self.NEAR      # the level ends when all are on the exit: go in after
        if not path or len(path) <= near + 1:
            self.note = "with the leader"; self.pressed = False; self.stuck = 0; return []
        self.note = "follow"; btn = self.toward(st, path[1]); self.pressed = bool(btn)
        return btn

def read(ra, grid=None):
    """one poll: the players, and the maze unless a grid is given. RetroArch answers one command a frame"""
    b = ra.ram(P_BASE, P_SIZE, "READ_CORE_RAM")
    if not b or len(b) < P_SIZE: return None
    if grid is None:
        grid = read_maze(ra)
        if grid is None: return None
    return State(_swap(b), grid)

def read_objects(ra):
    b = ra.ram(OBJ_BASE, OBJ_END - OBJ_BASE, "READ_CORE_RAM")
    return _swap(b) if b and len(b) == OBJ_END - OBJ_BASE else None

def attr(m, a): return m[a + 8] * 256 + m[a + 9]

def objects(m, tiles=MONSTER):
    """(x, y, attribute) of the records with a tile in tiles, from read_objects(). A dead one's record stays"""
    out = []
    for a in range(OBJ_FIRST - OBJ_BASE, len(m) - OBJ_SIZE, OBJ_SIZE):
        if attr(m, a) & TILES in tiles:
            x, y = _sw(m, a), _sw(m, a + 2)
            if x > 0 and y > 0: out.append((x, y, attr(m, a)))
    return out

class Live:
    """the monsters that are really there. A dead monster's record stays in the table with its last position, so only
    a record that moved or changed frame in the last HOLD seconds counts"""
    HOLD = 1.5

    def __init__(self): self.seen = {}; self.births = []

    def update(self, m, now):
        out = []; self.births = []
        for a in range(OBJ_FIRST - OBJ_BASE, len(m) - OBJ_SIZE, OBJ_SIZE):
            if attr(m, a) & TILES not in MONSTER: self.seen.pop(a, None); continue
            x, y = _sw(m, a), _sw(m, a + 2); sig = (x, y, attr(m, a)); old = self.seen.get(a)
            if old is None:                      # a record seen for the first time has not shown it is alive
                self.seen[a] = (sig, now - self.HOLD - 1); continue
            if old[0] != sig:
                if max(abs(x - old[0][0]), abs(y - old[0][1])) > 24 and x > 0 and y > 0: self.births.append((x, y))
                self.seen[a] = (sig, now)
            if now - self.seen[a][1] < self.HOLD and x > 0 and y > 0: out.append((x, y, sig[2]))
        return out

class Squad:
    """the heroes on one call at a time, each standing until the next: ("follow",), ("kill", cell), ("key", cell),
    ("door", cell), ("exit", cell). update() keeps what is live: the monsters, and the generators, with any that
    has taken fire for GIVEUP seconds with no change crossed off (a destroyed one's record can stay)"""
    GIVEUP = 4.0

    def __init__(self, heroes=(1, 2, 3), leader=0):
        self.heroes = {i: Follower(i) for i in heroes}; self.leader = leader; self.live = Live()
        self.foes = []; self.gens = {}; self.dead = set(); self.hit = {}; self.killed = 0; self.active = {}; self.now = 0

    def update(self, m, now):
        self.foes = self.live.update(m, now)
        gens = {(y // CELL, x // CELL): a for x, y, a in objects(m, FIXTURE) if not x % CELL and not y % CELL}
        for c in self.gens:
            if c not in gens and c not in self.dead: self.killed += 1
        for c, a in gens.items():
            if self.gens.get(c) != a: self.hit[c] = now
        self.gens = {c: a for c, a in gens.items() if c not in self.dead}
        for x, y in self.live.births:            # a generator proves itself by making monsters
            for c in self.gens:
                if abs(c[1] * CELL - x) <= BIRTH and abs(c[0] * CELL - y) <= BIRTH: self.active[c] = now
        self.now = now

    def alive_gens(self, st, cells=9):
        """generators near the group that have made a monster lately, nearest first. Many records in the table are
        dead ones, and hunting those wandered the group round the map for 90 s on the device"""
        me = st.cell(self.leader if st.alive(self.leader) else st.group()[0]); now = self.now
        near = [c for c in self.gens if abs(c[0] - me[0]) <= cells and abs(c[1] - me[1]) <= cells
                and now - self.active.get(c, -ACTIVE) < ACTIVE]
        return sorted(near, key=lambda c: abs(c[0] - me[0]) + abs(c[1] - me[1]))

    def step(self, st, call, now=0):
        """{player: buttons} for this poll"""
        kind = call[0]; out = {}
        if kind == "kill":
            taken = []; firing = False
            for i, h in self.heroes.items():
                out[i], c = h.assault(st, call[1], self.foes, taken)
                if c: taken.append(c)
                firing = firing or h.note == "fire"
            if all(h.note == "no way" or h.note == "no line" or h.note == "out" for h in self.heroes.values()):
                self.dead.add(call[1]); self.gens.pop(call[1], None)        # behind a door: for later, or for never
            elif firing and now - self.hit.get(call[1], now) > self.GIVEUP: self.dead.add(call[1]); self.gens.pop(call[1], None)
            elif not firing: self.hit[call[1]] = now
        elif kind in ("key", "door"):
            who = min(self.heroes, key=lambda i: abs(st.cell(i)[0] - call[1][0]) + abs(st.cell(i)[1] - call[1][1]))
            if kind == "door":
                have = [i for i in self.heroes if st.keys(i)]
                who = have[0] if have else who
            for i, h in self.heroes.items():
                out[i] = h.go(st, call[1], self.foes, doors=kind == "door") if i == who else h.step(st, who, self.foes)
        elif kind == "exit":
            for i, h in self.heroes.items(): out[i] = h.go(st, call[1], self.foes, doors=True)
        else:
            for i, h in self.heroes.items(): out[i] = h.step(st, self.leader, self.foes)
        return out

def read_maze(ra):
    a = MAZE & ~1; n = (MAZE + W * W + 2 - a) & ~1
    b = ra.ram(a, n, "READ_CORE_RAM")
    if not b or len(b) < n: return None
    return _swap(b)[MAZE - a:MAZE - a + W * W]

if __name__ == "__main__":       # a look at the game from RAM: python3 gauntlet.py
    import time
    from ra import RA
    ra = RA(timeout=0.3)
    while True:
        st = read(ra)
        if st:
            print(" | ".join(describe(st)) + " | span %d x %d" % st.span(), flush=True)
        time.sleep(0.5)
