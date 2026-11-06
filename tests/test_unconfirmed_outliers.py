"""Run: python3.12 -m unittest discover -s tests (needs boto3 importable; no AWS calls)."""
import datetime
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("ADMIN_KEY", "test")
os.environ.setdefault("PIPELINE_API_KEY", "test")
os.environ.setdefault("PIPELINE_APP_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lambda_function as lf  # noqa: E402

SELL = "SELL ORDER (seller has shares available)"
BUY = "BUY ORDER (another buyer seeking shares; no shares available)"
TODAY = datetime.date(2026, 11, 6)


def raw_deal(deal_id, last=None, refresh=None, seller_role=None, stage=2094370):
    cf = {}
    if last is not None:
        cf[lf.LAST_CONFIRMED_FIELD] = last
    if refresh is not None:
        cf[lf.REFRESH_FIELD] = refresh
    if seller_role is not None:
        cf[lf.SELLER_ROLE_FIELD] = [seller_role]
    return {"id": deal_id, "deal_stage": {"id": stage}, "custom_fields": cf}


def ago(days, sep="/"):
    return (TODAY - datetime.timedelta(days=days)).strftime(f"%Y{sep}%m{sep}%d")


class UnconfirmedTests(unittest.TestCase):
    def setUp(self):
        self.m = lf.build_confirm_map({"deals": [
            raw_deal(1),                                         # blank date
            raw_deal(2, stage=lf.HOLD_STAGE_ID),                 # Hold, blank date
            raw_deal(3, refresh=0),                              # Refresh 0, blank date
            raw_deal(4, last=ago(41), seller_role=7020357),      # GP alloc, 41 days
            raw_deal(5, last=ago(41, "-")),                      # other, 41 days (dash format)
            raw_deal(6, last=ago(61)),                           # other, 61 days
            raw_deal(7, last=ago(10), refresh=5),                # Refresh 5, 10 days
        ]})

    def u(self, deal_id):
        return lf.is_unconfirmed(deal_id, self.m, today=TODAY)

    def test_blank_date_unconfirmed(self):
        self.assertTrue(self.u(1))

    def test_hold_never_unconfirmed(self):
        self.assertFalse(self.u(2))

    def test_refresh_zero_never_unconfirmed(self):
        self.assertFalse(self.u(3))

    def test_gp_alloc_41_days_unconfirmed(self):
        self.assertTrue(self.u(4))

    def test_other_41_days_confirmed(self):
        self.assertFalse(self.u(5))
        self.assertTrue(self.u(6))

    def test_refresh_overrides_default(self):
        self.assertTrue(self.u(7))

    def test_missing_from_snapshot_confirmed(self):
        self.assertFalse(self.u(999))

    def test_load_failure_all_confirmed(self):
        lf._CONFIRM_CACHE.update(ts=0.0, map=None)
        with mock.patch.object(lf, "load_s3_json", side_effect=RuntimeError("boom")):
            m = lf.load_confirm_map()
        self.assertEqual(m, {})
        self.assertFalse(lf.is_unconfirmed(1, m, today=TODAY))


def deal(deal_id, gross, side=SELL, company="Zipline", structure="direct", unconfirmed=False):
    d = {"id": deal_id, "company": company, "order_side": side, "_structure_class": structure,
         "unconfirmed": unconfirmed}
    if gross is not None:
        d["gross"] = gross
    return d


def ids(deals):
    return sorted(d["id"] for d in deals)


class OutlierTests(unittest.TestCase):
    def test_sells_keep_only_115(self):
        kept, dropped = lf.filter_price_outliers([deal(1, "338"), deal(2, 250), deal(3, "115")])
        self.assertEqual(ids(kept), [3])
        self.assertEqual(sorted((d[2], d[3], d[4]) for d in dropped), [(1, 338.0, 115.0), (2, 250.0, 115.0)])
        self.assertEqual(dropped[0][:2], ("Zipline", "sell"))
        self.assertFalse(dropped[0][5])

    def test_sells_within_band_kept(self):
        kept, dropped = lf.filter_price_outliers([deal(1, 100), deal(2, 140)])
        self.assertEqual((ids(kept), dropped), ([1, 2], []))

    def test_fund_spv_never_filtered(self):
        kept, dropped = lf.filter_price_outliers([deal(1, 100), deal(2, 300, structure="fund")])
        self.assertEqual((ids(kept), dropped), ([1, 2], []))

    def test_unconfirmed_not_reference(self):
        kept, dropped = lf.filter_price_outliers(
            [deal(1, 80, unconfirmed=True), deal(2, 115), deal(3, 130)])
        self.assertEqual((ids(kept), dropped), ([1, 2, 3], []))

    def test_unconfirmed_outlier_dropped(self):
        kept, dropped = lf.filter_price_outliers([deal(1, 100), deal(2, 200, unconfirmed=True)])
        self.assertEqual(ids(kept), [1])
        self.assertTrue(dropped[0][5])

    def test_single_deal_never_dropped(self):
        for d in (deal(1, 500), deal(1, 500, unconfirmed=True), deal(1, 500, side=BUY)):
            kept, dropped = lf.filter_price_outliers([d])
            self.assertEqual((ids(kept), dropped), ([1], []))

    def test_buys_drop_low(self):
        kept, dropped = lf.filter_price_outliers([deal(1, 100, side=BUY), deal(2, 60, side=BUY)])
        self.assertEqual(ids(kept), [1])
        self.assertEqual(dropped, [("Zipline", "buy", 2, 60.0, 100.0, False)])

    def test_unpriced_kept(self):
        kept, dropped = lf.filter_price_outliers([deal(1, 100), deal(2, None), deal(3, ""), deal(4, "0")])
        self.assertEqual((ids(kept), dropped), ([1, 2, 3, 4], []))

    def test_groups_by_company_and_side(self):
        kept, _ = lf.filter_price_outliers([deal(1, 100), deal(2, 300, company="Stripe"),
                                            deal(3, 300, side=BUY)])
        self.assertEqual(ids(kept), [1, 2, 3])

    def test_results_block(self):
        _, dropped = lf.filter_price_outliers([deal(55, 338), deal(56, 115)])
        box = lf.outlier_html(dropped)
        self.assertIn("Hidden as price outliers (check or obsolete in Pipeline):", box)
        self.assertIn("Zipline — sell $338 vs best $115 — https://app.pipelinecrm.com/deals/55", box)
        self.assertEqual(lf.outlier_html([]), "")


class HandlerTests(unittest.TestCase):
    """Model payload gets unconfirmed flags, never dates/outliers; results page shows the block."""

    def test_model_payload_and_page(self):
        raw = [
            {"id": 11, "company": "Zipline", "type": "Sell Order", "structure_class": "direct", "gross": "338"},
            {"id": 12, "company": "Zipline", "type": "Sell Order", "structure_class": "direct", "gross": "115"},
        ]
        snap = {"deals": [raw_deal(11, last=ago(400)), raw_deal(12, last=datetime.date.today().strftime("%Y/%m/%d"))]}
        lf._CONFIRM_CACHE.update(ts=0.0, map=None)
        sent = {}

        def fake_s3(bucket, key):
            return {"pipeline_deals.json": raw, "deals.json": snap}.get(key, {})

        def fake_run(inquiry, person_ctx, deals, tracked, side="both"):
            sent["deals"] = deals
            return "=== MATCHES ===\n- Sell order — Zipline [[D1]]\n=== EMAIL DRAFT ===\nHi"

        with mock.patch.object(lf, "load_s3_json", side_effect=fake_s3), \
                mock.patch.object(lf, "run_matcher", side_effect=fake_run):
            r = lf.lambda_handler({"queryStringParameters": {"key": lf.ADMIN_KEY},
                                   "requestContext": {"http": {"method": "POST"}},
                                   "body": "inquiry=zipline&side=sell"}, None)
        self.assertEqual(len(sent["deals"]), 1)
        md = sent["deals"][0]
        self.assertEqual(md["ref"], "D1")
        self.assertIs(md["unconfirmed"], False)
        self.assertFalse(any(k.startswith("_") for k in md))
        self.assertNotIn("338", str(sent["deals"]))
        self.assertIn("Zipline — sell $338 vs best $115 — https://app.pipelinecrm.com/deals/11", r["body"])
        self.assertIn("https://trades.graciagroup.com/deal/12", r["body"])
        email = r["body"].split('id="dm-email">', 1)[1]
        self.assertNotIn("outlier", email)


if __name__ == "__main__":
    unittest.main(verbosity=2)
