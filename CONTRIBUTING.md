# Contributing

Thanks for helping preserve *The Annotated Grateful Dead Lyrics*! This is a
small, focused project: a faithful offline mirror of the 1990s site, with link
fixes applied at build time. Contributions are welcome — especially repairing
links and adding good substitutes for dead external ones.

See **[AGENTS.md](AGENTS.md)** for the full conventions; this is the short,
human-friendly version.

## Setup

```bash
make install        # installs deps with uv
make dist           # build the browsable site into dist/
make serve-dist     # view it at http://localhost:8000
make audit          # check link health
```

You do **not** need to run `make mirror` (the ~30–45 min archive crawl) — the
`mirror/` source is committed.

## The one rule

**Never edit `mirror/` or `dist/` by hand.**

- `mirror/` is the byte-for-byte archived source of truth.
- `dist/` is generated and gitignored.

All fixes are expressed as code in `scripts/build_site.py`, so they're
repeatable and reviewable.

## Common contributions

**Fix a broken internal link** (a page that exists under a different name):
add an entry to `REDIRECTS` in `scripts/build_site.py`.

**Repair a malformed link in the source** (missing quote, typo'd tag): add an
exact literal `(bad, good)` entry to `HTML_FIXES`, keyed by the file.

**Offer an alternative for a dead external link**: add an entry to `ALT_LINKS`
— it renders on the generated `link-gone.html` page. Please link to a real,
still-working resource (e.g. a Wikipedia article), not a guess.

After any change: `make dist && make audit` must pass (the audit is the CI gate).

## Commit messages

We use [Conventional Commits](https://www.conventionalcommits.org/) — they
drive automatic versioning:

- `feat: …` → minor release   (e.g. `feat: add alt link for the Grateful Dead Hour`)
- `fix: …` / `perf: …` → patch release   (e.g. `fix: repair broken biblio anchor`)
- `feat!: …` or a `BREAKING CHANGE:` footer → major release
- `docs:`, `chore:`, `refactor:`, `ci:`, `build:`, `test:` → no release

## Pull requests

`main` is protected, so:

1. Branch off `main`.
2. Make your change and run `make dist && make audit`.
3. Open a PR. CI must pass before it can merge.
4. On merge, the site redeploys to GitHub Pages automatically.

## A note on faithfulness

This is a *preservation*. We fix links so the site is navigable, but we don't
rewrite the original authors' content, styling, or period HTML. When a link is
genuinely dead with no honest substitute, we leave it rather than invent a
destination.
