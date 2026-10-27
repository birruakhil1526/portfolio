#!/bin/sh
# one-time setup of the speech-to-text relay on the VM; run from the repo root: sudo sh server/stt/install.sh
# nothing stays resident: fcgiwrap is socket-activated and starts Python only for each request
set -e
cd "$(dirname "$0")"

apt-get install -y fcgiwrap python3-venv
[ -x /opt/stt/venv/bin/python ] || python3 -m venv /opt/stt/venv
/opt/stt/venv/bin/pip install -q --upgrade nvidia-riva-client
install -o root -g root -m 755 transcribe.py /opt/stt/transcribe.py

# key and model id live only here, readable by nginx's fcgiwrap user
if [ ! -f /etc/stt.env ]; then
	cat > /etc/stt.env <<'EOF'
# from build.nvidia.com > parakeet model > Get API Key
NVIDIA_API_KEY=
# "function-id" shown in the same model's API example (parakeet-tdt-0.6b-v2 below)
PARAKEET_FUNCTION_ID=d3fe9151-442b-4204-a70d-5fcc597fd610
PARAKEET_LANGUAGE=en-US
EOF
fi
chown root:www-data /etc/stt.env
chmod 640 /etc/stt.env

systemctl enable --now fcgiwrap.socket
echo "done: put your key in /etc/stt.env, then install server/nginx-portfolio.conf and reload nginx"
