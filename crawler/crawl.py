"""Polite, cache-first BFS crawler for the Maryland Manual.

Design goals:
  * Never re-fetch. Every page is mirrored to disk under data/cache/ by its URL
    path; a warm cache makes re-runs cost zero network.
  * Never construct URLs. BFS follows only discovered links, classified by
    crawler.seeds.classify().
  * Be a good citizen: one request/second, identifying User-Agent, honor the
    fetch/record/skip dispositions.

The crawl manifest (what we fetched, status, hash, where we found it) lives in
data/cache/crawl.db so it survives manual.db rebuilds. The parse stage reads the
cache directory plus this manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from . import seeds

CACHE_DIR = Path("data/cache")
MANIFEST = CACHE_DIR / "crawl.db"
USER_AGENT = "maryland-manual-network/0.1 (dpwillis@umd.edu; journalism research)"
DELAY_SECONDS = 1.0

MANIFEST_SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    url            TEXT PRIMARY KEY,
    cache_path     TEXT,
    status         INTEGER,
    content_type   TEXT,
    sha256         TEXT,
    disposition    TEXT,      -- fetch_follow | fetch_only | record_only
    discovered_from TEXT,
    fetched_at     REAL,
    error          TEXT
);
CREATE INDEX IF NOT EXISTS idx_pages_disposition ON pages(disposition);
CREATE INDEX IF NOT EXISTS idx_pages_status ON pages(status);
"""


def cache_path_for(url: str) -> Path:
    """Mirror the URL path under CACHE_DIR. Directory URLs get index.html."""
    parsed = urlparse(url)
    path = parsed.path
    if path.endswith("/") or not path:
        path = path + "index.html"
    # Encode query into the filename so distinct queries don't collide.
    rel = path.lstrip("/")
    if parsed.query:
        qhash = hashlib.sha1(parsed.query.encode()).hexdigest()[:8]
        rel = f"{rel}.q{qhash}"
    return CACHE_DIR / rel


def open_manifest() -> sqlite3.Connection:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(MANIFEST)
    conn.executescript(MANIFEST_SCHEMA)
    return conn


def already_have(conn: sqlite3.Connection, url: str) -> bool:
    row = conn.execute(
        "SELECT cache_path, status FROM pages WHERE url = ?", (url,)
    ).fetchone()
    if not row:
        return False
    cache_path, status = row
    # A recorded 404 is a fact; don't retry.
    if status and status >= 400:
        return True
    return bool(cache_path and Path(cache_path).exists())


def extract_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        norm = seeds.normalize(a["href"], base=base_url)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def record(conn: sqlite3.Connection, url: str, **fields) -> None:
    cols = ["url", "cache_path", "status", "content_type", "sha256",
            "disposition", "discovered_from", "fetched_at", "error"]
    values = {c: fields.get(c) for c in cols}
    values["url"] = url
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "url")
    conn.execute(
        f"INSERT INTO pages ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(url) DO UPDATE SET {updates}",
        [values[c] for c in cols],
    )
    conn.commit()


def crawl(profile: str, limit: int | None = None, refresh: bool = False) -> None:
    conn = open_manifest()
    client = httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=30.0,
    )

    queue: deque[tuple[str, str]] = deque()
    enqueued: set[str] = set()
    for url in seeds.seed_urls(profile):
        norm = seeds.normalize(url)
        if norm and norm not in enqueued:
            enqueued.add(norm)
            queue.append((norm, "seed"))

    fetched = 0
    last_request = 0.0

    while queue:
        if limit is not None and fetched >= limit:
            print(f"Hit limit={limit}, stopping.")
            break

        url, source = queue.popleft()
        disposition = seeds.classify(url)

        if disposition in ("record_only", "skip"):
            record(conn, url, disposition=disposition, discovered_from=source)
            continue

        # fetch_follow or fetch_only
        cpath = cache_path_for(url)
        if not refresh and already_have(conn, url):
            # Use cached copy to discover links (only if we follow).
            if disposition == "fetch_follow" and cpath.exists():
                html = cpath.read_text(errors="replace")
                for link in extract_links(html, url):
                    if link not in enqueued:
                        enqueued.add(link)
                        queue.append((link, url))
            continue

        # Rate limit.
        elapsed = time.monotonic() - last_request
        if elapsed < DELAY_SECONDS:
            time.sleep(DELAY_SECONDS - elapsed)
        last_request = time.monotonic()

        try:
            resp = client.get(url)
        except httpx.HTTPError as e:
            record(conn, url, status=0, disposition=disposition,
                   discovered_from=source, fetched_at=time.time(), error=str(e))
            print(f"  ERR {url}: {e}", file=sys.stderr)
            continue

        fetched += 1
        ctype = resp.headers.get("content-type", "")
        body = resp.text if "text" in ctype or "html" in ctype else ""
        sha = hashlib.sha256(resp.content).hexdigest()

        if resp.status_code == 200 and body:
            cpath.parent.mkdir(parents=True, exist_ok=True)
            cpath.write_text(body, errors="replace")
            record(conn, url, cache_path=str(cpath), status=200,
                   content_type=ctype, sha256=sha, disposition=disposition,
                   discovered_from=source, fetched_at=time.time())
            print(f"[{fetched:5d}] {resp.status_code} {url}")
            if disposition == "fetch_follow":
                for link in extract_links(body, url):
                    if link not in enqueued:
                        enqueued.add(link)
                        queue.append((link, url))
        else:
            record(conn, url, status=resp.status_code, content_type=ctype,
                   sha256=sha, disposition=disposition, discovered_from=source,
                   fetched_at=time.time())
            print(f"[{fetched:5d}] {resp.status_code} {url}", file=sys.stderr)

    client.close()
    total = conn.execute("SELECT COUNT(*) FROM pages WHERE status=200").fetchone()[0]
    print(f"\nDone. {fetched} fetched this run; {total} cached 200s total; "
          f"{len(enqueued)} URLs seen.")
    conn.close()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Crawl the Maryland Manual.")
    ap.add_argument("--profile", default="mvp", choices=list(seeds.PROFILES))
    ap.add_argument("--limit", type=int, default=None,
                    help="Max pages to fetch this run (for testing).")
    ap.add_argument("--refresh", action="store_true",
                    help="Re-fetch even if cached.")
    args = ap.parse_args(argv)
    crawl(args.profile, limit=args.limit, refresh=args.refresh)


if __name__ == "__main__":
    main()
