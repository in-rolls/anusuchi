"""Checks on the committed tables, runnable without the raw sources.

Each count is checked against a second route to the same number: a total the
source prints, or the parse report recounted from the rows it summarises.
"""

import csv
import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LISTS = ROOT / "lists"
SOURCES = ROOT / "sources"


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


@pytest.fixture(scope="module")
def manifest():
    return {r["source_id"]: r for r in read(SOURCES / "manifest.tsv")}


@pytest.fixture(scope="module")
def registry():
    return {r["source_id"]: r for r in read(SOURCES / "registry.tsv")}


def test_every_fetched_source_is_registered(manifest, registry):
    assert set(manifest) <= set(registry)


def test_stored_bytes_are_named_by_their_checksum(manifest):
    for r in manifest.values():
        if r["stored_as"]:
            assert r["stored_as"].split(".")[0] == r["sha256"], r["source_id"]


@pytest.mark.parametrize(
    "table",
    ["st_entries.tsv", "wb_obc_entries.tsv", "poi_national_list.tsv"],
)
def test_every_row_cites_a_stored_source(table, manifest):
    for r in read(LISTS / table):
        assert manifest[r["source_id"]]["stored_as"], r["source_id"]


def test_files_end_lines_with_lf_only():
    for path in LISTS.glob("*.tsv"):
        assert b"\r" not in path.read_bytes(), path.name


# Scheduled Tribes


@pytest.fixture(scope="module")
def st():
    return read(LISTS / "st_entries.tsv")


def test_st_report_recounts_from_the_rows(st):
    for line in read(LISTS / "st_parse_report.tsv"):
        rows = [r for r in st if r["edition_id"] == line["edition_id"]]
        live = [r for r in rows if r["synonym"]]
        entries = {(r["state"], r["section"], r["entry_no"]) for r in live}
        assert len(entries) == int(line["n_entries"])
        assert len(live) == int(line["n_synonyms"])
        assert len(rows) - len(live) == int(line["n_omitted"])
        assert len({r["state"] for r in rows if r["state"]}) == int(line["n_states"])


def test_st_2025_edition(st):
    """756 entries in 32 States and UTs, the figures the README states."""
    line = {r["edition_id"]: r for r in read(LISTS / "st_parse_report.tsv")}
    assert line["st_list_current-072"]["n_entries"] == "756"
    assert line["st_list_current-072"]["n_states"] == "32"


def test_st_synonym_ranks_start_at_one_and_run_on(st):
    groups: dict[tuple, list[int]] = {}
    for r in st:
        if r["synonym"]:
            key = (r["edition_id"], r["state"], r["section"], r["entry_no"])
            groups.setdefault(key, []).append(int(r["synonym_rank"]))
    for key, ranks in groups.items():
        assert sorted(ranks) == list(range(1, len(ranks) + 1)), key


# West Bengal OBCs


def test_wb_obc_editions_hold_the_classes_the_notifications_count():
    """140 classes in the 2025 list; 66 in the list notified in 2026 (945)."""
    rows = read(LISTS / "wb_obc_entries.tsv")
    entries = Counter()
    for edition, entry in {(r["notified_date"], r["entry_no"]) for r in rows}:
        entries[edition] += 1
    assert entries == {"2025-06-03": 140, "2026-05-18": 66}


def test_wb_obc_gazette_and_department_copy_agree_everywhere():
    reconcile = read(LISTS / "wb_obc_reconcile.tsv")
    assert len(reconcile) == 66
    assert {r["copies_agree"] for r in reconcile} == {"true"}


# People of India, National List of Communities


@pytest.fixture(scope="module")
def poi():
    return read(LISTS / "poi_national_list.tsv")


def test_poi_reproduces_the_appendix_totals(poi):
    """The appendix prints 2,209 main communities and 586 segments."""
    mains = {r["serial"] for r in poi if r["level"] == "main"}
    segments = {(r["serial"], r["segment_no"]) for r in poi if r["level"] == "segment"}
    assert len(mains) == 2209
    assert len(segments) == 586


def test_poi_serials_run_one_to_2209_without_gaps(poi):
    assert sorted({int(r["serial"]) for r in poi}) == list(range(1, 2210))


def test_poi_segments_are_numbered_from_one_within_each_community(poi):
    numbers: dict[str, set[int]] = {}
    for r in poi:
        if r["level"] == "segment":
            numbers.setdefault(r["serial"], set()).add(int(r["segment_no"]))
    for serial, seen in numbers.items():
        assert seen == set(range(1, len(seen) + 1)), serial


def test_poi_fields_use_the_legend(poi):
    assert {r["level"] for r in poi} <= {"main", "variant", "segment", "segment_variant"}
    assert {r["category"] for r in poi} <= {"", "SC", "ST", "OBC", "NON SC", "NON ST", "NT", "UNC"}
    for r in poi:
        assert set(r["religion"]) <= set("HMCSBJTZ"), r["religion"]


def test_poi_states_are_the_32_of_the_period(poi):
    states = {r["state"] for r in poi} - {""}
    assert len(states) == 32


def test_poi_pages_match_the_printed_folio(poi):
    """The Introduction's printed folio runs 12 behind the PDF page."""
    for r in poi:
        assert int(r["page"]) - int(r["page_printed"]) == 12


def test_readme_source_counts_match_the_registry(manifest, registry):
    """The README's count of registered and unresolved sources is not stale."""
    text = (ROOT / "README.md").read_text(encoding="utf8")
    unresolved, total = map(int, re.search(r"(\d+) of (\d+) registered sources", text).groups())
    assert total == len(registry)
    assert unresolved == len([s for s in registry if not manifest.get(s, {}).get("stored_as")])
    wb = [s for s, r in registry.items() if r["kind"].startswith("wb_obc")]
    assert f"{len(wb)} documents are registered" in text
