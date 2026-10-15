#!/usr/bin/env python3
"""Home bridge for Birru's Space: run this on any always-on machine on the home WiFi
(laptop, Raspberry Pi, or an old Android phone with Termux). Python 3.8+, standard library only.

It finds devices on the WiFi (SSDP), talks to them in their own local protocol, can also pull in
cloud-connected appliances (SmartThings, Home Assistant), and connects *out* to the relay on the VM
so the /home/ page can control everything from anywhere. Nothing on the router has to be opened.

  python3 bridge.py setup     ask for the relay token once and save bridge.json
  python3 bridge.py scan      list what it can find, then exit
  python3 bridge.py           run (keep it running; see the /home/ page for autostart tips)

Local drivers: Roku / Roku TV, Samsung Tizen TV (2016+), LG webOS TV, Wake-on-LAN.
Cloud drivers: SmartThings (Samsung AC, washer, TV...), LG ThinQ (LG AC, washer, fridge...), Home
Assistant (anything HA supports, including Daikin, Midea, Tuya, and IR blasters for IR-only ACs).
The relay on the VM imports this file and runs the SmartThings and LG ThinQ drivers itself, so
cloud appliances work from the /home/ page without this bridge running at all.
"""
import base64
import hashlib
import ipaddress
import json
import os
import re
import socket
import ssl
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

VERSION = '1.0'
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.environ.get('HOME_BRIDGE_CONFIG', os.path.join(HERE, 'bridge.json'))
STATE = os.path.join(HERE, '.bridge-state.json')   # TV pairing keys, learnt MAC addresses
DEFAULT_RELAY = 'http://68.221.25.41'
APP_NAME = 'Birru Home'
REFRESH_EVERY = 120


def log(*a):
	print(time.strftime('%H:%M:%S'), *a, flush=True)


def load_json(path, default):
	try:
		with open(path) as f:
			return json.load(f)
	except (OSError, ValueError):
		return default


def save_json(path, obj):
	tmp = path + '.tmp'
	with open(tmp, 'w') as f:
		json.dump(obj, f, indent=2)
	os.replace(tmp, path)
	try:
		os.chmod(path, 0o600)
	except OSError:
		pass


state_lock = threading.Lock()
state = load_json(STATE, {})


def remember(key, value):
	with state_lock:
		state[key] = value
		save_json(STATE, state)


def private(host):
	try:
		return ipaddress.ip_address(socket.gethostbyname(host)).is_private
	except (OSError, ValueError):
		return False


def http(method, url, body=None, headers=None, timeout=8, insecure=False):
	data = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
	h = {'User-Agent': 'birru-home-bridge/' + VERSION}
	if isinstance(body, (dict, list)):
		h['Content-Type'] = 'application/json'
	h.update(headers or {})
	req = urllib.request.Request(url, data=data, headers=h, method=method)
	ctx = ssl._create_unverified_context() if insecure else None
	with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
		raw = r.read()
	try:
		return json.loads(raw) if raw else {}
	except ValueError:
		return raw.decode('utf-8', 'replace')


# ---------------------------------------------------------------- minimal WebSocket client (RFC 6455)

class WebSocket:
	def __init__(self, url, timeout=8, headers=None):
		u = urllib.parse.urlsplit(url)
		secure = u.scheme == 'wss'
		port = u.port or (443 if secure else 80)
		sock = socket.create_connection((u.hostname, port), timeout=timeout)
		if secure:
			# TVs use self-signed certificates on the LAN, so there is nothing to verify against
			sock = ssl._create_unverified_context().wrap_socket(sock, server_hostname=u.hostname)
		self.sock, self.buf = sock, b''
		key = base64.b64encode(os.urandom(16)).decode()
		path = (u.path or '/') + ('?' + u.query if u.query else '')
		lines = ['GET %s HTTP/1.1' % path, 'Host: %s:%d' % (u.hostname, port), 'Upgrade: websocket',
			'Connection: Upgrade', 'Sec-WebSocket-Key: ' + key, 'Sec-WebSocket-Version: 13']
		lines += ['%s: %s' % kv for kv in (headers or {}).items()]
		sock.sendall(('\r\n'.join(lines) + '\r\n\r\n').encode())
		while b'\r\n\r\n' not in self.buf:
			chunk = sock.recv(4096)
			if not chunk:
				raise ConnectionError('websocket handshake: connection closed')
			self.buf += chunk
		head, self.buf = self.buf.split(b'\r\n\r\n', 1)
		head = head.decode('latin-1')
		if ' 101 ' not in head.split('\r\n', 1)[0]:
			raise ConnectionError('websocket handshake refused: ' + head.split('\r\n', 1)[0])
		want = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
		if want not in head:
			raise ConnectionError('websocket handshake: bad accept key')

	def _read(self, n):
		while len(self.buf) < n:
			chunk = self.sock.recv(65536)
			if not chunk:
				raise ConnectionError('websocket closed')
			self.buf += chunk
		out, self.buf = self.buf[:n], self.buf[n:]
		return out

	def _frame(self, opcode, payload):
		mask = os.urandom(4)
		n = len(payload)
		head = bytes([0x80 | opcode])
		if n < 126:
			head += bytes([0x80 | n])
		elif n < 65536:
			head += bytes([0x80 | 126]) + struct.pack('!H', n)
		else:
			head += bytes([0x80 | 127]) + struct.pack('!Q', n)
		self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

	def send(self, obj):
		self._frame(0x1, (obj if isinstance(obj, str) else json.dumps(obj)).encode())

	def recv(self, timeout=8):
		self.sock.settimeout(timeout)
		message = b''
		while True:
			b1, b2 = self._read(2)
			opcode, n = b1 & 0x0F, b2 & 0x7F
			if n == 126:
				n = struct.unpack('!H', self._read(2))[0]
			elif n == 127:
				n = struct.unpack('!Q', self._read(8))[0]
			mask = self._read(4) if b2 & 0x80 else None
			payload = self._read(n)
			if mask:
				payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
			if opcode == 0x8:
				raise ConnectionError('websocket closed by device')
			if opcode == 0x9:
				self._frame(0xA, payload)
				continue
			if opcode in (0x0, 0x1, 0x2):
				message += payload
				if b1 & 0x80:
					text = message.decode('utf-8', 'replace')
					try:
						return json.loads(text)
					except ValueError:
						return text

	def close(self):
		try:
			self._frame(0x8, b'')
		except OSError:
			pass
		self.sock.close()


# ---------------------------------------------------------------- controls shared by the TV drivers

def btn(cid, label, group):
	return {'id': cid, 'label': label, 'type': 'button', 'group': group}


TV_CONTROLS = [
	btn('power', 'Power', 'power'),
	btn('vol_down', 'Vol −', 'volume'), btn('mute', 'Mute', 'volume'), btn('vol_up', 'Vol +', 'volume'),
	btn('ch_down', 'Ch −', 'channel'), btn('ch_up', 'Ch +', 'channel'),
	btn('up', '▲', 'nav'), btn('left', '◀', 'nav'), btn('ok', 'OK', 'nav'), btn('right', '▶', 'nav'), btn('down', '▼', 'nav'),
	btn('back', 'Back', 'keys'), btn('home', 'Home', 'keys'), btn('play', 'Play', 'keys'), btn('pause', 'Pause', 'keys'),
]


def wake_on_lan(mac):
	raw = bytes.fromhex(re.sub('[^0-9a-fA-F]', '', mac))
	if len(raw) != 6:
		raise ValueError('bad MAC address: ' + mac)
	packet = b'\xff' * 6 + raw * 16
	with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
		s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
		for port in (9, 7):
			s.sendto(packet, ('255.255.255.255', port))


def mac_for(dev):
	return dev.get('mac') or state.get('mac:' + dev['host'])


def tv_device(driver, host, name, info, extra=None):
	dev = {'id': '%s:%s' % (driver, host), 'name': name, 'kind': 'tv', 'driver': driver, 'host': host,
		'info': info, 'controls': [dict(c) for c in TV_CONTROLS], 'state': {}}
	dev.update(extra or {})
	if mac_for(dev):
		dev['controls'].insert(0, btn('power_on', 'Wake', 'power'))
	return dev


# ---------------------------------------------------------------- Roku (ECP over HTTP, port 8060)

ROKU_KEYS = {'power': 'Power', 'vol_up': 'VolumeUp', 'vol_down': 'VolumeDown', 'mute': 'VolumeMute',
	'ch_up': 'ChannelUp', 'ch_down': 'ChannelDown', 'up': 'Up', 'down': 'Down', 'left': 'Left',
	'right': 'Right', 'ok': 'Select', 'back': 'Back', 'home': 'Home', 'play': 'Play', 'pause': 'Play'}


def roku_run(dev, control, value):
	if control == 'power_on':
		key = 'PowerOn'
	else:
		key = ROKU_KEYS[control]
	http('POST', 'http://%s:8060/keypress/%s' % (dev['host'], key), body=b'', timeout=5)
	return 'sent ' + key


# ---------------------------------------------------------------- Samsung Tizen TV (WebSocket, 8001 / 8002)

SAMSUNG_KEYS = {'power': 'KEY_POWER', 'vol_up': 'KEY_VOLUP', 'vol_down': 'KEY_VOLDOWN', 'mute': 'KEY_MUTE',
	'ch_up': 'KEY_CHUP', 'ch_down': 'KEY_CHDOWN', 'up': 'KEY_UP', 'down': 'KEY_DOWN', 'left': 'KEY_LEFT',
	'right': 'KEY_RIGHT', 'ok': 'KEY_ENTER', 'back': 'KEY_RETURN', 'home': 'KEY_HOME', 'play': 'KEY_PLAY',
	'pause': 'KEY_PAUSE'}


def samsung_probe(host):
	try:
		info = http('GET', 'http://%s:8001/api/v2/' % host, timeout=3)
	except (OSError, urllib.error.URLError, ValueError):
		return None
	if not isinstance(info, dict) or 'device' not in info:
		return None
	d = info['device']
	if d.get('wifiMac'):
		remember('mac:' + host, d['wifiMac'])
	return tv_device('samsung', host, d.get('name') or 'Samsung TV', d.get('modelName', 'Samsung Tizen'),
		{'tokenAuth': str(d.get('TokenAuthSupport', '')).lower() == 'true'})


def samsung_run(dev, control, value):
	host = dev['host']
	name = base64.b64encode(APP_NAME.encode()).decode()
	token = state.get('samsung:' + host)
	if dev.get('tokenAuth'):
		url = 'wss://%s:8002/api/v2/channels/samsung.remote.control?name=%s' % (host, name)
		if token:
			url += '&token=' + token
	else:
		url = 'ws://%s:8001/api/v2/channels/samsung.remote.control?name=%s' % (host, name)
	ws = WebSocket(url, timeout=6)
	try:
		# the first time, the TV shows "allow Birru Home?"; wait for someone to press Allow
		deadline = time.time() + (30 if not token else 8)
		while True:
			msg = ws.recv(timeout=max(1, deadline - time.time()))
			event = msg.get('event') if isinstance(msg, dict) else None
			if event == 'ms.channel.connect':
				new = (msg.get('data') or {}).get('token')
				if new and new != token:
					remember('samsung:' + host, new)
				break
			if event == 'ms.channel.unauthorized':
				raise PermissionError('the TV refused: press Allow on the TV, or enable it under Settings > General > External Device Manager')
		key = SAMSUNG_KEYS[control]
		ws.send({'method': 'ms.remote.control', 'params': {'Cmd': 'Click', 'DataOfCmd': key,
			'Option': 'false', 'TypeOfRemote': 'SendRemoteKey'}})
		time.sleep(0.3)
		return 'sent ' + key
	finally:
		ws.close()


# ---------------------------------------------------------------- LG webOS TV (SSAP over WebSocket, 3001 / 3000)

LG_PERMISSIONS = ['LAUNCH', 'LAUNCH_WEBAPP', 'APP_TO_APP', 'CONTROL_AUDIO', 'CONTROL_DISPLAY',
	'CONTROL_INPUT_JOYSTICK', 'CONTROL_INPUT_MEDIA_PLAYBACK', 'CONTROL_INPUT_TV', 'CONTROL_POWER',
	'CONTROL_MOUSE_AND_KEYBOARD', 'READ_INSTALLED_APPS', 'READ_CURRENT_CHANNEL', 'READ_INPUT_DEVICE_LIST',
	'READ_NETWORK_STATE', 'READ_TV_CHANNEL_LIST', 'READ_POWER_STATE', 'READ_COUNTRY_INFO']
LG_URIS = {'power': 'ssap://system/turnOff', 'vol_up': 'ssap://audio/volumeUp', 'vol_down': 'ssap://audio/volumeDown',
	'ch_up': 'ssap://tv/channelUp', 'ch_down': 'ssap://tv/channelDown', 'play': 'ssap://media.controls/play',
	'pause': 'ssap://media.controls/pause'}
LG_BUTTONS = {'up': 'UP', 'down': 'DOWN', 'left': 'LEFT', 'right': 'RIGHT', 'ok': 'ENTER', 'back': 'BACK', 'home': 'HOME'}


class LGSession:
	def __init__(self, host):
		self.host, self.n, self.ws = host, 0, None
		errors = []
		for url in ('wss://%s:3001/' % host, 'ws://%s:3000/' % host):
			try:
				self.ws = WebSocket(url, timeout=6)
				break
			except (OSError, ConnectionError) as e:
				errors.append(str(e))
		if not self.ws:
			raise ConnectionError('TV not reachable (is it on?): ' + '; '.join(errors))
		key = state.get('lg:' + host)
		self.ws.send({'type': 'register', 'id': 'register_0', 'payload': {
			'forcePairing': False, 'pairingType': 'PROMPT', 'client-key': key,
			'manifest': {'manifestVersion': 1, 'appVersion': '1.1', 'permissions': LG_PERMISSIONS}}})
		deadline = time.time() + (8 if key else 40)
		while True:
			msg = self.ws.recv(timeout=max(1, deadline - time.time()))
			if not isinstance(msg, dict):
				continue
			if msg.get('type') == 'registered':
				new = (msg.get('payload') or {}).get('client-key')
				if new and new != key:
					remember('lg:' + host, new)
				break
			if msg.get('type') == 'error':
				raise PermissionError('the TV refused pairing: ' + str(msg.get('error')))

	def request(self, uri, payload=None):
		self.n += 1
		rid = 'req_%d' % self.n
		self.ws.send({'type': 'request', 'id': rid, 'uri': uri, 'payload': payload or {}})
		while True:
			msg = self.ws.recv(timeout=8)
			if isinstance(msg, dict) and msg.get('id') == rid:
				if msg.get('type') == 'error':
					raise RuntimeError(str(msg.get('error')))
				return msg.get('payload') or {}

	def close(self):
		self.ws.close()


def lg_run(dev, control, value):
	s = LGSession(dev['host'])
	try:
		if not state.get('mac:' + dev['host']):
			try:
				info = s.request('ssap://com.webos.service.connectionmanager/getinfo')
				mac = (info.get('wifiInfo') or {}).get('macAddress') or (info.get('wiredInfo') or {}).get('macAddress')
				if mac:
					remember('mac:' + dev['host'], mac)
			except (RuntimeError, OSError):
				pass
		if control == 'mute':
			muted = s.request('ssap://audio/getStatus').get('mute', False)
			s.request('ssap://audio/setMute', {'mute': not muted})
			return 'unmuted' if muted else 'muted'
		if control in LG_URIS:
			s.request(LG_URIS[control])
			return 'done'
		path = s.request('ssap://com.webos.service.networkinput/getPointerInputSocket')['socketPath']
		pointer = WebSocket(path, timeout=6)
		try:
			pointer.send('type:button\nname:%s\n\n' % LG_BUTTONS[control])
			time.sleep(0.2)
		finally:
			pointer.close()
		return 'sent ' + LG_BUTTONS[control]
	finally:
		s.close()


LOCAL_RUN = {'roku': roku_run, 'samsung': samsung_run, 'webos': lg_run}


def local_run(dev, control, value):
	if control == 'power_on':
		mac = mac_for(dev)
		if dev['driver'] == 'roku':
			try:
				return roku_run(dev, control, value)
			except (OSError, urllib.error.URLError):
				pass
		if not mac:
			raise ValueError('no MAC address known for Wake-on-LAN; add "mac" to this device in bridge.json')
		wake_on_lan(mac)
		return 'wake packet sent to ' + mac
	if dev['driver'] == 'wol':
		raise ValueError('this device only supports Wake')
	return LOCAL_RUN[dev['driver']](dev, control, value)


# ---------------------------------------------------------------- SSDP discovery on the WiFi

def ssdp_search(wait=3):
	found = {}
	targets = ['ssdp:all', 'roku:ecp', 'urn:dial-multiscreen-org:service:dial:1',
		'urn:schemas-upnp-org:device:MediaRenderer:1', 'urn:lge-com:service:webos-second-screen:1']
	s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
	s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
	s.settimeout(0.5)
	try:
		for st in targets:
			msg = 'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 2\r\nST: %s\r\n\r\n' % st
			s.sendto(msg.encode(), ('239.255.255.250', 1900))
		end = time.time() + wait
		while time.time() < end:
			try:
				data, (ip, _) = s.recvfrom(8192)
			except socket.timeout:
				continue
			if not ipaddress.ip_address(ip).is_private:
				continue
			headers = {}
			for line in data.decode('utf-8', 'replace').split('\r\n')[1:]:
				if ':' in line:
					k, v = line.split(':', 1)
					headers[k.strip().lower()] = v.strip()
			entry = found.setdefault(ip, {'ip': ip, 'st': set(), 'server': '', 'locations': set()})
			entry['st'].add(headers.get('st', ''))
			entry['server'] = entry['server'] or headers.get('server', '')
			if headers.get('location'):
				entry['locations'].add(headers['location'])
	except OSError as e:
		log('SSDP search failed:', e)
	finally:
		s.close()
	return found


def upnp_description(location):
	host = urllib.parse.urlsplit(location).hostname
	if not host or not private(host):
		return {}
	try:
		raw = http('GET', location, timeout=3)
		root = ET.fromstring(raw if isinstance(raw, str) else json.dumps(raw))
	except (OSError, urllib.error.URLError, ET.ParseError, ValueError):
		return {}
	out = {}
	for el in root.iter():
		tag = el.tag.split('}')[-1]
		if tag in ('friendlyName', 'manufacturer', 'modelName', 'deviceType') and tag not in out and el.text:
			out[tag] = el.text.strip()
	return out


def discover_local():
	devices = []
	for ip, e in sorted(ssdp_search().items()):
		desc = {}
		for loc in sorted(e['locations']):
			desc = upnp_description(loc)
			if desc.get('friendlyName'):
				break
		blob = ' '.join([e['server'], desc.get('manufacturer', ''), desc.get('modelName', ''),
			desc.get('friendlyName', ''), ' '.join(e['st'])]).lower()
		name = desc.get('friendlyName') or e['server'] or ip
		model = ' '.join(x for x in (desc.get('manufacturer'), desc.get('modelName')) if x)
		dev = None
		if 'roku' in blob:
			dev = tv_device('roku', ip, name, model or 'Roku')
		elif 'samsung' in blob:
			dev = samsung_probe(ip)
		elif 'webos' in blob or 'lge' in blob or 'lg electronics' in blob:
			dev = tv_device('webos', ip, name, model or 'LG webOS')
		if not dev:
			# shown so you can see what is on the WiFi; it has no local API this bridge knows
			kind = 'router' if 'gateway' in blob else 'speaker' if 'cast' in blob or 'sonos' in blob else 'other'
			dev = {'id': 'seen:' + ip, 'name': name, 'kind': kind, 'driver': 'seen', 'host': ip,
				'info': model or e['server'] or 'UPnP device', 'controls': [], 'state': {}}
		devices.append(dev)
	return devices


def manual_devices(cfg):
	out = []
	for d in cfg.get('devices', []):
		driver, host = d.get('driver'), d.get('host', '')
		if driver == 'samsung':
			dev = samsung_probe(host) or tv_device('samsung', host, d.get('name', 'Samsung TV'), 'Samsung Tizen (offline)', {'tokenAuth': True})
		elif driver in ('roku', 'webos'):
			dev = tv_device(driver, host, d.get('name', host), {'roku': 'Roku', 'webos': 'LG webOS'}[driver])
		elif driver == 'wol':
			dev = {'id': 'wol:' + (d.get('mac') or host), 'name': d.get('name', 'Computer'), 'kind': d.get('kind', 'computer'),
				'driver': 'wol', 'host': host, 'info': 'Wake-on-LAN', 'controls': [btn('power_on', 'Wake', 'power')], 'state': {}}
		else:
			log('bridge.json: unknown driver', driver)
			continue
		if d.get('name'):
			dev['name'] = d['name']
		if d.get('mac'):
			dev['mac'] = d['mac']
			if not any(c['id'] == 'power_on' for c in dev['controls']):
				dev['controls'].insert(0, btn('power_on', 'Wake', 'power'))
		out.append(dev)
	return out


# ---------------------------------------------------------------- SmartThings (cloud)

ST_API = os.environ.get('HOME_ST_API', 'https://api.smartthings.com/v1')
ST_KINDS = {'television': 'tv', 'airconditioner': 'ac', 'washer': 'washer', 'dryer': 'dryer', 'light': 'light',
	'switch': 'switch', 'refrigerator': 'fridge', 'dishwasher': 'dishwasher', 'robotcleaner': 'vacuum',
	'airpurifier': 'purifier', 'fan': 'fan'}


class SmartThings:
	def __init__(self, token):
		self.h = {'Authorization': 'Bearer ' + token}

	def get(self, path):
		return self.call('GET', path)

	def call(self, method, path, body=None):
		try:
			return http(method, ST_API + path, body=body, headers=self.h, timeout=10)
		except urllib.error.HTTPError as e:
			raise ValueError('SmartThings: ' + cloud_error(e)) from None

	def devices(self):
		out = []
		for item in self.get('/devices').get('items', []):
			try:
				out.append(self.build(item))
			except (OSError, urllib.error.URLError, ValueError) as e:
				log('SmartThings: skipping', item.get('label'), e)
		return out

	def build(self, item):
		did = item['deviceId']
		comp = next((c for c in item.get('components', []) if c.get('id') == 'main'), {})
		caps = {c['id'] for c in comp.get('capabilities', [])}
		cats = [c.get('name', '').lower() for c in comp.get('categories', [])]
		kind = next((ST_KINDS[c] for c in cats if c in ST_KINDS), 'other')
		st = self.get('/devices/%s/status' % did).get('components', {}).get('main', {})

		def val(cap, attr):
			return ((st.get(cap) or {}).get(attr) or {}).get('value')

		controls = []
		if 'switch' in caps:
			controls.append({'id': 'switch', 'label': 'Power', 'type': 'toggle', 'group': 'power', 'value': val('switch', 'switch') == 'on'})
		if 'audioVolume' in caps:
			controls += [btn('vol_down', 'Vol −', 'volume'), btn('vol_up', 'Vol +', 'volume')]
			controls.append({'id': 'volume', 'label': 'Volume', 'type': 'readout', 'group': 'volume', 'value': val('audioVolume', 'volume'), 'unit': '%'})
		if 'audioMute' in caps:
			controls.append({'id': 'mute', 'label': 'Mute', 'type': 'toggle', 'group': 'volume', 'value': val('audioMute', 'mute') == 'muted'})
		if 'tvChannel' in caps:
			controls += [btn('ch_down', 'Ch −', 'channel'), btn('ch_up', 'Ch +', 'channel')]
		if 'mediaPlayback' in caps:
			controls += [btn('play', 'Play', 'keys'), btn('pause', 'Pause', 'keys')]
		if 'temperatureMeasurement' in caps:
			controls.append({'id': 'room_temp', 'label': 'Room', 'type': 'readout', 'group': 'climate',
				'value': val('temperatureMeasurement', 'temperature'), 'unit': '°'})
		if 'thermostatCoolingSetpoint' in caps:
			controls.append({'id': 'setpoint', 'label': 'Set to', 'type': 'number', 'group': 'climate', 'min': 16, 'max': 30,
				'step': 1, 'unit': '°', 'value': val('thermostatCoolingSetpoint', 'coolingSetpoint')})
		if 'airConditionerMode' in caps:
			controls.append({'id': 'ac_mode', 'label': 'Mode', 'type': 'select', 'group': 'climate',
				'options': val('airConditionerMode', 'supportedAcModes') or ['auto', 'cool', 'dry', 'wind', 'heat'],
				'value': val('airConditionerMode', 'airConditionerMode')})
		if 'airConditionerFanMode' in caps:
			controls.append({'id': 'fan_mode', 'label': 'Fan', 'type': 'select', 'group': 'climate',
				'options': val('airConditionerFanMode', 'supportedAcFanModes') or ['auto', 'low', 'medium', 'high'],
				'value': val('airConditionerFanMode', 'fanMode')})
		for cap in ('washerOperatingState', 'dryerOperatingState'):
			if cap in caps:
				controls.append({'id': 'machine', 'label': 'Status', 'type': 'readout', 'group': 'cycle',
					'value': ' · '.join(str(x) for x in (val(cap, 'machineState'), val(cap, 'washerJobState') or val(cap, 'dryerJobState')) if x)})
				if val(cap, 'completionTime'):
					controls.append({'id': 'done_at', 'label': 'Done at', 'type': 'readout', 'group': 'cycle', 'value': val(cap, 'completionTime'), 'format': 'time'})
				if val('remoteControlStatus', 'remoteControlEnabled') == 'true':
					controls += [btn('cycle_run', 'Start', 'cycle'), btn('cycle_pause', 'Pause', 'cycle'), btn('cycle_stop', 'Stop', 'cycle')]
				else:
					controls.append({'id': 'remote', 'label': 'Remote start', 'type': 'readout', 'group': 'cycle', 'value': 'off: press Remote Control on the machine'})
		return {'id': 'st:' + did, 'name': item.get('label') or item.get('name') or 'SmartThings device', 'kind': kind,
			'driver': 'smartthings', 'host': 'SmartThings', 'info': item.get('manufacturerName') or 'SmartThings cloud',
			'controls': controls, 'state': {'caps': sorted(caps)}}

	def run(self, dev, control, value):
		did = dev['id'][3:]
		caps = set(dev.get('state', {}).get('caps', []))
		simple = {'vol_up': ('audioVolume', 'volumeUp'), 'vol_down': ('audioVolume', 'volumeDown'),
			'ch_up': ('tvChannel', 'channelUp'), 'ch_down': ('tvChannel', 'channelDown'),
			'play': ('mediaPlayback', 'play'), 'pause': ('mediaPlayback', 'pause')}
		args = []
		if control in simple:
			cap, cmd = simple[control]
		elif control == 'switch':
			cap, cmd = 'switch', 'on' if value else 'off'
		elif control == 'mute':
			cap, cmd = 'audioMute', 'mute' if value else 'unmute'
		elif control == 'setpoint':
			cap, cmd, args = 'thermostatCoolingSetpoint', 'setCoolingSetpoint', [value]
		elif control == 'ac_mode':
			cap, cmd, args = 'airConditionerMode', 'setAirConditionerMode', [value]
		elif control == 'fan_mode':
			cap, cmd, args = 'airConditionerFanMode', 'setFanMode', [value]
		elif control.startswith('cycle_'):
			cap = 'washerOperatingState' if 'washerOperatingState' in caps else 'dryerOperatingState'
			cmd, args = 'setMachineState', [control[6:]]
		else:
			raise ValueError('unsupported control')
		self.call('POST', '/devices/%s/commands' % did,
			{'commands': [{'component': 'main', 'capability': cap, 'command': cmd, 'arguments': args}]})
		return 'done'

	def refresh(self, dev):
		return self.build(self.get('/devices/' + dev['id'][3:]))


# ---------------------------------------------------------------- LG ThinQ Connect (cloud)

# public key from LG's official SDK (github.com/thinq-connect/pythinqconnect), not a secret
THINQ_API_KEY = 'v6GFvkweNo7DK7yD3ylIZ9w52aKBU0eJ7wLXkSR3'
THINQ_REGIONS = {
	'kic': 'AU BD CN HK ID IN JP KH KR LA LK MM MY NP NZ PH SG TH TW VN',
	'aic': 'AG AR AW BB BO BR BS BZ CA CL CO CR CU DM DO EC GD GT GY HN HT JM KN LC MX NI PA PE PR PY SR SV TT US UY VC VE',
}
THINQ_KINDS = (('AIR_CONDITIONER', 'ac'), ('WASH', 'washer'), ('DRYER', 'dryer'), ('REFRIGERATOR', 'fridge'),
	('DISH_WASHER', 'dishwasher'), ('ROBOT_CLEANER', 'vacuum'), ('AIR_PURIFIER', 'purifier'), ('FAN', 'fan'))
# schedules and per-unit duplicates would only clutter the card
THINQ_SKIP = {'timer', 'sleepTimer', 'location', 'twoSetTemperature', 'twoSetTemperatureInUnits', 'filterInfo', 'display'}
THINQ_TEMP = ('temperatureInUnits', 'temperature')
THINQ_LABELS = {'currentJobMode': 'Mode', 'windStrength': 'Fan', 'windStrengthDetail': 'Fan', 'currentState': 'Status',
	'remainHour': 'Hours left', 'remainMinute': 'Minutes left', 'remoteControlEnabled': 'Remote start'}


def thinq_base(country):
	region = next((r for r, cs in THINQ_REGIONS.items() if country in cs.split()), 'eic')
	return os.environ.get('HOME_THINQ_API') or 'https://api-%s.lgthinq.com' % region


def words(key):
	if key in THINQ_LABELS:
		return THINQ_LABELS[key]
	return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', key).capitalize()


def pick_unit(v, unit='C'):
	"""temperature resources come as one dict, or a list with one dict per unit"""
	if isinstance(v, list):
		return next((x for x in v if isinstance(x, dict) and x.get('unit') == unit), v[0] if v and isinstance(v[0], dict) else {})
	return v if isinstance(v, dict) else {}


def thinq_controls(prof, state):
	"""builds controls straight from the device profile, so every LG appliance type works without its own code"""
	if not isinstance(prof, dict):
		return [{'id': 'note', 'label': 'Controls', 'type': 'readout', 'group': 'info', 'value': 'use the LG ThinQ app for this one'}]
	power, out, readouts = [], [], 0
	for res in THINQ_TEMP:
		if res not in prof:
			continue
		spec, st = pick_unit(prof[res]), pick_unit(state.get(res))
		target = spec.get('targetTemperatureC') or spec.get('targetTemperature') or {}
		if st.get('currentTemperature') is not None:
			out.append({'id': 'room_temp', 'label': 'Room', 'type': 'readout', 'group': 'climate', 'value': st['currentTemperature'], 'unit': '°'})
		if 'w' in target.get('mode', []):
			rng = (target.get('value') or {}).get('w') or {}
			out.append({'id': res + '.targetTemperature', 'label': 'Set to', 'type': 'number', 'group': 'climate', 'unit': '°',
				'min': rng.get('min', 16), 'max': rng.get('max', 30), 'step': rng.get('step', 1), 'value': st.get('targetTemperature')})
		break
	for res, props in prof.items():
		if res in THINQ_SKIP or res in THINQ_TEMP or not isinstance(props, dict):
			continue
		st = state.get(res) if isinstance(state.get(res), dict) else {}
		for key, spec in props.items():
			if not isinstance(spec, dict):
				continue
			cid, cur, vals = res + '.' + key, st.get(key), (spec.get('value') or {}).get('w')
			if 'w' not in spec.get('mode', []):
				if 'r' in spec.get('mode', []) and readouts < 6 and cur is not None and not isinstance(cur, (dict, list)):
					out.append({'id': cid, 'label': words(key), 'type': 'readout', 'group': 'info', 'value': str(cur).replace('_', ' ').lower()})
					readouts += 1
				continue
			if spec.get('type') == 'enum' and isinstance(vals, list) and vals:
				if {'POWER_ON', 'POWER_OFF'} <= set(vals):
					power.append({'id': cid, 'label': 'Power', 'type': 'toggle', 'group': 'power', 'value': cur == 'POWER_ON',
						'send': ['POWER_ON', 'POWER_OFF']})
				elif res == 'operation' and len(vals) <= 4:
					out += [btn('%s=%s' % (cid, v), v.replace('_', ' ').capitalize(), 'cycle') for v in vals]
				else:
					out.append({'id': cid, 'label': words(key), 'type': 'select', 'group': 'climate', 'options': vals, 'value': cur})
			elif spec.get('type') == 'range' and isinstance(vals, dict):
				out.append({'id': cid, 'label': words(key), 'type': 'number', 'group': 'climate', 'min': vals.get('min', 0),
					'max': vals.get('max', 100), 'step': vals.get('step', 1), 'value': cur})
			elif spec.get('type') == 'boolean':
				out.append({'id': cid, 'label': words(key), 'type': 'toggle', 'group': 'options', 'value': bool(cur)})
	return power + out


class ThinQ:
	def __init__(self, token, country, client_id):
		self.token, self.country, self.client_id = token, country, client_id
		self.base = thinq_base(country)
		self.profiles = {}

	def call(self, method, path, body=None):
		headers = {'Authorization': 'Bearer ' + self.token, 'x-country': self.country, 'x-client-id': self.client_id,
			'x-api-key': THINQ_API_KEY, 'x-service-phase': 'OP',
			'x-message-id': base64.urlsafe_b64encode(uuid.uuid4().bytes)[:-2].decode()}
		if body is not None:
			headers['x-conditional-control'] = 'true'
		try:
			r = http(method, self.base + path, body=body, headers=headers, timeout=12)
		except urllib.error.HTTPError as e:
			raise ValueError('LG ThinQ: ' + cloud_error(e)) from None
		return r.get('response') if isinstance(r, dict) else r

	def devices(self):
		out = []
		for item in self.call('GET', '/devices') or []:
			try:
				out.append(self.build(item['deviceId'], item.get('deviceInfo') or {}))
			except (OSError, urllib.error.URLError, ValueError, KeyError) as e:
				log('LG ThinQ: skipping', item.get('deviceId'), e)
		return out

	def build(self, did, info):
		if did not in self.profiles:
			self.profiles[did] = (self.call('GET', '/devices/%s/profile' % did) or {}).get('property')
		state = self.call('GET', '/devices/%s/state' % did) or {}
		dtype = str(info.get('deviceType', ''))
		return {'id': 'lg:' + did, 'name': info.get('alias') or info.get('modelName') or 'LG appliance',
			'kind': next((k for t, k in THINQ_KINDS if t in dtype), 'other'), 'driver': 'thinq', 'host': 'LG ThinQ',
			'info': info.get('modelName') or 'cloud', 'controls': thinq_controls(self.profiles[did], state if isinstance(state, dict) else {}),
			'state': {'info': info}}

	def run(self, dev, control, value):
		did = dev['id'][3:]
		c = next((x for x in dev['controls'] if x['id'] == control), {})
		cid, _, fixed = control.partition('=')
		res, _, key = cid.partition('.')
		if fixed:
			value = fixed
		elif c.get('send'):
			value = c['send'][0 if value else 1]
		body = {res: {key: value}}
		if res in THINQ_TEMP:
			body[res]['unit'] = 'C'
		self.call('POST', '/devices/%s/control' % did, body)
		return 'done'

	def refresh(self, dev):
		return self.build(dev['id'][3:], dev.get('state', {}).get('info', {}))


def cloud_error(e):
	"""the useful part of a vendor API error response"""
	try:
		body = json.loads(e.read() or b'{}')
		err = body.get('error') if isinstance(body, dict) else None
		msg = err.get('message') if isinstance(err, dict) else err or body.get('message')
	except (OSError, ValueError, AttributeError):
		msg = None
	if e.code == 401:
		return 'the token was rejected or has expired: connect again'
	return '%s (HTTP %d)' % (msg or e.reason, e.code)


def check_value(control, value):
	"""validates a value from the page against the control it is meant for"""
	if not control or control['type'] == 'readout':
		raise ValueError('unknown control')
	if control['type'] == 'toggle':
		return bool(value)
	if control['type'] == 'number':
		value = float(value)
		if not control.get('min', -1e9) <= value <= control.get('max', 1e9):
			raise ValueError('out of range')
		return int(value) if value == int(value) else value
	if control['type'] == 'select' and value not in control.get('options', []):
		raise ValueError('not an option')
	return value


# ---------------------------------------------------------------- Home Assistant (local or cloud)

HA_KINDS = {'climate': 'ac', 'media_player': 'tv', 'light': 'light', 'switch': 'switch', 'fan': 'fan',
	'cover': 'cover', 'vacuum': 'vacuum', 'button': 'button', 'input_boolean': 'switch'}


class HomeAssistant:
	def __init__(self, url, token):
		self.url, self.h = url.rstrip('/'), {'Authorization': 'Bearer ' + token}

	def devices(self):
		return [d for d in (self.build(s) for s in http('GET', self.url + '/api/states', headers=self.h, timeout=10)) if d]

	def build(self, s):
		eid, a = s['entity_id'], s.get('attributes', {})
		domain = eid.split('.')[0]
		if domain not in HA_KINDS or s.get('state') == 'unavailable':
			return None
		on = s.get('state') not in ('off', 'unavailable', 'unknown', 'idle', 'standby', 'closed', 'docked')
		c = []
		if domain in ('light', 'switch', 'fan', 'input_boolean', 'climate', 'media_player'):
			c.append({'id': 'switch', 'label': 'Power', 'type': 'toggle', 'group': 'power', 'value': on})
		if domain == 'climate':
			if a.get('current_temperature') is not None:
				c.append({'id': 'room_temp', 'label': 'Room', 'type': 'readout', 'group': 'climate', 'value': a['current_temperature'], 'unit': '°'})
			if a.get('temperature') is not None:
				c.append({'id': 'setpoint', 'label': 'Set to', 'type': 'number', 'group': 'climate', 'value': a['temperature'],
					'min': a.get('min_temp', 16), 'max': a.get('max_temp', 30), 'step': a.get('target_temp_step', 1), 'unit': '°'})
			if a.get('hvac_modes'):
				c.append({'id': 'ac_mode', 'label': 'Mode', 'type': 'select', 'group': 'climate', 'options': a['hvac_modes'], 'value': s['state']})
			if a.get('fan_modes'):
				c.append({'id': 'fan_mode', 'label': 'Fan', 'type': 'select', 'group': 'climate', 'options': a['fan_modes'], 'value': a.get('fan_mode')})
		if domain == 'media_player':
			c += [btn('vol_down', 'Vol −', 'volume'), btn('vol_up', 'Vol +', 'volume'), btn('play', 'Play/Pause', 'keys')]
		if domain == 'cover':
			c += [btn('open', 'Open', 'power'), btn('stop', 'Stop', 'power'), btn('close', 'Close', 'power')]
		if domain == 'vacuum':
			c += [btn('start', 'Start', 'power'), btn('dock', 'Dock', 'power')]
		if domain == 'button':
			c.append(btn('press', 'Press', 'power'))
		return {'id': 'ha:' + eid, 'name': a.get('friendly_name') or eid, 'kind': HA_KINDS[domain], 'driver': 'homeassistant',
			'host': 'Home Assistant', 'info': eid, 'controls': c, 'state': {'state': s.get('state')}}

	def run(self, dev, control, value):
		eid = dev['id'][3:]
		domain = eid.split('.')[0]
		data = {'entity_id': eid}
		if control == 'switch':
			service = 'turn_on' if value else 'turn_off'
		elif control == 'setpoint':
			service, data['temperature'] = 'set_temperature', value
		elif control == 'ac_mode':
			service, data['hvac_mode'] = 'set_hvac_mode', value
		elif control == 'fan_mode':
			service, data['fan_mode'] = 'set_fan_mode', value
		else:
			service = {'vol_up': 'volume_up', 'vol_down': 'volume_down', 'play': 'media_play_pause', 'open': 'open_cover',
				'close': 'close_cover', 'stop': 'stop_cover', 'start': 'start', 'dock': 'return_to_base', 'press': 'press'}[control]
		http('POST', '%s/api/services/%s/%s' % (self.url, domain, service), headers=self.h, body=data, timeout=10)
		return 'done'

	def refresh(self, dev):
		return self.build(http('GET', '%s/api/states/%s' % (self.url, dev['id'][3:]), headers=self.h, timeout=10)) or dev


# ---------------------------------------------------------------- the bridge itself

class Bridge:
	def __init__(self, cfg):
		self.cfg = cfg
		self.relay = (os.environ.get('HOME_RELAY') or cfg.get('relay') or DEFAULT_RELAY).rstrip('/') + '/home/api'
		self.token = os.environ.get('HOME_BRIDGE_TOKEN') or cfg.get('token', '')
		self.cloud = {}
		if cfg.get('smartthings', {}).get('token'):
			self.cloud['smartthings'] = SmartThings(cfg['smartthings']['token'])
		lg = cfg.get('thinq', {})
		if lg.get('token') and lg.get('country'):
			self.cloud['thinq'] = ThinQ(lg['token'], lg['country'], lg.get('client_id') or 'birru-home-' + socket.gethostname())
		ha = cfg.get('homeassistant', {})
		if ha.get('url') and ha.get('token'):
			self.cloud['homeassistant'] = HomeAssistant(ha['url'], ha['token'])
		self.devices = {}
		self.lock = threading.Lock()

	def scan(self):
		found = []
		if self.cfg.get('scan', True):
			found += discover_local()
		# a device listed in bridge.json replaces whatever the scan found at the same address
		manual = manual_devices(self.cfg)
		hosts = {d['host'] for d in manual}
		found = [d for d in found if d['host'] not in hosts] + manual
		for name, client in self.cloud.items():
			try:
				found += client.devices()
			except (OSError, urllib.error.URLError, ValueError, KeyError) as e:
				log(name, 'failed:', e)
		with self.lock:
			self.devices = {d['id']: d for d in found}
		return found

	def run_command(self, cmd):
		dev = self.devices.get(cmd.get('device'))
		if not dev:
			raise ValueError('unknown device; try Rescan')
		control = next((c for c in dev['controls'] if c['id'] == cmd.get('control')), None)
		value = check_value(control, cmd.get('value'))
		if dev['driver'] in self.cloud:
			client = self.cloud[dev['driver']]
			message = client.run(dev, control['id'], value)
			time.sleep(1)
			try:
				dev = client.refresh(dev)
				with self.lock:
					self.devices[dev['id']] = dev
			except (OSError, urllib.error.URLError, ValueError, KeyError):
				pass
			return message, dev
		message = local_run(dev, control['id'], value)
		# TVs report their MAC on first contact; from then on they can be woken from standby
		if mac_for(dev) and not any(c['id'] == 'power_on' for c in dev['controls']):
			dev['controls'].insert(0, btn('power_on', 'Wake', 'power'))
		return message, dev

	def post(self, path, body):
		return http('POST', self.relay + path, body=body, headers={'Authorization': 'Bearer ' + self.token}, timeout=15)

	def publish(self):
		with self.lock:
			devices = list(self.devices.values())
		self.post('/bridge/devices', {'devices': devices, 'version': VERSION, 'host': socket.gethostname()})

	def handle(self, cmd):
		try:
			if cmd.get('type') == 'rescan':
				n = len(self.scan())
				self.publish()
				result = {'ok': True, 'message': 'found %d devices' % n}
			else:
				message, dev = self.run_command(cmd)
				result = {'ok': True, 'message': message, 'device': dev}
			log('ok', cmd.get('device', cmd.get('type')), cmd.get('control', ''), '->', result['message'])
		except Exception as e:  # report every failure back to the page instead of dying
			result = {'ok': False, 'message': '%s: %s' % (type(e).__name__, e)}
			log('failed', cmd.get('device'), cmd.get('control'), '->', result['message'])
		result['id'] = cmd['id']
		try:
			self.post('/bridge/result', result)
		except (OSError, urllib.error.URLError) as e:
			log('could not send result:', e)

	def refresher(self):
		while True:
			time.sleep(REFRESH_EVERY)
			try:
				self.scan()
				self.publish()
			except Exception as e:
				log('refresh failed:', e)

	def forever(self):
		if not self.token:
			sys.exit('no relay token: run  python3 bridge.py setup  first')
		log('scanning the WiFi...')
		log('found %d devices' % len(self.scan()))
		threading.Thread(target=self.refresher, daemon=True).start()
		backoff = 2
		published = False
		while True:
			try:
				if not published:
					self.publish()
					published = True
					log('connected to', self.relay)
				res = http('GET', self.relay + '/bridge/poll', headers={'Authorization': 'Bearer ' + self.token}, timeout=40)
				for cmd in res.get('cmds', []):
					threading.Thread(target=self.handle, args=(cmd,), daemon=True).start()
				backoff = 2
			except urllib.error.HTTPError as e:
				if e.code == 401:
					sys.exit('the relay rejected the token: check bridge.json')
				log('relay error', e.code, '- retrying in', backoff, 's')
				published = False
				time.sleep(backoff)
				backoff = min(backoff * 2, 60)
			except (OSError, urllib.error.URLError, ValueError) as e:
				log('relay unreachable (%s) - retrying in %d s' % (e, backoff))
				published = False
				time.sleep(backoff)
				backoff = min(backoff * 2, 60)


def setup():
	cfg = load_json(CONFIG, {})
	print('Birru Home bridge setup. Press Enter to keep the value in [brackets].')
	cfg['relay'] = input('Relay address [%s]: ' % cfg.get('relay', DEFAULT_RELAY)).strip() or cfg.get('relay', DEFAULT_RELAY)
	tok = input('Bridge token (from Create your home on the /home/ page)%s: ' % (' [saved]' if cfg.get('token') else '')).strip()
	cfg['token'] = tok or cfg.get('token', '')
	st = input('SmartThings personal access token (optional, for Samsung AC / washer)%s: ' % (' [saved]' if cfg.get('smartthings') else '')).strip()
	if st:
		cfg['smartthings'] = {'token': st}
	ha = input('Home Assistant URL, e.g. http://192.168.1.20:8123 (optional)%s: ' % (' [saved]' if cfg.get('homeassistant') else '')).strip()
	if ha:
		cfg['homeassistant'] = {'url': ha, 'token': input('Home Assistant long-lived access token: ').strip()}
	cfg.setdefault('devices', [])
	save_json(CONFIG, cfg)
	print('saved', CONFIG, '- now run:  python3 bridge.py')


def main():
	arg = sys.argv[1] if len(sys.argv) > 1 else 'run'
	if arg == 'setup':
		return setup()
	b = Bridge(load_json(CONFIG, {}))
	if arg == 'scan':
		for d in b.scan():
			print('%-10s %-9s %-16s %s  (%d controls)' % (d['driver'], d['kind'], d['host'], d['name'], len(d['controls'])))
		return
	if arg in ('run', 'start'):
		return b.forever()
	print(__doc__)


if __name__ == '__main__':
	try:
		main()
	except KeyboardInterrupt:
		pass
