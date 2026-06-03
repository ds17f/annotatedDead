#!/usr/bin/env python3
"""
Raw mirror crawler for the Annotated Grateful Dead Lyrics archive.

Unlike scrape.py (which converts pages to Markdown and is lossy), this crawler
saves the *original* HTML and binary assets byte-for-byte into mirror/, building
an offline, faithful source of truth. Conversion to any output format (faithful
static site, MkDocs, ...) is a separate, re-runnable step that reads from here.

How it stays faithful:
- Fetches via the archive.org "id_" form, which returns the original resource
  with no Wayback toolbar/link rewriting injected.
- Saves response bytes verbatim; no transcoding, no link rewriting.
- Canonicalizes internal links across the site's domain/case variants
  (artsites.ucsc.edu/GDead/agdl vs arts.ucsc.edu/gdead/agdl) to a single
  relative path, so each resource is fetched and stored exactly once.

State (.mirror_state/state.json) tracks succeeded/failed/queue for resume.
"""

import argparse
import json
import logging
import random
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup

# Archive snapshot to mirror.
TIMESTAMP = "20230806233010"
ARCHIVE_PREFIX = f"https://web.archive.org/web/{TIMESTAMP}id_/"
# Canonical origin used to build fetch URLs. archive.org normalizes the
# domain/case of the agdl prefix, so this single form resolves for every page.
ORIGIN_BASE = "http://artsites.ucsc.edu/GDead/agdl/"

MIRROR_DIR = Path(__file__).parent.parent / "mirror"
STATE_DIR = Path(__file__).parent.parent / ".mirror_state"
STATE_FILE = STATE_DIR / "state.json"

# Marker that identifies a URL as belonging to the AGDL site (case-insensitive).
AGDL_MARKER = "/gdead/agdl/"

# Polite rate limiting for archive.org.
MIN_DELAY = 2.0
MAX_DELAY = 4.0
SAVE_INTERVAL = 5

# Tags whose URL attribute we follow / fetch as page requisites.
LINK_ATTRS = [
    ("a", "href"),
    ("img", "src"),
    ("link", "href"),
    ("script", "src"),
    ("frame", "src"),
    ("iframe", "src"),
    ("area", "href"),
    ("input", "src"),
    ("embed", "src"),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent.parent / "mirror.log"),
    ],
)
logger = logging.getLogger(__name__)


def canonical_rel(url, page_origin):
    """Resolve a discovered URL and return its canonical AGDL-relative path.

    Returns the path of the resource relative to the agdl/ root (e.g.
    "david.html", "images/roses.gif"), or None if the URL is external, an
    anchor, or otherwise not part of the AGDL site.
    """
    if not url:
        return None
    url = url.strip()
    low = url.lower()
    if low.startswith(("#", "mailto:", "javascript:", "tel:", "data:")):
        return None

    # Resolve relative links against the page's original URL.
    absolute = urljoin(page_origin, url)
    parsed = urlparse(absolute)

    # Some archived links may point back at web.archive.org; unwrap them.
    if "web.archive.org" in parsed.netloc:
        m = re.search(r"https?://[^\s]*?" + re.escape(AGDL_MARKER), absolute, re.I)
        if not m:
            return None
        absolute = absolute[m.start():]
        parsed = urlparse(absolute)

    path = unquote(parsed.path)
    marker_idx = path.lower().find(AGDL_MARKER)
    if marker_idx == -1:
        return None

    rel = path[marker_idx + len(AGDL_MARKER):]
    rel = rel.lstrip("/")
    if rel == "" or rel.endswith("/"):
        rel += "index.html"
    return rel


def fetch_url(rel, max_retries=5):
    """Fetch an AGDL-relative resource via the archive id_ form.

    archive.org throttles bursts by dropping connections; retry those (and 5xx)
    with exponential backoff so a transient block doesn't mark a real page as
    failed. Client errors (404 etc.) fail fast -- those won't get better.
    """
    fetch = ARCHIVE_PREFIX + ORIGIN_BASE + rel
    last_exc = None
    for attempt in range(max_retries):
        time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
        try:
            resp = requests.get(fetch, timeout=45)
            resp.raise_for_status()
            return resp
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status is not None and 400 <= status < 500:
                raise
            last_exc = e
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
        backoff = 5 * (2 ** attempt) + random.uniform(0, 3)
        logger.warning("Throttled on %s; backoff %.0fs (attempt %d/%d)",
                       rel, backoff, attempt + 1, max_retries)
        time.sleep(backoff)
    raise last_exc


def is_html(resp, rel):
    """Decide whether a response should be parsed for more links."""
    ctype = resp.headers.get("Content-Type", "").lower()
    if "html" in ctype:
        return True
    if "image/" in ctype or "application/" in ctype:
        return False
    return rel.lower().endswith((".html", ".htm"))


def extract_links(content, page_origin):
    """Return the set of canonical AGDL-relative paths linked from a page."""
    soup = BeautifulSoup(content, "lxml")
    found = set()
    for tag, attr in LINK_ATTRS:
        for el in soup.find_all(tag):
            rel = canonical_rel(el.get(attr), page_origin)
            if rel:
                found.add(rel)
    return found


def save_bytes(rel, content):
    out = MIRROR_DIR / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(content)


def load_state():
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
            logger.info(
                "Loaded state: %d succeeded, %d failed, %d queued",
                len(state.get("succeeded", [])),
                len(state.get("failed", [])),
                len(state.get("queue", [])),
            )
            return state
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not load state: %s", e)
    return {"succeeded": [], "failed": [], "queue": []}


def save_state(succeeded, failed, queue):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(
            {"succeeded": sorted(succeeded), "failed": sorted(failed), "queue": queue},
            indent=2,
        )
    )


def crawl(start="gdhome.html", limit=None, retry_failed=False):
    state = load_state()
    succeeded = set(state["succeeded"])
    failed = set(state["failed"])
    queue = state["queue"] if state["queue"] else [start]

    if retry_failed:
        for rel in failed:
            if rel not in queue:
                queue.append(rel)
        failed.clear()

    logger.info(
        "Starting: %d succeeded, %d failed, %d queued (limit=%s)",
        len(succeeded), len(failed), len(queue), limit,
    )

    processed = 0
    try:
        while queue:
            if limit is not None and processed >= limit:
                logger.info("Reached limit of %d this run.", limit)
                break

            rel = queue.pop(0)
            if rel in succeeded:
                continue

            out = MIRROR_DIR / rel
            if out.exists() and rel not in failed:
                succeeded.add(rel)
                continue

            page_origin = ORIGIN_BASE + rel
            logger.info("Fetching: %s", rel)
            try:
                resp = fetch_url(rel)
            except requests.RequestException as e:
                logger.error("Failed %s: %s", rel, e)
                failed.add(rel)
                continue

            try:
                save_bytes(rel, resp.content)
            except OSError as e:
                logger.error("Could not save %s: %s", rel, e)
                failed.add(rel)
                continue

            succeeded.add(rel)
            failed.discard(rel)
            processed += 1

            if is_html(resp, rel):
                for link in extract_links(resp.content, page_origin):
                    if link not in succeeded and link not in queue:
                        queue.append(link)

            logger.info(
                "Saved %s  |  queue=%d succeeded=%d failed=%d",
                rel, len(queue), len(succeeded), len(failed),
            )

            if processed % SAVE_INTERVAL == 0:
                save_state(succeeded, failed, queue)

    except KeyboardInterrupt:
        logger.info("Interrupted; saving state.")
    finally:
        save_state(succeeded, failed, queue)
        logger.info(
            "Session ended. succeeded=%d failed=%d queued=%d",
            len(succeeded), len(failed), len(queue),
        )


def main():
    ap = argparse.ArgumentParser(description="Raw mirror crawler for AGDL archive.")
    ap.add_argument("--start", default="gdhome.html",
                    help="AGDL-relative path to start from (default: gdhome.html)")
    ap.add_argument("--limit", type=int, default=None,
                    help="Max pages to fetch this run (for testing).")
    ap.add_argument("--retry-failed", action="store_true",
                    help="Requeue previously failed URLs.")
    args = ap.parse_args()
    crawl(start=args.start, limit=args.limit, retry_failed=args.retry_failed)


if __name__ == "__main__":
    main()
