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
from concurrent.futures import ThreadPoolExecutor

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


# --- plot summaries -------------------------------------------------------
# IMDb's public datasets carry no plot, so the catalog rows showed only year,
# genre and rating - Stremio renders a description under a poster when the
# addon sends one, and we never did. TMDB fills that in, looked up by IMDb id.
# The key is optional: without it the build still succeeds, just without plots.
TMDB_KEY = os.environ.get("TMDB_API_KEY", "")


def fetch_overview(imdb_id):
    """TMDB plot for one IMDb id, or '' if anything at all goes wrong."""
    url = ("https://api.themoviedb.org/3/find/%s?api_key=%s&external_source=imdb_id"
           % (imdb_id, TMDB_KEY))
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.load(r)
    except Exception:
        return ""
    hits = data.get("movie_results") or data.get("tv_results") or []
    return (hits[0].get("overview") or "") if hits else ""


def fetch_overviews(imdb_ids):
    """Look the whole list up at once. 8 at a time keeps us well inside TMDB's
    rate limit while turning ~110s of serial requests into ~15s."""
    if not TMDB_KEY:
        print("TMDB_API_KEY not set - building without plot summaries")
        return {}
    ids = sorted(set(imdb_ids))
    with ThreadPoolExecutor(max_workers=8) as pool:
        texts = list(pool.map(fetch_overview, ids))
    out = {i: t for i, t in zip(ids, texts) if t}
    print("plots: %d of %d titles" % (len(out), len(ids)))
    return out


OVERVIEWS = {}


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
        meta = {
            "id": i["id"],
            "type": kind,
            "name": i["name"],
            "poster": f"https://images.metahub.space/poster/medium/{i['id']}/img",
            "imdbRating": f"{i['rating']:.1f}",
            "releaseInfo": str(i["year"]),
            "genres": i["genres"],
        }
        # Only send the key when we actually have text; an empty description
        # is worse than none, because Stremio reserves the space for it.
        if OVERVIEWS.get(i["id"]):
            meta["description"] = OVERVIEWS[i["id"]]
        metas.append(meta)
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

# Work out every id that will appear in any catalog, then fetch all plots in
# one pass - the year lists and the all-time lists overlap, so this avoids
# asking TMDB for the same title twice.
wanted = []
for kind, items in candidates.items():
    this_year_items = [i for i in items if i["year"] == this_year]
    pool_items = this_year_items if len(this_year_items) >= MIN_LIST_SIZE else items
    wanted += [i["id"] for i in rank(list(pool_items), PRIOR_VOTES[kind])[:LIST_SIZE]]
for kind, items in alltime.items():
    wanted += [i["id"] for i in rank(list(items), ALLTIME_PRIOR_VOTES[kind])[:ALLTIME_LIST_SIZE]]
OVERVIEWS = fetch_overviews(wanted)

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
