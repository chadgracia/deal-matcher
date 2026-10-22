"""Run: python3 tests/test_deal_ids.py (needs boto3 importable; no AWS calls)."""
import os
import sys
import unittest

os.environ.setdefault("ADMIN_KEY", "test")
os.environ.setdefault("PIPELINE_API_KEY", "test")
os.environ.setdefault("PIPELINE_APP_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lambda_function as lf  # noqa: E402

SELL = "SELL ORDER (seller has shares available)"
BUY = "BUY ORDER (another buyer seeking shares; no shares available)"
URL = "https://trades.graciagroup.com/deal/"

DEALS = [
    {"id": 55411897, "company": "Anduril", "order_side": SELL, "structure": "SPV on cap table",
     "min_size": "1500000", "max_size": "1500000", "net_price": "137"},
    {"id": 55411898, "company": "Anduril", "order_side": SELL, "structure": "2-Layer",
     "min_size": "250000", "max_size": "3000000", "net_price": "150"},
    {"id": 55411915, "company": "Moonshot AI", "order_side": SELL, "max_size": "2000000", "net_price": "12.5"},
    {"id": 55411920, "company": "Stripe", "order_side": SELL, "max_size": "500000", "net_price": "27"},
    {"id": 55411930, "company": "Stripe", "order_side": BUY, "max_size": "1000000", "net_price": "26"},
]


def make_output(match_line, email_para):
    return ("=== MATCHES ===\n" + match_line + "\n\n=== EMAIL DRAFT ===\nHi Sam,\n\n"
            + email_para + "\n\nBest,\nChad")


class DealIdCheck(unittest.TestCase):
    def test_correct_link_untouched(self):
        out = make_output(
            "- Sell order — Stripe (id 55411920): fits the size.",
            "Stripe\nCommon, up to $500K, net $27.\n" + URL + "55411920")
        fixed, corr, unres = lf.check_deal_ids(out, DEALS)
        self.assertEqual(fixed, out)
        self.assertEqual((corr, unres), ([], []))
        self.assertEqual(lf.id_warning_html(corr, unres), "")

    def test_anduril_moonshot_autocorrected_by_figures(self):
        out = make_output(
            "- Sell order — Anduril (id 55411915): SPV on cap table, $1.5M fixed, net $137.",
            "Anduril\nSPV on cap table, $1.5M fixed, net $137.\n" + URL + "55411915")
        fixed, corr, unres = lf.check_deal_ids(out, DEALS)
        self.assertNotIn("55411915", fixed)
        self.assertIn(URL + "55411897", fixed)
        self.assertIn("(id 55411897)", fixed)
        self.assertEqual(corr, [("Anduril", "55411915", "55411897")])
        self.assertEqual(unres, [])
        box = lf.id_warning_html(corr, unres)
        self.assertIn("Anduril: 55411915 &rarr; 55411897", box)
        self.assertIn("#b91c1c", box)

    def test_ambiguous_flagged_not_changed(self):
        # Two Anduril sell deals and no figures that single one out.
        out = make_output(
            "- Sell order — Anduril (id 55411915): defense exposure.",
            "Anduril\nDefense autonomy; terms on request.\n" + URL + "55411915")
        fixed, corr, unres = lf.check_deal_ids(out, DEALS)
        self.assertEqual(corr, [])
        self.assertIn(URL + "55411915" + lf.ID_CHECK_FLAG, fixed)
        self.assertIn("(id 55411915" + lf.ID_CHECK_FLAG + ")", fixed)
        self.assertEqual(len(unres), 2)
        self.assertEqual(unres[0][0], "Anduril")
        self.assertEqual(sorted(unres[0][2]), ["55411897", "55411898"])
        box = lf.id_warning_html(corr, unres)
        self.assertIn("NOT changed", box)
        self.assertIn("55411897, 55411898", box)

    def test_single_candidate_same_side_corrected(self):
        out = make_output("- Sell order — Stripe (id 55411915): common.", "Stripe\nCommon shares.\n" + URL + "55411915")
        fixed, corr, _ = lf.check_deal_ids(out, DEALS)
        self.assertIn(URL + "55411920", fixed)
        self.assertEqual(corr, [("Stripe", "55411915", "55411920")])

    def test_unknown_id_flagged(self):
        out = make_output("- Sell order — Stripe (id 99999999): common.", "Hi")
        _, corr, unres = lf.check_deal_ids(out, DEALS)
        self.assertEqual(corr, [("Stripe", "99999999", "55411920")])
        out = make_output("- Tracked only — Acme (id 99999999).", "Hi")
        fixed, corr, unres = lf.check_deal_ids(out, DEALS)
        self.assertEqual(corr, [])
        self.assertIn(lf.ID_CHECK_FLAG, fixed)
        self.assertEqual(unres[0][1], "99999999")


if __name__ == "__main__":
    unittest.main(verbosity=2)
