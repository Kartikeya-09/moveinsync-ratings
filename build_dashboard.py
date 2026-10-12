"""
Build dashboard.html (static, no JS, no external data) from data/reviews_tagged.csv.
Re-run after each scrape:   python scrape_reviews.py && python classify_reviews.py && python build_dashboard.py
"""
import html
import json
import math
import os
from datetime import datetime

import pandas as pd

LABELS = {
    "crash_slow_not_opening": "App crashes, slow, won't open",
    "feature_ui_gap": "Missing features / confusing UI",
    "booking_scheduling_fail": "Booking and scheduling failures",
    "tracking_eta_wrong": "Wrong tracking or ETA",
    "support_unresponsive": "Support / transport desk unresponsive",
    "login_otp_not_received": "OTP not arriving, can't log in",
    "cab_late_noshow": "Cab late or missing",
    "session_logout_loop": "Forced logouts, OTP on every open",
    "routing_pickup_time": "Routing and pickup times",
    "driver_conduct_safety": "Driver conduct and safety",
    "notification_rating_spam": "Notification and popup spam",
    "forced_checks_permissions": "Seat-belt / camera / permission checks",
    "noshow_policy_penalty": "No-show penalty policy",
}
OWNER_GROUP = lambda o: "ops" if o.startswith(("Operations", "Ops")) else ("platform" if o.startswith("Platform") else "app")
GROUP_NAME = {"app": "App / Product", "platform": "Platform", "ops": "Operations & support"}

# store-level inputs (from app_meta.json if present)
META = dict(score=4.64, ratings=114871, histogram=[7321, 840, 1235, 7269, 98200], current_version="?")
if os.path.exists("data/app_meta.json"):
    META.update(json.load(open("data/app_meta.json")))
H = META["histogram"]; N = META["ratings"]
TO5 = (H[0] * 4 + H[1] * 3) / N          # uplift if every 1-2 star became 5
TO4 = (H[0] * 3 + H[1] * 2) / N          # uplift if every 1-2 star became 4

df = pd.read_csv("data/reviews_tagged.csv", parse_dates=["date"])
df["text"] = df["text"].fillna("")
low = df[df.rating <= 2].copy()
p0 = len(low) / len(df)
ex = low.assign(t=low.themes_str.str.split("|")).explode("t")
esc = html.escape

# ---- KPIs
reply_rate = low.has_reply.mean()
act = low[~low.themes_str.isin(["generic_no_detail", "untagged_other"])]
def opsclass(s):
    g = {OWNER_GROUP(o) for o in s.split("|")}
    return "ops_only" if g == {"ops"} else ("no_ops" if "ops" not in g else "mixed")
oc = act.owners_str.apply(opsclass).value_counts(normalize=True)

# ---- monthly trend
m = df.assign(month=df.date.dt.to_period("M")).groupby("month").agg(n=("rating", "size"), mean=("rating", "mean"))
m = m.iloc[-24:]
if m.iloc[-1].n < 40: m = m.iloc[:-1]            # drop a thin, partial last month
W, Hh, L, B, T = 720, 220, 40, 30, 14
lo_, hi_ = 3.2, 4.4
X = lambda i: L + i * (W - L - 12) / (len(m) - 1)
Y = lambda v: T + (hi_ - v) / (hi_ - lo_) * (Hh - T - B)
pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(m["mean"]))
dots = "".join(f'<circle cx="{X(i):.1f}" cy="{Y(r["mean"]):.1f}" r="3.2"><title>{k}: {r["mean"]:.2f} avg from {int(r.n)} reviews</title></circle>' for i, (k, r) in enumerate(m.iterrows()))
grid = "".join(f'<line x1="{L}" x2="{W-12}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="g"/><text x="{L-6}" y="{Y(v)+4:.1f}" class="ax" text-anchor="end">{v:.1f}</text>' for v in (3.4, 3.6, 3.8, 4.0, 4.2))
xl = "".join(f'<text x="{X(i):.1f}" y="{Hh-8}" class="ax" text-anchor="middle">{str(k)[2:].replace("-", "/")}</text>' for i, k in enumerate(m.index) if i % 3 == 0)
chart = f'<svg viewBox="0 0 {W} {Hh}" role="img" aria-label="Average rating of written reviews by month">{grid}<polyline points="{pts}" class="ln"/>{dots}{xl}</svg>'

# ---- themes
rows = []
for t, g in ex.groupby("t"):
    if t not in LABELS: continue
    owner = low[low.themes_str.str.contains(t)].owners_str.str.split("|").explode()
    owner = owner[owner.apply(lambda o: t in LABELS and True)].mode().iloc[0]
    share = len(g) / len(low)
    rows.append((t, share, len(g), owner, share * TO4 * 0.5, share * TO5))
rows.sort(key=lambda r: -r[1])
mx = rows[0][1]
bars = "".join(
    f'<tr><td class="nm">{esc(LABELS[t])}<small>{esc(own)}</small></td>'
    f'<td class="bar"><span class="b {OWNER_GROUP(own)}" style="width:{s/mx*100:.0f}%"></span><b>{s*100:.1f}%</b></td>'
    f'<td class="num">{n}</td><td class="num">+{real:.3f}</td></tr>'
    for t, s, n, own, real, mxu in rows)

# ---- versions (flag = one-sided z against the window's baseline low-star share)
v = df[df.app_version.notna()].groupby("app_version").agg(n=("rating", "size"), mean=("rating", "mean"), first=("date", "min"), lows=("rating", lambda s: (s <= 2).sum()))
v = v[v.n >= 40].sort_values("first").tail(14).iloc[::-1]
vr = ""
for ver, r in v.iterrows():
    p = r.lows / r.n; z = (p - p0) / math.sqrt(p0 * (1 - p0) / r.n)
    st, cls = ("Regression", "bad") if z >= 1.64 else (("Watch", "warn") if z >= 1.0 else ("", ""))
    vr += f'<tr><td>{esc(str(ver))}</td><td>{r["first"]:%b %Y}</td><td class="num">{int(r.n)}</td><td class="num">{r["mean"]:.2f}</td><td class="num">{p*100:.0f}%</td><td class="{cls}">{st}</td></tr>'

# ---- quotes (short, single-theme, most thumbs-up)
def quotes(t):
    c = low[(low.themes_str == t) & low.text.str.len().between(40, 170)].sort_values("thumbs_up", ascending=False).head(2)
    return "".join(f"<blockquote>{esc(x.text.strip())}<cite>{x.rating}-star, v{esc(str(x.app_version))}, {x.thumbs_up} found helpful</cite></blockquote>" for x in c.itertuples())
qs = "".join(f"<details><summary>{esc(LABELS[t])}</summary>{quotes(t) or '<p class=m>No single-theme quotes yet.</p>'}</details>" for t, *_ in rows[:9])

top = rows[0]
html_doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>MoveInSync Play Store ratings: why and what to fix</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600;700&display=swap">
<style>
:root{{--bg:#f5f8f8;--ink:#13262b;--mut:#587077;--line:#d3dedf;--card:#fff;--app:#1d6f78;--platform:#4d5fb0;--ops:#b3641a;--bad:#b3261e;--warn:#9a6a00;box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#0f1b1e;--ink:#e6eff0;--mut:#93aab0;--line:#27393d;--card:#152327;--app:#4fb3bd;--platform:#8c9be0;--ops:#e0975a;--bad:#ff8a80;--warn:#e6b84a}}}}
:root[data-theme=dark]{{--bg:#0f1b1e;--ink:#e6eff0;--mut:#93aab0;--line:#27393d;--card:#152327;--app:#4fb3bd;--platform:#8c9be0;--ops:#e0975a;--bad:#ff8a80;--warn:#e6b84a}}
html{{scroll-padding-top:env(safe-area-inset-top,0px)}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 'Public Sans',system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:860px;margin:0 auto;padding:28px 18px 60px}}
h1{{font-size:clamp(26px,4.4vw,38px);line-height:1.15;margin:0 0 10px;letter-spacing:-.01em}}
h2{{font-size:20px;margin:42px 0 6px}} .lede{{font-size:18px;color:var(--mut);max-width:62ch;margin:0 0 22px}}
.m,small,cite,.ax{{color:var(--mut)}} p{{max-width:70ch}}
.kp{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;background:var(--line);border:1px solid var(--line);border-radius:6px;overflow:hidden;margin:18px 0}}
.kp div{{background:var(--card);padding:14px}} .kp b{{display:block;font-size:26px}} .kp span{{font-size:13px;color:var(--mut)}}
.scroll{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;font-size:14.5px}}
th{{text-align:left;font-weight:600;color:var(--mut);border-bottom:1px solid var(--line);padding:6px 8px 6px 0;font-size:13px}}
td{{padding:7px 8px 7px 0;border-bottom:1px solid var(--line);vertical-align:middle}} .num{{text-align:right;font-variant-numeric:tabular-nums}}
td small{{display:block;font-size:12px}} .nm{{min-width:190px}}
.bar{{min-width:150px;position:relative}} .b{{display:inline-block;height:12px;border-radius:2px;vertical-align:middle;margin-right:8px}}
.b.app{{background:var(--app)}} .b.platform{{background:var(--platform)}} .b.ops{{background:var(--ops)}}
.key span{{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 5px 0 14px}} .key{{font-size:13px;color:var(--mut)}}
.bad{{color:var(--bad);font-weight:600}} .warn{{color:var(--warn);font-weight:600}}
svg{{width:100%;height:auto;display:block}} .ln{{fill:none;stroke:var(--app);stroke-width:2.2}} circle{{fill:var(--app)}} .g{{stroke:var(--line)}} .ax{{font-size:11px;fill:var(--mut)}}
details{{border-bottom:1px solid var(--line);padding:9px 0}} summary{{cursor:pointer;font-weight:600}} summary:focus-visible{{outline:2px solid var(--app);outline-offset:3px}}
blockquote{{margin:10px 0 4px;padding-left:12px;border-left:3px solid var(--line)}} cite{{display:block;font-size:12.5px;font-style:normal;margin-top:2px}}
.act li{{margin:6px 0;max-width:72ch}}
</style></head><body><main>
<h1>Store rating is {META['score']:.2f}. The damage is a 1-star tail, and most of it is the app.</h1>
<p class="lede">{len(low):,} of {len(df):,} written reviews since {df.date.min():%b %Y} are 1-2 stars. {oc.get('no_ops',0)*100:.0f}% of those with a clear complaint mention nothing about cabs, drivers or support. Only {reply_rate*100:.0f}% received a developer reply.</p>
<div class="kp">
<div><b>{META['score']:.2f}</b><span>Store rating, {N:,} ratings</span></div>
<div><b>{df.rating.mean():.2f}</b><span>Written-review average (unhappy users write more)</span></div>
<div><b>{p0*100:.0f}%</b><span>Written reviews at 1-2 stars</span></div>
<div><b>{reply_rate*100:.1f}%</b><span>1-2 star reviews with a reply</span></div>
<div><b>{4.64 if False else META['score']+TO5:.2f}</b><span>Ceiling if every 1-2 star became 5</span></div>
</div>

<h2>Where the low ratings come from</h2>
<p class="m">Share of 1-2 star reviews. A review can carry more than one theme. About a third have no usable detail (generic sentiment or unrecognised) and are not shown. Uplift assumes half of affected users would move to 4 stars once the cause is fixed.</p>
<div class="key"><span style="background:var(--app)"></span>App / Product<span style="background:var(--platform)"></span>Platform<span style="background:var(--ops)"></span>Operations &amp; support</div>
<div class="scroll"><table><tr><th>Cause and owner</th><th>Share of 1-2 star</th><th class="num">Reviews</th><th class="num">Rating uplift</th></tr>{bars}</table></div>
<p>Fixing the largest cause alone is worth about +{top[4]:.2f} stars. No single fix moves the rating much, which is why the plan also adds more happy-user ratings.</p>

<h2>Average rating by month</h2>
<p class="m">Written reviews only, so it sits below the store rating. Watch the shape, not the level.</p>
{chart}

<h2>Release check</h2>
<p class="m">Share of 1-2 star reviews per app version (versions with 40+ reviews), compared with the {p0*100:.0f}% baseline. Regression means a clearly higher share; Watch means higher but with limited data.</p>
<div class="scroll"><table><tr><th>Version</th><th>First seen</th><th class="num">Reviews</th><th class="num">Avg</th><th class="num">1-2 star</th><th>Status</th></tr>{vr}</table></div>

<h2>What users say</h2>
<p class="m">The most-endorsed single-theme reviews for each cause.</p>{qs}

<h2>Limits</h2>
<ul class="act"><li>Themes are tagged by keyword rules and checked by hand on a sample; they will miss complaints in some languages (including Filipino-English mixes).</li>
<li>Reviews are a small, self-selected slice of {N:,} ratings. Theme shares are applied to all low ratings as an assumption.</li>
<li>Reviews cannot show root cause. Each cause here is a lead for engineering to confirm in logs.</li></ul>
<p class="m">Generated {datetime.now():%d %b %Y}. Rebuild with <code>build_dashboard.py</code>.</p>
</main></body></html>"""
open("dashboard.html", "w", encoding="utf-8").write(html_doc)
print("dashboard.html", len(html_doc) // 1024, "KB")