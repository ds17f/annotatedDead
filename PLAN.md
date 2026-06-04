# Project Legal-Cleanup & Safe-Hosting Plan

## Context
- The repository currently ships a full copy of *The Annotated Grateful Dead Lyrics* in `mirror/` (308 resources), which `build_site.py` turns into the full browsable site in `dist/`.
- David Dodd gave permission for the **annotations/essays** but **not** the underlying song lyrics (the lyrics are separately copyrighted, mostly "Ice Nine Publishing; used by permission").
- We want to keep the tooling (crawler, builder, auditor) so anyone can self-host the **full** site **if they obtain a lawful source** (e.g., the Wayback snapshot).
- For **our** public deployment we publish a **safe** version: the annotations are kept, the copyrighted lyric blocks are removed, and each song links out to the official lyrics source.

## Guiding principle (the shape of the design)
**Local = full. Publish = safe.**
- `make dist` always builds the complete site into `dist/`, unchanged. This is the local source of truth a self-hoster gets.
- `make safe` runs a **standalone post-pass** (`scripts/safe_build.py`) that strips the copyrighted lyric blocks **from `dist/` in place** and inserts a link to the official source. CI runs `make safe` before deploying.
- The strip pass is pure HTML→HTML; it has no coupling to the mirror crawl, so it can be reasoned about and tested on its own.

## Goals
| Goal | Desired outcome |
|------|----------------|
| **A. Standalone safe pass** | `scripts/safe_build.py` + a `make safe` target that strips lyric blocks from the built `dist/` (in place) and links each song to <https://www.dead.net/songs>. Keeps **all** annotation markup. |
| **B. CI publishes the safe site** | The existing GitHub-Actions workflow runs `make safe` (build → strip) before deploying to Pages. |
| **C. Placeholder when mirror is absent** | `build_site.py` emits a minimal placeholder `dist/index.html` when `mirror/` is empty/missing, so a fresh clone (post-purge) still builds something coherent. |
| **D. Documentation** | A "Status & Self-hosting" section in `README.md` covering full vs. safe builds and how to obtain a lawful mirror. |
| **E. Ignore the raw mirror** | `.gitignore` ignores `mirror/`. |
| **F. (LAST) Purge mirror from history** | After everything above works and is verified, back up `mirror/` outside the repo, then rewrite history to remove it, force-push, and notify collaborators. **This is the final, irreversible step — done deliberately at the end, not up front.** |

## How the lyric stripping actually works (corrected)
> The previous draft assumed lyrics lived in `<pre class="lyrics">…</pre>`. **That element does not exist anywhere** (0 pages). The real markup is 1990s-era and lyrics sit in a `<blockquote>` — but so do many *non-lyric* annotation quotes (public-domain poems like Lovelace, OED entries, reader emails, nursery rhymes). A blanket blockquote strip would destroy annotation content we are allowed to publish.

The dependable structural seam, verified across all 124 song pages:

```
[byline: David Dodd, UCSC]
<a href="#title"><b>"Song Title"</b></a>
Words by … ; music by …
Copyright Ice Nine Publishing; used by permission.   ← song-credit line
<blockquote> …the copyrighted lyrics… </blockquote>   ← THE block to remove
<hr>
<a name="title">  ← annotations begin here; everything from here on STAYS
   …essays, which may themselves contain <blockquote>s we keep…
```

Rule: **remove the lyric `<blockquote>`(s) that sit between the song-credit line and the first `<a name="…">` annotation anchor**, and replace with a short notice linking to <https://www.dead.net/songs>. Never touch blockquotes that appear after the first annotation anchor.

Edge cases the pass must handle:
- **`darkstar.html`** — has lyrics but its first annotation anchor is `<a name="dark">`, not `title`. So key on the *first* `<a name=…>` anchor, not the literal string "title".
- **`appl.html` and similar** — only annotate a *title phrase*; there is **no lyric blockquote**. These must be left untouched (the pass finds no block and skips).
- **`Copyright Steve Silberman. Used by permission.`** — an essay credit, not a song lyric. The "blockquote before the first annotation anchor" rule (not a bare "used by permission" text match) avoids mis-stripping here; add a guard/whitelist if needed.
- The pass should be a no-op on pages with no lyric block, and should **report counts** (pages processed, lyric blocks removed) the way `build_site.py` reports its passes.

## Reuse of existing code
- `scripts/mirror.py` — unchanged; still crawls the Wayback snapshot for self-hosters.
- `scripts/build_site.py` — unchanged for the full build; gains only the empty-mirror **placeholder** behavior (Goal C).
- `scripts/safe_build.py` — **new** standalone post-pass (Goal A). Reads `dist/`, strips lyric blocks in place, injects the dead.net link.
- `scripts/audit_links.py` — unchanged; audits whatever is in `dist/` (full or safe).
- `Makefile` — gains a `safe` target: `make dist` then `python scripts/safe_build.py`.
- `.gitignore` — add `mirror/`.

## Files to Modify / Add
| Path | Reason |
|------|--------|
| `scripts/safe_build.py` | New standalone strip-and-relink pass over `dist/`. |
| `Makefile` | New `safe` target (build → strip). |
| `scripts/build_site.py` | Emit placeholder `index.html` when `mirror/` is empty. |
| `.github/workflows/…` | Deploy step runs `make safe` instead of `make dist`. |
| `README.md` | "Status & Self-hosting" section (full vs. safe). |
| `.gitignore` | Ignore `mirror/`. |
| `PLAN.md` (this file) | Living plan. |

## Implementation Steps (ordered; destructive step is LAST)
1. **Write `scripts/safe_build.py`** implementing the boundary rule above; make it idempotent and have it print a count report. Verify on `althea.html`, `darkstar.html` (anchor != "title"), and `appl.html` (no lyric block → untouched).
2. **Add the `make safe` target** (`make dist` then `uv run python scripts/safe_build.py`).
3. **Add the placeholder** to `build_site.py` for the empty-`mirror/` case (Goal C).
4. **Point CI at `make safe`** so Pages serves the safe site; confirm `make audit` passes against the stripped `dist/`.
5. **Docs + `.gitignore`**: add the README section; add `mirror/` to `.gitignore`.
6. **Verify the whole pipeline locally** end to end (full build, safe strip, audit).
7. **(LAST) Purge `mirror/` from history** — only after 1–6 are merged and the safe site is confirmed:
   ```bash
   cp -r mirror ../annotated-lyrics-mirror-backup   # backup OUTSIDE the repo first
   git checkout main
   git filter-repo --path mirror/ --invert-paths
   git rev-list --objects --all | grep mirror/      # must return nothing
   git push --force-with-lease
   ```
   Then notify collaborators to re-clone (every commit hash changes).

## Verification Checklist
- [ ] `safe_build.py` strips the lyric blockquote on `althea.html` and `darkstar.html`, leaves `appl.html` untouched, and preserves all annotation-internal blockquotes.
- [ ] `safe_build.py` prints a count report and is idempotent (safe to re-run on an already-stripped `dist/`).
- [ ] `make safe` produces a `dist/` whose song pages link to <https://www.dead.net/songs> in place of lyrics.
- [ ] `make audit` passes against the stripped `dist/`.
- [ ] `build_site.py` emits a placeholder `index.html` when `mirror/` is empty.
- [ ] CI deploys the safe site to Pages without errors.
- [ ] `README.md` documents full vs. safe builds; `.gitignore` ignores `mirror/`.
- [ ] **(LAST)** Backup exists at `../annotated-lyrics-mirror-backup`; history contains no `mirror/` objects; force-push done; collaborators notified.

---
*Living planning artifact. Step 7 (history rewrite) is intentionally deferred to the very end.*
