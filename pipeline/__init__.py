"""Pipeline for the farm-to-label breakfast brand ownership dataset.

Two scripts live here and they run in this order:

    validate.py   checks data/brands.csv, and cross-checks it against Wikidata
    build.py      turns data/brands.csv into site/data/brands.json

Both are laptop-only. The published page never runs either of them, and never
calls an API. It reads the committed JSON file and nothing else.
"""
