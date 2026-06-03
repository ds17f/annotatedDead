#!/usr/bin/env python3
"""
Audit link health of a built site directory (default: dist/).

Browser-accurate: every link is resolved the way a browser would -- relative to
the page that contains it, case-sensitively (matching a Linux filesystem) -- and
checked against the files actually present. Also validates in-page #anchors.

Reports:
  - internal links that resolve vs. broken
  - case-only mismatches (work on macOS, break on Linux)
  - broken in-page anchors (target file exists, #fragment missing)
  - external links (left as-is; not verified for liveness)

Exit code is non-zero if any broken internal link or case-mismatch is found,
so it can gate a build. Broken anchors and dead-in-source artifacts are
reported but do not fail the audit (they are preserved from the original).
"""

import argparse
import collections
import glob
import os
import re
import sys
from urllib.parse import urlparse, unquote

from bs4 import BeautifulSoup

# A "real" internal link target: a clean path ending in a known extension. Broken
# targets that don't match are parse fragments from malformed 1990s HTML
# (e.g. 'a href=', 'chorus', 'btwind.html"') -- reported, but not build failures.
CLEAN_TARGET = re.compile(r"^[\w./-]+\.(html?|gif|jpe?g|png|doc|docx|pdf|txt)$", re.I)

EXTERNAL_SCHEMES = ("http", "https", "ftp", "gopher", "news", "file", "telnet")
LINK_ATTRS = [("a", "href"), ("img", "src"), ("link", "href"),
              ("script", "src"), ("area", "href"), ("frame", "src"),
              ("iframe", "src")]


def classify(u):
    low = u.strip().lower()
    if low.startswith(("#", "mailto:", "javascript:", "tel:", "data:")):
        return "skip"
    p = urlparse(u.strip())
    if p.scheme in EXTERNAL_SCHEMES or p.netloc:
        return "external"
    return "internal"


def audit(root):
    real = {os.path.relpath(p, root)
            for p in glob.glob(f"{root}/**/*", recursive=True) if os.path.isfile(p)}
    real_ci = {f.lower() for f in real}
    anchors = collections.defaultdict(set)
    for f in glob.glob(f"{root}/**/*.htm*", recursive=True):
        rel = os.path.relpath(f, root)
        soup = BeautifulSoup(open(f, "rb").read(), "lxml")
        for e in soup.find_all(attrs={"name": True}):
            anchors[rel].add(e["name"].lower())
        for e in soup.find_all(attrs={"id": True}):
            anchors[rel].add(e["id"].lower())

    stats = collections.Counter()
    broken, case_mismatch, broken_anchor = [], [], []

    for f in sorted(glob.glob(f"{root}/**/*.htm*", recursive=True)):
        page = os.path.relpath(f, root)
        pdir = os.path.dirname(page)
        soup = BeautifulSoup(open(f, "rb").read(), "lxml")
        for tag, attr in LINK_ATTRS:
            for el in soup.find_all(tag):
                v = el.get(attr)
                if not v:
                    continue
                kind = classify(v)
                if kind == "skip":
                    stats["anchor/mailto"] += 1
                    continue
                if kind == "external":
                    stats["external"] += 1
                    continue
                path = unquote(v.strip()).split("#", 1)[0].split("?", 1)[0]
                if path == "":
                    stats["internal-ok"] += 1
                    continue
                target = os.path.normpath(os.path.join(pdir, path))
                if target in real:
                    stats["internal-ok"] += 1
                elif target.lower() in real_ci:
                    stats["case-mismatch"] += 1
                    case_mismatch.append((page, v.strip(), target))
                else:
                    stats["broken"] += 1
                    broken.append((page, v.strip(), target))
        for a in soup.find_all("a", href=True):
            h = a["href"].strip()
            if "#" not in h:
                continue
            p = urlparse(h)
            if p.scheme or p.netloc:
                continue
            frag = unquote(h.split("#", 1)[1]).lower()
            if not frag:
                continue
            base = unquote(h.split("#", 1)[0])
            t = page if base == "" else os.path.normpath(os.path.join(pdir, base))
            if t in anchors and frag not in anchors[t]:
                broken_anchor.append(f"{t}#{frag}")

    print(f"=== link audit of {root}/ ===")
    for k in ["internal-ok", "external", "anchor/mailto", "case-mismatch", "broken"]:
        print(f"  {stats[k]:5d}  {k}")
    print()
    broken_real = [b for b in broken if CLEAN_TARGET.match(b[2])]
    broken_junk = [b for b in broken if not CLEAN_TARGET.match(b[2])]
    print(f"Broken internal links: {len(broken_real)} real, "
          f"{len(broken_junk)} malformed-source fragments, "
          f"{len(case_mismatch)} case-mismatch")
    for pg, v, t in broken_real:
        print(f"    REAL {pg}: {v!r} -> {t}")
    for pg, v, t in case_mismatch:
        print(f"    CASE {pg}: {v!r} -> have {t}")
    for pg, v, t in broken_junk:
        print(f"    junk {pg}: {v!r}")
    print()
    distinct = collections.Counter(broken_anchor)
    print(f"Broken in-page anchors: {len(broken_anchor)} occurrences, "
          f"{len(distinct)} distinct (preserved from 1990s source)")
    for k, n in distinct.most_common():
        print(f"    {n:3d}  {k}")

    return len(broken_real) + len(case_mismatch)


def main():
    ap = argparse.ArgumentParser(description="Audit built-site link health.")
    ap.add_argument("root", nargs="?", default="dist", help="site dir (default: dist)")
    args = ap.parse_args()
    if not os.path.isdir(args.root):
        sys.exit(f"{args.root}/ not found -- run 'make dist' first.")
    sys.exit(1 if audit(args.root) else 0)


if __name__ == "__main__":
    main()
