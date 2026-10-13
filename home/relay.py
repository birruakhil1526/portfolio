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
"""
import hmac
import json
import os
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PASSWORD = os.environ.get('HOME_PANEL_PASSWORD', '')
OPEN = os.environ.get('HOME_NO_PASSWORD') == '1'
BRIDGE_TOKEN = os.environ.get('HOME_BRIDGE_TOKEN', '')
PORT = int(os.environ.get('HOME_RELAY_PORT', '8787'))

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

	def user_ok(self):
		if OPEN:
			return True
		t = self.bearer()
		with lock:
			exp = sessions.get(t)
			if exp and exp > time.time():
				return True
			sessions.pop(t, None)
		return False

	def path_only(self):
		p = self.path.split('?', 1)[0]
		return p[len('/home/api'):] if p.startswith('/home/api') else p

	def do_GET(self):
		p = self.path_only()
		if p == '/state':
			if not self.user_ok():
				return self.send(401, {'error': 'login'})
			with lock:
				return self.send(200, public_state())
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
			return self.send(200, {'ok': True})
		if p == '/cmd':
			if not self.user_ok():
				return self.send(401, {'error': 'login'})
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

	def login(self, data):
		ip, now = self.ip(), time.time()
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
	elif len(PASSWORD) < 8:
		sys.exit('set HOME_PANEL_PASSWORD (8+ chars), or HOME_NO_PASSWORD=1 for test mode')
	srv = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
	srv.daemon_threads = True
	print('home relay on 127.0.0.1:%d' % PORT, flush=True)
	srv.serve_forever()


if __name__ == '__main__':
	main()
