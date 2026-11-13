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
| `sources/` | gazette PDFs and pages exactly as fetched | the government republishes | nobody — bytes |
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

**Many entries are scheduled only in named places.** 34 of 772 ST entries carry
an area restriction: Gujarat's *Kunbi* only in the Dangs district, Andhra's
*Dhulia, Paiko, Putiya* only in Vishakhapatnam and Vijayanagaram. Category is
therefore a function of *(label, district)*, not of label alone, which is why
`area_restriction` is its own column.

## Pipeline

Numbered, re-runnable, each step writing only its own layer.

| step | writes |
|---|---|
| `scripts/10_fetch_sources.py` | `sources/raw/<sha256>.<ext>`, `sources/manifest.tsv` |
| `scripts/20_parse_st_list.py` | `lists/st_entries.tsv`, `lists/st_parse_report.tsv` |

**Step 10** fetches every URL in `sources/registry.tsv`, records the newest
Wayback capture and submits one where none exists, stores bytes under their own
SHA-256, and writes a manifest row per artifact. A source that fails is a row
with a status and no checksum, not a silence. Nothing is ever overwritten: a
republished document is a new file and a new row beside the old one.

This is not ceremony. `socialjustice.gov.in` was refusing connections while this
was written, and **every Scheduled Castes document here — the consolidated Order
and the amendment trail back to a 1936 Order predating the Constitution — was
recovered from the Wayback Machine rather than the live site.**

**Step 20** reads the ST Order's two-column layout by word position, splitting on
the gutter found per page. **772 entries across 32 States and UTs — every State
and UT that has Scheduled Tribes yields at least one.** It recovers the Order's
own synonym lists (`Bhottada, Dhotada, Bhotra, Bhatra, Bhattara, Bhotora,
Bhatara` is one tribe, Odisha entry 5), splits the 34 area restrictions into
their own column, keeps section headings as context rather than emitting them as
phantom tribes, and picks up the entries the Order prints without a number.

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
  discrepancies...`), which is stripped.

## Known gaps

- SC, OBC and PVTG lists are fetched but not yet parsed. Only the ST Order has a
  reader.
- 6 of 74 registered sources resolved neither live nor in the archive. They are
  manifest rows with a status and no checksum; four are amendment Acts and two
  are administrative circulars.
- `tribal.nic.in` does not present a complete certificate chain; verification is
  disabled for that host alone and the manifest records `tls_verified=false` on
  the affected rows.

## Not yet built

`crosswalks/` is empty. The first will map Odisha's Record-of-Rights jati labels
onto these entries, using the `status` / `method` / `evidence` vocabulary proven
in `land/crosswalk/caste_crosswalk_additions.tsv`: every row carries how it was
decided and a sentence saying why, and nothing is silently dropped.
