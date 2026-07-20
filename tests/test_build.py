"""Tests for the build step.

Why this file exists
--------------------
The dataset is hand-curated, which means the failure mode to worry about is
not "the code crashed". It is "the code ran, produced a plausible-looking
number, and the number was wrong". These tests pin down the four places where
that could happen quietly:

1. A row missing its evidence still builds. It must not.
2. The top-3 concentration share, the headline number, is computed wrong.
3. A city in brands.csv has no coordinates, so a map point vanishes.
4. The independent, family-owned, and employee-owned count is wrong, which
   would understate the part of the finding that makes it credible.

Every test builds from a small CSV written here in the test, not from the real
dataset. That way the expected numbers can be worked out by hand and the tests
do not change meaning every time a brand is added.

Run them with::

    python -m pytest
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import build as build_module
from pipeline.build import build, compute_summary, find_missing_places, load_brands
from pipeline.validate import check_required_fields, load_rows


# ---------------------------------------------------------------------------
# Fixtures: small hand-made datasets
# ---------------------------------------------------------------------------

# The CSV header, kept as one string so every fixture below stays readable.
# It matches EXPECTED_COLUMNS in validate.py.
HEADER = (
    "brand,category,qualifying_signal,signal_evidence,brand_origin_city,"
    "brand_origin_state,brand_origin_source,direct_owner,ultimate_parent,"
    "parent_type,parent_hq_city,parent_hq_state,parent_hq_country,"
    "ownership_source_1,ownership_source_2,verified_on,notes"
)


def make_row(
    brand: str,
    *,
    ultimate_parent: str,
    parent_type: str = "public_company",
    category: str = "cereal",
    signal: str = "farm_name",
    origin_city: str = "Bigtown",
    origin_state: str = "CA",
    hq_city: str = "Bigtown",
    hq_state: str = "CA",
    direct_owner: str | None = None,
    source_1: str = "https://example.com/brands",
    source_2: str = "https://example.org/deal",
    verified_on: str = "2026-09-22",
    notes: str = "",
    origin_source: str = "https://example.net/about",
) -> str:
    """Build one valid CSV line, with any field overridable.

    Why it exists: most tests need a handful of rows that differ in exactly one
    field. Writing 17 columns by hand each time would bury the thing each test
    is actually about.
    """
    return ",".join(
        [
            brand,
            category,
            signal,
            f"'{brand}' branding",
            origin_city,
            origin_state,
            origin_source,
            direct_owner or ultimate_parent,
            ultimate_parent,
            parent_type,
            hq_city,
            hq_state,
            "USA",
            source_1,
            source_2,
            verified_on,
            notes,
        ]
    )


PLACES = "\n".join(
    [
        "city,state,country,lat,lon",
        "Bigtown,CA,USA,34.0,-118.0",
        "Smallville,KS,USA,39.0,-98.0",
        "Milltown,VT,USA,44.0,-72.0",
    ]
)


@pytest.fixture
def workspace(tmp_path: Path):
    """Give each test its own throwaway data directory.

    Why it exists: ``tmp_path`` is pytest's per-test temporary directory. Using
    it means no test can touch the real data/brands.csv, and tests cannot
    affect each other through leftover files.

    Returns a helper that writes the two CSVs and runs the build, handing back
    the parsed JSON.
    """

    def run(brand_lines: list[str], places: str = PLACES) -> dict:
        data_dir = tmp_path / "data"
        data_dir.mkdir(exist_ok=True)
        brands_csv = data_dir / "brands.csv"
        places_csv = data_dir / "places.csv"
        out_json = tmp_path / "site" / "data" / "brands.json"

        brands_csv.write_text(HEADER + "\n" + "\n".join(brand_lines) + "\n", encoding="utf-8")
        places_csv.write_text(places + "\n", encoding="utf-8")

        return build(
            brands_csv=brands_csv, places_csv=places_csv, output_json=out_json
        )

    return run


# ---------------------------------------------------------------------------
# 1. Build refuses a row that is missing its evidence
# ---------------------------------------------------------------------------

def test_build_fails_when_ownership_source_is_missing(workspace):
    """A row with only one ownership source must stop the build.

    Why this matters: the page tells its reader that every ownership claim has
    two independent sources. If the build accepted a row with one, the page
    would be making a promise the data does not keep.
    """
    rows = [
        make_row("Good Brand", ultimate_parent="Big Foods"),
        make_row("Bad Brand", ultimate_parent="Big Foods", source_2=""),
    ]

    with pytest.raises(ValueError) as caught:
        workspace(rows)

    # The error must name the offending row, so the curator knows where to look.
    assert "Bad Brand" in str(caught.value)
    assert "ownership_source_2" in str(caught.value)


def test_build_fails_when_verified_date_is_missing(workspace):
    """A row with no verification date must stop the build.

    Why this matters: the whole page is stamped "as of" a date. A row with no
    date has no "as of", so the stamp would be false for that row.
    """
    rows = [make_row("Undated Brand", ultimate_parent="Big Foods", verified_on="")]

    with pytest.raises(ValueError) as caught:
        workspace(rows)

    assert "Undated Brand" in str(caught.value)
    assert "verified_on" in str(caught.value)


def test_build_fails_when_verified_date_is_not_a_real_date(workspace):
    """A date-shaped string that is not a date must stop the build too.

    Why this matters: 2026-13-01 looks like a date and would render happily on
    the page. Catching it here is the only place it gets caught.
    """
    rows = [make_row("Odd Date", ultimate_parent="Big Foods", verified_on="2026-13-01")]

    with pytest.raises(ValueError) as caught:
        workspace(rows)

    assert "verified_on" in str(caught.value)


def test_build_fails_when_both_sources_are_the_same_url(workspace):
    """Two identical source URLs are one source, and must not pass.

    Why this matters: this is the easiest curation slip to make, pasting the
    same link twice, and it defeats the entire two-source rule.
    """
    rows = [
        make_row(
            "Doubled",
            ultimate_parent="Big Foods",
            source_1="https://example.com/same",
            source_2="https://example.com/same",
        )
    ]

    with pytest.raises(ValueError) as caught:
        workspace(rows)

    assert "same URL" in str(caught.value)


def test_the_two_gap_markers_are_reported_separately(workspace):
    """An origin gap must not be reported as an unsourced ownership claim.

    Why this matters: the first version of the pipeline had one marker for
    both, so flagging the rows whose origin city was not cited to the brand's
    own page put the serious badge on nine rows out of ten. That buried the one
    row whose ownership really was short of a source, which is the opposite of
    what a flag is for.
    """
    rows = [
        # Ownership fine, origin not cited to the brand.
        make_row(
            "Origin Gap",
            ultimate_parent="Big Foods",
            origin_source="",
            notes="origin_unconfirmed: city taken from a news report",
        ),
        # Ownership short of a source.
        make_row(
            "Source Gap",
            ultimate_parent="Big Foods",
            notes="unverified: the second source was never opened",
        ),
        # Nothing missing.
        make_row("Clean", ultimate_parent="Big Foods"),
    ]

    payload = workspace(rows)
    by_name = {b["brand"]: b for b in payload["brands"]}

    assert by_name["Origin Gap"]["origin_unconfirmed"] is True
    assert by_name["Origin Gap"]["unverified"] is False

    assert by_name["Source Gap"]["unverified"] is True
    assert by_name["Source Gap"]["origin_unconfirmed"] is False

    assert by_name["Clean"]["unverified"] is False
    assert by_name["Clean"]["origin_unconfirmed"] is False

    assert payload["summary"]["unverified_count"] == 1
    assert payload["summary"]["origin_unconfirmed_count"] == 1


def test_claimed_origin_city_needs_a_source_or_a_declared_gap(workspace):
    """A city with no source and no declared gap must stop the build.

    Why this matters: an origin city on the page is a claim about what the
    brand says about itself. Printing one with no citation and no flag is the
    single most misleading thing this dataset could do.
    """
    with pytest.raises(ValueError) as caught:
        workspace(
            [
                make_row(
                    "Silent Claim",
                    ultimate_parent="Big Foods",
                    origin_city="Bigtown",
                    origin_source="",
                )
            ]
        )
    assert "brand_origin_source" in str(caught.value)


def test_row_may_omit_origin_source_only_when_flagged(workspace):
    """A blank brand-origin source is allowed on a row flagged unverified.

    Why this matters: DECISIONS.md rule 4 says a row whose ownership is solid
    but whose self-claimed origin could not be confirmed stays in the dataset
    with a visible flag, rather than being dropped. This test pins that rule
    down in both directions.
    """
    # Flagged and blank: allowed, and the flag reaches the JSON.
    payload = workspace(
        [
            make_row(
                "Flagged Brand",
                ultimate_parent="Big Foods",
                origin_city="",
                origin_state="",
                origin_source="",
                notes="origin_unconfirmed: could not find the brand's own origin page",
            )
        ]
    )
    assert payload["brands"][0]["origin_unconfirmed"] is True
    # No coordinates invented for a place we do not know.
    assert payload["brands"][0]["brand_origin"]["lat"] is None

    # Blank but not flagged: refused.
    with pytest.raises(ValueError) as caught:
        workspace(
            [
                make_row(
                    "Silent Gap",
                    ultimate_parent="Big Foods",
                    origin_city="",
                    origin_state="",
                    origin_source="",
                )
            ]
        )
    assert "brand_origin_source" in str(caught.value)


# ---------------------------------------------------------------------------
# 2. The top-3 share, the headline number
# ---------------------------------------------------------------------------

def test_top_three_share_on_a_hand_made_csv(workspace):
    """The top-3 concentration share must match a count done by hand.

    The fixture: 10 brands across 5 parents.

        Big Foods    4 brands
        Mega Corp    3 brands
        Holdco       1 brand
        Family Mill  1 brand
        Co-op        1 brand

    The top 3 parents are Big Foods (4), Mega Corp (3), and then one of the
    three single-brand parents (1), so the top-3 count is 8 of 10, and the
    share is 0.8.

    Why this matters: this number is the page's headline. If it is wrong, the
    one sentence a reader remembers is wrong.
    """
    rows = (
        [make_row(f"Big {i}", ultimate_parent="Big Foods") for i in range(4)]
        + [make_row(f"Mega {i}", ultimate_parent="Mega Corp") for i in range(3)]
        + [
            make_row("Held", ultimate_parent="Holdco"),
            make_row("Milled", ultimate_parent="Family Mill", parent_type="family_owned"),
            make_row("Shared", ultimate_parent="Co-op", parent_type="cooperative"),
        ]
    )

    summary = workspace(rows)["summary"]

    assert summary["total_brands"] == 10
    assert summary["total_parents"] == 5
    assert summary["top_n"] == 3
    assert summary["top_n_brand_count"] == 8
    assert summary["top_n_share"] == 0.8

    # The two largest must be named, and in descending order.
    named = [p["name"] for p in summary["top_n_parents"]]
    assert named[:2] == ["Big Foods", "Mega Corp"]
    assert summary["top_n_parents"][0]["brand_count"] == 4


def test_top_three_share_when_there_are_fewer_than_three_parents(workspace):
    """With two parents, the top-3 share is 100 percent, not an error.

    Why this matters: a slice of the dataset, or an early curation pass, can
    easily have fewer than three parents. The arithmetic should not need a
    special case, and it should not silently divide by the wrong number.
    """
    rows = [
        make_row("One", ultimate_parent="Alpha"),
        make_row("Two", ultimate_parent="Beta"),
    ]
    summary = workspace(rows)["summary"]

    assert summary["total_parents"] == 2
    assert summary["top_n_brand_count"] == 2
    assert summary["top_n_share"] == 1.0


def test_summary_on_an_empty_dataset_does_not_divide_by_zero():
    """An empty dataset gives zeroed numbers rather than a crash.

    Why this matters: the share is a division by the brand count. A clear
    zeroed summary is easier to debug than a ZeroDivisionError traceback.
    """
    summary = compute_summary([], [])

    assert summary["total_brands"] == 0
    assert summary["top_n_share"] == 0.0


# ---------------------------------------------------------------------------
# 3. Every place in brands.csv exists in places.csv
# ---------------------------------------------------------------------------

def test_build_fails_when_a_city_has_no_coordinates(workspace):
    """A city with no row in places.csv must stop the build.

    Why this matters: a missing coordinate does not look like a bug. The map
    just draws one fewer point, and nobody notices. Failing the build is the
    only way this stays visible.
    """
    rows = [
        make_row("Nowhere Brand", ultimate_parent="Big Foods", origin_city="Atlantis", origin_state="XX")
    ]

    with pytest.raises(ValueError) as caught:
        workspace(rows)

    assert "Atlantis" in str(caught.value)
    assert "Nowhere Brand" in str(caught.value)


def test_build_fails_when_a_parent_hq_has_no_coordinates(workspace):
    """The same rule applies to the parent headquarters, not just the origin.

    Why this matters: the map's whole point is the line between two points. A
    missing HQ loses the line, and with it the comparison the map exists for.
    """
    rows = [
        make_row("Brand", ultimate_parent="Big Foods", hq_city="Shangri-La", hq_state="ZZ")
    ]

    with pytest.raises(ValueError) as caught:
        workspace(rows)

    assert "Shangri-La" in str(caught.value)


def test_every_place_in_the_real_dataset_exists_in_places_csv():
    """The committed dataset must have coordinates for every place it names.

    Why this matters: the tests above prove the check works. This one runs it
    against the real files, so a brand added without its coordinates fails CI
    rather than reaching the published page.

    Skipped rather than failed when the dataset is not present yet, so the
    test suite is useful from the first commit of the pipeline.
    """
    if not build_module.BRANDS_CSV.exists() or not build_module.PLACES_CSV.exists():
        pytest.skip("dataset not curated yet")

    brands = load_brands(build_module.BRANDS_CSV)
    places = build_module.load_places(build_module.PLACES_CSV)

    missing = find_missing_places(brands, places)
    assert missing == [], "places.csv is missing: " + "; ".join(missing)


def test_place_lookup_ignores_case_and_surrounding_spaces(workspace):
    """"battle creek" and "Battle Creek" are the same place.

    Why this matters: the CSV is typed by hand. A stray capital or trailing
    space should not silently cost a map point.
    """
    payload = workspace(
        [make_row("Spaced", ultimate_parent="Big Foods", origin_city=" bigtown ")],
    )
    assert payload["brands"][0]["brand_origin"]["lat"] == 34.0


# ---------------------------------------------------------------------------
# 4. Counting the independents
# ---------------------------------------------------------------------------

def test_independent_family_and_employee_owned_are_counted(workspace):
    """The not-conglomerate count must include every one of those types.

    The fixture holds 7 brands:

        public_company   2
        private_equity   1
        independent      1
        family_owned     1
        employee_owned   1
        cooperative      1

    Four of those parent types are member, family, worker, or founder owned,
    so the count is 4 of 7.

    Why this matters: these rows are the control group. DECISIONS.md argues
    that "most are conglomerate-owned, and here are the ones that are not" is
    a more credible finding than a list of gotchas. Undercounting the second
    half would hollow that out.
    """
    rows = [
        make_row("Pub A", ultimate_parent="Big Foods", parent_type="public_company"),
        make_row("Pub B", ultimate_parent="Mega Corp", parent_type="public_company"),
        make_row("PE", ultimate_parent="Capital LP", parent_type="private_equity"),
        make_row("Indie", ultimate_parent="Indie Co", parent_type="independent"),
        make_row("Fam", ultimate_parent="Family Mill", parent_type="family_owned"),
        make_row("ESOP", ultimate_parent="Worker Mill", parent_type="employee_owned"),
        make_row("Coop", ultimate_parent="Growers Co-op", parent_type="cooperative"),
    ]

    summary = workspace(rows)["summary"]

    assert summary["total_brands"] == 7
    assert summary["not_conglomerate_count"] == 4

    # The by-type counts must also be exact, because the page colours the tree
    # by parent_type and a miscount would mislabel a node.
    assert summary["counts_by_parent_type"] == {
        "cooperative": 1,
        "employee_owned": 1,
        "family_owned": 1,
        "independent": 1,
        "private_equity": 1,
        "public_company": 2,
    }

    # The grouping is published in the JSON so the page can show its working
    # rather than asking the reader to trust the label.
    assert set(summary["not_conglomerate_types"]) == {
        "cooperative",
        "employee_owned",
        "family_owned",
        "independent",
    }


def test_unverified_rows_are_counted_not_dropped(workspace):
    """A flagged row still counts toward the total, and is counted as flagged.

    Why this matters: dropping a weak row would flatter the dataset. The rule
    is to keep it and show the flag, so both numbers have to be right.
    """
    rows = [
        make_row("Solid", ultimate_parent="Big Foods"),
        make_row(
            "Shaky",
            ultimate_parent="Big Foods",
            origin_city="",
            origin_state="",
            origin_source="",
            notes="unverified: no origin page found",
        ),
    ]
    summary = workspace(rows)["summary"]

    assert summary["total_brands"] == 2
    assert summary["unverified_count"] == 1


# ---------------------------------------------------------------------------
# Shape of the output, which the page depends on
# ---------------------------------------------------------------------------

def test_json_has_the_three_keys_the_page_reads(workspace):
    """The JSON must always carry brands, parents, and summary.

    Why this matters: the page fetches this file and reads those three keys. A
    rename here would break the site silently on load.
    """
    payload = workspace([make_row("Solo", ultimate_parent="Big Foods")])
    assert set(payload) == {"brands", "parents", "summary"}


def test_output_is_valid_json_on_disk(tmp_path: Path):
    """The written file must parse, with no NaN literals in it.

    Why this matters: pandas turns an empty cell into NaN, and ``json.dumps``
    writes NaN as the bare token ``NaN``, which is not valid JSON and makes
    ``JSON.parse`` throw in the browser. The loader fills blanks to prevent
    this, and this test is what keeps that behaviour honest.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    brands_csv = data_dir / "brands.csv"
    places_csv = data_dir / "places.csv"
    out_json = tmp_path / "site" / "data" / "brands.json"

    # A row with several deliberately empty trailing cells.
    brands_csv.write_text(
        HEADER
        + "\n"
        + make_row(
            "Blankish",
            ultimate_parent="Big Foods",
            origin_city="",
            origin_state="",
            origin_source="",
            notes="unverified: origin not found",
        )
        + "\n",
        encoding="utf-8",
    )
    places_csv.write_text(PLACES + "\n", encoding="utf-8")

    build(brands_csv=brands_csv, places_csv=places_csv, output_json=out_json)

    text = out_json.read_text(encoding="utf-8")
    assert "NaN" not in text
    parsed = json.loads(text)  # throws if the file is not valid JSON
    assert parsed["brands"][0]["brand"] == "Blankish"


def test_intermediate_owner_is_detected(workspace):
    """A two-level chain must be marked so the hover card can show it.

    Why this matters: some brands sit under a subsidiary which sits under a
    holding company. The tree uses the ultimate parent, so the middle of the
    chain would disappear entirely if the row did not record that it exists.
    """
    payload = workspace(
        [
            make_row("Deep", ultimate_parent="Holdco", direct_owner="Subsidiary Inc"),
            make_row("Flat", ultimate_parent="Big Foods"),
        ]
    )
    by_name = {b["brand"]: b for b in payload["brands"]}

    assert by_name["Deep"]["has_intermediate_owner"] is True
    assert by_name["Flat"]["has_intermediate_owner"] is False


# ---------------------------------------------------------------------------
# The real dataset, checked with validate.py's own rules
# ---------------------------------------------------------------------------

def test_real_dataset_passes_the_required_field_checks():
    """The committed dataset must satisfy every evidence rule.

    Why this matters: this is the test that stops an unsourced row reaching the
    published page. It runs the same function the build gate runs, against the
    real file.

    Skipped while the dataset is still being curated, so the suite is green
    from the first pipeline commit onward.
    """
    if not build_module.BRANDS_CSV.exists():
        pytest.skip("dataset not curated yet")

    problems = check_required_fields(load_rows(build_module.BRANDS_CSV))
    assert problems == [], "brands.csv problems:\n  " + "\n  ".join(problems)
