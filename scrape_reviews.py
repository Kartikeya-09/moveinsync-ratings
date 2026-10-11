"""
MoveInSync Play Store review scraper (re-runnable).

Usage:
    pip install google-play-scraper pandas
    python scrape_reviews.py                 # scrape everything, save CSV, print quick stats
    python scrape_reviews.py --max 20000     # cap number of reviews per sort order
    python scrape_reviews.py --stats-only    # skip scraping, just re-print stats from saved CSV

Outputs (in ./data):
    reviews.csv   one row per review
    app_meta.json current rating, rating count, star histogram, current version
"""
import argparse
import json
import os
import time
from datetime import datetime

import pandas as pd
from google_play_scraper import Sort, app, reviews

APP_ID = "com.moveinsync.ets"
COUNTRY = "in"
LANG = "en"
OUT_DIR = "data"
CSV_PATH = os.path.join(OUT_DIR, "reviews.csv")
META_PATH = os.path.join(OUT_DIR, "app_meta.json")


def fetch_meta():
    info = app(APP_ID, lang=LANG, country=COUNTRY)
    meta = {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "title": info.get("title"),
        "score": info.get("score"),
        "ratings": info.get("ratings"),
        "reviews": info.get("reviews"),
        "histogram": info.get("histogram"),  # [1-star, 2-star, 3-star, 4-star, 5-star]
        "current_version": info.get("version"),
        "last_updated": info.get("lastUpdatedOn"),
        "installs": info.get("installs"),
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2, default=str)
    return meta


def scrape_sort(sort, label, max_reviews):
    """Page through reviews for one sort order using continuation tokens."""
    rows, token = [], None
    while len(rows) < max_reviews:
        try:
            batch, token = reviews(
                APP_ID, lang=LANG, country=COUNTRY, sort=sort,
                count=200, continuation_token=token,
            )
        except Exception as e:  # network hiccup / rate limit: wait and retry once
            print(f"  [{label}] error: {e}; sleeping 10s and retrying")
            time.sleep(10)
            try:
                batch, token = reviews(
                    APP_ID, lang=LANG, country=COUNTRY, sort=sort,
                    count=200, continuation_token=token,
                )
            except Exception as e2:
                print(f"  [{label}] giving up: {e2}")
                break
        rows.extend(batch)
        print(f"  [{label}] {len(rows)} reviews so far")
        if not batch or token is None:
            break
        time.sleep(1)  # be polite
    return rows


def scrape(max_reviews):
    all_rows = []
    # NEWEST gives full chronological coverage; MOST_RELEVANT adds highly-voted reviews
    for sort, label in [(Sort.NEWEST, "newest"), (Sort.MOST_RELEVANT, "relevant")]:
        print(f"Scraping sort={label} ...")
        all_rows.extend(scrape_sort(sort, label, max_reviews))

    df = pd.DataFrame(all_rows)
    df = df.drop_duplicates(subset="reviewId").copy()
    keep = {
        "reviewId": "review_id", "userName": "user", "content": "text",
        "score": "rating", "thumbsUpCount": "thumbs_up",
        "reviewCreatedVersion": "app_version", "at": "date",
        "replyContent": "dev_reply", "repliedAt": "reply_date",
    }
    df = df[list(keep)].rename(columns=keep)
    df["date"] = pd.to_datetime(df["date"])
    df["has_reply"] = df["dev_reply"].notna()
    df = df.sort_values("date", ascending=False)
    os.makedirs(OUT_DIR, exist_ok=True)
    df.to_csv(CSV_PATH, index=False)
    print(f"Saved {len(df)} unique reviews to {CSV_PATH}")
    return df


def quick_stats(df, meta=None):
    print("\n" + "=" * 60)
    if meta:
        print(f"Store rating: {meta['score']:.2f} from {meta['ratings']} ratings "
              f"(current version {meta['current_version']})")
        print(f"Star histogram (1..5): {meta['histogram']}")
    print(f"Reviews scraped: {len(df)}  |  {df['date'].min().date()} -> {df['date'].max().date()}")
    print(f"Mean rating of scraped reviews: {df['rating'].mean():.2f}")

    print("\nRating distribution (% of reviews):")
    print((df["rating"].value_counts(normalize=True).sort_index() * 100).round(1).to_string())

    df = df.copy()
    df["month"] = df["date"].dt.to_period("M")
    monthly = df.groupby("month")["rating"].agg(["count", "mean"]).round(2)
    print("\nLast 12 months (count, mean rating):")
    print(monthly.tail(12).to_string())

    ver = df[df["app_version"].notna()].groupby("app_version")["rating"].agg(["count", "mean"])
    ver = ver[ver["count"] >= 20].sort_values("mean")
    print("\nWorst app versions (>=20 reviews):")
    print(ver.head(10).round(2).to_string())

    low = df[df["rating"] <= 2]
    print(f"\n1-2 star share: {len(low) / len(df) * 100:.1f}%")
    print(f"Developer reply rate on 1-2 star reviews: {low['has_reply'].mean() * 100:.1f}%")
    print(f"Developer reply rate on 4-5 star reviews: "
          f"{df[df['rating'] >= 4]['has_reply'].mean() * 100:.1f}%")
    print("=" * 60)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--max", type=int, default=50000, help="max reviews per sort order")
    p.add_argument("--stats-only", action="store_true")
    args = p.parse_args()

    if args.stats_only:
        df = pd.read_csv(CSV_PATH, parse_dates=["date"])
        meta = json.load(open(META_PATH)) if os.path.exists(META_PATH) else None
    else:
        meta = fetch_meta()
        df = scrape(args.max)
    quick_stats(df, meta)