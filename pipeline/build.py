"""Turn data/brands.csv into site/data/brands.json, the one file the page reads.

Why this file exists
--------------------
The website is plain HTML, CSS, and JavaScript with no build step and no API
calls. That is a deliberate constraint: it means the page cannot break because
a service went down, and anyone can open it from a link. The cost of that
constraint is that the page needs its data pre-shaped, because a browser
should not be doing joins and group-bys on page load.

This script pays that cost once, on a laptop. It reads the hand-curated CSV,
attaches coordinates, computes every number the page displays, and writes one
JSON file. That JSON is committed, so the site works whether or not anyone
ever runs this script again.

Three top-level keys come out:

``brands``
    One object per CSV row, plus the looked-up coordinates.
``parents``
    One object per ultimate parent, with how many of our brands it owns.
``summary``
    Every number the headline and the summary tiles display, computed here
    rather than in JavaScript, so the page and the README cannot disagree.

Run it like this::

    python -m pipeline.build

A note on the shape of this file
--------------------------------
Everything below the CSV loader works on a plain ``list`` of ``dict``, one
dict per row. That is a deliberate choice for a 50-row dataset. It means the
grouping and counting read like the sentences they implement, it means the
tests need no table library, and it means the script runs on a machine where
nothing has been installed yet. pandas is used for exactly one job, reading
the CSV, where its type handling genuinely helps.
"""

from __future__ import annotations

# --- standard library ------------------------------------------------------
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# --- this project ----------------------------------------------------------
# The required-field checks live in validate.py and are reused here rather
# than rewritten. The reason is a rule about this repository:
# site/data/brands.json is committed, so it is the file a reader actually
# sees. It must never be generated from a CSV that fails its own evidence
# rules, because that would publish an unsourced claim. Importing the check
# means build and validate can never disagree about what "sourced" means.
from pipeline.validate import (
    EXPECTED_COLUMNS,
    ORIGIN_UNCONFIRMED_MARKER,
    UNVERIFIED_MARKER,
    check_required_fields,
)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
BRANDS_CSV = REPO_ROOT / "data" / "brands.csv"
PLACES_CSV = REPO_ROOT / "data" / "places.csv"
OUTPUT_JSON = REPO_ROOT / "site" / "data" / "brands.json"

# Both gap markers come from validate.py, so there is exactly one definition
# of each and the two scripts cannot drift apart. See validate.py for why
# there are two of them rather than one.

# Parent types that mean "this brand is not owned by a large diversified
# company". The summary tile counts these, and DECISIONS.md explains the
# grouping. A cooperative is member-owned, so it is counted here too, but it
# is also reported on its own in ``counts_by_parent_type`` so nobody has to
# take the grouping on trust.
NOT_CONGLOMERATE_TYPES = {
    "independent",
    "family_owned",
    "employee_owned",
    "cooperative",
}

# How many parents the concentration headline talks about.
TOP_N_PARENTS = 3


# ---------------------------------------------------------------------------
# Reading the CSV
# ---------------------------------------------------------------------------

def read_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    """Read a CSV into a list of dictionaries, with every value a string.

    Why it exists: this is the only place in the build that touches a CSV
    file, so it is the only place that has to care about missing values and
    type guessing.

    pandas is used when it is installed, because ``read_csv`` handles quoted
    fields, stray whitespace, and encodings more carefully than hand-rolled
    parsing would. Two arguments matter and both are there to defeat pandas'
    helpfulness:

    * ``dtype=str`` stops it reading a year-like column as a number.
    * ``.fillna("")`` stops an empty cell becoming the float ``NaN``, which
      ``json.dumps`` writes as the bare token ``NaN``. That is not valid JSON
      and it makes ``JSON.parse`` throw in the browser, which would break the
      page on load with no clue as to why.

    When pandas is not installed, the standard library's ``csv.DictReader``
    does the same job for a file this size. The fallback exists so the build
    runs anywhere, including a fresh machine and a CI container with no
    dependencies. Both paths return the same thing, so nothing downstream can
    tell which one ran.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"{csv_path} not found.")

    try:
        import pandas as pd  # the table library named in requirements.txt
    except ImportError:
        with csv_path.open(newline="", encoding="utf-8") as handle:
            return [
                {key: (value or "").strip() for key, value in row.items()}
                for row in csv.DictReader(handle)
            ]

    frame = pd.read_csv(csv_path, dtype=str).fillna("")
    return [
        {key: str(value).strip() for key, value in record.items()}
        for record in frame.to_dict("records")
    ]


def load_brands(csv_path: Path = BRANDS_CSV) -> list[dict[str, str]]:
    """Read brands.csv and check that its header is the expected one.

    Why it exists: a renamed or dropped column would not crash anything. It
    would produce empty strings all the way through to the page, where a
    whole column of the story would just be blank. Checking the header turns
    that into an immediate, readable failure.
    """
    rows = read_csv_rows(csv_path)
    if rows:
        found = set(rows[0])
        missing = [c for c in EXPECTED_COLUMNS if c not in found]
        if missing:
            raise ValueError(
                f"{csv_path.name} is missing column(s): {', '.join(missing)}"
            )
    return rows


# ---------------------------------------------------------------------------
# Places
# ---------------------------------------------------------------------------

def place_key(city: str, state: str) -> str:
    """Build the lookup key for a city and state pair.

    Why it exists: "Battle Creek, MI" and "battle creek , mi" are the same
    place, and a lookup that treated them as different would silently lose a
    map point. Normalising in one function means the table loader and the row
    reader cannot drift apart.
    """
    return f"{(city or '').strip().casefold()}|{(state or '').strip().casefold()}"


def load_places(csv_path: Path = PLACES_CSV) -> dict[str, dict]:
    """Load the hand-written city-to-coordinate lookup table.

    Why it exists: the map needs latitude and longitude for every brand origin
    and every parent headquarters. A geocoding service would be the obvious
    answer, and it is the wrong one here. There are only a few dozen distinct
    places in this dataset, so a hand-written table is faster, needs no API
    key, has no rate limit, cannot fail offline, and cannot silently return a
    different answer next year. It is also reviewable, because a wrong
    coordinate shows up in a diff.

    Returns a dictionary keyed by ``place_key``, so a lookup is one step.
    """
    if not csv_path.exists():
        raise FileNotFoundError(
            f"{csv_path} not found. Every city in brands.csv needs a row here."
        )

    rows = read_csv_rows(csv_path)
    required = {"city", "state", "country", "lat", "lon"}
    if rows:
        missing = required - set(rows[0])
        if missing:
            raise ValueError(
                f"{csv_path.name} is missing column(s): {', '.join(sorted(missing))}"
            )

    table: dict[str, dict] = {}
    for row in rows:
        key = place_key(row["city"], row["state"])
        if key in table:
            raise ValueError(
                f"{csv_path.name} lists {row['city']}, {row['state']} twice"
            )
        try:
            table[key] = {
                "city": row["city"],
                "state": row["state"],
                "country": row["country"],
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
            }
        except ValueError as exc:
            raise ValueError(
                f"{csv_path.name}: {row['city']}, {row['state']} has a "
                f"non-numeric coordinate ({exc})"
            ) from exc

    return table


def find_missing_places(
    brands: list[dict[str, str]], places: dict[str, dict]
) -> list[str]:
    """List every city in brands.csv that has no row in places.csv.

    Why it exists: a missing coordinate would drop a point off the map with no
    visible error, which is the worst kind of bug in a data project. This
    turns it into a loud failure at build time.

    A blank origin city is not a missing place. It is a declared gap on a row
    that could not confirm the brand's self-claimed origin, so it is skipped
    here and flagged on the page instead.
    """
    missing: list[str] = []

    for row in brands:
        pairs = [
            (row["brand_origin_city"], row["brand_origin_state"], "brand origin"),
            (row["parent_hq_city"], row["parent_hq_state"], "parent HQ"),
        ]
        for city, state, label in pairs:
            if not str(city).strip():
                continue  # declared gap, handled elsewhere
            if place_key(city, state) not in places:
                missing.append(f"{row['brand']} ({label}): {city}, {state}")

    return missing


# ---------------------------------------------------------------------------
# Shaping
# ---------------------------------------------------------------------------

def row_is_unverified(notes: str) -> bool:
    """Return True if a row's *ownership* claim lacks two independent sources.

    Why it exists: this is the serious flag. The page promises two sources per
    ownership claim, so a row that falls short has to say so on its face. It
    is kept separate from ``row_origin_unconfirmed`` because a reader who sees
    one badge on most rows stops reading badges.
    """
    return UNVERIFIED_MARKER in (notes or "").casefold()


def row_origin_unconfirmed(notes: str) -> bool:
    """Return True if the brand's self-claimed home is not cited to the brand.

    Why it exists: the ownership can be watertight while the origin is not.
    Many brands render their "our story" page client-side, or make no origin
    claim at all. Those rows keep their ownership standing and lose only their
    line on the map.
    """
    return ORIGIN_UNCONFIRMED_MARKER in (notes or "").casefold()


def build_brand_records(
    brands: list[dict[str, str]], places: dict[str, dict]
) -> list[dict]:
    """Turn each CSV row into the object the page consumes.

    Why it exists: this is the one place that decides the shape of the JSON
    the front end reads. Every key the page touches is named here, so a change
    to the page's data needs is a change to this function and nowhere else.

    Coordinates come out as ``null`` rather than a guess when a place is
    absent. The map draws nothing for a null, which is the honest rendering of
    "we do not know where this brand says it is from".
    """
    records: list[dict] = []

    for row in brands:
        origin = places.get(
            place_key(row["brand_origin_city"], row["brand_origin_state"])
        )
        hq = places.get(place_key(row["parent_hq_city"], row["parent_hq_state"]))

        records.append(
            {
                "brand": row["brand"],
                "category": row["category"],
                "qualifying_signal": row["qualifying_signal"],
                "signal_evidence": row["signal_evidence"],

                # Where the brand says it is from, and the brand's own page
                # that says so.
                "brand_origin": {
                    "city": row["brand_origin_city"],
                    "state": row["brand_origin_state"],
                    "source": row["brand_origin_source"],
                    "lat": origin["lat"] if origin else None,
                    "lon": origin["lon"] if origin else None,
                },

                # The ownership chain. direct_owner and ultimate_parent are
                # often the same company, and that is not an error.
                "direct_owner": row["direct_owner"],
                "ultimate_parent": row["ultimate_parent"],
                "parent_type": row["parent_type"],
                "parent_hq": {
                    "city": row["parent_hq_city"],
                    "state": row["parent_hq_state"],
                    "country": row["parent_hq_country"],
                    "lat": hq["lat"] if hq else None,
                    "lon": hq["lon"] if hq else None,
                },

                # Two independent sources, and the date they were checked.
                "sources": [
                    s
                    for s in (row["ownership_source_1"], row["ownership_source_2"])
                    if s
                ],
                "verified_on": row["verified_on"],
                "notes": row["notes"],

                # Precomputed so the page does not have to parse notes text.
                "unverified": row_is_unverified(row["notes"]),
                "origin_unconfirmed": row_origin_unconfirmed(row["notes"]),

                # True when the chain has a middle, which the hover card shows
                # as "brand, then subsidiary, then holding company".
                "has_intermediate_owner": (
                    row["direct_owner"].strip().casefold()
                    != row["ultimate_parent"].strip().casefold()
                ),
            }
        )

    return records


def build_parent_records(
    brands: list[dict[str, str]], places: dict[str, dict]
) -> list[dict]:
    """Build one object per ultimate parent, with its brand count.

    Why it exists: the Sankey tree needs one node per parent, sized by how
    many of our brands it owns, and the page should not have to group rows
    itself.

    Note what ``brand_count`` counts: brands *in this dataset*, not brands the
    company owns in the world. A parent with 6 rows here may own 60 breakfast
    brands overall. The page's limits section says so, because the difference
    matters.

    ``defaultdict(list)`` is the standard library's group-by: reading a key
    that does not exist yet creates an empty list rather than raising, so the
    loop needs no "first time I have seen this parent" branch.
    """
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in brands:
        grouped[row["ultimate_parent"]].append(row)

    parents: list[dict] = []
    for name, group in grouped.items():
        first = group[0]  # HQ and type are properties of the parent, not the row
        hq = places.get(place_key(first["parent_hq_city"], first["parent_hq_state"]))

        parents.append(
            {
                "name": name,
                "parent_type": first["parent_type"],
                "brand_count": len(group),
                "brands": sorted(r["brand"] for r in group),
                "hq": {
                    "city": first["parent_hq_city"],
                    "state": first["parent_hq_state"],
                    "country": first["parent_hq_country"],
                    "lat": hq["lat"] if hq else None,
                    "lon": hq["lon"] if hq else None,
                },
            }
        )

    # Biggest owner first, then alphabetical, so the tree and the legend have
    # a stable and meaningful order.
    parents.sort(key=lambda p: (-p["brand_count"], p["name"]))
    return parents


def compute_summary(brands: list[dict[str, str]], parents: list[dict]) -> dict:
    """Compute every number the headline and the summary tiles show.

    Why it exists: the page's opening sentence is a claim about the data, and
    it has to come from the data rather than from anybody's expectation.
    Putting the arithmetic here, once, means the headline, the tiles, and the
    README cannot drift apart.

    ``top_n_share`` is the share of brands *in this dataset* owned by the
    largest few parents. It is a concentration measure for this sample only,
    not a market share, and the page says so in its limits section.
    """
    total = len(brands)

    # Guard the division so a run against an empty CSV gives a clear zeroed
    # summary rather than a ZeroDivisionError traceback.
    if total == 0:
        return {
            "total_brands": 0,
            "total_parents": 0,
            "top_n": TOP_N_PARENTS,
            "top_n_parents": [],
            "top_n_brand_count": 0,
            "top_n_share": 0.0,
            "counts_by_parent_type": {},
            "not_conglomerate_count": 0,
            "not_conglomerate_types": sorted(NOT_CONGLOMERATE_TYPES),
            "unverified_count": 0,
            "origin_unconfirmed_count": 0,
            "counts_by_category": {},
            "counts_by_signal": {},
            "last_verified": "",
        }

    top = parents[:TOP_N_PARENTS]
    top_count = sum(p["brand_count"] for p in top)

    # Counter is the standard library's tally tool: it turns a list of values
    # into a value-to-count dictionary in one step.
    by_type = Counter(row["parent_type"] for row in brands)
    by_category = Counter(row["category"] for row in brands)
    by_signal = Counter(row["qualifying_signal"] for row in brands)

    not_conglomerate = sum(
        count for kind, count in by_type.items() if kind in NOT_CONGLOMERATE_TYPES
    )
    unverified = sum(1 for row in brands if row_is_unverified(row["notes"]))
    origin_unconfirmed = sum(
        1 for row in brands if row_origin_unconfirmed(row["notes"])
    )

    # The most recent verification date, which the footer shows as "last
    # verified". ISO dates sort correctly as plain strings, so max() is safe.
    dates = [row["verified_on"] for row in brands if row["verified_on"].strip()]

    return {
        "total_brands": total,
        "total_parents": len(parents),

        "top_n": TOP_N_PARENTS,
        "top_n_parents": [
            {"name": p["name"], "brand_count": p["brand_count"]} for p in top
        ],
        "top_n_brand_count": top_count,
        # Rounded to three places: enough for a one-decimal percentage on the
        # page without implying precision the sample does not have.
        "top_n_share": round(top_count / total, 3),

        "counts_by_parent_type": dict(sorted(by_type.items())),
        "not_conglomerate_count": not_conglomerate,
        "not_conglomerate_types": sorted(NOT_CONGLOMERATE_TYPES),

        "unverified_count": unverified,
        "origin_unconfirmed_count": origin_unconfirmed,
        "counts_by_category": dict(sorted(by_category.items())),
        "counts_by_signal": dict(sorted(by_signal.items())),
        "last_verified": max(dates) if dates else "",
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build(
    brands_csv: Path = BRANDS_CSV,
    places_csv: Path = PLACES_CSV,
    output_json: Path = OUTPUT_JSON,
) -> dict:
    """Run the whole build and write the JSON file.

    Why it exists: one function that does the build end to end, with every
    path injectable, so the tests can run it against a small hand-made CSV in
    a temporary directory.

    Raises ``ValueError`` if any row is missing its evidence, or if any place
    is missing from places.csv. Both are loud on purpose: an unsourced row
    would publish a claim the project promised not to make, and a silently
    absent map point is worse than a failed build.
    """
    brands = load_brands(brands_csv)
    places = load_places(places_csv)

    # Gate 1: the evidence rules. Re-uses validate.py so there is one
    # definition of a publishable row.
    problems = check_required_fields(brands)
    if problems:
        raise ValueError(
            f"{len(problems)} row problem(s) in {brands_csv.name}; refusing to "
            "build a JSON file the page would present as sourced:\n  "
            + "\n  ".join(problems)
        )

    # Gate 2: every named place has coordinates.
    missing = find_missing_places(brands, places)
    if missing:
        raise ValueError(
            f"{len(missing)} place(s) in {brands_csv.name} are not in "
            f"{places_csv.name}:\n  " + "\n  ".join(missing)
        )

    payload = {
        "brands": build_brand_records(brands, places),
        "parents": build_parent_records(brands, places),
        "summary": None,  # filled in below, once parents are ranked
    }
    payload["summary"] = compute_summary(brands, payload["parents"])

    output_json.parent.mkdir(parents=True, exist_ok=True)
    # indent=2 keeps the committed file readable in a diff, which matters
    # because this file is checked in. sort_keys is left off so the key order
    # stays the order written above, which reads more logically than
    # alphabetical.
    output_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    return payload


def main(argv: list[str] | None = None) -> int:
    """Build the JSON and print a short report. Returns the exit code.

    Why it exists: gives a readable summary at the terminal, so the headline
    numbers can be sanity-checked without opening the JSON file.
    """
    payload = build()
    summary = payload["summary"]

    print(f"Wrote {OUTPUT_JSON.relative_to(REPO_ROOT)}")
    print(f"  brands:            {summary['total_brands']}")
    print(f"  ultimate parents:  {summary['total_parents']}")
    print(
        f"  top {summary['top_n']} parents own:  "
        f"{summary['top_n_brand_count']} brands "
        f"({summary['top_n_share'] * 100:.1f}%)"
    )
    for parent in summary["top_n_parents"]:
        print(f"      {parent['name']}: {parent['brand_count']}")
    print(f"  not conglomerate:  {summary['not_conglomerate_count']}")
    print(f"  unverified rows:   {summary['unverified_count']}")
    print(f"  origin unconfirmed:{summary['origin_unconfirmed_count']:>4}")
    print(f"  last verified:     {summary['last_verified']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
