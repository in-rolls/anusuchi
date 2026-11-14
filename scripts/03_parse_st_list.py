"""Read the Constitution (Scheduled Tribes) Order into one row per entry.

Mechanical, and deliberately so. This step decides nothing: it turns a PDF the
government published into the same content as rows, so that the crosswalk in
crosswalk can cite a numbered entry rather than an opinion. Anything requiring
judgment belongs downstream, and anything this step cannot read is reported
rather than guessed at.

The Order is printed in two columns, English on the left and Hindi on the
right, with the entry number repeated in each. `extract_text` interleaves them,
which is why this reads word positions and splits on the column gap instead.
The split is found per page as the widest vertical band no word touches in the
middle of the page, rather than hardcoded, because the gutter moves between
pages. Measuring between where words *start* is not the same thing: on the page
listing Meghalaya's Kuki sub-tribes in four columns (numeral, English, numeral,
Hindi), the widest start-to-start gap is between the Hindi numerals and the
Hindi, which put both on the English side.

Entries wrap over several lines and carry their synonyms inline:

    5. Bhottada, Dhotada, Bhotra, Bhatra, Bhattara, Bhotora, Bhatara

All seven of those are one gazetted tribe, entry 5 for Odisha. That comma list
is the Order supplying its own alias table, and it is what makes matching a
recorded jati label tractable later without inventing synonyms of our own.

**One row per synonym, not per entry, and every edition in one table.** The
grain matters and the reason is measurable. Between the 2023 and 2025 editions,
12 of Odisha's 62 shared entry numbers changed their printed name, and nearly
every change is a synonym being *added* to a community that did not otherwise
move:

    6  Bhuiya, Bhuyan   ->  Bhuiya, Bhuyan, Pauri Bhuyan, Paudi Bhuyan
    9  Bhunjia          ->  Bhunjia, Chuktia Bhunjia
   28  Kawar, Kanwar    ->  Kawar, Kanwar, Kaur, Kunwar, Kaonr, Kuanr, ...

Compared as whole strings that reads as twelve communities disappearing and
fourteen appearing. Compared at synonym grain it reads as `Pauri Bhuyan` joining
an existing entry, which is what happened. `name_as_printed` is carried on every
row so the exploded form can always be collapsed back to what the gazette says.

`notified_date` is what makes the table answer a question about time at all. It
is parsed from the source title, where the ministry states it, and without it
there is no axis to put the editions on.

Run:

    python scripts/03_parse_st_list.py

Writes `lists/st_entries.tsv`: edition_id, notified_date, category, state,
state_as_printed, section, entry_no, synonym, synonym_rank, name_as_printed,
area_restriction, source_id, page.
"""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from pathlib import Path

import pdfplumber

HERE = Path(__file__).resolve().parent.parent
MANIFEST = HERE / "sources/manifest.tsv"
RAW = HERE / "sources/raw"
OUT = HERE / "lists/st_entries.tsv"

# Editions whose layout this reader does not handle, by checksum. Parsing them
# anyway yields plausible rows that are wrong: the 2017 list read as 240 entries
# against a true ~750, with Telangana absent.
UNREAD = {
    "2524086b8fcc2535e2c28a8f12eb91e6c2ee3a553d7a2f83761b7bfc597e35c9": (
        "the 2017 list is set in three columns; this reader splits two"
    ),
}

# The ministry states the notified date in the document title and nowhere
# machine-readable, so it is read from there: "(26-09-2025)", "(as on
# 04-08-2023)", or a bare year.
DATED = re.compile(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})")
YEARED = re.compile(r"\b(19|20)(\d{2})\b")


def notified_date(title: str) -> str:
    """Return the edition date stated in a source title.

    Args:
        title: The registry title of the document.

    Returns:
        An ISO date, a bare year, or an empty string when neither is stated.
    """
    match = DATED.search(title)
    if match:
        day, month, year = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    match = YEARED.search(title)
    return f"{match.group(0)}" if match else ""


# A state heading is matched against the fixed set of States and Union
# Territories, not against a shape. An earlier version accepted any capitalised
# line without a number, which read the wrapped continuation "Bhuyan" -- the
# tail of Odisha's entry 6 -- as the start of a new state, and produced 53
# states and 6 Odisha entries against a true 62. The set is public and
# closed, so there is no reason to guess.
# Headings are matched against the fixed set of States and Union Territories,
# canonicalised, because neither the printed spelling nor the shape can be
# trusted. Two failures drove this. Accepting any capitalised unnumbered line
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

# A capital roman numeral opens a new section wherever it falls. Assam's "II. In
# the State of Assam ..." follows entry 15 of section I, and testing only before
# the first entry glued it onto that entry and filed all of section II under I.
NEW_SECTION = re.compile(r"^[IVX]+\s*[.)]\s+\S")

# Editorial matter: "Note: In case of any discrepancies in the spelling ...". It
# always closes a page, every page in the 2023 edition and the last page in the
# others, so it ends the page rather than being cut out of an entry afterwards.
# Cutting it out afterwards deleted whatever followed it, which once entries are
# carried across pages was the rest of the entry.
NOTE = re.compile(r"^note\s*:", re.I)


def is_state(line: str) -> bool:
    """Return whether a line is a State or Union Territory heading.

    Args:
        line: One line of the English column.

    Returns:
        True when the line names a State or UT.
    """
    # No State or UT name contains a digit. Without this test the normaliser,
    # which strips punctuation, read the joined pair "43. Goa" as "goa": the
    # wrapped-heading join then fired, the entry regex claimed it as entry 43
    # named "Goa" under the previous state, and Goa and Telangana vanished from
    # the 2023 edition entirely -- 40 entries lost to a stray line number.
    if any(character.isdigit() for character in line):
        return False
    return re.sub(r"[^a-z& ]", "", line.lower()).strip() in CANONICAL


ENTRY = re.compile(r"^(\d{1,3})\s*[.)]\s*(.*)$")

# Some numbers are printed without their dot: Chhattisgarh's "36 Pardhi". A bare
# number opens an entry only when it is the next in sequence, so that a number
# inside a name or a restriction cannot.
BARE = re.compile(r"^(\d{1,3})\s+([A-Z].*)$")

# Sub-tribe and area lists are enumerated: "i. Biate", "(iii) Chhalya",
# "(iiia) Darlong". The enumerator separates names the way a comma does.
ENUMERATOR = re.compile(r"(?:(?<=\s)|^)(?:\([ivxl]+a?\)|[ivxl]+a?\.(?=\s|$))")

# A deleted entry keeps its number and says "Omitted". It is a gap in the
# numbering, not a tribe called Omitted.
OMITTED = re.compile(r"^omitted\.?$", re.I)
INCLUDING = re.compile(r"\bincluding(?: the following sub-\s*tribes)?\s*:\s*-?", re.I)

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
    r"division|block|region|area|areas|excluding|including the|forests|nesses)\b[^()]*)\)",
    re.I,
)

# Long restrictions are set in square brackets and enumerate places inside them:
# Pardhi "[In (i) Bastar, ... and (viii) Dhamtari ... district]". Every square
# bracket in these Orders is a restriction.
BRACKETED = re.compile(r"\[([^\[\]]*)\]?")

# The English column never holds Devanagari, so a Devanagari word on the English
# side is the Hindi column leaking across a misplaced split, never content.
DEVANAGARI = re.compile(r"[\u0900-\u097F]")

# Lines that are page furniture rather than content. The 2023 edition repeats a
# running title on every page; now that an entry is carried over a page break,
# it would otherwise be read into it.
NOISE = re.compile(
    r"^(the constitution|scheduled tribes order|the schedule|part |page |\d+$"
    r"|state\s*/\s*union territory wise)",
    re.I,
)
# A merged UT prints one list per former UT, each numbered from 1: "PART I -
# Dadra and Nagar Haveli", "PART II - Daman and Diu". NOISE drops lines opening
# "part ", so these are caught first, or the two lists collide.
PART = re.compile(r"^part\s+[IVX]+\s*[\u2013\u2014-]\s*\S", re.I)
# The same title can share a line with the last entry above it: Uttar Pradesh's
# "Bhuinya (in the district of Sonbhadra) State / Union Territory".
TRAILER = re.compile(r"\s*\bstate\s*/\s*union territory\b.*$", re.I)

# Typesetting faults that differ between files of the same text, so that an
# unchanged tribe reads as dropped in one edition and added in the next: words
# run together ("SonjhariJhareka", "NookaDhora"), stray marks ("Langoli ;Pardhi",
# "Koli `"), and an accented "María". No name in these Orders has a capital
# inside a word or a Latin diacritic, so undoing all three is safe.
GLUED = re.compile(r"(?<=[a-z])(?=[A-Z])")
STRAY = re.compile(r"\s*[`;]\s*(?=\S)|\s*`$")

# Faults that need a reading of the law rather than a rule, kept by hand with
# the evidence for each. `name_as_printed` always keeps what the file says.
ERRATA = HERE / "sources/st_errata.tsv"


def clean(text: str) -> str:
    """Undo the typesetting faults that vary between files of the same text.

    Args:
        text: An entry as printed.

    Returns:
        The entry with glued words split, stray marks removed and Latin
        diacritics dropped.
    """
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = STRAY.sub(" ", GLUED.sub(" ", text))
    return " ".join(text.split())


def read_errata() -> list[dict]:
    """Return the hand-kept corrections, one per state, entry and phrase."""
    with ERRATA.open(encoding="utf8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def correct(rows: list[dict], errata: list[dict]) -> None:
    """Apply each erratum to the entries it names, recording it on the row.

    Args:
        rows: Entry rows with `text` set to the cleaned entry.
        errata: Rows of `sources/st_errata.tsv`.
    """
    for erratum in errata:
        for row in rows:
            if (
                row["state"] == erratum["state"]
                and str(row["entry_no"]) == erratum["entry_no"]
                and re.search(rf"\b{re.escape(erratum['printed'])}\b", row["text"])
            ):
                row["text"] = re.sub(
                    rf"\b{re.escape(erratum['printed'])}\b", erratum["corrected"], row["text"]
                )
                row["corrected"] = "; ".join(
                    filter(
                        None, [row["corrected"], f"{erratum['printed']} -> {erratum['corrected']}"]
                    )
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
    # A point is in the gutter when fewer than a tenth of the page's lines
    # touch it. Requiring that no line touches it fails on every page whose
    # title runs across both columns.
    low, high = int(0.35 * page.width), int(0.75 * page.width)
    touching: dict[int, set[int]] = {}
    for word in words:
        for x in range(max(low, int(word["x0"])), min(high, int(word["x1"]) + 1)):
            touching.setdefault(x, set()).add(round(word["top"] / 3))
    limit = 0.1 * len({round(w["top"] / 3) for w in words})
    split = 0.55 * page.width
    widest, start = 0, low
    for x in range(low, high + 1):
        if x < high and len(touching.get(x, ())) < limit:
            continue
        if x - start > widest:
            widest, split = x - start, (x + start) / 2
        start = x + 1
    if widest <= 8:
        split = 0.55 * page.width

    lines: dict[int, list[dict]] = {}
    for word in words:
        if word["x0"] >= split or DEVANAGARI.search(word["text"]):
            continue
        lines.setdefault(round(word["top"] / 3), []).append(word)
    out = []
    for key in sorted(lines):
        tokens = [w["text"] for w in sorted(lines[key], key=lambda w: w["x0"])]
        # The Hindi column repeats the line's entry number or enumerator, and
        # where the gutter is narrow it lands on this side: "38. Sor 38".
        if tokens and re.fullmatch(r"\(?(\d{1,3}|[ivxl]+a?)[.)]?", tokens[0]):
            bare = tokens[0].strip("().")
            tokens = tokens[:1] + [t for t in tokens[1:] if t.strip("().") != bare]
        text = " ".join(" ".join(tokens).split())
        if text:
            out.append(text)
    return out


def parse(path: Path, source_id: str, errata: list[dict]) -> tuple[list[dict], list[str]]:
    """Read every entry out of the Order.

    Args:
        path: The stored PDF.
        source_id: The manifest id to stamp on each row.
        errata: Hand-kept corrections to apply after cleaning.

    Returns:
        The entry rows, and a list of pages that yielded no entries.
    """
    rows: list[dict] = []
    barren: list[str] = []
    state = ""
    printed_state = ""
    section = ""
    opened = False
    # Set while a section heading may still be wrapping onto further lines:
    # Assam's "I. In the autonomous Districts of" / "Karbi Anglong and North
    # Cachar Hills" otherwise made the second line a tribe.
    heading = False
    # An entry can run over a page break: Tripura's Kuki sub-tribes continue
    # from "(ii) Belalhut" to "(iii) Chhalya" overleaf. So the open entry is
    # carried across pages, not closed at the foot of each.
    pending: dict | None = None
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            started = 0
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
                if NOTE.match(line):
                    break
                line = TRAILER.sub("", line)
                if PART.match(line):
                    if pending:
                        rows.append(pending)
                        pending = None
                    section = line.strip()
                    opened = False
                    heading = False
                    continue
                if not line or NOISE.match(line):
                    continue
                match = ENTRY.match(line)
                bare = BARE.match(line)
                if not match and bare and pending and int(bare.group(1)) == pending["entry_no"] + 1:
                    match = bare
                if (
                    match
                    and not match.group(2).strip()
                    and pending
                    and int(match.group(1)) == pending["entry_no"]
                ):
                    continue  # the open entry's number printed again on its own (2023, "43.")
                if match:
                    opened = True
                    heading = False
                    started += 1
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
                    heading = False
                elif NEW_SECTION.match(line):
                    if pending:
                        rows.append(pending)
                        pending = None
                    section = line.strip()
                    opened = False
                    heading = True
                elif heading or (SECTION.search(line) and not opened):
                    # Section heading, not a tribe. Kept as context for the
                    # entries that follow rather than emitted as one.
                    section = f"{section} {line}".strip()
                    heading = True
                elif pending is None and state and not opened and not SECTION.search(line):
                    # An unnumbered entry directly under a state heading.
                    opened = True
                    started += 1
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
            if not started:
                barren.append(str(number))
    if pending:
        rows.append(pending)
    for row in rows:
        row["name_as_printed"] = row["name_as_printed"].rstrip(" .,;")
        row["text"] = clean(row["name_as_printed"]).rstrip(" .,;")
        row["corrected"] = ""
    correct(rows, errata)
    exploded = []
    for row in rows:
        printed = row.pop("text")
        restrictions = [m.group(1).strip() for m in BRACKETED.finditer(printed)]
        without = BRACKETED.sub(" ", printed)
        restrictions += [m.group(1).strip() for m in AREA.finditer(without)]
        row["area_restriction"] = " | ".join(restrictions)
        without = AREA.sub(" ", without)
        # "X (including Y and Z)" names aliases the same way a comma does.
        without = re.sub(r"\(\s*including ([^()]*)\)", r", \1", without, flags=re.I)
        without = ENUMERATOR.sub(",", INCLUDING.sub(",", without))
        # Mizoram writes alternatives with "or": "Biate or Biete", "Synteng or
        # Pnar". Every " or " in these Orders joins two names for one tribe.
        without = without.replace(" and ", ", ").replace(" or ", ", ")
        without = " ".join(without.split()).rstrip(" .,;")
        if OMITTED.match(printed):
            exploded.append({**row, "synonym": "", "synonym_rank": 0})
            continue
        # Lakshadweep's entry defines its tribe by birthplace in full sentences.
        # Split on commas it becomes fragments such as "1994", so it stays whole.
        if row["entry_no"] == 0 and re.search(r"[a-z]\. [A-Z]", printed):
            exploded.append({**row, "synonym": printed, "synonym_rank": 1})
            continue
        # The Order's own comma list is the synonym set. The first is the head
        # name only by printing order, not by any legal precedence.
        names = [p.strip(" .,;") for p in without.split(",") if p.strip(" .,;")]
        for rank, synonym in enumerate(names or [printed], 1):
            exploded.append({**row, "synonym": synonym, "synonym_rank": rank})
    return exploded, barren


def main() -> None:
    """Parse ST Orders into one table of synonym-grain rows."""
    argparse.ArgumentParser(description=__doc__).parse_args()

    with MANIFEST.open(encoding="utf8") as handle:
        manifest = list(csv.DictReader(handle, delimiter="\t"))

    # Every edition is parsed together because spelling is settled across them:
    # parsing one alone gives that edition different rows.
    # One document published at two URLs is one edition: the 2017 list moved
    # paths unchanged and is held twice, from 2017 and from 2021.
    first: dict[str, dict] = {}
    for r in sorted(manifest, key=lambda r: r["source_id"]):
        if r["kind"].startswith("st_list") and r["stored_as"]:
            first.setdefault(r["sha256"], r)
    wanted = list(first.values())
    for record in [r for r in wanted if r["sha256"] in UNREAD]:
        print(f"skipping {record['source_id']}: {UNREAD[record['sha256']]}")
    wanted = [r for r in wanted if r["sha256"] not in UNREAD]
    if not wanted:
        raise SystemExit("no ST list editions with bytes; run step 01 first")

    errata = read_errata()
    rows: list[dict] = []
    summary = []
    for record in sorted(wanted, key=lambda r: r["source_id"]):
        parsed, barren = parse(RAW / record["stored_as"], record["source_id"], errata)
        date = notified_date(record["title"])
        for row in parsed:
            row["edition_id"] = record["source_id"]
            row["notified_date"] = date
            row["category"] = "ST"
        rows.extend(parsed)
        # Assam's two sections each number from 1, so the section is part of
        # an entry's identity.
        live = [r for r in parsed if r["synonym"]]
        entries = {(r["state"], r["section"], r["entry_no"]) for r in live}
        states = {r["state"] for r in parsed if r["state"]}
        summary.append(
            {
                "edition_id": record["source_id"],
                "notified_date": date,
                "n_states": len(states),
                "n_entries": len(entries),
                "n_omitted": sum(1 for r in parsed if r["synonym_rank"] == 0),
                "n_synonyms": len(live),
                "n_area_restricted": sum(1 for r in live if r["area_restriction"]),
                "n_corrected": 0,
                "barren_pages": ",".join(barren),
            }
        )

    # The same name is spaced and capitalised differently between files of the
    # same text: "Borokachari" in three editions, "Boro kachari" in the fourth.
    # Each name takes the form most editions print, the latest breaking a tie.
    forms: dict[tuple, dict[str, list]] = {}
    for row in rows:
        if row["synonym"]:
            key = (row["state"], re.sub(r"\W", "", row["synonym"].lower()))
            forms.setdefault(key, {}).setdefault(row["synonym"], []).append(row["notified_date"])
    for row in rows:
        if not row["synonym"]:
            continue
        spellings = forms[(row["state"], re.sub(r"\W", "", row["synonym"].lower()))]
        usual = max(spellings, key=lambda s: (len(set(spellings[s])), max(spellings[s])))
        if usual != row["synonym"]:
            row["corrected"] = "; ".join(
                filter(None, [row["corrected"], f"{row['synonym']} -> {usual}"])
            )
            row["synonym"] = usual
    for line in summary:
        line["n_corrected"] = len(
            {
                (r["state"], r["section"], r["entry_no"])
                for r in rows
                if r["edition_id"] == line["edition_id"] and r["corrected"]
            }
        )

    # An erratum that no longer matches anything has gone stale, either because
    # the parse changed or the text was corrected at source; it must not linger.
    applied = " ; ".join(r["corrected"] for r in rows)
    stale = [e for e in errata if f"{e['printed']} -> {e['corrected']}" not in applied]
    if stale:
        raise SystemExit(f"errata matching no entry: {stale}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "edition_id",
                "notified_date",
                "category",
                "state",
                "state_as_printed",
                "section",
                "entry_no",
                "synonym",
                "synonym_rank",
                "name_as_printed",
                "area_restriction",
                "corrected",
                "source_id",
                "page",
            ],
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)

    report = HERE / "lists/st_parse_report.tsv"
    with report.open("w", encoding="utf8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(summary[0]), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(summary)

    print(f"{len(rows):,} synonym rows across {len(summary)} edition(s) -> {OUT}")
    for line in summary:
        print(
            f"  {line['edition_id']:<22} {line['notified_date']:<11} "
            f"{line['n_states']:>2} states  {line['n_entries']:>4} entries  "
            f"{line['n_synonyms']:>5} synonyms"
        )
    print(f"per-edition summary -> {report}")

    seen = {r["state"] for r in rows if r["state"]}
    missing = sorted(set(CANONICAL.values()) - seen - NO_SCHEDULED_TRIBES)
    if missing:
        print(f"States/UTs with STs but no entry read: {', '.join(missing)}")
    else:
        print("every State/UT with Scheduled Tribes yielded at least one entry")


if __name__ == "__main__":
    main()
