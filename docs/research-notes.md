# Research notes: findings in hand, not yet in the dataset

Working document. Everything here was read on the page it is cited to. These
rows are not in `data/brands.csv` yet because each one still needs its second
source opened, or a field confirmed. Section 6 of [DECISIONS.md](../DECISIONS.md)
is the full candidate queue; this file is the part already part-researched.

Nothing in this file may be copied into the CSV without opening the second
source first.

---

## Confirmed facts, second source still needed

### Nature's Path -> Nature's Path Foods, Inc. (family_owned)
- Canadian, privately held, family-owned, HQ Richmond, British Columbia.
- Founded 1985 by Arran and Ratana Stephens. Son Arjan became president in 2023.
- Describes itself as "an independent and family-owned company" and "North
  America's largest independent organic breakfast food brand".
- Signal: `family_claim`.
- Candidate sources: naturespath.com press releases, the Richmond Chamber of
  Commerce listing, the Organic Trade Association honoree page for the founders.
- Note: naturespath.com/en-us/our-story/ returns product listings only when
  scraped, so the brand's own wording needs a different page.

### Weisenberger Mill -> Weisenberger Mill (family_owned)
- READ, from the weisenberger.com site footer:
  "Weisenberger Mill is located on the South Elkhorn Creek in southern Scott
  County, Kentucky. Six generations of Weisenberger's have operated the mill at
  the present location since 1865."
- Signal: `farm_name` (Mill) plus `family_claim` (six generations).
- Origin: Midway, KY (Scott County). Needs a second source and a city citation.

### Anson Mills -> Anson Mills (independent)
- READ, from https://ansonmills.com/biographies :
  "Never one for half measures, Glenn, in 1998, sold his worldly possessions,
  tossed his business card, and rented a sprawling metal warehouse behind a car
  wash in Columbia, South Carolina. He installed four native granite stone
  mills. Anson Mills was born."
  "Catherine lives in Charlotte, North Carolina, and is a full partner in Anson
  Mills Direct to Chefs Worldwide."
- Founder: Glenn Roberts. Origin: Columbia, SC. Signal: `farm_name`.

### Hometown Food Company cluster -> Brynwood Partners (private_equity)
Hometown Food Company, Chicago IL, formed by Brynwood Partners in June 2018 to
buy a portfolio from The J.M. Smucker Company. Brynwood is "founded in 1984 and
based in Greenwich, CT ... private equity firm" (READ, on the PRNewswire
Arrowhead Mills release). Manufacturing in Toledo OH and Hereford TX.

Portfolio includes these qualifying brands, each needing its own two sources:
- **Hungry Jack** - `founder_name`, a named persona on pancake mix
- **Martha White** - `founder_name`, a named persona on baking mixes
- **Jim Dandy** - `founder_name` persona, grits
- **Birch Benders** - `origin_place`, signal needs confirming

Arrowhead Mills from this cluster is already in the dataset.

### Nature's Bakery -> Mars, Incorporated (private_company)
- Founded 2011, HQ Reno NV, acquired by Mars in 2020 or 2021 (date needs
  pinning down). Mars HQ McLean VA. Mars invested $237m in a Salt Lake City
  facility, opened 2025.
- The brand calls itself "a family-owned company" while being owned by Mars,
  which is itself family-owned. Per DECISIONS.md, Mars is `private_company`
  and the family control goes in `notes`, so the independent count keeps its
  meaning.
- Signal: `family_claim`.

### Post Consumer Brands cluster -> Post Holdings, Inc. (public_company)
READ, from https://www.postconsumerbrands.com/our-brands/ navigation and
https://www.postconsumerbrands.com/our-history/ :
- Post Consumer Brands, LLC, 20802 Kensington Boulevard, Lakeville, MN 55044.
- Post Holdings, Inc., 2503 S. Hanley Road, St. Louis, MO 63144.
- "Post Consumer Brands acquires the Weetabix U.S. portfolio of cereals,
  including Puffins, Alpen and Barbara's cereal".
- "Post Holdings purchases MOM Brands (renamed from the Malt-O-Meal Company in
  2012) and merges it with Post Foods to create Post Consumer Brands".
- Qualifying candidate still to do: **Mom's Best** (`family_claim`).
- Barbara's from this cluster is already in the dataset.

### General Mills cluster -> General Mills, Inc. (public_company)
- **Larabar** - `founder_name`, named for founder Lara Merriken. The Cornucopia
  article READ for Annie's also lists "Cascadian Farm, Larabar and Food Should
  Taste Good" among General Mills' natural and organic acquisitions, so one
  source is in hand.
- **Nature Valley** - `farm_imagery`. naturevalley.com/our-story carries
  "(c) 2026 General Mills. All rights reserved.", so ownership has one source.
  The origin claim and the imagery evidence still need a readable page.

### PepsiCo cluster -> PepsiCo, Inc. (public_company)
- **Quaker Oats** - `founder_name`, a named persona. PepsiCo bought Quaker Oats
  in 2001. Quaker HQ Chicago IL, PepsiCo HQ Purchase NY.
- **Pearl Milling Company** - `farm_name` plus `origin_place`. Renamed from Aunt
  Jemima in 2021. "Pearl Milling Company was founded in 1888 in St. Joseph,
  Missouri". Chain: brand -> The Quaker Oats Company -> PepsiCo.
- Candidate source: pepsico.com press release on the rebrand, plus NPR or PBS.

### Clif Bar signal detail
The row is in the dataset with ownership firm, but the "named for the founder's
father Clifford" story is not in either source opened, so the row carries
`origin_unconfirmed`. Clif Bar's own story page would close it.

---

## Dropped, and why

These failed the **signal** test rather than the sourcing test. Their branding
does not lean on a farm, a family, a place or a founder, whatever their
ownership turns out to be.

| Candidate | Owner found | Why dropped |
|---|---|---|
| Cream of Wheat | B&G Foods, Parsippany NJ | chef persona, not farm, family, place or founder |
| Krusteaz | The Krusteaz Company (family-owned, ex-Continental Mills) | brand name carries no signal; revisit if its packaging carries family-owned copy |
| Malt-O-Meal | Post Consumer Brands | milling reference is too weak to count |
| Alpen | Post Consumer Brands | Alpine framing on a UK-origin muesli, too weak |
| Puffins | Post Consumer Brands | no signal |

---

## Blocked

- **Wikidata.** `query.wikidata.org/sparql` and `www.wikidata.org/w/api.php`
  both refused every request made while curating. No row uses Wikidata as a
  source. `pipeline/validate.py` implements the cross-check in full and runs
  from a laptop.
- **generalmills.com** timed out on every attempt, so General Mills ownership
  rests on brand-site copyright footers plus news reporting instead of the
  corporate brands page.
- Several brand "our story" pages return navigation only when scraped, because
  they render client-side. That is the main reason 8 of the 10 current rows
  carry `origin_unconfirmed`.
