"""python3 -m unittest ledger/test_match.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from match import Brand, damerau, registrable, score, split_host  # noqa: E402

PAYPAL = Brand("paypal", ["paypal.com", "paypal.me"])
PAYTM = Brand("paytm", ["paytm.com", "paytmbank.com"])
ACME = Brand("acmebank", ["acmebank.com"])


def pts(host, brand=PAYPAL):
	return score(host, brand)[0]


def kinds(host, brand=PAYPAL):
	return {r["kind"] for r in score(host, brand)[1]}


class Match(unittest.TestCase):
	def test_owned_domains_never_match(self):
		self.assertEqual(pts("paypal.com"), 0)
		self.assertEqual(pts("www.paypal.com"), 0)
		self.assertEqual(pts("checkout.paypal.me"), 0)

	def test_unrelated(self):
		for h in ("example.com", "pineapple.org", "mail.google.com", "papal-history.org"):
			self.assertLess(pts(h), 56, h)

	def test_contains(self):
		self.assertIn("contains", kinds("paypal-verify-account.com"))
		self.assertGreaterEqual(pts("paypal-verify-account.com"), 85)
		self.assertIn("contains", kinds("paypal.co.in"))

	def test_homoglyph(self):
		host = "xn--" + "рaypal".encode("punycode").decode()  + ".com"  # Cyrillic р
		self.assertIn("homoglyph", kinds(host))
		self.assertGreaterEqual(pts(host), 95)

	def test_leet_and_pairs(self):
		self.assertIn("leet", kinds("paypa1-login.com"))
		self.assertIn("leet", kinds("acrnebank.com", ACME))

	def test_typo(self):
		self.assertIn("typo", kinds("papyal.com"))
		self.assertIn("contains", kinds("paypall.com"))
		self.assertIn("typo", kinds("acmebnak.net", ACME))
		self.assertEqual(pts("paypal.com"), 0)
		self.assertIn("typo", kinds("netflx-billing-update.com", Brand("netflix", ["netflix.com"])))
		self.assertEqual(pts("devb.ref-finance.com", Brand("binance", ["binance.com"])), 0)
		self.assertEqual(pts("nordic-finance.com", Brand("binance", ["binance.com"])), 0)

	def test_short_terms_need_word_boundaries(self):
		short = Brand("sbi", ["sbi.co.in", "onlinesbi.sbi"])
		self.assertEqual(pts("website.com", short), 0)
		self.assertEqual(pts("lesbian.org", short), 0)
		self.assertGreaterEqual(pts("sbi-kyc-update.com", short), 70)
		self.assertGreaterEqual(pts("sbikyc.in", short), 70)

	def test_free_hosting_counts_as_registered(self):
		self.assertEqual(split_host("paypal-login.vercel.app"), ("", "paypal-login", "vercel.app"))
		self.assertIn("contains", kinds("paypal-login.vercel.app"))
		self.assertIn("free-host", kinds("paypal-login.vercel.app"))

	def test_subdomain_only(self):
		self.assertIn("subdomain", kinds("paypal.random-shop.com"))
		self.assertLess(pts("paypal.random-shop.com"), 70)

	def test_helpers(self):
		self.assertEqual(registrable("a.b.example.co.uk"), "example.co.uk")
		self.assertEqual(damerau("paypal", "papyal"), 1)
		self.assertEqual(damerau("paypal", "paypal"), 0)


if __name__ == "__main__":
	unittest.main()
