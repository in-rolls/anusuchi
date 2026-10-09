"""Read West Bengal's State List of OBCs into one row per class name.

Two editions, read by two different routes because they were made two different
ways.

**The notification-wise list of 3 June 2025** is an Excel sheet printed to PDF
by the Backward Classes Welfare Department. It has a real text layer and ruled
cells, so `extract_tables` returns serial, class and notification exactly as
typed. It numbers 64 pre-2010 classes followed by the 2025 additions.

**Notification No. 945-BCW/MR-23/2026 of 18 May 2026** is the list in force: the
66 pre-2010 classes the Calcutta High Court left standing on 22 May 2024, after
the 2025 additions were withdrawn by No. 944 the same day. It exists only as
scans with a machine OCR layer, and the OCR is poor where it matters:

     2 Baisirya Kapali        (Baishya Kapali)
    28 r\\.oniwar/Rauniyar     (Roniwar/Rauniyar)
    t4 Satchasi               (14)

So the gazette is not trusted for spelling. It is trusted for *which* classes
and in *what order*, and each entry is matched to the department's typed 2025
text, which is where its spelling comes from. Three things keep that honest:

- `entry_no` is the line's position, and every number the OCR did read cleanly
  must equal it. A dropped or doubled line breaks that immediately.
- The department's own copy of No. 945 is a separate scan with its own OCR
  errors. Both copies are matched independently and must pick the same 2025
  class at every position. They share this code but not a single byte.
- Every match carries its similarity score in `lists/wb_obc_reconcile.tsv`, and
  an entry with no close 2025 counterpart keeps its OCR text, flagged, rather
  than being forced onto the nearest name.

**Synonyms.** As with the ST Order, the list supplies its own aliases and the
table is at synonym grain. Top-level commas and slashes separate names
(`Keori/Koiri`, `Teli, Kolu`). Parentheses are not split: what they hold goes
verbatim into `qualifier`, because the list uses them for two different things,
aliases (`Gope (Pallav Gope, Ballav Gope, ...)`, `Rayeen (Kunjra)`) and
conditions (`Hajjam (Muslim)`, `Dhobi (other than those included in the list
of Scheduled Castes)`), and telling those apart is a judgment this step does
not make. `(including X)` is the one exception, read as an alias the same way
the ST parser reads it.

Run:

    python scripts/05_parse_wb_obc.py

Writes `lists/wb_obc_entries.tsv`, `lists/wb_obc_reconcile.tsv` and
`lists/wb_obc_parse_report.tsv`.
"""

from __future__ import annotations

import csv
import difflib
import re
import sys
from pathlib import Path

import pdfplumber

HERE = Path(__file__).resolve().parent.parent
MANIFEST = HERE / "sources/manifest.tsv"
RAW = HERE / "sources/raw"
ENTRIES = HERE / "lists/wb_obc_entries.tsv"
RECONCILE = HERE / "lists/wb_obc_reconcile.tsv"
REPORT = HERE / "lists/wb_obc_parse_report.tsv"

TYPED = "wb_obc_list-076"
GAZETTE = "wb_obc_list-077"
DEPARTMENT_COPY = "wb_obc_list-078"
GAZETTE_SIZE = 66

# Below this the OCR line is not confidently the same class as any typed name.
# The worst true match in the current scans is well above it; see the
# reconcile table, which reports every score so this can be audited.
MATCH_FLOOR = 0.75

# The number column of both scans sits left of x=130 points; class names are
# centred well to the right of it. A line starting in the number column opens
# an entry, anything else continues the open one.
NUMBER_COLUMN = 130.0
RUNNING_HEAD = re.compile(r"AZ\S*\s*\S*TTE|^Page \d+ of \d+$")
DATED = re.compile(r"(\d{1,2})-(\d{1,2})-(\d{4})")

FIELDS = [
    "edition_id",
    "notified_date",
    "category",
    "jurisdiction",
    "entry_no",
    "synonym",
    "synonym_rank",
    "qualifier",
    "name",
    "name_as_printed",
    "name_source_id",
    "notification",
    "source_id",
    "page",
]


def manifest() -> dict[str, dict]:
    """Return the newest fetched manifest row for each source.

    Returns:
        Manifest rows keyed by source_id, only those that have bytes.
    """
    with MANIFEST.open(encoding="utf8") as handle:
        rows = [r for r in csv.DictReader(handle, delimiter="\t") if r.get("sha256")]
    return {r["source_id"]: r for r in sorted(rows, key=lambda r: r["fetched_at"])}


def notified_date(title: str) -> str:
    """Return the ISO date a registry title states as `(dd-mm-yyyy)`.

    Args:
        title: The registry title.

    Returns:
        An ISO date, or an empty string.
    """
    found = DATED.search(title)
    if not found:
        return ""
    day, month, year = found.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def squash(text: str | None) -> str:
    """Collapse whitespace, including the newlines a wrapped cell carries.

    Args:
        text: Raw cell or line text.

    Returns:
        Single-spaced text.
    """
    return " ".join((text or "").split())


def read_typed(path: Path) -> list[dict]:
    """Read the department's typed notification-wise list.

    Args:
        path: The PDF.

    Returns:
        One dict per numbered class with entry_no, name, notification, page.
    """
    rows = []
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            for table in page.extract_tables():
                for cells in table:
                    serial = squash(cells[0])
                    if not serial.isdigit():
                        continue
                    rows.append(
                        {
                            "entry_no": int(serial),
                            "name": squash(cells[1]),
                            "notification": squash(cells[2]),
                            "page": number,
                        }
                    )
    return rows


def read_scan(path: Path) -> list[dict]:
    """Read the numbered list out of an OCR'd scan of No. 945.

    Args:
        path: The PDF.

    Returns:
        One dict per entry in printed order, with the number as the OCR read it,
        the OCR name, and the page.
    """
    entries: list[dict] = []
    inside = False
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            for line in page.extract_text_lines():
                text = line["text"].strip()
                if text == "LIST":
                    inside = True
                    continue
                if not inside or RUNNING_HEAD.search(text):
                    continue
                if text.startswith("By order"):
                    inside = False
                    continue
                if line["x0"] < NUMBER_COLUMN:
                    head, _, rest = text.partition(" ")
                    entries.append({"number_as_read": head, "ocr": rest.strip(), "page": number})
                elif entries:
                    entries[-1]["ocr"] = f"{entries[-1]['ocr']} {text}".strip()
    # A stray mark in the number column (a lone `I` under a running head) opens
    # an entry with no name. It is not a class.
    return [e for e in entries if e["ocr"]]


def letters(text: str) -> str:
    """Return the lowercase letters of a name, for OCR-tolerant comparison.

    Args:
        text: A class name.

    Returns:
        Letters only.
    """
    return re.sub(r"[^a-z]", "", text.lower())


def match(scan: list[dict], typed: list[dict]) -> list[tuple[dict | None, float]]:
    """Pair each scanned entry with a typed class, one-to-one, best scores first.

    Args:
        scan: Entries read from a scan.
        typed: Classes read from the typed list.

    Returns:
        For each scanned entry, its typed class (or None) and the similarity.
    """
    scores = sorted(
        (
            (difflib.SequenceMatcher(None, letters(s["ocr"]), letters(t["name"])).ratio(), i, j)
            for i, s in enumerate(scan)
            for j, t in enumerate(typed)
        ),
        reverse=True,
    )
    paired: dict[int, tuple[dict | None, float]] = {}
    taken = set()
    for score, i, j in scores:
        if i in paired or j in taken:
            continue
        if score < MATCH_FLOOR:
            break
        paired[i] = (typed[j], score)
        taken.add(j)
    best = {
        i: max(
            difflib.SequenceMatcher(None, letters(s["ocr"]), letters(t["name"])).ratio()
            for t in typed
        )
        for i, s in enumerate(scan)
        if i not in paired
    }
    return [paired.get(i, (None, best.get(i, 0.0))) for i in range(len(scan))]


def split_names(name: str) -> list[tuple[str, str]]:
    """Split a class into its printed names, keeping parentheses as qualifiers.

    Args:
        name: The class as printed.

    Returns:
        (synonym, qualifier) pairs in printed order.
    """
    name = re.sub(r"\(\s*including ([^()]*)\)", r", \1", name, flags=re.I)
    parts, depth, current = [], 0, ""
    for char in name:
        depth += char == "("
        depth -= char == ")"
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    names = []
    for part in parts:
        qualifier = "; ".join(squash(q) for q in re.findall(r"\(([^()]*)\)", part))
        base = re.sub(r"\([^()]*\)", " ", part)
        for variant in base.split("/"):
            variant = squash(variant).strip(" .,;")
            if variant:
                names.append((variant, qualifier))
    return names


def explode(base: dict, name: str) -> list[dict]:
    """Return synonym-grain rows for one class.

    Args:
        base: The fields every row of this class shares.
        name: The class name to split.

    Returns:
        One row per printed name.
    """
    pairs = split_names(name) or [(name, "")]
    return [
        {**base, "synonym": synonym, "synonym_rank": rank, "qualifier": qualifier}
        for rank, (synonym, qualifier) in enumerate(pairs, 1)
    ]


def main() -> None:
    """Parse both editions, reconcile the scans, and write the three tables."""
    sources = manifest()
    missing = [s for s in (TYPED, GAZETTE, DEPARTMENT_COPY) if s not in sources]
    if missing:
        sys.exit(f"not fetched: {', '.join(missing)}; run scripts/01_fetch_sources.py first")

    typed_row = sources[TYPED]
    typed = read_typed(RAW / typed_row["stored_as"])
    serials = [r["entry_no"] for r in typed]
    if serials != list(range(1, len(typed) + 1)):
        sys.exit(f"typed list serials are not 1..{len(typed)}: {serials}")

    scans = {s: read_scan(RAW / sources[s]["stored_as"]) for s in (GAZETTE, DEPARTMENT_COPY)}
    for source_id, entries in scans.items():
        if len(entries) != GAZETTE_SIZE:
            sys.exit(f"{source_id}: read {len(entries)} entries, the notification says 66")
        # Every number the OCR read cleanly must be the entry's position.
        clashes = [
            (position, e["number_as_read"])
            for position, e in enumerate(entries, 1)
            if e["number_as_read"].isdigit() and int(e["number_as_read"]) != position
        ]
        print(f"{source_id}: legible numbers off position: {clashes or 'none'}", file=sys.stderr)

    matched = {s: match(entries, typed) for s, entries in scans.items()}

    rows = []
    for record in typed:
        base = {
            "edition_id": TYPED,
            "notified_date": notified_date(typed_row["title"]),
            "category": "OBC",
            "jurisdiction": "West Bengal",
            "entry_no": record["entry_no"],
            "name": record["name"],
            "name_as_printed": record["name"],
            "name_source_id": TYPED,
            "notification": record["notification"],
            "source_id": TYPED,
            "page": record["page"],
        }
        rows.extend(explode(base, record["name"]))

    reconcile = []
    gazette_row = sources[GAZETTE]
    for position, (entry, copy) in enumerate(zip(scans[GAZETTE], scans[DEPARTMENT_COPY]), 1):
        typed_match, score = matched[GAZETTE][position - 1]
        copy_match, copy_score = matched[DEPARTMENT_COPY][position - 1]
        name = typed_match["name"] if typed_match else entry["ocr"]
        base = {
            "edition_id": GAZETTE,
            "notified_date": notified_date(gazette_row["title"]),
            "category": "OBC",
            "jurisdiction": "West Bengal",
            "entry_no": position,
            "name": name,
            "name_as_printed": entry["ocr"],
            "name_source_id": TYPED if typed_match else GAZETTE,
            "notification": "",
            "source_id": GAZETTE,
            "page": entry["page"],
        }
        rows.extend(explode(base, name))
        same = (typed_match or {}).get("entry_no") == (copy_match or {}).get("entry_no")
        reconcile.append(
            {
                "entry_no": position,
                "gazette_number_as_read": entry["number_as_read"],
                "gazette_ocr": entry["ocr"],
                "gazette_score": f"{score:.3f}",
                "copy_number_as_read": copy["number_as_read"],
                "copy_ocr": copy["ocr"],
                "copy_score": f"{copy_score:.3f}",
                "typed_entry_no": typed_match["entry_no"] if typed_match else "",
                "typed_name": typed_match["name"] if typed_match else "",
                "copies_agree": str(same).lower(),
            }
        )

    ENTRIES.parent.mkdir(parents=True, exist_ok=True)
    with ENTRIES.open("w", encoding="utf8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with RECONCILE.open("w", encoding="utf8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(reconcile[0]), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(reconcile)

    summary = []
    for edition in (TYPED, GAZETTE):
        mine = [r for r in rows if r["edition_id"] == edition]
        summary.append(
            {
                "edition_id": edition,
                "notified_date": mine[0]["notified_date"],
                "n_entries": len({r["entry_no"] for r in mine}),
                "n_synonyms": len(mine),
                "n_qualified": sum(1 for r in mine if r["qualifier"]),
                "n_names_from_ocr": len(
                    {r["entry_no"] for r in mine if r["name_source_id"] == GAZETTE}
                ),
            }
        )
    with REPORT.open("w", encoding="utf8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(summary[0]), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(summary)

    disagree = [r["entry_no"] for r in reconcile if r["copies_agree"] != "true"]
    print(f"{len(rows):,} synonym rows -> {ENTRIES}", file=sys.stderr)
    for line in summary:
        print(
            f"  {line['edition_id']:<18} {line['notified_date']}  {line['n_entries']:>3} classes"
            f"  {line['n_synonyms']:>4} names  {line['n_names_from_ocr']} from OCR",
            file=sys.stderr,
        )
    print(f"  scans disagree at: {disagree or 'none'}", file=sys.stderr)


if __name__ == "__main__":
    main()
