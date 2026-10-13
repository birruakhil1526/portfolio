#!/usr/bin/env python3
"""Home control relay: runs on the VM behind nginx at /home/api/.

The browser cannot reach devices on the home WiFi, and the VM cannot either, so a bridge
(home/bridge.py) runs on a machine at home and connects *out* to this relay. The relay keeps the
latest device list the bridge posted, queues commands from the browser and hands them to the
bridge on its next long poll. Nothing is stored on disk; a restart only means logging in again.

Environment (from /etc/home-relay.env, never committed):
  HOME_PANEL_PASSWORD  what the /home/ page asks for
  HOME_NO_PASSWORD=1   test mode: anyone who opens /home/ can control the devices
  HOME_BRIDGE_TOKEN    what bridge.py sends
  HOME_RELAY_PORT      default 8787, bound to 127.0.0.1 only
  Google sign-in (needs HTTPS, see server/https-setup.sh):
  HOME_PUBLIC_URL      https://<name>.duckdns.org
  GOOGLE_CLIENT_ID     from Google Cloud Console > Google Auth Platform > Clients
  GOOGLE_CLIENT_SECRET
  HOME_ALLOWED_EMAILS  comma separated Google accounts that may sign in
"""
import base64
import hmac
import json
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PASSWORD = os.environ.get('HOME_PANEL_PASSWORD', '')
OPEN = os.environ.get('HOME_NO_PASSWORD') == '1'
BRIDGE_TOKEN = os.environ.get('HOME_BRIDGE_TOKEN', '')
PORT = int(os.environ.get('HOME_RELAY_PORT', '8787'))
PUBLIC_URL = os.environ.get('HOME_PUBLIC_URL', '').rstrip('/')
GOOGLE_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
ALLOWED = {e.strip().lower() for e in os.environ.get('HOME_ALLOWED_EMAILS', '').split(',') if e.strip()}
GOOGLE = bool(PUBLIC_URL.startswith('https://') and GOOGLE_ID and GOOGLE_SECRET and ALLOWED)
# overridable only so home/test_home.py can stand in for Google
GOOGLE_AUTH_URL = os.environ.get('GOOGLE_AUTH_URL', 'https://accounts.google.com/o/oauth2/v2/auth')
GOOGLE_TOKEN_URL = os.environ.get('GOOGLE_TOKEN_URL', 'https://oauth2.googleapis.com/token')
COOKIE = 'home_session'

SESSION_TTL = 30 * 86400      # a login lasts 30 days
CMD_TTL = 15                  # a command not picked up in 15 s is dropped, so the AC never turns on late
POLL_WAIT = 25                # bridge long poll; nginx proxy_read_timeout must be longer
ONLINE_WINDOW = 45            # bridge counts as online if it polled this recently
MAX_BODY = 256 * 1024
LOGIN_FAILS = 5               # per IP per 15 minutes
LOGIN_WINDOW = 900

lock = threading.Condition()
sessions = {}                 # token -> expiry
fails = {}                    # ip -> [timestamps]
queue = []                    # commands waiting for the bridge
results = {}                  # cmd id -> result
pending = {}                  # Google sign-in state -> (nonce, expiry)
bridge = {'seen': 0, 'version': '', 'host': '', 'devices': [], 'updated': 0}


def same(a, b):
	return bool(a) and bool(b) and hmac.compare_digest(a.encode(), b.encode())


class Handler(BaseHTTPRequestHandler):
	server_version = 'home-relay'
	sys_version = ''

	def log_message(self, fmt, *args):
		sys.stderr.write('%s %s\n' % (self.ip(), fmt % args))

	def ip(self):
		# nginx sets X-Real-IP; we only listen on 127.0.0.1 so the header cannot be spoofed from outside
		return self.headers.get('X-Real-IP') or self.client_address[0]

	def send(self, code, obj):
		body = json.dumps(obj).encode()
		self.send_response(code)
		self.send_header('Content-Type', 'application/json')
		self.send_header('Content-Length', str(len(body)))
		self.send_header('Cache-Control', 'no-store')
		self.end_headers()
		self.wfile.write(body)

	def body(self):
		n = int(self.headers.get('Content-Length') or 0)
		if n > MAX_BODY:
			raise ValueError('body too large')
		try:
			return json.loads(self.rfile.read(n) or b'{}')
		except json.JSONDecodeError:
			raise ValueError('bad json')

	def bearer(self):
		h = self.headers.get('Authorization', '')
		return h[7:] if h.startswith('Bearer ') else ''

	def cookie(self, name):
		for part in self.headers.get('Cookie', '').split(';'):
			k, _, v = part.strip().partition('=')
			if k == name:
				return v
		return ''

	def session(self):
		# the page sends a bearer token after a password login; Google sign-in sets an HttpOnly cookie
		for t in (self.bearer(), self.cookie(COOKIE)):
			if not t:
				continue
			with lock:
				exp = sessions.get(t)
				if exp and exp > time.time():
					return t
				sessions.pop(t, None)
		return ''

	def user_ok(self):
		if OPEN or self.bearer() and self.session() == self.bearer():
			return True
		if not self.session():
			return False
		# a cookie rides along on any request, so a write must come from our own page (SameSite=Lax covers most of it)
		if self.command == 'POST':
			origin = self.headers.get('Origin', '')
			return bool(PUBLIC_URL) and origin == PUBLIC_URL
		return True

	def login_needed(self):
		return self.send(401, {'error': 'login', 'google': GOOGLE, 'password': bool(PASSWORD), 'url': PUBLIC_URL if GOOGLE else ''})

	def redirect(self, location, cookie=None):
		self.send_response(302)
		self.send_header('Location', location)
		self.send_header('Cache-Control', 'no-store')
		self.send_header('Content-Length', '0')
		if cookie:
			self.send_header('Set-Cookie', cookie)
		self.end_headers()

	def path_only(self):
		p = self.path.split('?', 1)[0]
		return p[len('/home/api'):] if p.startswith('/home/api') else p

	def do_GET(self):
		p = self.path_only()
		if p == '/state':
			if not self.user_ok():
				return self.login_needed()
			with lock:
				return self.send(200, public_state())
		if p == '/auth/google':
			return self.google_start()
		if p == '/auth/callback':
			return self.google_callback()
		if p == '/bridge/poll':
			if not same(self.bearer(), BRIDGE_TOKEN):
				return self.send(401, {'error': 'bad bridge token'})
			return self.send(200, {'cmds': self.poll()})
		self.send(404, {'error': 'not found'})

	def do_POST(self):
		p = self.path_only()
		try:
			data = self.body()
		except ValueError as e:
			return self.send(400, {'error': str(e)})
		if p == '/login':
			return self.login(data)
		if p == '/logout':
			with lock:
				sessions.pop(self.bearer(), None)
				if not self.bearer() and self.user_ok():
					sessions.pop(self.cookie(COOKIE), None)
			body = b'{"ok": true}'
			self.send_response(200)
			self.send_header('Content-Type', 'application/json')
			self.send_header('Content-Length', str(len(body)))
			self.send_header('Set-Cookie', '%s=; Path=/home/; Max-Age=0; HttpOnly; Secure; SameSite=Lax' % COOKIE)
			self.end_headers()
			return self.wfile.write(body)
		if p == '/cmd':
			if not self.user_ok():
				return self.login_needed()
			return self.queue_command(data)
		if p.startswith('/bridge/'):
			if not same(self.bearer(), BRIDGE_TOKEN):
				return self.send(401, {'error': 'bad bridge token'})
			if p == '/bridge/devices':
				devices = data.get('devices')
				if not isinstance(devices, list):
					return self.send(400, {'error': 'devices must be a list'})
				with lock:
					bridge.update(devices=devices, updated=time.time(), seen=time.time(),
						version=str(data.get('version', ''))[:40], host=str(data.get('host', ''))[:80])
					lock.notify_all()
				return self.send(200, {'ok': True})
			if p == '/bridge/result':
				cid = str(data.get('id', ''))
				with lock:
					results[cid] = {'ok': bool(data.get('ok')), 'message': str(data.get('message', ''))[:500]}
					dev = data.get('device')
					if isinstance(dev, dict):
						bridge['devices'] = [dev if d.get('id') == dev.get('id') else d for d in bridge['devices']]
					lock.notify_all()
				return self.send(200, {'ok': True})
		self.send(404, {'error': 'not found'})

	def google_start(self):
		if not GOOGLE:
			return self.send(404, {'error': 'Google sign-in is not set up'})
		state, nonce, now = secrets.token_urlsafe(24), secrets.token_urlsafe(24), time.time()
		with lock:
			for k in [k for k, v in pending.items() if v[1] < now]:
				del pending[k]
			if len(pending) > 200:
				return self.send(429, {'error': 'too many sign-ins in progress'})
			pending[state] = (nonce, now + 600)
		q = urllib.parse.urlencode({'client_id': GOOGLE_ID, 'redirect_uri': PUBLIC_URL + '/home/api/auth/callback',
			'response_type': 'code', 'scope': 'openid email', 'state': state, 'nonce': nonce, 'prompt': 'select_account'})
		# the state cookie ties the callback to this browser, so a link someone else started cannot log you in
		self.redirect(GOOGLE_AUTH_URL + '?' + q,
			'home_oauth=%s; Path=/home/api/auth/; Max-Age=600; HttpOnly; Secure; SameSite=Lax' % state)

	def google_callback(self):
		def fail(why):
			self.log_message('google sign-in refused: %s', why)
			return self.redirect('/home/?login_error=' + urllib.parse.quote(why))
		if not GOOGLE:
			return fail('Google sign-in is not set up')
		q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
		state, code = (q.get('state') or [''])[0], (q.get('code') or [''])[0]
		with lock:
			entry = pending.pop(state, None)
		if not entry or entry[1] < time.time() or not same(state, self.cookie('home_oauth')):
			return fail('sign-in expired, try again')
		if not code:
			return fail('sign-in cancelled')
		try:
			req = urllib.request.Request(GOOGLE_TOKEN_URL, data=urllib.parse.urlencode({
				'code': code, 'client_id': GOOGLE_ID, 'client_secret': GOOGLE_SECRET,
				'redirect_uri': PUBLIC_URL + '/home/api/auth/callback', 'grant_type': 'authorization_code'}).encode())
			with urllib.request.urlopen(req, timeout=10) as r:
				tok = json.loads(r.read())
			# the token comes straight from Google over TLS, so its claims can be read without checking the signature
			payload = tok['id_token'].split('.')[1]
			claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
		except (OSError, urllib.error.URLError, ValueError, KeyError, IndexError) as e:
			return fail('could not reach Google (%s)' % type(e).__name__)
		email = str(claims.get('email', '')).lower()
		if claims.get('aud') != GOOGLE_ID or claims.get('iss') not in ('accounts.google.com', 'https://accounts.google.com'):
			return fail('token was not for this site')
		if claims.get('nonce') != entry[0] or float(claims.get('exp', 0)) < time.time():
			return fail('sign-in expired, try again')
		if not claims.get('email_verified') or email not in ALLOWED:
			return fail('%s is not allowed here' % (email or 'that account'))
		token = secrets.token_urlsafe(32)
		with lock:
			sessions[token] = time.time() + SESSION_TTL
		self.log_message('google sign-in: %s', email)
		self.redirect('/home/', '%s=%s; Path=/home/; Max-Age=%d; HttpOnly; Secure; SameSite=Lax' % (COOKIE, token, SESSION_TTL))

	def login(self, data):
		ip, now = self.ip(), time.time()
		if not PASSWORD and not OPEN:
			return self.send(401, {'error': 'password sign-in is off, use Google'})
		with lock:
			recent = [t for t in fails.get(ip, []) if now - t < LOGIN_WINDOW]
			fails[ip] = recent
			if len(recent) >= LOGIN_FAILS:
				return self.send(429, {'error': 'too many tries, wait 15 minutes'})
		if not OPEN and not same(str(data.get('password', '')), PASSWORD):
			with lock:
				fails[ip].append(now)
			time.sleep(1)
			return self.send(401, {'error': 'wrong password'})
		token = secrets.token_urlsafe(32)
		with lock:
			for t in [t for t, e in sessions.items() if e < now]:
				del sessions[t]
			sessions[token] = now + SESSION_TTL
		self.send(200, {'token': token})

	def queue_command(self, data):
		kind = data.get('type', 'control')
		if kind not in ('control', 'rescan'):
			return self.send(400, {'error': 'unknown command type'})
		cmd = {'id': secrets.token_hex(8), 'type': kind, 'at': time.time()}
		if kind == 'control':
			cmd.update(device=str(data.get('device', ''))[:200], control=str(data.get('control', ''))[:80],
				value=data.get('value'))
		with lock:
			if time.time() - bridge['seen'] > ONLINE_WINDOW:
				return self.send(503, {'error': 'bridge is offline: start bridge.py at home'})
			queue.append(cmd)
			lock.notify_all()
			deadline = time.time() + CMD_TTL + (20 if kind == 'rescan' else 0)
			while cmd['id'] not in results and time.time() < deadline:
				lock.wait(deadline - time.time())
			res = results.pop(cmd['id'], None)
			if cmd in queue:
				queue.remove(cmd)
		if res is None:
			return self.send(504, {'error': 'no answer from the bridge'})
		self.send(200 if res['ok'] else 502, res)

	def poll(self):
		deadline = time.time() + POLL_WAIT
		with lock:
			bridge['seen'] = time.time()
			while True:
				now = time.time()
				queue[:] = [c for c in queue if now - c['at'] < CMD_TTL]
				if queue or now >= deadline:
					out = queue[:]
					queue.clear()
					bridge['seen'] = now
					return out
				lock.wait(deadline - now)


def public_state():
	now = time.time()
	return {
		'bridge': {'online': now - bridge['seen'] < ONLINE_WINDOW, 'seen': bridge['seen'],
			'version': bridge['version'], 'host': bridge['host']},
		'devices': bridge['devices'], 'updated': bridge['updated'], 'now': now,
	}


def main():
	if len(BRIDGE_TOKEN) < 16:
		sys.exit('set HOME_BRIDGE_TOKEN (16+ chars)')
	if OPEN:
		print('HOME_NO_PASSWORD=1: /home/ is open to anyone', flush=True)
	elif PASSWORD and len(PASSWORD) < 8:
		sys.exit('HOME_PANEL_PASSWORD must be 8+ chars')
	elif not PASSWORD and not GOOGLE:
		sys.exit('set up Google sign-in (HOME_PUBLIC_URL, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, HOME_ALLOWED_EMAILS), '
			'HOME_PANEL_PASSWORD, or HOME_NO_PASSWORD=1 for test mode')
	if GOOGLE:
		print('Google sign-in for', ', '.join(sorted(ALLOWED)), flush=True)
	srv = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
	srv.daemon_threads = True
	print('home relay on 127.0.0.1:%d' % PORT, flush=True)
	srv.serve_forever()


if __name__ == '__main__':
	main()
