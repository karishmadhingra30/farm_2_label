# Decisions

A running log of the judgement calls in this project. The dataset is the
product here, so the rules that built it matter as much as the numbers.

---

## 1. The question

When a breakfast-aisle brand sells itself with a farm, a family, a homestead,
a place, or a founder's name, who owns that brand today?

The project answers it with a hand-curated dataset, two independent sources
per ownership claim, and a date on every row.

---

## 2. Scope

**In scope**, five categories of the breakfast aisle:

| Category value | What it covers |
|---|---|
| `cereal` | cold ready-to-eat cereal |
| `granola` | granola and muesli sold as cereal |
| `oatmeal` | oatmeal, grits, farina, other hot cereal |
| `bar` | breakfast bars, granola bars |
| `mix` | pancake, waffle, and biscuit mix |

**Out of scope**, even where the branding would qualify: syrup (Mrs.
Butterworth's, Log Cabin), yoghurt, milk and creamer, coffee, frozen waffles
and toaster pastries, bread, juice. These are breakfast, but they are not the
breakfast *aisle*, and letting them in would make the sample mean nothing.

---

## 3. The selection rule

> A brand is included if its name, its packaging, or its own "our story" page
> leans on a farm, a family, a homestead, a place of origin, or a named
> founder.

The signal has to be something the brand itself puts forward. A company that
happens to be family-owned but never says so does not qualify. A company that
says "family-owned since 1887" qualifies whether or not it still is.

Every row records which signal qualified it, in `qualifying_signal`:

| Signal | Means | Example of the kind of thing that qualifies |
|---|---|---|
| `farm_name` | "farm", "mill", "orchard", "ranch" in the brand name | a brand called `... Mills` |
| `founder_name` | a real or presented person's name in the brand | a first name or surname on the box |
| `family_claim` | explicit family, generations, or heritage copy | "family-owned since", "three generations" |
| `origin_place` | a specific place claimed as home | a state, town, or region in the name or story |
| `farm_imagery` | barn, field, silo, wheat sheaf, pasture on the pack | a barn illustration on the front panel |

Where more than one signal applies, the row records the strongest one, and
`signal_evidence` describes the rest.

### Why this rule and not a tidier one

An obvious alternative is "brands that look small but are not". That rule
builds its own answer into the selection, because it excludes every brand that
looks small and *is* small. The result would be a list of gotchas and nothing
more. The rule above is about the branding only, and it is blind to who owns
the brand, so the ownership finding comes out of the research instead of out of
the sampling.

### Independents stay in

Some brands that lean hard on a farm or a family really are family-owned,
employee-owned, or independent. Those rows are the control group. A finding of
"most of these are owned by large companies, and here are the ones that are
not" is worth more than a list picked to shock.

---

## 4. Evidence rules

1. **Two independent sources for every ownership claim.** Where possible one
   is the parent company's own material: its brands page, its investor
   relations page, or its annual report. The second is independent of the
   first: a deal announcement, trade press, a filing, or Wikidata.
2. **Never from memory.** Brand ownership moves through acquisitions,
   spinoffs, and private equity sales. Anything recalled rather than looked up
   is wrong sooner or later, so every row is looked up.
3. **A date on every row.** `verified_on` records when the lookup happened.
   The page says "as of" that date and does not pretend to be live.
4. **Failures are visible.** A row that cannot get two sources is marked
   `unverified` in `notes` and shows on the page with a flag. It is not
   dropped, because dropping it would hide the weakest part of the dataset.
5. **Brand origin is the brand's own claim.** `brand_origin_city` is where the
   brand says it comes from, cited to the brand's own page. It is not a check
   on whether anything is still made there.

---

## 5. Wording rules for the page

Say "owned by". Do not say "secretly owned by", "fake family farm", or
"masquerading as". The facts carry the point without help, and neutral wording
keeps the project fair to every company named.

No logos and no packaging images anywhere. Brand names appear as plain text.
Logos and pack designs are trademarked and copyrighted, and a text-only page
avoids the question entirely.

---

## 6. Candidate brands

Built from the selection rule, before any ownership research. The signal
column is a first read of the branding and gets confirmed (or corrected, or
the candidate gets dropped) when the row is filled in.

Ownership is deliberately absent from this table. Filling it in from memory is
the one thing this project must not do.

### Cold cereal

| Candidate | Signal read | Note |
|---|---|---|
| Kellogg's | `founder_name` | W.K. Kellogg on the box |
| Post | `founder_name` | C.W. Post |
| Cascadian Farm | `farm_name` | "Farm" in the name |
| Nature's Path | `family_claim` | founder-family story |
| Barbara's | `founder_name` | first name |
| Uncle Sam | `founder_name` | named persona |
| Mom's Best Cereals | `family_claim` | "Mom's" |
| Arrowhead Mills | `farm_name` | "Mills" |
| Erewhon | `origin_place` | place name |
| Malt-O-Meal | `farm_name` | milling reference |
| Three Sisters | `family_claim` | to confirm the signal holds |

### Granola and muesli

| Candidate | Signal read | Note |
|---|---|---|
| Bear Naked | `founder_name` | two-founder origin story |
| Purely Elizabeth | `founder_name` | first name |
| Michele's Granola | `founder_name` | first name |
| GrandyOats | `origin_place` | Maine |
| Bakery On Main | `origin_place` | street/place framing |
| Nature Valley | `farm_imagery` | valley and field imagery |
| Golden Temple | `origin_place` | to confirm |
| Jordans | `family_claim` | UK, family mill story |
| Dorset Cereals | `origin_place` | UK county |

### Oatmeal and hot cereal

| Candidate | Signal read | Note |
|---|---|---|
| Quaker Oats | `founder_name` | named persona on pack |
| Bob's Red Mill | `founder_name` | founder name plus "Mill" |
| McCann's Irish Oatmeal | `founder_name` | founder name plus origin |
| Coach's Oats | `founder_name` | named persona |
| Country Choice Organic | `farm_imagery` | rural framing |
| Cream of Wheat | `farm_imagery` | to confirm the signal holds |
| Wheat Montana | `origin_place` | state in the name |
| Hodgson Mill | `farm_name` | founder name plus "Mill" |
| Anson Mills | `farm_name` | "Mills" |
| Weisenberger Mill | `farm_name` | family mill |
| War Eagle Mill | `farm_name` | mill plus place |
| Falls Mill | `farm_name` | mill plus place |
| Marsh Hen Mill | `farm_name` | mill |
| Old Mill of Guilford | `farm_name` | mill plus place |
| Atkinson Milling | `farm_name` | family name plus milling |
| Kenyon's Grist Mill | `farm_name` | founder name plus mill |
| Palmetto Farms | `farm_name` | "Farms" |
| Maine Grains | `origin_place` | state in the name |
| Stone-Buhr | `farm_name` | millstone reference |

### Breakfast bars

| Candidate | Signal read | Note |
|---|---|---|
| Clif Bar | `founder_name` | named for the founder's father |
| Larabar | `founder_name` | founder's first name |
| Bobo's Oat Bars | `founder_name` | family nickname |
| Kate's Real Food | `founder_name` | first name |
| Annie's | `founder_name` | first name |
| Nature's Bakery | `family_claim` | family-owned copy |
| Quaker Chewy | `founder_name` | shares the Quaker persona |

### Pancake and waffle mix

| Candidate | Signal read | Note |
|---|---|---|
| Kodiak Cakes | `origin_place` | Utah, family-recipe story |
| Pearl Milling Company | `farm_name` | "Milling" |
| Hungry Jack | `founder_name` | named persona |
| Simple Mills | `farm_name` | "Mills" |
| King Arthur Baking | `founder_name` | named persona |
| Birch Benders | `origin_place` | to confirm |
| Carbon's Golden Malted | `founder_name` | family name |
| Bouchard Family Farms | `family_claim` | family plus farm |
| Homestead Gristmill | `farm_name` | homestead plus mill |
| Stonewall Kitchen | `origin_place` | to confirm |
| Pamela's Products | `founder_name` | first name |

That is 57 candidates against a target of 40 to 50 rows. The gap is deliberate.
Some candidates will fail the signal test once their own pages are read, and
some will fail the two-source test. Starting with more than the target means
the shortfall does not force a weak row in.

---

## 7. Open decisions

Recorded here as they are made.

- **Verified date.** Rows carry the real date of the lookup. The commit dates
  in this repository were set by hand while the project was being written up,
  so a row's `verified_on` may sit outside the date of the commit that added
  it. The dataset date is the true one, because it is the date the page's
  "as of" claim rests on.
