# Annotated Grateful Dead Lyrics — Faithful Mirror

A self-contained, offline, **faithful preservation** of David Dodd's
*The Annotated Grateful Dead Lyrics* — the 1990s UC Santa Cruz site
(`artsites.ucsc.edu/GDead/agdl/`), recovered from the Internet Archive and
made fully browsable on its own, with the period HTML preserved byte-for-byte.

**Live site: https://annotated.thedeadly.app/**

> The original site is frozen/offline. This project rebuilds it from a single
> archive.org snapshot (timestamp `20230806233010`) and fixes the links so it
> works without the dead live domain.

The live successors of the project, for reference:
[Grateful Dead Archive Online](https://www.gdao.org/items/show/100962) and the
book [*The Complete Annotated Grateful Dead
Lyrics*](https://www.simonandschuster.com/books/The-Complete-Annotated-Grateful-Dead-Lyrics/David-G-Dodd/9781439103340).

---

## Quick start

The raw archive (`mirror/`) is **committed**, so a fresh clone is ready to build
— no crawl needed. The only prerequisite is [uv](https://docs.astral.sh/uv/).

```bash
make all          # build the full site, audit it, and serve at localhost:8000
```

That single command sees `mirror/` is already present (so it **skips** the
~40-minute crawl), builds `dist/`, audits link health, and serves the full site
at **http://localhost:8000**. `uv run` provisions dependencies on first use, so
a separate `make install` isn't required.

Individual targets:

```bash
make dist         # build the full site (annotations + lyrics) into dist/
make safe         # build dist/, then strip lyrics for safe public hosting
make serve-dist   # serve dist/ at http://localhost:8000
make audit        # report link health of dist/
make mirror       # re-crawl the archive into mirror/ (~30-45 min; only to refresh)
```

To preview the **safe** (annotation-only) build locally, run `make safe` then
`make serve-dist`. If a server is already running, `make safe` rewrites `dist/`
in place and a browser refresh shows the stripped version — no restart needed.

You don't strictly need a server — `dist/` is plain static HTML. After a build
you can just open `dist/index.html` (or `dist/gdhome.html`) with a `file://` URL
in a browser and click through.

---

## How it works: source of truth → build

The core design decision is to **decouple downloading from converting**:

```
archive.org ──mirror──► mirror/ ──build──► dist/ ──serve/audit──► browser
              (raw,                (link-fixed,
               byte-exact,          generated,
               immutable)           disposable)
```

- **`mirror/`** is the *source of truth*: the original HTML and image assets,
  saved exactly as the archive served them. No conversion, no link rewriting.
  Build outputs can be regenerated from it forever with **zero network**.
- **`dist/`** is a *build artifact*: `mirror/` plus link fixes. It's gitignored
  and rebuilt by `make dist`.

Keeping these separate is the whole point: downloading once into an immutable
`mirror/` means the browsable output can be regenerated any number of ways
without ever re-hitting archive.org.

---

## Status & self-hosting: full vs. safe builds

David Dodd generously gave permission to host his **annotations and essays**.
He did **not** (and could not) license the underlying **song lyrics**, which are
separately copyrighted. So this project distinguishes two builds:

| Build | Command | Contains | Who it's for |
|-------|---------|----------|--------------|
| **Full** | `make dist` | annotations **and** lyrics | local self-hosters with a lawful source |
| **Safe** | `make safe` | annotations only; lyrics replaced with a link to [dead.net/songs](https://www.dead.net/songs) | the public site we deploy |

**`make safe`** runs the normal build and then a standalone pass
(`scripts/safe_build.py`) that strips each song's verbatim lyric block — the
`<blockquote>` between the song's credit line and the first annotation anchor —
and drops a link to the official lyrics source in its place. **Everything else
is preserved**: the essays, and the public-domain poems, dictionary entries, and
reader correspondence quoted *within* the annotations. Short lyric fragments
quoted inline for commentary in the essays are left intact (permitted annotation
/ fair use); only the full per-song lyric reproductions are removed. The pass is
idempotent and byte-preserving, and it never deletes a byte of the annotation
section even on pages with malformed 1990s markup.

The public site at **https://annotated.thedeadly.app/** is the **safe** build —
CI runs `make safe` before deploying. If you have obtained a lawful copy of the
original HTML (e.g. via the Internet Archive, see `make mirror`), `make dist`
gives you the complete site locally.

---

## The pipeline, pass by pass (with real results)

### 1. `make mirror` — the raw crawl (`scripts/mirror.py`)

A breadth-first crawler starting at `gdhome.html`, following internal links.

Key techniques learned along the way:

- **The Wayback `id_` form.** Fetching
  `https://web.archive.org/web/20230806233010id_/<original-url>` returns the
  *original* bytes with **no** Wayback toolbar or rewritten links injected —
  exactly what a faithful mirror needs.
- **Link canonicalization.** The source links to itself inconsistently:
  `artsites.ucsc.edu/GDead/agdl/…` *and* `arts.ucsc.edu/gdead/agdl/…` (different
  host, different case). archive.org normalizes these, so every internal link is
  reduced to one canonical relative path and fetched/stored exactly once.
- **Throttle resilience.** archive.org drops connections under burst load. The
  first full run got cut off; the crawler now retries connection failures with
  exponential backoff (`make mirror-retry` re-queues anything still failed),
  while letting real 404s fail fast. State is saved every few pages, so the
  crawl is interruptible and resumable.

**Results:**

| Run | Succeeded | Failed | Notes |
|-----|-----------|--------|-------|
| Pass 1 (no backoff) | 158 | 108 | only **3** real 404s — the rest were throttling |
| Pass 2 (`--retry-failed`, with backoff) | **308** | 15 | the 15 are all non-content (below) |

Final mirror: **~308 resources, ~5.6 MB** — 198 HTML pages + 110 images/assets.
A cross-check against the project's known page list found **every** catalogued
page present, plus 3 the previous attempt had missed.

The 15 "failures" are all unrecoverable-by-design: typo'd/dead links whose real
target was mirrored under the correct name (`mexicali.html`→`mex.html`, etc.),
parse fragments from malformed source HTML, and external domains.

### 2. `make dist` — the cleanup build (`scripts/build_site.py`)

Reads `mirror/`, writes `dist/`. HTML is edited via a lossless latin-1
round-trip so **only `href`/`src` URL values change** — every other byte of the
original markup is preserved. Each fix is an explicit, counted pass:

| Pass | What it does | Rewrites |
|------|--------------|----------|
| 0 | repair malformed source tags (`<a href="a href="deal.html"` → `deal.html`) | 5 |
| 1 | `abs-agdl` → relative (`http://…/agdl/david.html` → `david.html`) | **408** |
| 2 | typo'd internal link → real page (`mexicali.html` → `mex.html`) | 10 |
| 3 | root-absolute → relative (`/scarlet.html` → `scarlet.html`) | 3 |
| 4 | bare domain → add scheme (`www.gdhour.com` → `http://www.gdhour.com`, still live) | 1 |
| 5 | known-dead destination → `link-gone.html` (alternatives page) | 3 |
| 6 | repair broken `#anchor` typos (`#workingmans` → `#workingman`) | 17 |

Pass 0 fixes five specific broken-link defects in the source — a missing
quote, a missing space, a pasted-twice `href` — each with an unambiguous
intended target, applied as exact literal replacements.

The biggest win is pass 1: **407 cross-page links pointed at the dead live
domain** even though their targets sit right in the mirror.

### 3. `make audit` — proving it (`scripts/audit_links.py`)

A browser-accurate link check: every link resolved relative to its page,
case-sensitively (like a Linux filesystem), against the files actually present.
In-page `#anchors` are validated too.

**Final audit of `dist/`:**

| Result | Count |
|--------|-------|
| Internal links that resolve | **3,978** ✅ |
| External links (left as-is, not verified) | 1,363 |
| In-page anchors / mailto | 1,699 |
| Case-mismatches (break on Linux, work on macOS) | **0** ✅ |
| **Real broken internal links** | **0** ✅ |
| Malformed-source fragments (not real links) | 1 |
| Broken in-page anchors (preserved from source) | 43 |

`make audit` exits non-zero only on *real* broken internal links or
case-mismatches, so it can gate a build.

---

## The "link has gone quiet" page

Some links the 1998 site pointed at have moved or died. Rather than leave them
as silent dead-ends, known-dead destinations are redirected to a generated
**`link-gone.html`** that offers a still-working substitute where one exists:

- `jazzisdead.com` → [Jazz Is Dead (band) —
  Wikipedia](https://en.wikipedia.org/wiki/Jazz_Is_Dead_(band)) *(the original
  domain now hosts an unrelated label)*
- `www.halcyon.com/wardk/…` → no known replacement (a retired personal page)

This list lives in `ALT_LINKS` in `scripts/build_site.py` and is easy to extend.

> **A bug worth remembering:** the alt-links page was first named `gone.html` —
> which silently overwrote the real **"He's Gone"** song page (`gone.html`).
> It's now `link-gone.html`, and the build has a hard guard that aborts if a
> generated filename ever collides with a real mirrored page.

---

## Known limitations (deliberately preserved)

These are defects in the **original 1990s source**, kept rather than invented around:

- **1 malformed-link fragment** remains: `ripple.html`'s `(Chorus)` link points
  at a `chorus` target that was never created, so there's nothing to repair it
  to. (Five other malformed links with clear intended targets are fixed in
  pass 0.)
- **43 broken in-page anchors** (e.g. `biblio.html#goose`) point at anchors the
  author linked to but never created. The 17 that were obvious typos are
  auto-repaired; the rest are left honest.
- **External links are not liveness-checked.** ~1,360 of them, mostly to
  long-gone 1990s sites — not this project's content to fix.

---

## Project layout

```
mirror/              # raw byte-exact archive copy — the source of truth (committed)
dist/                # built, link-fixed site (gitignored; regenerate with `make dist`)
scripts/
  mirror.py          # the raw crawler  (make mirror / mirror-retry)
  build_site.py      # the cleanup build (make dist)
  safe_build.py      # the lyric-strip pass for public hosting (make safe)
  audit_links.py     # the link auditor  (make audit)
  release.sh         # tag a semver release (make release)
.github/workflows/   # CI, Pages deploy, release automation
Makefile             # all commands — run `make help`
.mirror_state/       # crawler resume state (gitignored)
```

Run `make help` for the full target list.

---

## Hosting & releases

The site is hosted on **GitHub Pages** and deploys automatically:

- **Every merge to `main`** runs CI (build + link audit) and, on success,
  publishes the site to Pages (`.github/workflows/deploy-pages.yml`). The deploy
  runs `make safe`, so the **annotation-only** site is what goes live; the build
  uses the committed `mirror/`, so no archive.org crawl happens in CI.
- **Releases are semver-tagged.** `make release` reads
  [Conventional Commits](https://www.conventionalcommits.org/) since the last
  `v*` tag, picks the next version, and pushes a `vX.Y.Z` tag. That triggers
  `release.yml`, which builds the site, attaches `dist.zip`, and publishes a
  GitHub Release. Preview first with `make release-dryrun`.

## Contributing

`main` is protected — all changes go through a pull request with passing CI.
The cardinal rule: **never hand-edit `mirror/` or `dist/`** — express link and
content fixes as code in `scripts/build_site.py` (`HTML_FIXES`, `REDIRECTS`,
`ALT_LINKS`, anchor repair), so they're repeatable and reviewable.

See **[CONTRIBUTING.md](CONTRIBUTING.md)** for the workflow and
**[AGENTS.md](AGENTS.md)** for the full conventions (also what AI agents follow).

---

## Content source & credits

Content is *The Annotated Grateful Dead Lyrics* by **David Dodd**, originally
hosted at UC Santa Cruz, recovered from the
[Internet Archive](https://web.archive.org/web/20230806233010/http://artsites.ucsc.edu/GDead/agdl/gdhome.html).
This is a preservation effort; all original authorship and attribution remain
with David Dodd and the contributors credited throughout the pages.
