#!/usr/bin/env python3
"""
Build a browsable, faithful static site from the raw mirror/.

Reads mirror/ (the pristine byte-for-byte archive copy) and writes dist/. The
HTML is edited as raw text via a latin-1 round-trip (a lossless 1:1 byte
mapping) so that ONLY href/src URL values change -- every other byte of the
original 1990s markup is preserved. Binary assets are copied verbatim.

Link cleanup runs as explicit passes, each counted in the build report:

  1. abs-agdl   http://arts.ucsc.edu/gdead/agdl/david.html  -> david.html
                (both domain/case variants; bare root -> index.html)
  2. typo       dead internal links whose real target exists in the mirror,
                e.g. mexicali.html -> mex.html (REDIRECTS)
  3. root-abs   /scarlet.html -> scarlet.html  (only when basename exists)
  4. scheme-fix bare external domains written without a scheme,
                e.g. www.gdhour.com -> http://www.gdhour.com  (still live)
  5. gone       known-dead destinations -> gone.html#slug, a generated page
                offering curated, still-working alternatives (ALT_LINKS)
  6. anchors    target file exists but #fragment is missing -> repair obvious
                typos via close-match (e.g. #workingmans -> #workingman) and
                strip stray-quote artifacts (#grove" -> #grove)

Anything not matched -- in-page anchors, live external links, and genuinely
broken links already broken in the 1990s source -- is left untouched.
"""

import difflib
import html as htmllib
import re
import shutil
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse, unquote

SRC = Path(__file__).parent.parent / "mirror"
OUT = Path(__file__).parent.parent / "dist"

# Filename for the generated alt-links page. Deliberately hyphenated so it can
# never collide with a real 1990s page (e.g. gone.html is the "He's Gone" song).
GONE_PAGE = "link-gone.html"

# --- Pass 0: surgical repairs of specific malformed tags in the 1990s source.
# Each entry is an exact (bad -> good) literal fix for one unique HTML defect
# that a browser cannot parse as a link (a missing quote, a missing space, a
# pasted-twice href). Applied to the raw text BEFORE link rewriting, so the
# repaired href still flows through the redirect/anchor passes below.
HTML_FIXES = {
    "bachmann.html": [('<a href=btwind.html">', '<a href="btwind.html">')],
    "greene.html":   [('href=ripple.html">', 'href="ripple.html">')],
    "ramble2.html":  [('<a href="biblio.html>Sources</a>',
                       '<a href="biblio.html">Sources</a>')],
    "shalit.html":   [('<a href="a href="deal.html"', '<a href="deal.html"')],
    "stephen.html":  [('<a href="ladyfinger">', '<a href="#ladyfinger">')],
}

# --- Pass 2: dead internal links whose real target lives under another name ---
REDIRECTS = {
    "mexicali.html": "mex.html",
    "birdsong.html": "bird.html",
    "goldroad.htm": "goldroad.html",
    "throwin.html": "throwing.html",
    "bibliol.html": "biblio.html",
    "miss.html": "mission.html",
    "btwind.html": "btw.html",
}

# --- Pass 5: known-dead destinations -> curated alternatives on gone.html ---
ALT_LINKS = {
    "jazzisdead.com": {
        "slug": "jazz-is-dead",
        "title": "Jazz Is Dead (jazzisdead.com)",
        "note": "Originally the site of Jazz Is Dead, the instrumental Grateful "
                "Dead tribute band. That domain now hosts an unrelated music "
                "label, so the old link is misleading.",
        "alts": [
            ("Jazz Is Dead (band) — Wikipedia",
             "https://en.wikipedia.org/wiki/Jazz_Is_Dead_(band)"),
        ],
    },
    "www.halcyon.com/wardk/kuli_loach": {
        "slug": "kuli-loach",
        "title": "Personal page (www.halcyon.com/wardk/…)",
        "note": "A personal Halcyon.com member homepage from the 1990s. "
                "Halcyon retired member pages and no replacement is known.",
        "alts": [],
    },
}

# Bare external domains without a scheme (pass 4). Matches things like
# "www.gdhour.com" or "example.org/path" but NOT "biblio.html".
TLD_RE = re.compile(
    r"^(www\.)?[\w-]+(\.[\w-]+)*\.(com|org|net|edu|gov|info|us|uk|de)(/|$)", re.I
)

ATTR_RE = re.compile(
    r"((?:href|src)\s*=\s*)(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", re.IGNORECASE
)

HAVE = set()                  # local file rel-paths, e.g. {"scarlet.html", ...}
ANCHORS = {}                  # rel-path -> set of lowercased name/id anchors
report = Counter()


def norm_dest(v):
    """Normalize an external destination for matching ALT_LINKS, so that
    'jazzisdead.com' and 'http://www.jazzisdead.com' compare equal."""
    v = v.strip().lower()
    v = re.sub(r"^https?://", "", v)
    v = re.sub(r"^www\.", "", v)
    return v.rstrip("/")


ALT_NORM = {norm_dest(k): val for k, val in ALT_LINKS.items()}


def split_frag(s):
    if "#" in s:
        base, frag = s.split("#", 1)
        return base, frag
    return s, None


def fix_fragment(target_rel, frag):
    """Return a (possibly repaired) fragment for a link into target_rel."""
    if frag is None or frag == "":
        return frag
    anchors = ANCHORS.get(target_rel)
    if not anchors:
        return frag
    low = frag.lower()
    if low in anchors:
        return frag
    cleaned = re.sub(r"[^\w.-]+$", "", low)  # strip trailing quotes/junk
    if cleaned and cleaned in anchors:
        report["6_anchor_fixed"] += 1
        return cleaned
    match = difflib.get_close_matches(cleaned or low, list(anchors), n=1, cutoff=0.85)
    if match:
        report["6_anchor_fixed"] += 1
        return match[0]
    report["6_anchor_unresolved"] += 1
    return frag


def rewrite_value(value):
    v = value.strip()
    low = v.lower()
    if not v or low.startswith(("#", "mailto:", "javascript:", "tel:", "data:")):
        return value

    # Known-dead destination -> alternatives page (pass 5). Matches bare and
    # fully-qualified forms alike (jazzisdead.com == http://www.jazzisdead.com).
    entry = ALT_NORM.get(norm_dest(v))
    if entry:
        report["5_gone"] += 1
        return f"{GONE_PAGE}#{entry['slug']}"

    parsed = urlparse(v)

    if parsed.scheme in ("http", "https"):
        # Absolute AGDL link on the dead live domain -> local relative path.
        if "ucsc.edu" in parsed.netloc.lower() and "/agdl/" in parsed.path.lower():
            path = unquote(parsed.path)
            i = path.lower().find("/agdl/")
            rel = path[i + len("/agdl/"):].lstrip("/")
            rel, frag = split_frag(rel)
            rel = rel or "index.html"
            rel = REDIRECTS.get(rel, rel)
            frag = fix_fragment(rel, frag)
            report["1_abs_agdl"] += 1
            out = rel
            if parsed.query:
                out += "?" + parsed.query
            return out + ("#" + frag if frag else "")
        return value  # live/other external -- leave as-is

    if parsed.scheme:  # ftp:, gopher:, news:, ... -- external, leave
        return value

    # Bare external domain missing its scheme (pass 4).
    if TLD_RE.match(v):
        report["4_scheme_fix"] += 1
        return "http://" + v

    # Relative / root-relative internal link.
    rel, frag = split_frag(unquote(v))
    rel = rel.split("?", 1)[0]

    if rel in REDIRECTS:
        report["2_typo"] += 1
        rel = REDIRECTS[rel]
        frag = fix_fragment(rel, frag)
        return rel + ("#" + frag if frag else "")

    if rel.startswith("/"):
        base = rel.lstrip("/")
        if base in HAVE:
            report["3_root_abs"] += 1
            frag = fix_fragment(base, frag)
            return base + ("#" + frag if frag else "")
        return value  # external root-absolute (gopher/ftp leftovers) -- leave

    # Plain relative link that already resolves locally: still repair its anchor.
    if rel in HAVE and frag:
        frag2 = fix_fragment(rel, frag)
        if frag2 != frag:
            return rel + "#" + frag2
    return value


def rewrite_html(text):
    def repl(m):
        prefix = m.group(1)
        d, s, bare = m.group(2), m.group(3), m.group(4)
        if d is not None:
            return f'{prefix}"{rewrite_value(d)}"'
        if s is not None:
            return f"{prefix}'{rewrite_value(s)}'"
        return f"{prefix}{rewrite_value(bare)}"

    return ATTR_RE.sub(repl, text)


def index_inputs():
    from bs4 import BeautifulSoup
    for p in SRC.rglob("*"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(SRC))
        HAVE.add(rel)
        if p.suffix.lower() in (".html", ".htm"):
            soup = BeautifulSoup(p.read_bytes(), "lxml")
            names = {e["name"].lower() for e in soup.find_all(attrs={"name": True})}
            ids = {e["id"].lower() for e in soup.find_all(attrs={"id": True})}
            ANCHORS[rel] = names | ids


def render_gone_page():
    rows = []
    for entry in sorted(ALT_LINKS.values(), key=lambda e: e["slug"]):
        alts = entry["alts"]
        if alts:
            items = "\n".join(
                f'      <li><a href="{u}">{htmllib.escape(label)}</a></li>'
                for label, u in alts
            )
            alt_html = f"    <p>Try instead:</p>\n    <ul>\n{items}\n    </ul>"
        else:
            alt_html = "    <p><em>No working replacement is known.</em></p>"
        rows.append(
            f'  <section id="{entry["slug"]}">\n'
            f'    <h2>{htmllib.escape(entry["title"])}</h2>\n'
            f'    <p>{htmllib.escape(entry["note"])}</p>\n'
            f"{alt_html}\n  </section>"
        )
    body = "\n".join(rows)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Link Not Available — Annotated Grateful Dead Lyrics (mirror)</title>
<style>
  body {{ font-family: Georgia, serif; max-width: 42rem; margin: 3rem auto;
         padding: 0 1rem; line-height: 1.5; color: #222; }}
  h1 {{ font-size: 1.6rem; }}
  section {{ border-top: 1px solid #ddd; padding-top: 1rem; margin-top: 1.5rem; }}
  a {{ color: #5b3a8e; }}
  .home {{ margin-top: 2rem; }}
</style>
</head>
<body>
<h1>That link has gone quiet</h1>
<p>This is a preserved 1998-era mirror of <em>The Annotated Grateful Dead
Lyrics</em>. Some links it once pointed to have moved or vanished. Where we
could find a still-working substitute, it is listed below.</p>
{body}
<p class="home"><a href="index.html">&larr; Back to the home page</a></p>
</body>
</html>
"""


def main():
    index_inputs()
    if GONE_PAGE in HAVE:
        raise SystemExit(
            f"FATAL: generated page name {GONE_PAGE!r} collides with a real "
            f"mirrored page. Pick a different GONE_PAGE to avoid clobbering it."
        )
    if OUT.exists():
        shutil.rmtree(OUT)

    html_count = bin_count = 0
    for src in SRC.rglob("*"):
        if not src.is_file():
            continue
        dst = OUT / src.relative_to(SRC)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix.lower() in (".html", ".htm"):
            text = src.read_bytes().decode("latin-1")
            for bad, good in HTML_FIXES.get(str(src.relative_to(SRC)), []):
                if bad in text:
                    text = text.replace(bad, good)
                    report["0_html_repair"] += 1
                else:
                    print(f"  WARNING: HTML_FIX for {src.name} no longer matches: {bad!r}")
            dst.write_bytes(rewrite_html(text).encode("latin-1"))
            html_count += 1
        else:
            shutil.copy2(src, dst)
            bin_count += 1

    (OUT / GONE_PAGE).write_text(render_gone_page(), encoding="utf-8")

    print(f"Built dist/: {html_count} html + 1 alt-links page, {bin_count} assets copied.\n")
    print("Link cleanup passes (rewrites applied):")
    labels = {
        "0_html_repair": "malformed source tag repaired",
        "1_abs_agdl": "abs-agdl -> relative",
        "2_typo": "typo'd internal -> real page",
        "3_root_abs": "/root-absolute -> relative",
        "4_scheme_fix": "bare domain -> add http://",
        "5_gone": "known-dead -> link-gone.html",
        "6_anchor_fixed": "broken #anchor repaired",
        "6_anchor_unresolved": "  (#anchor left unresolved)",
    }
    for key, label in labels.items():
        print(f"  {report[key]:5d}  {label}")


if __name__ == "__main__":
    main()
