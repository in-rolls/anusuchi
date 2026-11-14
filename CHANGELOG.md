# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.1.0] - 2026-11-14

The first release: India's statutory caste lists stored as published, and the
ones with readers parsed into rows.

### Sources

- **137 documents registered, 130 stored** under their own SHA-256, each with a
  manifest row recording where the bytes came from, when, and the Wayback
  capture behind them. The Scheduled Castes documents, back to a 1936 Order,
  came from the archive because `socialjustice.gov.in` was refusing
  connections. Seven sources resolved neither live nor archived and are kept
  as rows with a status and no checksum.
- **People of India**, the Anthropological Survey's ethnography, stored apart
  from the Orders because it is official but not law: the Introduction (1992),
  Gujarat (2003) and Tamil Nadu (1997). Each title carries its publication
  year and the 1985–92 fieldwork window.
- Maharashtra's consolidated OBC list and West Bengal's memoranda on `Sunri
  (excluding Saha)`, the two documents that name surnames.

### Lists

- **`st_entries.tsv`**: the Scheduled Tribes Order in four editions (August
  2023, 2024, November 2024, September 2025), one row per synonym. 756 entries
  in 32 States and UTs in 2025, with area restrictions in their own column and
  four misprints corrected from `sources/st_errata.tsv`, each citing the Act it
  rests on. `presence_matrix.tsv` and `n_communities.tsv` compare editions.
- **`wb_obc_entries.tsv`**: West Bengal's State List of OBCs, the typed 2025
  list (140 classes) and the 2026 list in force (66), matched entry by entry
  against two independent scans.
- **`poi_national_list.tsv`**: the People of India National List of
  Communities, read from a scan by OCR. 3,205 entries over 4,682 rows; the
  parse reproduces the appendix's printed totals of 2,209 main communities and
  586 segments. 104 names carry a visible OCR error and are flagged
  `name_suspect`.

### Fixed before release

- The merged UT of Dadra and Nagar Haveli and Daman and Diu prints two lists
  each numbered from 1. They had collided into one, losing five entries per
  edition; the 2025 count is 756, not the 751 earlier drafts gave.
- Step 03 could parse a single edition, which gave that edition different
  rows from a full run and skipped the stale-erratum check. It now always
  parses every edition.
- In `poi_national_list.tsv`, `page` is the PDF page, as in every other table,
  and the printed folio is `page_printed`.

### Checks

- `tests/test_lists.py` checks the committed tables against a second route to
  each number, without the raw sources, and CI runs it with the linters.
  Steps 03 to 06 rebuild every table byte-identically from the stored sources.
