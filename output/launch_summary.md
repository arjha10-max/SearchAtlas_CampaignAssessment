# Launch summary: B2B SaaS (mock account) (2026-12)

Cap $120,000 | Meta $65,000 | Google $55,000 | CPA target $250-$280

## Budget and forecast

| Platform | Campaign | Monthly $ | Daily $ | Assumed CPA | Trials |
|---|---|---:|---:|---:|---:|
| meta | Prospecting_A+_US_Scale | 42,000 | 1,355 | 240 | 175 |
| meta | Prospecting_Test_US_ABO | 14,000 | 452 | 300 | 47 |
| meta | Retargeting_US_14d | 6,000 | 194 | 350 | 17 |
| meta | Flex reserve | 3,000 | reserve | 240 | 12 |
| google | Search_NonBrand_US | 27,000 | 871 | 290 | 93 |
| google | Search_Brand_US | 9,000 | 290 | 155 | 58 |
| google | PMax_US | 11,000 | 355 | 320 | 34 |
| google | Search_NonBrand_UK (gated, paused) | 3,000 | 97 | 300 | 10 |
| google | Flex reserve | 5,000 | reserve | 290 | 17 |

**Base case:** $120,000 -> 464 trials -> **$259 blended CPA**
**Brand 50% non-incremental:** 435 trials -> $276 CPA
**Every CPA +10%:** 422 trials -> $284 CPA

## Validation

- No errors.
- WARN: meta/Prospecting_Test_US_ABO/UGC_Founder_v3_NewHook: creative not supplied -> built PAUSED
- WARN: meta/Prospecting_Test_US_ABO/Static_Agents_vs_Manual: creative not supplied -> built PAUSED
- WARN: google/Search_NonBrand_US/Alternatives_Competitor: unresolved {{placeholders}} -> built PAUSED
- WARN: google/Search_Brand_US/Brand_Core: unresolved {{placeholders}} -> built PAUSED
- WARN: google/Search_NonBrand_UK: gate not verified -> built PAUSED. Checks: UK test signup visible in PostHog with utm_source=google; Google conversion fires from a UK IP; UK pricing/currency on landing page

## Manual steps (cannot be bulk-uploaded)

1. Fix and verify Meta Pixel + Conversions API on the signup flow *before* enabling anything (dedupe on event_id).
2. Build PMax asset groups, brand exclusions and audience signals in the Google Ads UI.
3. Create the shared-budget-free setup: confirm every Google campaign shows its own Standard budget after import.
4. Replace `landing_url`, `pixel_id` and `variables` in the plan; supply creative for ads marked PAUSED.
5. In Editor and Ads Manager use *Check changes / preview* before posting. Nothing here pushes live.
