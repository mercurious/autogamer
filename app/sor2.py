#!/usr/bin/env python3
# Streets of Rage 2 (Sega, 1992; Genesis, genesis_plus_gx) from RAM: the game's state for both players, the enemies
# and the items, and a reflex fighter that plays one player. There is no disassembly to port: the map below was read
# off the running game on car12 (diffs under scripted pads) and checked against Action Replay codes and the old
# Streets of Rage Online hacking notes (object IDs).
#
# RAM (68k addresses, FF0000 + offset; RetroArch's READ_CORE_RAM gives the 64 KB work RAM word-swapped: the byte at A
# is at A^1). Objects of 0x100 bytes: EF00 player 1, F000 player 2, F100-F600 six enemy slots; then F700-F9FF six item
# slots of 0x80. In each: +00 routine (0 = empty; 2 stand/walk, 4 and 28 hit, 06/08 knocked out, 0A thrown, 0C/0E
# held by someone from the front/behind, 14 attacking, 1A/1C holding someone from the front/behind (B: knees, then
# a throw), 22 jumping), +06 sprite y (y minus height), +0C ID (below), +0E animation (bit 0: facing right),
# +20 x, +24 y (world px; y grows down the screen), +38 the weapon a player holds, +50 invincibility timer, +78 name
# (ASCII), +80 health (0x68 full, a word), +82 lives left after this one (punks: stars). FC03 game mode (0x18
# select, 0x14 in a stage), FC10 frame counter, FC22 the foreground plane's horizontal scroll (minus the
# camera's x: the screen's left edge in world px), FC3C time (BCD), FC6B difficulty, FD0F stage (0-7).
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE, SIZE = 0xef00, 0x1100          # one read a poll: EF00-FFFF (RetroArch answers one command a frame)
P1, P2 = 0, 1
PLAYERS = {0x00: "Max", 0x02: "Axel", 0x04: "Blaze", 0x06: "Skate"}
PUNKS = {0x08: "Galsia", 0x0a: "Donovan", 0x0c: "Jack", 0x0e: "Barbon", 0x10: "Electra", 0x12: "Y. Signal",
         0x14: "Fog", 0x16: "Ninja", 0x18: "Big Ben", 0x1a: "Hakuyo", 0x1e: "Raven", 0x20: "Jet", 0x22: "Zamza",
         0x24: "R. Bear", 0x26: "Abadede", 0x2c: "Oxygen", 0x30: "Mr. X", 0x32: "Shiva", 0x34: "Ninja",
         0x36: "Ninja", 0x3a: "Vehelits"}
WEAPONS = {0x3c: "knife", 0x3e: "pipe", 0x40: "kunai", 0x42: "katana", 0x44: "kunai", 0x46: "grenade"}
FOOD = {0x92: "apple", 0x94: "roast chicken"}
BONUS = {0x8c: "money bag", 0x8e: "gold bar", 0x90: "1UP"}
STAGES = ["the city streets", "the bridge", "the amusement park", "the baseball stadium", "the ship",
          "the beach and jungle", "the factory", "Mr. X's island fortress"]
FULL = 0x68
SCREEN_W = 320
DOWN = {0x04, 0x06, 0x08, 0x0a, 0x28}   # hit, knocked out, thrown
HELD = {0x0c, 0x0e}                  # someone has grabbed it
HOLDING = {0x1a, 0x1c}               # it has grabbed someone
FREE = {0x02, 0x14}                  # routines where the pad steers (stand/walk, attacking)

class State:
    """one poll: m = the 0x1100 bytes from EF00 in the game's own (big-endian) order"""
    def __init__(self, m): self.m = m

    def b(self, a): return self.m[a - BASE]
    def w(self, a): return self.m[a - BASE] * 256 + self.m[a - BASE + 1]
    def sw(self, a): v = self.w(a); return v - 0x10000 if v & 0x8000 else v

    # the game
    def mode(self): return self.b(0xfc03)
    def in_stage(self): return self.mode() == 0x14
    def selecting(self): return self.mode() == 0x18
    def frame(self): return self.w(0xfc10)
    def stage(self): return self.b(0xfd0f) & 7
    def cam(self): return -self.sw(0xfc22)
    def clock(self): v = self.b(0xfc3c); return (v >> 4) * 10 + (v & 15)

    # any object: slot base address
    def on(self, o): return self.w(o) != 0
    def routine(self, o): return self.w(o)
    def oid(self, o): return self.b(o + 0x0d)
    def x(self, o): return self.sw(o + 0x20)
    def y(self, o): return self.sw(o + 0x24)
    def z(self, o): return max(self.sw(o + 0x24) - self.sw(o + 0x06), 0)
    def right(self, o): return self.b(o + 0x0f) & 1
    def hp(self, o): return self.w(o + 0x80)
    def stars(self, o): return self.b(o + 0x83)
    def name(self, o):
        s = bytes(self.m[o - BASE + 0x78:o - BASE + 0x80]).split(b"\0")[0].decode("ascii", "replace").strip()
        return s.title() if s.isalpha() or " " in s or "." in s else PUNKS.get(self.oid(o), "punk")

    # players
    def p(self, i): return 0xef00 + 0x100 * i
    def joined(self, i): return self.on(self.p(i))
    def lives(self, i): return self.b(self.p(i) + 0x83)
    def php(self, i): return self.hp(self.p(i))
    def weapon(self, i): return WEAPONS.get(self.b(self.p(i) + 0x39))
    def who(self, i): return PLAYERS.get(self.oid(self.p(i)), "player %d" % (i + 1))
    def alive(self, i): return self.joined(i) and self.php(i) > 0
    def free(self, i): return self.routine(self.p(i)) in FREE

    # enemies and items
    def enemies(self):
        """the punks on the board: slot addresses with an ID in the punks' range and health left"""
        out = []
        for o in range(0xf100, 0xf700, 0x100):
            if self.on(o) and 0x08 <= self.oid(o) < 0x3c and self.hp(o) > 0: out.append(o)
        return out

    def items(self):
        """items lying on the ground: (slot, kind, name) for food, bonuses and weapons"""
        out = []
        for o in range(0xf700, 0xfa00, 0x80):
            if not self.on(o): continue
            k = self.oid(o)
            if k in FOOD: out.append((o, "food", FOOD[k]))
            elif k in BONUS: out.append((o, "bonus", BONUS[k]))
            elif k in WEAPONS: out.append((o, "weapon", WEAPONS[k]))
        return out

    def onscreen(self, o, margin=0):
        c = self.cam(); return c - margin <= self.x(o) <= c + SCREEN_W + margin

def read(ra):
    b = ra.ram(BASE, SIZE, "READ_CORE_RAM")
    if not b or len(b) < SIZE: return None
    return State(bytes(b[i ^ 1] for i in range(SIZE)))

def sign(v): return (v > 0) - (v < 0)

class Fighter:
    """a reflex brawler for player i: walks into a lane beside its target and works it over with combos, turns to
    face it, throws a special when it is boxed in (it costs a little health), steps out of a punch line, and walks over
    an item to pick it up. Whom it fights is set from outside: pick(st, enemies) -> slot or None. want: an item slot to
    go for (or None). home: (x, y) to keep near when there is nobody to fight (or None: follow the other player)."""
    REACH = (14, 34)              # x distance a punch lands at (px)
    LANE = 7                      # depth difference a punch still lands at (px)
    KICK = (40, 72)               # x distance a flying kick starts from, in the target's lane

    def __init__(self, i):
        self.i = i; self.pick = None; self.want = None; self.home = None; self.special = True
        self.n = 0; self.note = ""; self.target = None; self.mash = 0; self.special_t = 0
        self.tgt_t = 0; self.tgt_hp = None; self.ban = {}; self.stall = None; self.last = None
        self.seq = []; self.kick_t = 0; self.lead = False   # buttons queued a poll each (a flying kick); push on alone

    def me(self, st): return st.p(self.i)

    def friend_in_line(self, st, face):
        """the other player stands in the line of a punch (the game lets partners hit each other)"""
        o = st.p(1 - self.i); m = self.me(st)
        if not st.alive(1 - self.i): return False
        dx = st.x(o) - st.x(m)
        return abs(st.y(o) - st.y(m)) <= self.LANE + 3 and 0 < dx * face <= self.REACH[1] + 6

    def walk(self, st, gx, gy, slack=3):
        m = self.me(st); btn = []
        dx, dy = gx - st.x(m), gy - st.y(m)
        if abs(dx) > slack: btn.append("right" if dx > 0 else "left")
        if abs(dy) > 2: btn.append("down" if dy > 0 else "up")
        return btn

    def step(self, st):
        """the buttons for this poll"""
        self.n += 1; m = self.me(st); mx, my = st.x(m), st.y(m)
        if not st.alive(self.i): self.note = "out"; self.seq = []; return []
        if st.routine(m) in HOLDING:                   # a grab: knees, knees, throw
            self.note = "grab"; self.mash += 1; return ["b"] if self.mash % 6 < 3 else []
        if st.routine(m) in HELD:                      # grabbed: wriggle
            self.note = "held"; self.mash += 1; return [("left", "right")[self.mash // 3 % 2]]
        if st.routine(m) in DOWN: self.note = "down"; self.seq = []; return []
        if self.seq: return self.seq.pop(0)
        foes = [o for o in st.enemies() if st.onscreen(o, 8) and self.ban.get(o, 0) < self.n]
        # an item it was sent for
        if self.want is not None and st.on(self.want):
            o = self.want; dx, dy = st.x(o) - mx, st.y(o) - my
            close = [e for e in foes if abs(st.x(e) - mx) < 30 and abs(st.y(e) - my) < 8]
            if not close or abs(dx) < 24:
                self.note = "item"
                if abs(dx) <= 6 and abs(dy) <= 3:
                    self.mash += 1; return ["b"] if self.mash % 6 < 3 else []
                return self.walk(st, st.x(o), st.y(o), slack=2)
        t = self.pick(st, foes) if self.pick and foes else (foes and min(foes, key=lambda o: abs(st.x(o) - mx) + 2 * abs(st.y(o) - my)))
        if not t:
            self.target = None; self.note = "follow"
            if self.home: return self.walk(st, self.home[0], self.home[1], slack=10)
            o = st.p(1 - self.i)
            if self.lead or not st.alive(1 - self.i): return self.walk(st, st.cam() + 260, my, slack=6)
            if st.alive(1 - self.i):
                side = -1 if mx < st.x(o) else 1
                return self.walk(st, st.x(o) + side * 36, st.y(o) + (10 if my >= st.y(o) else -10), slack=14)
            return self.walk(st, st.cam() + 200, my, slack=20)
        # a target that takes no hits for a while (out of reach, on a ledge, behind something): leave it a bit
        if t != self.target: self.target = t; self.tgt_t = self.n; self.tgt_hp = st.hp(t)
        elif st.hp(t) < self.tgt_hp: self.tgt_hp = st.hp(t); self.tgt_t = self.n
        elif self.n - self.tgt_t > 600:
            self.ban[t] = self.n + 300; self.stall = dict(stall="no hits in 10 s", target=st.name(t), x=mx, y=my,
                                                          tx=st.x(t), ty=st.y(t)); self.tgt_t = self.n
        tx, ty = st.x(t), st.y(t); dx, dy = tx - mx, ty - my
        side = sign(mx - tx) or (1 if st.x(st.p(1 - self.i)) < tx else -1)
        crowd = [e for e in foes if abs(st.x(e) - mx) < 44 and abs(st.y(e) - my) < 10]
        if (self.special and len(crowd) >= 2 and st.php(self.i) > 24 and self.n - self.special_t > 120
                and st.free(self.i) and not self.friend_in_line(st, 1) and not self.friend_in_line(st, -1)):
            self.special_t = self.n; self.note = "special"; return ["y"]
        face = 1 if st.right(m) else -1
        if self.REACH[0] <= abs(dx) <= self.REACH[1] and abs(dy) <= self.LANE and st.z(t) < 20:
            want = sign(dx)
            if face != want: self.note = "turn"; return ["right" if want > 0 else "left"]
            if self.friend_in_line(st, face): self.note = "friend in line"; return self.walk(st, mx, ty + (12 if my > ty else -12))
            self.note = "hit"; self.mash += 1
            return ["b"] if self.mash % 4 < 2 else []
        if (self.KICK[0] <= abs(dx) <= self.KICK[1] and abs(dy) <= 3 and st.z(t) < 8 and self.n - self.kick_t > 90
                and st.routine(m) == 0x02 and not self.friend_in_line(st, sign(dx))):
            d = "right" if dx > 0 else "left"; self.kick_t = self.n; self.note = "flying kick"
            self.seq = [["a", d]] * 3 + [[d]] * 7 + [["b", d]] * 3 + [[d]] * 20
            return self.seq.pop(0)
        self.note = "close in"
        if abs(dy) > 3 and abs(dx) < 30:             # into its lane from out of its reach first
            return self.walk(st, tx + side * 40, ty, slack=4)
        return self.walk(st, tx + side * 24, ty, slack=4)

def nearest(st, foes, x, y):
    return min(foes, key=lambda o: abs(st.x(o) - x) + 2 * abs(st.y(o) - y)) if foes else None

if __name__ == "__main__":       # a look at the game from RAM: python3 sor2.py
    from ra import RA
    ra = RA(timeout=0.3)
    while True:
        st = read(ra)
        if st:
            out = ["mode %02x stage %d cam %d time %d" % (st.mode(), st.stage(), st.cam(), st.clock())]
            for i in (0, 1):
                o = st.p(i)
                out.append("P%d %s x%d y%d z%d hp%d lives%d r%02x %s" % (i + 1, st.who(i), st.x(o), st.y(o), st.z(o),
                           st.php(i), st.lives(i), st.routine(o), "R" if st.right(o) else "L"))
            for o in st.enemies():
                out.append("%s x%d y%d z%d hp%d r%02x" % (st.name(o), st.x(o), st.y(o), st.z(o), st.hp(o), st.routine(o)))
            for o, k, n in st.items(): out.append("%s %s x%d y%d" % (k, n, st.x(o), st.y(o)))
            print(" | ".join(out), flush=True)
        time.sleep(0.5)
