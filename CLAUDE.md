# deal-matcher — project notes

AWS Lambda (Python, single file `lambda_function.py`). Deployed to the `deal-matcher` Lambda by
`.github/workflows/deploy.yml` on push to `main`.

## Verify
- `python3.12 -m py_compile lambda_function.py`
- `python3.12 -m unittest discover -s tests` (needs `boto3` importable; no AWS calls)

## Unconfirmed rule (shared — MUST stay identical to CRMDealDetails `unconfirmed_status()` and trades `_unconfirmed_since()`)
- Source: `s3://full-pipeline-cache/deals.json` (raw Pipeline snapshot, `{"deals": [...]}`) plus the
  stale-deal-scanner log `s3://full-pipeline-cache/obsolete-review/log.json`, both loaded with
  `load_s3_json` inside the same per-container 10-minute cache (`load_confirm_map`). Fail-soft: any
  deals.json load error -> every deal is confirmed; a missing/unreadable/malformed log -> no restores
  (never fails the deals load).
- Fields: LAST_CONFIRMED `custom_label_4012491` ("YYYY/MM/DD" or "YYYY-MM-DD"), REFRESH
  `custom_label_3994687` (days), SELLER_ROLE `custom_label_3938748`, and the deal's `updated_at`
  (Pipeline "YYYY/MM/DD HH:MM:SS +0000" or ISO -> aware UTC datetime; missing/unparseable = ignored).
- Threshold = REFRESH if set (0 = never Unconfirmed); else 30 days if SELLER_ROLE is 7020357
  (GP — syndicating new allocation), else 60.
- Effective date = the newer of LAST_CONFIRMED and the UTC date of `updated_at` (any Pipeline edit
  counts as confirmation). Unconfirmed when there is no effective date, or it is more than the
  threshold days before today's UTC date. Hold (stage 2094373) is never Unconfirmed. A deal missing
  from deals.json counts as confirmed.
- Restore exception: per deal take the LATEST log entry (newest `at`; tie/unreadable -> later in the
  list). If its action is `"restored"`, `updated_at` counts only when > 15 minutes after that `at`
  (unreadable `at` -> ignore `updated_at`); otherwise LAST_CONFIRMED alone. Stops a bulk restore's own
  write from making an old deal look confirmed; later edits still count.
- Tests: `tests/test_unconfirmed_outliers.py`, `tests/test_unconfirmed_updated_at.py`.
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

## SECURITY RULES — MANDATORY (read before any change)

This repo is PUBLIC, and so are its GitHub Actions logs. Secrets have leaked from Chad's repos 5-6 times. Never again.

1. No secret value ever goes in code, tests, docs, comments, commit messages, PR text or logs. That includes API keys, admin keys, HMAC/signing secrets, tokens, passwords, and any URL containing `key=`, `token=` or `sso=`. Secrets come from `os.environ[...]` (Lambda environment variables) or `s3://pipeline-token/` only. Tests use obvious fakes like `"test-key"`.
2. Every `aws lambda ...` command in a workflow must end with `> /dev/null`. Lambda API responses include every environment variable, and the logs are public. Never print the environment (`printenv`, `env`, `set -x`, or `print(os.environ)`).
3. Never log or print a secret, even partially, or a request URL that carries one.
4. `.github/scripts/secret_guard.py` runs automatically before every `git commit` and `git push` (via `.claude/settings.json`), and again in CI. If it blocks you, remove the secret and move the value to an environment variable. NEVER bypass, weaken, delete or skip the guard, and never use `--no-verify` or `secret-guard: allow` to get past it without Chad's explicit approval.
5. A new secret needs Chad to add a Lambda environment variable first. Tell him the exact variable name. Code that reads it ships after that.
6. Before finishing, run `python3 .github/scripts/secret_guard.py --tree` and report the result.
7. NEVER build anything that asks for, collects, uploads, stores, emails or processes client identity data — tax IDs, SSNs, passports, driver's licenses, other government IDs, or dates of birth. Chad does not want or need it; identity verification is handled by Rainmaker's own forms. If a task seems to need it, stop and ask Chad.
