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

Not every song uses a <blockquote>. Some lay the lyrics out as bare
<br>-separated lines, or inside a layout <table> (e.g. soma.html, bird.html). For
those we strip the span from the end of the credit/copyright preamble to the
seam, gated so non-lyric pages stay untouched: pages whose region carries list
markup (discographies, title-phrase nav like appl.html / tribute.html) are
skipped, and the span must be verse-dense (>=10 <br>; real lyric spans have >=27,
everything else <=5). Single-line epigraphs above the credit line, and short
lyric fragments quoted inside the annotations, are fragments -- left in place, by
the same fair-use reasoning that keeps the essays.
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

# Some pages lay lyrics out as bare <br>-separated lines (or inside a layout
# <table>) with no <blockquote> at all. There the lyric span runs from the end
# of the credit/copyright preamble to the annotation seam. PREAMBLE_RE finds the
# credit lines (the lyrics start after the LAST one); BOUNDARY_RE finds the
# <br>/<p> that ends that line.
PREAMBLE_RE = re.compile(
    r"(words?\s+(?:and\s+music\s+)?by|lyrics?\s+by|music\s+by"
    r"|copyright|used\s+(?:by|with)[^<\n]*permission)",
    re.I,
)
BOUNDARY_RE = re.compile(r"<br\s*/?>|<p\s*/?>", re.I)

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


def _lyric_start(text, lo, seam):
    """Where the lyrics begin: just after the last credit/copyright line in the
    [lo, seam) region. Falls back to lo if no preamble line is found."""
    last = None
    for m in PREAMBLE_RE.finditer(text[lo:seam]):
        last = m
    if not last:
        return lo
    pos = lo + last.end()
    boundary = BOUNDARY_RE.search(text, pos, seam)
    return boundary.end() if boundary else pos


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

    # Case 1: lyrics wrapped in <blockquote> (the common layout). Targets are the
    # blockquotes starting between the credit line and the seam.
    targets = [m for m in BLOCKQUOTE_RE.finditer(text) if lo <= m.start() < seam]
    if targets:
        # Replace right-to-left so earlier match offsets stay valid. The first
        # lyric block (in document order) becomes the notice; any others are
        # dropped, while the prose between them -- Dodd's editorial notes -- is
        # left in place.
        #
        # Some 1990s pages (e.g. eleven.html) never close the lyric <blockquote>
        # before the annotations, so the match runs past the seam and would
        # engulf the <a name=...> anchor. Clamp every removal at the seam: never
        # delete a byte of the annotation section, even at the cost of leaving a
        # stray, browser-ignored </blockquote> behind.
        first = targets[0]
        out = text
        for m in reversed(targets):
            end = min(m.end(), seam)
            repl = NOTICE if m is first else ""
            out = out[: m.start()] + repl + out[end:]
        return out, len(targets)

    # Case 2: no lyric <blockquote>. Lyrics may instead be bare <br>-separated
    # lines or inside a layout <table> (e.g. soma.html, bird.html). Strip the
    # span from the end of the credit preamble to the seam -- but only when it
    # really is a reproduced lyric. Two gates keep non-lyric pages (title-phrase
    # annotations, discographies, the home page) untouched: skip if the region
    # carries list markup (a discography / nav block), and require a verse-dense
    # span. Across the archive that span has >=27 <br> on real lyric pages and
    # <=5 on everything else, so a threshold of 10 separates them cleanly.
    if "<li" in text[lo:seam].lower():
        return None
    start = _lyric_start(text, lo, seam)
    if text[start:seam].lower().count("<br") < 10:
        return None
    return text[:start] + NOTICE + text[seam:], 1


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
