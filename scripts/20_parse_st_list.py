"""Read the Constitution (Scheduled Tribes) Order into one row per entry.

Mechanical, and deliberately so. This step decides nothing: it turns a PDF the
government published into the same content as rows, so that the crosswalk in
step 30 can cite a numbered entry rather than an opinion. Anything requiring
judgment belongs downstream, and anything this step cannot read is reported
rather than guessed at.

The Order is printed in two columns, English on the left and Hindi on the
right, with the entry number repeated in each. `extract_text` interleaves them,
which is why this reads word positions and splits on the column gap instead.
The split is found per page as the widest empty vertical band in the middle
third, rather than hardcoded, because the gutter moves between pages.

Entries wrap over several lines and carry their synonyms inline:

    5. Bhottada, Dhotada, Bhotra, Bhatra, Bhattara, Bhotora, Bhatara

All seven of those are one gazetted tribe, entry 5 for Odisha. That comma list
is the Order supplying its own alias table, and it is what makes matching a
recorded jati label tractable later without inventing synonyms of our own.

Run:

    python scripts/20_parse_st_list.py [--source-id st_list_current-072]

Writes `lists/st_entries.tsv`: state, entry_no, name_as_printed, synonyms,
source_id, page.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path

import pdfplumber

HERE = Path(__file__).resolve().parent.parent
MANIFEST = HERE / "sources/manifest.tsv"
RAW = HERE / "sources/raw"
OUT = HERE / "lists/st_entries.tsv"

# A state heading is matched against the fixed set of States and Union
# Territories, not against a shape. An earlier version accepted any capitalized
# line without a number, which read the wrapped continuation "Bhuyan" -- the
# tail of Odisha's entry 6 -- as the start of a new state, and produced 53
# states and 6 Odisha entries against a true 62. The set is public and
# closed, so there is no reason to guess.
# Headings are matched against the fixed set of States and Union Territories,
# canonicalised, because neither the printed spelling nor the shape can be
# trusted. Two failures drove this. Accepting any capitalized unnumbered line
# read the wrapped continuation "Bhuyan" -- the tail of Odisha's entry 6 -- as a
# new state, giving 53 states and 6 Odisha entries against a true 64. And the
# Order misspells Uttarakhand as "Uttrakhand", so a set holding only the correct
# spelling lost a whole State whose five tribes were in the document all along.
CANONICAL = {
    "andhra pradesh": "Andhra Pradesh",
    "arunachal pradesh": "Arunachal Pradesh",
    "assam": "Assam",
    "bihar": "Bihar",
    "chhattisgarh": "Chhattisgarh",
    "chattisgarh": "Chhattisgarh",
    "goa": "Goa",
    "gujarat": "Gujarat",
    "haryana": "Haryana",
    "himachal pradesh": "Himachal Pradesh",
    "jharkhand": "Jharkhand",
    "karnataka": "Karnataka",
    "kerala": "Kerala",
    "madhya pradesh": "Madhya Pradesh",
    "maharashtra": "Maharashtra",
    "manipur": "Manipur",
    "meghalaya": "Meghalaya",
    "mizoram": "Mizoram",
    "nagaland": "Nagaland",
    "odisha": "Odisha",
    "orissa": "Odisha",
    "punjab": "Punjab",
    "rajasthan": "Rajasthan",
    "sikkim": "Sikkim",
    "tamil nadu": "Tamil Nadu",
    "telangana": "Telangana",
    "tripura": "Tripura",
    "uttar pradesh": "Uttar Pradesh",
    "uttarakhand": "Uttarakhand",
    "uttrakhand": "Uttarakhand",
    "uttaranchal": "Uttarakhand",
    "west bengal": "West Bengal",
    "andaman and nicobar islands": "Andaman and Nicobar Islands",
    "andaman & nicobar islands": "Andaman and Nicobar Islands",
    "dadra and nagar haveli": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra and nagar haveli and daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
    "daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
    "delhi": "Delhi",
    "jammu and kashmir": "Jammu and Kashmir",
    "jammu & kashmir": "Jammu and Kashmir",
    "ladakh": "Ladakh",
    "lakshadweep": "Lakshadweep",
    "puducherry": "Puducherry",
    "pondicherry": "Puducherry",
    "chandigarh": "Chandigarh",
}

# States and UTs with no Scheduled Tribes at all. Recorded so that "the Order
# schedules nobody here" can be told apart from "this parse missed them",
# which is the only thing that makes the gap report worth reading.
NO_SCHEDULED_TRIBES = {"Punjab", "Haryana", "Delhi", "Chandigarh"}

# A line ending in a colon, or opening with a roman numeral, introduces a
# section rather than a tribe. Assam's list is split into "I. In the autonomous
# Districts of..." and "II. In the State of Assam including...", and Arunachal
# opens "All tribes in the State including:". Read as entries these become
# phantom tribes; read as context they are the state-level area restriction.
SECTION = re.compile(r"(:\s*$)|(^(?:[IVX]+|[A-H])\s*[.)]\s)")

# Trailing editorial matter that is not part of any entry.
NOTE = re.compile(r"\s*Note\s*:.*$", re.I | re.S)


def is_state(line: str) -> bool:
    """Return whether a line is a State or Union Territory heading.

    Args:
        line: One line of the English column.

    Returns:
        True when the line names a State or UT.
    """
    return re.sub(r"[^a-z& ]", "", line.lower()).strip() in CANONICAL


ENTRY = re.compile(r"^(\d{1,3})\s*[.)]\s*(.*)$")

# Not every entry is numbered. Puducherry's sole tribe is printed as bare text
# ("Irular (including Villi and Vettaikaran)") and Lakshadweep's is a
# descriptive paragraph. A number-anchored reader drops both silently, so a
# state heading immediately followed by unnumbered text opens entry 0.

# Area restrictions ride inside the entry text: an entry can be scheduled only
# in named districts, taluks or tahsils. That is the lower-geography problem,
# and gluing it into the tribe name would both corrupt the name and lose the
# restriction, so it is split off into its own column.
AREA = re.compile(
    r"\(([^()]*\b(?:district|districts|taluk|taluka|tahsil|tehsil|sub-division|"
    r"division|block|region|area|areas|excluding|including the)\b[^()]*)\)",
    re.I,
)

# Lines that are page furniture rather than content.
NOISE = re.compile(
    r"^(the constitution|scheduled tribes order|the schedule|part |page |\d+$)", re.I
)


def latin_column(page) -> list[str]:
    """Return the page's left-hand English column as lines.

    Args:
        page: A `pdfplumber` page of the Order.

    Returns:
        The English lines, in reading order.
    """
    words = page.extract_words()
    if not words:
        return []
    # The gutter is the widest gap between word starts in the middle of the
    # page. Finding it per page beats a constant: the columns shift.
    middle = sorted(w["x0"] for w in words if 0.35 * page.width < w["x0"] < 0.75 * page.width)
    split = 0.55 * page.width
    if len(middle) > 1:
        gaps = [(b - a, (a + b) / 2) for a, b in zip(middle, middle[1:])]
        widest, centre = max(gaps)
        if widest > 20:
            split = centre

    lines: dict[int, list[dict]] = {}
    for word in words:
        if word["x0"] >= split:
            continue
        lines.setdefault(round(word["top"] / 3), []).append(word)
    out = []
    for key in sorted(lines):
        text = " ".join(w["text"] for w in sorted(lines[key], key=lambda w: w["x0"]))
        text = " ".join(text.split())
        if text:
            out.append(text)
    return out


def parse(path: Path, source_id: str) -> tuple[list[dict], list[str]]:
    """Read every entry out of the Order.

    Args:
        path: The stored PDF.
        source_id: The manifest id to stamp on each row.

    Returns:
        The entry rows, and a list of pages that yielded no entries.
    """
    rows: list[dict] = []
    barren: list[str] = []
    state = ""
    printed_state = ""
    section = ""
    opened = False
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            before = len(rows)
            pending: dict | None = None
            lines = latin_column(page)
            # A heading can wrap: "Dadra and Nagar Haveli and Daman" / "and Diu"
            # is one UT split by the column width. Joining a line with its
            # successor before testing recovers it; the join is only kept when
            # the pair names a State, so it cannot swallow an entry.
            joined = set()
            for index in range(len(lines) - 1):
                pair = f"{lines[index]} {lines[index + 1]}".strip()
                if is_state(pair) and not is_state(lines[index]):
                    lines[index] = pair
                    joined.add(index + 1)
            lines = [line for index, line in enumerate(lines) if index not in joined]
            for line in lines:
                if NOISE.match(line):
                    continue
                match = ENTRY.match(line)
                if match:
                    opened = True
                    if pending:
                        rows.append(pending)
                    pending = {
                        "state": state,
                        "state_as_printed": printed_state,
                        "section": section,
                        "entry_no": int(match.group(1)),
                        "name_as_printed": match.group(2).strip(),
                        "source_id": source_id,
                        "page": number,
                    }
                elif is_state(line):
                    if pending:
                        rows.append(pending)
                        pending = None
                    printed_state = line.strip()
                    state = CANONICAL[re.sub(r"[^a-z& ]", "", line.lower()).strip()]
                    section = ""
                    opened = False
                elif SECTION.search(line) and not opened:
                    # Section heading, not a tribe. Kept as context for the
                    # entries that follow rather than emitted as one.
                    section = f"{section} {line}".strip()
                elif pending is None and state and not opened and not SECTION.search(line):
                    # An unnumbered entry directly under a state heading.
                    opened = True
                    pending = {
                        "state": state,
                        "state_as_printed": printed_state,
                        "section": section,
                        "entry_no": 0,
                        "name_as_printed": line.strip(),
                        "source_id": source_id,
                        "page": number,
                    }
                elif pending is not None:
                    # A continuation of the entry above; entries wrap freely.
                    pending["name_as_printed"] = f"{pending['name_as_printed']} {line}".strip()
            if pending:
                rows.append(pending)
            if len(rows) == before:
                barren.append(str(number))
    for row in rows:
        printed = NOTE.sub("", row["name_as_printed"]).rstrip(" .,;")
        restrictions = [m.group(1).strip() for m in AREA.finditer(printed)]
        row["area_restriction"] = " | ".join(restrictions)
        without = AREA.sub(" ", printed)
        # "X (including Y and Z)" names aliases the same way a comma does.
        without = re.sub(r"\(\s*including ([^()]*)\)", r", \1", without, flags=re.I)
        without = " ".join(without.replace(" and ", ", ").split()).rstrip(" .,;")
        row["name_as_printed"] = printed
        # The Order's own comma list is the synonym set. The first is the head
        # name only by printing order, not by any legal precedence.
        row["synonyms"] = "|".join(p.strip(" .,;") for p in without.split(",") if p.strip(" .,;"))
    return rows, barren


def main() -> None:
    """Parse the ST Order named on the command line into `lists/`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", default="st_list_current-072")
    arguments = parser.parse_args()

    with MANIFEST.open(encoding="utf8") as handle:
        manifest = {r["source_id"]: r for r in csv.DictReader(handle, delimiter="\t")}
    if arguments.source_id not in manifest:
        raise SystemExit(f"{arguments.source_id} is not in the manifest; run step 10 first")
    record = manifest[arguments.source_id]
    if not record.get("stored_as"):
        raise SystemExit(f"{arguments.source_id} has no bytes; step 10 could not fetch it")

    rows, barren = parse(RAW / record["stored_as"], arguments.source_id)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "state",
                "state_as_printed",
                "section",
                "entry_no",
                "name_as_printed",
                "synonyms",
                "area_restriction",
                "source_id",
                "page",
            ],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(rows)

    states = sorted({r["state"] for r in rows if r["state"]})
    restricted = sum(1 for r in rows if r["area_restriction"])
    print(f"{len(rows):,} entries across {len(states)} states -> {OUT}")
    print(f"{restricted:,} entries carry an area restriction")
    if barren:
        print(f"pages yielding no entry: {', '.join(barren)}")

    # States that have Scheduled Tribes but produced nothing are a gap in this
    # read, not a fact about the country. Naming them is the point.
    counts = Counter(r["state"] for r in rows)
    report = HERE / "lists/st_parse_report.tsv"
    with report.open("w", encoding="utf8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["state", "n_entries"])
        for name in sorted(counts):
            writer.writerow([name, counts[name]])
    seen = set(states)
    missing = sorted(set(CANONICAL.values()) - seen - NO_SCHEDULED_TRIBES)
    print(f"per-state counts -> {report}")
    if missing:
        print(f"States/UTs with STs but no entry read: {', '.join(missing)}")
    else:
        print("every State/UT with Scheduled Tribes yielded at least one entry")


if __name__ == "__main__":
    main()
