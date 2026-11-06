# deal-matcher — project notes

AWS Lambda (Python, single file `lambda_function.py`). Deployed to the `deal-matcher` Lambda by
`.github/workflows/deploy.yml` on push to `main`.

## Verify
- `python3.12 -m py_compile lambda_function.py`
- `python3.12 -m unittest discover -s tests` (needs `boto3` importable; no AWS calls)

## Unconfirmed deals (shared rule — keep identical to chadgracia/trades and CRMDealDetails)
- Source: `s3://full-pipeline-cache/deals.json` (raw Pipeline snapshot, `{"deals": [...]}`), cached per
  container for 10 minutes (`load_confirm_map`). Fail-soft: any load error -> every deal is confirmed.
- Fields: LAST_CONFIRMED `custom_label_4012491` ("YYYY/MM/DD" or "YYYY-MM-DD"), REFRESH
  `custom_label_3994687` (days), SELLER_ROLE `custom_label_3938748`.
- Threshold = REFRESH if set (0 = never Unconfirmed); else 30 days if SELLER_ROLE is 7020357
  (GP — syndicating new allocation), else 60.
- Unconfirmed when LAST_CONFIRMED is blank or more than the threshold days before today's UTC date.
  Hold (stage 2094373) is never Unconfirmed. A deal missing from deals.json counts as confirmed.
- The model gets `"unconfirmed": true/false` on each live deal — never the date. SYSTEM_PROMPT tells it
  to tag them "(unconfirmed)" in MATCHES, call them older indications Chad will reconfirm in the email,
  and list confirmed deals first when fit is equal.

## Price outliers — Direct deals only (`filter_price_outliers`)
- Runs on `matched_deals` after own-deal exclusion and the unconfirmed flags, BEFORE D1/D2 refs.
- Only `structure_class == "direct"` (from pipeline_deals.json, kept internally as `_structure_class`
  and stripped before the model call) takes part. Fund/SPV, Forward and unknown structure: never filtered.
- Group by company (lowercased) + side. Gross price only; no numeric gross > 0 -> always kept.
- Reference comes only from CONFIRMED priced Direct deals: SELL = lowest gross, BUY = highest gross.
  No confirmed priced deal in the group -> nothing filtered.
- Drop Direct sells with gross > 1.5 x ref and Direct buys with gross < 0.67 x ref (confirmed or not).
  Never drop the last remaining deal for a company + side.
- Dropped deals appear ONLY on the results page, in the muted "Hidden as price outliers (check or
  obsolete in Pipeline):" block (`outlier_html`). Never sent to the model, never in the email draft.
