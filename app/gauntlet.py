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
# health (a binary word). The maze is 32 x 32 bytes from E246, row by row, 16 px cells, written there for each level:
# 00 floor, 09 wall, 04 exit. Other codes (doors, keys, treasure, food, generators) are not decoded yet.
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
MAZE, W = 0xe246, 32
FLOOR, WALL, EXIT = 0x00, 0x09, 0x04
CELL = BOX = 16
VIEW_H = 224                         # measured: the group's top to its bottom when the screen stopped them
VIEW_W = 208                         # the playfield's width on the screen; the side limit is not measured yet
STEP = 2                             # px a probe looks ahead
DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}

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
    def pos(self, i): return self.x(i), self.y(i)
    def cell(self, i): return cell_of(self.x(i), self.y(i))
    def group(self): return [i for i in range(4) if self.alive(i)]

    def code(self, r, c): return self.grid[r * W + c] if 0 <= r < W and 0 <= c < W else WALL
    def wall(self, r, c): return self.code(r, c) == WALL

    def exits(self): return [(i // W, i % W) for i in range(W * W) if self.grid[i] == EXIT]

    def hits_wall(self, x, y):
        """a player's box at x, y overlaps a wall cell"""
        return any(self.wall(r, c) for r in range(y // CELL, (y + BOX - 1) // CELL + 1)
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

def route(st, src, dst, avoid=()):
    """the cells from src to dst, walls and avoid closed, or None. avoid: cells other players stand in"""
    q = collections.deque([src]); prev = {src: None}; closed = set(avoid) - {src, dst}
    while q:
        c = q.popleft()
        if c == dst:
            path = []
            while c is not None: path.append(c); c = prev[c]
            return path[::-1]
        r, k = c
        for n in ((r, k + 1), (r + 1, k), (r, k - 1), (r - 1, k)):
            if n not in prev and n not in closed and (not st.wall(*n) or n == dst) and 0 <= n[0] < W and 0 <= n[1] < W:
                prev[n] = c; q.append(n)
    return None

def describe(st, names=PLAYERS):
    """one line a player: where it can go and what stops it, for the model's question"""
    def what(b): return b if isinstance(b, str) else names[b]
    lines = []
    for i in st.group():
        stop = ["%s blocked by %s" % (d, what(st.blocked(i, d))) for d in DIRS if st.blocked(i, d) is not None]
        lines.append("%s at %d,%d: %s; %s." % (names[i], st.x(i), st.y(i), "free " + ", ".join(st.free(i)) if st.free(i)
                                               else "cannot move", ", ".join(stop) or "nothing in the way"))
    return lines

def read(ra, grid=None):
    """one poll: the players, and the maze unless a grid is given. RetroArch answers one command a frame"""
    b = ra.ram(P_BASE, P_SIZE, "READ_CORE_RAM")
    if not b or len(b) < P_SIZE: return None
    if grid is None:
        grid = read_maze(ra)
        if grid is None: return None
    return State(_swap(b), grid)

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
