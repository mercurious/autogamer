# Third-party software, models and games

This repository holds its own code (MIT, see `LICENSE`). A release tarball built by `build/build.sh` also contains:

| component | in the tarball as | upstream | licence |
|---|---|---|---|
| llamatalk: llama.cpp's `llama-server` and pockettts.cpp's `tts-server`, and the model downloader | `llamatalk/` | https://github.com/mercurious/llamatalk | MIT (its binaries: MIT, see `llamatalk/THIRD_PARTY.md`) |
| NES Pickleball: the cartridge (`pickleball.nes`, a homebrew ROM), its teammate sidecar and its mailbox contract | `pickleball/` | https://github.com/mercurious/nes-pickleball | MIT (the same author; the ROM's sound uses CC0 recordings and Pently, zlib: see its `CREDITS.md`) |

## Models

The installer downloads the models from Hugging Face (`llamatalk/models.txt`); none are redistributed here. Each has
its own licence or terms of use on its model card, which you accept by downloading it: Gemma 4 E2B and E4B
(`google/gemma-4-E2B-it-qat-q4_0-gguf`, `google/gemma-4-E4B-it-qat-q4_0-gguf`), Pocket TTS
(`Serveurperso/pocket-tts-GGUF`) and Qwen3-ASR-0.6B (`ggml-org/Qwen3-ASR-0.6B-GGUF`).

## What it uses but does not bring

- **RetroArch and its cores** (fceumm, stella), MangoHud, foot and sway: from ROCKNIX, as installed on the device.
- **The games.** No commercial game is included, downloaded or linked. You provide your own copies, dumped from
  cartridges you own. The RAM addresses in the players were found by watching the games' memory while they ran; no
  game code is included or derived. The one game in the tarball is NES Pickleball, the author's own homebrew (above).
