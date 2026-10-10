#!/usr/bin/env python3
# Contra (Konami, 1988; NES, fceumm) from RAM: the game's state for either player and a reflex soldier that plays one
# of them. The RAM map and the rules are the game's own, from the annotated disassembly (github.com/vermiceli/
# nes-contra-us, src/ram.asm and bank7.asm): the collision boxes, the background collision map and the two-player
# rules are ported, not guessed.
#
# RAM (NES CPU addresses; a pair is P1, P2): 18 game routine (5 = in a level), 22 two players, 24 the 30-lives code,
# 2C level routine (4 = playing), 30 level (0-7), 32/33 lives left, 38/39 game over, 40 indoor (1, 80 the boss
# screen), 41 vertical scrolling, 64/65 screen and pixels into it, 90/91 state (0 dropping in, 1 normal, 2 dead,
# 3 frozen), A0 jumping (low nibble), A2 causing the scroll, AA/AB weapon (low 3 bits: 0 rifle, 1 M, 2 F, 3 S, 4 L;
# bit 4 rapid), B2 in water, C6 vertical speed, D6 sprite (17 crouching), F1/F2 the pads, FC/FD scroll, FF PPUCTRL.
# 31A/31B the players' Y, 334/335 X (the point the game tests: the feet are 16 below it). Enemies, 16 slots: 324 Y,
# 33E X, 4B8 routine (0 = empty), 4E8/4F8 Y speed, 508/518 X speed (whole, fraction), 528 type (00 weapon item,
# 01 bullet, 02 pill box, 03 flying capsule, 05 soldier; 10+ belong to the level), 578 HP, 588 collision code (low
# 4 bits), 598 flags (bit 0: never touches the player). Indoors a crouching player is out of reach of bullets.
# 680: the background collision map (2 bits per 16x16 point: empty, floor, water, solid).
#
# Two players (bank7): the screen does not scroll while the other player stands left of x 0x21; on the vertical level
# the lower player is pulled down and dies off the screen; indoors the next room opens only when both are ready; a
# player who is game over and presses A takes a life from the other one. The soldier never presses A once it is out.
import math, os, socket, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# the game's collision boxes: [player pose][enemy collision code] = (dy, dx, height, width) added to the enemy's
# position; the player's point inside the box is a hit. Poses: 0 in water, 1 jumping, 2 crouching, 3 standing.
BOX = [
    [(0xf1, 0xf7, 0x28, 0x12), (0xfe, 0xf9, 0x14, 0x14), (0xf8, 0xf3, 0x1a, 0x1a), (0xf2, 0xed, 0x26, 0x26),
     (0xe0, 0xf0, 0x08, 0x20), (0xfd, 0xf8, 0x10, 0x10), (0xf5, 0xf7, 0x20, 0x12), (0xe7, 0xe2, 0x3c, 0x3c),
     (0xf1, 0xe2, 0x28, 0x3c), (0xe4, 0xd3, 0x48, 0x5a), (0x00, 0xf6, 0x16, 0x16), (0x08, 0xf1, 0x12, 0x1e),
     (0xf5, 0xf1, 0x20, 0x1e), (0xea, 0xec, 0x37, 0x28), (0xf3, 0xf3, 0x11, 0x1a)],
    [(0xea, 0xf8, 0x1e, 0x10), (0xf6, 0xfa, 0x0c, 0x0c), (0xf1, 0xf5, 0x12, 0x16), (0xea, 0xee, 0x24, 0x24),
     (0xe0, 0xf0, 0x08, 0x20), (0xf5, 0xf9, 0x0e, 0x0e), (0xed, 0xf8, 0x1e, 0x10), (0xdf, 0xe3, 0x3a, 0x3a),
     (0xe9, 0xe3, 0x26, 0x3a), (0xdc, 0xd4, 0x46, 0x58), (0xf8, 0xf7, 0x14, 0x14), (0x00, 0xf2, 0x10, 0x1c),
     (0xed, 0xf2, 0x1e, 0x1c), (0xe2, 0xed, 0x35, 0x26), (0xf3, 0xf1, 0x12, 0x1e)],
    [(0xf4, 0xf1, 0x0d, 0x1e), (0xf3, 0xf4, 0x04, 0x18), (0xec, 0xed, 0x10, 0x26), (0xe6, 0xe7, 0x1c, 0x32),
     (0xe0, 0xf0, 0x08, 0x20), (0xf1, 0xf2, 0x06, 0x1c), (0xe9, 0xf1, 0x16, 0x1e), (0xdb, 0xdc, 0x32, 0x48),
     (0xe5, 0xdc, 0x1e, 0x48), (0xd8, 0xcd, 0x3e, 0x66), (0xf4, 0xf0, 0x19, 0x22), (0xfc, 0xeb, 0x08, 0x2a),
     (0xe3, 0xf2, 0x1a, 0x1c), (0xde, 0xe6, 0x2d, 0x34), (0xe9, 0xea, 0x0d, 0x2c)],
    [(0xf3, 0xf8, 0x24, 0x10), (0xf0, 0xfb, 0x1f, 0x0a), (0xea, 0xf5, 0x2b, 0x16), (0xe3, 0xee, 0x39, 0x24),
     (0xe0, 0xf0, 0x08, 0x20), (0xee, 0xf9, 0x23, 0x0e), (0xe6, 0xf8, 0x33, 0x10), (0xd8, 0xe3, 0x4f, 0x3a),
     (0xe2, 0xe3, 0x3b, 0x3a), (0xd5, 0xd4, 0x5b, 0x58), (0xf1, 0xf7, 0x29, 0x14), (0xf9, 0xf2, 0x25, 0x1c),
     (0xe4, 0xf2, 0x35, 0x1c), (0xda, 0xed, 0x4a, 0x26), (0xe6, 0xf1, 0x2a, 0x1e)]]
WATER, JUMP, CROUCH, STAND = range(4)
EMPTY, FLOOR, H2O, SOLID = 0, 1, 2, 0x80
WEAPONS = {0: "rifle", 1: "machine gun (M)", 2: "fire gun (F)", 3: "spread gun (S)", 4: "laser (L)"}
ITEMS = {0: "rapid fire (R)", 1: "machine gun (M)", 2: "fire gun (F)", 3: "spread gun (S)", 4: "laser (L)",
         5: "barrier (B)", 6: "falcon"}
LEVELS = ["Jungle", "Base 1", "Waterfall", "Base 2", "Snow Field", "Energy Zone", "Hangar", "Alien's Lair"]
PLAYING = 4                  # level routine: playing the level
# the jump (measured on car8): screen y relative to the take-off, frame by frame; 58 frames, 59 px up at frame 29
JUMP_DY = [0, 0, -4, -8, -12, -15, -19, -22, -25, -28, -31, -33, -36, -38, -41, -43, -45, -47, -48, -50, -51, -53,
           -54, -55, -56, -57, -57, -58, -58, -59, -59, -59, -58, -58, -58, -57, -56, -55, -54, -53, -52, -51, -49, -47,
           -46, -44, -42, -39, -37, -34, -32, -29, -26, -23, -20, -17, -13, -10, -6, -2, 0]
# base corridors: what to shoot first (lower first): soldiers at the front, then the wall's guns, then its core
LOW_WALL = 110               # a base target this low on the screen takes crouching shots (a core at 112: yes; 104: standing)
INDOOR_TARGETS = {0x15: 0, 0x16: 0, 0x18: 0, 0x17: 1, 0x13: 1, 0x14: 2, 0x10: 2}

def sb(v): return v - 256 if v > 127 else v

class State:
    """one poll of the game's RAM: z 00-FF, s 300-3FF, e 4B8-5B7, c 680-6FF"""
    def __init__(self, z, s, e, c): self.z, self.s, self.e, self.c = z, s, e, c

    # the game
    def playing(self): return self.z[0x18] == 5 and self.z[0x2c] == PLAYING
    def level(self): return self.z[0x30]
    def two(self): return self.z[0x22] == 1
    def indoor(self): return self.z[0x40] != 0
    def vertical(self): return self.z[0x41] == 1
    def frame(self): return self.z[0x1a]

    # a player (0 or 1)
    def x(self, i): return self.s[0x34 + i]
    def y(self, i): return self.s[0x1a + i]
    def pstate(self, i): return self.z[0x90 + i]
    def alive(self, i): return self.z[0x90 + i] == 1 and not self.z[0x38 + i]
    def lives(self, i): return self.z[0x32 + i]
    def over(self, i): return self.z[0x38 + i] != 0
    def jumping(self, i): return self.z[0xa0 + i] & 0x0f != 0
    def in_water(self, i): return self.z[0xb2 + i] != 0
    def crouched(self, i): return self.z[0xd6 + i] == 0x17
    def weapon(self, i): return self.z[0xaa + i] & 0x07
    def rapid(self, i): return self.z[0xaa + i] & 0x10 != 0
    def invincible(self, i): return self.z[0xae + i] != 0 or self.z[0xb0 + i] != 0
    def pose(self, i):
        if self.in_water(i): return WATER
        if self.jumping(i): return JUMP
        return CROUCH if self.crouched(i) else STAND

    # enemies
    def slots(self): return [k for k in range(16) if self.e[k]]
    def ex(self, k): return self.s[0x3e + k]
    def ey(self, k): return self.s[0x24 + k]
    def etype(self, k): return self.e[0x70 + k]
    def ehp(self, k): return self.e[0xc0 + k]
    def ecode(self, k): return self.e[0xd0 + k] & 0x0f
    def eflags(self, k): return self.e[0xe0 + k]
    def eattr(self, k): return self.e[0xf0 + k]
    def evx(self, k): return sb(self.e[0x50 + k]) + self.e[0x60 + k] / 256
    def evy(self, k): return sb(self.e[0x30 + k]) + self.e[0x40 + k] / 256
    def harmful(self, k):
        """can enemy k touch (kill) a player? (a weapon item touches to be taken)"""
        return self.e[k] and self.etype(k) != 0x00 and not self.eflags(k) & 1 and self.ecode(k) != 0x0f

    def bg(self, x, y):
        """the background at screen point (x, y): EMPTY, FLOOR, H2O or SOLID (the game's get_bg_collision)"""
        if not 0 <= y < 0xe0 or not 0 <= x < 256: return EMPTY
        v = y + self.z[0xfc]
        if v >= 256: v = (v & 0xff) + 0x10
        elif v >= 0xf0: v = (v + 0x10) & 0xff
        h = x + self.z[0xfd]; nt = self.z[0xff] & 1
        if h >= 256: nt ^= 1; h &= 0xff
        b = self.c[((v >> 2) & 0x3c) | (h >> 6) | (0x40 if nt else 0)]
        return (EMPTY, FLOOR, H2O, SOLID)[(b >> (6 - 2 * ((h >> 4) & 3))) & 3]

def hits(st, k, px, py, pose, t=0, v=None):
    """does enemy k, t frames from now on its course (v: (vx, vy) a frame, else its RAM speed), touch a player at
    (px, py) in this pose?"""
    dy, dx, h, w = BOX[pose][st.ecode(k)]
    vx, vy = v if v else (st.evx(k), st.evy(k))
    ex = st.ex(k) + vx * t; ey = st.ey(k) + vy * t
    return 0 <= py - (ey + sb(dy)) < h and 0 <= px - (ex + sb(dx)) < w

def read(ra):
    """a State from four pipelined reads (RetroArch answers them all within a frame; 256 bytes is its limit)"""
    ra.s.setblocking(False)
    try:
        while True: ra.s.recv(65536)
    except (BlockingIOError, socket.error): pass
    ra.s.settimeout(0.2)
    want = [(0x000, 256), (0x300, 256), (0x4b8, 256), (0x680, 128)]
    for a, n in want: ra.s.sendto(("READ_CORE_MEMORY %x %d" % (a, n)).encode(), ra.addr)
    got = {}
    try:
        while len(got) < len(want):
            p = ra.s.recv(65536).decode(errors="replace").split()
            if len(p) > 2: got[int(p[1], 16)] = p[2:]
    except (socket.timeout, ValueError): return None
    out = []
    for a, n in want:
        p = got.get(a)
        if not p or len(p) != n: return None
        out.append(bytes(int(x, 16) for x in p))
    return State(*out)

class Soldier:
    """a reflex player for player i (0 or 1): dodges what its collision boxes say will hit it, jumps pits, aims at the
    nearest enemy and fires. Where it goes is set from outside: goal (screen x to keep near), and pickup (go for a
    weapon item) or not."""
    H = 36                       # frames ahead it looks for a hit (a boss's spread falls ~48 frames)

    def __init__(self, i):
        self.i = i; self.goal = 0x70; self.pickup = True; self.fire_t = 0; self.face = 1; self.note = ""
        self.jump_t = -99; self.n = 0; self.target = None; self.jump_d = 0
        self.seen = {}; self.vel = {}
        self.ceiling = 0             # the vertical level: never jump to rise above this screen y (0: no limit)
        self.climb_x = None   # slot -> (type, x, y, frame) last poll; slot -> (vx, vy) a frame

    def track(self, st):
        """each enemy's speed: its RAM speed, or what it moved since the last poll (rollers and others that move
        by their own rules show 0 in RAM)"""
        f = st.frame(); seen = {}; vel = {}
        for k in st.slots():
            t, x, y = st.etype(k), st.ex(k), st.ey(k); seen[k] = (t, x, y, f)
            vx, vy = st.evx(k), st.evy(k)
            p = self.seen.get(k)
            if (vx, vy) == (0, 0) and p and p[0] == t and 0 < (f - p[3]) % 256 <= 4:
                n = (f - p[3]) % 256; ox, oy = self.vel.get(k, (0, 0))
                vx = 0.5 * ox + 0.5 * sb((x - p[1]) & 0xff) / n; vy = 0.5 * oy + 0.5 * sb((y - p[2]) & 0xff) / n
            vel[k] = (vx, vy)
        self.seen, self.vel = seen, vel

    def first_hit(self, st, pose, path, bullets=True):
        """the first frame (0..H-1) an enemy on its course touches the player following path(t) -> (x, y) in this
        pose, or None. bullets=False: enemy bullets cannot touch this pose (crouching indoors)"""
        first = None
        for k in st.slots():
            if not st.harmful(k) or not bullets and st.etype(k) == 0x01: continue
            for t in range(self.H if first is None else first):
                x, y = path(t)
                if hits(st, k, x, y, pose, t, self.vel.get(k)): first = t; break
        return first

    def dodge(self, st, d):
        """the safest move for the next H frames: (name, d, crouch, jump), the plan (walk d) when it is clear"""
        i = self.i; px, py = st.x(i), st.y(i); indoor = st.z[0x40] == 1
        if st.in_water(i):
            if self.first_hit(st, WATER, lambda t: (px + d * t, py)) is None: return "plan", d, False, False
            return "dive", 0, True, False                  # crouching in water: out of reach of everything
        opts = [("plan", d, False, False), ("crouch", 0, True, False), ("jump", d, False, True),
                ("back", -(d or self.face), False, False), ("on", d or self.face, False, False),
                ("jump back", -(d or self.face), False, True)]
        best = None
        for name, dd, crouch, jump in opts:
            if jump and (self.n - self.jump_t < 6 or st.jumping(i)): continue
            if crouch: t = self.first_hit(st, CROUCH, lambda t: (px, py), bullets=not indoor)
            elif jump: t = self.first_hit(st, JUMP, lambda t: (px + dd * t, py + JUMP_DY[min(t, len(JUMP_DY) - 1)]))
            else: t = self.first_hit(st, STAND, lambda t: (px + dd * t, py))
            if t is None: return name, dd, crouch, jump
            if best is None or t > best[0]: best = (t, name, dd, crouch, jump)
        return best[1:]

    def pit_ahead(self, st, d):
        """walking d (+1/-1) leads off an edge with nothing below to land on"""
        i = self.i; px, py = st.x(i), st.y(i); feet = py + 0x10
        for look in (6, 12, 18):
            x = px + d * look
            if not 0 <= x < 256: return False
            if st.bg(x, feet) != EMPTY: continue
            return not any(st.bg(x, yy) != EMPTY for yy in range(feet + 16, 0xe0, 8))
        return False

    def pick_target(self, st, way=0):
        """the enemy to shoot: the nearest, ahead first. way: the direction it is going (+1/-1, 0 standing): a still
        enemy behind it is left behind (a closed pill box behind held both players for minutes)"""
        i = self.i; px, py = st.x(i), st.y(i); best = None
        for k in st.slots():
            t = st.etype(k)
            if t in (0x00, 0x01) or st.ehp(k) == 0: continue
            still = self.vel.get(k, (0, 0)) == (0, 0)
            if way and still and (st.ex(k) - px) * way < -24: continue
            if t == 0x02 and not 0 <= (st.ex(k) - px) * (way or self.face) < 100: continue
            if t == 0x03 and not self.pickup: continue          # a capsule: shoot it only to take what it carries
            ex, ey = st.ex(k), st.ey(k)
            if not (4 < ex < 252 and 8 < ey < 232): continue
            d = abs(ex - px) + 0.7 * abs(ey - py) + (40 if (ex - px) * self.face < 0 else 0)
            if best is None or d < best[0]: best = (d, k)
        return best[1] if best else None

    def item(self, st):
        """a weapon item on the screen (type 00): its slot, or None"""
        for k in st.slots():
            if st.etype(k) == 0x00 and 0 < st.ex(k) < 256: return k
        return None

    def ledge_above(self, st, x, feet):
        """the feet of a floor a jump from feet at x reaches (it rises 59 px), or None"""
        for yy in range(feet - 16, feet - 56, -4):
            if st.bg(x, yy) in (FLOOR, SOLID) and st.bg(x, yy - 8) == EMPTY: return yy
        return None

    def climb_target(self, st):
        """the vertical level: the best ledge a jump reaches, (x, feet), or None. Higher and nearer is better; none
        whose jump would rise above the ceiling (a scroll the other player may not survive)"""
        i = self.i; px, py = st.x(i), st.y(i); feet = py + 0x10
        if py - 59 < self.ceiling: return None
        best = None
        for x in range(8, 249, 4):
            for yy in range(feet - 56, feet - 11, 4):
                if st.bg(x, yy) in (FLOOR, SOLID) and st.bg(x, yy - 8) == EMPTY and st.bg(x, yy - 20) != SOLID:
                    score = yy + 0.4 * abs(x - px)
                    if best is None or score < best[0]: best = (score, x, yy)
                    break
        return best[1:] if best else None

    def climb(self, st, ty):
        """toward a point above (screen y ty, an item's centre): (x to walk to, jump now?)"""
        i = self.i; px = st.x(i); feet = st.y(i) + 0x10
        for off in sorted(range(-64, 65, 8), key=abs):
            x = px + off
            if 0 < x < 256 and self.ledge_above(st, x, feet) is not None: return x, abs(off) < 8
        return None, False

    def aim_at(self, st, k, grounded):
        """the aim (up, upfwd, fwd, low, downfwd, down) and side (+1/-1) to hit enemy k"""
        i = self.i; px, py = st.x(i), st.y(i)
        dx = st.ex(k) - px; dy = (py - 6) - st.ey(k)        # up is positive
        ang = math.degrees(math.atan2(dy, abs(dx) + 1e-3)); side = 1 if dx >= 0 else -1
        if ang > 65 or abs(dx) < 8 and dy > 0: return "up", side
        if ang > 22: return "upfwd", side
        if ang > -15: return ("low" if st.ey(k) > py + 6 and grounded and not st.in_water(i) else "fwd"), side
        if ang > -65 or grounded: return "downfwd", side
        return "down", side

    def step(self, st):
        """the buttons to hold this frame"""
        i = self.i; self.n += 1; self.note = ""; self.track(st)
        if not st.playing() or st.pstate(i) != 1 or st.over(i): return []   # never A when out: it takes a life
        if st.z[0x40] == 1: return self.step_indoor(st)
        px, py = st.x(i), st.y(i); grounded = not st.jumping(i)
        btn = set()

        # where to go: the goal, or a weapon item when it may take one
        goal = self.goal; k = self.item(st); up = False
        if k is not None and self.pickup:
            if st.ey(k) < py - 20:                           # above: climb toward it, or leave it
                if grounded and not st.in_water(i):
                    cx, up = self.climb(st, st.ey(k))
                    if cx is not None: goal = st.ex(k) if up else cx
            elif st.ey(k) < py + 40: goal = st.ex(k)
        d = 1 if goal > px + 6 else -1 if goal < px - 6 else 0
        if st.vertical() and not up:                          # the waterfall: up, ledge by ledge
            if grounded:
                c = self.climb_target(st); self.climb_x = None
                if c:
                    d = 1 if c[0] > px + 3 else -1 if c[0] < px - 3 else 0
                    if abs(c[0] - px) <= 14: up = True; self.climb_x = c[0]
                else: d = 0
            elif self.climb_x is not None:
                d = 1 if self.climb_x > px + 2 else -1 if self.climb_x < px - 2 else 0
        if k is not None and not self.pickup and d and 0 <= (st.ex(k) - px) * d < 24 and abs(st.ey(k) - py) < 32:
            d = 0                                            # not walking into a weapon left for the other player

        # aim at the nearest enemy; a diagonal shot walks
        k = self.pick_target(st, d); self.target = k; aim = None
        if k is not None:
            aim, side = self.aim_at(st, k, grounded)
            if aim == "up" and abs(st.ex(k) - px) > 5 and grounded: aim = None; d = side    # under it first
            elif aim in ("upfwd", "downfwd") and d == 0: d = side
            elif d == 0 and side != self.face: d = side          # turn round (a frame's step)
            self.face = d or self.face
        else: self.face = d or self.face

        # danger: the move that stays clear for H frames
        jump = False
        if grounded or st.in_water(i):
            name, d2, crouch, jump = self.dodge(st, d)
            if name != "plan":
                self.note = name; d = d2
                if crouch: aim = "low"; d = 0
        if up and not jump and grounded: jump = True; self.note = "climb"
        # pits: jump over (on the ground, walking toward one)
        if grounded and d and not jump and self.pit_ahead(st, d): jump = True; self.note = "pit"
        if jump: btn.add("a"); self.jump_t = self.n; self.jump_d = d or self.face
        if not grounded and self.n - self.jump_t < 60 and self.jump_d and self.note not in ("back",) and not st.vertical():
            d = d or self.jump_d                                # keep the jump's direction in the air

        # the pad: walking direction and aim
        side = "right" if (d or self.face) > 0 else "left"
        if d: btn.add(side)
        if aim == "up": btn.add("up")
        elif aim == "upfwd": btn.update(("up", side))
        elif aim == "downfwd": btn.update(("down", side))
        elif aim == "down" and not grounded: btn.add("down")
        elif aim == "low" and grounded: btn.add("down"); btn.discard("right"); btn.discard("left")
        if self.fire(k): btn.add("b")
        return sorted(btn)

    def fire(self, k):
        """press and release B (the rifle shoots on each press), while there is something to shoot"""
        return (k is not None or self.n % 30 < 4) and (self.n // 2) % 2 == 0

    def step_indoor(self, st):
        """a base corridor: the player stays at the front and shoots into the screen. Crouching is out of reach of
        bullets; up walks into the next room once it is cleared (and electrocutes before)."""
        i = self.i; px, py = st.x(i), st.y(i); grounded = not st.jumping(i); btn = set()
        if st.z[0x37]: return ["up"]                         # cleared: on to the next room
        best = None
        for k in st.slots():
            t = st.etype(k)
            if t not in INDOOR_TARGETS or st.ehp(k) == 0: continue
            pri = INDOOR_TARGETS[t] * 256 + abs(st.ex(k) - px)
            if best is None or pri < best[0]: best = (pri, k)
        k = best[1] if best else None; self.target = k
        goal = self.goal; low = k is not None and st.ey(k) >= LOW_WALL
        if k is not None:     # shots fly from the gun toward a point 64 above it at x 128 (bank6): stand where it lines up
            gy = py - (0x0c if low else 0x18); goal = 128 + (st.ex(k) - 128) * 64 / max(st.ey(k) - (gy - 64), 8)
            goal = min(max(goal, 0x20), 0xe0)
        d = 1 if goal > px + 3 else -1 if goal < px - 3 else 0
        jump = False
        if grounded:
            name, d2, crouch, jump = self.dodge(st, d)
            if name != "plan":
                self.note = name; d = d2
                if crouch: btn.add("down"); d = 0
        if jump: btn.add("a"); self.jump_t = self.n
        elif low and d == 0 and grounded: btn.add("down")      # a low target takes crouching shots (and bullets miss)
        if d: btn.add("right" if d > 0 else "left")
        if self.fire(k): btn.add("b")
        return sorted(btn)
