# CLAUDE.md

This project's conventions for AI agents live in **[AGENTS.md](AGENTS.md)** —
read it first. Key points:

- Never hand-edit `mirror/` (the raw archive source — gitignored, not committed
  to this public repo because it holds the copyrighted lyrics; recreate it with
  `make mirror`) or `dist/` (generated). Express all link/content fixes as code
  in `scripts/build_site.py` passes.
- Keep the audit green: `make dist && make audit`.
- Use Conventional Commits (`feat:`/`fix:`/`feat!:`) — they drive releases.
- `main` is PR-protected; all changes go through a pull request.
