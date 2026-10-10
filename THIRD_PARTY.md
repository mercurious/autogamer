# Third-party software, models and games

This repository holds its own code (MIT, see `LICENSE`). A release tarball built by `build/build.sh` also contains:

| component | in the tarball as | upstream | licence |
|---|---|---|---|
| llamatalk: llama.cpp's `llama-server` and pockettts.cpp's `tts-server`, and the model downloader | `llamatalk/` | https://github.com/mercurious/llamatalk | MIT (its binaries: MIT, see `llamatalk/THIRD_PARTY.md`) |

## Models

The installer downloads the models from Hugging Face (`llamatalk/models.txt`); none are redistributed here. Each has
its own licence or terms of use on its model card, which you accept by downloading it: Gemma 4 E2B and E4B
(`google/gemma-4-E2B-it-qat-q4_0-gguf`, `google/gemma-4-E4B-it-qat-q4_0-gguf`) and Pocket TTS
(`Serveurperso/pocket-tts-GGUF`).

## What it uses but does not bring

- **RetroArch and its cores** (fceumm, stella), MangoHud, foot and sway: from ROCKNIX, as installed on the device.
- **The games.** None are included, downloaded or linked. You provide your own copies, dumped from cartridges you
  own. The RAM addresses in the players were found by watching the games' memory while they ran; no game code is
  included or derived.
