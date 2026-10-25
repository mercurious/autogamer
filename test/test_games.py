#!/usr/bin/env python3
# games.py: finding a ROM by CRC, on made-up "ROMs" (random bytes behind an iNES header) in a temp folder, and the
# game table's sanity. No real game is needed or read. Usage: python3 test/test_games.py
import os, random, re, sys, tempfile, zipfile, zlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import games

n = bad = 0
def ok(cond, what):
    global n, bad
    n += 1; bad += not cond; print(("ok   " if cond else "FAIL ") + what)

crc = lambda d: "%08x" % (zlib.crc32(d) & 0xffffffff)
rnd = random.Random(1)
body = bytes(rnd.getrandbits(8) for _ in range(4096)); nes = b"NES\x1a" + bytes(12) + body
a26 = bytes(rnd.getrandbits(8) for _ in range(2048))
T = tempfile.mkdtemp(); os.makedirs(os.path.join(T, "nes")); os.makedirs(os.path.join(T, "atari2600"))
def put_zip(system, name, member, data):
    with zipfile.ZipFile(os.path.join(T, system, name), "w", zipfile.ZIP_DEFLATED) as z: z.writestr(member, data)

def game(**kw):
    g = dict(id="t", section="main", title="T", system="nes", core="fceumm", dump="Test (USA)", model=None, tts=False,
             names=("Test (USA)*", "Test.*"), about=())
    g.update(kw); return g

put_zip("nes", "Test (USA).zip", "Test (USA).nes", nes)
p, v = games.find(game(crc=(crc(body),)), T)
ok(p and p.endswith("Test (USA).zip") and v, "named zip, headerless CRC: found, verified")
os.rename(os.path.join(T, "nes", "Test (USA).zip"), os.path.join(T, "nes", "my copy.zip"))
p, v = games.find(game(crc=(crc(body), crc(nes))), T)
ok(p and p.endswith("my copy.zip") and v, "renamed zip, headered CRC in its directory: found, verified")
p, v = games.find(game(crc=(crc(body),)), T)
ok(p is None, "renamed zip, only the headerless CRC known: not found (no unpacking of every file)")
put_zip("nes", "Test (USA) (Rev 1).zip", "Test.nes", nes[:-1] + b"x")
p, v = games.find(game(crc=(crc(body), crc(nes))), T)
ok(p and p.endswith("my copy.zip") and v, "a named zip of another version loses to a verified renamed one")
os.remove(os.path.join(T, "nes", "my copy.zip"))
p, v = games.find(game(crc=(crc(body), crc(nes))), T)
ok(p and p.endswith("(Rev 1).zip") and not v, "only another version: used, unverified")
open(os.path.join(T, "nes", "Test.nes"), "wb").write(nes)
p, v = games.find(game(crc=(crc(body),)), T)
ok(p and p.endswith("Test.nes") and v, "an unpacked .nes, headerless CRC: verified")
put_zip("atari2600", "Test (USA).zip", "Test.a26", a26)
p, v = games.find(game(system="atari2600", core="stella", crc=(crc(a26),)), T)
ok(p and v, "Atari 2600 zip: verified")
p, v = games.find(game(system="atari2600", crc=(crc(a26),)), os.path.join(T, "nowhere"))
ok(p is None and not v, "no system folder: none")
open(os.path.join(T, "nes", "Test (USA) broken.zip"), "wb").write(b"PK not a zip")
p, v = games.find(game(crc=("00000000",)), T)
ok(p is not None and not v, "a broken zip is skipped, not fatal")

H = tempfile.mkdtemp(); os.makedirs(os.path.join(H, "pickleball"))
pbnes = b"NES\x1a" + bytes(12) + bytes(rnd.getrandbits(8) for _ in range(4096))
pb = game(crc=(crc(pbnes[16:]), crc(pbnes)), bundled="pickleball/pickleball.nes", names=("Pickleball*",))
p, v = games.find(pb, T, H)
ok(p is None and not v, "a bundled game with no bundled file and no copy in the folder: none")
open(os.path.join(T, "nes", "Pickleball.nes"), "wb").write(pbnes)
p, v = games.find(pb, T, H)
ok(p and p.endswith("nes/Pickleball.nes") and v, "a bundled game: a copy in the ROM folder is used when the bundle is missing")
open(os.path.join(H, "pickleball", "pickleball.nes"), "wb").write(pbnes)
p, v = games.find(pb, T, H)
ok(p == os.path.join(H, "pickleball", "pickleball.nes") and v, "a bundled game: the bundled file first")
ok("reinstall" in games.need(pb), "a bundled game that is missing says to reinstall")

ids = [g["id"] for g in games.GAMES]
ok(len(ids) == len(set(ids)) == 12, "twelve games, unique ids")
ok([g["section"] for g in games.GAMES] == ["main"] * 9 + ["bonus"] * 3, "nine main games, then three bonus")
ok(all(g.get("bundled") == "pickleball/pickleball.nes" for g in games.GAMES if g["id"].startswith("pickleball")), "the pickleball games use the bundled ROM")
ok(all(re.fullmatch(r"[0-9a-f]{8}", c) for g in games.GAMES for c in g["crc"]), "CRCs are 8 lower-case hex digits")
ok(all(len(g["crc"]) == 2 for g in games.GAMES if g["system"] == "nes"), "NES games know the dump with and without header")
ok(all(len(g["about"]) <= 3 and all(len(l) <= 60 for l in g["about"]) for g in games.GAMES), "menu text fits 3 x 60")
ok(all(g["players"] and all(s in ("1P", "2P", "CPU", "") and w in ("you", "model", "bot", "game", "voices") and len(t) <= 34
                            for s, w, t in g["players"]) for g in games.GAMES), "the menu card's who-plays lines fit")
ok([g["id"] for g in games.GAMES if g.get("say")] == ["contra-coop", "sor2-coop", "pickleball-coop"],
   "voice orders on the menu card for the three games that take them")
print("%d/%d passed" % (n - bad, n)); sys.exit(1 if bad else 0)
