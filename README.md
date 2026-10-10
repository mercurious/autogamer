# Autogamer

A small language model plays retro games on a handheld while you watch: it places Tetris pieces, picks tennis
strokes, runs a motocross engine, picks its moments to attack in a boxing ring, fights beside you as Player 2 in Contra, and calls a tennis match out loud. Everything runs on the device, a Retroid Pocket Flip 2 with ROCKNIX, with
no cloud and no account. The model is slow, so the games run in slow motion at a level you choose. That makes a
contest: at Hard it keeps up, at Expert the game runs at real speed and the model falls behind.

> **Autogamer brings no games.** You provide your own copy of each game, dumped from a cartridge you own; see
> [ROMs](#roms). This repository never contains, downloads or links to a game.

> **AI disclosure.** This project was written with Claude Code (Anthropic's Claude Opus 5.5). Most of the code and
> this README are model output, produced under the author's direction. The author chose what to build, ran it on the
> hardware and judged what was worth watching. Measurements were taken on the device named below. Treat it as a
> working prototype, not a finished product.

## The games

One **Autogamer** entry under Ports opens a menu:

| | game | who plays | what you watch |
|---|---|---|---|
| main | **Tetris: the model decides** (NES) | the model picks where every piece goes, thinking while it falls | whether it keeps the stack down; too late, and the piece drops low where it falls |
| main | **NES Tennis: the model picks the stroke** | the model picks forehand or backhand for every return | points won and lost against the game's computer; too late, and it swings on impulse |
| main | **Excitebike: the model rides the turbo** | a reflex rider steers, jumps and lands; the model calls turbo or cruise, each call holding until the next | the race clock against the qualifying time; too slow to ease off, and the engine overheats |
| main | **Punch-Out!!: the model runs the offence** | a reflex loop dodges every punch; the model calls pummel, body blows or wait whenever the opponent is open, in bullet time | the fight: win and the next opponent comes out; too late, and the opening is gone |
| main | **Contra: the model is Player 2** (NES) | you play Player 1 on the handheld; a reflex soldier plays Player 2 and the model makes a partner's calls: cover you, lead or hang back, take a weapon or leave it for you, borrow a life | how far you get together; a careless partner takes your spread gun or drags the screen away from you |
| main | **Tennis (Atari 2600): commentated** | a fast bot plays pink; the model commentates | every point called out loud, live, with the score |
| bonus | **Tennis (Atari 2600): the model aims** | the model aims every return | it seldom wins a point: what a small model cannot do yet |
| bonus | **Tetris: the heuristic** | a hand-written placement rule, no model | full-speed Tetris to level 27 and beyond |
| bonus | **Super Mario Bros.: the bot** | a run-and-jump bot, no model | it clears 1-1, then falls into the pits of 1-2 |

The model reads the game's memory, not the screen: the game's state (the stack, the ball, the score, the engine's
heat) is read from RAM through RetroArch's network commands and handed to the model as text, and its answer is pressed
on a virtual gamepad.
Small models cannot yet read a game frame reliably on this hardware (a look at the screen took ~20 s on the GPU and
located the ball no better than a guess).

### Levels

The model games have four levels, chosen on the screen while the model loads and changed at any time with **SELECT**:

| level | Tetris | Tennis | Excitebike | Punch-Out!! |
|---|---|---|---|---|
| Hard | the model has 2x its usual think time per piece | most shots answered in time | a call every second of race time | a human's 0.5 s to call an opening |
| Harder | 1.5x | about half | every 2 s | 0.75 s |
| Hardest (default) | 1.2x | few | every 3 s | 1 s |
| Expert | real time | real time | real time | real time |

The game runs in RetroArch's slow motion (the music slows and drops with it). Each session measures the model's think
time and the next one sets the speeds from it. Tetris starts at the NES level whose pieces fall in about the model's
think time, and speeds up every 10 lines as usual.

In Excitebike the turbo heats the engine by about 3.5 a second; at 32 it overheats and the bike stops for about 4 s,
while cruising cools it to 17. The model's call holds until its next one, so the time between calls decides how
finely it can run the turbo. Each question tells it how long its answer will take in race time and what each choice
would do to the temperature by then. Qualify (the 3RD time on the screen) and the next race starts; miss and it is
game over.

In Punch-Out!! Mac dodges every punch by himself (a reflex loop that knows when each one lands). The model runs the
offence: whenever the opponent is open, reeling after a dodge or standing off defence (from the bell on), the game
drops into bullet time (slow motion at the level's ratio) and the model calls PUMMEL (rapid jabs to the face until
they are blocked), BODY (rapid body blows) or WAIT, and while Mac has a star, STAR: the uppercut (START). Mac loses a
star each time he is hit and all of them when the round ends, so when to spend one is the model's call too. Each
question carries its record in that situation, tries, hits and blocks, which is how it learns where an opponent is
open: Glass Joe takes 5-6 head hits after a dodge and 3 while he stands, and blocks every body blow while he stands.
A call that comes after the opening has closed is wasted. Win and the next opponent comes out; lose and it is a
rematch; a third loss is game over.

Contra has no levels: you are playing too, so it runs in real time. The game starts itself with 2 players; you are
Player 1 on the handheld's controls and the model is Player 2 (on RetroArch's network remote pad). A reflex soldier
plays Player 2 from the game's memory: it dodges what the game's own collision boxes say would hit it, jumps pits,
climbs the waterfall ledge by ledge, aims and fires; in the bases it shoots into the screen and crouches under
bullets. The model makes the calls a partner makes, each standing until the next: COVER (stay right behind you),
LEAD (go ahead and clear the way) or REAR (hang back and watch behind); TAKE a weapon on the screen (otherwise it is
left for you); and when Player 2 is out of lives, BORROW one of yours (the game's own rule: a player who is out and
presses A takes a life from the other) or SIT OUT. Each question carries how you are doing (lives, lives lost in the
last minute, weapon, where you are) and its record with each call this stage: your lives and its own lost while the
call stood, and the screens gained. The record is also kept across games (`state/contra_record.json`, per stage and
call, and apart for games with the stand-in), and each question gives it as rates: what one session learns about
playing with you, the next is told. It keeps to the game's two-player rules: it never stands at the left edge while
you push on (the screen would not scroll) and on the waterfall it does not climb past the scroll line while you are
low on the screen (you would be pushed off the bottom). `AG_CT_KONAMI=1` enters the 30-lives code at the title;
`AG_CT_STANDIN=1` has a reflex soldier play Player 1 too, to watch without a partner.

## What to expect

Measured on a 12 GB Flip 2 (ROCKNIX 20261001), CPU only:

| | |
|---|---|
| Tetris, Gemma 4 E4B | 6.8 s per piece; at Hardest, a game lasted 7 minutes: 10 lines, NES level 3, 21 pieces placed by the model and 27 by the fallback when it was late |
| Tetris, Gemma 4 E2B | 3.9 s per piece, with weaker choices |
| NES Tennis, E4B | 3.7-3.9 s per stroke; a return leaves about 2 s of game time |
| Atari Tennis commentary, E2B | a point called 3.5-4 s after it ends, the winner right 10 times out of 10 |
| Atari Tennis, the bot | won a set 6-3 against the game's computer |
| Excitebike, E4B | 3.4-4.0 s per call; at Hardest it qualified on track 1 in 1:09.61 (the game's record was 1:16), 24 calls, about a third of the race on turbo, no overheat, one fall. Cruising only, the rider takes 72-91 s on the five tracks against qualifying times of 74-84 s: from track 3 on, the turbo decides |
| Punch-Out!!, E4B, 8 GB Flip 2 | 4.1 s per call; at Hardest it beat Glass Joe and Von Kaiser and reached Piston Honda: 34 pummels landed 96 hits, 36 punches dodged and none taken, 16 of 42 calls too late for their opening |
| frame pacing | the panel runs at 60 Hz during a game (put back after): 1 % of frames off the 16.7 ms cadence |
| loading | E4B is 5 GB: the first start after a boot reads it from the SD card (a minute or more); the game waits, paused |

Not yet tested: the 8 GB Flip 2 for the other games (Punch-Out!! ran there with E4B next to RetroArch), other handhelds, other ROCKNIX releases.

## Requirements

- A **Retroid Pocket Flip 2** (Snapdragon 865 / SM8250) with **ROCKNIX** and its sway session (foot, swaymsg,
  wlr-randr), RetroArch with the **fceumm** (NES) and **stella** (Atari 2600) cores, and Python 3: all part of
  ROCKNIX. Other SM8250 handhelds will likely work; other chips need other core numbers (`AG_RA_CPUS`).
- 12 GB of RAM tested; 8 GB untested.
- Storage: 3.7 GB for the models (8.8 GB with E4B, `--no-e4b` to skip it), unless another llamatalk app already has
  them; about 17 MB for the programs.
- Optional: MangoHud, for the bar across the top (fps, frame times, the model at work).

## Install

**Without ssh:** download [`Install-Autogamer.sh`](https://github.com/mercurious/autogamer/releases/latest/download/Install-Autogamer.sh)
and put it in the handheld's ports folder (`roms/ports`, over the network share or on the SD card). Refresh the game
list in EmulationStation and start **Install-Autogamer** from Ports, with WiFi on and the handheld on its charger. It
downloads the latest release, checks it, installs it next to the models of other llamatalk apps (or where there is
the most room) and downloads the models, full screen; a button closes it at the end. It then becomes
**Update-Autogamer**: start that to update.

**Over ssh:** download `autogamer-aarch64.tar.gz` from the latest [release](https://github.com/mercurious/autogamer/releases/latest)
(`sha256sum -c autogamer-aarch64.tar.gz.sha256` checks it). Then, on the handheld (over ssh), in a directory with room,
for example on the SD card:

```sh
tar xzf autogamer-aarch64.tar.gz && cd autogamer
./install.sh              # the models (if not already on the device), the Ports entry, and which ROMs it found
./install.sh --no-e4b     # without the larger model (Tetris, NES Tennis, Excitebike, Punch-Out!! and Contra then play with E2B)
```

Then refresh the game lists in EmulationStation and start **Autogamer** from Ports. The models go to
[llamatalk](https://github.com/mercurious/llamatalk)'s shared models directory: with
[Retro Voice Chat](https://github.com/mercurious/retro-voice-chat) installed, only E4B is downloaded.
`./install.sh --uninstall` removes the Ports entry; delete the directory to remove the rest (the models stay for
other apps: `llamatalk/models.sh path` says where).

To build a release: `build/build.sh` on an arm64 Linux machine with podman (it builds llamatalk at its pinned commit).
`build/release.sh` builds what is on `main`, checks the tarball and uploads it as a draft GitHub release `v<VERSION>`
(`DRY=1` builds and checks without uploading; `ENGINE=docker` builds with docker; `PREBUILT=1` uploads a tarball
built by `DRY=1` on a build server from the same commit).

## ROMs

Put your own copies in ROCKNIX's ROM folders, zipped or not (`.zip`, `.nes`, `.a26`; `.7z` is not read):

| game | folder | the version it was made for | CRC32 |
|---|---|---|---|
| Tetris (NES) | `roms/nes` | Tetris (USA) | `1394f57e` without the iNES header, `6d72c53a` with it |
| Tennis (NES) | `roms/nes` | Tennis (Japan, USA) | `d4d9e21a` without the header, `5f457c00` with it |
| Super Mario Bros. (NES) | `roms/nes` | Super Mario Bros. (World) | `d445f698` without the header, `3337ec46` with it |
| Excitebike (NES) | `roms/nes` | Excitebike (Nintendo, 1984) | `49aeb3a6` without the header, `6faa4584` with an old "DiskDude!" header |
| Mike Tyson's Punch-Out!! (NES) | `roms/nes` | Mike Tyson's Punch-Out!! (Nintendo, 1987) | `2c818014` without the header, `3df8e170` with it |
| Contra (NES) | `roms/nes` | Contra (Konami, 1988) | `f6035030` without the header, `c50a8304` with it |
| Tennis (Atari 2600) | `roms/atari2600` | Activision, 1981 | `0a42515b` |

The players read each game's memory at fixed addresses, which belong to one version of the game, so autogamer looks
for these checksums. A file named like the game is tried first, then every file in the folder (a renamed zip is found
from its directory, without unpacking). A file named like the game with another checksum is used but marked
unverified in the menu: another version may be misread. The menu and `install.sh` say which file each game uses, or
which one to add.

Autogamer never writes to your ROMs or your save states: it runs RetroArch with its own settings for that launch
only (network commands on, save-state autoload off) and keeps its level-change save states in its own folder.

## Controls

| where | button | action |
|---|---|---|
| menu | D-pad or left stick | choose a game |
| | A, B or START | play |
| | HOME | back to EmulationStation |
| level picker | up/down, A | choose the level, start (it starts by itself after 30 s) |
| in a game | SELECT | pause and change the level (SELECT again: carry on) |
| | HOME | end the game, back to the menu |

RetroArch's own hotkeys (HOME+START, HOME+X) still work.

## Settings

Environment variables for `app/autogamer.sh` or `app/run.sh` (set them in the Ports entry, or run from ssh):

| variable | meaning |
|---|---|
| `AG_GAME` | play this game (`tetris-model`, `ntennis-model`, `excitebike-model`, `punchout-model`, `tennis`, `tennis-model`, `tetris`, `smb`) without the menu |
| `AG_LEVEL` | the level, 0-3 (Hard to Expert), without the picker; `AG_PICK=0`: the last one, without the picker |
| `AG_MODELS`, `AG_ROMS` | the models directory (default: llamatalk's shared one), the ROM folders (default `/storage/roms`) |
| `AG_TETRIS_MODEL`, `AG_NTENNIS_MODEL`, `AG_EXCITEBIKE_MODEL`, `AG_PUNCHOUT_MODEL`, `AG_TENNIS_MODEL` | another model (gguf basename in the models directory) |
| `AG_TL_GAMELEVEL` | Tetris: the NES level to start at (default: from the model's think time) |
| `AG_NT_CPU` | NES Tennis: the game's own computer level, 1-5 (default 1) |
| `AG_EB_TRACK` | Excitebike: the track the series starts on, 1-5 (default 1) |
| `AG_VOICE`, `NR_TTS=0` | the Pocket TTS voice (default `alba`); no voice, captions only |
| `AG_HUD=0`, `AG_60HZ=0` | no MangoHud bar; leave the panel at 120 Hz |
| `AG_RA_CPUS`, `AG_RA_CFG` | RetroArch's cores (default 0-3); one more RetroArch config file |
| `AG_LLAMA` | another `llama-server` (for example a GPU build) |

Logs of the last run of each game are in `logs/`; think times and level choices in `state/`.

## Adding a game

A game is an entry in `app/games.py` (title, system, core, the dump's CRCs), a player script that reads its RAM and
presses buttons (`ra.py` and `pad.py`; `tetris_llm.py` and `ntennis_llm.py` show the model's turn, `level.py` and
`picker.py` the levels), and a case in `app/run.sh`. `tools/ramwatch.py` shows which RAM bytes change while you play;
`tools/corefps.py` measures the game's real speed from its frame counter. A good game for this has decisions a few
seconds apart, each one visible on the screen, and a clock that keeps running while the model thinks.

## Licence

MIT, see `LICENSE`. The runtime it bundles and the models it downloads have their own licences: see
`THIRD_PARTY.md`. Tetris, Tennis, Excitebike, Punch-Out!!, Contra and Super Mario Bros. are trademarks of their owners; autogamer is not affiliated
with or endorsed by them.
