#!/usr/bin/env python3
# The games autogamer plays, and finding your copy of each. Autogamer brings no games: the player reads each game's
# memory at fixed addresses, which belong to one version (dump) of the game, so a ROM is matched by its CRC32: the
# whole file, or for the NES also without its 16-byte iNES header. Files named like the game are tried first, then
# every other file in the system's folder; a .zip is read without unpacking where its directory has the CRC. A file
# named like the game whose CRC is unknown is still used, marked unverified (another version may be misread).
# Usage: games.py status            every game: its ROM (or what to add), for install.sh
#        games.py shell GAME        SYS= CORE= ROM= ROM_OK= TITLE= for run.sh (ROM empty when there is none)
# Env: AG_ROMS (default /storage/roms)
import fnmatch, os, sys, zipfile, zlib

ROMS = os.environ.get("AG_ROMS", "/storage/roms")
EXTS = {"nes": (".nes",), "atari2600": (".a26", ".bin")}
SYSNAME = {"nes": "NES", "atari2600": "Atari 2600"}

# section: main (a model under pressure, the point of autogamer) or bonus. model: the language model it needs (None:
# a bot plays, no model); tts: it speaks. crc: the known dumps (lower-case hex; NES both headerless and with header).
GAMES = [
    dict(id="tetris-model", section="main", title="Tetris: the model decides", system="nes", core="fceumm",
         dump="Tetris (USA)", crc=("1394f57e", "6d72c53a"), model="e4b", tts=True,
         names=("Tetris (USA)*", "Tetris (Nintendo)*", "Tetris.*", "Tetris (*"),
         about=("The model picks where every piece goes, thinking while",
                "it falls. The level sets how much slow motion it gets;",
                "SELECT changes it during the game.")),
    dict(id="ntennis-model", section="main", title="NES Tennis: the model aims every return", system="nes", core="fceumm",
         dump="Tennis (Japan, USA)", crc=("d4d9e21a", "5f457c00"), model="e4b", tts=True,
         names=("Tennis (Japan, USA)*", "Tennis (USA)*", "Tennis.*", "Tennis (*"),
         about=("Forehand or backhand on every return, against the",
                "game's computer. Too late to decide, and it swings",
                "on impulse. SELECT changes the level.")),
    dict(id="excitebike-model", section="main", title="Excitebike: the model rides the turbo", system="nes",
         core="fceumm", dump="Excitebike (Nintendo, 1984)", crc=("49aeb3a6", "6faa4584"), model="e4b", tts=True,
         names=("Excitebike (Japan, USA)*", "Excitebike (USA)*", "Excitebike.*", "Excitebike (*"),
         about=("Turbo or cruise, against the qualifying time. Each call",
                "holds until the next: too slow to ease off, and the",
                "engine overheats. SELECT changes the level.")),
    dict(id="punchout-model", section="main", title="Punch-Out!!: the model runs the offence", system="nes",
         core="fceumm", dump="Mike Tyson's Punch-Out!! (Nintendo, 1987)", crc=("2c818014", "3df8e170"), model="e4b",
         tts=True, names=("Mike Tyson's Punch-Out!! (*", "Mike Tyson's Punch-Out!!.*", "Mike Tyson's Punch-Out!!*"),
         about=("Mac dodges by himself; the model calls when to pummel.",
                "Win and the next opponent comes out. SELECT changes",
                "the level.")),
    dict(id="tennis", section="main", title="Tennis (Atari 2600): commentated", system="atari2600", core="stella",
         dump="Tennis (Activision, 1981)", crc=("0a42515b",), model="e2b", tts=True,
         names=("Tennis (USA)*", "Tennis.*", "Tennis (*"),
         about=("A fast bot plays pink from the game's memory; the",
                "model calls every point out loud as it happens.")),
    dict(id="tennis-model", section="bonus", title="Tennis (Atari 2600): the model aims", system="atari2600",
         core="stella", dump="Tennis (Activision, 1981)", crc=("0a42515b",), model="e2b", tts=True,
         names=("Tennis (USA)*", "Tennis.*", "Tennis (*"),
         about=("The model aims every return. It seldom wins a point:",
                "a fair look at what a small model cannot do yet.")),
    dict(id="tetris", section="bonus", title="Tetris: the heuristic", system="nes", core="fceumm",
         dump="Tetris (USA)", crc=("1394f57e", "6d72c53a"), model=None, tts=False,
         names=("Tetris (USA)*", "Tetris (Nintendo)*", "Tetris.*", "Tetris (*"),
         about=("No model: a hand-written placement rule plays at full",
                "speed, to level 27 and beyond.")),
    dict(id="smb", section="bonus", title="Super Mario Bros.: the bot", system="nes", core="fceumm",
         dump="Super Mario Bros. (World)", crc=("d445f698", "3337ec46"), model=None, tts=False,
         names=("Super Mario Bros. (World)*", "Super Mario Bros..*", "Super Mario Bros. (USA)*",
                "Super Mario Bros. (Japan, USA)*"),
         about=("No model: a run-and-jump bot. It clears 1-1, then",
                "falls into the pits of 1-2.")),
]
BY_ID = {g["id"]: g for g in GAMES}

def _crc(data): return "%08x" % (zlib.crc32(data) & 0xffffffff)

def crcs(path, system, deep=True):
    """the CRCs of the ROM images in a file: a zip's directory CRC for each member, and with deep=True for the NES also
    the CRC without the iNES header (that reads the member, at most 1 MB)"""
    ext = EXTS[system]; out = []
    try:
        if path.lower().endswith(".zip"):
            with zipfile.ZipFile(path) as z:
                for i in z.infolist():
                    if not i.filename.lower().endswith(ext): continue
                    out.append("%08x" % i.CRC)
                    if deep and system == "nes" and i.file_size <= 1 << 20:
                        d = z.read(i)
                        if d[:4] == b"NES\x1a": out.append(_crc(d[16:]))
        elif path.lower().endswith(ext) and os.path.getsize(path) <= 1 << 22:
            d = open(path, "rb").read(); out.append(_crc(d))
            if system == "nes" and d[:4] == b"NES\x1a": out.append(_crc(d[16:]))
    except (OSError, zipfile.BadZipFile, NotImplementedError): pass
    return out

def find(g, roms=None):
    """(path, verified) of the game's ROM, or (None, False)"""
    d = os.path.join(roms or ROMS, g["system"])
    try: files = sorted(f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f)))
    except OSError: return None, False
    named = [f for p in g["names"] for f in files if fnmatch.fnmatchcase(f, p)]
    named = list(dict.fromkeys(named))
    for f in named:
        if set(crcs(os.path.join(d, f), g["system"])) & set(g["crc"]): return os.path.join(d, f), True
    for f in files:                     # renamed copies: the directory CRC only, no unpacking
        if f not in named and set(crcs(os.path.join(d, f), g["system"], deep=False)) & set(g["crc"]):
            return os.path.join(d, f), True
    return (os.path.join(d, named[0]), False) if named else (None, False)

def need(g):
    """what to add for this game, in a line"""
    return "Add your own %s for the %s to %s" % (g["dump"], SYSNAME[g["system"]], os.path.join(ROMS, g["system"]))

def q(s): return "'" + str(s).replace("'", "'\\''") + "'"

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "shell" and len(sys.argv) == 3 and sys.argv[2] in BY_ID:
        g = BY_ID[sys.argv[2]]; path, ok = find(g)
        print("SYS=%s CORE=%s ROM=%s ROM_OK=%s TITLE=%s NEED=%s" % (q(g["system"]), q(g["core"]), q(path or ""),
              q("1" if ok else ""), q(g["title"]), q(need(g))))
    elif cmd == "status":
        for g in GAMES:
            path, ok = find(g)
            st = "ok        " if ok else "unverified" if path else "MISSING   "
            print("  %s %-40s %s" % (st, g["title"], path if path else need(g)))
    else:
        sys.exit("usage: games.py status | games.py shell GAME (%s)" % ", ".join(BY_ID))
