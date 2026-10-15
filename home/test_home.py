#!/usr/bin/env python3
"""End-to-end check of the home control path, no real devices needed:
page API -> relay -> bridge -> fake Roku (HTTP) and fake Samsung TV (WebSocket) on localhost, and
page API -> relay -> fake SmartThings and LG ThinQ clouds, with no bridge involved."""
import base64
import hashlib
import importlib.util
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
got = {'roku': [], 'samsung': [], 'st': [], 'st_token': [], 'lg': []}


def free_port():
	with socket.socket() as s:
		s.bind(('127.0.0.1', 0))
		return s.getsockname()[1]


class FakeRoku(BaseHTTPRequestHandler):
	def log_message(self, *a): pass

	def do_POST(self):
		got['roku'].append(self.path)
		self.send_response(200)
		self.send_header('Content-Length', '0')
		self.end_headers()


class FakeSamsung(BaseHTTPRequestHandler):
	def log_message(self, *a): pass

	def do_GET(self):
		if self.headers.get('Upgrade', '').lower() != 'websocket':
			body = json.dumps({'device': {'name': 'Test TV', 'modelName': 'QA55', 'wifiMac': 'aa:bb:cc:dd:ee:ff', 'TokenAuthSupport': 'false'}}).encode()
			self.send_response(200)
			self.send_header('Content-Length', str(len(body)))
			self.end_headers()
			return self.wfile.write(body)
		accept = base64.b64encode(hashlib.sha1((self.headers['Sec-WebSocket-Key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
		self.wfile.write(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n' % accept).encode())
		msg = json.dumps({'event': 'ms.channel.connect', 'data': {}}).encode()
		self.wfile.write(bytes([0x81, len(msg)]) + msg)
		self.wfile.flush()
		b1, b2 = self.rfile.read(2)
		n = b2 & 0x7F
		if n == 126:
			n = struct.unpack('!H', self.rfile.read(2))[0]
		mask = self.rfile.read(4)
		data = bytes(b ^ mask[i % 4] for i, b in enumerate(self.rfile.read(n)))
		got['samsung'].append(json.loads(data)['params']['DataOfCmd'])
		self.close_connection = True


LG_PROFILES = {
	'a1': {'operation': {'airConOperationMode': {'type': 'enum', 'mode': ['r', 'w'], 'value': {'r': ['POWER_ON', 'POWER_OFF'], 'w': ['POWER_ON', 'POWER_OFF']}}},
		'airConJobMode': {'currentJobMode': {'type': 'enum', 'mode': ['r', 'w'], 'value': {'r': ['COOL', 'FAN'], 'w': ['COOL', 'FAN']}}},
		'temperatureInUnits': [{'unit': 'C', 'targetTemperature': {'type': 'range', 'mode': ['r', 'w'], 'value': {'w': {'min': 18, 'max': 30, 'step': 1}}}}],
		'timer': {'relativeHourToStop': {'type': 'range', 'mode': ['r', 'w'], 'value': {'w': {'min': 0, 'max': 24}}}}},
	'w1': {'runState': {'currentState': {'type': 'enum', 'mode': ['r'], 'value': {'r': ['RUNNING', 'END']}}},
		'operation': {'washerOperationMode': {'type': 'enum', 'mode': ['w'], 'value': {'w': ['START', 'STOP', 'POWER_OFF']}}}},
}
LG_STATE = {
	'a1': {'operation': {'airConOperationMode': 'POWER_OFF'}, 'airConJobMode': {'currentJobMode': 'COOL'},
		'temperatureInUnits': [{'unit': 'C', 'currentTemperature': 29, 'targetTemperature': 24}, {'unit': 'F', 'targetTemperature': 75}]},
	'w1': {'runState': {'currentState': 'RUNNING'}},
}
ST_AC = {'deviceId': 'ac9', 'label': 'Bedroom AC', 'manufacturerName': 'Samsung', 'components': [{'id': 'main',
	'capabilities': [{'id': 'switch'}, {'id': 'thermostatCoolingSetpoint'}, {'id': 'temperatureMeasurement'}],
	'categories': [{'name': 'AirConditioner'}]}]}


class FakeClouds(BaseHTTPRequestHandler):
	"""SmartThings under /st, LG ThinQ under /lg"""
	def log_message(self, *a): pass

	def reply(self, code, obj):
		body = json.dumps(obj).encode()
		self.send_response(code)
		self.send_header('Content-Type', 'application/json')
		self.send_header('Content-Length', str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def body(self):
		return self.rfile.read(int(self.headers.get('Content-Length') or 0))

	def st_ok(self):
		return self.headers.get('Authorization') in ('Bearer access-1', 'Bearer access-2')

	def lg_ok(self):
		h = self.headers
		return h.get('Authorization') == 'Bearer lg-' + 'p' * 30 and h.get('x-country') == 'IN' and h.get('x-api-key') and h.get('x-client-id') and h.get('x-message-id')

	def do_GET(self):
		p = self.path
		if p.startswith('/st/'):
			if not self.st_ok():
				return self.reply(401, {'error': {'message': 'bad token'}})
			if p == '/st/v1/devices':
				return self.reply(200, {'items': [ST_AC]})
			if p == '/st/v1/devices/ac9/status':
				return self.reply(200, {'components': {'main': {'switch': {'switch': {'value': 'off'}},
					'thermostatCoolingSetpoint': {'coolingSetpoint': {'value': 25}}, 'temperatureMeasurement': {'temperature': {'value': 31}}}}})
			if p == '/st/v1/devices/ac9':
				return self.reply(200, ST_AC)
		if p.startswith('/lg/'):
			if not self.lg_ok():
				return self.reply(401, {'error': {'code': '1218', 'message': 'invalid token'}})
			if p == '/lg/devices':
				return self.reply(200, {'response': [{'deviceId': 'a1', 'deviceInfo': {'deviceType': 'DEVICE_AIR_CONDITIONER', 'alias': 'Hall AC', 'modelName': 'RS-Q19'}},
					{'deviceId': 'w1', 'deviceInfo': {'deviceType': 'DEVICE_WASHER', 'alias': 'Washer'}}]})
			parts = p.split('/')
			if len(parts) == 5 and parts[4] == 'profile':
				return self.reply(200, {'response': {'property': LG_PROFILES[parts[3]]}})
			if len(parts) == 5 and parts[4] == 'state':
				return self.reply(200, {'response': LG_STATE[parts[3]]})
		self.reply(404, {'error': 'not found'})

	def do_POST(self):
		p, raw = self.path, self.body()
		if p == '/st/oauth/token':
			form = dict(x.split('=', 1) for x in raw.decode().split('&'))
			if self.headers.get('Authorization') != 'Basic ' + base64.b64encode(b'st-client:st-secret').decode():
				return self.reply(401, {'error': 'bad client'})
			got['st_token'].append(form['grant_type'])
			if form['grant_type'] == 'authorization_code' and form.get('code') == 'good-code':
				# expires inside the relay's 5-minute margin, so the next call must refresh it
				return self.reply(200, {'access_token': 'access-1', 'refresh_token': 'refresh-1', 'expires_in': 200})
			if form['grant_type'] == 'refresh_token' and form.get('refresh_token') == 'refresh-1':
				return self.reply(200, {'access_token': 'access-2', 'refresh_token': 'refresh-2', 'expires_in': 86399})
			return self.reply(400, {'error': 'invalid_grant'})
		if p == '/st/v1/devices/ac9/commands' and self.st_ok():
			got['st'].append((self.headers['Authorization'], json.loads(raw)['commands'][0]))
			return self.reply(200, {'results': []})
		if p.startswith('/lg/devices/') and p.endswith('/control') and self.lg_ok():
			got['lg'].append((p.split('/')[3], json.loads(raw), self.headers.get('x-conditional-control')))
			return self.reply(200, {'response': {}})
		self.reply(404, {'error': 'not found'})


class NoRedirect(urllib.request.HTTPRedirectHandler):
	def redirect_request(self, *a):
		return None


def serve(handler, port):
	srv = ThreadingHTTPServer(('127.0.0.1', port), handler)
	threading.Thread(target=srv.serve_forever, daemon=True).start()


def call(base, path, body=None, token=''):
	req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
		headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, method='POST' if body is not None else 'GET')
	try:
		with urllib.request.urlopen(req, timeout=30) as r:
			return r.status, json.loads(r.read())
	except urllib.error.HTTPError as e:
		return e.code, json.loads(e.read())


def wait_for(base, tok, name):
	for _ in range(100):
		code, s = call(base, '/state', token=tok)
		dev = next((d for d in s.get('devices', []) if d['name'] == name), None)
		if dev:
			return s, dev
		time.sleep(0.1)
	raise AssertionError('%s never showed up: %s' % (name, s))


def check_clouds(base, owner, friend, env):
	"""cloud appliances: linked on the page, controlled by the relay itself, no bridge involved"""
	assert call(base, '/links/thinq', {'token': 'lg-' + 'p' * 30, 'country': 'IN'})[0] == 401, 'linking needs a login'
	assert call(base, '/links/thinq', {'token': 'lg-' + 'p' * 30, 'country': 'India'}, owner)[0] == 400, 'country must be a code'
	code, r = call(base, '/links/thinq', {'token': 'lg-' + 'q' * 30, 'country': 'IN'}, owner)
	assert code == 400 and 'expired' in r['error'], 'a bad LG token must be refused when linking: %s' % r
	code, r = call(base, '/links/thinq', {'token': 'lg-' + 'p' * 30, 'country': 'IN'}, owner)
	assert code == 200 and '2 appliances' in r['message'], r
	s, ac = wait_for(base, owner, 'Hall AC')
	assert s['links']['thinq']['error'] == '', s['links']
	assert ac['kind'] == 'ac' and ac['controls'][0]['label'] == 'Power', ac['controls']
	ids = {c['id']: c for c in ac['controls']}
	assert ids['temperatureInUnits.targetTemperature']['value'] == 24 and ids['temperatureInUnits.targetTemperature']['min'] == 18
	assert ids['room_temp']['value'] == 29 and ids['airConJobMode.currentJobMode']['options'] == ['COOL', 'FAN']
	assert not any(i.startswith('timer.') for i in ids), 'timers stay off the card'
	assert any(d['name'] == 'Hall TV' for d in s['devices']), 'bridge devices still show next to cloud ones'

	assert call(base, '/cmd', {'device': 'lg:a1', 'control': 'operation.airConOperationMode', 'value': True}, owner)[0] == 200
	assert call(base, '/cmd', {'device': 'lg:a1', 'control': 'temperatureInUnits.targetTemperature', 'value': 22}, owner)[0] == 200
	code, r = call(base, '/cmd', {'device': 'lg:a1', 'control': 'temperatureInUnits.targetTemperature', 'value': 45}, owner)
	assert code == 502 and 'out of range' in r['message'], r
	code, r = call(base, '/cmd', {'device': 'lg:a1', 'control': 'airConJobMode.currentJobMode', 'value': 'TURBO'}, owner)
	assert code == 502 and 'not an option' in r['message'], r
	wait_for(base, owner, 'Washer')
	assert call(base, '/cmd', {'device': 'lg:w1', 'control': 'operation.washerOperationMode=START'}, owner)[0] == 200
	assert got['lg'] == [
		('a1', {'operation': {'airConOperationMode': 'POWER_ON'}}, 'true'),
		('a1', {'temperatureInUnits': {'targetTemperature': 22, 'unit': 'C'}}, 'true'),
		('w1', {'operation': {'washerOperationMode': 'START'}}, 'true')], got['lg']

	# SmartThings sign-in for the friend's home, whose bridge never runs
	code, r = call(base, '/links/smartthings/start', {}, friend)
	assert code == 200 and r['url'].startswith(env['HOME_ST_OAUTH'] + '/authorize?'), r
	q = urllib.parse.parse_qs(r['url'].split('?', 1)[1])
	assert q['redirect_uri'] == ['http://68.221.25.41/home/api/st/callback'] and 'x:devices:*' in q['scope'][0], q
	opener = urllib.request.build_opener(NoRedirect)

	def callback(query):
		try:
			opener.open(base + '/st/callback?' + urllib.parse.urlencode(query), timeout=10)
		except urllib.error.HTTPError as e:
			assert e.code == 302, e.code
			return e.headers['Location']
		raise AssertionError('callback must redirect')
	assert 'link_error' in callback({'state': q['state'][0], 'error': 'access_denied'})
	assert 'expired' in urllib.parse.unquote_plus(callback({'state': q['state'][0], 'code': 'good-code'})), 'a sign-in state works once'
	state = urllib.parse.parse_qs(call(base, '/links/smartthings/start', {}, friend)[1]['url'].split('?', 1)[1])['state'][0]
	assert callback({'state': state, 'code': 'good-code'}) == '/home/?linked=smartthings'
	s, st_ac = wait_for(base, friend, 'Bedroom AC')
	assert s['links']['smartthings']['kind'] == 'oauth', s
	assert got['st_token'][:2] == ['authorization_code', 'refresh_token'], 'the short-lived token must be renewed: %s' % got['st_token']
	code, r = call(base, '/cmd', {'device': 'st:ac9', 'control': 'switch', 'value': True}, friend)
	assert code == 200, r
	assert got['st'][-1] == ('Bearer access-2', {'component': 'main', 'capability': 'switch', 'command': 'on', 'arguments': []}), got['st']
	assert 'Bedroom AC' not in json.dumps(call(base, '/state', token=owner)[1]), 'owner must not see the friend cloud'
	code, r = call(base, '/cmd', {'device': 'st:ac9', 'control': 'switch', 'value': True}, owner)
	assert code != 200 and len(got['st']) == 1, 'a home without SmartThings linked must not reach it: %s %s' % (code, r)
	code, r = call(base, '/cmd', {'type': 'rescan'}, owner)
	assert code == 200 and r['message'] == 'found 2 devices, and 2 cloud devices', 'rescan covers bridge and cloud: %s %s' % (code, r)

	links_file = os.path.join(os.path.dirname(env['HOME_RELAY_DATA']), 'links.json')
	assert oct(os.stat(links_file).st_mode & 0o777) == '0o600', 'cloud tokens must be private to the relay'
	with open(env['HOME_RELAY_DATA']) as f:
		assert 'access-2' not in f.read()

	assert call(base, '/links/remove', {'service': 'thinq'}, owner)[0] == 200
	s = call(base, '/state', token=owner)[1]
	assert 'thinq' not in s['links'] and not any(d['id'].startswith('lg:') for d in s['devices']), s
	code, r = call(base, '/cmd', {'device': 'lg:a1', 'control': 'operation.airConOperationMode', 'value': False}, owner)
	assert code != 200 and len(got['lg']) == 3, 'an unlinked cloud must not be reachable'


def main():
	serve(FakeRoku, 8060)
	serve(FakeSamsung, 8001)
	cloud_port = free_port()
	serve(FakeClouds, cloud_port)
	fake = 'http://127.0.0.1:%d' % cloud_port
	port = free_port()
	env = dict(os.environ, HOME_PANEL_PASSWORD='test-password', HOME_BRIDGE_TOKEN='t' * 32, HOME_RELAY_PORT=str(port), HOME_RELAY_DATA=os.path.join(tempfile.mkdtemp(), 'accounts.json'),
		HOME_ST_API=fake + '/st/v1', HOME_ST_OAUTH=fake + '/st/oauth', HOME_THINQ_API=fake + '/lg', HOME_ST_CLIENT_ID='st-client', HOME_ST_CLIENT_SECRET='st-secret')
	relay = subprocess.Popen([sys.executable, os.path.join(ROOT, 'home', 'relay.py')], env=env, stderr=subprocess.DEVNULL)
	tmp = tempfile.mkdtemp()
	try:
		base = 'http://127.0.0.1:%d/home/api' % port
		for _ in range(50):
			try:
				socket.create_connection(('127.0.0.1', port), timeout=0.2).close()
				break
			except OSError:
				time.sleep(0.1)

		assert call(base, '/state')[0] == 401, 'state must need a login'
		assert call(base, '/login', {'password': 'nope'})[0] == 401
		code, r = call(base, '/login', {'password': 'test-password'})
		assert code == 200, r
		tok = r['token']
		code, r = call(base, '/cmd', {'device': 'roku:127.0.0.1', 'control': 'vol_up'}, tok)
		assert code == 503, 'offline bridge must be reported: %s' % r

		cfg = os.path.join(tmp, 'bridge.json')
		with open(cfg, 'w') as f:
			json.dump({'relay': 'http://127.0.0.1:%d' % port, 'token': 't' * 32, 'scan': False,
				'devices': [{'driver': 'roku', 'host': '127.0.0.1', 'name': 'Bedroom Roku'},
					{'driver': 'samsung', 'host': 'localhost', 'name': 'Hall TV'}]}, f)
		os.environ['HOME_BRIDGE_CONFIG'] = cfg
		spec = importlib.util.spec_from_file_location('bridge', os.path.join(ROOT, 'site', 'home', 'bridge.py'))
		bridge = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(bridge)
		bridge.STATE = os.path.join(tmp, 'state.json')
		bridge.log = lambda *a: None
		b = bridge.Bridge(bridge.load_json(cfg, {}))
		threading.Thread(target=b.forever, daemon=True).start()

		for _ in range(50):
			code, s = call(base, '/state', token=tok)
			if s.get('bridge', {}).get('online') and s['devices']:
				break
			time.sleep(0.1)
		names = sorted(d['name'] for d in s['devices'])
		assert names == ['Bedroom Roku', 'Hall TV'], names
		hall = next(d for d in s['devices'] if d['name'] == 'Hall TV')
		assert any(c['id'] == 'power_on' for c in hall['controls']), 'Samsung MAC should enable Wake'

		code, r = call(base, '/cmd', {'device': 'roku:127.0.0.1', 'control': 'vol_up'}, tok)
		assert code == 200 and got['roku'] == ['/keypress/VolumeUp'], (code, r, got)
		code, r = call(base, '/cmd', {'device': 'samsung:localhost', 'control': 'home'}, tok)
		assert code == 200 and got['samsung'] == ['KEY_HOME'], (code, r, got)
		code, r = call(base, '/cmd', {'device': 'roku:127.0.0.1', 'control': 'rm -rf'}, tok)
		assert code == 502 and 'unknown control' in r['message'], r
		code, r = call(base, '/cmd', {'device': 'roku:10.0.0.9', 'control': 'power'}, tok)
		assert code == 502 and 'unknown device' in r['message'], r
		assert call(base, '/bridge/poll', token='wrong')[0] == 401

		# sign-up: a new home sees only its own bridge's devices, never the owner's
		code, acc = call(base, '/signup', {'name': 'Friend flat'})
		assert code == 200 and acc['token'].startswith('hk_') and acc['bridge_token'].startswith('hb_'), acc
		code, st = call(base, '/state', token=acc['token'])
		assert code == 200 and st['devices'] == [] and st['home'] == 'Friend flat', st
		code, r = call(base, '/cmd', {'device': 'roku:127.0.0.1', 'control': 'vol_up'}, acc['token'])
		assert code == 503 and got['roku'] == ['/keypress/VolumeUp'], '(friend bridge not connected yet) a key must never reach the owner bridge: %s %s' % (code, r)
		assert call(base, '/bridge/devices', {'devices': [{'id': 'x:1', 'name': 'Friend TV', 'controls': []}]}, acc['bridge_token'])[0] == 200
		assert [d['name'] for d in call(base, '/state', token=acc['token'])[1]['devices']] == ['Friend TV']
		assert 'Friend TV' not in json.dumps(call(base, '/state', token=tok)[1]), 'owner must not see other homes'
		code, r = call(base, '/login', {'password': acc['token']})
		assert code == 200 and r['token'] == acc['token'], r
		with open(env['HOME_RELAY_DATA']) as f:
			assert acc['token'] not in f.read(), 'keys must be stored hashed'
		for i in range(2):
			assert call(base, '/signup', {'name': 'spam %d' % i})[0] == 200
		assert call(base, '/signup', {'name': 'spam 3'})[0] == 429, 'sign-ups must be rate limited'
		check_clouds(base, tok, acc['token'], env)
		relay.terminate()
		relay.wait()
		env['HOME_NO_PASSWORD'] = '1'
		env.pop('HOME_PANEL_PASSWORD')
		relay = subprocess.Popen([sys.executable, os.path.join(ROOT, 'home', 'relay.py')], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		for _ in range(50):
			try:
				socket.create_connection(('127.0.0.1', port), timeout=0.2).close()
				break
			except OSError:
				time.sleep(0.1)
		assert call(base, '/state')[0] == 200, 'test mode must not need a login'
		assert call(base, '/bridge/poll', token='wrong')[0] == 401, 'test mode must still check the bridge token'
		print('home control: ok')
	finally:
		relay.terminate()


if __name__ == '__main__':
	main()
