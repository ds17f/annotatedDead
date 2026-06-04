#!/usr/bin/env python3
"""
Safe-publish pass: strip copyrighted song-lyric blocks from the built dist/.

Runs AFTER build_site.py, transforming dist/ IN PLACE so CI can deploy a public
site that keeps David Dodd's annotations but omits the lyrics he was not able to
license. Local self-hosters who never run this keep the full site.

Pure HTML->HTML and byte-preserving: edits go through the same latin-1 round-trip
build_site.py uses, so untouched bytes of the 1990s markup stay exactly as they
were. The pass is idempotent -- a stripped page carries NOTICE_MARK and is skipped
on re-run.

What it removes (and, deliberately, what it does NOT):

A song page is laid out as

    [byline]                                   <- kept
    <a href="#title"><b>"Song"</b></a>
    Words by ... ; music by ...                <- the song-credit line
    Copyright ...; used by permission.
    <blockquote> ...the lyrics... </blockquote> <- REMOVED
    <hr>
    <a name="title">  ...annotations...        <- kept (incl. the public-domain
                                                  poems, OED entries and reader
                                                  emails they quote)

So we excise only the <blockquote>(s) between the song-credit line and the first
<a name=...> annotation anchor, and drop a link to the official lyrics source in
their place. The credit line is what tells a real song page apart from a thematic
essay (e.g. goose.html / nonsense.html have no such line) -- those are skipped
untouched. Pages with no annotation anchor at all (bios, bibliographies) are
skipped too. Where a song shows more than one lyric blockquote (alternate verses,
e.g. clem.html), each is removed but any editorial note Dodd wrote between them is
preserved.
"""

import re
from collections import Counter
from pathlib import Path

DIST = Path(__file__).parent.parent / "dist"
SONGS_URL = "https://www.dead.net/songs"

# First annotation anchor: <a name="..."> marks where the essay begins. Lyrics
# live before it; everything from it onward is annotation we keep.
SEAM_RE = re.compile(r"<a\s+name\s*=", re.I)

# The song-credit line that precedes real lyrics. Matching one of these (rather
# than a bare "used by permission" text search) is what distinguishes a song
# page from an essay, and excludes the unrelated "Copyright Steve Silberman.
# Used by permission." essay credit.
CREDIT_RE = re.compile(
    r"(used by permission|words?\s+(?:and\s+music\s+)?by|lyrics?\s+by|music\s+by)",
    re.I,
)

BLOCKQUOTE_RE = re.compile(r"<blockquote>.*?</blockquote>", re.I | re.S)

# Marker left in stripped pages so re-running the pass is a no-op.
NOTICE_MARK = "<!-- lyrics-stripped -->"
NOTICE = (
    NOTICE_MARK + "\n<blockquote>\n"
    "<p><em>Lyrics omitted.</em> The annotations below are reproduced by "
    "permission of David Dodd; the song lyrics themselves are copyrighted and "
    "are not reproduced here. Read them at the official source: "
    f'<a href="{SONGS_URL}">dead.net/songs</a>.</p>\n'
    "</blockquote>"
)


def strip_page(text):
    """Return (new_text, n_blocks_removed) if this is a song page with lyrics to
    strip, else None to leave the page untouched."""
    seam_m = SEAM_RE.search(text)
    if not seam_m:
        return None                       # no annotation anchor -> not a song page
    seam = seam_m.start()

    credit_m = CREDIT_RE.search(text[:seam])
    if not credit_m:
        return None                       # no song-credit line -> essay/bio, skip
    lo = credit_m.start()

    # Lyric blockquotes are those starting between the credit line and the seam.
    targets = [m for m in BLOCKQUOTE_RE.finditer(text) if lo <= m.start() < seam]
    if not targets:
        return None                       # song title page with no reproduced lyrics

    # Replace right-to-left so earlier match offsets stay valid. The first lyric
    # block (in document order) becomes the notice; any others are dropped, while
    # the prose between them -- Dodd's editorial notes -- is left in place.
    #
    # Some 1990s pages (e.g. eleven.html) never close the lyric <blockquote>
    # before the annotations, so the match runs past the seam and would engulf
    # the <a name=...> anchor. Clamp every removal at the seam: never delete a
    # byte of the annotation section, even at the cost of leaving a stray,
    # browser-ignored </blockquote> behind.
    first = targets[0]
    out = text
    for m in reversed(targets):
        end = min(m.end(), seam)
        repl = NOTICE if m is first else ""
        out = out[: m.start()] + repl + out[end:]
    return out, len(targets)


def main():
    if not DIST.exists():
        raise SystemExit("dist/ not found -- run 'make dist' first.")

    report = Counter()
    for p in sorted(DIST.rglob("*.html")):
        text = p.read_bytes().decode("latin-1")
        report["scanned"] += 1
        if NOTICE_MARK in text:
            report["already"] += 1
            continue
        result = strip_page(text)
        if result is None:
            continue
        out, n = result
        p.write_bytes(out.encode("latin-1"))
        report["stripped"] += 1
        report["blocks"] += n

    print(f"safe_build: scanned {report['scanned']} html pages")
    print(f"  {report['stripped']:4d}  song pages stripped of lyrics")
    print(f"  {report['blocks']:4d}  lyric blocks removed -> link to {SONGS_URL}")
    if report["already"]:
        print(f"  {report['already']:4d}  already stripped (idempotent skip)")


if __name__ == "__main__":
    main()
