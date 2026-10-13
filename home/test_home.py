#!/usr/bin/env python3
"""End-to-end check of the home control path, no real devices needed:
page API -> relay -> bridge -> fake Roku (HTTP) and fake Samsung TV (WebSocket) on localhost."""
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
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
got = {'roku': [], 'samsung': []}


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


def main():
	serve(FakeRoku, 8060)
	serve(FakeSamsung, 8001)
	port = free_port()
	env = dict(os.environ, HOME_PANEL_PASSWORD='test-password', HOME_BRIDGE_TOKEN='t' * 32, HOME_RELAY_PORT=str(port))
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
