# AGENTS.md

## Git identity firewall

The maintainer has two GitHub identities that must never cross. Each repo belongs to exactly
one of them, and the owner of its `origin` remote decides which. Every commit, push, issue,
PR and doc in this repo uses this repo's identity only.

**Lane: `mercurious` (pseudonymous).** This repo is `mercurious/autogamer` (public).

- Commit as `mercurious <dutch.money@gmail.com>`. That is already this repo's `user.email`.
- Keep the maintainer's real name, institution and other accounts out of everything here:
  code, docs, commit messages, issues and PRs. Nothing in this repo may link this identity to
  the other one.
- `gh` usually has the other account active. Before pushing, or if a push fails with
  "Repository not found" or 403, run `gh auth switch --user mercurious`. When you're done,
  switch back to the account that `gh auth status` showed as active before.

On the maintainer's machines, a Claude Code `PreToolUse` hook enforces this:
`~/.claude/hooks/git-identity-firewall.py`, registered on `Bash` in `~/.claude/settings.json`
(self-tests: `python3 ~/.claude/hooks/test_git_identity_firewall.py`). It runs before
`git commit|merge|rebase|cherry-pick|am|revert|push`, including inside `ssh HOST '...'`, and
before `gh repo create --push` and `gh pr create`. It reads the origin owner, the configured
`user.email`, and any `-c user.*`, `--author` or `GIT_*_EMAIL` override. It denies the command
when that identity doesn't belong to the owner's lane. The owner-to-email map is `RULES` in the
script. A repo with no remote is allowed.

If the hook denies a command, the identity is wrong. Fix `user.email`, or ask the maintainer.
Don't route around the hook: no overrides, no other shells, no rewriting the remote. Agents
other than Claude Code aren't covered by that hook, but they are covered by the next one.

A second firewall runs inside git itself, so it covers every tool (Claude Code, gemini, copilot,
a plain shell): the global `core.hooksPath` is `~/.config/git/identity-firewall/hooks`, the
logic is in `firewall.py`, and the self-tests are in `test_firewall.py`. `pre-commit` and
`commit-msg` block the other lane's names and email addresses in staged changes, file paths
and commit messages, and check the commit identity. `pre-push` checks every outgoing commit.
Git has no global identity (`user.useConfigOnly`), so each repo needs its own `user.name`
and `user.email` (`git config --local`). The repo's own hooks in `.git/hooks` still run after
the firewall. Never pass `--no-verify` or change `core.hooksPath`; only the maintainer may
bypass a block.

## Where work runs

Agents work from the maintainer's daily driver: an Asahi Linux M1 with 8 GB of RAM and no fan. It is the
smallest computer in this project. Even the 12 GB Flip 2 handheld (car12), with a fan on its Snapdragon, has more
room. A build or a long job here chokes the machine the maintainer is using, so keep heavy work off it:

- Compile on the maintainer's OCI Ampere nodes, the laptop's cloudmates. `etk-cloud` (4 OCPU, 24 GB) builds the
  releases: bundle `main`, copy it to `~/llamatalk-builds/bundles/autogamer.bundle`, run
  `~/llamatalk-builds/node_autogamer.sh` there, and copy the tarball back. On the laptop,
  `PREBUILT=1 build/release.sh` only checks the tarball and uploads it. Never run `build/build.sh`, a podman or
  docker build, or a full `build/release.sh` on the laptop.
- The nodes belong to the maintainer, so nothing should stop an agent using them. If a step to a node is blocked
  (a permission prompt, a denial, a failing ssh), stop and ask the maintainer to fix the block. Don't fall back to
  building on the laptop.
- Long or CPU-heavy jobs (emulator labs, benchmarks, model runs) also go on a node or a rig. Quick checks are
  fine on the laptop (`test/test_games.py`, `py_compile`, `sh -n`).
