"""Ledger: watches Certificate Transparency logs for lookalikes of the brands it guards.

One process, standard library plus `cryptography`:
  * a reader thread per CT log tails the newest certificates
  * every hostname is scored against the watched brands (match.py)
  * matches land in SQLite and stream to browsers over Server-Sent Events
  * a small JSON API behind nginx serves the landing page and the console

Run: LEDGER_DB=./ledger.db python3 ledger/ledger.py   (listens on 127.0.0.1:8790)
"""
import collections
import csv
import hashlib
import io
import json
import os
import queue
import random
import re
import sqlite3
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ct  # noqa: E402
import match  # noqa: E402

DB = os.environ.get("LEDGER_DB", "/var/lib/ledger/ledger.db")
HOST = os.environ.get("LEDGER_HOST", "127.0.0.1")
PORT = int(os.environ.get("LEDGER_PORT", "8790"))
IST = timezone(timedelta(hours=5, minutes=30))

RECENT = 150_000        # hostnames kept in memory for instant backfill (about 20 minutes)
MAX_STREAMS = 150       # concurrent browsers on the live stream
TRIAL_TTL = 30 * 60     # a visitor's watch lasts half an hour
MAX_TRIALS = 60
FIREHOSE_PER_SEC = 14   # sampled certificates pushed to each browser

SEED = [
	("paypal", "PayPal", ["paypal.com", "paypal.me", "paypalobjects.com", "paypal-community.com"]),
	("netflix", "Netflix", ["netflix.com", "netflix.net", "nflxvideo.net", "nflximg.net", "nflxext.com"]),
	("metamask", "MetaMask", ["metamask.io", "metamask.app.link"]),
	("coinbase", "Coinbase", ["coinbase.com", "coinbase.net", "cbhq.net"]),
	("paytm", "Paytm", ["paytm.com", "paytmbank.com", "paytmmall.com", "paytmmoney.com", "paytm.in", "paytmpayments.com"]),
	("phonepe", "PhonePe", ["phonepe.com"]),
	("binance", "Binance", ["binance.com", "binance.us", "binance.org", "binance.vision", "binance.info"]),
]


def now():
	return time.time()


def today():
	return datetime.now(IST).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- storage

class Store:
	def __init__(self, path):
		os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
		self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
		self.lock = threading.Lock()
		with self.lock:
			self.db.execute("PRAGMA journal_mode=WAL")
			self.db.execute("PRAGMA synchronous=NORMAL")
			self.db.executescript("""
				CREATE TABLE IF NOT EXISTS brands(
					id INTEGER PRIMARY KEY, term TEXT UNIQUE NOT NULL, label TEXT NOT NULL,
					official TEXT NOT NULL DEFAULT '[]', keywords TEXT NOT NULL DEFAULT '[]',
					webhook TEXT NOT NULL DEFAULT '', public INTEGER NOT NULL DEFAULT 1, created REAL);
				CREATE TABLE IF NOT EXISTS hits(
					id INTEGER PRIMARY KEY, brand_id INTEGER NOT NULL, domain TEXT NOT NULL,
					score INTEGER, severity TEXT, reasons TEXT, issuer TEXT, log TEXT, idx INTEGER,
					logged REAL, first_seen REAL, last_seen REAL, seen INTEGER DEFAULT 1,
					status TEXT NOT NULL DEFAULT 'new', note TEXT NOT NULL DEFAULT '',
					UNIQUE(brand_id, domain));
				CREATE INDEX IF NOT EXISTS hits_recent ON hits(first_seen DESC);
				CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
			""")
			if not self.db.execute("SELECT 1 FROM brands LIMIT 1").fetchone():
				for term, label, official in SEED:
					self.db.execute("INSERT INTO brands(term,label,official,created) VALUES(?,?,?,?)",
					                (term, label, json.dumps(official), now()))

	def q(self, sql, args=()):
		with self.lock:
			cur = self.db.execute(sql, args)
			cols = [c[0] for c in cur.description] if cur.description else []
			return [dict(zip(cols, r)) for r in cur.fetchall()]

	def x(self, sql, args=()):
		with self.lock:
			cur = self.db.execute(sql, args)
			return cur.lastrowid, cur.rowcount

	def kv_get(self, k, default=None):
		r = self.q("SELECT v FROM kv WHERE k=?", (k,))
		return json.loads(r[0]["v"]) if r else default

	def kv_set(self, k, v):
		self.x("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))

	def brands(self):
		rows = self.q("SELECT * FROM brands ORDER BY label COLLATE NOCASE")
		for r in rows:
			r["official"] = json.loads(r["official"])
			r["keywords"] = json.loads(r["keywords"])
			r["public"] = bool(r["public"])
		return rows

	def record_hit(self, brand_id, domain, points, reasons, issuer, log, idx, logged):
		"""True when this (brand, domain) is new."""
		t = now()
		with self.lock:
			cur = self.db.execute(
				"UPDATE hits SET last_seen=?, seen=seen+1, score=MAX(score, ?) WHERE brand_id=? AND domain=?",
				(t, points, brand_id, domain))
			if cur.rowcount:
				return None
			cur = self.db.execute(
				"INSERT INTO hits(brand_id,domain,score,severity,reasons,issuer,log,idx,logged,first_seen,last_seen)"
				" VALUES(?,?,?,?,?,?,?,?,?,?,?)",
				(brand_id, domain, points, match.severity(points), json.dumps(reasons), issuer, log, idx, logged, t, t))
			return cur.lastrowid


# ---------------------------------------------------------------- live fan-out

class Client:
	def __init__(self, trial=None):
		self.q = queue.Queue(maxsize=400)
		self.trial = trial

	def send(self, event, data):
		try:
			self.q.put_nowait((event, data))
		except queue.Full:
			pass


class Hub:
	def __init__(self):
		self.clients = set()
		self.lock = threading.Lock()
		self.bucket = FIREHOSE_PER_SEC
		self.bucket_t = now()

	def add(self, c):
		with self.lock:
			if len(self.clients) >= MAX_STREAMS:
				return False
			self.clients.add(c)
			return True

	def remove(self, c):
		with self.lock:
			self.clients.discard(c)

	def count(self):
		return len(self.clients)

	def broadcast(self, event, data, trial=None):
		with self.lock:
			targets = list(self.clients)
		for c in targets:
			if trial is None or c.trial == trial:
				c.send(event, data)

	def firehose(self, data):
		"""Sampled: browsers can't usefully show 100+ certificates a second."""
		t = now()
		self.bucket = min(FIREHOSE_PER_SEC, self.bucket + (t - self.bucket_t) * FIREHOSE_PER_SEC)
		self.bucket_t = t
		if self.bucket >= 1 and self.clients:
			self.bucket -= 1
			self.broadcast("cert", data)


# ---------------------------------------------------------------- the engine

class Ledger:
	def __init__(self, store):
		self.store = store
		self.hub = Hub()
		self.lock = threading.Lock()
		self.recent = collections.deque(maxlen=RECENT)
		self.seen = collections.OrderedDict()
		self.trials = {}
		self.started = now()
		self.per_sec = collections.deque(maxlen=61)   # [second, certificates]
		self.delays = collections.deque(maxlen=2000)  # seconds from log timestamp to us
		self.issuers = collections.Counter()
		c = store.kv_get("counters", {})
		self.total = c.get("total", 0)
		self.day = c.get("day", today())
		self.day_certs = c.get("day_certs", 0) if self.day == today() else 0
		self.day_hits = c.get("day_hits", 0) if self.day == today() else 0
		self.reload_brands()

	# brands ------------------------------------------------------------
	def reload_brands(self):
		rows = self.store.brands()
		self.brand_rows = {r["id"]: r for r in rows}
		self.watched = [match.Brand(r["term"], r["official"], r["keywords"], id=r["id"], label=r["label"]) for r in rows]

	def trial_brands(self):
		t = now()
		with self.lock:
			for k in [k for k, v in self.trials.items() if v["expires"] < t]:
				del self.trials[k]
			return [(k, v["brand"]) for k, v in self.trials.items()]

	# ingest ------------------------------------------------------------
	def tick(self, n=1):
		sec = int(now())
		with self.lock:
			if self.per_sec and self.per_sec[-1][0] == sec:
				self.per_sec[-1][1] += n
			else:
				self.per_sec.append([sec, n])
			d = today()
			if d != self.day:
				self.day, self.day_certs, self.day_hits = d, 0, 0
			self.day_certs += n
			self.total += n

	def rate(self):
		cut = int(now()) - 60
		with self.lock:
			n = sum(c for s, c in self.per_sec if cut <= s < int(now()))
		return round(n / 60, 1)

	def process(self, log, idx, ts, der):
		hosts, issuer = ct.names(der)
		if not hosts:
			return
		issuer = sys.intern(issuer)
		key = hashlib.blake2b((issuer + "|" + ",".join(sorted(hosts[:30]))).encode(), digest_size=10).digest()
		with self.lock:
			if key in self.seen:   # the same certificate from another log, or its precertificate
				self.seen.move_to_end(key)
				return
			self.seen[key] = 1
			if len(self.seen) > 250_000:
				self.seen.popitem(last=False)
		self.tick()
		logged = ts / 1000
		self.delays.append(max(0.0, now() - logged))
		self.issuers[issuer or "Unknown"] += 1
		hosts = hosts[:100]
		for h in hosts:
			self.recent.append((logged, h, issuer, log.name))
		self.hub.firehose({"d": hosts[0], "n": len(hosts), "i": issuer, "l": log.name, "t": int(ts)})

		for b in self.watched:
			best = self.best(hosts, b)
			if best:
				h, pts, reasons = best
				hid = self.store.record_hit(b.id, h, pts, reasons, issuer, log.name, idx, logged)
				if hid:
					with self.lock:
						self.day_hits += 1
					row = self.brand_rows.get(b.id, {})
					data = {"id": hid, "d": h, "b": b.label, "s": pts, "sev": match.severity(pts),
					        "r": reasons, "i": issuer, "l": log.name, "t": int(ts)}
					if row.get("public"):
						self.hub.broadcast("hit", data)
					if row.get("webhook") and pts >= 70:
						threading.Thread(target=self.webhook, args=(row, data), daemon=True).start()
		for token, b in self.trial_brands():
			best = self.best(hosts, b)
			if best:
				h, pts, reasons = best
				self.hub.broadcast("watch", {"d": h, "b": b.label, "s": pts, "sev": match.severity(pts),
				                             "r": reasons, "i": issuer, "l": log.name, "t": int(ts)}, trial=token)

	@staticmethod
	def best(hosts, brand):
		top = None
		for h in hosts:
			pts, reasons = match.score(h, brand)
			if pts >= match.MIN_SCORE and (not top or pts > top[1]):
				top = (h, pts, reasons)
		return top

	def follow(self, log):
		"""Tail one log forever, staying near its head."""
		backoff = 2
		while True:
			try:
				if log.pos is None:
					log.pos = max(log.tree_size() - 512, 0)
				if log.pos >= log.size:
					time.sleep(4)
					log.tree_size()
					continue
				if log.size - log.pos > 60_000:   # fell far behind (restart, outage): jump to the head
					log.pos = log.size - 1024
				got = log.entries(log.pos, min(log.pos + log.batch, log.size))
				if not got:
					time.sleep(2)
					log.tree_size()
					continue
				for idx, ts, der in got:
					self.process(log, idx, ts, der)
				log.pos = got[-1][0] + 1
				log.read += len(got)
				log.last_ok = now()
				backoff = 2
			except Exception as e:
				log.errors += 1
				log.last_error = f"{type(e).__name__}: {e}"[:200]
				time.sleep(backoff)
				backoff = min(backoff * 2, 120)

	def persist(self):
		while True:
			time.sleep(30)
			with self.lock:
				c = {"total": self.total, "day": self.day, "day_certs": self.day_certs, "day_hits": self.day_hits}
			try:
				self.store.kv_set("counters", c)
			except Exception:
				pass

	def pulse(self):
		while True:
			time.sleep(2)
			if self.hub.count():
				self.hub.broadcast("stats", self.stats(brief=True))

	def start(self):
		for log in ct.LOGS:
			threading.Thread(target=self.follow, args=(log,), daemon=True, name=log.name).start()
		threading.Thread(target=self.persist, daemon=True).start()
		threading.Thread(target=self.pulse, daemon=True).start()

	# views -------------------------------------------------------------
	def stats(self, brief=False):
		d = sorted(self.delays)
		with self.lock:
			out = {"rate": 0, "total": self.total, "today": self.day_certs, "hits_today": self.day_hits,
			       "watching": len(self.watched), "viewers": self.hub.count(),
			       "delay": round(d[len(d) // 2], 1) if d else None}
		out["rate"] = self.rate()
		if brief:
			return out
		out["uptime"] = int(now() - self.started)
		out["logs"] = [dict(l.status(), kind=l.kind) for l in ct.LOGS]
		out["issuers"] = [{"name": k, "n": v} for k, v in self.issuers.most_common(6)]
		out["brands"] = [{"term": r["term"], "label": r["label"]} for r in self.brand_rows.values() if r["public"]]
		return out

	def watch(self, term, ip):
		term = re.sub(r"[^a-z0-9-]", "", match.skeleton(term.strip().lower()))[:32]
		if len(term.replace("-", "")) < 3:
			raise ValueError("Use at least 3 letters or digits.")
		t = now()
		with self.lock:
			mine = [k for k, v in self.trials.items() if v["ip"] == ip and v["expires"] > t]
			for k in mine[:-2]:            # each visitor keeps their newest three
				del self.trials[k]
			if len(self.trials) >= MAX_TRIALS:
				oldest = min(self.trials, key=lambda k: self.trials[k]["expires"])
				del self.trials[oldest]
			token = hashlib.blake2b(os.urandom(16), digest_size=12).hexdigest()
			brand = match.Brand(term.replace("-", ""), label=term)
			self.trials[token] = {"brand": brand, "ip": ip, "expires": t + TRIAL_TTL}
			snapshot = list(self.recent)
		found, seen = [], set()
		for logged, h, issuer, logname in reversed(snapshot):
			if h in seen:
				continue
			pts, reasons = match.score(h, brand)
			if pts >= match.MIN_SCORE:
				seen.add(h)
				found.append({"d": h, "b": term, "s": pts, "sev": match.severity(pts), "r": reasons,
				              "i": issuer, "l": logname, "t": int(logged * 1000)})
				if len(found) >= 60:
					break
		window = int(t - snapshot[0][0]) if snapshot else 0
		return {"token": token, "term": term, "expires": int(t + TRIAL_TTL), "backfill": found,
		        "scanned": len(snapshot), "window": window}

	def webhook(self, brand, hit):
		text = (f"Ledger: {hit['sev'].upper()} lookalike of {brand['label']}: {hit['d']} "
		        f"(score {hit['s']}, issued by {hit['i'] or 'unknown CA'}) https://crt.sh/?q={hit['d']}")
		body = json.dumps({"text": text, "content": text, "ledger": hit}).encode()
		try:
			req = urllib.request.Request(brand["webhook"], data=body, method="POST",
			                             headers={"Content-Type": "application/json", "User-Agent": ct.UA})
			urllib.request.urlopen(req, timeout=8).read()
			return True, "delivered"
		except Exception as e:
			return False, f"{type(e).__name__}: {e}"[:200]


def takedown(hit, brand):
	reasons = "\n".join(f"  - {r['detail']}" for r in json.loads(hit["reasons"] or "[]"))
	seen = datetime.fromtimestamp(hit["logged"] or hit["first_seen"], IST).strftime("%d %b %Y, %H:%M IST")
	return f"""Subject: Phishing / brand impersonation report: {hit['domain']}

To the abuse team,

We are writing on behalf of {brand['label']} about the domain below, which imitates our brand
and appears to be set up for phishing our customers.

Domain:            {hit['domain']}
TLS certificate:   issued by {hit['issuer'] or 'unknown CA'}, logged {seen}
                   in Certificate Transparency log {hit['log']} (entry {hit['idx']})
Certificate record: https://crt.sh/?q={hit['domain']}
Our official domains: {', '.join(brand['official']) or '(listed on our website)'}

Why we believe it impersonates {brand['label']}:
{reasons}

{brand['label']} has not authorised this domain. We ask that you suspend the domain and any
hosting or certificate associated with it, and preserve related records.

Regards,
{brand['label']} brand protection
"""


# ---------------------------------------------------------------- HTTP

class Limiter:
	def __init__(self, per_minute):
		self.rate = per_minute / 60
		self.cap = per_minute
		self.b = {}
		self.lock = threading.Lock()

	def ok(self, key):
		t = now()
		with self.lock:
			tokens, last = self.b.get(key, (self.cap, t))
			tokens = min(self.cap, tokens + (t - last) * self.rate)
			if tokens < 1:
				self.b[key] = (tokens, t)
				return False
			self.b[key] = (tokens - 1, t)
			if len(self.b) > 20_000:
				self.b.clear()
			return True


WATCH_LIMIT = Limiter(6)
SCORE_LIMIT = Limiter(90)
STATUSES = {"new", "reviewing", "takedown", "resolved", "dismissed"}


class Handler(BaseHTTPRequestHandler):
	server_version = "Ledger"
	sys_version = ""
	protocol_version = "HTTP/1.1"
	app: Ledger = None

	def log_message(self, *a):
		pass

	@property
	def ip(self):
		return self.headers.get("X-Real-IP") or self.client_address[0]

	@property
	def admin(self):
		return bool(self.headers.get("X-Remote-User"))

	def reply(self, status, obj=None, ctype="application/json", raw=None):
		body = raw if raw is not None else json.dumps(obj, separators=(",", ":")).encode()
		self.send_response(status)
		self.send_header("Content-Type", ctype)
		self.send_header("Content-Length", str(len(body)))
		self.send_header("Cache-Control", "no-store")
		self.end_headers()
		self.wfile.write(body)

	def body(self):
		n = int(self.headers.get("Content-Length") or 0)
		if n > 64_000:
			raise ValueError("Body too large.")
		return json.loads(self.rfile.read(n) or b"{}") if n else {}

	def do_GET(self):
		try:
			self.route("GET")
		except (BrokenPipeError, ConnectionResetError):
			pass
		except Exception as e:
			self.reply(500, {"error": f"{type(e).__name__}"})

	def do_POST(self):
		try:
			self.route("POST")
		except ValueError as e:
			self.reply(400, {"error": str(e)})
		except Exception as e:
			self.reply(500, {"error": f"{type(e).__name__}"})

	def do_DELETE(self):
		try:
			self.route("DELETE")
		except Exception as e:
			self.reply(500, {"error": f"{type(e).__name__}"})

	def route(self, method):
		u = urlparse(self.path)
		p = u.path.rstrip("/")
		qs = {k: v[0] for k, v in parse_qs(u.query).items()}
		app = self.app
		if p.startswith("/api/admin"):
			if not self.admin:
				return self.reply(403, {"error": "Sign in to the console."})
			return self.route_admin(method, p[len("/api/admin"):], qs)

		if method == "GET" and p == "/api/stats":
			return self.reply(200, app.stats())
		if method == "GET" and p == "/api/stream":
			return self.stream(qs.get("w"))
		if method == "GET" and p == "/api/hits":
			limit = max(1, min(int(qs.get("limit", 30)), 100))
			rows = app.store.q(
				"SELECT h.id, h.domain d, b.label b, h.score s, h.severity sev, h.reasons r, h.issuer i, h.log l,"
				" CAST(h.logged*1000 AS INTEGER) t FROM hits h JOIN brands b ON b.id=h.brand_id"
				" WHERE b.public=1 ORDER BY h.first_seen DESC LIMIT ?", (limit,))
			for r in rows:
				r["r"] = json.loads(r["r"] or "[]")
			return self.reply(200, rows)
		if method == "GET" and p == "/api/score":
			if not SCORE_LIMIT.ok(self.ip):
				return self.reply(429, {"error": "Slow down a little."})
			d = (qs.get("d") or "").strip().lower()[:253]
			b = (qs.get("b") or "").strip().lower()[:32]
			if not d or not b:
				return self.reply(400, {"error": "Give a domain and a brand."})
			d = re.sub(r"^[a-z]+://", "", d).split("/")[0]
			try:
				d = d.encode("idna").decode("ascii") if any(ord(c) > 127 for c in d) else d
			except Exception:
				pass
			brand = match.Brand(b, [re.sub(r"[^a-z0-9-]", "", b) + ".com"])   # assume the .com is the real one
			pts, reasons = match.score(d, brand)
			uni = match.to_unicode(d)
			sub, label, suffix = match.split_host(uni)
			return self.reply(200, {"domain": d, "unicode": uni, "brand": brand.term, "score": pts,
			                        "severity": match.severity(pts) if pts >= match.MIN_SCORE else "clear",
			                        "reasons": reasons, "skeleton": match.skeleton(uni),
			                        "parts": {"sub": sub, "label": label, "suffix": suffix}})
		if method == "POST" and p == "/api/watch":
			if not WATCH_LIMIT.ok(self.ip):
				return self.reply(429, {"error": "That's a lot of watches. Try again in a few minutes."})
			return self.reply(200, app.watch(str(self.body().get("term", "")), self.ip))
		return self.reply(404, {"error": "Not found."})

	def stream(self, trial):
		if trial and trial not in self.app.trials:
			trial = None
		c = Client(trial)
		if not self.app.hub.add(c):
			return self.reply(503, {"error": "The live stream is full right now."})
		self.send_response(200)
		self.send_header("Content-Type", "text/event-stream")
		self.send_header("Cache-Control", "no-store")
		self.send_header("X-Accel-Buffering", "no")
		self.send_header("Connection", "keep-alive")
		self.end_headers()
		try:
			self.wfile.write(b"retry: 3000\n" + self.event("stats", self.app.stats(brief=True)))
			self.wfile.flush()
			while True:
				try:
					event, data = c.q.get(timeout=15)
					chunk = [self.event(event, data)]
					while len(chunk) < 50:
						try:
							chunk.append(self.event(*c.q.get_nowait()))
						except queue.Empty:
							break
					self.wfile.write(b"".join(chunk))
				except queue.Empty:
					self.wfile.write(b": keep-alive\n\n")
				self.wfile.flush()
		except (BrokenPipeError, ConnectionResetError, OSError):
			pass
		finally:
			self.app.hub.remove(c)
			self.close_connection = True

	@staticmethod
	def event(name, data):
		return f"event: {name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()

	def route_admin(self, method, p, qs):
		app, store = self.app, self.app.store
		if method == "GET" and p == "/me":
			return self.reply(200, {"user": self.headers.get("X-Remote-User")})
		if method == "GET" and p == "/brands":
			rows = store.brands()
			counts = {r["brand_id"]: r for r in store.q(
				"SELECT brand_id, COUNT(*) n, SUM(status='new') open, SUM(severity='high') high,"
				" MAX(first_seen) last FROM hits GROUP BY brand_id")}
			for r in rows:
				c = counts.get(r["id"], {})
				r.update(hits=c.get("n", 0), open=c.get("open", 0) or 0, high=c.get("high", 0) or 0, last=c.get("last"))
			return self.reply(200, rows)
		if method == "POST" and p == "/brands":
			b = self.body()
			term = re.sub(r"[^a-z0-9]", "", match.skeleton(str(b.get("term", "")).lower()))[:32]
			if len(term) < 3:
				raise ValueError("The brand term needs at least 3 letters or digits.")
			label = str(b.get("label") or term).strip()[:60]
			official = [d.strip().lower() for d in b.get("official", []) if d.strip()][:50]
			keywords = [k.strip().lower() for k in b.get("keywords", []) if k.strip()][:50]
			webhook = str(b.get("webhook") or "").strip()[:500]
			if webhook and not webhook.startswith("https://"):
				raise ValueError("Webhooks must be https:// URLs.")
			args = (term, label, json.dumps(official), json.dumps(keywords), webhook, int(bool(b.get("public", True))))
			try:
				if b.get("id"):
					store.x("UPDATE brands SET term=?,label=?,official=?,keywords=?,webhook=?,public=? WHERE id=?", args + (int(b["id"]),))
				else:
					store.x("INSERT INTO brands(term,label,official,keywords,webhook,public,created) VALUES(?,?,?,?,?,?,?)", args + (now(),))
			except sqlite3.IntegrityError:
				raise ValueError(f"'{term}' is already watched.")
			app.reload_brands()
			return self.reply(200, {"ok": True})
		m = re.fullmatch(r"/brands/(\d+)", p)
		if method == "DELETE" and m:
			store.x("DELETE FROM hits WHERE brand_id=?", (int(m[1]),))
			store.x("DELETE FROM brands WHERE id=?", (int(m[1]),))
			app.reload_brands()
			return self.reply(200, {"ok": True})
		m = re.fullmatch(r"/brands/(\d+)/test", p)
		if method == "POST" and m:
			row = app.brand_rows.get(int(m[1]))
			if not row or not row.get("webhook"):
				raise ValueError("Add a webhook URL first.")
			ok, msg = app.webhook(row, {"id": 0, "d": f"test-{row['term']}-verify.example", "b": row["label"], "s": 90,
			                            "sev": "high", "r": [], "i": "Test CA", "l": "test", "t": int(now() * 1000)})
			return self.reply(200 if ok else 502, {"ok": ok, "message": msg})
		if method == "GET" and p in ("/hits", "/export.csv"):
			where, args = ["1=1"], []
			if qs.get("brand"):
				where.append("h.brand_id=?"); args.append(int(qs["brand"]))
			if qs.get("status") in STATUSES:
				where.append("h.status=?"); args.append(qs["status"])
			elif qs.get("status") == "open":
				where.append("h.status IN ('new','reviewing','takedown')")
			if qs.get("severity") in ("high", "medium", "low"):
				where.append("h.severity=?"); args.append(qs["severity"])
			if qs.get("q"):
				where.append("h.domain LIKE ?"); args.append(f"%{qs['q'].lower()}%")
			sql = (" FROM hits h JOIN brands b ON b.id=h.brand_id WHERE " + " AND ".join(where))
			if p == "/export.csv":
				rows = store.q("SELECT h.domain, b.label brand, h.score, h.severity, h.status, h.issuer, h.log, h.idx,"
				               " datetime(h.first_seen,'unixepoch') first_seen_utc, h.note" + sql + " ORDER BY h.first_seen DESC LIMIT 50000", args)
				buf = io.StringIO()
				w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["domain"])
				w.writeheader()
				w.writerows(rows)
				return self.reply(200, raw=buf.getvalue().encode(), ctype="text/csv; charset=utf-8")
			limit = max(1, min(int(qs.get("limit", 50)), 200))
			offset = max(0, int(qs.get("offset", 0)))
			total = store.q("SELECT COUNT(*) n" + sql, args)[0]["n"]
			rows = store.q("SELECT h.*, b.label brand" + sql + " ORDER BY h.first_seen DESC LIMIT ? OFFSET ?", args + [limit, offset])
			for r in rows:
				r["reasons"] = json.loads(r["reasons"] or "[]")
			return self.reply(200, {"total": total, "rows": rows})
		m = re.fullmatch(r"/hits/(\d+)", p)
		if method == "POST" and m:
			b = self.body()
			if b.get("status") and b["status"] not in STATUSES:
				raise ValueError("Unknown status.")
			if "status" in b:
				store.x("UPDATE hits SET status=? WHERE id=?", (b["status"], int(m[1])))
			if "note" in b:
				store.x("UPDATE hits SET note=? WHERE id=?", (str(b["note"])[:2000], int(m[1])))
			return self.reply(200, {"ok": True})
		m = re.fullmatch(r"/hits/(\d+)/takedown", p)
		if method == "GET" and m:
			rows = store.q("SELECT * FROM hits WHERE id=?", (int(m[1]),))
			if not rows:
				return self.reply(404, {"error": "Not found."})
			brand = app.brand_rows.get(rows[0]["brand_id"])
			return self.reply(200, {"text": takedown(rows[0], brand)})
		return self.reply(404, {"error": "Not found."})


def main():
	store = Store(DB)
	app = Ledger(store)
	app.start()
	Handler.app = app
	srv = ThreadingHTTPServer((HOST, PORT), Handler)
	srv.daemon_threads = True
	print(f"ledger on http://{HOST}:{PORT} db={DB}", flush=True)
	srv.serve_forever()


if __name__ == "__main__":
	main()
