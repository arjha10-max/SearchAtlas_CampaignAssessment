# campaign-builder

Turns one YAML plan into launch-ready files for Google Ads Editor and Meta Ads Manager,
after checking the plan against the guardrails that the last 2 months of data taught us.

    pip install pyyaml pytest
    python build.py plans/2026-12_rebuild.yaml --out output/
    pytest -q

## Approved plan (December 2026)
`plans/2026-12_rebuild.yaml` is the final recommendation that was approved. The $/day and $/month table is in
[`docs/final_recommendation.md`](docs/final_recommendation.md). Budgets use a 30-day basis (`budget_days: 30`),
so the generated daily budgets match that table exactly. Two forecasts, both in the launch summary:
cautious (today's CPAs, no improvement) and best case (pre-break CPAs, Meta $245 / Google $258).

## Reuse for the next launch (5 steps)
1. `cp plans/2026-12_rebuild.yaml plans/2027-01_scale.yaml`
2. Edit `launch_month`, budgets, `assumed_cpa` (use last month's PostHog-basis CPA, not platform CPA), ads, keywords.
3. Fill `variables:` (brand_name, competitors) and `landing_url`, `pixel_id`.
4. `python build.py plans/2027-01_scale.yaml` - errors block the build, warnings come out PAUSED.
5. Import the two CSVs, use preview/check-changes in each tool, then enable.

## Guardrails enforced (each one comes from something in the data)
| Rule | Why |
|---|---|
| No shared budgets | Adding UK to the shared budget cut every US campaign ~31% and UK converted 0 |
| Platform split and $120K cap | Hard stop. Approved split is Meta $69,150 / Google $49,950 ($119,100 total) |
| Forecast blended CPA must land in $250-280 | Plan has to pay for itself on paper |
| utm_source = facebook / google on every URL | PostHog is the source of truth and reconciles on utm_source |
| Test lane: 1 concept per ad set (ABO) | Clean reads; CBO starves new ads |
| Geo gate: unverified -> PAUSED, $0 budget | UK spent $15K with zero reported conversions; $0 is only allowed on a gated campaign |
| RSA limits (30/90 chars), >=3 headlines, >=2 descriptions | Caught a 32-char headline during the first run |
| Placeholders / missing creative -> PAUSED | Nothing half-finished goes live |

## Limits (be upfront in the demo)
- Dry-run only: it writes files, it does not call the Meta/Google APIs. A `--push` mode would need
  OAuth + a developer token; the plan schema already carries everything the API calls need.
- Column names follow the Editor / Ads Manager import formats from memory; do one import with
  preview first and, if a column is rejected, export an existing campaign and match its header.
- PMax asset groups cannot be bulk uploaded.
