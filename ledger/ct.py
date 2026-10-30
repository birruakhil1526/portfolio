"""Certificate Transparency log readers.

Two log flavours are live in 2026:
  * RFC 6962 logs (Google Argon, Cloudflare Nimbus, ...): JSON get-sth / get-entries
  * static-ct-api "tiled" logs (Let's Encrypt Sycamore/Willow, ...): a text checkpoint plus
    256-entry data tiles fetched as plain files

Both yield the same thing to the rest of Ledger: (index, timestamp_ms, der_certificate).
"""
import base64
import concurrent.futures
import gzip
import json
import struct
import time
import urllib.request

from cryptography import x509
from cryptography.x509.oid import ExtensionOID, NameOID

UA = "Ledger/1.0 (+http://68.221.25.41/ledger/; CT monitor)"
TILE = 256


def fetch(url, timeout=20):
	req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
	with urllib.request.urlopen(req, timeout=timeout) as r:
		body = r.read()
		if r.headers.get("Content-Encoding") == "gzip" or body[:2] == b"\x1f\x8b":
			body = gzip.decompress(body)
		return body


class Reader:
	"""Common bookkeeping: where we are in the log and how fast it grows."""

	def __init__(self, name, url):
		self.name = name
		self.url = url.rstrip("/") + "/"
		self.size = 0        # tree size at the last checkpoint
		self.pos = None      # next index to read
		self.read = 0        # entries read since start
		self.errors = 0
		self.last_ok = 0.0
		self.last_error = ""

	def status(self):
		lag = self.size - self.pos if self.pos is not None else 0
		return {"name": self.name, "size": self.size, "pos": self.pos, "lag": max(lag, 0),
		        "read": self.read, "errors": self.errors, "last_ok": self.last_ok, "last_error": self.last_error}


class RFC6962(Reader):
	kind = "rfc6962"
	batch = 512
	# Google's logs hand out ~32 entries a request, slower than they grow; read pieces in parallel
	pieces = 8
	pool = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="ct")

	def tree_size(self):
		self.size = json.loads(fetch(self.url + "ct/v1/get-sth"))["tree_size"]
		return self.size

	def entries(self, start, end):
		"""Entries in [start, end), fetched as parallel pieces; stops at the first gap."""
		step = max(1, -(-(end - start) // self.pieces))
		jobs = [self.pool.submit(self.piece, a, min(a + step, end)) for a in range(start, end, step)]
		out = []
		for j in jobs:
			got = j.result()
			out.extend(got)
			if not got or got[-1][0] != min(got[0][0] + step, end) - 1:
				break
		return out

	def piece(self, start, end):
		out = []
		while start < end:
			got = self.page(start, end)
			if not got:
				break
			out.extend(got)
			start = got[-1][0] + 1
		return out

	def page(self, start, end):
		"""One get-entries call; logs may return fewer than asked."""
		url = f"{self.url}ct/v1/get-entries?start={start}&end={end - 1}"
		out = []
		for i, e in enumerate(json.loads(fetch(url))["entries"]):
			leaf = base64.b64decode(e["leaf_input"])
			ts = struct.unpack(">Q", leaf[2:10])[0]
			etype = struct.unpack(">H", leaf[10:12])[0]
			if etype == 0:   # x509_entry: the certificate is in the leaf
				n = int.from_bytes(leaf[12:15], "big")
				der = leaf[15:15 + n]
			else:            # precert_entry: the full precertificate heads extra_data
				extra = base64.b64decode(e["extra_data"])
				n = int.from_bytes(extra[0:3], "big")
				der = extra[3:3 + n]
			out.append((start + i, ts, der))
		return out


class Tiled(Reader):
	kind = "tiled"
	batch = TILE

	def tree_size(self):
		lines = fetch(self.url + "checkpoint").decode().split("\n")
		self.size = int(lines[1])
		return self.size

	@staticmethod
	def tile_path(n):
		# 1234067 -> x001/x234/067
		parts = []
		while True:
			parts.append(f"{n % 1000:03d}")
			n //= 1000
			if n == 0:
				break
		return "/".join(["x" + p for p in reversed(parts[1:])] + [parts[0]])

	def entries(self, start, end):
		"""Reads the single tile containing `start`; returns entries in [start, end)."""
		tile = start // TILE
		full = min(self.size - tile * TILE, TILE)
		path = "tile/data/" + self.tile_path(tile) + (f".p/{full}" if full < TILE else "")
		data = fetch(self.url + path)
		out, off, idx = [], 0, tile * TILE
		while off < len(data) and idx < tile * TILE + full:
			ts = struct.unpack(">Q", data[off:off + 8])[0]
			etype = struct.unpack(">H", data[off + 8:off + 10])[0]
			off += 10
			if etype == 0:
				n = int.from_bytes(data[off:off + 3], "big")
				der = data[off + 3:off + 3 + n]
				off += 3 + n
			else:
				off += 32                                     # issuer_key_hash
				n = int.from_bytes(data[off:off + 3], "big")  # TBSCertificate, not needed
				off += 3 + n
			ext = struct.unpack(">H", data[off:off + 2])[0]  # CtExtensions
			off += 2 + ext
			if etype == 1:                                    # PrecertificateExtraData
				n = int.from_bytes(data[off:off + 3], "big")
				der = data[off + 3:off + 3 + n]
				off += 3 + n
			chain = struct.unpack(">H", data[off:off + 2])[0]  # fingerprints
			off += 2 + chain
			if start <= idx < end:
				out.append((idx, ts, der))
			idx += 1
		return out


def names(der):
	"""DNS names and issuer organisation of a certificate; ([], '') if it won't parse."""
	try:
		cert = x509.load_der_x509_certificate(der)
	except Exception:
		return [], ""
	found = []
	try:
		san = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
		found = san.get_values_for_type(x509.DNSName)
	except Exception:
		pass
	if not found:
		try:
			found = [a.value for a in cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)]
		except Exception:
			pass
	issuer = ""
	try:
		attrs = cert.issuer.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)
		issuer = attrs[0].value if attrs else ""
	except Exception:
		pass
	seen, clean = set(), []
	for n in found:
		n = str(n).strip().lower().rstrip(".")
		if n.startswith("*."):
			n = n[2:]
		if n and n not in seen:
			seen.add(n)
			clean.append(n)
	return clean, issuer


LOGS = [
	# tiled: Let's Encrypt issues most certificates on the web, and most phishing padlocks
	Tiled("Let's Encrypt Sycamore", "https://mon.sycamore.ct.letsencrypt.org/2026h2/"),
	Tiled("Let's Encrypt Willow", "https://mon.willow.ct.letsencrypt.org/2026h2/"),
	# RFC 6962: where most other CAs (Google Trust Services, Sectigo, DigiCert, ...) log
	RFC6962("Google Argon", "https://ct.googleapis.com/logs/us1/argon2026h2/"),
	RFC6962("Cloudflare Nimbus", "https://ct.cloudflare.com/logs/nimbus2026/"),
]


if __name__ == "__main__":
	# smoke test: read the newest entries of each log and print a few names
	for log in LOGS:
		t = time.time()
		size = log.tree_size()
		got = log.entries(size - 40, size)
		took = time.time() - t
		print(f"{log.name}: size={size} got={len(got)} in {took:.2f}s")
		for idx, ts, der in got[:4]:
			print("   ", idx, ts, names(der))
