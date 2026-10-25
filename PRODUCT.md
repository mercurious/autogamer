# Product

<!-- impeccable:product-schema 1 -->

## Platform

handheld (not web): a fullscreen `foot` terminal window under sway on ROCKNIX, on a Retroid Pocket Flip 2
(1920x1080 screen), driven by the gamepad only (d-pad or left stick, A/B/START, SELECT, HOME).

## Stack

Stay in foot (the user's choice, 2026-10-25): Python 3 standard library writing ANSI to the terminal. 24-bit colour,
Unicode box and block characters and sixel images are available; no new runtime dependencies (no pygame, GTK or SDL).
The font and colours are passed on foot's command line in `app/autogamer.sh`, `app/run.sh` and `app/level.py`.

## Users

- The maintainer, daily: picking a game to test, tune or watch.
- New installers from GitHub: they need to see which ROMs and models are missing and what to add, and do not know the
  games or modes yet.
- Onlookers: people watching over a shoulder or on a demo; the menu has to explain the idea at a glance.

## Product Purpose

Autogamer lets a small language model play retro games on the handheld, with no cloud and no account. The menu is
the one entry under Ports: it lists the games (main, then bonus), says what the model does in each, whether the ROM
and model are present, and starts the chosen one. HOME returns to EmulationStation.

## Positioning

The model reads the game's memory, not the screen, and plays under real time pressure: it is slow, so the game runs
in slow motion at a level you choose, and at Expert it falls behind. Each game gives the model a different job: it
decides (Tetris), aims (Tennis), rides the turbo (Excitebike), runs the offence (Punch-Out!!), is Player 2 beside you
(Contra, Streets of Rage 2), talks as your partner (Pickleball) or commentates (Atari Tennis). Some modes need no
model: a bot or the cartridge plays.

## Operating Context

- Launched from EmulationStation's Ports; after a game ends (HOME) the menu comes back with that game highlighted.
- Before a model game starts, a level picker (`app/picker.py`) shows while the model loads; in a game, SELECT opens the
  level menu over it (`app/level.py`). Both are foot screens too.
- SELECT in the menu turns the MangoHud bar on or off for the games after.
- The device is held in the hands or shown to others; no touch, no keyboard.

## Capabilities and Constraints

- Game data comes from `app/games.py` (title, section, system, model, voice, ROM status, a 3 x 60 character "about").
- The user brings every commercial ROM; the menu must say exactly what is missing and where to put it, never offer a
  download. NES Pickleball is bundled.
- Models: Gemma 4 E4B (falls back to E2B), Pocket TTS voice; either may be missing.
- Game modes that need a missing ROM or model stay listed but cannot start; the menu says what is missing.

## Brand Commitments

- Name: Autogamer. Public repo under the pseudonymous `mercurious` identity; nothing may link it to another identity.
- Voice: plain, literal, measured English (see README); claims match what was measured on the device.
- Brings no commercial games; never shows, links or implies ROM sources. Game names and logos belong to their owners.

## Evidence on Hand

- The README's game table and level table (real behaviour and measurements).
- No screenshots, box art or title artwork are in the repo; commercial game art must not be added.

## Product Principles

1. Show what the model does, not what it is: each game's job for the model is the headline.
2. Honest status: missing ROMs, models and voices are stated plainly with the fix.
3. Glanceable from arm's length: the handheld is watched, often by more than one person.
4. Nothing slows the launch: the menu reads only, starts instantly and never grabs the pad.
