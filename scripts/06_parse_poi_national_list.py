"""Read People of India Vol I, Appendix G, the National List of Communities.

The Anthropological Survey of India's list of the 4,635 communities its 1985-92
survey studied: 2,209 main communities, 586 segments and 1,840 territorial
units, by the appendix's own consolidated statement. Each line gives a name,
its category where one applied (SC, ST, NON SC, NON ST), a religion code, and
the states it was found in; a state can carry its own category, chiefly OBC.

The scan is Google's, with no text layer, so step one is tesseract with word
boxes, cached under `sources/ocr/<source_id>/`. Everything after that reads
positions, not text:

- Odd and even pages sit at different horizontal offsets, so the serial column
  is located afresh on every page, as the commonest x of serial-shaped first
  words.
- A word in the serial column opens a main community, however it was read.
  `41.` comes out as `al.` and `11.` as `Me`; the position does not.
- A line starting at the name column is a variant of the open main community:
  the same name with another category or state (`AGARIA /AGARIYA (SC)`).
- A numbered line indented past the name column is a segment. Segments carry a
  running counter across the whole list (`TANGAM (ST) (T) 15.`).
- An indented line without a number is the open segment's name wrapping onto a
  second line, unless the segment is complete and the line repeats its name,
  in which case it is a variant of that segment. A trailing or leading `/`
  always means a wrap.
- Words right of the name column are states. Each attaches to the entry open
  at its line.

Two checks make a dropped or doubled line fatal rather than silent. The count
of main communities must be 2,209 and of segments 586, the totals the appendix
prints. And within those counts every serial and segment counter the OCR read
as a clean number must equal its position, up to the digit confusions tesseract
makes on this typeface (3/8, 1/7 and the like); a lost line shifts every
number after it, which no digit confusion explains.

Names are kept as read. Tesseract reads this typeface's H as `II` or `IT` often
enough (`AITLUWALIA`, `BIIIAR`) that names need a correction pass before being
joined to anything, and `name_suspect` marks the ones that visibly need it. A
dictionary repair (swap `II` for `H` where the result is a word seen elsewhere)
was tried and rejected: it fixes `BRALIMAN` but also "fixes" real names such as
`BONDILI` and `KALLAR`. States are matched to the 32 states and UTs of the
period, and religion codes to the appendix's legend. `religion_as_read` and
`state_as_read` keep what the page said, and `religion_certain` marks the dozen
code groups the legend cannot resolve.

The OCR cache is versioned, so the list reproduces without tesseract and a
different tesseract version cannot silently change it.

The date that matters is when a community was observed: fieldwork ran from 2
October 1985 to 31 March 1992. Categories are as the survey recorded them then,
not as the Orders stand now.

Run:

    python scripts/06_parse_poi_national_list.py

Needs `pdftoppm` (poppler) and `tesseract` on PATH for the first run only.
Writes `lists/poi_national_list.tsv` and `lists/poi_national_list_report.tsv`.
"""

from __future__ import annotations

import csv
import difflib
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
MANIFEST = HERE / "sources/manifest.tsv"
RAW = HERE / "sources/raw"
OCR = HERE / "sources/ocr"
ENTRIES = HERE / "lists/poi_national_list.tsv"
REPORT = HERE / "lists/poi_national_list_report.tsv"

SOURCE = "poi_volume-121"
# Scan pages of Appendix G. The consolidated statement at the foot of the last
# page ends the list; pages 221-222 are blank.
PAGES = range(144, 221)
# Printed page = scan page - 12, read off the running page numbers.
PAGE_OFFSET = 12
DPI = 300
MAIN_TOTAL = 2209
SEGMENT_TOTAL = 586
# Lines are about 35 pixels apart at 300 dpi; a larger jump at the foot of a
# page is the bottom margin, and anything under it is scan-edge noise.
FOOT_GAP = 120

STATES = [
    "ANDHRA PRADESH", "ARUNACHAL PRADESH", "ASSAM", "BIHAR", "GOA", "GUJARAT",
    "HARYANA", "HIMACHAL PRADESH", "JAMMU & KASHMIR", "KARNATAKA", "KERALA",
    "MADHYA PRADESH", "MAHARASHTRA", "MANIPUR", "MEGHALAYA", "MIZORAM",
    "NAGALAND", "ORISSA", "PUNJAB", "RAJASTHAN", "SIKKIM", "TAMIL NADU",
    "TRIPURA", "UTTAR PRADESH", "WEST BENGAL", "ANDAMAN & NICOBAR ISLANDS",
    "CHANDIGARH", "DADRA & NAGAR HAVELI", "DAMAN & DIU", "DELHI",
    "LAKSHADWEEP", "PONDICHERRY",
]  # fmt: skip
# Below this a state string is OCR debris, not a state. The weakest true match
# in the current OCR is `COA` for Goa, at 0.67.
STATE_FLOOR = 0.65
CATEGORIES = {"SC", "ST", "OBC", "NON SC", "NON ST", "NT", "UNC"}
RELIGIONS = "HMCSBJTZ"
# How tesseract reads this typeface's H inside a code group.
H_LIKE = re.compile(r"^(?:11|II|I1|1I|HH|HI|IH|1|I|#1|1H|H1|EI|EH|HD|1D|ID|É)$")
CODE_GROUP = re.compile(r"[HMCSBJTZ1IE#D&É,.*8 ]+|ZA")
# Digit pairs tesseract confuses on this typeface; a serial that differs from
# its position only by these is a misreading, anything else a lost line.
CONFUSABLE = {
    frozenset(p)
    for p in ("38", "17", "56", "08", "58", "39", "14", "27", "68", "09", "12", "35", "48", "28")
}

SERIAL = re.compile(r"^[\dSs$]{1,4}[.,]$")
SEGMENT_NO = re.compile(r"^[\dSs$Il|]{1,2}(?:[.,]|$)")
SEGMENT_GLUED = re.compile(r"^[\dIl|]{1,2}[.,][A-Z]")
PAREN = re.compile(r"\(([^()]*)\)")
COUNTER = re.compile(
    r"(?:^|[\s)])((?=[\d$S\]lI]*\d)[\d$S\]lI]{1,3})\s*(?:[.,]+(?=\s|$|\()|$|(?=\())"
)
DIGITS = str.maketrans("$S]lI", "35111")
# The two marks of a misread name: a doubled I, which is how this typeface's H
# comes out and almost never a real spelling, and characters no name carries.
SUSPECT = re.compile(r"II|[^A-Z /,.\-'&]")
TITLE_DATES = re.compile(r"published (\d{4}); fieldwork (\S+) to (\S+)\)")

FIELDS = [
    "source_id",
    "published",
    "observed_from",
    "observed_to",
    "serial",
    "serial_as_read",
    "level",
    "segment_no",
    "segment_no_as_read",
    "segment_counter",
    "name",
    "name_suspect",
    "name_qualifier",
    "category",
    "religion",
    "religion_as_read",
    "religion_certain",
    "state_category",
    "state",
    "state_area",
    "state_as_read",
    "page",
    "page_printed",
]


def manifest() -> dict[str, dict]:
    """Return the newest fetched manifest row for each source.

    Returns:
        Manifest rows keyed by source_id, only those that have bytes.
    """
    with MANIFEST.open(encoding="utf8") as handle:
        rows = [r for r in csv.DictReader(handle, delimiter="\t") if r.get("sha256")]
    return {r["source_id"]: r for r in rows}


def ocr(pdf: Path, out: Path) -> None:
    """Render each page and run tesseract with word boxes, skipping cached pages.

    Args:
        pdf: The scanned volume.
        out: Directory for one `p<page>.tsv` per page.
    """
    out.mkdir(parents=True, exist_ok=True)
    for page in PAGES:
        tsv = out / f"p{page}.tsv"
        if tsv.exists():
            continue
        png = out / f"p{page}.png"
        subprocess.run(
            ["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(DPI), "-gray", "-png",
             "-singlefile", str(pdf), str(png.with_suffix(""))],
            check=True,
        )  # fmt: skip
        subprocess.run(
            ["tesseract", str(png), str(tsv.with_suffix("")), "--psm", "6", "tsv"],
            check=True,
            capture_output=True,
        )
        png.unlink()


def page_lines(path: Path) -> list[tuple[int, list[tuple[float, str]]]]:
    """Return a page's OCR lines, each as (top, [(x as page fraction, word)]).

    Args:
        path: A tesseract TSV.

    Returns:
        Lines sorted top to bottom, words left to right.
    """
    with path.open(encoding="utf8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE))
    width = max(int(r["left"]) + int(r["width"]) for r in rows)
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        if r["level"] == "5" and r["text"].strip():
            groups.setdefault((r["block_num"], r["par_num"], r["line_num"]), []).append(r)
    lines = []
    for words in groups.values():
        words.sort(key=lambda w: int(w["left"]))
        # Median, not min: one tall stray mark otherwise lifts a line above its neighbor.
        top = sorted(int(w["top"]) for w in words)[len(words) // 2]
        lines.append((top, [(int(w["left"]) / width, w["text"]) for w in words]))
    return sorted(lines, key=lambda line: line[0])


def serial_column(lines: list) -> float | None:
    """Return the page's serial-column x: the commonest x of serial-shaped first words."""
    xs = [
        round(words[0][0], 2)
        for _, words in lines
        if len(words) > 1 and SERIAL.match(words[0][1]) and words[0][0] < 0.25
    ]
    return Counter(xs).most_common(1)[0][0] if xs else None


def page_text(lines: list, folio: int) -> list:
    """Return the lines between the running header and the foot of the page.

    The scan's edges carry dust and gutter shadow that tesseract reads as words
    (`EEPTCCEE?`, `a ae`). Above the header line, which holds the printed page
    number, nothing is printed; below the last entry a gap of several blank
    lines separates the text from the edge.

    Args:
        lines: A page's OCR lines.
        folio: The printed page number.

    Returns:
        The lines from just under the header to the last line of text.
    """
    for i, (_, words) in enumerate(lines[:4]):
        if any(t.strip(".,'") == str(folio) for _, t in words) and len(words) <= 3:
            lines = lines[i + 1 :]
            break
    end = len(lines)
    while end > 1 and lines[end - 1][0] - lines[end - 2][0] > FOOT_GAP:
        end -= 1
    return lines[:end]


def classify(lines: list, nx: float):
    """Yield (kind, left text, right text) per line; kind is main, variant, segment or cont.

    Args:
        lines: A page's OCR lines.
        nx: The page's serial-column x.

    Yields:
        One tuple per line that carries text.
    """
    for _, words in lines:
        if len(words) == 1 and re.fullmatch(r"[\d\s.,]+", words[0][1]):
            continue  # running page number
        left = [(x, t) for x, t in words if x < nx + 0.47]
        left = left[:1] + [(x, t) for x, t in left[1:] if re.search(r"[A-Za-z0-9(]", t)]
        rest = [(x, t) for x, t in words if x >= nx + 0.47]
        # A long segment line pushes its counter (`361.`) past the state column's edge.
        if rest and left and re.fullmatch(r"[\d$S\]lI]{1,3}[.,]", rest[0][1]):
            left, rest = left + rest[:1], rest[1:]
        right = " ".join(t for _, t in rest)
        while left and not re.search(r"[A-Za-z0-9$]", left[0][1]):
            left = left[1:]  # stray mark before the text
        if not left:
            if right:
                yield "state", "", right
            continue
        x0, first = left[0]
        text = " ".join(t for _, t in left)
        if x0 < nx + 0.04:
            if len(left) > 1 and left[1][0] >= nx + 0.05:
                yield "main", text, right
            elif text.strip(" .,;'|"):
                yield "variant", text, right
            elif right:
                yield "state", "", right
        elif x0 >= nx + 0.11:
            if (SEGMENT_NO.match(first) and len(left) > 1) or SEGMENT_GLUED.match(first):
                yield "segment", text, right
            else:
                yield "cont", text, right
        else:
            yield "variant", text, right


def split_codes(text: str) -> tuple[str, str, str, str, str]:
    """Split an entry into name, category, religion codes, segment counter and qualifier.

    Args:
        text: The entry's left-column text, wraps joined.

    Returns:
        (name, category, religion as read, counter, qualifier). Parentheses that
        are neither a category nor a code group, such as `(MUSLIM)`, are the
        qualifier.
    """
    counter = ""
    found = list(COUNTER.finditer(text))
    if found:
        m = found[-1]
        counter = m.group(1).translate(DIGITS)
        text = text[: m.start(1)] + " " + text[m.end() :]
    cat, rel, qual = [], [], []
    for group in PAREN.findall(text):
        g = re.sub(r"\s+", " ", group.strip().upper())
        g = g.replace("QBC", "OBC").replace("NONSC", "NON SC")
        if g in CATEGORIES:
            cat.append(g)
        elif CODE_GROUP.fullmatch(g):
            rel.append(g)
        else:
            qual.append(g)
    name = re.sub(r"\s+", " ", PAREN.sub(" ", text)).strip(" .,;'|")
    return name, "/".join(cat), "/".join(rel), counter, "/".join(qual)


def religion_codes(raw: str) -> tuple[str, bool]:
    """Return legend letters for an OCR'd code group, and whether every token resolved.

    Args:
        raw: Code groups as read, e.g. `11&S` or `H, C&T`.

    Returns:
        Letters in legend order (`HS`, `HCT`) and a certainty flag. An `8`
        standing for `&` makes the group uncertain, since it can also be a B.
    """
    out, sure = [], "8" not in raw
    for tok in re.split(r"[&,. 8/]+", raw.upper().replace("É", "&")):
        if not tok:
            continue
        if tok == "ZA":
            out.append("Z")
        elif tok in set(RELIGIONS):
            out.append(tok)
        elif re.fullmatch(f"[{RELIGIONS}]{{2,}}", tok):
            out += list(tok)
        elif H_LIKE.match(tok):
            out.append("H")
        elif re.fullmatch(r"(?:11|I1|II|1)[MCSBJT]", tok):
            out += ["H", tok[-1]]
        else:
            sure = False
    return "".join(sorted(set(out), key=RELIGIONS.index)), sure


def match_state(text: str) -> tuple[str, float]:
    """Return the closest state of the period and its similarity."""
    t = text.upper()
    for misread in ("II", "LI", "IT", "TI"):
        t = t.replace(misread, "H")
    t = re.sub(r"\s+", " ", re.sub(r"[^A-Z& ]", "", t)).strip()
    t = {"DIU & DAMAN": "DAMAN & DIU"}.get(t, t)
    if not t:
        return "", 1.0
    best = difflib.get_close_matches(t, STATES, n=1, cutoff=0.0)[0]
    return best, difflib.SequenceMatcher(None, t, best).ratio()


def first_word(text: str) -> str:
    """Return the first word of an entry's name, before any slash."""
    return split_codes(text)[0].split(" ")[0].split("/")[0]


def read(pages: dict[int, list]) -> list[dict]:
    """Assemble entries from classified lines across all pages.

    Args:
        pages: OCR lines keyed by scan page.

    Returns:
        Entries in page order, each with its left text, states and page.
    """
    found = {p: serial_column(lines) for p, lines in pages.items()}
    xs: dict[int, float] = {}
    for p, x in found.items():
        if x is None:  # a page of segments only: use its side's usual offset
            same = [v for q, v in found.items() if v is not None and q % 2 == p % 2]
            x = Counter(same).most_common(1)[0][0]
        xs[p] = x
    entries: list[dict] = []
    cur: dict | None = None
    main: dict | None = None
    for p, lines in pages.items():
        for kind, text, right in classify(page_text(lines, p - PAGE_OFFSET), xs[p]):
            if p == PAGES[0] and re.search(r"Appendix|National|COMMUNITY", text):
                continue
            if "Consolidated" in text:
                break
            if kind == "main":
                serial, body = text.split(" ", 1)
                main = {"serial_as_read": serial.strip(".,")}
                cur = {"level": "main", "main": main, "raw": body, "states": [], "page": p}
                main["entry"] = cur
                entries.append(cur)
            elif kind == "segment":
                m = re.match(r"^([\dSs$Il|]{1,2})[.,]?\s*(.*)", text)
                number, body = (m.group(1), m.group(2)) if m else ("", text)
                cur = {"level": "segment", "main": main, "segment_no_as_read": number,
                       "raw": body, "states": [], "page": p}  # fmt: skip
                entries.append(cur)
            elif kind == "cont" and cur is not None:
                complete = cur["level"] == "segment_variant" or (
                    cur["level"] == "segment" and split_codes(cur["raw"])[3]
                )
                repeats = (
                    difflib.SequenceMatcher(None, first_word(cur["raw"]), first_word(text)).ratio()
                    > 0.7
                )
                wraps = text.startswith("/") or cur["raw"].rstrip().endswith("/")
                if complete and repeats and not wraps:
                    cur = {"level": "segment_variant", "main": main, "raw": text, "states": [],
                           "page": p, "segment_no_as_read": cur["segment_no_as_read"],
                           "parent": cur.get("parent", cur)}  # fmt: skip
                    entries.append(cur)
                else:
                    cur["raw"] += " " + text
            elif (
                kind == "variant"
                and cur is not None
                and cur["level"] in ("main", "variant")
                and (cur["raw"].rstrip().endswith("/") or text.startswith("/"))
            ):
                cur["raw"] += " " + text
            elif kind == "variant":
                cur = {"level": "variant", "main": main, "raw": text, "states": [], "page": p}
                entries.append(cur)
            if right and cur is not None:
                cur["states"].append(right)
    serial = position = 0
    for e in entries:
        if e["level"] == "main":
            serial += 1
            e["main"]["serial"] = serial
            position = 0
        elif e["level"] == "segment":
            position += 1
            e["segment_no"] = position
        elif e["level"] == "segment_variant":
            e["segment_no"] = e["parent"]["segment_no"]
    return entries


def misread(read_as: str, position: int) -> bool:
    """Whether a number read off the page differs from its position only by digit confusions."""
    a, b = str(position), read_as
    short, long_ = sorted((a, b), key=len)
    if len(long_) == len(short) + 1 and any(
        long_[:i] + long_[i + 1 :] == short for i in range(len(long_))
    ):
        return True  # one digit dropped or added
    return len(a) == len(b) and all(x == y or frozenset(x + y) in CONFUSABLE for x, y in zip(a, b))


def check(entries: list[dict]) -> list[dict]:
    """Run the count and sequence checks; exit if a line was lost or doubled.

    Args:
        entries: Assembled entries.

    Returns:
        Report rows, one per check.
    """
    mains = [e for e in entries if e["level"] == "main"]
    segments = [e for e in entries if e["level"] == "segment"]
    serials = [(e["main"]["serial_as_read"], e["main"]["serial"]) for e in mains]
    counters = [(split_codes(e["raw"])[3], i) for i, e in enumerate(segments, 1)]
    report = []
    for name, pairs, total in (
        ("main communities", serials, MAIN_TOTAL),
        ("segments", counters, SEGMENT_TOTAL),
    ):
        clean = [(r, p) for r, p in pairs if r.isdigit()]
        exact = sum(int(r) == p for r, p in clean)
        confused = sum(int(r) != p and misread(r, p) for r, p in clean)
        off = [(r, p) for r, p in clean if int(r) != p and not misread(r, p)]
        report.append({
            "check": name,
            "found": len(pairs),
            "expected": total,
            "numbers_read": len(clean),
            "equal_position": exact,
            "digit_confusion": confused,
            "off_position": len(off),
            "examples": "; ".join(f"read {r} at {p}" for r, p in off[:5]),
        })  # fmt: skip
        if len(pairs) != total:
            sys.exit(f"{name}: read {len(pairs)}, the appendix prints {total}")
        if off:
            sys.exit(f"{name}: numbers off position, a line was lost or doubled: {off[:5]}")
    return report


def rows_of(entries: list[dict], dates: tuple[str, str, str]) -> list[dict]:
    """Expand entries to one row per state.

    Args:
        entries: Assembled entries.
        dates: (published, observed_from, observed_to) from the registry title.

    Returns:
        Table rows in FIELDS order.
    """
    rows = []
    for e in entries:
        name, cat, rel, counter, qual = split_codes(e["raw"])
        if not name and e["level"] == "variant":
            # A variant printed as codes alone, `(NON ST) (H)` under MINA /MEENA,
            # is the main community under another category.
            name = split_codes(e["main"]["entry"]["raw"])[0]
        if e["level"] != "segment":
            counter = ""  # only segments are counted; DHARUA's stray printed 7 is not a count
        religion, sure = religion_codes(rel)
        states = [s for s in e["states"] if not re.fullmatch(r"[\d\s.,]+", s.strip())]
        for s in states or [""]:
            s = s.strip(" .,;'|").replace("QBC", "OBC")
            state_cat, area = "", ""
            m = re.match(r"^\(\s*([A-Z ]+?)\s*\)\s*", s)
            if m:
                inner, s = m.group(1), s[m.end() :]
                if inner in CATEGORIES:
                    state_cat = inner
                elif CODE_GROUP.fullmatch(inner):  # a religion code set into the state column
                    rel = "/".join(x for x in (rel, inner) if x)
                    religion, sure = religion_codes(rel)
                else:
                    area = inner
            a = re.search(r"\(([^()]*)\)\s*$", s)
            if a:
                area, s = (area + " " + a.group(1)).strip(), s[: a.start()].strip()
            state, score = match_state(s)
            rows.append({
                "source_id": SOURCE,
                "published": dates[0],
                "observed_from": dates[1],
                "observed_to": dates[2],
                "serial": e["main"]["serial"],
                "serial_as_read": e["main"]["serial_as_read"],
                "level": e["level"],
                "segment_no": e.get("segment_no", ""),
                "segment_no_as_read": e.get("segment_no_as_read", ""),
                "segment_counter": counter,
                "name": name,
                "name_suspect": bool(SUSPECT.search(name)),
                "name_qualifier": qual,
                "category": cat,
                "religion": religion,
                "religion_as_read": rel,
                "religion_certain": sure,
                "state_category": state_cat,
                "state": state.title().replace("&", "and") if score >= STATE_FLOOR else "",
                "state_area": area.title(),
                "state_as_read": s,
                "page": e["page"],
                "page_printed": e["page"] - PAGE_OFFSET,
            })  # fmt: skip
    return rows


def main() -> None:
    """OCR if needed, parse, check, and write the list and its report."""
    sources = manifest()
    if SOURCE not in sources:
        sys.exit(f"not fetched: {SOURCE}; run scripts/01_fetch_sources.py first")
    record = sources[SOURCE]
    dates = TITLE_DATES.search(record["title"])
    if not dates:
        sys.exit(f"{SOURCE}: no publication and fieldwork dates in its registry title")
    cache = OCR / SOURCE
    ocr(RAW / record["stored_as"], cache)
    pages = {p: page_lines(cache / f"p{p}.tsv") for p in PAGES}
    entries = read(pages)
    report = check(entries)
    published, observed_from, observed_to = dates.groups()
    rows = rows_of(entries, (published, observed_from, observed_to))

    unmatched = [r for r in rows if r["state_as_read"] and not r["state"]]
    levels = Counter(e["level"] for e in entries)
    report.append({
        "check": "states outside the 32 of the period",
        "found": len(unmatched),
        "expected": 0,
        "examples": "; ".join(sorted({r["state_as_read"] for r in unmatched})[:8]),
    })  # fmt: skip
    report.append({
        "check": "names with a misread mark",
        "found": sum(1 for r in rows if r["name_suspect"]),
        "expected": 0,
        "examples": "; ".join(sorted({r["name"] for r in rows if r["name_suspect"]})[:8]),
    })  # fmt: skip
    report.append({
        "check": "religion codes the legend cannot resolve",
        "found": sum(1 for r in rows if not r["religion_certain"]),
        "expected": 0,
    })  # fmt: skip

    ENTRIES.parent.mkdir(exist_ok=True)
    with ENTRIES.open("w", encoding="utf8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    keys = ["check", "found", "expected", "numbers_read", "equal_position", "digit_confusion",
            "off_position", "examples"]  # fmt: skip
    with REPORT.open("w", encoding="utf8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(report)
    print(
        f"{levels['main']} main, {levels['segment']} segments, {levels['variant']} variants, "
        f"{levels['segment_variant']} segment variants; {len(rows)} rows -> {ENTRIES.name}",
        file=sys.stderr,
    )
    for r in report:
        print(f"  {r['check']}: {r['found']} (expected {r['expected']}) {r.get('examples', '')}",
              file=sys.stderr)  # fmt: skip


if __name__ == "__main__":
    main()
