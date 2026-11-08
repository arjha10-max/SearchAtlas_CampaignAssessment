# Launch summary: B2B SaaS (mock account) (2026-12)

Cap $120,000 | Meta $69,150 | Google $49,950 | CPA target $250-$280

## Budget and forecast

| Platform | Campaign | Monthly $ | Daily $ | Assumed CPA | Trials |
|---|---|---:|---:|---:|---:|
| meta | Prospecting_A+_US_Scale | 49,500 | 1,650 | 250 | 198 |
| meta | Prospecting_Test_US_ABO | 9,900 | 330 | 328 | 30 |
| meta | Retargeting_US_14d | 9,750 | 325 | 433 | 23 |
| google | Search_NonBrand_US | 33,000 | 1,100 | 310 | 106 |
| google | Search_Brand_US | 9,000 | 300 | 154 | 58 |
| google | PMax_US | 7,950 | 265 | 338 | 24 |
| google | Search_NonBrand_UK (gated, paused) | 0 | 0 | 300 | 0 |

**Base case:** $119,100 -> 439 trials -> **$271 blended CPA**
**Brand 50% non-incremental:** 410 trials -> $291 CPA
**Every CPA +10%:** 399 trials -> $298 CPA

## Validation

- No errors.
- WARN: Total $119,100 leaves $900 of the $120,000 cap unallocated
- WARN: meta/Prospecting_Test_US_ABO/UGC_Founder_v3_NewHook: creative not supplied -> built PAUSED
- WARN: meta/Prospecting_Test_US_ABO/Static_Agents_vs_Manual: creative not supplied -> built PAUSED
- WARN: meta/Retargeting_US_14d/Retargeting_Second_Creative: creative not supplied -> built PAUSED
- WARN: google/Search_NonBrand_US/Alternatives_Competitor: unresolved {{placeholders}} -> built PAUSED
- WARN: google/Search_Brand_US/Brand_Core: unresolved {{placeholders}} -> built PAUSED
- WARN: google/Search_NonBrand_UK: gate not verified -> built PAUSED. Checks: UK test signup visible in PostHog with utm_source=google; Google conversion fires from a UK IP; UK pricing/currency on landing page
- WARN: Brand-haircut scenario CPA $291 breaks the $280 ceiling

## Manual steps (cannot be bulk-uploaded)

1. Fix and verify Meta Pixel + Conversions API on the signup flow *before* enabling anything (dedupe on event_id).
2. Build PMax asset groups, brand exclusions and audience signals in the Google Ads UI.
3. Create the shared-budget-free setup: confirm every Google campaign shows its own Standard budget after import.
4. Replace `landing_url`, `pixel_id` and `variables` in the plan; supply creative for ads marked PAUSED.
5. In Editor and Ads Manager use *Check changes / preview* before posting. Nothing here pushes live.
