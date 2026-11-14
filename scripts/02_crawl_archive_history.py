"""Walk the archive's captures of each index page and recover what it once linked.

Step 01 uses the Wayback Machine as a fallback: it asks for the closest capture
of a URL and fetches that when the live site fails. This step uses it as a
record. Those are different questions -- "can I still get this document" and
"what did this page say in 2022" -- and only the second recovers editions the
government has since taken down.

**Documents are not versioned in place, so do not look for them there.** The
consolidated Scheduled Castes Order at `.../upload/44641758177828.pdf` has
fourteen captures and one digest. It has never changed and never will: the
ministry mints a new URL for each edition rather than replacing bytes. Diffing a
document URL across its captures finds nothing, every time, and that is a fact
about how the publisher works rather than about the archive.

**The index pages are where change lives.** `socialjustice.gov.in/common/76750`
has captures going back years and they differ. Each version links to whatever was
current on that date, so the union of those links across time is the set of
documents the ministry has ever published there. The 2022 capture alone carries
29 PDF URLs the live page no longer mentions, because the site migrated readable
paths (`GOI-SC-ORDER-1936.pdf`) to opaque numeric ones (`82951673327147.PDF`).

Captures are collapsed on digest, so a page that sat unchanged for a year is
fetched once rather than fifty times.

Search goes through the `wayback` library rather than hand-built CDX calls. The
first version of this step built its own, and the archive answers an outage with
HTTP 200 and an HTML body reading "Internet Archive: Temporarily Offline";
parsed for timestamps that yields nothing, which is indistinguishable from a URL
that was never captured, and it silently turned three index pages into zero. The
library raises instead, and brings retries and rate limiting with it.

This step writes `sources/discovered.tsv` and nothing else. Promoting a
discovered URL into the registry is a separate decision behind `--promote`, and
fetching is still step 01's job.

Run:

    python scripts/02_crawl_archive_history.py [--limit N] [--promote]
"""

from __future__ import annotations

import argparse
import csv
import html
import re
import sys
import urllib.parse
from collections import defaultdict
from pathlib import Path

from wayback import WaybackClient, WaybackSession

HERE = Path(__file__).resolve().parent.parent
INDEX_PAGES = HERE / "sources/index_pages.tsv"
REGISTRY = HERE / "sources/registry.tsv"
DISCOVERED = HERE / "sources/discovered.tsv"

UA = "anusuchi/0.1 (statutory caste list archive; research use)"

# Only documents are worth recovering. A capture links to hundreds of navigation
# targets, and following those would crawl the ministry rather than read it.
DOCUMENT = re.compile(r"\.(pdf|doc|docx|xls|xlsx)$", re.I)

LINK = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
WAYBACK_PREFIX = re.compile(r"^(?:https?://web\.archive\.org)?/web/\d+\w*/")

FIELDS = [
    "url",
    "title_as_linked",
    "index_page",
    "first_seen",
    "last_seen",
    "n_captures",
    "in_registry",
]


def read_tsv(path: Path) -> list[dict]:
    """Return a TSV as a list of dicts.

    Args:
        path: The file to read.

    Returns:
        One dict per row, or an empty list when the file is absent.
    """
    if not path.exists():
        return []
    with path.open(encoding="utf8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def normalize(url: str) -> str:
    """Return a URL in the form used to compare against the registry.

    Args:
        url: Any absolute URL.

    Returns:
        The URL without its scheme, so http and https forms compare equal.
    """
    return re.sub(r"^https?://", "", url).strip()


def documents_in(body: str, page_url: str) -> list[tuple[str, str]]:
    """Return the document links in one archived page.

    Links are resolved against the page they were found on. Half the sources
    write them relative -- `tribal.nic.in` links its ST lists as
    `downloads/Statistics/ListofPVTGs191212.pdf` -- and recording those as-is
    produced one usable URL per capture across six hundred captures, because a
    bare relative path matches nothing and fetches nothing.

    Args:
        body: The archived page's HTML.
        page_url: The original URL of the page, for resolving relative links.

    Returns:
        One `(absolute document url, link text)` pair per document linked.
    """
    found = []
    for match in LINK.finditer(body):
        href = WAYBACK_PREFIX.sub("", html.unescape(match.group(1)))
        if not DOCUMENT.search(urllib.parse.urlparse(href).path):
            continue
        href = urllib.parse.urljoin(page_url, href)
        text = " ".join(html.unescape(re.sub(r"<[^>]*>", "", match.group(2))).split())
        found.append((href, text))
    return found


def crawl(page: dict, client: WaybackClient, limit: int | None) -> dict[str, dict]:
    """Read every distinct capture of one index page.

    Args:
        page: A row of `sources/index_pages.tsv`.
        client: An open Wayback client.
        limit: Stop after this many captures, or None for all of them.

    Returns:
        One record per document URL the page has ever linked to.
    """
    url = page["url"]
    records = list(client.search(url, filter_field="statuscode:200", collapse="digest"))
    records.sort(key=lambda record: record.timestamp)
    if limit:
        records = records[:limit]
    print(f"{page['index_id']:<12} {len(records):>3} distinct captures", file=sys.stderr)

    stamps: dict[str, list[str]] = defaultdict(list)
    titles: dict[str, str] = {}
    for position, record in enumerate(records, 1):
        when = record.timestamp.strftime("%Y%m%d%H%M%S")
        try:
            memento = client.get_memento(record, exact=False)
            body = memento.text
        except Exception as error:  # noqa: BLE001
            # A single unplayable capture is not a reason to lose the rest, but
            # it is a reason to say so rather than to record nothing.
            print(f"  {position:>3}/{len(records)} {when}  unplayable: {error}", file=sys.stderr)
            continue
        for document, text in documents_in(body, url):
            stamps[document].append(when)
            # Keep the longest link text seen: the old readable paths carry
            # better titles than the numeric ones that replaced them.
            if len(text) > len(titles.get(document, "")):
                titles[document] = text
        print(
            f"  {position:>3}/{len(records)} {when}  {len(stamps):>4} urls so far",
            file=sys.stderr,
        )

    return {
        document: {
            "url": document,
            "title_as_linked": titles.get(document, ""),
            "index_page": page["index_id"],
            "first_seen": min(seen),
            "last_seen": max(seen),
            "n_captures": str(len(seen)),
        }
        for document, seen in stamps.items()
    }


def promote(rows: list[dict], registry: list[dict]) -> int:
    """Append URLs that are not already registered.

    Args:
        rows: Discovered rows not present in the registry.
        registry: The registry as it stands.

    Returns:
        How many rows were appended.
    """
    added, taken = [], set()
    start = len(registry)
    for row in rows:
        key = normalize(row["url"])
        if key in taken:
            continue
        taken.add(key)
        start += 1
        added.append(
            {
                "source_id": f"discovered-{start:03d}",
                "kind": "discovered",
                "authority": "primary",
                "publisher": urllib.parse.urlparse(row["url"]).netloc,
                "title": row["title_as_linked"]
                or Path(urllib.parse.urlparse(row["url"]).path).name,
                "url": row["url"],
            }
        )
    with REGISTRY.open("a", encoding="utf8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["source_id", "kind", "authority", "publisher", "title", "url"],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writerows(added)
    return len(added)


def main() -> None:
    """Crawl each index page's captures and record what they linked to."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="captures per index page")
    parser.add_argument("--promote", action="store_true")
    arguments = parser.parse_args()

    pages = read_tsv(INDEX_PAGES)
    if not pages:
        raise SystemExit(f"no index pages listed in {INDEX_PAGES}")
    registry = read_tsv(REGISTRY)
    known = {normalize(r["url"]) for r in registry}

    session = WaybackSession(retries=6, backoff=2, timeout=90, user_agent=UA)
    seen: dict[tuple[str, str], dict] = {}
    with WaybackClient(session=session) as client:
        for page in pages:
            for document, record in crawl(page, client, arguments.limit).items():
                record["in_registry"] = str(normalize(document) in known).lower()
                seen[(normalize(document), page["index_id"])] = record

    rows = sorted(seen.values(), key=lambda r: (r["index_page"], r["first_seen"], r["url"]))
    DISCOVERED.parent.mkdir(parents=True, exist_ok=True)
    with DISCOVERED.open("w", encoding="utf8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)

    fresh = [r for r in rows if r["in_registry"] == "false"]
    print(
        f"\n{len(rows):,} document urls across {len(pages)} index pages; "
        f"{len(fresh):,} not in the registry -> {DISCOVERED}",
        file=sys.stderr,
    )
    if arguments.promote and fresh:
        print(
            f"appended {promote(fresh, registry):,} urls to {REGISTRY}; re-run step 01",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
