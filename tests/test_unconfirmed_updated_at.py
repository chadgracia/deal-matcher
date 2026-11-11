"""Unconfirmed rule: updated_at + restore exception. Fake S3 only; no network.
Must match CRMDealDetails unconfirmed_status() and trades _unconfirmed_since()."""
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

UTC = datetime.timezone.utc
TODAY = datetime.date(2026, 11, 6)
NOON = datetime.datetime(2026, 11, 6, 12, tzinfo=UTC)
DID = 4242
LOG = lf.RESTORE_LOG_KEY


def ago(days):
    return NOON - datetime.timedelta(days=days)


def pipe_ts(dt):
    return dt.astimezone(UTC).strftime("%Y/%m/%d %H:%M:%S +0000")


def raw_deal(lc=None, updated=None, raw_updated=None, refresh=None, stage=2094370, deal_id=DID):
    cf = {}
    if lc is not None:
        cf[lf.LAST_CONFIRMED_FIELD] = lc.strftime("%Y/%m/%d")
    if refresh is not None:
        cf[lf.REFRESH_FIELD] = refresh
    d = {"id": deal_id, "deal_stage": {"id": stage}, "custom_fields": cf}
    if updated is not None:
        d["updated_at"] = pipe_ts(updated)
    if raw_updated is not None:
        d["updated_at"] = raw_updated
    return d


def restored_log(action="restored", days=150, at=None):
    t = ago(days)
    return t, {"entries": [
        {"deal_id": DID, "action": "kept", "at": (t - datetime.timedelta(days=5)).isoformat()},
        {"deal_id": 777, "action": "restored", "at": t.isoformat()},
        {"deal_id": DID, "action": action, "at": at if at is not None else t.strftime("%Y-%m-%dT%H:%M:%SZ")},
    ]}


class Base(unittest.TestCase):
    def setUp(self):
        lf._CONFIRM_CACHE.update(ts=0.0, map=None)

    tearDown = setUp

    def unconf(self, deals, log=None, log_error=None, deal_id=DID):
        """Run through load_confirm_map with a fake load_s3_json, then is_unconfirmed."""
        lf._CONFIRM_CACHE.update(ts=0.0, map=None)
        self.calls = []

        def fake(bucket, key):
            self.calls.append(key)
            if key == "deals.json":
                return {"deals": deals}
            if key == LOG:
                if log_error:
                    raise log_error
                if log is None:
                    raise RuntimeError("NoSuchKey")
                return log
            raise AssertionError(key)

        with mock.patch.object(lf, "load_s3_json", side_effect=fake):
            m = lf.load_confirm_map()
        return lf.is_unconfirmed(deal_id, m, today=TODAY)


class UpdatedAt(Base):
    def test_blank_lc_edit_1_day_ago_confirmed(self):
        self.assertFalse(self.unconf([raw_deal(updated=ago(1))]))

    def test_blank_lc_edit_100_days_ago_unconfirmed(self):
        self.assertTrue(self.unconf([raw_deal(updated=ago(100))]))

    def test_lc_10_days_edit_100_days_confirmed(self):
        self.assertFalse(self.unconf([raw_deal(lc=ago(10), updated=ago(100))]))

    def test_old_lc_recent_edit_confirmed(self):
        self.assertFalse(self.unconf([raw_deal(lc=ago(200), updated=ago(3))]))

    def test_threshold_boundary_on_updated_date(self):
        self.assertFalse(self.unconf([raw_deal(updated=ago(60))]))
        self.assertTrue(self.unconf([raw_deal(updated=ago(61))]))

    def test_iso_and_offset_updated_at(self):
        self.assertFalse(self.unconf([raw_deal(raw_updated=ago(1).isoformat())]))
        self.assertTrue(self.unconf([raw_deal(raw_updated=ago(100).strftime("%Y-%m-%dT%H:%M:%SZ"))]))
        m = lf.build_confirm_map({"deals": [raw_deal(raw_updated="2026/09/07 22:30:00 -0400")]})
        self.assertEqual(m[str(DID)][4], datetime.datetime(2026, 9, 8, 2, 30, tzinfo=UTC))

    def test_missing_or_bad_updated_at_uses_lc_alone(self):
        self.assertTrue(self.unconf([raw_deal(lc=ago(100))]))
        self.assertFalse(self.unconf([raw_deal(lc=ago(5))]))
        self.assertTrue(self.unconf([raw_deal(lc=ago(100), raw_updated="garbage")]))
        self.assertFalse(self.unconf([raw_deal(lc=ago(5), raw_updated="garbage")]))
        self.assertTrue(self.unconf([raw_deal()]))


class RestoreException(Base):
    def test_restore_write_does_not_confirm(self):
        t, log = restored_log()
        self.assertTrue(self.unconf([raw_deal(lc=ago(200), updated=t + datetime.timedelta(minutes=1))], log))

    def test_restore_exactly_15_min_still_ignored(self):
        t, log = restored_log()
        self.assertTrue(self.unconf([raw_deal(updated=t + datetime.timedelta(minutes=15))], log))

    def test_edit_two_days_after_restore_confirmed(self):
        t, log = restored_log(days=4)
        self.assertFalse(self.unconf([raw_deal(lc=ago(200), updated=t + datetime.timedelta(days=2))], log))

    def test_restore_unreadable_at_ignores_updated_at(self):
        _, log = restored_log(at="not a time")
        log["entries"] = [log["entries"][2]]
        self.assertTrue(self.unconf([raw_deal(lc=ago(200), updated=ago(1))], log))
        self.assertFalse(self.unconf([raw_deal(lc=ago(5), updated=ago(1))], log))

    def test_latest_undone_plain_rule(self):
        t, log = restored_log(action="undone")
        self.assertFalse(self.unconf([raw_deal(lc=ago(200), updated=ago(1))], log))
        self.assertTrue(self.unconf([raw_deal(lc=ago(200), updated=t + datetime.timedelta(minutes=1))], log))

    def test_latest_by_time_not_position(self):
        t = ago(150)
        log = {"entries": [
            {"deal_id": DID, "action": "restored", "at": t.isoformat()},
            {"deal_id": DID, "action": "kept", "at": (t - datetime.timedelta(days=1)).isoformat()},
        ]}
        self.assertTrue(self.unconf([raw_deal(lc=ago(200), updated=t + datetime.timedelta(minutes=1))], log))

    def test_tie_later_in_list_wins(self):
        t = ago(150).isoformat()
        log = {"entries": [{"deal_id": DID, "action": "restored", "at": t},
                           {"deal_id": DID, "action": "undone", "at": t}]}
        self.assertFalse(self.unconf([raw_deal(updated=ago(1))], log))

    def test_other_deal_restore_ignored(self):
        log = {"entries": [{"deal_id": 777, "action": "restored", "at": ago(1).isoformat()}]}
        self.assertFalse(self.unconf([raw_deal(updated=ago(1))], log))

    def test_log_unreadable_plain_rule_and_deals_still_load(self):
        self.assertFalse(self.unconf([raw_deal(updated=ago(1))], log_error=RuntimeError("AccessDenied")))
        self.assertTrue(self.unconf([raw_deal(updated=ago(100))], log_error=RuntimeError("AccessDenied")))
        self.assertIsNotNone(lf._CONFIRM_CACHE["map"])

    def test_log_missing_plain_rule(self):
        self.assertFalse(self.unconf([raw_deal(updated=ago(1))], log=None))

    def test_log_malformed_plain_rule(self):
        for bad in (["not", "a", "dict"], {"entries": "junk"}, {"entries": [1, None, {"x": 1}]}, "str"):
            self.assertFalse(self.unconf([raw_deal(updated=ago(1))], log=bad), bad)
        self.assertEqual(lf.build_restore_map(["x"]), {})

    def test_log_in_same_ten_minute_cache(self):
        _, log = restored_log()
        self.unconf([raw_deal(updated=ago(1))], log)
        with mock.patch.object(lf, "load_s3_json", side_effect=AssertionError("cached")):
            lf.load_confirm_map()
        self.assertEqual(self.calls, ["deals.json", LOG])


class Unchanged(Base):
    def test_hold_and_refresh_zero_confirmed(self):
        self.assertFalse(self.unconf([raw_deal(updated=ago(400), stage=lf.HOLD_STAGE_ID)]))
        self.assertFalse(self.unconf([raw_deal(updated=ago(400), refresh=0)]))

    def test_missing_from_deals_json_confirmed(self):
        self.assertFalse(self.unconf([raw_deal(updated=ago(400))], deal_id=999))

    def test_deals_load_failure_all_confirmed(self):
        with mock.patch.object(lf, "load_s3_json", side_effect=RuntimeError("boom")):
            m = lf.load_confirm_map()
        self.assertEqual(m, {})


if __name__ == "__main__":
    unittest.main()
