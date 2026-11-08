#!/usr/bin/env python3
"""
campaign-builder: turn a campaign plan (YAML) into launch-ready upload files.

    python build.py plans/2026-12_rebuild.yaml --out output/

Steps: load plan -> validate guardrails -> forecast -> emit
  output/google_ads_editor.csv   (import in Google Ads Editor: Account > Import > From file)
  output/meta_bulk_import.csv    (import in Meta Ads Manager: Create & Edit in bulk > Import)
  output/launch_summary.md       (human-readable plan, forecast, manual steps)

Validation failures stop the build (exit 1). Warnings never launch anything live:
unresolved placeholders, unverified geo gates and missing creative are forced to PAUSED.
"""
import argparse, calendar, csv, re, sys
from pathlib import Path
import yaml

PLATFORM_TAG = {"meta": "META", "google": "GOOG"}


# ---------------------------------------------------------------- helpers
def load_plan(path):
    with open(path) as f:
        return yaml.safe_load(f)


def days_in_month(launch_month):
    y, m = map(int, launch_month.split("-"))
    return calendar.monthrange(y, m)[1]


def budget_days(plan):
    """Days used to turn monthly budgets into daily ones. `account.budget_days` (e.g. 30) wins
    over the calendar month so daily budgets match the approved $/day table exactly."""
    a = plan["account"]
    return a.get("budget_days") or days_in_month(a["launch_month"])


def yyyymm(launch_month):
    return launch_month.replace("-", "")


def sub(text, variables):
    """Fill {{var}} placeholders from plan.variables; unknown ones stay as-is."""
    if not isinstance(text, str):
        return text
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(variables.get(m.group(1), m.group(0))), text)


def has_placeholder(text):
    return isinstance(text, str) and re.search(r"\{\{\w+\}\}", text) is not None


def full_name(plan, platform, name):
    return f"{PLATFORM_TAG[platform]}_{name}_{yyyymm(plan['account']['launch_month'])}"


def utm_url(plan, platform, campaign_name, ad_name=None):
    base = plan["account"]["landing_url"]
    src = plan["account"]["utm_source"][platform]
    if platform == "meta":
        # Meta fills these macros per ad at serve time
        tags = f"utm_source={src}&utm_medium=paid_social&utm_campaign={{{{campaign.name}}}}&utm_content={{{{ad.name}}}}"
    else:
        tags = f"utm_source={src}&utm_medium=cpc&utm_campaign={campaign_name}&utm_term={{keyword}}"
    return base, tags


# ---------------------------------------------------------------- validation
def all_campaigns(plan):
    for platform in ("meta", "google"):
        for c in plan.get(platform, {}).get("campaigns", []):
            yield platform, c


def validate(plan):
    errors, warnings = [], []
    acct = plan["account"]
    cap = acct["monthly_cap"]

    # 1. Budget caps
    totals = {}
    for platform in ("meta", "google"):
        camp = sum(c["monthly_budget"] for c in plan[platform]["campaigns"])
        reserve = plan[platform].get("flex_reserve", {}).get("monthly_budget", 0)
        totals[platform] = camp + reserve
        if totals[platform] > acct["platform_split"][platform]:
            errors.append(f"{platform}: planned ${totals[platform]:,} exceeds platform split ${acct['platform_split'][platform]:,}")
        elif totals[platform] < acct["platform_split"][platform]:
            warnings.append(f"{platform}: ${acct['platform_split'][platform] - totals[platform]:,} of the split is unallocated")
    if sum(totals.values()) > cap:
        errors.append(f"Total ${sum(totals.values()):,} exceeds monthly cap ${cap:,}")
    elif sum(totals.values()) < cap:
        warnings.append(f"Total ${sum(totals.values()):,} leaves ${cap - sum(totals.values()):,} of the ${cap:,} cap unallocated")

    for platform, c in all_campaigns(plan):
        tag = f"{platform}/{c['name']}"
        # 2. No shared budgets: every campaign owns its budget
        if "shared_budget" in c:
            errors.append(f"{tag}: shared budgets are not allowed (one campaign starved the others last time)")
        if c["monthly_budget"] < 0 or (c["monthly_budget"] == 0 and not c.get("gate")):
            errors.append(f"{tag}: monthly_budget must be > 0 (only a gated campaign may sit at $0)")
        # 3. ABO ad-set budgets must add up; test lanes get exactly one concept per ad set
        if c.get("budget_mode") == "ABO" and len(c.get("adsets", [])) > 1:
            s = sum(a.get("monthly_budget", 0) for a in c["adsets"])
            if s != c["monthly_budget"]:
                errors.append(f"{tag}: ad set budgets sum to ${s:,}, campaign is ${c['monthly_budget']:,}")
            if "Test" in c["name"]:
                for a in c["adsets"]:
                    if len(a["ads"]) != 1:
                        errors.append(f"{tag}/{a['name']}: a test ad set must hold exactly 1 concept (found {len(a['ads'])})")
        # 4. Google RSA limits
        for ag in c.get("ad_groups", []):
            rsa = ag.get("rsa", {})
            hs = [sub(h, plan.get("variables", {})) for h in rsa.get("headlines", [])]
            ds = [sub(d, plan.get("variables", {})) for d in rsa.get("descriptions", [])]
            if len(hs) < 3 or len(ds) < 2:
                errors.append(f"{tag}/{ag['name']}: RSA needs >=3 headlines and >=2 descriptions")
            for h in hs:
                if len(h) > 30 and not has_placeholder(h):
                    errors.append(f"{tag}/{ag['name']}: headline over 30 chars: '{h}'")
            for d in ds:
                if len(d) > 90 and not has_placeholder(d):
                    errors.append(f"{tag}/{ag['name']}: description over 90 chars: '{d}'")
        # 5. Gates / placeholders -> forced PAUSED (warning, not error)
        gate = c.get("gate")
        if gate and not gate.get("tracking_verified"):
            warnings.append(f"{tag}: gate not verified -> built PAUSED. Checks: " + "; ".join(gate["checks"]))
        for ag in c.get("ad_groups", []):
            blob = " ".join([k[0] for k in ag["keywords"]] + ag["rsa"]["headlines"] + ag["rsa"]["descriptions"])
            if has_placeholder(sub(blob, plan.get("variables", {}))):
                warnings.append(f"{tag}/{ag['name']}: unresolved {{{{placeholders}}}} -> built PAUSED")
        for a in c.get("adsets", []):
            for ad in a["ads"]:
                if ad["creative_status"] == "new_needed":
                    warnings.append(f"{tag}/{ad['name']}: creative not supplied -> built PAUSED")

    # 6. Forecast must land inside the CPA target
    f = forecast(plan)
    if not (acct["cpa_target"]["low"] <= f["base"]["cpa"] <= acct["cpa_target"]["high"]):
        errors.append(f"Forecast blended CPA ${f['base']['cpa']:.0f} is outside ${acct['cpa_target']['low']}-${acct['cpa_target']['high']}")
    if f["stress_brand"]["cpa"] > acct["cpa_target"]["high"]:
        warnings.append(f"Brand-haircut scenario CPA ${f['stress_brand']['cpa']:.0f} breaks the ${acct['cpa_target']['high']} ceiling")
    return errors, warnings


# ---------------------------------------------------------------- forecast
def forecast(plan):
    """Trials = budget / assumed CPA. Scenarios: base, brand-haircut, all CPAs +10%."""
    rows = []
    for platform in ("meta", "google"):
        for c in plan[platform]["campaigns"]:
            live = not (c.get("gate") and not c["gate"].get("tracking_verified"))
            rows.append((platform, c["name"], c["monthly_budget"], c["assumed_cpa"], c.get("incrementality_haircut", 1.0), live))
        r = plan[platform].get("flex_reserve")
        if r:
            rows.append((platform, "Flex reserve", r["monthly_budget"], r["assumed_cpa"], 1.0, True))

    def run(cpa_mult=1.0, haircut=False):
        spend = trials = 0.0
        for _, _, b, cpa, hc, _ in rows:
            spend += b
            trials += (b / (cpa * cpa_mult)) * (hc if haircut else 1.0)
        return {"spend": spend, "trials": trials, "cpa": spend / trials}

    return {
        "rows": rows,
        "base": run(),
        "stress_brand": run(haircut=True),
        "stress_cpa10": run(cpa_mult=1.10),
    }


# ---------------------------------------------------------------- emitters
GOOGLE_COLS = ["Campaign", "Campaign Type", "Campaign Status", "Campaign Daily Budget", "Budget type",
               "Bid Strategy Type", "Target CPA", "Target Impression Share", "Max CPC Limit", "Networks",
               "Location", "Ad Group", "Ad Group Status", "Keyword", "Criterion Type", "Ad Type", "Final URL",
               "Tracking Template"] + [f"Headline {i}" for i in range(1, 7)] + [f"Description {i}" for i in range(1, 3)]


def google_rows(plan):
    v = plan.get("variables", {})
    dim = budget_days(plan)
    rows = []
    for c in plan["google"]["campaigns"]:
        name = full_name(plan, "google", c["name"])
        gate = c.get("gate")
        status = "Paused" if (c["monthly_budget"] == 0 or (gate and not gate.get("tracking_verified"))) else ("Enabled" if c["status"] == "ENABLED" else "Paused")
        bs = c["bid_strategy"]
        base_url, tags = utm_url(plan, "google", name)
        row = dict.fromkeys(GOOGLE_COLS, "")
        row.update({
            "Campaign": name,
            "Campaign Type": "Performance Max" if c["type"] == "PERFORMANCE_MAX" else "Search",
            "Campaign Status": status,
            "Campaign Daily Budget": f"{c['monthly_budget'] / dim:.2f}" if c["monthly_budget"] else "",
            "Budget type": "Standard",          # never "Shared"
            "Bid Strategy Type": bs["type"],
            "Target CPA": bs.get("target_cpa", ""),
            "Target Impression Share": bs.get("percent", ""),
            "Max CPC Limit": bs.get("max_cpc", ""),
            "Networks": "Google search" if c["type"] == "SEARCH" else "",   # search partners + display off
            "Tracking Template": "{lpurl}?" + tags,
        })
        rows.append(row)
        for loc in c["locations"]:
            r = dict.fromkeys(GOOGLE_COLS, ""); r.update({"Campaign": name, "Location": loc}); rows.append(r)
        for neg in c.get("negatives", []):
            r = dict.fromkeys(GOOGLE_COLS, ""); r.update({"Campaign": name, "Keyword": neg, "Criterion Type": "Negative Phrase"}); rows.append(r)
        for ag in c.get("ad_groups", []):
            blob = " ".join([k[0] for k in ag["keywords"]] + ag["rsa"]["headlines"] + ag["rsa"]["descriptions"])
            ag_status = "Paused" if (status == "Paused" or ag.get("status") == "PAUSED" or has_placeholder(sub(blob, v))) else "Enabled"
            r = dict.fromkeys(GOOGLE_COLS, ""); r.update({"Campaign": name, "Ad Group": ag["name"], "Ad Group Status": ag_status}); rows.append(r)
            for kw, mt in ag["keywords"]:
                r = dict.fromkeys(GOOGLE_COLS, "")
                r.update({"Campaign": name, "Ad Group": ag["name"], "Keyword": sub(kw, v), "Criterion Type": mt.capitalize()})
                rows.append(r)
            r = dict.fromkeys(GOOGLE_COLS, "")
            r.update({"Campaign": name, "Ad Group": ag["name"], "Ad Type": "Responsive search ad", "Final URL": base_url})
            for i, h in enumerate(ag["rsa"]["headlines"][:6], 1): r[f"Headline {i}"] = sub(h, v)
            for i, d in enumerate(ag["rsa"]["descriptions"][:2], 1): r[f"Description {i}"] = sub(d, v)
            rows.append(r)
    return rows


META_COLS = ["Campaign Name", "Campaign Status", "Campaign Objective", "Buying Type", "Campaign Daily Budget",
             "Ad Set Name", "Ad Set Status", "Ad Set Daily Budget", "Optimization Goal", "Conversion Event",
             "Billing Event", "Bid Strategy", "Countries", "Age Min", "Age Max", "Advantage+ Audience",
             "Custom Audience Note", "Frequency Cap Note", "Ad Name", "Ad Status", "Primary Text", "Headline",
             "Call To Action", "Link", "URL Tags", "Pixel ID"]


def meta_rows(plan):
    dim = budget_days(plan)
    m = plan["meta"]
    rows = []
    for c in m["campaigns"]:
        cname = full_name(plan, "meta", c["name"])
        for a in c["adsets"]:
            ad_budget = a.get("monthly_budget", c["monthly_budget"] if len(c["adsets"]) == 1 else 0)
            for ad in a["ads"]:
                base_url, tags = utm_url(plan, "meta", cname, ad["name"])
                paused = ad["creative_status"] == "new_needed"
                r = dict.fromkeys(META_COLS, "")
                r.update({
                    "Campaign Name": cname,
                    "Campaign Status": "ACTIVE",
                    "Campaign Objective": c["objective"],
                    "Buying Type": "AUCTION",
                    "Campaign Daily Budget": f"{c['monthly_budget'] / dim:.2f}" if c["budget_mode"] == "CBO" else "",
                    "Ad Set Name": a["name"],
                    "Ad Set Status": "ACTIVE",
                    "Ad Set Daily Budget": f"{ad_budget / dim:.2f}" if c["budget_mode"] == "ABO" else "",
                    "Optimization Goal": "OFFSITE_CONVERSIONS",
                    "Conversion Event": m["optimization_event"],
                    "Billing Event": "IMPRESSIONS",
                    "Bid Strategy": "LOWEST_COST_WITHOUT_CAP",
                    "Countries": ",".join(a["countries"]),
                    "Age Min": a["age"][0], "Age Max": a["age"][1],
                    "Advantage+ Audience": "Yes" if a["audience"] == "advantage_plus" else "No",
                    "Custom Audience Note": a["audience"] if a["audience"].startswith("custom") else "",
                    "Frequency Cap Note": a.get("frequency_cap", ""),
                    "Ad Name": ad["name"],
                    "Ad Status": "PAUSED" if paused else "ACTIVE",
                    "Primary Text": ad["primary"], "Headline": ad["headline"], "Call To Action": ad["cta"],
                    "Link": base_url, "URL Tags": tags, "Pixel ID": m["pixel_id"],
                })
                rows.append(r)
    return rows


def write_csv(path, cols, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)


def write_summary(path, plan, errors, warnings, f):
    acct = plan["account"]; dim = budget_days(plan)
    L = [f"# Launch summary: {acct['name']} ({acct['launch_month']})", "",
         f"Cap ${acct['monthly_cap']:,} | Meta ${acct['platform_split']['meta']:,} | Google ${acct['platform_split']['google']:,} | "
         f"CPA target ${acct['cpa_target']['low']}-${acct['cpa_target']['high']}", "",
         "## Budget and forecast", "", "| Platform | Campaign | Monthly $ | Daily $ | Assumed CPA | Trials |", "|---|---|---:|---:|---:|---:|"]
    for platform, name, b, cpa, hc, live in f["rows"]:
        daily = "reserve" if name == "Flex reserve" else f"{b / dim:,.0f}"
        note = "" if live else " (gated, paused)"
        L.append(f"| {platform} | {name}{note} | {b:,} | {daily} | {cpa} | {b / cpa:.0f} |")
    L += ["", f"**Base case:** ${f['base']['spend']:,.0f} -> {f['base']['trials']:.0f} trials -> **${f['base']['cpa']:.0f} blended CPA**",
          f"**Brand 50% non-incremental:** {f['stress_brand']['trials']:.0f} trials -> ${f['stress_brand']['cpa']:.0f} CPA",
          f"**Every CPA +10%:** {f['stress_cpa10']['trials']:.0f} trials -> ${f['stress_cpa10']['cpa']:.0f} CPA", "",
          "## Validation", ""]
    L += [f"- ERROR: {e}" for e in errors] or ["- No errors."]
    L += [f"- WARN: {w}" for w in warnings]
    L += ["", "## Manual steps (cannot be bulk-uploaded)", "",
          "1. Fix and verify Meta Pixel + Conversions API on the signup flow *before* enabling anything (dedupe on event_id).",
          "2. Build PMax asset groups, brand exclusions and audience signals in the Google Ads UI.",
          "3. Create the shared-budget-free setup: confirm every Google campaign shows its own Standard budget after import.",
          "4. Replace `landing_url`, `pixel_id` and `variables` in the plan; supply creative for ads marked PAUSED.",
          "5. In Editor and Ads Manager use *Check changes / preview* before posting. Nothing here pushes live."]
    Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- main
def main(argv=None):
    p = argparse.ArgumentParser(description="Build ready-to-upload campaign files from a plan.")
    p.add_argument("plan"); p.add_argument("--out", default="output")
    a = p.parse_args(argv)
    plan = load_plan(a.plan)
    errors, warnings = validate(plan)
    f = forecast(plan)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    write_summary(out / "launch_summary.md", plan, errors, warnings, f)
    for w in warnings: print("WARN ", w)
    if errors:
        for e in errors: print("ERROR", e)
        print(f"\nBuild blocked: {len(errors)} error(s). See {out/'launch_summary.md'}")
        return 1
    write_csv(out / "google_ads_editor.csv", GOOGLE_COLS, google_rows(plan))
    write_csv(out / "meta_bulk_import.csv", META_COLS, meta_rows(plan))
    print(f"\nOK: forecast ${f['base']['cpa']:.0f} blended CPA on {f['base']['trials']:.0f} trials. Files in {out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
