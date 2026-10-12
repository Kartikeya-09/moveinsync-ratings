# MoveInSync Play Store ratings: why they sit where they do, and what to fix first

**Live dashboard:** [add dashboard link]
**Recommendation (PDF):** [add PDF link] (Word version: `docs/MoveInSync_Ratings_Recommendation.docx`)
**Demo video:** [add Loom link]

## The answer in four lines

- The store rating is **4.64** from 114,871 ratings. The problem is a tail of about 8,200 one- and two-star ratings that holds it below a ceiling of 4.92.
- Of low-star reviews that name a clear cause, about **81% say nothing about cabs, drivers or support**. The app is the main lever.
- Largest causes: crashes and slow loading (15.7% of low-star reviews), login and forced-logout failures (14.6%), booking failures (13.6%).
- Replies to low-star reviews have almost stopped: about 13% in Q4 2025, about 0.5% in the last two quarters.

Top 3 actions: restart replies to low-star reviews, fix login and OTP failures, add a release gate and fix crashes. Details, owners, metrics and ticket-ready write-ups are in the recommendation document.

## How it works

```
scrape_reviews.py     Play Store reviews + store rating histogram -> data/
classify_reviews.py   tags each review by cause and owning team (keyword rules)
build_dashboard.py    builds the static dashboard from the tagged data
evaluate_validation.py scores the tagger against a hand-labelled sample
```

Tagging is rule-based on purpose: it is free, repeatable, and every tag can be traced to the pattern that fired. Owners are grouped as App / Product, Platform, and Operations & support. Rating uplift per cause is estimated from the store's own star histogram (assumptions are stated in the recommendation document).

## Re-run it (answers "how are our ratings?" any time)

```
pip install google-play-scraper pandas
python scrape_reviews.py        # writes data/reviews.csv and data/app_meta.json
python classify_reviews.py      # writes data/reviews_tagged.csv (last 24 months)
python build_dashboard.py       # writes dashboard.html; publish it as index.html
```

The dashboard includes a release check: for each app version with 40+ reviews it compares the share of 1-2 star reviews with the baseline and flags **Regression** or **Watch**.

## Accuracy

I hand-labelled 114 reviews (`data/validation_labeled.csv`), sampled across themes, not at random.

| | All tags right | Tag precision | Tag recall |
|---|---|---|---|
| First version of the rules | 57% | 72% | 85% |
| After fixing errors the labels exposed | 69% | 83% | 88% |

The second row is **optimistic**, because the rules were tuned on the same sample. Reproduce with `python evaluate_validation.py data/validation_labeled.csv`.

## Limits

- Reviews are self-selected and skew negative (written-review average 3.75 against a store rating of 4.64).
- Reviews show symptoms, not root causes. Every "likely cause" in the recommendation is a hypothesis for engineering to confirm in logs.
- About 36% of low-star reviews carry no usable detail ("worst app") and are not assigned a cause.
- Non-English text, including Filipino-English mixes, is undercounted.
- No access to Play Console (crash and ANR rates, device split). That is the first thing to check.
- No public Reddit or X complaints were found, so those sources are not used.

## Data note

The raw scrape includes reviewer names, so it is not committed. `data/reviews_tagged.csv` has names removed. Run `scrape_reviews.py` to regenerate the raw file.

## Tools

Python (google-play-scraper, pandas), Claude for writing code, analysis and drafting, GitHub Pages for the dashboard. AI output was checked against the data and a hand-labelled sample.
