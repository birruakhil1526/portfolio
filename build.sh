#!/bin/sh
# build generated pages; --check also fails if they were not rebuilt or a stranger's phone number slipped in
set -e
cd "$(dirname "$0")"

python3 study/build_study.py
python3 jobs/build_jobs.py

[ "$1" = "--check" ] || exit 0

if ! git diff --quiet -- site/; then
	echo "site/ is out of date: run ./build.sh and commit the result" >&2
	git diff --stat -- site/ >&2
	exit 1
fi

# only Akhil's own number may be published
if grep -rnoE '(\+91[ -]?)?\b[6-9][0-9]{9}\b' site/ --include='*.html' | grep -v '7989714750$'; then
	echo "possible phone number in site/" >&2
	exit 1
fi
echo "site/ is up to date"
