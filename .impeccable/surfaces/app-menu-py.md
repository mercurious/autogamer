---
version: 1
slug: "app-menu-py"
primary_target: "app/menu.py"
related_targets: []
---

# Main menu (app/menu.py)

Scope: the game menu, a fullscreen foot terminal on the Flip 2 (120 x 34 cells at 20pt). Mode: operate. Audience:
the maintainer daily, new installers (missing ROMs and models), onlookers. Task: pick a game and start it; see what
the model does in it and what is missing. Constraints: stdlib Python, ANSI truecolor, gamepad only, reads only.

## Direction contract

THESIS: Each game's panel is the arcade cabinet's instruction card: who plays, how, and what the model does, on one
flat yellow card. It refuses the console launcher's grey list-plus-metadata pane and the green phosphor costume.

OWN-WORLD: Cabinet laminate black #141210 ground, card yellow #f2c230 reserved for the active row and its card, P1 red
#e23b2e (you), P2 blue #2f6fe0 (the model), paper #f4efe2 text, warm grey #8a8378 for quiet text. Big pixel
letters (3x5 half-block font) for the model's job; single-cell type for everything else. One status legend:
● ready, ◐ uncertain, ○ missing.

STORY: An onlooker reads the big line and understands what the model is doing; a new installer sees at once which
games need a ROM and where it goes; the daily user scans the list, presses A.

FIRST VIEWPORT: Header: AUTOGAMER in pixel letters, tagline, HUD state. Left 56 columns: MAIN and BONUS lists (status
dot, name, the model's job, system right-aligned); the active row lit yellow and running into the card. Right: the
card, edge to edge yellow: the job in pixel letters, player lines (1P/2P caps coloured by who plays), the about text,
voice orders when the game takes them, status rows at the card's foot. Bottom: button caps A PLAY, up/down GAME,
SELECT HUD BAR, HOME QUIT.

FORM: grounded candidate 4 of 7 (arcade instruction card and attract mode); seed:8d898b545ca78598. Signature move: the
active row and the card are one yellow field; idle 30 s starts attract mode, cycling the cards until a press.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
