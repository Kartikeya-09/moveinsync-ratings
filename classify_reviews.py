"""
Tag MoveInSync reviews by complaint theme and owning team.

Rule-based on purpose: free, instant, deterministic, and every tag is explainable
(you can see which pattern fired). An LLM pass can be layered on top for the
'untagged' residue -- see README.

Usage:
    python classify_reviews.py                 # reads data/reviews.csv -> data/reviews_tagged.csv
    python classify_reviews.py --since 2024-10-01
"""
import argparse
import re

import pandas as pd

# theme -> (owner, regex). Multi-label: a review can hit several themes.
# Includes common Hinglish / romanised Indian-language spellings.
THEMES = {
    "login_otp_not_received": ("Platform (backend/auth)", r"(otp|verification code|codes?|\bpin)\b.{0,40}(not|n't|no|never|didn|don|doesn|nahi|nhi).{0,25}(receiv|get|got|come|coming|arriv|sent|work)|(not|n't|unable|can't|cannot|couldn't|nahi|nhi).{0,30}(login|log in|sign ?in|register|registration|verify|verif)|(login|log in|sign ?in|registration).{0,30}(issue|problem|fail|error|not working|stuck)|no (otp|code)|not (verifying|verified)|unable to login|can't login|(not|n't|never).{0,12}(getting|receiving|received|get|got).{0,20}(otp|code)|validate (my )?identity|verify (my )?identity|(otp|code).{0,30}(every (minute|time|day)|again and again|repeatedly)|password again|asking password"),
    "session_logout_loop": ("App (mobile)", r"(log(ged|s|ging)?|sign(ed|s|ing)?)[ -]?(me )?out|re-?login|login again|keeps? (asking|asks).{0,15}(login|otp)|asks? (for )?otp (every|each)|\bsso\b|session expired|(every|each) time (you |i |we )?open.{0,30}(login|otp)|login (via|with) otp|login credentials|(so|too|this) much otp|bank(ing)? (app|application)|otp.{0,20}bank"),
    "crash_slow_not_opening": ("App (mobile)", r"crash|hang|freez|frozen|stuck|lag+y?|slow|not (opening|open|loading|responding)|(doesn't|does not|won't|can't|cannot|unable to|not able to) (open|load|start)|loading|takes? (forever|too (much|long))|oops|something went wrong|technical (error|issue|glitch)|server error|app (is )?not working|not working properly|keeps? (stopping|closing)|bug|glitch|buggy|uninstall|blank screen|white screen|black screen|not installed|buffering|stops? working|(only|works?) (on|with) wifi|no internet connection|reinstall|re-install|install (this )?app again|keeps? (on )?updating|not (showing|displaying) (upcoming|trip|cab|car)"),
    "tracking_eta_wrong": ("Platform (location/ETA)", r"track|gps|live location|location|\beta\b|real[ -]?time|where is (my )?(cab|driver|vehicle)|map|vehicle (location|position)|driver location|not (updating|updated)|hours ago|stale"),
    "notification_rating_spam": ("App/Product (notifications)", r"notification|notify|spam|\bads?\b|advert|popup|pop-up|pop up|(rate|review|rating|star).{0,40}(every (time|day|ride|trip)|each (time|ride|trip)|after (every|each)|repeated|constant|pop ?up|prompt|nag|forc|compel|mandatory)|(every|each|after (every|each)).{0,30}(ride|trip).{0,30}(rate|review|rating)|star pop|survey|play ?store review|mandatory (review|rating|feedback)|(asks?|asking).{0,15}(a )?(review|rating)"),
    "forced_checks_permissions": ("Product (safety flows)", r"seat ?(belt|buckle)|buckle|selfie|face (scan|verif)|photo|camera|microphone|\bmic\b|permission|read(ing)? phone|phone state|allow access"),
    "booking_scheduling_fail": ("App + Platform (booking)", r"book|schedul|roster|slot|request.{0,30}(not|fail|accept|error|reject)|calendar|cancel|(select|choose|change).{0,20}(pick|drop|point|location|shift|time)|pick ?up point|drop point|unable to (select|add|set)"),
    "routing_pickup_time": ("Platform (routing engine)", r"rout(e|ing)|detour|sequence|clubb|pick ?up time|drop (time|sequence|management)|travel time|(too )?(early|earlier) pick|pickup varies|time varies|longer? (route|way)|zig ?zag|illogical|randomly assigned"),
    "cab_late_noshow": ("Operations / vendor", r"\blate\b|delay|waiting|wait(ed)? (for|more|long|an? hour)|(cab|driver|vehicle|taxi|shuttle|bus).{0,30}(not|never|didn|don|no).{0,15}(come|came|arriv|show|reach|turn|pick|available)|no (cab|vehicle|driver|show)|cab not|did(n't| not) (come|arrive|pick)|missed (my )?(cab|pick|shift)|no cab available|cab facility nahi"),
    "driver_conduct_safety": ("Operations / vendor", r"rude|rash|unsafe|not safe|safety|harass|drunk|misbehav|behaviou?r|abus|overspeed|over speed|speeding|dangerous|drive(r)? (is|was)|fear|escort"),
    "support_unresponsive": ("Ops / support desk", r"support|customer (care|service)|help ?desk|helpline|no (response|reply)|not (respond|reply|answer|pick)|ivr|escalat|complain|transport (team|desk|manager)|call(s|ed)? (not|never)|never (pick|answer|respond)|unresponsive|no one (respond|reply|answer)"),
    "noshow_policy_penalty": ("Product / client policy", r"no ?show.{0,40}(3|three|times|block|deactivat|suspend|disabled|penal|cab facility)|deactivat|blocked|suspend|penalt|(3|three) no ?show"),
    "feature_ui_gap": ("Product (UX)", r"\bui\b|\bux\b|user[ -]?(friendly|unfriendly)|interface|design|confus|(no|need|add|should|please add|missing|want).{0,25}(option|feature|button|link|history|view|see)|old trips?|trip history|co[ -]?passenger|not (able|possible) to see|can't see|cannot see|unable to see|zoom|where is the|feedback (option|link)|(no|not).{0,15}(option|provision).{0,25}(feedback|complain|raise)|raise (trip|a )?complaint|car number|vehicle number|who (all )?(are|is) (there )?in (the )?(cab|vehicle)|inaccurate (timing|time)|(don't|doesn't|not) show.{0,15}(exact )?(time|number)|previous app was better|transport policy|call option|driver (number|contact)|connect(ing)? driver|sos|contact (the )?(driver|chauffeur)|call (the )?driver|drivers? (don't|doesn't|not).{0,15}call|phone number.{0,30}(connect|disconnect|unavailable)"),
}

# Sentiment-only reviews with no actionable detail
GENERIC = r"^[\W\d_]*(worst|waste|useless|bad|poor|pathetic|horrible|terrible|trash|bakwas|bekar|kharab|nonsense|rubbish|3rd class|time ?waste|not good|very bad|too bad|disgusting|pathetic)\b.{0,40}$"


def tag(text: str):
    t = (text or "").lower().strip()
    hits = [name for name, (_, rx) in THEMES.items() if re.search(rx, t)]
    # tracking 'location' alone is weak: need it to co-occur with a problem word, else drop
    if "tracking_eta_wrong" in hits and not re.search(
        r"track|gps|eta|real[ -]?time|not (updat|show|accurate|correct|work)|wrong|incorrect|inaccurate|ago|stale|slow|issue|problem|error|fail|delay|never|unable|can't|cannot", t):
        hits.remove("tracking_eta_wrong")
    # crash theme: 'loading' / 'uninstall' alone are weak
    if "crash_slow_not_opening" in hits and re.fullmatch(r".*", t) and len(hits) > 1:
        strong = re.search(r"crash|hang|freez|frozen|slow|not (opening|open|loading|responding)|(doesn't|does not|won't|can't|cannot|unable to|not able to) (open|load|start)|takes? (forever|too (much|long))|oops|something went wrong|technical|server error|not working|keeps? (stopping|closing)|bug|glitch|lag", t)
        if not strong:
            hits.remove("crash_slow_not_opening")
    if not hits:
        if re.search(GENERIC, t) or len(t) < 25:
            return ["generic_no_detail"]
        return ["untagged_other"]
    return hits


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--since", default="2024-10-01")
    p.add_argument("--inp", default="data/reviews.csv")
    p.add_argument("--out", default="data/reviews_tagged.csv")
    a = p.parse_args()

    df = pd.read_csv(a.inp, parse_dates=["date"])
    df = df[df["date"] >= a.since].copy()
    df["text"] = df["text"].fillna("")
    df["themes"] = df["text"].apply(tag)
    owner = {k: v[0] for k, v in THEMES.items()}
    owner.update({"generic_no_detail": "Unknown", "untagged_other": "Unknown"})
    df["owners"] = df["themes"].apply(lambda ts: sorted({owner[t] for t in ts}))
    df["themes_str"] = df["themes"].apply(lambda ts: "|".join(ts))
    df["owners_str"] = df["owners"].apply(lambda os_: "|".join(os_))
    df.drop(columns=["themes", "owners"]).to_csv(a.out, index=False)
    print(f"Tagged {len(df)} reviews since {a.since} -> {a.out}")


if __name__ == "__main__":
    main()