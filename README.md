# Annotated Grateful Dead Lyrics — Faithful Mirror

A self-contained, offline, **faithful preservation** of David Dodd's
*The Annotated Grateful Dead Lyrics* — the 1990s UC Santa Cruz site
(`artsites.ucsc.edu/GDead/agdl/`), recovered from the Internet Archive and
made fully browsable on its own, with the period HTML preserved byte-for-byte.

> The original site is frozen/offline. This project rebuilds it from a single
> archive.org snapshot (timestamp `20230806233010`) and fixes the links so it
> works without the dead live domain.

The live successors of the project, for reference:
[Grateful Dead Archive Online](https://www.gdao.org/items/show/100962) and the
book [*The Complete Annotated Grateful Dead
Lyrics*](https://www.simonandschuster.com/books/The-Complete-Annotated-Grateful-Dead-Lyrics/David-G-Dodd/9781439103340).

---

## Quick start

```bash
make install      # install deps (uv)
make mirror       # download the raw archive into mirror/  (~30-45 min, one time)
make dist         # build the browsable, link-fixed site into dist/
make serve-dist   # serve dist/ at http://localhost:8000
make audit        # report link health of dist/
```

You don't strictly need a server — `dist/` is plain static HTML. After
`make dist` you can just open `dist/index.html` (or `dist/gdhome.html`) with a
`file://` URL in a browser and click through.

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
| 1 | `abs-agdl` → relative (`http://…/agdl/david.html` → `david.html`) | **408** |
| 2 | typo'd internal link → real page (`mexicali.html` → `mex.html`) | 9 |
| 3 | root-absolute → relative (`/scarlet.html` → `scarlet.html`) | 3 |
| 4 | bare domain → add scheme (`www.gdhour.com` → `http://www.gdhour.com`, still live) | 1 |
| 5 | known-dead destination → `link-gone.html` (alternatives page) | 3 |
| 6 | repair broken `#anchor` typos (`#workingmans` → `#workingman`) | 17 |

The biggest win is pass 1: **407 cross-page links pointed at the dead live
domain** even though their targets sit right in the mirror.

### 3. `make audit` — proving it (`scripts/audit_links.py`)

A browser-accurate link check: every link resolved relative to its page,
case-sensitively (like a Linux filesystem), against the files actually present.
In-page `#anchors` are validated too.

**Final audit of `dist/`:**

| Result | Count |
|--------|-------|
| Internal links that resolve | **3,973** ✅ |
| External links (left as-is, not verified) | 1,363 |
| In-page anchors / mailto | 1,698 |
| Case-mismatches (break on Linux, work on macOS) | **0** ✅ |
| **Real broken internal links** | **0** ✅ |
| Malformed-source fragments (not real links) | 6 |
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

- **6 malformed-link fragments** (`a href=`, `chorus`, `btwind.html"`, …) come
  from unclosed/broken tags; a browser never saw them as valid links either.
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
  audit_links.py     # the link auditor  (make audit)
Makefile             # all commands — run `make help`
.mirror_state/       # crawler resume state (gitignored)
```

Run `make help` for the full target list.

---

## Content source & credits

Content is *The Annotated Grateful Dead Lyrics* by **David Dodd**, originally
hosted at UC Santa Cruz, recovered from the
[Internet Archive](https://web.archive.org/web/20230806233010/http://artsites.ucsc.edu/GDead/agdl/gdhome.html).
This is a preservation effort; all original authorship and attribution remain
with David Dodd and the contributors credited throughout the pages.
