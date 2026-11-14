"""Measure how the Scheduled Tribe lists change between editions.

Two questions, and the second is only honest because of how the entries table is
grained.

**Does a community stay on the list?** A presence matrix: rows are synonyms,
columns are editions, a filled cell means the gazette named that community in
that edition. Built per state, because a national matrix of 1,800 rows says less
than one state's seventy.

**Does the list grow?** Two counts per edition, plotted together because they
move for different reasons. Gazetted *entries* change when a community is
scheduled or de-scheduled. Distinct *synonyms* change when the same community is
written more ways -- which the Orders do constantly, and which would look like
communities appearing and disappearing if the table were grained per entry
rather than per synonym.

A worked example of why that matters. Between 2023 and 2025, twelve of Odisha's
sixty-two shared entry numbers changed their printed name, and almost every
change is a synonym added to a community that did not otherwise move: entry 6
went from "Bhuiya, Bhuyan" to "Bhuiya, Bhuyan, Pauri Bhuyan, Paudi Bhuyan".
Compared as printed strings that is twelve communities lost and fourteen gained.
Compared at synonym grain it is two names joining an existing entry.

Churn is reported as first and last appearance rather than as a flag, because a
community that leaves and returns is a different thing from one that was added.

Run:

    python scripts/04_over_time.py [--state Odisha]

Writes `lists/presence_matrix.tsv`, `lists/n_communities.tsv`, and figures under
`out/fig/`.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent.parent
ENTRIES = HERE / "lists/st_entries.tsv"
MATRIX = HERE / "lists/presence_matrix.tsv"
COUNTS = HERE / "lists/n_communities.tsv"
FIG = HERE / "out/fig"


def read_entries() -> list[dict]:
    """Return the parsed entries.

    Raises:
        SystemExit: If the entries table has not been built.

    Returns:
        One dict per synonym-grain row.
    """
    if not ENTRIES.exists():
        raise SystemExit(f"{ENTRIES} not found; run step 03 first")
    with ENTRIES.open(encoding="utf8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def editions(rows: list[dict]) -> list[str]:
    """Return the edition dates present, oldest first.

    Args:
        rows: Entry rows.

    Returns:
        Sorted edition dates.
    """
    return sorted({r["notified_date"] for r in rows if r["notified_date"]})


def counts_table(rows: list[dict], dates: list[str]) -> list[dict]:
    """Count entries and distinct synonyms per state per edition.

    Args:
        rows: Entry rows.
        dates: Edition dates, oldest first.

    Returns:
        One row per state and edition, plus an ALL-INDIA row per edition.
    """
    out = []
    states = sorted({r["state"] for r in rows if r["state"]})
    for state in [*states, "ALL INDIA"]:
        for date in dates:
            sub = [
                r
                for r in rows
                if r["notified_date"] == date
                and r["synonym"]
                and (state == "ALL INDIA" or r["state"] == state)
            ]
            out.append(
                {
                    "state": state,
                    "notified_date": date,
                    "n_entries": len({(r["state"], r["section"], r["entry_no"]) for r in sub}),
                    "n_synonyms": len({(r["state"], r["synonym"]) for r in sub}),
                }
            )
    return out


def presence(rows: list[dict], dates: list[str], state: str) -> list[dict]:
    """Return one row per synonym with its presence in each edition.

    Args:
        rows: Entry rows.
        dates: Edition dates, oldest first.
        state: The state to build the matrix for.

    Returns:
        One dict per synonym, carrying a column per edition.
    """
    # Step 03 gives each name one spelling across editions, so a name missing
    # from an edition is missing from its text, not spelled differently there.
    seen: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        # An omitted entry has no name to be present.
        if row["state"] != state or not row["notified_date"] or not row["synonym"]:
            continue
        seen[row["synonym"]].add(row["notified_date"])

    out = []
    for synonym, where in seen.items():
        record = {"state": state, "synonym": synonym}
        record.update({date: int(date in where) for date in dates})
        record["n_editions"] = len(where)
        record["first_seen"] = min(where)
        record["last_seen"] = max(where)
        record["in_all"] = int(len(where) == len(dates))
        out.append(record)
    # Persistent communities band together at the top, churn falls to the
    # bottom, which is the only ordering that makes the matrix readable.
    return sorted(out, key=lambda r: (-r["n_editions"], r["first_seen"], r["synonym"].lower()))


def draw_matrix(matrix: list[dict], dates: list[str], state: str, path: Path) -> None:
    """Draw the presence matrix: a summary band, then the names that move.

    Drawing all 243 rows at equal height gave a figure 5,370 pixels tall whose
    labels overlapped into a smear, and the rows that carried the finding -- the
    ones that come and go -- were the smallest part of it. The names present in
    every edition are the background: they collapse to one band with a count.
    The rest get a labelled row each.

    Args:
        matrix: Presence rows, persistent first.
        dates: Edition dates, oldest first.
        state: The state named in the title.
        path: Where to write the figure.
    """
    stable = [r for r in matrix if r["in_all"]]
    churn = [r for r in matrix if not r["in_all"]]
    figure = plt.figure(
        figsize=(4.6 + 1.1 * len(dates), max(3.6, 0.22 * len(churn) + 2.2)),
        layout="constrained",
    )
    ratios = [1, max(len(churn), 1)] if stable else [0.001, max(len(churn), 1)]
    top, bottom = figure.subplots(
        2, 1, gridspec_kw={"height_ratios": ratios, "hspace": 0.06}, sharex=True
    )

    def style(axes) -> None:
        for edge in range(1, len(dates)):
            axes.axvline(edge - 0.5, color="white", lw=1.6)
        for spine in axes.spines.values():
            spine.set_visible(False)

    if stable:
        top.imshow(
            [[1] * len(dates)], aspect="auto", cmap="Greys", vmin=0, vmax=1, interpolation="nearest"
        )
        top.set_yticks([0])
        top.set_yticklabels([f"{len(stable)} in every\nedition"], fontsize=8)
        top.tick_params(axis="y", length=0)
        style(top)
    top.set_xticks(range(len(dates)))

    bottom.imshow(
        [[row[date] for date in dates] for row in churn],
        aspect="auto",
        cmap="Greys",
        vmin=0,
        vmax=1,
        interpolation="nearest",
    )
    bottom.set_xticks(range(len(dates)))
    bottom.set_xticklabels(dates, fontsize=9, rotation=30, ha="right")
    bottom.set_yticks(range(len(churn)))
    bottom.set_yticklabels([r["synonym"][:38] for r in churn], fontsize=7)
    bottom.tick_params(axis="y", length=0)
    style(bottom)

    top.set_title(
        f"{state}: {len(matrix)} Scheduled Tribe names, {len(dates)} editions\n"
        f"Filled means the gazette named it. {len(churn)} names do not appear "
        f"in every edition.",
        fontsize=10,
        loc="left",
    )
    figure.savefig(path, dpi=170)
    plt.close(figure)


def draw_counts(counts: list[dict], dates: list[str], path: Path) -> None:
    """Draw national entry and synonym counts against edition date.

    Args:
        counts: The counts table.
        dates: Edition dates, oldest first.
        path: Where to write the figure.
    """
    national = {r["notified_date"]: r for r in counts if r["state"] == "ALL INDIA"}
    figure, axes = plt.subplots(figsize=(7.0, 4.0))
    for field, label, colour in (
        ("n_entries", "gazetted entries", "#1a1a1a"),
        ("n_synonyms", "distinct names", "#b22222"),
    ):
        values = [national[d][field] for d in dates]
        axes.plot(dates, values, "-o", color=colour, lw=2.0, ms=7, label=label)
        for x, y in zip(dates, values):
            axes.annotate(
                f"{y:,}",
                (x, y),
                textcoords="offset points",
                xytext=(0, 9),
                ha="center",
                fontsize=9,
                color=colour,
            )
    axes.set_ylabel("count, all India")
    axes.set_title(
        "Scheduled Tribes: entries and names by edition\n"
        "Entries move when a community is scheduled or de-scheduled.\n"
        "Names move when the same community is written more ways.",
        fontsize=10,
        loc="left",
    )
    axes.margins(x=0.08)
    axes.legend(frameon=False, fontsize=9)
    axes.grid(axis="y", alpha=0.25)
    for spine in ("top", "right"):
        axes.spines[spine].set_visible(False)
    figure.tight_layout()
    figure.savefig(path, dpi=170)
    plt.close(figure)


def main() -> None:
    """Build the over-time tables and figures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", default="Odisha")
    arguments = parser.parse_args()

    rows = read_entries()
    dates = editions(rows)
    if len(dates) < 2:
        raise SystemExit(f"only {len(dates)} edition(s) parsed; run step 03 first")

    counts = counts_table(rows, dates)
    with COUNTS.open("w", encoding="utf8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["state", "notified_date", "n_entries", "n_synonyms"],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(counts)

    matrix = presence(rows, dates, arguments.state)
    with MATRIX.open("w", encoding="utf8", newline="") as handle:
        fields = ["state", "synonym", *dates, "n_editions", "first_seen", "last_seen", "in_all"]
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(matrix)

    FIG.mkdir(parents=True, exist_ok=True)
    draw_matrix(matrix, dates, arguments.state, FIG / "presence_matrix.png")
    draw_counts(counts, dates, FIG / "n_communities.png")

    churn = [r for r in matrix if not r["in_all"]]
    print(f"editions: {', '.join(dates)}")
    print(f"{arguments.state}: {len(matrix)} names, {len(matrix) - len(churn)} in every edition")
    for row in churn[:12]:
        span = f"{row['first_seen']}..{row['last_seen']}"
        print(f"   {row['synonym'][:38]:<40} {span}  {row['n_editions']}/{len(dates)}")
    print(f"\n{MATRIX}\n{COUNTS}\n{FIG}")


if __name__ == "__main__":
    main()
