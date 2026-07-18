"""Check data/brands.csv for missing evidence, and cross-check it against Wikidata.

Why this file exists
--------------------
The dataset in ``data/brands.csv`` is hand-curated, which means every row is a
place a human can make a mistake. This script is the guard rail. It does two
separate jobs, and it is worth keeping them separate in your head:

1. **Required-field checks** (offline). Does every row actually carry the URLs
   and the date it claims to? This needs no network and always runs.
2. **Wikidata cross-check** (online). Does an independent database agree about
   who owns this brand? This needs the internet and can be skipped.

A mismatch in job 2 is *not* an error. Wikidata is edited by volunteers and
goes stale, exactly like memory does. A mismatch means "go look at this row
again", and whatever you decide gets written into that row's ``notes``.

Run it like this::

    python -m pipeline.validate               # both jobs
    python -m pipeline.validate --offline     # skip the network
    python -m pipeline.validate --limit 10    # only the first 10 rows

Exit code is 1 if the required-field checks fail, so this can sit in CI.
"""

from __future__ import annotations

# --- standard library ------------------------------------------------------
import argparse          # parses the command-line flags above
import csv               # reads brands.csv; the standard library is enough here
import datetime as dt    # validates that verified_on is a real date
import hashlib           # turns a brand name into a safe cache filename
import json              # reads and writes the cached Wikidata responses
import re                # one URL shape check
import sys               # sets the exit code
import time              # spaces requests out to be polite to Wikidata
from pathlib import Path

# --- third-party -----------------------------------------------------------
# ``requests`` is the HTTP client used for the Wikidata SPARQL queries. It is
# imported lazily inside the function that needs it, so that --offline works on
# a machine where nothing has been pip-installed yet.


# ---------------------------------------------------------------------------
# Project paths and constants
# ---------------------------------------------------------------------------

# Resolve paths relative to this file rather than the shell's working
# directory, so the script behaves the same wherever you run it from.
REPO_ROOT = Path(__file__).resolve().parent.parent
BRANDS_CSV = REPO_ROOT / "data" / "brands.csv"
CACHE_DIR = REPO_ROOT / "data" / "cache"

# Wikidata's public SPARQL endpoint. SPARQL is the query language for
# Wikidata's graph, the way SQL is the query language for a table.
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"

# Wikidata's user-agent policy asks every script to identify itself and give a
# contact route, so an admin can reach the author instead of blocking the IP.
# See https://foundation.wikimedia.org/wiki/Policy:User-Agent_policy
USER_AGENT = (
    "farm2label/1.0 (https://github.com/karishmadhingra30/farm_2_label; "
    "breakfast brand ownership research) python-requests"
)

# One request per second. Wikidata does not publish a hard rate limit for the
# SPARQL endpoint, but one per second is the conventional courtesy and keeps a
# 50-row run under a minute.
SECONDS_BETWEEN_REQUESTS = 1.0

# The columns brands.csv must have, in order. Declaring this in code means a
# renamed or dropped column is caught immediately instead of silently
# producing empty values later in build.py.
EXPECTED_COLUMNS = [
    "brand",
    "category",
    "qualifying_signal",
    "signal_evidence",
    "brand_origin_city",
    "brand_origin_state",
    "brand_origin_source",
    "direct_owner",
    "ultimate_parent",
    "parent_type",
    "parent_hq_city",
    "parent_hq_state",
    "parent_hq_country",
    "ownership_source_1",
    "ownership_source_2",
    "verified_on",
    "notes",
]

# Controlled vocabularies. Free-text typos in these columns would split one
# category into two on the page, so they are checked rather than trusted.
VALID_CATEGORIES = {"cereal", "granola", "oatmeal", "bar", "mix"}
VALID_SIGNALS = {
    "farm_name",
    "founder_name",
    "family_claim",
    "origin_place",
    "farm_imagery",
}
VALID_PARENT_TYPES = {
    "public_company",
    "private_company",
    "private_equity",
    "cooperative",
    "employee_owned",
    "family_owned",
    "independent",
}

# Columns that must always hold a URL, for every row without exception.
ALWAYS_REQUIRED_URLS = ["ownership_source_1", "ownership_source_2"]

# Columns that hold a URL when present but may be blank on a row whose gap is
# declared in notes. DECISIONS.md rule 4 is the reason this list exists: a row
# whose ownership is solid but whose self-claimed origin could not be
# confirmed stays in the dataset with a visible flag.
FLAGGABLE_URLS = ["brand_origin_source"]

# Two distinct markers, because two different things can be missing and
# conflating them would mislead the reader.
#
# UNVERIFIED_MARKER means the *ownership* claim does not rest on two
# independent sources. That is the serious one: it is the promise the page
# makes in its method section.
#
# ORIGIN_UNCONFIRMED_MARKER means the ownership is fine but the brand's
# self-claimed home town is not cited to the brand's own page, usually
# because the brand renders its story client-side or makes no such claim.
# That is a narrower gap and it deserves a narrower flag.
#
# The first version of this file had only one marker, and flagging the origin
# gaps with it put a scary "flagged" badge on nine rows out of ten, which
# buried the single row whose ownership really was short of a source.
UNVERIFIED_MARKER = "unverified"
ORIGIN_UNCONFIRMED_MARKER = "origin_unconfirmed"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_rows(csv_path: Path = BRANDS_CSV) -> list[dict[str, str]]:
    """Read brands.csv into a list of dictionaries, one per brand.

    Why it exists: every other function here takes rows rather than a path, so
    the checks can be unit-tested against a small hand-made CSV without
    touching the real dataset.

    Uses ``csv.DictReader`` rather than pandas because this script's job is to
    inspect rows one at a time and report on them. pandas earns its place in
    build.py, where whole-column reshaping is the work.
    """
    if not csv_path.exists():
        raise FileNotFoundError(
            f"{csv_path} not found. The dataset is the core of this project; "
            "there is nothing to validate without it."
        )

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

        # Compare the header against EXPECTED_COLUMNS as a set, so column
        # order can change without failing, but a missing or unknown column
        # is caught.
        found = list(reader.fieldnames or [])

    missing = [c for c in EXPECTED_COLUMNS if c not in found]
    unknown = [c for c in found if c not in EXPECTED_COLUMNS]
    if missing or unknown:
        parts = []
        if missing:
            parts.append(f"missing columns: {', '.join(missing)}")
        if unknown:
            parts.append(f"unexpected columns: {', '.join(unknown)}")
        raise ValueError(f"{csv_path.name} header is wrong. " + "; ".join(parts))

    return rows


# ---------------------------------------------------------------------------
# Job 1: required-field checks (offline)
# ---------------------------------------------------------------------------

def looks_like_url(value: str) -> bool:
    """Return True if the value is shaped like an http(s) URL.

    Why it exists: catches the common curation slips, an empty cell, a bare
    domain pasted without a scheme, or a note typed into a source column. It
    deliberately does not check that the URL resolves, because that would turn
    a fast offline check into a slow networked one.
    """
    return bool(re.match(r"^https?://[^\s]+\.[^\s]+", value.strip()))


def is_valid_date(value: str) -> bool:
    """Return True if the value is a real calendar date in YYYY-MM-DD form.

    Why it exists: the whole page rests on an "as of" date, so a typo like
    2026-13-01 has to fail here rather than render as a plausible-looking
    string on the site.
    """
    try:
        dt.date.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return False
    return True


def check_required_fields(rows: list[dict[str, str]]) -> list[str]:
    """Check every row for the evidence it is required to carry.

    Why it exists: this is the promise the page makes to its reader. Two
    ownership sources and a verification date on every row, no exceptions. If
    this function returns anything, the dataset is not publishable yet.

    Returns a list of human-readable problem strings. Empty list means clean.
    A row that declares itself ``unverified`` in notes is still required to
    have its two ownership sources; the marker covers the brand-origin gap
    only, per DECISIONS.md rule 4.
    """
    problems: list[str] = []

    # Track brand names to catch an accidental duplicate row, which would
    # quietly double-count that brand in every summary number.
    seen_brands: dict[str, int] = {}

    for index, row in enumerate(rows, start=2):  # start=2: row 1 is the header
        brand = (row.get("brand") or "").strip()
        where = f"row {index}"

        if not brand:
            problems.append(f"{where}: brand name is empty")
            continue
        where = f"row {index} ({brand})"

        if brand.casefold() in seen_brands:
            problems.append(
                f"{where}: duplicate of row {seen_brands[brand.casefold()]}"
            )
        else:
            seen_brands[brand.casefold()] = index

        notes = (row.get("notes") or "").casefold()
        ownership_flagged = UNVERIFIED_MARKER in notes
        origin_flagged = ORIGIN_UNCONFIRMED_MARKER in notes

        # --- the two ownership sources, required on every row --------------
        for column in ALWAYS_REQUIRED_URLS:
            value = (row.get(column) or "").strip()
            if not value:
                problems.append(f"{where}: {column} is empty")
            elif not looks_like_url(value):
                problems.append(f"{where}: {column} is not a URL: {value!r}")

        # Two sources that are the same source are one source.
        source_1 = (row.get("ownership_source_1") or "").strip()
        source_2 = (row.get("ownership_source_2") or "").strip()
        if source_1 and source_1 == source_2:
            problems.append(
                f"{where}: ownership_source_1 and ownership_source_2 are the "
                "same URL, so the claim has one source, not two"
            )

        # --- URLs that may be blank only on a flagged row ------------------
        for column in FLAGGABLE_URLS:
            value = (row.get(column) or "").strip()
            if not value:
                # A blank brand-origin source is allowed only on a row that
                # declares the gap, with either marker.
                if not (origin_flagged or ownership_flagged):
                    problems.append(
                        f"{where}: {column} is empty and notes declares no gap "
                        f"(expected '{ORIGIN_UNCONFIRMED_MARKER}' or "
                        f"'{UNVERIFIED_MARKER}')"
                    )
            elif not looks_like_url(value):
                problems.append(f"{where}: {column} is not a URL: {value!r}")

        # A row may leave the origin out, but it may not claim a city with no
        # source at all unless it says so.
        if (row.get("brand_origin_city") or "").strip() and not (
            (row.get("brand_origin_source") or "").strip()
            or origin_flagged
            or ownership_flagged
        ):
            problems.append(
                f"{where}: brand_origin_city is set but brand_origin_source is "
                f"empty and no gap is declared in notes"
            )

        # --- the verification date ----------------------------------------
        verified_on = (row.get("verified_on") or "").strip()
        if not verified_on:
            problems.append(f"{where}: verified_on is empty")
        elif not is_valid_date(verified_on):
            problems.append(
                f"{where}: verified_on is not a YYYY-MM-DD date: {verified_on!r}"
            )

        # --- controlled vocabularies --------------------------------------
        category = (row.get("category") or "").strip()
        if category not in VALID_CATEGORIES:
            problems.append(
                f"{where}: category {category!r} is not one of "
                f"{sorted(VALID_CATEGORIES)}"
            )

        signal = (row.get("qualifying_signal") or "").strip()
        if signal not in VALID_SIGNALS:
            problems.append(
                f"{where}: qualifying_signal {signal!r} is not one of "
                f"{sorted(VALID_SIGNALS)}"
            )

        parent_type = (row.get("parent_type") or "").strip()
        if parent_type not in VALID_PARENT_TYPES:
            problems.append(
                f"{where}: parent_type {parent_type!r} is not one of "
                f"{sorted(VALID_PARENT_TYPES)}"
            )

        # --- the ownership chain ------------------------------------------
        # Every row needs both ends of the chain named. Where a brand is owned
        # directly by the top of the chain, the two columns hold the same
        # company, which is fine and expected.
        for column in ("direct_owner", "ultimate_parent"):
            if not (row.get(column) or "").strip():
                problems.append(f"{where}: {column} is empty")

        # Evidence for the selection rule. Without this the row cannot say why
        # it belongs in the dataset at all.
        if not (row.get("signal_evidence") or "").strip():
            problems.append(f"{where}: signal_evidence is empty")

    return problems


# ---------------------------------------------------------------------------
# Job 2: Wikidata cross-check (online)
# ---------------------------------------------------------------------------

def cache_path_for(brand: str) -> Path:
    """Return the cache file path for one brand's Wikidata response.

    Why it exists: brand names contain apostrophes, slashes, and spaces, none
    of which belong in a filename. Hashing the name gives a stable, safe
    filename, and the brand is written inside the file so the cache stays
    readable by a human.
    """
    digest = hashlib.sha256(brand.casefold().encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"{digest}.json"


def build_sparql_query(brand: str) -> str:
    """Build the SPARQL query that asks Wikidata who owns this brand.

    Why it exists: keeping the query in one documented function means the
    property choices are reviewable rather than buried in a string.

    The properties being read:

    * ``P127`` is "owned by". This is the one that usually names the company
      holding a consumer brand.
    * ``P749`` is "parent organization". This is the one that usually applies
      when the brand's Wikidata item is a *company* rather than a product.

    A brand can legitimately have either, both, or neither, so both are
    fetched with OPTIONAL. Without OPTIONAL, a brand missing one property
    would return no rows at all, which would look like "not on Wikidata".

    The label match uses ``rdfs:label`` plus ``skos:altLabel`` so that a brand
    filed under a slightly different name, for example its legal name, still
    matches.
    """
    # Escape double quotes and backslashes so a brand name cannot break out of
    # the SPARQL string literal.
    safe = brand.replace("\\", "\\\\").replace('"', '\\"')

    return f"""
SELECT ?item ?itemLabel ?ownedBy ?ownedByLabel ?parentOrg ?parentOrgLabel
WHERE {{
  {{ ?item rdfs:label "{safe}"@en }}
  UNION
  {{ ?item skos:altLabel "{safe}"@en }}

  OPTIONAL {{ ?item wdt:P127 ?ownedBy }}
  OPTIONAL {{ ?item wdt:P749 ?parentOrg }}

  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
LIMIT 10
""".strip()


def fetch_wikidata(brand: str, *, use_cache: bool = True) -> dict:
    """Ask Wikidata who owns this brand, caching the answer on disk.

    Why it exists: the cross-check is re-run many times while the dataset is
    being curated. Caching means Wikidata is queried once per brand rather
    than once per run, which is both faster and the polite way to use a free
    public endpoint.

    Returns the parsed SPARQL JSON response. Raises on a network or HTTP
    error, so the caller can decide whether one unreachable brand should stop
    the whole run.
    """
    # Imported here rather than at module top so that --offline works without
    # requests installed.
    import requests

    cache_file = cache_path_for(brand)
    if use_cache and cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        return cached["response"]

    response = requests.get(
        WIKIDATA_SPARQL,
        params={"query": build_sparql_query(brand), "format": "json"},
        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()

    # Write the brand and the fetch time alongside the response so the cache
    # can be read and audited by hand later.
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(
            {
                "brand": brand,
                "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "query": build_sparql_query(brand),
                "response": payload,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Space requests out. This sleep only runs on a cache miss, so a fully
    # cached re-run is instant.
    time.sleep(SECONDS_BETWEEN_REQUESTS)
    return payload


def owners_from_response(payload: dict) -> set[str]:
    """Pull the set of owner and parent names out of a SPARQL response.

    Why it exists: the SPARQL JSON shape is nested and repetitive. One brand
    can come back as several rows, one per combination of owner and parent.
    Flattening to a set of names is what the comparison actually needs.
    """
    names: set[str] = set()
    for binding in payload.get("results", {}).get("bindings", []):
        for key in ("ownedByLabel", "parentOrgLabel"):
            label = binding.get(key, {}).get("value", "").strip()
            if label:
                names.add(label)
    return names


def names_agree(csv_name: str, wikidata_names: set[str]) -> bool:
    """Decide whether the CSV's owner appears among Wikidata's owners.

    Why it exists: the same company is written many ways. "General Mills",
    "General Mills, Inc.", and "General Mills Inc" are one company, and a
    plain string equality check would report all three as mismatches and bury
    the real disagreements in noise.

    The comparison is deliberately loose: lowercase, strip the common company
    suffixes and punctuation, then accept a match if either name contains the
    other. Loose matching risks a false agreement, which is the safer failure
    here, because the cost of a missed mismatch is one row not re-checked,
    while the cost of a false mismatch is losing trust in the whole report.
    """
    def normalise(name: str) -> str:
        lowered = name.casefold()
        # Drop legal-form suffixes and punctuation that carry no meaning for
        # identity purposes.
        lowered = re.sub(
            r"\b(inc|incorporated|corp|corporation|co|company|plc|llc|ltd|"
            r"limited|holdings|holding|group|sa|nv|ag|kgaa)\b",
            " ",
            lowered,
        )
        lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
        return " ".join(lowered.split())

    target = normalise(csv_name)
    if not target:
        return False

    for candidate in wikidata_names:
        other = normalise(candidate)
        if not other:
            continue
        if target == other or target in other or other in target:
            return True
    return False


def cross_check_wikidata(
    rows: list[dict[str, str]],
    *,
    use_cache: bool = True,
    limit: int | None = None,
) -> dict[str, list[str]]:
    """Compare every row's ownership against Wikidata and report the result.

    Why it exists: an independent second opinion on the hand-curated column
    that matters most. This is the check described in DECISIONS.md rule 1's
    second source.

    Returns a dictionary of three lists, keyed ``agreed``, ``mismatched``, and
    ``absent``, each holding human-readable lines.

    A mismatch is never corrected automatically. Wikidata is volunteer-edited
    and goes stale, so the CSV may well be the more current of the two. A
    mismatch means "recheck this row by hand and write down what you decided".
    """
    results: dict[str, list[str]] = {"agreed": [], "mismatched": [], "absent": [], "errors": []}

    subset = rows[:limit] if limit else rows
    for row in subset:
        brand = (row.get("brand") or "").strip()
        if not brand:
            continue

        try:
            payload = fetch_wikidata(brand, use_cache=use_cache)
        except Exception as exc:  # network, HTTP, or malformed JSON
            # One unreachable brand should not abandon the other 44, so the
            # error is recorded and the loop carries on.
            results["errors"].append(f"{brand}: could not query Wikidata ({exc})")
            continue

        wikidata_names = owners_from_response(payload)
        if not wikidata_names:
            # Either the brand has no Wikidata item, or its item records no
            # ownership. Both are fine and both are worth noting.
            results["absent"].append(
                f"{brand}: no owner or parent recorded on Wikidata"
            )
            continue

        # A row agrees if Wikidata names either end of our recorded chain.
        # Wikidata is inconsistent about whether it stores the immediate owner
        # or the top of the group, so accepting either is correct rather than
        # lenient.
        direct = (row.get("direct_owner") or "").strip()
        ultimate = (row.get("ultimate_parent") or "").strip()

        if names_agree(direct, wikidata_names) or names_agree(ultimate, wikidata_names):
            results["agreed"].append(f"{brand}: agrees with Wikidata")
        else:
            results["mismatched"].append(
                f"{brand}: CSV says direct={direct!r}, ultimate={ultimate!r}; "
                f"Wikidata says {sorted(wikidata_names)}"
            )

    return results


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Run the checks and print a report. Returns the process exit code.

    Why it exists: gives the script one documented entry point, so it can be
    called from a test or from CI as well as from a terminal.

    Exit code 1 means the required-field checks found something. A Wikidata
    mismatch does not fail the run, because a mismatch is a prompt to a human
    rather than a defect in the dataset.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--offline",
        action="store_true",
        help="run the required-field checks only, no network",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="re-query Wikidata even when a cached response exists",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="cross-check only the first N rows (useful while curating)",
    )
    args = parser.parse_args(argv)

    rows = load_rows()
    print(f"Loaded {len(rows)} rows from {BRANDS_CSV.relative_to(REPO_ROOT)}\n")

    # --- job 1 ------------------------------------------------------------
    print("Required-field checks")
    print("-" * 60)
    problems = check_required_fields(rows)
    if problems:
        for problem in problems:
            print(f"  FAIL  {problem}")
        print(f"\n{len(problems)} problem(s) found.\n")
    else:
        print("  All rows carry two ownership sources and a valid date.\n")

    # --- job 2 ------------------------------------------------------------
    if args.offline:
        print("Wikidata cross-check skipped (--offline).")
    else:
        print("Wikidata cross-check")
        print("-" * 60)
        results = cross_check_wikidata(
            rows, use_cache=not args.no_cache, limit=args.limit
        )
        print(f"  agreed:     {len(results['agreed'])}")
        print(f"  mismatched: {len(results['mismatched'])}")
        print(f"  absent:     {len(results['absent'])}")
        if results["errors"]:
            print(f"  errors:     {len(results['errors'])}")
        print()

        # Mismatches are the point of this job, so they print in full.
        for line in results["mismatched"]:
            print(f"  RECHECK  {line}")
        for line in results["absent"]:
            print(f"  NOTE     {line}")
        for line in results["errors"]:
            print(f"  ERROR    {line}")
        if results["mismatched"]:
            print(
                "\n  A mismatch is not automatically an error. Wikidata is "
                "volunteer-edited\n  and goes stale. Recheck the row by hand "
                "and record the decision in notes."
            )

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
