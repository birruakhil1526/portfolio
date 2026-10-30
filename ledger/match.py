"""Lookalike scoring: does this hostname pretend to be a watched brand?

A brand is a term ("paypal") plus the domains it really owns. A hostname is reduced to a
"skeleton" (punycode decoded, homoglyphs and accents folded to ASCII) and then checked for:
  homoglyph  the skeleton spells the brand, the raw name does not (раypal with a Cyrillic р)
  leet       digit swaps spell the brand (paypa1, netfl1x)
  contains   the brand appears inside a name it doesn't own (paypal-verify.com)
  typo       one or two keystrokes away (paypall, netflx)
Scam words (login, verify, kyc, refund, ...) add weight. Each check explains itself, so the
console and the lookalike lab can show why a name scored what it did.
"""
import re
import unicodedata

# Cyrillic, Greek and Latin look-alikes of ASCII letters (Unicode confusables, the common ones)
HOMOGLYPHS = {
	"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j",
	"ԁ": "d", "ӏ": "l", "ѕ": "s", "ԛ": "q", "ԝ": "w", "һ": "h", "ո": "n", "ս": "u", "к": "k",
	"м": "m", "т": "t", "в": "b", "н": "h", "ɡ": "g", "ı": "i", "ł": "l", "ø": "o", "ð": "d",
	"α": "a", "ο": "o", "ν": "v", "ι": "i", "κ": "k", "ρ": "p", "τ": "t", "υ": "u", "ε": "e",
	"ϲ": "c", "ԍ": "g", "ɩ": "l", "ɑ": "a", "ʋ": "v", "ꞩ": "s", "ᴠ": "v", "ᴡ": "w", "ꮃ": "w",
}
LEET = {"0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "9": "g", "$": "s", "@": "a"}
# letter pairs that read as one letter at a glance
PAIRS = [("rn", "m"), ("vv", "w"), ("cl", "d"), ("nn", "m")]

SCAM_WORDS = {
	"login", "signin", "secure", "verify", "verification", "account", "update", "support", "help",
	"service", "customer", "care", "refund", "reward", "rewards", "bonus", "gift", "offer", "claim",
	"wallet", "otp", "kyc", "pay", "payment", "bank", "loan", "auth", "unlock", "billing", "invoice",
	"alert", "confirm", "recovery", "restore", "upi", "aadhaar", "pan", "card", "cashback", "prize",
	"official", "online", "portal", "web", "app", "my", "id", "connect", "sync", "airdrop",
}

# suffixes under which the next label is what someone registered (a slice of the Public
# Suffix List: country second levels plus the free hosting platforms phishers love)
SUFFIXES = {
	"co.in", "org.in", "net.in", "firm.in", "gen.in", "ind.in", "gov.in", "ac.in", "edu.in",
	"co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.nz", "co.za",
	"com.br", "com.mx", "com.ar", "co.jp", "ne.jp", "or.jp", "com.cn", "com.hk", "com.sg",
	"com.my", "co.id", "com.tr", "com.ng", "co.ke", "com.pk", "com.bd", "com.np", "com.lk",
	"github.io", "gitlab.io", "vercel.app", "netlify.app", "pages.dev", "workers.dev",
	"web.app", "firebaseapp.com", "herokuapp.com", "azurewebsites.net", "onrender.com",
	"fly.dev", "glitch.me", "repl.co", "replit.app", "blogspot.com", "wixsite.com",
	"weebly.com", "webflow.io", "framer.app", "ngrok.io", "ngrok-free.app", "trycloudflare.com",
	"duckdns.org", "000webhostapp.com", "appspot.com", "cloudfront.net", "s3.amazonaws.com",
	"surge.sh", "translate.goog", "r2.dev", "lovable.app", "bolt.new", "carrd.co",
}


def to_unicode(host):
	out = []
	for label in host.split("."):
		if label.startswith("xn--"):
			try:
				label = label.encode("ascii").decode("idna")
			except Exception:
				pass
		out.append(label)
	return ".".join(out)


def skeleton(s):
	s = "".join(HOMOGLYPHS.get(c, c) for c in s.lower())
	s = unicodedata.normalize("NFKD", s)
	return "".join(c for c in s if not unicodedata.combining(c))


def deleet(s):
	s = "".join(LEET.get(c, c) for c in s)
	for a, b in PAIRS:
		s = s.replace(a, b)
	return s


def split_host(host):
	"""('login.paypal-secure', 'paypal-secure', 'co.in') for login.paypal-secure.co.in"""
	labels = host.split(".")
	if len(labels) < 2:
		return "", host, ""
	for n in (3, 2):
		if len(labels) > n and ".".join(labels[-n:]) in SUFFIXES:
			return ".".join(labels[:-n - 1]), labels[-n - 1], ".".join(labels[-n:])
	return ".".join(labels[:-2]), labels[-2], labels[-1]


def registrable(host):
	_, label, suffix = split_host(host)
	return f"{label}.{suffix}" if suffix else label


def tokens(s):
	return [t for t in re.split(r"[^a-z]+", s) if t]


def damerau(a, b, cap=3):
	"""Edit distance with transpositions, giving up once it passes `cap`."""
	if abs(len(a) - len(b)) > cap:
		return cap + 1
	prev2, prev = None, list(range(len(b) + 1))
	for i in range(1, len(a) + 1):
		cur = [i] + [0] * len(b)
		best = cur[0]
		for j in range(1, len(b) + 1):
			cost = a[i - 1] != b[j - 1]
			cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
			if prev2 and i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
				cur[j] = min(cur[j], prev2[j - 2] + 1)
			best = min(best, cur[j])
		if best > cap:
			return cap + 1
		prev2, prev = prev, cur
	return prev[-1]


class Brand:
	def __init__(self, term, official=(), keywords=(), id=None, label=None):
		self.id = id
		self.term = re.sub(r"[^a-z0-9]", "", skeleton(term))
		self.label = label or term
		self.official = {d.lower().strip().lstrip("*.").rstrip(".") for d in official if d.strip()}
		self.keywords = {k.lower() for k in keywords}

	def owns(self, host):
		return any(host == d or host.endswith("." + d) for d in self.official)


def score(host, brand):
	"""(score 0-100, [reasons]) of `host` imitating `brand`; (0, []) when it doesn't."""
	host = host.lower().rstrip(".")
	term = brand.term
	if not term or len(term) < 3 or brand.owns(host):
		return 0, []
	uni = to_unicode(host)
	sub, label, suffix = split_host(uni)
	raw_label = label.lower()
	sk_label, sk_sub = skeleton(raw_label), skeleton(sub)
	flat_label = re.sub(r"[^a-z0-9]", "", sk_label)
	short = len(term) <= 4
	reasons, best = [], 0

	def hit(points, kind, detail):
		nonlocal best
		best = max(best, points)
		reasons.append({"kind": kind, "points": points, "detail": detail})

	# 1. homoglyphs: non-ASCII letters that fold into the brand
	if any(ord(c) > 127 for c in raw_label) and term in flat_label:
		swapped = [f"{c} (U+{ord(c):04X}) looks like {HOMOGLYPHS.get(c, skeleton(c))}"
		           for c in raw_label if ord(c) > 127 and skeleton(c) != c][:3]
		hit(96, "homoglyph", "; ".join(swapped) or "non-Latin letters spell the brand")

	label_tokens = tokens(flat_label) if not short else tokens(sk_label)
	contains = (term in flat_label) if not short else (
		term in label_tokens or any(t.startswith(term) and t[len(term):] in SCAM_WORDS for t in label_tokens)
		or any(t.endswith(term) and t[:-len(term)] in SCAM_WORDS for t in label_tokens))

	# 2. leet / letter-pair swaps
	if not contains and best < 96:
		dl = re.sub(r"[^a-z]", "", deleet(sk_label))
		if (term in dl) if not short else (term in tokens(deleet(sk_label))):
			hit(88, "leet", f"'{label}' reads as '{dl}' with digit or letter-pair swaps")

	# 3. brand inside a registered name it doesn't own
	if contains and best < 96:
		exact = flat_label == term
		pts = 82 if exact else 74
		where = f"{label}.{suffix}" if suffix else label
		hit(pts, "contains", f"'{term}' registered under {where}" + (" (same name, other TLD)" if exact else ""))

	# 4. typo distance on the registered label and its pieces
	if best < 74 and not short and len(term) >= 5:
		cap = 1 if len(term) < 9 else 2
		# a shorter piece of a longer name is usually a real word (papal-history), not a typo;
		# a piece only counts when the name also carries scam words (netflx-billing), and typosquats
		# keep the first letter, which rules out real words like finance vs binance
		pieces = tokens(sk_label)
		scammy = any(t in SCAM_WORDS or t in brand.keywords for t in pieces)
		cands = {flat_label} | ({t for t in pieces if len(t) >= len(term) - 1} if scammy else set())
		for cand in cands:
			if cand and cand != term and cand[0] == term[0] and abs(len(cand) - len(term)) <= cap:
				d = damerau(cand, term, cap)
				if d <= cap:
					hit(80 - 6 * (d - 1), "typo", f"'{cand}' is {d} keystroke{'s' if d > 1 else ''} from '{term}'")
					break

	# 5. brand only in the subdomain of somebody else's domain (paypal.example-shop.com)
	if best == 0 and sk_sub:
		sub_flat = tokens(sk_sub)
		if (term in re.sub(r"[^a-z0-9]", "", sk_sub)) if not short else term in sub_flat:
			hit(58, "subdomain", f"'{term}' in the subdomain of {label}.{suffix}")

	if best == 0:
		return 0, []

	words = [t for t in tokens(skeleton(uni).replace(term, " ")) if t in SCAM_WORDS | brand.keywords]
	if words:
		bonus = min(4 * len(set(words)) + 4, 14)
		hit(min(best + bonus, 100), "scam-words", "also says " + ", ".join(sorted(set(words))[:5]))
	if suffix in SUFFIXES and "." in suffix and suffix.split(".")[-1] in ("app", "dev", "io", "me", "net", "com", "co", "sh", "goog", "new", "org"):
		hit(min(best + 4, 100), "free-host", f"on free hosting ({suffix})")
	return best, reasons


def severity(points):
	return "high" if points >= 85 else "medium" if points >= 70 else "low"


MIN_SCORE = 56
