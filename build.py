"""Build a static Stremio catalog addon: the top-rated movies and series of the current year.

Source: IMDb's public daily datasets (https://datasets.imdbws.com), no API key needed.
Ranking: IMDb weighted rating, so a title needs broad agreement (many votes) to rank high.

    score = v/(v+m) * R + m/(v+m) * C

    R = the title's average rating, v = its number of votes,
    m = prior weight (votes), C = mean rating of all candidate titles.

Output goes to site/ and is published with GitHub Pages.
"""
import csv
import datetime
import gzip
import json
import os
import urllib.request

DATASETS = "https://datasets.imdbws.com/"
MIN_VOTES = {"movie": 25000, "series": 10000}
PRIOR_VOTES = {"movie": 100000, "series": 30000}
LIST_SIZE = 50
MIN_LIST_SIZE = 20   # early in the year, top up with last year's titles

TYPE_MAP = {"movie": "movie", "tvSeries": "series", "tvMiniSeries": "series"}

csv.field_size_limit(10**9)


def download(name):
    if not os.path.exists(name):
        urllib.request.urlretrieve(DATASETS + name, name)
    return name


def read_tsv(name):
    f = gzip.open(download(name), "rt", encoding="utf-8")
    return csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)


# All-time list: only titles almost everyone has rated.
ALLTIME_MIN_VOTES = {"movie": 250000, "series": 100000}
ALLTIME_PRIOR_VOTES = {"movie": 500000, "series": 200000}
ALLTIME_LIST_SIZE = 100


def rank(items, prior_votes):
    """Sort by IMDb weighted rating (see module docstring)."""
    m = prior_votes
    mean_rating = sum(i["rating"] for i in items) / max(len(items), 1)
    for i in items:
        v = i["votes"]
        i["score"] = v / (v + m) * i["rating"] + m / (v + m) * mean_rating
    items.sort(key=lambda i: i["score"], reverse=True)
    return items


def write_catalog(kind, catalog_id, items):
    metas = []
    for i in items:
        metas.append({
            "id": i["id"],
            "type": kind,
            "name": i["name"],
            "poster": f"https://images.metahub.space/poster/medium/{i['id']}/img",
            "imdbRating": f"{i['rating']:.1f}",
            "releaseInfo": str(i["year"]),
            "genres": i["genres"],
        })
    with open(f"site/catalog/{kind}/{catalog_id}.json", "w") as f:
        json.dump({"metas": metas}, f)
    print(kind, catalog_id, len(metas), [m["name"] for m in metas[:5]])


ratings = {}
for row in read_tsv("title.ratings.tsv.gz"):
    ratings[row["tconst"]] = (float(row["averageRating"]), int(row["numVotes"]))

this_year = datetime.date.today().year
candidates = {"movie": [], "series": []}
alltime = {"movie": [], "series": []}
for row in read_tsv("title.basics.tsv.gz"):
    kind = TYPE_MAP.get(row["titleType"])
    if kind is None or row["isAdult"] == "1":
        continue
    if row["tconst"] not in ratings or not row["startYear"].isdigit():
        continue
    rating, votes = ratings[row["tconst"]]
    title = {
        "id": row["tconst"],
        "name": row["primaryTitle"],
        "year": int(row["startYear"]),
        "rating": rating,
        "votes": votes,
        "genres": [] if row["genres"] == "\\N" else row["genres"].split(","),
    }
    if votes >= ALLTIME_MIN_VOTES[kind]:
        alltime[kind].append(title)
    if title["year"] >= this_year - 1 and votes >= MIN_VOTES[kind]:
        candidates[kind].append(title)

os.makedirs("site/catalog/movie", exist_ok=True)
os.makedirs("site/catalog/series", exist_ok=True)

for kind, items in candidates.items():
    this_year_items = [i for i in items if i["year"] == this_year]
    if len(this_year_items) >= MIN_LIST_SIZE:
        items = this_year_items
    items = rank(items, PRIOR_VOTES[kind])
    write_catalog(kind, "top-year", items[:LIST_SIZE])

for kind, items in alltime.items():
    items = rank(items, ALLTIME_PRIOR_VOTES[kind])
    write_catalog(kind, "all-time", items[:ALLTIME_LIST_SIZE])

manifest = {
    "id": "com.farhat7.topofyear",
    "version": "1.0." + datetime.date.today().strftime("%Y%m%d"),
    "name": "Top of the Year",
    "description": f"Top-rated movies and series of {this_year}, plus all-time greats, from IMDb ratings (weighted by votes). Rebuilt daily.",
    "resources": ["catalog"],
    "types": ["movie", "series"],
    "idPrefixes": ["tt"],
    "catalogs": [
        {"type": "movie", "id": "top-year", "name": "Top Movies of the Year"},
        {"type": "series", "id": "top-year", "name": "Top Series of the Year"},
        {"type": "movie", "id": "all-time", "name": "All-Time Great Movies"},
        {"type": "series", "id": "all-time", "name": "All-Time Great Series"},
    ],
    "behaviorHints": {"configurable": False, "configurationRequired": False},
}
with open("site/manifest.json", "w") as f:
    json.dump(manifest, f, indent=1)
with open("site/.nojekyll", "w") as f:
    f.write("")
