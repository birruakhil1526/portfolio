"""Builds site/study/index.html from the markdown guides in study/src, with diagrams and tips."""

import html
import re
from pathlib import Path

import diagrams as d

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / 'site' / 'study' / 'index.html'

GUIDES = [
	{
		'id': 'lending', 'tab': 'fintech-lending', 'src': 'fintech-lending-db-interview-guide.md',
		'fixes': [('combine an database', 'combine a database')],
		# (heading prefix, nth match) -> blocks placed at the end of that heading's content
		'end': [
			(('Fintech Lending Systems', 1), [d.lending_lifecycle]),
			(('2. Loan Origination System', 1), [d.los_states]),
			(('Normalized Database Schema', 1), ['tip:This <code>credit_score BETWEEN 300 AND 850</code> range is the US FICO scale. In Indian fintech interviews, mention that CIBIL scores run 300–900.']),
			(('Scenario A: Enforcing Idempotent', 1), [d.idempotency_sequence]),
			(('Normalized Database Schema', 2), [d.double_entry]),
			(('Scenario A: Concurrency Control', 1), [d.row_lock_timeline]),
			(('Scenario B: Repayment Waterfall', 1), [d.repayment_waterfall, 'tip:Watch out: <code>total_unpaid_interest</code> above sums the full <code>interest_component</code>, including parts already paid. A stricter version applies <code>paid_amount</code> to interest first and subtracts it.']),
			(('Core Responsibilities', 3), [d.dpd_buckets]),
			(('Normalized Database Schema', 3), [d.lending_er]),
			(('Scenario A: Automated Daily DPD', 1), ["tip:A gotcha worth raising: a loan that becomes current again drops out of the CTE, so its old bucket is never reset. Add a second step that sets <code>delinquency_bucket = 'CURRENT'</code> and <code>dpd_count = 0</code> for loans that are no longer overdue."]),
			(('Q1:', 1), [d.saga]),
			(('Q2:', 1), [d.hash_chain]),
			(('Q7:', 1), [d.timeout_polling]),
			(('Q9:', 1), [d.keyset_workers, 'tip:From your own work: when the same Spring Boot CRON job runs on several instances, a distributed lock such as ShedLock makes sure each run happens once.']),
			(('Q10:', 1), ['tip:From your own work: YugabyteDB is a CP database that uses Raft consensus per tablet, a concrete example you have run in production.']),
		],
	},
	{
		'id': 'system-design', 'tab': 'system-design', 'src': 'system-design-interview-guide.md',
		'fixes': [("A user author's multiple posts", 'A user authors multiple posts')],
		'end': [
			(('1. The Master System Design', 1), [d.sd_phases]),
			(('Phase 2:', 1), [d.sd_ladder]),
			(('Phase 3:', 1), [d.sd_hld]),
			(('Step 2:', 1), [d.sd_cardinality]),
			(('Step 4:', 1), ['tip:Precision point: the primary key is the clustered index in MySQL (InnoDB). In PostgreSQL, tables are heaps and the primary key is an ordinary B-tree index.']),
			(('Step 5:', 1), [d.sd_index_pagination]),
			(('Real-Time Architecture', 1), [d.sd_messaging]),
			(('Asynchronous Event-Driven Order', 1), [d.sd_orders]),
			(('Compute & Storage Architecture', 1), [d.sd_video]),
			(('Caching Strategies', 2), [d.sd_caching]),
			(('Replication Topologies', 1), [d.sd_replication]),
			(('Sharding Strategies', 1), [d.sd_sharding]),
			(('CAP Theorem', 1), [d.sd_cap]),
		],
	},
]

SQL_KW = set('''SELECT FROM WHERE AND OR NOT IN INSERT INTO VALUES UPDATE SET DELETE CREATE TABLE INDEX ON PRIMARY KEY
FOREIGN REFERENCES UNIQUE CHECK DEFAULT NULL CONSTRAINT CASCADE BEGIN COMMIT ROLLBACK FOR JOIN INNER LEFT GROUP BY
ORDER HAVING LIMIT OFFSET AS CASE WHEN THEN ELSE END WITH CONFLICT DO RETURNING EXCLUDED BETWEEN ASC DESC INTERVAL
GENERATED ALWAYS IDENTITY IS TRUE FALSE'''.split())
SQL_TYPES = set('UUID VARCHAR INT BIGINT NUMERIC DECIMAL TEXT BOOLEAN DATE TIMESTAMP TIME ZONE BIGSERIAL'.split())
SQL_FN = set('COUNT SUM MAX MIN COALESCE NOW GEN_RANDOM_UUID CURRENT_TIMESTAMP CURRENT_DATE'.split())
SQL_TOK = re.compile(r"(--[^\n]*)|('(?:[^']|'')*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z_0-9]*)|(\s+|.)", re.S)


def esc(s):
	return html.escape(s, quote=False)


def highlight_sql(src):
	out = []
	for m in SQL_TOK.finditer(src):
		comment, string, num, word, other = m.groups()
		if comment:
			out.append(f'<span class="c-f">{esc(comment)}</span>')
		elif string:
			out.append(f'<span class="c-s">{esc(string)}</span>')
		elif num:
			out.append(f'<span class="c-o">{num}</span>')
		elif word:
			up = word.upper()
			cls = 'c-p' if up in SQL_KW else 'c-y' if up in SQL_TYPES else 'c-b' if up in SQL_FN else ''
			out.append(f'<span class="{cls}">{word}</span>' if cls else esc(word))
		else:
			out.append(esc(other))
	return ''.join(out)


def math(t):
	t = t.replace('\\rightarrow', '→')
	t = re.sub(r'\\text\{([^}]*)\}', r'\1', t)
	t = re.sub(r'_\{([^}]*)\}', r'<sub>\1</sub>', t)
	return re.sub(r'_(\w)', r'<sub>\1</sub>', t)


def inline(s):
	codes = []

	def keep(m):
		codes.append(m.group(1))
		return f'\x00{len(codes) - 1}\x00'

	s = re.sub(r'`([^`]+)`', keep, s)
	s = esc(s)
	s = re.sub(r'\$([^$]+)\$', lambda m: f'<span class="m">{math(m.group(1))}</span>', s)
	s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
	s = re.sub(r'(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])', r'<em>\1</em>', s)
	return re.sub('\x00(\\d+)\x00', lambda m: f'<code>{esc(codes[int(m.group(1))])}</code>', s)


LIST_RE = re.compile(r'^\s*(\*|-|\d+\.)\s+(.*)$')


def parse(md):
	lines, blocks, para, i = md.split('\n'), [], [], 0

	def flush():
		if para:
			blocks.append(('p', ' '.join(para)))
			para.clear()

	while i < len(lines):
		ln = lines[i]
		if ln.startswith('```'):
			flush()
			lang, code = ln[3:].strip(), []
			i += 1
			while not lines[i].startswith('```'):
				code.append(lines[i])
				i += 1
			blocks.append(('code', lang, '\n'.join(code)))
			i += 1
			continue
		m = re.match(r'^(#{1,4})\s+(.*)$', ln)
		if m:
			flush()
			blocks.append(('h', len(m.group(1)), m.group(2).strip()))
		elif ln.strip() == '---':
			flush()
		elif ln.startswith('>'):
			flush()
			quote = []
			while i < len(lines) and lines[i].startswith('>'):
				quote.append(lines[i].lstrip('>').strip())
				i += 1
			blocks.append(('quote', ' '.join(quote)))
			continue
		elif ln.startswith('|'):
			flush()
			rows = []
			while i < len(lines) and lines[i].startswith('|'):
				rows.append(lines[i])
				i += 1
			blocks.append(('table', rows))
			continue
		elif LIST_RE.match(ln):
			flush()
			ordered, items = LIST_RE.match(ln).group(1)[0].isdigit(), []
			while i < len(lines) and LIST_RE.match(lines[i]):
				items.append(LIST_RE.match(lines[i]).group(2))
				i += 1
			blocks.append(('list', ordered, items))
			continue
		elif not ln.strip():
			flush()
		else:
			para.append(ln.strip())
		i += 1
	flush()
	return blocks


def render_block(b):
	kind = b[0]
	if kind == 'p':
		return f'<p>{inline(b[1])}</p>'
	if kind == 'code':
		lang, src = b[1], b[2]
		body = highlight_sql(src) if lang == 'sql' else esc(src)
		return (f'<div class="code"><div class="code-h"><span>{lang or "text"}</span>'
				f'<button class="copy" type="button">copy</button></div><pre><code>{body}</code></pre></div>')
	if kind == 'quote':
		return f'<div class="callout">{inline(b[1])}</div>'
	if kind == 'list':
		tag = 'ol' if b[1] else 'ul'
		return f'<{tag}>' + ''.join(f'<li>{inline(it)}</li>' for it in b[2]) + f'</{tag}>'
	if kind == 'table':
		rows = [[c.strip() for c in r.strip().strip('|').split('|')] for r in b[1]]
		head = ''.join(f'<th>{inline(c)}</th>' for c in rows[0])
		body = ''.join('<tr>' + ''.join(f'<td>{inline(c)}</td>' for c in r) + '</tr>' for r in rows[2:])
		return f'<div class="tbl"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
	raise ValueError(kind)


def slugify(text, used):
	base = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:48].strip('-')
	s, n = base, 2
	while s in used:
		s, n = f'{base}-{n}', n + 1
	used.add(s)
	return s


def extra(item):
	if isinstance(item, str) and item.startswith('tip:'):
		return f'<div class="callout note">{item[4:]}</div>'
	return item()


def build_guide(g):
	md = (HERE / 'src' / g['src']).read_text()
	for old, new in g['fixes']:
		assert old in md, old
		md = md.replace(old, new)
	blocks = parse(md)
	headings = [b[2] for b in blocks if b[0] == 'h']

	ends = {}
	for (prefix, nth), items in g['end']:
		hits = [i for i, h in enumerate(headings) if h == prefix or h.startswith(prefix)]
		assert len(hits) >= nth, f'no heading #{nth} for {prefix!r}'
		ends.setdefault(hits[nth - 1], []).extend(extra(it) for it in items)

	used, out, toc = set(), [], []
	title, hidx, open_sec, open_qa = '', -1, False, False

	def close_end():
		if hidx >= 0:
			out.extend(ends.get(hidx, []))

	for b in blocks:
		if b[0] != 'h':
			out.append(render_block(b))
			continue
		close_end()
		hidx += 1
		level, text = b[1], b[2]
		if open_qa and level <= 3:
			out.append('</div></details>')
			open_qa = False
		if level == 1:
			title = text
			out.append('<div class="intro">')
			continue
		sid = f'{g["id"]}--{slugify(text, used)}'
		if level == 2:
			if open_sec:
				out.append('</section>')
			else:
				out.append('</div>')
			toc.append((sid, re.sub(r'^\d+\.\s*', '', text)))
			out.append(f'<section class="sec" id="{sid}"><div class="sec-h"><h2>{inline(text)}</h2>'
					   f'<label class="done-box"><input type="checkbox" data-sec="{sid}"> done</label></div>')
			open_sec = True
		elif level == 3 and re.match(r'Q\d+:', text):
			num, rest = text.split(':', 1)
			out.append(f'<details class="qa" id="{sid}"><summary><span class="qn">{num}</span>'
					   f'<span>{inline(rest.strip())}</span></summary><div class="qa-a">')
			open_qa = True
		else:
			out.append(f'<h{level} id="{sid}">{inline(text)}</h{level}>')
	close_end()
	if open_qa:
		out.append('</div></details>')
	out.append('</section>')

	body = ''.join(out)
	figs = body.count('<figure')
	words = len(re.sub(r'<[^>]+>', ' ', body).split())
	return {'title': title, 'body': body, 'toc': toc, 'figs': figs, 'mins': max(1, round(words / 200))}


def page(guides):
	tabs = ''.join(f'<a href="#{g["id"]}" data-guide="{g["id"]}">{g["tab"]}</a>' for g in GUIDES)
	articles = []
	for g, r in zip(GUIDES, guides):
		toc = ''.join(f'<a href="#{sid}"><span class="tick"></span><span>{inline(t)}</span></a>' for sid, t in r['toc'])
		articles.append(f'''
<article class="guide" data-guide="{g['id']}" id="{g['id']}-guide" hidden>
	<div class="layout">
		<details class="toc" open>
			<summary>contents</summary>
			<div class="prog"><b><i></i></b><span></span></div>
			<nav>{toc}</nav>
		</details>
		<div class="doc">
			<div class="g-head">
				<div class="eyebrow">study/{g['tab']}.md</div>
				<h1>{inline(r['title'])}</h1>
				<div class="meta">~{r['mins']} min read · {r['figs']} diagrams · {len(r['toc'])} sections</div>
				<div class="prog"><b><i></i></b><span></span></div>
			</div>
			{r['body']}
		</div>
	</div>
</article>''')
	return TEMPLATE.replace('{{TABS}}', tabs).replace('{{DEFS}}', d.DEFS).replace('{{ARTICLES}}', ''.join(articles))


TEMPLATE = (HERE / 'template.html').read_text()

if __name__ == '__main__':
	built = [build_guide(g) for g in GUIDES]
	OUT.parent.mkdir(parents=True, exist_ok=True)
	OUT.write_text(page(built))
	for g, r in zip(GUIDES, built):
		print(f"{g['id']}: {len(r['toc'])} sections, {r['figs']} diagrams, ~{r['mins']} min")
	print(f'wrote {OUT} ({OUT.stat().st_size // 1024} KB)')
