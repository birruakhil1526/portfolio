"""Builds site/jobs/index.html from jobs/jobs.json, the daily job matches."""

import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / 'site' / 'jobs' / 'index.html'

GROUPS = [
	('top', 'Senior Angular roles', 'Angular frontend or Angular + Java / Spring Boot full stack, Bengaluru · Hyderabad · Remote'),
	('ai', 'Angular + AI / LLM', 'Angular roles that also use the Claude and LLM tooling work'),
	('other', 'Also worth a look', 'Strong fit, other city or a step up'),
]

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jobs · Birru's Space</title>
<meta name="robots" content="noindex, nofollow">
<meta name="theme-color" content="#0b0e14">
<script>try { if (localStorage.getItem('theme') === 'light') document.documentElement.dataset.theme = 'light'; } catch (e) {}</script>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' rx='12' fill='%230b0e14'/><text x='10' y='42' font-family='monospace' font-size='30' font-weight='700' fill='%237ee787'>&gt;_</text></svg>">
<style>
:root {
	--bg: #0b0e14; --surface: #11151c; --surface-2: #161b24; --line: #222a36;
	--text: #d6dde6; --muted: #8b96a5; --faint: #5c6675;
	--green: #7ee787; --blue: #79c0ff; --orange: #ffa657;
	--mono: ui-monospace, 'SF Mono', SFMono-Regular, 'Cascadia Code', 'JetBrains Mono', Menlo, Consolas, 'Liberation Mono', monospace;
	--sans: system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
	color-scheme: dark;
}
:root[data-theme="light"] {
	--bg: #f6f8fa; --surface: #ffffff; --surface-2: #f0f3f6; --line: #d8dee4;
	--text: #1f2328; --muted: #59636e; --faint: #8c959f;
	--green: #1a7f37; --blue: #0550ae; --orange: #bc4c00;
	color-scheme: light;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font: 15px/1.6 var(--sans); -webkit-font-smoothing: antialiased; }
a { color: var(--blue); text-decoration: none; }
a:hover { text-decoration: underline; }
.wrap { max-width: 860px; margin: 0 auto; padding: 0 16px; }
nav {
	position: sticky; top: 0; z-index: 10;
	background: color-mix(in srgb, var(--bg) 88%, transparent); backdrop-filter: blur(8px);
	border-bottom: 1px solid var(--line); font: 13px var(--mono);
}
nav .wrap { display: flex; align-items: center; justify-content: space-between; height: 48px; gap: 8px; }
.brand { color: var(--green); font-weight: 700; white-space: nowrap; }
.brand:hover { text-decoration: none; }
#theme {
	display: inline-flex; gap: 2px; padding: 2px; flex-shrink: 0;
	font: 12px var(--mono); background: var(--surface); color: var(--faint);
	border: 1px solid var(--line); border-radius: 999px; cursor: pointer;
}
#theme span { padding: 3px 9px; border-radius: 999px; }
#theme .d, :root[data-theme="light"] #theme .l { background: var(--surface-2); color: var(--text); box-shadow: 0 0 0 1px var(--line); }
:root[data-theme="light"] #theme .d { background: none; color: var(--faint); box-shadow: none; }
header { padding: 32px 0 8px; }
.eyebrow { font: 13px var(--mono); color: var(--green); }
h1 { font-size: clamp(26px, 5vw, 34px); line-height: 1.15; letter-spacing: -.03em; margin: 6px 0 8px; }
.meta { font: 12.5px var(--mono); color: var(--faint); }
section { padding: 24px 0 4px; }
h2 { font-size: 19px; letter-spacing: -.01em; }
.sub { color: var(--muted); font-size: 13.5px; margin: 2px 0 12px; }
.list { display: grid; gap: 10px; list-style: none; }
.job {
	display: block; padding: 12px 14px; border: 1px solid var(--line); border-radius: 12px;
	background: var(--surface); color: var(--text);
}
.job:hover { border-color: var(--blue); text-decoration: none; }
.job b { display: block; font-weight: 600; overflow-wrap: anywhere; }
.job small { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 4px; font: 12.5px var(--mono); color: var(--muted); }
.job .open { color: var(--blue); margin-left: auto; }
.job .few { color: var(--green); }
.job .many { color: var(--orange); }
footer { padding: 32px 0 40px; font: 12px var(--mono); color: var(--faint); }
</style>
</head>
<body>
<nav><div class="wrap">
	<a class="brand" href="/">~/birru</a>
	<button id="theme" type="button" aria-label="Switch theme"><span class="d">dark</span><span class="l">light</span></button>
</div></nav>
<main class="wrap">
	<header>
		<div class="eyebrow">$ cat jobs.json</div>
		<h1>Daily job matches</h1>
		<p class="meta">updated __UPDATED__ · __COUNT__ roles · __SOURCE__</p>
	</header>
__SECTIONS__
</main>
<footer class="wrap">refreshed every morning at 7 AM IST · tap a role to open it on LinkedIn and apply</footer>
<script>
	const root = document.documentElement;
	document.getElementById('theme').onclick = () => {
		const t = root.dataset.theme === 'light' ? 'dark' : 'light';
		root.dataset.theme = t;
		document.querySelector('meta[name="theme-color"]').content = t === 'light' ? '#f6f8fa' : '#0b0e14';
		try { localStorage.setItem('theme', t); } catch (e) {}
	};
	if (root.dataset.theme === 'light') document.querySelector('meta[name="theme-color"]').content = '#f6f8fa';
</script>
</body>
</html>
"""


def esc(s):
	return html.escape(str(s), quote=True)


def card(job):
	n = job.get('applicants', '')
	cls = 'few' if n.startswith('<') else 'many' if n.endswith('+') else ''
	return (
		f'\t\t<li><a class="job" href="{esc(job["url"])}" target="_blank" rel="noopener noreferrer">'
		f'<b>{esc(job["title"])}</b>'
		f'<small><span>{esc(job["company"])}</span><span>{esc(job["location"])}</span>'
		f'<span class="{cls}">{esc(n)} applicants</span><span class="open">open ↗</span></small></a></li>'
	)


def page(data):
	sections = []
	for key, title, sub in GROUPS:
		jobs = [j for j in data['jobs'] if j.get('group', 'top') == key]
		if not jobs:
			continue
		sections.append(
			f'\t<section>\n\t\t<h2>{esc(title)}</h2>\n\t\t<p class="sub">{esc(sub)}</p>\n'
			f'\t\t<ul class="list">\n' + '\n'.join(card(j) for j in jobs) + '\n\t\t</ul>\n\t</section>'
		)
	return (PAGE
		.replace('__UPDATED__', esc(data['updated']))
		.replace('__COUNT__', str(len(data['jobs'])))
		.replace('__SOURCE__', esc(data.get('source', '')))
		.replace('__SECTIONS__', '\n'.join(sections)))


if __name__ == '__main__':
	data = json.loads((HERE / 'jobs.json').read_text())
	OUT.parent.mkdir(parents=True, exist_ok=True)
	OUT.write_text(page(data))
