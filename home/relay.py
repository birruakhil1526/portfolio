#!/usr/bin/env python3
"""Home control relay: runs on the VM behind nginx at /home/api/.

The browser cannot reach devices on the home WiFi, and the VM cannot either, so a bridge
(site/home/bridge.py) runs on a machine at home and connects *out* to this relay. The relay keeps
the latest device list each bridge posted, queues commands from the browser and hands them to that
bridge on its next long poll.

Cloud appliances need no bridge: a home can link SmartThings (Samsung) and LG ThinQ on the page, and
the relay then talks to those vendor clouds itself, using the drivers from bridge.py. The bridge is
only needed for devices that are reachable on the home WiFi alone (TVs over LAN, Wake-on-LAN).

Every account is its own home: signing up on /home/ creates an access key (to log in) and a bridge
token (for bridge.py), and a key only ever sees and controls the devices of its own home.
Accounts are kept in HOME_RELAY_DATA as SHA-256 hashes of the keys; device lists stay in memory.
Cloud links are kept next to it in links.json (mode 600): those tokens have to be usable, so they
are stored as they are.

Environment (from /etc/home-relay.env, never committed):
  HOME_BRIDGE_TOKEN    optional: bridge token of the owner's home, which existed before sign-up
  HOME_PANEL_PASSWORD  optional: password that also opens the owner's home
  HOME_NO_PASSWORD=1   test mode: anyone without a key lands in the owner's home
  HOME_SIGNUP=0        turn off new sign-ups (default on)
  HOME_RELAY_DATA      default /var/lib/home-relay/accounts.json
  HOME_RELAY_PORT      default 8787, bound to 127.0.0.1 only
  HOME_ST_CLIENT_ID, HOME_ST_CLIENT_SECRET
                       optional SmartThings OAuth app: enables "Connect SmartThings" with tokens that
                       renew themselves (without it, a 24-hour personal token can be pasted instead)
  HOME_PUBLIC_URL      default http://68.221.25.41, used for the SmartThings redirect address
"""
import base64
import hashlib
import hmac
import importlib.util
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PASSWORD = os.environ.get('HOME_PANEL_PASSWORD', '')
OPEN = os.environ.get('HOME_NO_PASSWORD') == '1'
OWNER_BRIDGE = os.environ.get('HOME_BRIDGE_TOKEN', '')
SIGNUP = os.environ.get('HOME_SIGNUP', '1') != '0'
DATA = os.environ.get('HOME_RELAY_DATA', '/var/lib/home-relay/accounts.json')
PORT = int(os.environ.get('HOME_RELAY_PORT', '8787'))
LINKS = os.path.join(os.path.dirname(DATA), 'links.json')
ST_CLIENT_ID = os.environ.get('HOME_ST_CLIENT_ID', '')
ST_CLIENT_SECRET = os.environ.get('HOME_ST_CLIENT_SECRET', '')
ST_OAUTH = os.environ.get('HOME_ST_OAUTH', 'https://api.smartthings.com/v1/oauth')
ST_SCOPES = 'r:devices:* x:devices:* r:locations:*'
PUBLIC_URL = os.environ.get('HOME_PUBLIC_URL', 'http://68.221.25.41').rstrip('/')
ST_REDIRECT = PUBLIC_URL + '/home/api/st/callback'

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
CLOUD_FRESH = 20              # re-read cloud devices at most this often, and only while a page is open
OAUTH_TTL = 600
CLOUDS = {'st:': 'smartthings', 'lg:': 'thinq'}   # device id prefix -> linked cloud

lock = threading.Condition()
sessions = {}                 # password session token -> (home id, expiry)
fails = {}                    # ip -> [timestamps]
signups = {}                  # ip -> [timestamps]
accounts = {}                 # home id -> {name, key, bridge, created}; key and bridge are sha256 hex
homes = {}                    # home id -> runtime state, see home()
links = {}                    # home id -> {cloud name: tokens}, see link_*()
clouds = {}                   # home id -> cloud devices and driver objects, see cloud()
oauth_states = {}             # SmartThings sign-in in progress: state -> (home id, expiry)
cloud_lock = threading.Lock() # links and clouds; never held during a network call
st_lock = threading.Lock()    # SmartThings refresh tokens are single use, so one refresh at a time


def load_drivers():
	"""the cloud drivers live in bridge.py, installed next to this file or found in the repo"""
	here = os.path.dirname(os.path.abspath(__file__))
	for path in (os.path.join(here, 'bridge.py'), os.path.join(here, '..', 'site', 'home', 'bridge.py')):
		if os.path.exists(path):
			spec = importlib.util.spec_from_file_location('bridge', path)
			mod = importlib.util.module_from_spec(spec)
			spec.loader.exec_module(mod)
			mod.log = lambda *a: print(*a, file=sys.stderr, flush=True)
			return mod
	sys.exit('bridge.py not found next to relay.py')


drivers = load_drivers()


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


def load_links():
	try:
		with open(LINKS) as f:
			links.update(json.load(f))
	except FileNotFoundError:
		pass


def save_links():
	os.makedirs(os.path.dirname(LINKS), exist_ok=True)
	tmp = LINKS + '.tmp'
	with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
		json.dump(links, f, indent=1)
	os.replace(tmp, LINKS)


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


# ---------------------------------------------------------------- cloud appliances, no bridge needed

def cloud(hid):
	return clouds.setdefault(hid, {'clients': {}, 'devices': [], 'errors': {}, 'at': 0, 'busy': False})


def st_token(form):
	"""SmartThings OAuth token request: a sign-in code or a refresh token in, fresh tokens out"""
	body = urllib.parse.urlencode(dict(form, client_id=ST_CLIENT_ID)).encode()
	auth = base64.b64encode(('%s:%s' % (ST_CLIENT_ID, ST_CLIENT_SECRET)).encode()).decode()
	try:
		r = drivers.http('POST', ST_OAUTH + '/token', body=body, timeout=12, headers={
			'Authorization': 'Basic ' + auth, 'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'})
	except urllib.error.HTTPError as e:
		raise ValueError('SmartThings: ' + drivers.cloud_error(e)) from None
	if not isinstance(r, dict) or not r.get('access_token'):
		raise ValueError('SmartThings sent no token')
	return {'kind': 'oauth', 'access': r['access_token'], 'refresh': r.get('refresh_token', ''),
		'expires': time.time() + int(r.get('expires_in') or 86000)}


def st_access(hid):
	"""a SmartThings access token for this home, renewed a few minutes before it runs out"""
	with st_lock:
		link = links.get(hid, {}).get('smartthings')
		if not link:
			raise ValueError('SmartThings is not connected')
		if link.get('refresh') and time.time() > link['expires'] - 300:
			fresh = st_token({'grant_type': 'refresh_token', 'refresh_token': link['refresh']})
			with cloud_lock:
				link.update(fresh)
				save_links()
		return link['access']


def client_for(hid, svc):
	c, link = cloud(hid), links.get(hid, {}).get(svc)
	if not link:
		raise ValueError('%s is not connected' % svc)
	client = c['clients'].get(svc)
	if svc == 'smartthings':
		client = client or drivers.SmartThings('')
		client.h = {'Authorization': 'Bearer ' + st_access(hid)}
	elif svc == 'thinq':
		# keeps the cached device profiles until the token changes
		if not client or client.token != link['token']:
			client = drivers.ThinQ(link['token'], link['country'], link['client'])
	with cloud_lock:
		c['clients'][svc] = client
	return client


def refresh_cloud(hid):
	c = cloud(hid)
	devices, errors = [], {}
	try:
		for svc in list(links.get(hid, {})):
			try:
				devices += client_for(hid, svc).devices()
			except Exception as e:  # one broken cloud must not hide the others
				errors[svc] = str(e)[:300]
				devices += [d for d in c['devices'] if d.get('driver') == svc]
	finally:
		with cloud_lock:
			c.update(devices=devices, errors=errors, at=time.time(), busy=False)
	return devices


def refresh_soon(hid):
	"""re-reads cloud devices in the background when the page asks for state and the copy is stale"""
	c = cloud(hid)
	with cloud_lock:
		if not links.get(hid) or c['busy'] or time.time() - c['at'] < CLOUD_FRESH:
			return
		c['busy'] = True
	threading.Thread(target=refresh_cloud, args=(hid,), daemon=True).start()


def run_cloud(hid, data):
	did = str(data.get('device', ''))
	svc, c = CLOUDS[did[:3]], cloud(hid)
	dev = next((d for d in c['devices'] if d['id'] == did), None)
	if not dev:
		raise ValueError('unknown device; tap Rescan')
	control = next((x for x in dev['controls'] if x['id'] == data.get('control')), None)
	value = drivers.check_value(control, data.get('value'))
	client = client_for(hid, svc)
	message = client.run(dev, control['id'], value)
	time.sleep(1)
	try:
		dev = client.refresh(dev)
		with cloud_lock:
			c['devices'] = [dev if d['id'] == dev['id'] else d for d in c['devices']]
	except Exception as e:
		drivers.log('refresh after command failed:', e)
	return {'ok': True, 'message': message, 'device': dev}


def is_cloud_device(hid, did):
	return isinstance(did, str) and CLOUDS.get(did[:3]) in links.get(hid, {})


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
			refresh_soon(hid)
			with lock:
				return self.send(200, public_state(hid))
		if p == '/st/callback':
			return self.st_callback()
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
		if p == '/cmd' or p.startswith('/links/'):
			hid = self.user_home()
			if not hid:
				return self.login_needed()
			if p == '/cmd':
				return self.queue_command(hid, data)
			try:
				if p == '/links/thinq':
					return self.send(200, link_thinq(hid, data))
				if p == '/links/smartthings':
					return self.send(200, link_st_token(hid, data))
				if p == '/links/smartthings/start':
					return self.send(200, st_start(hid))
				if p == '/links/remove':
					return self.send(200, unlink(hid, str(data.get('service', ''))))
			except (ValueError, OSError) as e:
				return self.send(400, {'error': str(e)[:300]})
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

	def redirect(self, query):
		self.send_response(302)
		self.send_header('Location', '/home/?' + urllib.parse.urlencode(query))
		self.send_header('Content-Length', '0')
		self.end_headers()

	def st_callback(self):
		"""SmartThings sends the browser back here after the user allowed (or refused) access"""
		q = urllib.parse.parse_qs(self.path.partition('?')[2])
		state = (q.get('state') or [''])[0]
		with cloud_lock:
			hid, expires = oauth_states.pop(state, (None, 0))
		if not hid or expires < time.time():
			return self.redirect({'link_error': 'That SmartThings sign-in expired, connect again.'})
		code = (q.get('code') or [''])[0]
		if not code:
			return self.redirect({'link_error': 'SmartThings access was not allowed.'})
		try:
			tokens = st_token({'grant_type': 'authorization_code', 'code': code, 'redirect_uri': ST_REDIRECT})
		except (ValueError, OSError) as e:
			return self.redirect({'link_error': str(e)[:200]})
		store_link(hid, 'smartthings', dict(tokens, linked=time.time()))
		self.log_message('smartthings linked: %s', hid)
		self.redirect({'linked': 'smartthings'})

	def queue_command(self, hid, data):
		kind = data.get('type', 'control')
		if kind not in ('control', 'rescan'):
			return self.send(400, {'error': 'unknown command type'})
		if kind == 'control' and is_cloud_device(hid, data.get('device')):
			try:
				return self.send(200, run_cloud(hid, data))
			except (ValueError, OSError, KeyError, TypeError) as e:
				return self.send(502, {'ok': False, 'message': str(e)[:300]})
		cloud_note = ''
		if kind == 'rescan' and links.get(hid):
			with cloud_lock:
				cloud(hid)['busy'] = True
			cloud_note = '%d cloud devices' % len(refresh_cloud(hid))
			with lock:
				bridge_off = time.time() - home(hid)['seen'] > ONLINE_WINDOW
			if bridge_off:
				return self.send(200, {'ok': True, 'message': 'found ' + cloud_note})
		cmd = {'id': secrets.token_hex(8), 'type': kind, 'at': time.time()}
		if kind == 'control':
			cmd.update(device=str(data.get('device', ''))[:200], control=str(data.get('control', ''))[:80],
				value=data.get('value'))
		with lock:
			h = home(hid)
			if time.time() - h['seen'] > ONLINE_WINDOW:
				return self.send(503, {'error': 'this device needs the bridge at home, and it is offline'})
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
		if cloud_note and res['ok']:
			res['message'] += ', and ' + cloud_note
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


def store_link(hid, svc, value):
	with cloud_lock:
		links.setdefault(hid, {})[svc] = value
		cloud(hid)['clients'].pop(svc, None)
		cloud(hid)['at'] = 0
		save_links()


def link_thinq(hid, data):
	token = str(data.get('token', '')).strip()
	country = str(data.get('country', '')).strip().upper()
	if not re.fullmatch(r'[A-Z]{2}', country):
		raise ValueError('pick the country your LG account is in')
	if not 20 <= len(token) <= 500:
		raise ValueError('paste the whole LG personal access token')
	client_id = links.get(hid, {}).get('thinq', {}).get('client') or 'birru-home-' + secrets.token_hex(8)
	n = len(drivers.ThinQ(token, country, client_id).call('GET', '/devices') or [])
	store_link(hid, 'thinq', {'token': token, 'country': country, 'client': client_id})
	return {'ok': True, 'message': 'LG ThinQ connected: %d appliance%s' % (n, '' if n == 1 else 's')}


def link_st_token(hid, data):
	"""a personal access token: works at once, but SmartThings makes new ones expire after 24 hours"""
	token = str(data.get('token', '')).strip()
	if not 20 <= len(token) <= 500:
		raise ValueError('paste the whole SmartThings token')
	n = len(drivers.SmartThings(token).get('/devices').get('items', []))
	store_link(hid, 'smartthings', {'kind': 'token', 'access': token, 'linked': time.time()})
	return {'ok': True, 'message': 'SmartThings connected: %d device%s' % (n, '' if n == 1 else 's')}


def st_start(hid):
	if not (ST_CLIENT_ID and ST_CLIENT_SECRET):
		raise ValueError('SmartThings sign-in is not set up on this server; paste a token instead')
	state, now = secrets.token_urlsafe(24), time.time()
	with cloud_lock:
		for k in [k for k, v in oauth_states.items() if v[1] < now]:
			del oauth_states[k]
		oauth_states[state] = (hid, now + OAUTH_TTL)
	return {'url': ST_OAUTH + '/authorize?' + urllib.parse.urlencode({'client_id': ST_CLIENT_ID, 'response_type': 'code',
		'redirect_uri': ST_REDIRECT, 'scope': ST_SCOPES, 'state': state})}


def unlink(hid, svc):
	with cloud_lock:
		if svc not in links.get(hid, {}):
			raise ValueError('not connected')
		del links[hid][svc]
		c = cloud(hid)
		c['clients'].pop(svc, None)
		c['devices'] = [d for d in c['devices'] if d.get('driver') != svc]
		c['errors'].pop(svc, None)
		save_links()
	return {'ok': True, 'message': 'disconnected'}


def public_state(hid):
	h, c, now = home(hid), cloud(hid), time.time()
	linked = links.get(hid, {})
	ids = {d['id'] for d in c['devices']}
	# a cloud linked here wins over the same cloud configured in bridge.py
	devices = c['devices'] + [d for d in h['devices'] if d.get('id') not in ids and d.get('driver') not in linked]
	return {
		'home': 'owner' if hid == OWNER else accounts.get(hid, {}).get('name', ''),
		'bridge': {'online': now - h['seen'] < ONLINE_WINDOW, 'seen': h['seen'], 'version': h['version'], 'host': h['host']},
		'links': {svc: {'kind': l.get('kind', ''), 'error': c['errors'].get(svc, ''),
			'since': l.get('linked', 0)} for svc, l in linked.items()},
		'loading': bool(linked) and not c['at'],
		'st_signin': bool(ST_CLIENT_ID and ST_CLIENT_SECRET),
		'devices': devices, 'updated': h['updated'], 'now': now,
	}


def main():
	if OWNER_BRIDGE and len(OWNER_BRIDGE) < 16:
		sys.exit('HOME_BRIDGE_TOKEN must be 16+ chars')
	if PASSWORD and len(PASSWORD) < 8:
		sys.exit('HOME_PANEL_PASSWORD must be 8+ chars')
	load_accounts()
	load_links()
	if OPEN:
		print('HOME_NO_PASSWORD=1: visitors without a key land in the owner home', flush=True)
	print('%d accounts, sign-up %s' % (len(accounts), 'on' if SIGNUP else 'off'), flush=True)
	srv = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
	srv.daemon_threads = True
	print('home relay on 127.0.0.1:%d' % PORT, flush=True)
	srv.serve_forever()


if __name__ == '__main__':
	main()
