# anusuchi

**Statutory caste lists for India, stored as published and parsed into rows.**

*Anusuchi* (अनुसूची) is the Schedule of the Constitution — the one that gives
Anusuchit Jati and Anusuchit Janjati their names.

A land record, an electoral roll or a survey records a *jati*: `ପାଣ`, `कुर्मी`,
`Bagata`. Almost every question worth asking needs a *category* — Scheduled
Caste, Scheduled Tribe, Other Backward Class, or none of them. The mapping
between the two is law, published in gazetted Orders, and it is not in any of
those datasets. This repo holds the law and the mapping, so that analysis does
not have to invent either.

## Three layers, kept apart

| layer | what it is | changes when | who judges |
|---|---|---|---|
| `sources/` | gazette PDFs and pages exactly as fetched; `st_errata.tsv`, the misprints corrected, each with its evidence | the government republishes | nobody for the bytes; a person, citing a stored Act, for an erratum |
| `lists/` | one row per gazetted entry | `sources/` changes | nobody — mechanical parse |
| `crosswalks/` | one row per *dataset label* → entry | a dataset is added, or a call is revised | a person, on the record |

`lists/` is shared by every state and every downstream repo. `crosswalks/` is
per dataset and is the only place judgment lives. Mixing them is how a legal
list quietly acquires someone's opinion.

## What this does and does not license

The chain has two links, and they do not have the same standing.

**jati → category is official.** The gazette settles it. That is what this repo
holds.

**surname → jati is irreducibly statistical.** No Order names a surname, and no
amount of gazette work changes that. In Odisha's land records, of 2,052
surnames carried by 100 or more people, **67 (3.3%) belong to a single jati**,
covering 0.3% of tenants; the median surname spans **12** jatis and the widest
spans **421**. `Behera` has 153,016 bearers across 421 jatis, its commonest at
14%.

**Nothing here may be described as an official mapping from a name to a caste.**

## Two legal facts that change the arithmetic

**Scheduled Caste status is conditioned on religion.** Paragraph 3 of the
Constitution (Scheduled Castes) Order, 1950:

> no person who professes a religion different from the Hindu, the Sikh or the
> Buddhist religion shall be deemed to be a member of a Scheduled Caste

**Scheduled Tribe status is not.** The ST Order carries no equivalent clause.

So in Odisha's own labels, `ପାଣ ଖ୍ରୀଷ୍ଟିୟାନ` — Pana Christian, 40,729 tenants —
is legally **not** SC, while `କନ୍ଧ ଖ୍ରୀଷ୍ଟିୟାନ` — Kandha Christian, 30,121 — **is**
still ST. A crosswalk that reads only the caste half of the label gets one of
those wrong.

**Many entries are scheduled only in named places.** 40 of 751 ST entries carry
an area restriction: Gujarat's *Kunbi* only in the Dangs district, Andhra's
*Dhulia, Paiko, Putiya* only in Vishakhapatnam and Vijayanagaram. Category is
therefore a function of *(label, district)*, not of label alone, which is why
`area_restriction` is its own column.

## Pipeline

Numbered, re-runnable, each step writing only its own layer.

| step | writes |
|---|---|
| `scripts/01_fetch_sources.py` | `sources/raw/<sha256>.<ext>`, `sources/manifest.tsv` |
| `scripts/02_crawl_archive_history.py` | `sources/discovered.tsv`; with `--promote`, new rows in `sources/registry.tsv` |
| `scripts/03_parse_st_list.py` | `lists/st_entries.tsv`, `lists/st_parse_report.tsv` |
| `scripts/04_over_time.py` | `lists/presence_matrix.tsv`, `lists/n_communities.tsv`, `out/fig/*.png` |
| `scripts/05_parse_wb_obc.py` | `lists/wb_obc_entries.tsv`, `lists/wb_obc_reconcile.tsv`, `lists/wb_obc_parse_report.tsv` |

**Step 01** fetches every URL in `sources/registry.tsv`, records the newest
Wayback capture and submits one where none exists, stores bytes under their own
SHA-256, and writes a manifest row per artefact. Bytes recovered from the archive
are the raw capture, not the archive's viewer, which wraps HTML in its own
player; and a pinned capture is recorded as the one the archive actually served,
which can be months from the one requested. A source that fails is a row
with a status and no checksum, not a silence. Nothing is ever overwritten: a
republished document is a new file and a new row beside the old one.

This is not ceremony. `socialjustice.gov.in` was refusing connections while this
was written, and **every Scheduled Castes document here — the consolidated Order
and the amendment trail back to a 1936 Order predating the Constitution — was
recovered from the Wayback Machine rather than the live site.**

**Step 02** uses the archive as a record rather than a fallback. Ministries mint
a new URL for each edition instead of replacing bytes, so change lives in the
index pages that link to documents, not in the documents. It walks every capture
of each page in `sources/index_pages.tsv` and writes the union of what they ever
linked to `sources/discovered.tsv`. The 2022 capture of the SC page alone links
29 PDFs the live page no longer mentions. Promoting a discovered URL into the
registry is a separate `--promote` decision.

**Step 03** reads the ST Order's two-column layout by word position, splitting at
the widest vertical band on each page that almost no line touches. **751 entries
across 32 States and UTs in the 2025 edition — every State and UT that has
Scheduled Tribes yields at least one.** It recovers the Order's own synonym lists
(`Bhottada, Dhotada, Bhotra, Bhatra, Bhattara, Bhotora, Bhatara` is one tribe,
Odisha entry 5) and the enumerated sub-tribes of the Kuki entries in Assam,
Meghalaya, Mizoram and Tripura; carries an entry across a page break; splits the
40 area restrictions, bracketed or parenthesised, into their own column; keeps
section headings as context, so Assam's two sections each numbered from 1 stay
apart; records the 16 entries printed `Omitted` as numbering gaps rather than as
tribes; and picks up the entries the Order prints without a number.

Files of the same Order are typeset differently, so a tribe present in every
edition can read as dropped in one and back in the next. Three repairs give
each name one spelling across editions, and `name_as_printed` keeps what each
file says:

- Typesetting faults are undone by rule: words run together (`SonjhariJhareka`,
  `NookaDhora`), stray marks (`Langoli ;Pardhi`, ``Koli ` ``) and an accented
  `Bada María`.
- Misprints that need a reading of the law are corrected from
  `sources/st_errata.tsv`, which gives the evidence for each. The `corrected`
  column records the change on every row it touched, and the step fails if an
  erratum stops matching. There are four errata: Chhattisgarh's `Abhuj Maria`
  and `Sonjhari Jhareka`, which Act 13 of 2023 prints as `Abujh Maria` and
  `Sonjhari, Jhareka`; Karnataka's `Bhil Garasia Dholi Bhil`, which loses its
  comma in the 2024 files; and Madhya Pradesh's `Sonjhari Jhareka`, which only
  the 2025 file splits.
- Spacing and capitals that differ between files (`Borokachari`, `Boro
  kachari`) take the form most editions print, the latest breaking a tie.

Four editions are read: 4 August 2023, an undated 2024 file, 25 November 2024,
and 26 September 2025. The 2017 list is stored, from two URLs that hold the same
bytes, but set in three columns, which this reader does not split.

**Step 04** compares ST editions. It builds a presence matrix of synonyms by
edition, per state, and counts entries and distinct synonyms per edition. The
two counts are kept separate because they move for different reasons: entries
change when a community is scheduled or de-scheduled, synonyms when the same
community is written more ways.

After step 03's repairs, 58 names are not in all four editions, and every one is
a change in the text, not a reading error. 57 are the names the February 2024
Acts added: 50 for Odisha (No. 6 of 2024), 4 for Jammu and Kashmir (No. 3) and 3
for Andhra Pradesh (No. 7). Each appears in the stored text of its Act. The
58th is Telangana's `Malis`, below.

## West Bengal's State List of OBCs

The Central List of OBCs and a State's own list are different instruments: the
first governs central posts, the second state posts and state education. West
Bengal's is the first State List here, and it has just been through a reversal.

| date | instrument | classes |
|---|---|---|
| 1994–2009 | notifications from 346-TW/EC onward | 66 |
| 2010–2022 | additions, split into Category A and B | 66 + post-2010 classes |
| 22 May 2024 | Calcutta High Court, WPO 60 of 2011: post-2010 additions struck down | 66 |
| May–June 2025 | 1056 re-sub-categorises 64; 1057 and 1107 add 51 and 25 | 140 |
| 18 May 2026 | 944 withdraws the 2025 package; **945 notifies the list in force** | 66 |

**Sources.** 42 documents are registered: the 945 list as gazetted and as the
department's own copy, the typed 2025 list, the 1993–2010 compilation, 27
inclusion, amendment, categorisation and withdrawal notifications, certificate
and roster circulars, the two Acts and the Commission Rules, and the 2024
judgment with the July 2026 order on 944–946. Two are fetched from the
department's own site (`anagrasarkalyan.gov.in`). That site serves everything
else through encrypted per-session links, so the rest come from
[civicresearch/wb-obc-document-bundle](https://github.com/civicresearch/wb-obc-document-bundle)
(the source behind [obcwb.civicresearch.in](https://obcwb.civicresearch.in/)),
pinned to one commit and marked `authority=mirror`. For the two documents both
places hold, the mirror's bytes are identical to the department's.

**`scripts/05_parse_wb_obc.py`** reads two editions. The typed 2025 list comes
out of its ruled cells directly: 140 classes, each with the notification chain
that put it there. The 2026 gazette is a scan whose OCR reads `Baishya Kapali`
as `Baisirya Kapali` and `14` as `t4`, so the code trusts it for which classes
appear and in what order, not for spelling. Each gazette entry is matched to the
typed text, and three checks keep the match honest:

- Every legible OCR number must equal the entry's position. The one exception,
  `41` printed where `47` belongs, is a misread; the department's copy reads it
  as `47`.
- The department's copy, a separate scan with its own OCR errors, must match
  the same typed class at every position. It does, at all 66.
- Every score is in `lists/wb_obc_reconcile.tsv`. True matches score 0.889 or
  higher. The two entries with no typed counterpart score 0.667 or lower and
  keep their OCR spelling: **`Bharbhuja` and `Devanga` are in the 66 but missing
  from the 2025 list**, which re-categorised only 64.

Parentheses go verbatim into a `qualifier` column instead of being split. The
list uses them both for aliases (`Rayeen (Kunjra)`) and for conditions
(`Hajjam (Muslim)`, `Dhobi (other than those included in the list of
Scheduled Castes)`), and deciding which is which is a crosswalk's call.

## What the source gets wrong, and how that is handled

The Order is a scanned-and-retyped legal document and it has typos. Each is
recorded rather than corrected in place: `state` carries the canonical name and
`state_as_printed` carries what the page actually says.

- **The Order misspells Uttarakhand as `Uttrakhand`**, and spells Jaunsari as
  `Jannsari` under that heading while spelling it correctly under Uttar Pradesh.
  Matching only the correct spelling lost the whole State — its five tribes were
  in the document the entire time.
- **A heading can wrap.** `Dadra and Nagar Haveli and Daman` / `and Diu` is one
  UT split by the column width.
- **Not every entry is numbered.** Puducherry's sole tribe and Lakshadweep's
  descriptive entry are bare text.
- **Some lines are sections, not tribes.** Assam's list splits into `I. In the
  autonomous Districts of...` and `II. In the State of Assam...`; Arunachal opens
  `All tribes in the State including:`. These are kept in a `section` column as
  context for the entries beneath them.
- Puducherry's entry trails into editorial boilerplate (`Note: In case of any
  discrepancies...`), which closes the page; the 2023 edition prints it at the
  foot of every page, under a running title on every page.
- **Some numbers have no dot.** Chhattisgarh's `36 Pardhi` is read as entry 36
  only because it follows 35; a bare number out of sequence stays text.
- **Spacing varies between files.** The 2024 files print `NookaDhora` and
  `PattidiKoya` where 2023 and 2025 print `Nooka Dhora`. Step 03 splits the
  joined words, as above.
- **Later files can lag the law.** Act 13 of 2023 restated Chhattisgarh's entry
  16 with `Abujh Maria`; the 2023 file follows it, and the three later files
  print `Abhuj Maria` instead. Each erratum cites the Act it rests on.

## Known gaps

- The SC list, the Central OBC list and the PVTG list are fetched but not yet
  parsed. Only the ST Order and West Bengal's State List of OBCs have readers.
- The 2017 ST list is set in three columns and is not read, so the over-time
  exhibits start in 2023.
- The undated 2024 ST file lists Telangana's `Malis` (entry 20); the 2023,
  November 2024 and 2025 editions do not. Its date comes from its file name
  alone, so where it falls in that sequence is unconfirmed. None of the 2024
  amendment Acts adds or removes it.
- Madhya Pradesh's `Sonjhari Jhareka` is corrected to one name, the form three
  of four files print, but no Act for Madhya Pradesh is stored to settle it.
- West Bengal's notifications before 2025 are scans with no text layer and are
  stored but not read; the 2010 Category A/B split is therefore not in `lists/`.
  Corrigendum 1172-BCW/MR-38/2025, which the 2025 list cites for four classes,
  is not among the sources.
- 7 of 127 registered sources resolved neither live nor in the archive. They are
  manifest rows with a status and no checksum: two amendment Acts, two
  administrative circulars, the Sikkim SC Order of 1978, a Meghalaya page, and a
  2019 PVTG list whose pinned capture the archive no longer serves.
- `tribal.nic.in` and `egazette.gov.in` do not present a complete certificate chain; verification is
  disabled for those hosts alone and the manifest records `tls_verified=false` on
  the affected rows.

## Not yet built

`crosswalks/` is empty. The first will map Odisha's Record-of-Rights jati labels
onto these entries, using the `status` / `method` / `evidence` vocabulary proven
in `land/crosswalk/caste_crosswalk_additions.tsv`: every row carries how it was
decided and a sentence saying why, and nothing is silently dropped.
