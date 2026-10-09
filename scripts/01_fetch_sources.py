"""Fetch every source in the registry, archive it, and record what happened.

This step acquires bytes and nothing else. It does not parse, clean, or
interpret. That separation is the point: `sources/raw/` is what a government
published, `lists/` is what we read out of it, and `crosswalks/` is what a
person decided. Only the last of those three involves judgment, and keeping the
first two mechanical is what makes the third auditable.

Three things it does that a plain download loop would not.

**It records the archive, both directions.** For every URL it asks the Wayback
Machine for the newest capture and writes it to the manifest, so a citation
stays resolvable after the site changes. Where there is no capture it submits
one. This is not belt-and-braces: `socialjustice.gov.in` was refusing
connections when this pipeline was written, and every Scheduled Castes document
here -- the consolidated Order and the amendment trail back to 1936 -- was
recovered from Wayback rather than from the live site.

**It records failures as rows.** A source that will not download gets a manifest
row with its status and no checksum, rather than being missing. A gap you can
see is a gap you can chase.

**It never overwrites.** Bytes land under their own SHA-256, so a republished
document is a new file and a new row beside the old one, not a silent
replacement. Which jatis were scheduled when is a question the store should be
able to answer, and it cannot answer it if editions overwrite each other.

`tribal.nic.in` does not present a complete certificate chain, so verification
is disabled for it and the manifest says so in `tls_verified`. For legal
reference data an unverified channel is a fact to record, not to hide; the
checksum and the independent entry-count check in step 03 are what stand in
for it.

Run:

    python scripts/01_fetch_sources.py [--limit N] [--kind st_list_current]

Writes `sources/raw/<sha256>.<ext>` and `sources/manifest.tsv`.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests
import urllib3
from wayback import WaybackClient, WaybackSession
from wayback.exceptions import WaybackException

HERE = Path(__file__).resolve().parent.parent
REGISTRY = HERE / "sources/registry.tsv"
RAW = HERE / "sources/raw"
MANIFEST = HERE / "sources/manifest.tsv"

# Hosts whose certificate chain does not validate. Listed explicitly rather
# than disabling verification globally, so the exception stays visible and the
# manifest can record which rows it applied to.
UNVERIFIED_HOSTS = {"tribal.nic.in"}

# The archive answers a burst with 429 and a Retry-After header.
RATE_LIMIT_RETRIES = 4
RATE_LIMIT_WAIT = 60.0

# Captures are looked up in the CDX index through the `wayback` library, as in
# step 02. The `wayback/available` endpoint answered "no capture" for 4 of 6
# PDFs that CDX listed, a different 4 on each run; and a hand-built CDX call
# reads the archive's HTTP 200 "Temporarily Offline" page as no capture, where
# the library raises and retries. CDX itself takes 10 to 50 seconds to answer.
ARCHIVE_TIMEOUT = 120
SAVE = "https://web.archive.org/save/"
UA = "anusuchi/0.1 (statutory caste list archive; research use)"

FIELDS = [
    "source_id",
    "kind",
    "capture_timestamp",
    "authority",
    "publisher",
    "title",
    "url",
    "fetched_at",
    "http_status",
    "n_bytes",
    "sha256",
    "content_type",
    "stored_as",
    "tls_verified",
    "wayback_url",
    "wayback_timestamp",
    "note",
]


def read_registry() -> list[dict]:
    """Return the curated list of sources to acquire.

    Returns:
        One dict per registry row.
    """
    with REGISTRY.open(encoding="utf8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def wayback_snapshot(url: str, archive: WaybackClient) -> tuple[str, str]:
    """Return the newest Wayback capture of a URL.

    Args:
        url: The original URL.
        archive: A Wayback client.

    Returns:
        The capture URL and its timestamp, or two empty strings.
    """
    try:
        records = list(archive.search(url, limit=-1, filter_field="statuscode:200"))
    except WaybackException:
        return "", ""
    if not records:
        return "", ""
    timestamp = records[-1].timestamp.strftime("%Y%m%d%H%M%S")
    return f"http://web.archive.org/web/{timestamp}/{url}", timestamp


def request_archive(url: str, session: requests.Session) -> None:
    """Ask the Wayback Machine to capture a URL that it has never seen.

    Failure is not an error: Save Page Now rate-limits and times out, and a
    source without a capture is recorded as such rather than retried forever.

    Args:
        url: The original URL.
        session: A requests session.
    """
    try:
        session.get(SAVE + url, timeout=45, headers={"User-Agent": UA})
    except requests.RequestException:
        pass


def extension_for(url: str, content_type: str) -> str:
    """Return the file extension to store bytes under.

    Args:
        url: The source URL.
        content_type: The response content type.

    Returns:
        An extension including the leading dot.
    """
    if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
        return ".pdf"
    if "html" in content_type.lower():
        return ".html"
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return suffix if 1 < len(suffix) <= 5 else ".bin"


def fetch_one(row: dict, session: requests.Session, archive: WaybackClient) -> dict:
    """Acquire one source and return its manifest row.

    Args:
        row: A registry row.
        session: A requests session.
        archive: A Wayback client.

    Returns:
        The manifest row, with empty checksum fields when the fetch failed.
    """
    url = row["url"]
    # A registry row may pin a capture. Superseded editions live at URLs the
    # publisher later reused: `LatestListofScheduledtribes.pdf` held one ST list
    # from 2017 to 2020 and a different one from 2021, so fetching it live gets
    # today's edition twice and the history never. Pinning the capture is the
    # only way to get the bytes that were there then.
    capture = (row.get("capture_timestamp") or "").strip()
    host = urllib.parse.urlparse(url).netloc
    verify = host not in UNVERIFIED_HOSTS
    record = dict(row)
    record.update(
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        tls_verified=str(verify).lower(),
        http_status="",
        n_bytes="",
        sha256="",
        content_type="",
        stored_as="",
        note="",
    )

    body = b""
    attempts = [f"http://web.archive.org/web/{capture}id_/{url}"] if capture else [url, ""]
    for attempt, target in enumerate(attempts):
        if capture:
            record["note"] = f"pinned to capture {capture}"
        elif attempt == 1:
            # The live site failed. Fall back to the archive, which is why the
            # archive is queried for every source rather than only for the
            # ones that happen to break.
            target, _ = wayback_snapshot(url, archive)
            if not target:
                record["note"] = "live fetch failed and no wayback capture"
                break
            record["note"] = "recovered from wayback"
        for _ in range(RATE_LIMIT_RETRIES):
            try:
                response = session.get(
                    target, timeout=120, verify=verify, headers={"User-Agent": UA}
                )
            except requests.RequestException as error:
                record["http_status"] = "0"
                record["note"] = type(error).__name__
                break
            record["http_status"] = str(response.status_code)
            record["content_type"] = response.headers.get("content-type", "").split(";")[0]
            if response.ok and response.content:
                body = response.content
                break
            # The archive rate-limits with 429 and names the wait in a header.
            # Treating that as a dead source loses the document; waiting costs
            # a minute and keeps it.
            if response.status_code != 429:
                break
            wait = float(response.headers.get("retry-after", RATE_LIMIT_WAIT))
            record["note"] = f"rate limited, waited {wait:.0f}s"
            print(f"      429; sleeping {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)
        if body:
            break

    if body:
        digest = hashlib.sha256(body).hexdigest()
        stored = RAW / f"{digest}{extension_for(url, record['content_type'])}"
        if not stored.exists():
            stored.write_bytes(body)
        record.update(n_bytes=str(len(body)), sha256=digest, stored_as=stored.name)

    wayback_url, wayback_timestamp = wayback_snapshot(url, archive)
    if not wayback_url:
        request_archive(url, session)
        wayback_url, wayback_timestamp = wayback_snapshot(url, archive)
    record.update(wayback_url=wayback_url, wayback_timestamp=wayback_timestamp)
    return record


def main() -> None:
    """Fetch the registry into `sources/raw/` and write the manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--kind", help="only fetch sources of this kind")
    parser.add_argument("--pause", type=float, default=1.0)
    arguments = parser.parse_args()

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    RAW.mkdir(parents=True, exist_ok=True)

    rows = read_registry()
    if arguments.kind:
        rows = [r for r in rows if r["kind"] == arguments.kind]
    if arguments.limit:
        rows = rows[: arguments.limit]

    # Re-running must not lose earlier rows: a source that fetched last week and
    # 404s today is still evidence, and the byte store is keyed on the digest so
    # nothing is overwritten either way.
    existing = []
    if MANIFEST.exists():
        with MANIFEST.open(encoding="utf8") as handle:
            existing = list(csv.DictReader(handle, delimiter="\t"))
    already = {(r["source_id"], r["sha256"]) for r in existing if r.get("sha256")}

    session = requests.Session()
    archive = WaybackClient(
        session=WaybackSession(retries=6, backoff=2, timeout=ARCHIVE_TIMEOUT, user_agent=UA)
    )
    written = []
    for index, row in enumerate(rows, 1):
        record = fetch_one(row, session, archive)
        key = (record["source_id"], record["sha256"])
        # A lookup that comes back empty is not evidence the capture is gone;
        # the archive's index is intermittent. Keep the one already on record.
        known = next((r for r in existing if (r["source_id"], r["sha256"]) == key), None)
        if known and known.get("wayback_url") and not record["wayback_url"]:
            record.update(
                wayback_url=known["wayback_url"], wayback_timestamp=known["wayback_timestamp"]
            )
        if record["sha256"] and key in already:
            record["note"] = (record["note"] + " unchanged").strip()
        else:
            written.append(record)
        status = record["http_status"] or "--"
        size = f"{int(record['n_bytes']):,}" if record["n_bytes"] else "no bytes"
        print(
            f"{index:>3}/{len(rows)} {record['source_id']:<24} {status:>3} {size:>12}"
            f"  {record['note']}",
            file=sys.stderr,
        )
        existing = [r for r in existing if (r["source_id"], r["sha256"]) != key]
        existing.append(record)
        time.sleep(arguments.pause)

    with MANIFEST.open("w", encoding="utf8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(sorted(existing, key=lambda r: (r["source_id"], r["fetched_at"])))

    got = sum(1 for r in existing if r.get("sha256"))
    print(
        f"\n{len(existing)} manifest rows, {got} with bytes, "
        f"{len(existing) - got} unresolved; {len(written)} new this run",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
