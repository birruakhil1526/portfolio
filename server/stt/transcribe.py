#!/opt/stt/venv/bin/python
# CGI script run by fcgiwrap for POST /api/stt: forwards a WAV/OGG upload to NVIDIA's hosted Parakeet model
# and returns the transcript. All inference happens on NVIDIA's side; this only relays the request.
# Settings come from /etc/stt.env (NVIDIA_API_KEY, PARAKEET_FUNCTION_ID), never from this public repo.
import io
import json
import os
import sys
import wave

MAX_BYTES = 3_500_000  # ~110 s of 16 kHz mono 16-bit audio; keeps the gRPC message under 4 MB
ENV_FILE = os.environ.get('STT_ENV_FILE', '/etc/stt.env')  # override is for local testing


def reply(status, body):
	sys.stdout.write(f'Status: {status}\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n\r\n')
	sys.stdout.write(json.dumps(body))
	sys.stdout.flush()
	sys.exit(0)


def load_env():
	env = {}
	try:
		with open(ENV_FILE) as f:
			for line in f:
				line = line.strip()
				if line and not line.startswith('#') and '=' in line:
					key, value = line.split('=', 1)
					env[key.strip()] = value.strip().strip('"\'')
	except OSError:
		pass
	return env


def main():
	if os.environ.get('REQUEST_METHOD') != 'POST':
		reply('405 Method Not Allowed', {'error': 'POST audio to this endpoint'})

	try:
		length = int(os.environ.get('CONTENT_LENGTH') or 0)
	except ValueError:
		length = 0
	if length <= 0:
		reply('400 Bad Request', {'error': 'empty upload'})
	if length > MAX_BYTES:
		reply('413 Payload Too Large', {'error': 'audio too long, keep it under about 110 seconds'})

	audio = sys.stdin.buffer.read(length)
	is_wav = audio[:4] == b'RIFF' and audio[8:12] == b'WAVE'
	is_ogg = audio[:4] == b'OggS'
	if not (is_wav or is_ogg):
		reply('415 Unsupported Media Type', {'error': 'send 16-bit mono WAV or OGG/Opus audio'})

	env = load_env()
	api_key = env.get('NVIDIA_API_KEY')
	function_id = env.get('PARAKEET_FUNCTION_ID')
	if not api_key or not function_id:
		reply('503 Service Unavailable', {'error': 'speech service is not configured'})

	import riva.client  # imported late so bad requests are rejected without loading grpc

	auth = riva.client.Auth(
		uri=env.get('PARAKEET_SERVER', 'grpc.nvcf.nvidia.com:443'),
		use_ssl=True,
		metadata_args=[['function-id', function_id], ['authorization', f'Bearer {api_key}']],
	)
	config = riva.client.RecognitionConfig(
		language_code=env.get('PARAKEET_LANGUAGE', 'en-US'),
		max_alternatives=1,
		enable_automatic_punctuation=True,
	)
	if is_wav:
		try:
			with wave.open(io.BytesIO(audio)) as w:
				config.sample_rate_hertz = w.getframerate()
				config.audio_channel_count = w.getnchannels()
		except (wave.Error, EOFError):
			reply('415 Unsupported Media Type', {'error': 'could not read the WAV header'})
		config.encoding = riva.client.AudioEncoding.LINEAR_PCM
	else:
		config.encoding = riva.client.AudioEncoding.OGGOPUS

	try:
		response = riva.client.ASRService(auth).offline_recognize(audio, config)
	except Exception as e:  # grpc errors: bad key, quota, unsupported audio
		details = getattr(e, 'details', lambda: str(e))()
		reply('502 Bad Gateway', {'error': f'NVIDIA speech service failed: {details}'})

	text = ' '.join(r.alternatives[0].transcript.strip() for r in response.results if r.alternatives).strip()
	reply('200 OK', {'text': text})


main()
