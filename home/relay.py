#!/usr/bin/env python3
"""Home control relay: runs on the VM behind nginx at /home/api/.

The browser cannot reach devices on the home WiFi, and the VM cannot either, so a bridge
(site/home/bridge.py) runs on a machine at home and connects *out* to this relay. The relay keeps
the latest device list each bridge posted, queues commands from the browser and hands them to that
bridge on its next long poll.

Every account is its own home: signing up on /home/ creates an access key (to log in) and a bridge
token (for bridge.py), and a key only ever sees and controls the devices of its own bridge.
Accounts are kept in HOME_RELAY_DATA as SHA-256 hashes of the keys; device lists stay in memory.

Environment (from /etc/home-relay.env, never committed):
  HOME_BRIDGE_TOKEN    optional: bridge token of the owner's home, which existed before sign-up
  HOME_PANEL_PASSWORD  optional: password that also opens the owner's home
  HOME_NO_PASSWORD=1   test mode: anyone without a key lands in the owner's home
  HOME_SIGNUP=0        turn off new sign-ups (default on)
  HOME_RELAY_DATA      default /var/lib/home-relay/accounts.json
  HOME_RELAY_PORT      default 8787, bound to 127.0.0.1 only
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PASSWORD = os.environ.get('HOME_PANEL_PASSWORD', '')
OPEN = os.environ.get('HOME_NO_PASSWORD') == '1'
OWNER_BRIDGE = os.environ.get('HOME_BRIDGE_TOKEN', '')
SIGNUP = os.environ.get('HOME_SIGNUP', '1') != '0'
DATA = os.environ.get('HOME_RELAY_DATA', '/var/lib/home-relay/accounts.json')
PORT = int(os.environ.get('HOME_RELAY_PORT', '8787'))

SESSION_TTL = 30 * 86400      # a password login lasts 30 days
CMD_TTL = 15                  # a command not picked up in 15 s is dropped, so the AC never turns on late
POLL_WAIT = 25                # bridge long poll; nginx proxy_read_timeout must be longer
ONLINE_WINDOW = 45            # bridge counts as online if it polled this recently
MAX_BODY = 256 * 1024
LOGIN_FAILS = 5               # per IP per 15 minutes
LOGIN_WINDOW = 900
SIGNUPS_PER_IP = 3            # per hour
MAX_ACCOUNTS = 100
OWNER = 'owner'

lock = threading.Condition()
sessions = {}                 # password session token -> (home id, expiry)
fails = {}                    # ip -> [timestamps]
signups = {}                  # ip -> [timestamps]
accounts = {}                 # home id -> {name, key, bridge, created}; key and bridge are sha256 hex
homes = {}                    # home id -> runtime state, see home()


def same(a, b):
	return bool(a) and bool(b) and hmac.compare_digest(a.encode(), b.encode())


def digest(token):
	return hashlib.sha256(token.encode()).hexdigest()


def home(hid):
	if hid not in homes:
		homes[hid] = {'queue': [], 'results': {}, 'seen': 0, 'version': '', 'host': '', 'devices': [], 'updated': 0}
	return homes[hid]


def load_accounts():
	try:
		with open(DATA) as f:
			accounts.update(json.load(f))
	except FileNotFoundError:
		pass


def save_accounts():
	os.makedirs(os.path.dirname(DATA), exist_ok=True)
	tmp = DATA + '.tmp'
	with open(tmp, 'w') as f:
		json.dump(accounts, f, indent=1)
	os.chmod(tmp, 0o600)
	os.replace(tmp, DATA)


def home_for_key(token):
	if not token:
		return None
	h = digest(token)
	return next((hid for hid, a in accounts.items() if hmac.compare_digest(a['key'], h)), None)


def home_for_bridge(token):
	if not token:
		return None
	if same(token, OWNER_BRIDGE):
		return OWNER
	h = digest(token)
	return next((hid for hid, a in accounts.items() if hmac.compare_digest(a['bridge'], h)), None)


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

	def user_home(self):
		"""which home this browser may control: by access key, password session, or test mode"""
		t = self.bearer()
		with lock:
			hid = home_for_key(t)
			if hid:
				return hid
			s = sessions.get(t)
			if s and s[1] > time.time():
				return s[0]
			sessions.pop(t, None)
		return OWNER if OPEN else None

	def login_needed(self):
		return self.send(401, {'error': 'login', 'signup': SIGNUP, 'password': bool(PASSWORD)})

	def path_only(self):
		p = self.path.split('?', 1)[0]
		return p[len('/home/api'):] if p.startswith('/home/api') else p

	def do_GET(self):
		p = self.path_only()
		if p == '/state':
			hid = self.user_home()
			if not hid:
				return self.login_needed()
			with lock:
				return self.send(200, public_state(hid))
		if p == '/bridge/poll':
			hid = home_for_bridge(self.bearer())
			if not hid:
				return self.send(401, {'error': 'bad bridge token'})
			return self.send(200, {'cmds': self.poll(hid)})
		self.send(404, {'error': 'not found'})

	def do_POST(self):
		p = self.path_only()
		try:
			data = self.body()
		except ValueError as e:
			return self.send(400, {'error': str(e)})
		if p == '/login':
			return self.login(data)
		if p == '/signup':
			return self.signup(data)
		if p == '/logout':
			with lock:
				sessions.pop(self.bearer(), None)
			return self.send(200, {'ok': True})
		if p == '/cmd':
			hid = self.user_home()
			if not hid:
				return self.login_needed()
			return self.queue_command(hid, data)
		if p.startswith('/bridge/'):
			hid = home_for_bridge(self.bearer())
			if not hid:
				return self.send(401, {'error': 'bad bridge token'})
			if p == '/bridge/devices':
				devices = data.get('devices')
				if not isinstance(devices, list):
					return self.send(400, {'error': 'devices must be a list'})
				with lock:
					home(hid).update(devices=devices, updated=time.time(), seen=time.time(),
						version=str(data.get('version', ''))[:40], host=str(data.get('host', ''))[:80])
					lock.notify_all()
				return self.send(200, {'ok': True})
			if p == '/bridge/result':
				cid = str(data.get('id', ''))
				with lock:
					h = home(hid)
					h['results'][cid] = {'ok': bool(data.get('ok')), 'message': str(data.get('message', ''))[:500]}
					dev = data.get('device')
					if isinstance(dev, dict):
						h['devices'] = [dev if d.get('id') == dev.get('id') else d for d in h['devices']]
					lock.notify_all()
				return self.send(200, {'ok': True})
		self.send(404, {'error': 'not found'})

	def limited(self, table, limit, window):
		now = time.time()
		with lock:
			table[self.ip()] = [t for t in table.get(self.ip(), []) if now - t < window]
			return len(table[self.ip()]) >= limit

	def login(self, data):
		"""one box on the page: an access key from sign-up, or the owner's password"""
		if self.limited(fails, LOGIN_FAILS, LOGIN_WINDOW):
			return self.send(429, {'error': 'too many tries, wait 15 minutes'})
		secret = str(data.get('password', '')).strip()
		with lock:
			hid = home_for_key(secret)
			name = accounts[hid]['name'] if hid else ''
		if hid:
			return self.send(200, {'token': secret, 'name': name})
		if same(secret, PASSWORD):
			token, now = secrets.token_urlsafe(32), time.time()
			with lock:
				for t in [t for t, s in sessions.items() if s[1] < now]:
					del sessions[t]
				sessions[token] = (OWNER, now + SESSION_TTL)
			return self.send(200, {'token': token, 'name': 'owner'})
		with lock:
			fails[self.ip()].append(time.time())
		time.sleep(1)
		self.send(401, {'error': 'that key is not right'})

	def signup(self, data):
		if not SIGNUP:
			return self.send(403, {'error': 'sign-up is closed'})
		name = re.sub(r'\s+', ' ', str(data.get('name', ''))).strip()[:40]
		if not name:
			return self.send(400, {'error': 'type a name for your home'})
		if self.limited(signups, SIGNUPS_PER_IP, 3600):
			return self.send(429, {'error': 'too many sign-ups from here, try again in an hour'})
		key, bridge_token = 'hk_' + secrets.token_urlsafe(18), 'hb_' + secrets.token_urlsafe(32)
		with lock:
			if len(accounts) >= MAX_ACCOUNTS:
				return self.send(503, {'error': 'no room for new homes right now'})
			hid = secrets.token_hex(6)
			accounts[hid] = {'name': name, 'key': digest(key), 'bridge': digest(bridge_token), 'created': int(time.time())}
			signups[self.ip()].append(time.time())
			save_accounts()
		self.log_message('signup: %s', hid)
		# the only time these are shown: only their hashes are kept
		self.send(200, {'token': key, 'bridge_token': bridge_token, 'name': name})

	def queue_command(self, hid, data):
		kind = data.get('type', 'control')
		if kind not in ('control', 'rescan'):
			return self.send(400, {'error': 'unknown command type'})
		cmd = {'id': secrets.token_hex(8), 'type': kind, 'at': time.time()}
		if kind == 'control':
			cmd.update(device=str(data.get('device', ''))[:200], control=str(data.get('control', ''))[:80],
				value=data.get('value'))
		with lock:
			h = home(hid)
			if time.time() - h['seen'] > ONLINE_WINDOW:
				return self.send(503, {'error': 'bridge is offline: start bridge.py at home'})
			h['queue'].append(cmd)
			lock.notify_all()
			deadline = time.time() + CMD_TTL + (20 if kind == 'rescan' else 0)
			while cmd['id'] not in h['results'] and time.time() < deadline:
				lock.wait(deadline - time.time())
			res = h['results'].pop(cmd['id'], None)
			if cmd in h['queue']:
				h['queue'].remove(cmd)
		if res is None:
			return self.send(504, {'error': 'no answer from the bridge'})
		self.send(200 if res['ok'] else 502, res)

	def poll(self, hid):
		deadline = time.time() + POLL_WAIT
		with lock:
			h = home(hid)
			h['seen'] = time.time()
			while True:
				now = time.time()
				h['queue'][:] = [c for c in h['queue'] if now - c['at'] < CMD_TTL]
				if h['queue'] or now >= deadline:
					out = h['queue'][:]
					h['queue'].clear()
					h['seen'] = now
					return out
				lock.wait(deadline - now)


def public_state(hid):
	h, now = home(hid), time.time()
	return {
		'home': 'owner' if hid == OWNER else accounts.get(hid, {}).get('name', ''),
		'bridge': {'online': now - h['seen'] < ONLINE_WINDOW, 'seen': h['seen'], 'version': h['version'], 'host': h['host']},
		'devices': h['devices'], 'updated': h['updated'], 'now': now,
	}


def main():
	if OWNER_BRIDGE and len(OWNER_BRIDGE) < 16:
		sys.exit('HOME_BRIDGE_TOKEN must be 16+ chars')
	if PASSWORD and len(PASSWORD) < 8:
		sys.exit('HOME_PANEL_PASSWORD must be 8+ chars')
	load_accounts()
	if OPEN:
		print('HOME_NO_PASSWORD=1: visitors without a key land in the owner home', flush=True)
	print('%d accounts, sign-up %s' % (len(accounts), 'on' if SIGNUP else 'off'), flush=True)
	srv = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
	srv.daemon_threads = True
	print('home relay on 127.0.0.1:%d' % PORT, flush=True)
	srv.serve_forever()


if __name__ == '__main__':
	main()
