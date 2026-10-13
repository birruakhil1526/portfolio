"""Fetches senior Angular roles from LinkedIn via Apify, ranks them against the site's skills
and writes jobs/jobs.json. Run daily by .github/workflows/jobs.yml; needs APIFY_TOKEN."""

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'jobs.json'
ACTOR = 'valig~linkedin-jobs-scraper'
EXCLUDE = ['intern', 'trainee', 'fresher', 'junior', 'manager', 'director']
WEEK = 'r604800'
REMOTE = [{'key': 'f_WT', 'value': '2'}]

# (keywords, location, extra input)
SEARCHES = [
	('Senior Angular Developer', 'Bengaluru, Karnataka, India', {'titleInclude': ['angular']}),
	('Senior Angular Developer', 'Hyderabad, Telangana, India', {'titleInclude': ['angular']}),
	('Senior Angular Developer', 'India', {'titleInclude': ['angular'], 'urlParam': REMOTE}),
	('Angular Java Spring Boot full stack', 'Bengaluru, Karnataka, India', {}),
	('Angular Java Spring Boot full stack', 'Hyderabad, Telangana, India', {}),
]

HOME = re.compile(r'bengaluru|bangalore|hyderabad|^india$', re.I)
SENIOR = re.compile(r'\b(senior|sr\.?|lead|staff|principal|specialist|iii|avp|vice president)\b', re.I)
SKIP = re.compile(r'\.net|dotnet|c#|\bjunior\b|2 to 5|\bassociate\b(?!.*senior)|\bqa\b|\btest', re.I)
AI = re.compile(r'\b(ai|llm|genai|gen ai|claude|ml)\b', re.I)
FINANCE = re.compile(r'bank|financ|fintech|invest|payment|capital|fidelity|fis\b|citi|jpmorgan|wells fargo|mastercard|visa|vanguard|state street', re.I)
CITY = re.compile(r',.*$')


def run(keywords, location, extra):
	body = {'keywords': keywords, 'location': location, 'datePosted': WEEK, 'limit': 40, 'titleExclude': EXCLUDE, **extra}
	url = f'https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items?timeout=240'
	req = urllib.request.Request(url, json.dumps(body).encode(), {
		'Content-Type': 'application/json',
		'Authorization': f'Bearer {os.environ["APIFY_TOKEN"]}',
	})
	with urllib.request.urlopen(req, timeout=300) as r:
		return json.load(r)


def applicants(text):
	text = text or ''
	if 'first 25' in text:
		return '<25', 10
	if 'Over 200' in text:
		return '200+', 250
	m = re.search(r'\d+', text)
	return (m.group(), int(m.group())) if m else ('?', 100)


def score(job):
	title, company = job.get('title', ''), job.get('companyName', '')
	s = 0
	s += 6 if 'angular' in title.lower() else 0
	s += 2 if re.search(r'java|spring', title, re.I) else 0
	s += 3 if SENIOR.search(title) else 0
	s += 2 if FINANCE.search(f'{company} {job.get("sector", "")}') else 0
	return s


def main():
	seen, rows = set(), []
	for keywords, location, extra in SEARCHES:
		try:
			items = run(keywords, location, extra)
		except Exception as e:  # one failed search should not lose the rest
			print(f'search failed: {keywords} / {location}: {e}', file=sys.stderr)
			continue
		print(f'{keywords} / {location}: {len(items)} results')
		for j in items:
			url = (j.get('url') or '').split('?')[0]
			title = j.get('title') or ''
			key = (title.lower(), (j.get('companyName') or '').lower())
			if not url or url in seen or key in seen or SKIP.search(title):
				continue
			seen.update([url, key])
			label, n = applicants(j.get('applicationsCount'))
			rows.append({
				'title': title.strip(), 'company': (j.get('companyName') or '').strip(),
				'location': CITY.sub('', j.get('location') or '').strip() or 'India',
				'applicants': label, 'url': url, '_score': score(j), '_n': n,
				'_home': bool(HOME.search(CITY.sub('', j.get('location') or 'India').strip())),
				'_ai': bool(AI.search(title)),
			})

	if not rows:
		sys.exit('no jobs fetched; keeping the existing list')

	rows.sort(key=lambda r: (-r['_score'], r['_n']))
	angular = [r for r in rows if 'angular' in r['title'].lower()]
	ai = [r for r in rows if r['_ai']][:4]
	top = [r for r in rows if r['_home'] and not r['_ai'] and r['_score'] >= 6][:18]
	other = [r for r in angular if not r['_home'] and not r['_ai']][:4]
	for group, picked in (('top', top), ('ai', ai), ('other', other)):
		for r in picked:
			r['group'] = group

	jobs = [{k: v for k, v in r.items() if not k.startswith('_')} for r in top + ai + other]
	now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
	OUT.write_text(json.dumps({
		'updated': now.strftime('%Y-%m-%d %H:%M IST'),
		'source': 'LinkedIn, senior Angular roles posted in the last 7 days (Bengaluru, Hyderabad, remote India)',
		'jobs': jobs,
	}, indent='\t', ensure_ascii=False) + '\n')
	print(f'wrote {len(jobs)} jobs to {OUT}')


if __name__ == '__main__':
	main()
