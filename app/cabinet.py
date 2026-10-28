#!/usr/bin/env python3
# The look of autogamer's own screens (menu.py, picker.py, run.sh's messages): an arcade cabinet's instruction card,
# drawn in 24-bit colour on foot's cell grid (20pt on the Flip 2: 120 x 34 cells of 16 x 32 px). Laminate black, card
# yellow for the highlighted row and its card only, P1 red (you), P2 blue (the model), pixel letters (3 x 5, M N W
# wider) set with half blocks, so their pixels are square.
# `cabinet.py notice TITLE FILE [SECONDS]`: TITLE in pixel letters on a card, FILE's text under it, for SECONDS (8).
import os, shutil, sys, time

INK, CARD, P1, P2, PAPER, DIM, RULE = "#141210", "#f2c230", "#e23b2e", "#2f6fe0", "#f4efe2", "#8a8378", "#3a352f"
QUIET, KEY, CARDRULE = "#5c4a10", "#2b2620", "#b38b16"
DOT = {"ok": ("●", "#7fc46a", "#2e7d32"), "unsure": ("◐", "#e0a43a", "#8a4b00"), "miss": ("○", "#e2614f", "#a3241a"),
       "none": ("·", DIM, QUIET)}                     # (symbol, on the black, on the card)
FOOT = ["foot", "--app-id=autogamer", "-f", "monospace:size=20", "-o", "colors.background=" + INK[1:],
        "-o", "colors.foreground=" + PAPER[1:]]

FONT = {"A": ".#.|#.#|###|#.#|#.#", "B": "##.|#.#|##.|#.#|##.", "C": ".##|#..|#..|#..|.##", "D": "##.|#.#|#.#|#.#|##.",
        "E": "###|#..|##.|#..|###", "F": "###|#..|##.|#..|#..", "G": "###|#..|#.#|#.#|###", "H": "#.#|#.#|###|#.#|#.#",
        "I": "###|.#.|.#.|.#.|###", "J": "..#|..#|..#|#.#|.#.", "K": "#.#|#.#|##.|#.#|#.#", "L": "#..|#..|#..|#..|###",
        "M": "#...#|##.##|#.#.#|#...#|#...#", "N": "#..#|##.#|#.##|#..#|#..#", "O": "###|#.#|#.#|#.#|###",
        "P": "##.|#.#|##.|#..|#..", "Q": ".#.|#.#|#.#|##.|.##", "R": "##.|#.#|##.|#.#|#.#", "S": ".##|#..|.#.|..#|##.",
        "T": "###|.#.|.#.|.#.|.#.", "U": "#.#|#.#|#.#|#.#|###", "V": "#.#|#.#|#.#|#.#|.#.",
        "W": "#...#|#...#|#.#.#|##.##|#...#", "X": "#.#|#.#|.#.|#.#|#.#", "Y": "#.#|#.#|.#.|.#.|.#.",
        "Z": "###|..#|.#.|#..|###", "0": "###|#.#|#.#|#.#|###", "1": ".#.|##.|.#.|.#.|###", "2": "##.|..#|.#.|#..|###",
        "3": "##.|..#|.#.|..#|##.", "4": "#.#|#.#|###|..#|..#", "5": "###|#..|##.|..#|##.", "6": ".##|#..|###|#.#|###",
        "7": "###|..#|.#.|.#.|.#.", "8": "###|#.#|###|#.#|###", "9": "###|#.#|###|..#|##.", "!": "#|#|#|.|#",
        "'": "#|#|.|.|.", "-": "...|...|###|...|...", ".": ".|.|.|.|#", ",": ".|.|.|#|#", ":": ".|#|.|#|.",
        "/": "..#|..#|.#.|#..|#..", " ": "..|..|..|..|..", "?": "##.|..#|.#.|...|.#."}

def pixels(text):
    rows = [[] for _ in range(5)]
    for k, ch in enumerate(text):
        g = FONT.get(ch, FONT["?"]).split("|")
        for r in range(5): rows[r] += [p == "#" for p in g[r]] + ([False] if k < len(text) - 1 else [])
    return rows

def bigwidth(text): return len(pixels(text)[0])

def rgb(h): return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)

def wrap(s, w):
    out, line = [], ""
    for word in (p[k:k + w] for p in s.split() for k in range(0, len(p), w)):   # a word longer than a line breaks
        if line and len(line) + 1 + len(word) > w: out.append(line); line = word
        else: line = (line + " " + word).strip()
    return out + [line] if line else out

def bigwrap(text, w):
    """the words in lines of at most w cells of pixel letters"""
    out, line = [], ""
    for word in text.split():
        t = (line + " " + word).strip()
        if line and bigwidth(t) > w: out.append(line); line = word
        else: line = t
    return out + [line] if line else out

class Grid:
    """the screen as cells [char, fg, bg, bold], written out as ANSI, run by run"""
    def __init__(s, w=None, h=None):
        if w is None: w, h = shutil.get_terminal_size((120, 34))
        s.w, s.h = w, h; s.c = [[[" ", PAPER, INK, False] for _ in range(w)] for _ in range(h)]
    def fill(s, x, y, w, h, bg, ch=" ", fg=PAPER):
        for j in range(max(y, 0), min(y + h, s.h)):
            for i in range(max(x, 0), min(x + w, s.w)): s.c[j][i] = [ch, fg, bg, False]
    def put(s, x, y, text, fg, bg=None, bold=False):
        if 0 <= y < s.h:
            for k, ch in enumerate(text):
                if 0 <= x + k < s.w: s.c[y][x + k] = [ch, fg, bg or s.c[y][x + k][2], bold]
        return x + len(text)
    def right(s, x2, y, text, fg, bg=None, bold=False): return s.put(x2 - len(text), y, text, fg, bg, bold)
    def big(s, x, y, text, fg, scale=1):
        """pixel letters: 3 rows tall (half blocks), or at scale 2 five rows of 2-cell pixels, twice the size"""
        px = pixels(text)
        if scale == 2:
            for r, row in enumerate(px):
                for i, on in enumerate(row):
                    if on: s.fill(x + 2 * i, y + r, 2, 1, fg)
            return
        for r in range(0, 5, 2):
            bot = px[r + 1] if r < 4 else [False] * len(px[r])
            for i, top in enumerate(px[r]):
                ch = "█" if top and bot[i] else "▀" if top else "▄" if bot[i] else " "
                if ch != " ": s.put(x + i, y + r // 2, ch, fg)
    def rule(s, x, y, w, bg=INK, fg=RULE): s.fill(x, y, w, 1, bg, "─", fg)
    def caps(s, x, y, keys):
        """the button row: (cap, colour, label[, label colour]); colour P1 / P2 for the main keys, else KEY (a lit
        switch: its own colour, and DIM on the label when it is off)"""
        for cap, bg, lab, *fg in keys:
            x = s.put(x, y, " %s " % cap, PAPER if bg == KEY else "#ffffff", bg, True) + 1
            x = s.put(x, y, lab, fg[0] if fg else PAPER) + 4
        return x
    def ansi(s):
        out, now = ["\033[?7l"], None
        for y, row in enumerate(s.c):
            out.append("\033[%d;1H" % (y + 1))
            for ch, fg, bg, bold in row:
                if (fg, bg, bold) != now:
                    now = (fg, bg, bold)
                    out.append("\033[0;%s38;2;%d;%d;%d;48;2;%d;%d;%dm" % (("1;" if bold else ""), *rgb(fg), *rgb(bg)))
                out.append(ch)
        return "".join(out) + "\033[0m"

def header(sc, right=""):
    """AUTOGAMER in pixel letters over a rule, the tagline, and a quiet word on the right"""
    sc.big(4, 1, "AUTOGAMER", PAPER)
    if sc.w >= 90: sc.put(4 + bigwidth("AUTOGAMER") + 3, 2, "a small language model plays retro games", DIM)
    if right: sc.right(sc.w - 4, 2, right, DIM)
    sc.rule(4, 4, sc.w - 8)

def show(frame, last=None):
    """write a frame (only when it changed); returns it"""
    if frame != last: sys.stdout.write(frame); sys.stdout.flush()
    return frame

def start(): sys.stdout.write("\033[?25l\033[2J"); sys.stdout.flush()
def end(): sys.stdout.write("\033[0m\033[?7h\033[?25h\033[H\033[2J"); sys.stdout.flush()

def notice(title, text, secs=8.0):
    sc = Grid(); x0, x1 = 4, sc.w - 4
    header(sc)
    sc.fill(x0, 6, x1 - x0, sc.h - 9, CARD)
    y = 8
    for l in bigwrap(title.upper(), x1 - x0 - 6)[:2]: sc.big(x0 + 3, y, l, INK); y += 3
    y += 1
    for l in wrap(text, min(x1 - x0 - 6, 100))[:sc.h - 3 - y - 1]: sc.put(x0 + 3, y, l, INK); y += 1
    sc.put(4, sc.h - 2, "Closes in %d s" % round(secs), DIM)
    start(); show(sc.ansi()); time.sleep(secs); end()

if __name__ == "__main__" and sys.argv[1:2] == ["notice"]:
    notice(sys.argv[2], open(sys.argv[3]).read(), float(sys.argv[4]) if len(sys.argv) > 4 else 8)
