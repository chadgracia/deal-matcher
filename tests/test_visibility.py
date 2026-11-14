"""Run: python3.12 -m unittest discover -s tests (needs boto3 importable; no AWS calls)."""
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


class NoSuchKey(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


def raw(deal_id, vis=None):
    cf = {} if vis is None else {lf.VISIBILITY_FIELD: vis}
    return {"id": deal_id, "deal_stage": {"id": 1}, "custom_fields": cf}


DEALS_JSON = {"deals": [raw(1), raw(2, lf.VIS_ALL), raw(3, [lf.VIS_INTERESTED]),
                        raw(4, "7223458.0"), raw(5, ""), raw(6, "junk"), raw(7, 999)]}


def live(i):
    return {"id": i, "company": f"Co{i}", "order_side": SELL}


def fake_s3(overrides):
    def _load(bucket, key):
        if key == "deals.json":
            return DEALS_JSON
        if key == lf.RESTORE_LOG_KEY:
            return {"entries": []}
        if key == lf.VIS_OVERRIDES_KEY:
            if isinstance(overrides, Exception):
                raise overrides
            return overrides
        raise AssertionError(key)
    return _load


class VisibilityTests(unittest.TestCase):
    def setUp(self):
        lf._CONFIRM_CACHE.update(ts=0.0, map=None, vis=None)
        lf._VIS_OVERRIDES_CACHE.update(ts=0.0, data=None)

    def test_vis_value_normalisation(self):
        for v in (None, "", [], "junk", 999, True, {"a": 1}):
            self.assertEqual(lf.vis_value(v), lf.VIS_ALL, v)
        for v in (7223458, "7223458", " 7223458.0 ", [7223458], ["7223458"]):
            self.assertEqual(lf.vis_value(v), lf.VIS_PRIVATE, v)
        self.assertEqual(lf.vis_value([lf.VIS_INTERESTED]), lf.VIS_INTERESTED)

    def test_map_and_filter(self):
        with mock.patch.object(lf, "load_s3_json", side_effect=fake_s3(NoSuchKey())):
            m = lf.load_visibility_map()
        self.assertEqual(m, {"1": lf.VIS_ALL, "2": lf.VIS_ALL, "3": lf.VIS_INTERESTED,
                             "4": lf.VIS_PRIVATE, "5": lf.VIS_ALL, "6": lf.VIS_ALL, "7": lf.VIS_ALL})
        deals = [live(i) for i in (1, 2, 3, 4, 5, 8)]   # 8 = missing from deals.json
        kept, interested = lf.apply_visibility(deals, m)
        self.assertEqual([d["id"] for d in kept], [1, 2, 3, 5, 8])          # Private dropped
        self.assertEqual([d["id"] for d in interested], [3])
        self.assertTrue(kept[2]["interested_investors_only"])
        for d in kept:                                                    # blank / All untouched
            if d["id"] != 3:
                self.assertNotIn("interested_investors_only", d)

    def test_override_wins(self):
        ov = {"1": {"v": lf.VIS_PRIVATE, "at": "2026-11-14T00:00:00Z"},
              "4": {"v": str(lf.VIS_ALL), "at": "2026-11-14T00:00:00Z"},
              "9": {"v": [lf.VIS_INTERESTED], "at": "2026-11-14T00:00:00Z"}}
        with mock.patch.object(lf, "load_s3_json", side_effect=fake_s3(ov)):
            m = lf.load_visibility_map()
        self.assertEqual((m["1"], m["4"], m["9"]), (lf.VIS_PRIVATE, lf.VIS_ALL, lf.VIS_INTERESTED))
        kept, interested = lf.apply_visibility([live(1), live(4), live(9)], m)
        self.assertEqual([d["id"] for d in kept], [4, 9])
        self.assertEqual([d["id"] for d in interested], [9])

    def test_overrides_cached_60s(self):
        s3 = mock.Mock(side_effect=fake_s3({}))
        with mock.patch.object(lf, "load_s3_json", s3):
            lf.load_visibility_map()
            lf.load_visibility_map()
        self.assertEqual([c.args[1] for c in s3.call_args_list].count(lf.VIS_OVERRIDES_KEY), 1)
        self.assertEqual([c.args[1] for c in s3.call_args_list].count("deals.json"), 1)

    def test_overrides_error_uses_deals_json(self):
        with mock.patch.object(lf, "load_s3_json", side_effect=fake_s3(RuntimeError("boom"))):
            m = lf.load_visibility_map()
        self.assertEqual(m["4"], lf.VIS_PRIVATE)

    def test_fail_soft_no_filtering(self):
        def bad(bucket, key):
            raise RuntimeError("down")
        with mock.patch.object(lf, "load_s3_json", side_effect=bad):
            with self.assertLogs(lf.logger, "WARNING") as cm:
                m = lf.load_visibility_map()
        self.assertIsNone(m)
        self.assertTrue(any("visibility: lookup failed; no visibility filtering" in x for x in cm.output))
        deals = [live(3), live(4)]
        kept, interested = lf.apply_visibility(deals, m)
        self.assertEqual(kept, deals)
        self.assertEqual(interested, [])

    def test_interested_html_admin_block(self):
        self.assertEqual(lf.interested_html([]), "")
        out = lf.interested_html([live(3)])
        self.assertIn("Interested investors only", out)
        self.assertIn("Co3 — Sell Order — https://app.pipelinecrm.com/deals/3", out)

    def test_prompt_tag(self):
        self.assertIn("interested_investors_only=true", lf.SYSTEM_PROMPT)
        self.assertIn("'(interested investors only)'", lf.SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
