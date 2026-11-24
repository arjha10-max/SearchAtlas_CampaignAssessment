/* campaign-builder core: a browser port of build.py.
 * Same validation, forecast and output rules as the Python script, so the
 * files this produces match output/ exactly. Requires js-yaml (window.jsyaml). */
(function (root) {
  "use strict";

  const PLATFORM_TAG = { meta: "META", google: "GOOG" };
  const GOOGLE_COLS = ["Campaign", "Campaign Type", "Campaign Status", "Campaign Daily Budget", "Budget type",
    "Bid Strategy Type", "Target CPA", "Target Impression Share", "Max CPC Limit", "Networks",
    "Location", "Ad Group", "Ad Group Status", "Keyword", "Criterion Type", "Ad Type", "Final URL",
    "Tracking Template"].concat([1, 2, 3, 4, 5, 6].map(i => "Headline " + i), [1, 2].map(i => "Description " + i));
  const META_COLS = ["Campaign Name", "Campaign Status", "Campaign Objective", "Buying Type", "Campaign Daily Budget",
    "Ad Set Name", "Ad Set Status", "Ad Set Daily Budget", "Optimization Goal", "Conversion Event",
    "Billing Event", "Bid Strategy", "Countries", "Age Min", "Age Max", "Advantage+ Audience",
    "Custom Audience Note", "Frequency Cap Note", "Ad Name", "Ad Status", "Primary Text", "Headline",
    "Call To Action", "Link", "URL Tags", "Pixel ID"];

  // ---------- helpers
  const num = n => Number(n).toLocaleString("en-US");          // Python {:,}
  const fixed = (n, d) => Number(n).toFixed(d);                  // Python {:.Nf}

  function daysInMonth(launchMonth) {
    const [y, m] = launchMonth.split("-").map(Number);
    return new Date(y, m, 0).getDate();
  }
  function budgetDays(plan) {
    const a = plan.account;
    return a.budget_days || daysInMonth(a.launch_month);
  }
  function yyyymm(launchMonth) { return launchMonth.replace(/-/g, ""); }
  function sub(text, variables) {
    if (typeof text !== "string") return text;
    return text.replace(/\{\{(\w+)\}\}/g, (m, k) => (k in variables ? String(variables[k]) : m));
  }
  function hasPlaceholder(text) { return typeof text === "string" && /\{\{\w+\}\}/.test(text); }
  function fullName(plan, platform, name) {
    return `${PLATFORM_TAG[platform]}_${name}_${yyyymm(plan.account.launch_month)}`;
  }
  function utmUrl(plan, platform, campaignName) {
    const base = plan.account.landing_url;
    const src = plan.account.utm_source[platform];
    const tags = platform === "meta"
      ? `utm_source=${src}&utm_medium=paid_social&utm_campaign={{campaign.name}}&utm_content={{ad.name}}`
      : `utm_source=${src}&utm_medium=cpc&utm_campaign=${campaignName}&utm_term={keyword}`;
    return [base, tags];
  }
  function allCampaigns(plan) {
    const out = [];
    for (const platform of ["meta", "google"]) {
      for (const c of (plan[platform] && plan[platform].campaigns) || []) out.push([platform, c]);
    }
    return out;
  }
  const sum = arr => arr.reduce((s, x) => s + x, 0);

  // ---------- validation
  function validate(plan) {
    const errors = [], warnings = [];
    const acct = plan.account, cap = acct.monthly_cap, vars = plan.variables || {};
    const totals = {};
    for (const platform of ["meta", "google"]) {
      const camp = sum(plan[platform].campaigns.map(c => c.monthly_budget));
      const reserve = (plan[platform].flex_reserve || {}).monthly_budget || 0;
      totals[platform] = camp + reserve;
      const split = acct.platform_split[platform];
      if (totals[platform] > split) errors.push(`${platform}: planned $${num(totals[platform])} exceeds platform split $${num(split)}`);
      else if (totals[platform] < split) warnings.push(`${platform}: $${num(split - totals[platform])} of the split is unallocated`);
    }
    const grand = totals.meta + totals.google;
    if (grand > cap) errors.push(`Total $${num(grand)} exceeds monthly cap $${num(cap)}`);
    else if (grand < cap) warnings.push(`Total $${num(grand)} leaves $${num(cap - grand)} of the $${num(cap)} cap unallocated`);

    for (const [platform, c] of allCampaigns(plan)) {
      const tag = `${platform}/${c.name}`;
      if ("shared_budget" in c) errors.push(`${tag}: shared budgets are not allowed (one campaign starved the others last time)`);
      if (c.monthly_budget < 0 || (c.monthly_budget === 0 && !c.gate)) errors.push(`${tag}: monthly_budget must be > 0 (only a gated campaign may sit at $0)`);
      if (c.budget_mode === "ABO" && (c.adsets || []).length > 1) {
        const s = sum(c.adsets.map(a => a.monthly_budget || 0));
        if (s !== c.monthly_budget) errors.push(`${tag}: ad set budgets sum to $${num(s)}, campaign is $${num(c.monthly_budget)}`);
        if (c.name.includes("Test")) {
          for (const a of c.adsets) {
            if (a.ads.length !== 1) errors.push(`${tag}/${a.name}: a test ad set must hold exactly 1 concept (found ${a.ads.length})`);
          }
        }
      }
      for (const ag of c.ad_groups || []) {
        const rsa = ag.rsa || {};
        const hs = (rsa.headlines || []).map(h => sub(h, vars));
        const ds = (rsa.descriptions || []).map(d => sub(d, vars));
        if (hs.length < 3 || ds.length < 2) errors.push(`${tag}/${ag.name}: RSA needs >=3 headlines and >=2 descriptions`);
        for (const h of hs) if (h.length > 30 && !hasPlaceholder(h)) errors.push(`${tag}/${ag.name}: headline over 30 chars: '${h}'`);
        for (const d of ds) if (d.length > 90 && !hasPlaceholder(d)) errors.push(`${tag}/${ag.name}: description over 90 chars: '${d}'`);
      }
      const gate = c.gate;
      if (gate && !gate.tracking_verified) warnings.push(`${tag}: gate not verified -> built PAUSED. Checks: ` + gate.checks.join("; "));
      for (const ag of c.ad_groups || []) {
        const blob = [...ag.keywords.map(k => k[0]), ...ag.rsa.headlines, ...ag.rsa.descriptions].join(" ");
        if (hasPlaceholder(sub(blob, vars))) warnings.push(`${tag}/${ag.name}: unresolved {{placeholders}} -> built PAUSED`);
      }
      for (const a of c.adsets || []) {
        for (const ad of a.ads) {
          if (ad.creative_status === "new_needed") warnings.push(`${tag}/${ad.name}: creative not supplied -> built PAUSED`);
        }
      }
    }

    const f = forecast(plan);
    if (!(f.base.cpa >= acct.cpa_target.low && f.base.cpa <= acct.cpa_target.high)) {
      errors.push(`Forecast blended CPA $${Math.round(f.base.cpa)} is outside $${acct.cpa_target.low}-$${acct.cpa_target.high}`);
    }
    if (f.stress_brand.cpa > acct.cpa_target.high) {
      warnings.push(`Brand-haircut scenario CPA $${Math.round(f.stress_brand.cpa)} breaks the $${acct.cpa_target.high} ceiling`);
    }
    return { errors, warnings };
  }

  // ---------- forecast
  function forecast(plan) {
    const rows = [];
    for (const platform of ["meta", "google"]) {
      for (const c of plan[platform].campaigns) {
        const live = !(c.gate && !c.gate.tracking_verified);
        rows.push([platform, c.name, c.monthly_budget, c.assumed_cpa, c.incrementality_haircut === undefined ? 1.0 : c.incrementality_haircut, live]);
      }
      const r = plan[platform].flex_reserve;
      if (r) rows.push([platform, "Flex reserve", r.monthly_budget, r.assumed_cpa, 1.0, true]);
    }
    const run = (cpaMult = 1.0, haircut = false) => {
      let spend = 0, trials = 0;
      for (const [, , b, cpa, hc] of rows) {
        spend += b;
        trials += (b / (cpa * cpaMult)) * (haircut ? hc : 1.0);
      }
      return { spend, trials, cpa: spend / trials };
    };
    const out = { rows, base: run(), stress_brand: run(1.0, true), stress_cpa10: run(1.10), pre_break: null };
    const bc = plan.account.baseline_cpa;
    if (bc) {
      const spend = sum(rows.map(r => r[2]));
      const trials = sum(rows.map(r => r[2] / bc[r[0]]));
      out.pre_break = { spend, trials, cpa: spend / trials };
      out.pre_break_x110 = { spend, trials: trials / 1.10, cpa: spend / (trials / 1.10) };
    }
    return out;
  }

  // ---------- emitters
  const blank = cols => Object.fromEntries(cols.map(c => [c, ""]));

  function googleRows(plan) {
    const v = plan.variables || {};
    const dim = budgetDays(plan);
    const rows = [];
    for (const c of plan.google.campaigns) {
      const name = fullName(plan, "google", c.name);
      const gate = c.gate;
      const status = (c.monthly_budget === 0 || (gate && !gate.tracking_verified)) ? "Paused"
        : (c.status === "ENABLED" ? "Enabled" : "Paused");
      const bs = c.bid_strategy;
      const [baseUrl, tags] = utmUrl(plan, "google", name);
      const row = blank(GOOGLE_COLS);
      Object.assign(row, {
        "Campaign": name,
        "Campaign Type": c.type === "PERFORMANCE_MAX" ? "Performance Max" : "Search",
        "Campaign Status": status,
        "Campaign Daily Budget": c.monthly_budget ? fixed(c.monthly_budget / dim, 2) : "",
        "Budget type": "Standard",
        "Bid Strategy Type": bs.type,
        "Target CPA": bs.target_cpa !== undefined ? String(bs.target_cpa) : "",
        "Target Impression Share": bs.percent !== undefined ? String(bs.percent) : "",
        "Max CPC Limit": bs.max_cpc !== undefined ? (Number.isInteger(bs.max_cpc) ? fixed(bs.max_cpc, 1) : String(bs.max_cpc)) : "",
        "Networks": c.type === "SEARCH" ? "Google search" : "",
        "Tracking Template": "{lpurl}?" + tags,
      });
      rows.push(row);
      for (const loc of c.locations) rows.push(Object.assign(blank(GOOGLE_COLS), { "Campaign": name, "Location": loc }));
      for (const neg of c.negatives || []) {
        rows.push(Object.assign(blank(GOOGLE_COLS), { "Campaign": name, "Keyword": neg, "Criterion Type": "Negative Phrase" }));
      }
      for (const ag of c.ad_groups || []) {
        const blob = [...ag.keywords.map(k => k[0]), ...ag.rsa.headlines, ...ag.rsa.descriptions].join(" ");
        const agStatus = (status === "Paused" || ag.status === "PAUSED" || hasPlaceholder(sub(blob, v))) ? "Paused" : "Enabled";
        rows.push(Object.assign(blank(GOOGLE_COLS), { "Campaign": name, "Ad Group": ag.name, "Ad Group Status": agStatus }));
        for (const [kw, mt] of ag.keywords) {
          rows.push(Object.assign(blank(GOOGLE_COLS), {
            "Campaign": name, "Ad Group": ag.name, "Keyword": sub(kw, v),
            "Criterion Type": mt.charAt(0).toUpperCase() + mt.slice(1),
          }));
        }
        const r = Object.assign(blank(GOOGLE_COLS), {
          "Campaign": name, "Ad Group": ag.name, "Ad Type": "Responsive search ad", "Final URL": baseUrl,
        });
        ag.rsa.headlines.slice(0, 6).forEach((h, i) => { r["Headline " + (i + 1)] = sub(h, v); });
        ag.rsa.descriptions.slice(0, 2).forEach((d, i) => { r["Description " + (i + 1)] = sub(d, v); });
        rows.push(r);
      }
    }
    return rows;
  }

  function metaRows(plan) {
    const dim = budgetDays(plan);
    const m = plan.meta;
    const rows = [];
    for (const c of m.campaigns) {
      const cname = fullName(plan, "meta", c.name);
      for (const a of c.adsets) {
        const adBudget = a.monthly_budget !== undefined ? a.monthly_budget : (c.adsets.length === 1 ? c.monthly_budget : 0);
        for (const ad of a.ads) {
          const [baseUrl, tags] = utmUrl(plan, "meta", cname);
          const paused = ad.creative_status === "new_needed";
          rows.push(Object.assign(blank(META_COLS), {
            "Campaign Name": cname,
            "Campaign Status": "ACTIVE",
            "Campaign Objective": c.objective,
            "Buying Type": "AUCTION",
            "Campaign Daily Budget": c.budget_mode === "CBO" ? fixed(c.monthly_budget / dim, 2) : "",
            "Ad Set Name": a.name,
            "Ad Set Status": "ACTIVE",
            "Ad Set Daily Budget": c.budget_mode === "ABO" ? fixed(adBudget / dim, 2) : "",
            "Optimization Goal": "OFFSITE_CONVERSIONS",
            "Conversion Event": m.optimization_event,
            "Billing Event": "IMPRESSIONS",
            "Bid Strategy": "LOWEST_COST_WITHOUT_CAP",
            "Countries": a.countries.join(","),
            "Age Min": a.age[0], "Age Max": a.age[1],
            "Advantage+ Audience": a.audience === "advantage_plus" ? "Yes" : "No",
            "Custom Audience Note": a.audience.startsWith("custom") ? a.audience : "",
            "Frequency Cap Note": a.frequency_cap || "",
            "Ad Name": ad.name,
            "Ad Status": paused ? "PAUSED" : "ACTIVE",
            "Primary Text": ad.primary, "Headline": ad.headline, "Call To Action": ad.cta,
            "Link": baseUrl, "URL Tags": tags, "Pixel ID": m.pixel_id,
          }));
        }
      }
    }
    return rows;
  }

  // Python csv module: CRLF line endings, quote only fields with comma, quote or newline.
  function toCsv(cols, rows) {
    const esc = v => {
      const s = v === undefined || v === null ? "" : String(v);
      return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    const lines = [cols.map(esc).join(",")].concat(rows.map(r => cols.map(c => esc(r[c])).join(",")));
    return lines.join("\r\n") + "\r\n";
  }

  function summaryMarkdown(plan, errors, warnings, f) {
    const acct = plan.account, dim = budgetDays(plan);
    const L = [`# Launch summary: ${acct.name} (${acct.launch_month})`, "",
      `Cap $${num(acct.monthly_cap)} | Meta $${num(acct.platform_split.meta)} | Google $${num(acct.platform_split.google)} | ` +
      `CPA target $${acct.cpa_target.low}-$${acct.cpa_target.high}`, "",
      "## Budget and forecast", "", "| Platform | Campaign | Monthly $ | Daily $ | Assumed CPA | Trials |", "|---|---|---:|---:|---:|---:|"];
    for (const [platform, name, b, cpa, , live] of f.rows) {
      const daily = name === "Flex reserve" ? "reserve" : num(Math.round(b / dim));
      const note = live ? "" : " (gated, paused)";
      L.push(`| ${platform} | ${name}${note} | ${num(b)} | ${daily} | ${cpa} | ${Math.round(b / cpa)} |`);
    }
    L.push("", `**Base case:** $${num(Math.round(f.base.spend))} -> ${Math.round(f.base.trials)} trials -> **$${Math.round(f.base.cpa)} blended CPA**`,
      `**Brand 50% non-incremental:** ${Math.round(f.stress_brand.trials)} trials -> $${Math.round(f.stress_brand.cpa)} CPA`,
      `**Every CPA +10%:** ${Math.round(f.stress_cpa10.trials)} trials -> $${Math.round(f.stress_cpa10.cpa)} CPA`);
    if (f.pre_break) {
      L.push("", `**Best case (pre-break CPAs, Meta $${acct.baseline_cpa.meta} / Google $${acct.baseline_cpa.google}):** ` +
        `${Math.round(f.pre_break.trials)} trials -> $${Math.round(f.pre_break.cpa)} CPA; ` +
        `if those are 10% worse: $${Math.round(f.pre_break_x110.cpa)} CPA`);
    }
    L.push("", "## Validation", "");
    if (errors.length) L.push(...errors.map(e => `- ERROR: ${e}`));
    else L.push("- No errors.");
    L.push(...warnings.map(w => `- WARN: ${w}`));
    L.push("", "## Manual steps (cannot be bulk-uploaded)", "",
      "1. Fix and verify Meta Pixel + Conversions API on the signup flow *before* enabling anything (dedupe on event_id).",
      "2. Build PMax asset groups, brand exclusions and audience signals in the Google Ads UI.",
      "3. Create the shared-budget-free setup: confirm every Google campaign shows its own Standard budget after import.",
      "4. Replace `landing_url`, `pixel_id` and `variables` in the plan; supply creative for ads marked PAUSED.",
      "5. In Editor and Ads Manager use *Check changes / preview* before posting. Nothing here pushes live.");
    return L.join("\n") + "\n";
  }

  // ---------- main entry: returns every step so the UI can show them
  function runBuild(yamlText) {
    const steps = [];
    let plan;
    try {
      plan = jsyaml.load(yamlText);
      if (!plan || !plan.account || !plan.meta || !plan.google) throw new Error("Plan must have account, meta and google sections");
    } catch (e) {
      return { ok: false, steps: [{ name: "Load plan", status: "error", detail: e.message }] };
    }
    steps.push({ name: "Load plan", status: "ok", detail: `${plan.account.name} · ${plan.account.launch_month} · ${plan.meta.campaigns.length} Meta + ${plan.google.campaigns.length} Google campaigns` });

    const { errors, warnings } = validate(plan);
    steps.push({ name: "Check guardrails", status: errors.length ? "error" : (warnings.length ? "warn" : "ok"),
      detail: errors.length ? `${errors.length} error(s) block the build` : (warnings.length ? `${warnings.length} warning(s), flagged ads/campaigns will be built PAUSED` : "All guardrails pass"),
      errors, warnings });

    const f = forecast(plan);
    steps.push({ name: "Forecast", status: "ok", detail: `$${Math.round(f.base.cpa)} blended CPA on ${Math.round(f.base.trials)} trials, $${num(Math.round(f.base.spend))} spend` });

    const summary = summaryMarkdown(plan, errors, warnings, f);
    const result = { plan, errors, warnings, forecast: f, summary, files: {} };
    if (errors.length) {
      steps.push({ name: "Write files", status: "error", detail: "Blocked: no CSVs written. Summary still generated." });
      return Object.assign(result, { ok: false, steps });
    }
    const g = googleRows(plan), m = metaRows(plan);
    result.files = {
      "google_ads_editor.csv": { text: toCsv(GOOGLE_COLS, g), cols: GOOGLE_COLS, rows: g },
      "meta_bulk_import.csv": { text: toCsv(META_COLS, m), cols: META_COLS, rows: m },
      "launch_summary.md": { text: summary },
    };
    steps.push({ name: "Write files", status: "ok", detail: `${g.length} Google rows, ${m.length} Meta ads, 3 files` });
    return Object.assign(result, { ok: true, steps });
  }

  const api = { runBuild, validate, forecast, googleRows, metaRows, toCsv, summaryMarkdown, GOOGLE_COLS, META_COLS };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.CampaignCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
