"""Inline SVG diagrams for the study page. Colours come from the page's CSS tokens."""

from html import escape


def esc(s):
	return escape(str(s), quote=True)


def fig(w, h, body, caption):
	return (
		f'<figure class="fig"><div class="fig-scroll">'
		f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{esc(caption)}">{body}</svg>'
		f'</div><figcaption>{esc(caption)}</figcaption></figure>'
	)


def box(x, y, w, h, lines, tone='', size=12):
	if isinstance(lines, str):
		lines = lines.split('\n')
	out = [f'<rect class="bx {tone}" x="{x}" y="{y}" width="{w}" height="{h}" rx="8"/>']
	lh = size + 4
	cy = y + h / 2 - (len(lines) - 1) * lh / 2
	for i, line in enumerate(lines):
		cls = 't'
		if len(lines) > 1:
			cls += ' tb' if i == 0 else ' ts'
		out.append(
			f'<text class="{cls}" x="{x + w / 2}" y="{cy + i * lh}" text-anchor="middle" '
			f'dominant-baseline="central">{esc(line)}</text>'
		)
	return ''.join(out)


def txt(x, y, s, cls='lb', anchor='middle'):
	return f'<text class="{cls}" x="{x}" y="{y}" text-anchor="{anchor}">{esc(s)}</text>'


def _marker(tone, start=False, end=True):
	m = f'url(#ah{"-" + tone if tone else ""})'
	return (f' marker-start="{m}"' if start else '') + (f' marker-end="{m}"' if end else '')


def arrow(x1, y1, x2, y2, tone='', dash=False, label=None, lx=None, ly=None, anchor='middle', both=False, head=True):
	cls = f'ln {tone}' + (' dash' if dash else '')
	out = f'<line class="{cls}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"{_marker(tone, both, head)}/>'
	if label:
		lx = (x1 + x2) / 2 if lx is None else lx
		ly = (y1 + y2) / 2 - 7 if ly is None else ly
		out += txt(lx, ly, label, f'lb {tone}', anchor)
	return out


def curve(d, tone='', dash=False, label=None, lx=0, ly=0, anchor='middle'):
	cls = f'ln {tone}' + (' dash' if dash else '')
	out = f'<path class="{cls}" d="{d}"{_marker(tone)}/>'
	if label:
		out += txt(lx, ly, label, f'lb {tone}', anchor)
	return out


def line(x1, y1, x2, y2, cls='ln'):
	return f'<line class="{cls}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>'


MARKERS = ''.join(
	f'<marker id="ah{"-" + t if t else ""}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
	f'markerHeight="6" orient="auto-start-reverse"><path class="mk {t}" d="M0,0 L10,5 L0,10 z"/></marker>'
	for t in ['', 'g', 'b', 'r', 'o', 'p', 'y']
)
DEFS = f'<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>{MARKERS}</defs></svg>'


# ---------- fintech lending ----------

def lending_lifecycle():
	b = []
	panels = [
		(10, 'b', 'LOS · origination', ['onboard + KYC', 'credit bureau score', 'underwriting', 'approve / reject']),
		(290, 'g', 'LMS · management', ['disburse loan', 'EMI schedule', 'daily interest accrual', 'repay → ledger']),
		(570, 'o', 'LCS · collection', ['compute DPD', 'bucket 1–3 / NPA', 'assign agent + PTP', 'settle / write-off']),
	]
	for x, tone, title, steps in panels:
		b.append(f'<rect class="pn {tone}" x="{x}" y="10" width="210" height="270" rx="12"/>')
		b.append(txt(x + 105, 38, title, 'h'))
		for i, s in enumerate(steps):
			y = 56 + i * 54
			b.append(box(x + 15, y, 180, 38, s))
			if i < 3:
				b.append(arrow(x + 105, y + 38, x + 105, y + 52))
	b.append(arrow(220, 150, 288, 150, 'b', label='disburse', ly=140))
	b.append(arrow(500, 150, 568, 150, 'o', label='EMI missed', ly=140))
	b.append(curve('M 675 281 C 675 322, 395 322, 395 283', 'g', True, 'paid / restructured', 535, 326))
	return fig(790, 335, ''.join(b), 'The credit lifecycle: a loan moves LOS → LMS, and into LCS only when payments are missed')


def los_states():
	b = []
	states = [(10, 'DRAFT', ''), (165, 'SUBMITTED', 'b'), (320, 'UNDERWRITING', 'p'), (475, 'APPROVED', 'g'), (630, 'DISBURSED', 'g')]
	for i, (x, s, tone) in enumerate(states):
		b.append(box(x, 62, 125, 40, s, tone))
		if i < 4:
			b.append(arrow(x + 125, 82, states[i + 1][0] - 2, 82))
	b.append(curve('M 362 62 C 350 20, 415 20, 403 60', 'p', label='MANUAL_REVIEW', lx=382, ly=18))
	b.append(box(320, 140, 125, 36, 'REJECTED', 'r'))
	b.append(arrow(382, 102, 382, 138, 'r', label='decision = REJECT', lx=392, ly=124, anchor='start'))
	b.append(txt(692, 122, 'hands over to LMS', 'lb g'))
	return fig(790, 185, ''.join(b), 'loan_applications.status as a state machine: only forward moves, enforced by the CHECK constraint')


def idempotency_sequence():
	b = []
	for x, name in [(110, 'client'), (395, 'API'), (680, 'database')]:
		b.append(box(x - 70, 8, 140, 32, name, 'b'))
		b.append(line(x, 40, x, 270, 'ln dash faint'))
	msgs = [
		(72, 110, 395, 'POST /applications · key=K1', '', False),
		(98, 395, 680, 'INSERT … idempotency_key=K1', '', False),
		(124, 680, 395, 'row created: app-123', '', True),
		(150, 395, 110, '201 sent · response lost ✕', 'r', True),
		(186, 110, 395, 'retry with the same key=K1', 'o', False),
		(212, 395, 680, 'ON CONFLICT (key) → same row', '', False),
		(238, 680, 395, 'returns app-123', '', True),
		(262, 395, 110, '200 · app-123 · no duplicate', 'g', False),
	]
	for y, a, c, label, tone, dash in msgs:
		x2 = c - 3 if c > a else c + 3
		b.append(arrow(a, y, x2, y, tone, dash, label))
	return fig(790, 280, ''.join(b), 'Idempotency key: a retried request finds the existing row instead of creating a second loan')


def row_lock_timeline():
	b = [txt(10, 72, 'auto-debit job', 't', 'start'), txt(10, 142, 'mobile payment', 't', 'start')]
	b.append(box(170, 50, 95, 36, 'BEGIN · lock', 'g'))
	b.append(box(267, 50, 200, 36, 'update EMI + loan', 'b'))
	b.append(box(469, 50, 70, 36, 'COMMIT', 'g'))
	b.append(box(230, 120, 70, 36, 'BEGIN'))
	b.append(box(302, 120, 236, 36, 'waiting for row lock…', 'o dash'))
	b.append(box(540, 120, 170, 36, 'lock → new balance', 'g'))
	b.append(box(712, 120, 70, 36, 'COMMIT', 'g'))
	b.append(line(539, 38, 539, 165, 'ln g dash'))
	b.append(txt(539, 30, 'lock released', 'lb g'))
	b.append(arrow(170, 186, 780, 186))
	b.append(txt(170, 204, 'time →', 'lb', 'start'))
	return fig(790, 212, ''.join(b), 'SELECT … FOR UPDATE: the second payment waits, then reads the already-updated balance')


def repayment_waterfall():
	b = [box(10, 50, 150, 60, 'payment\n₹1,500 received', 'b')]
	b.append(box(215, 50, 165, 60, '1 · penalties & fees\n₹100 cleared', 'r'))
	b.append(box(420, 50, 165, 60, '2 · accrued interest\n₹400 cleared', 'o'))
	b.append(box(625, 50, 160, 60, '3 · principal\n₹1,000 reduced', 'g'))
	b.append(arrow(160, 80, 213, 80))
	b.append(arrow(380, 80, 418, 80, label='₹1,400 left', ly=40))
	b.append(arrow(585, 80, 623, 80, label='₹1,000 left', ly=40))
	b.append(txt(395, 145, 'anything left after principal is an excess payment / prepayment'))
	return fig(790, 160, ''.join(b), 'Repayment waterfall (example amounts): each bucket is cleared before money reaches the next')


def double_entry():
	b = [box(270, 10, 250, 42, 'repayment_transaction\n₹1,250 EMI received', 'b')]
	accounts = [(20, 'CASH_ACCOUNT', 'Dr', '1,250'), (285, 'PRINCIPAL_RECEIVABLE', 'Cr', '1,000'), (550, 'INTEREST_INCOME', 'Cr', '250')]
	for x, name, side, amt in accounts:
		b.append(arrow(395, 52, x + 110, 88))
		b.append(txt(x + 110, 106, name, 'h'))
		b.append(line(x, 116, x + 220, 116, 'ln strong'))
		b.append(line(x + 110, 116, x + 110, 186, 'ln strong'))
		b.append(txt(x + 55, 134, 'Dr (debit)', 'ts'))
		b.append(txt(x + 165, 134, 'Cr (credit)', 'ts'))
		tone = 'g' if side == 'Dr' else 'o'
		b.append(txt(x + 55 if side == 'Dr' else x + 165, 164, amt, f'amt {tone}'))
	b.append(txt(395, 220, 'Σ debits 1,250 = Σ credits 1,250  ✓ balanced', 'lb g'))
	return fig(790, 232, ''.join(b), 'Double-entry: one repayment becomes balanced ledger rows; debits always equal credits')


def _table(x, y, name, rows, tone):
	h = 26 + 20 * len(rows) + 6
	out = [f'<rect class="bx {tone}" x="{x}" y="{y}" width="220" height="{h}" rx="8"/>']
	out.append(txt(x + 10, y + 18, name, 'h', 'start'))
	out.append(line(x, y + 26, x + 220, y + 26, f'ln {tone}'))
	for i, (col, tag) in enumerate(rows):
		cy = y + 42 + i * 20
		out.append(txt(x + 10, cy, col, 'ts', 'start'))
		if tag:
			out.append(txt(x + 210, cy, tag, f'lb {tone}', 'end'))
	return ''.join(out)


def lending_er():
	b = []
	tables = [
		(10, 20, 'borrowers', [('borrower_id', 'PK'), ('national_id', 'UQ')], 'b'),
		(10, 140, 'loan_applications', [('application_id', 'PK'), ('borrower_id', 'FK'), ('idempotency_key', 'UQ')], 'b'),
		(10, 290, 'credit_assessments', [('assessment_id', 'PK'), ('application_id', 'FK')], 'b'),
		(285, 20, 'repayment_schedules', [('loan_id', 'FK'), ('installment_number', 'UQ')], 'g'),
		(285, 140, 'loans', [('loan_id', 'PK'), ('application_id', 'FK·UQ')], 'g'),
		(285, 260, 'repayment_transactions', [('transaction_id', 'PK'), ('loan_id', 'FK')], 'g'),
		(285, 352, 'general_ledger', [('ledger_id', 'PK'), ('transaction_id', 'FK')], 'g'),
		(560, 20, 'delinquency_records', [('loan_id', 'FK·UQ'), ('dpd_count, bucket', '')], 'o'),
		(560, 140, 'collection_cases', [('case_id', 'PK'), ('loan_id', 'FK')], 'o'),
		(560, 260, 'promise_to_pay', [('ptp_id', 'PK'), ('case_id', 'FK')], 'o'),
	]
	rels = [
		(120, 92, 120, 140, '1:N'), (120, 232, 120, 290, '1:N'), (230, 180, 285, 180, '1:1'),
		(395, 140, 395, 92, '1:N'), (395, 212, 395, 260, '1:N'), (395, 332, 395, 352, '1:N'),
		(505, 160, 560, 60, '1:1'), (505, 190, 560, 190, '1:N'), (670, 212, 670, 260, '1:N'),
	]
	for x1, y1, x2, y2, label in rels:
		b.append(line(x1, y1, x2, y2, 'ln'))
		if x1 == x2:
			b.append(txt(x1 + 10, (y1 + y2) / 2 + 4, label, 'lb', 'start'))
		else:
			b.append(txt((x1 + x2) / 2, (y1 + y2) / 2 - 6, label, 'lb'))
	for t in tables:
		b.append(_table(*t))
	b.append(txt(20, 400, '■ LOS', 'lb b', 'start'))
	b.append(txt(85, 400, '■ LMS', 'lb g', 'start'))
	b.append(txt(150, 400, '■ LCS', 'lb o', 'start'))
	return fig(790, 432, ''.join(b), 'How all ten tables connect across LOS, LMS and LCS (key columns only)')


def dpd_buckets():
	b = [txt(10, 26, 'days past due →', 'lb', 'start')]
	segs = [(10, 110, 'CURRENT', '0 days', 'g'), (125, 150, 'BUCKET_1', '1–30', 'y'), (280, 150, 'BUCKET_2', '31–60', 'o'),
			(435, 150, 'BUCKET_3', '61–90', 'r'), (590, 90, 'NPA', '> 90', 'r'), (685, 100, 'WRITE_OFF', 'policy', 'p')]
	for x, w, name, days, tone in segs:
		b.append(box(x, 40, w, 50, [name, days], tone))
	b.append(txt(395, 122, 'nightly batch → recompute DPD → move bucket → pick collection strategy'))
	return fig(790, 135, ''.join(b), 'Delinquency buckets: the later the bucket, the more aggressive the collection action')


def saga():
	b = [box(10, 60, 110, 50, 'LOS\napproves', 'b'), box(260, 60, 200, 50, 'LMS\nPENDING_DISBURSEMENT', 'g'),
		 box(560, 60, 150, 50, 'payment\ngateway', 'p')]
	b.append(arrow(120, 85, 258, 85, label='LoanApprovedEvent', ly=75))
	b.append(arrow(460, 85, 558, 85, label='disburse', ly=75))
	b.append(box(560, 172, 150, 44, 'loan → ACTIVE', 'g'))
	b.append(arrow(635, 110, 635, 170, 'g', label='success', lx=645, ly=144, anchor='start'))
	b.append(box(200, 172, 290, 44, 'compensate:\nCancelLoanDisbursement', 'r'))
	b.append(arrow(585, 110, 492, 186, 'r', True, 'permanent failure', 545, 146))
	b.append(arrow(345, 172, 345, 112, 'r', True, 'roll back', 355, 146, 'start'))
	return fig(790, 228, ''.join(b), 'Saga with a compensating event instead of a blocking two-phase commit')


def hash_chain():
	b = []
	entries = [('entry #41', '₹1,250 DR CASH', '0000…', '9f2c…'), ('entry #42', '₹1,000 CR PRINCIPAL', '9f2c…', 'a71e…'),
			   ('entry #43', '₹250 CR INTEREST', 'a71e…', '3bd0…'), ('entry #44', '₹500 DR CASH', '3bd0…', 'c58f…')]
	for i, (title, payload, prev, h) in enumerate(entries):
		x = 10 + i * 195
		b.append(f'<rect class="bx" x="{x}" y="25" width="175" height="95" rx="8"/>')
		b.append(txt(x + 12, 46, title, 'h', 'start'))
		b.append(txt(x + 12, 68, payload, 'ts', 'start'))
		b.append(txt(x + 12, 88, f'prev: {prev}', 'lb o', 'start'))
		b.append(txt(x + 12, 108, f'hash: {h}', 'lb g', 'start'))
		if i < 3:
			b.append(arrow(x + 175, 98, x + 193, 98, 'o'))
	b.append(txt(395, 148, 'change any old row → its hash changes → every later prev hash stops matching'))
	return fig(790, 160, ''.join(b), 'Tamper-evident ledger: each row stores the hash of the row before it')


def timeout_polling():
	b = [box(10, 70, 120, 50, 'disburse\nrequest', 'b'), box(165, 70, 140, 50, 'gateway times\nout → UNKNOWN', 'o'),
		 box(345, 70, 190, 50, 'store\nPENDING_VERIFICATION', 'p'), box(575, 70, 205, 50, 'worker polls status\nwith same idempotency key', 'b')]
	b.append(arrow(130, 95, 163, 95))
	b.append(arrow(305, 95, 343, 95))
	b.append(arrow(535, 95, 573, 95))
	b.append(curve('M 640 70 C 640 24, 720 24, 720 68', '', label='still pending → retry later', lx=680, ly=20))
	b.append(box(575, 172, 205, 44, 'SUCCESS → DISBURSED', 'g'))
	b.append(arrow(677, 120, 677, 170, 'g'))
	b.append(box(345, 172, 190, 44, 'FAILED → mark failed', 'r'))
	b.append(arrow(600, 120, 537, 180, 'r', label='definitive failure', lx=548, ly=146, anchor='end'))
	return fig(790, 228, ''.join(b), 'A timeout is not a failure: park it, verify with the provider, then decide')


def keyset_workers():
	b = [box(10, 70, 150, 54, 'scheduler\nnightly accrual', 'b'), arrow(160, 97, 208, 97)]
	b.append(f'<rect class="bx p" x="210" y="50" width="330" height="95" rx="10"/>')
	b.append(txt(375, 70, 'message queue', 'h'))
	for i, (a, c) in enumerate([('chunk 1', '≤ 1000'), ('chunk 2', '≤ 2000'), ('chunk 3', '≤ 3000'), ('…', '')]):
		b.append(box(220 + i * 78, 84, 72, 46, [a, c] if c else a))
	for y in (15, 77, 139):
		b.append(box(600, y, 180, 40, f'worker {(y - 15) // 62 + 1}', 'g'))
		b.append(arrow(540, 97, 598, y + 20))
	b.append(txt(10, 192, 'each chunk = WHERE loan_id > :last_id ORDER BY loan_id LIMIT 1000', 'lb', 'start'))
	return fig(790, 202, ''.join(b), 'Keyset chunks on a queue let several workers share a 10M-loan batch job')


# ---------- system design ----------

def sd_phases():
	b = []
	phases = [('1 · clarify', 'FR vs NFR · ~5m', 'b'), ('2 · classify', 'data or compute?', 'p'),
			  ('3 · HLD', 'components · ~10m', 'g'), ('4 · schema', 'DDL + SQL · ~10m', 'o'),
			  ('5 · deep dive', 'bottlenecks · ~10m', 'r')]
	for i, (a, c, tone) in enumerate(phases):
		x = 10 + i * 156
		b.append(box(x, 30, 140, 60, [a, c], tone))
		if i < 4:
			b.append(arrow(x + 140, 60, x + 154, 60))
	b.append(txt(395, 118, 'times are a suggested split for a 45-minute round'))
	return fig(790, 130, ''.join(b), 'The five-phase interview flow')


def sd_ladder():
	b = []
	labels = ['1 · optimise code', '2 · scale up', '3 · scale out', '4 · distributed DB', '5 · load balancer']
	tones = ['b', 'p', 'g', 'o', 'r']
	for i, (s, tone) in enumerate(zip(labels, tones)):
		x, y = 10 + i * 155, 150 - i * 33
		b.append(box(x, y, 150, 40, s, tone))
	b.append(curve('M 85 196 C 400 196, 705 150, 705 60', '', True))
	b.append(txt(10, 208, 'more users, more traffic →', 'lb', 'start'))
	return fig(790, 215, ''.join(b), 'How systems typically evolve: fix the code first, add hardware later')


def sd_hld():
	b = [box(10, 105, 95, 50, 'clients\nweb · app'), box(130, 105, 110, 50, 'DNS + CDN\nstatic assets', 'b'),
		 box(265, 105, 110, 50, 'load\nbalancer', 'p')]
	b.append(arrow(105, 130, 128, 130))
	b.append(arrow(240, 130, 263, 130))
	for i, y in enumerate((55, 112, 169)):
		b.append(box(405, y, 130, 36, f'service {i + 1}', 'g'))
		b.append(arrow(375, 130, 403, y + 18))
	b.append(box(580, 25, 120, 46, 'Redis\ncache', 'o'))
	b.append(box(580, 107, 120, 46, 'SQL / NoSQL\ndatabase', 'b'))
	b.append(box(580, 190, 120, 46, 'message\nqueue', 'p'))
	b.append(box(715, 190, 70, 46, 'workers', 'g'))
	for y in (48, 130, 213):
		b.append(arrow(535, 130, 578, y))
	b.append(arrow(700, 213, 713, 213))
	b.append(curve('M 750 190 C 750 130, 730 130, 702 130', '', True))
	return fig(790, 250, ''.join(b), 'A standard high-level architecture: stateless services behind a load balancer')


def sd_cardinality():
	b = [box(10, 45, 95, 36, 'users', 'b'), box(150, 45, 95, 36, 'profile', 'b'), line(105, 63, 150, 63)]
	b += [txt(113, 56, '1', 'lb', 'start'), txt(142, 56, '1', 'lb', 'end'), txt(127, 135, '1 : 1  (FK + UNIQUE)')]
	b += [box(280, 45, 95, 36, 'users', 'g'), box(430, 45, 95, 36, 'posts', 'g'), line(375, 63, 430, 63)]
	b += [line(416, 63, 430, 53), line(416, 63, 430, 73), txt(383, 56, '1', 'lb', 'start'), txt(408, 52, 'N', 'lb', 'end')]
	b.append(txt(402, 135, '1 : N  (FK on the child)'))
	b += [box(560, 15, 100, 36, 'students', 'o'), box(685, 15, 95, 36, 'courses', 'o'), box(605, 95, 135, 36, 'enrollments', 'p')]
	b += [line(610, 51, 640, 95), line(732, 51, 705, 95)]
	b += [txt(618, 70, '1', 'lb', 'end'), txt(632, 92, 'N', 'lb', 'end'), txt(726, 70, '1', 'lb', 'start'), txt(712, 92, 'N', 'lb', 'start')]
	b.append(txt(672, 155, 'N : M  (junction table)'))
	return fig(790, 165, ''.join(b), 'The three relationship types and how each is stored')


def sd_index_pagination():
	b = [txt(10, 22, 'INDEX (user_id, created_at)', 'h', 'start'), box(10, 35, 120, 32, 'user_id', 'b'),
		 box(132, 35, 120, 32, 'created_at', 'b')]
	b.append(txt(10, 100, '✓ WHERE user_id = 7', 'lb g', 'start'))
	b.append(txt(10, 126, '✓ WHERE user_id = 7 AND created_at > t', 'lb g', 'start'))
	b.append(txt(10, 152, '✗ WHERE created_at > t  (skips 1st column)', 'lb r', 'start'))
	b.append(txt(10, 190, 'leftmost prefix rule: filter from the left', 'lb', 'start'))
	b.append(txt(410, 22, 'OFFSET vs cursor', 'h', 'start'))
	b.append(txt(410, 52, 'OFFSET 10000 LIMIT 20', 't', 'start'))
	b.append(box(410, 62, 370, 26, 'reads 10,020 rows · keeps 20', 'r'))
	b.append(txt(410, 122, 'WHERE id < :last ORDER BY id DESC LIMIT 20', 't', 'start'))
	b.append(f'<rect class="bx g" x="410" y="132" width="40" height="26" rx="6"/>')
	b.append(txt(460, 150, 'index seek → reads 20 rows', 'lb g', 'start'))
	b.append(txt(410, 190, 'offset cost grows with page depth; cursor stays flat', 'lb', 'start'))
	return fig(790, 205, ''.join(b), 'Composite index prefix rule, and why cursor pagination beats OFFSET')


def sd_messaging():
	b = [box(10, 40, 105, 46, 'sender', 'b'), box(165, 40, 140, 46, 'WS gateway A', 'g'),
		 box(165, 180, 140, 46, 'messages DB', 'o'), box(370, 110, 140, 46, 'Kafka\nbroker', 'p'),
		 box(560, 180, 225, 46, 'Redis\nuser → gateway map', 'y'), box(560, 40, 120, 46, 'WS gateway B', 'g'),
		 box(705, 40, 80, 46, 'recipient', 'b')]
	b.append(arrow(115, 63, 163, 63, label='1 send', ly=55, both=True))
	b.append(arrow(235, 86, 235, 178, label='2 persist', lx=245, ly=136, anchor='start'))
	b.append(arrow(305, 76, 368, 122, label='3 publish', lx=332, ly=118, anchor='end'))
	b.append(arrow(510, 145, 572, 178, label='4 who holds user?', lx=545, ly=176, anchor='end'))
	b.append(arrow(510, 122, 572, 80, label='5 route', lx=558, ly=112, anchor='start'))
	b.append(arrow(680, 63, 703, 63, both=True))
	b.append(txt(692, 30, 'push'))
	return fig(790, 240, ''.join(b), 'Real-time chat: persistent sockets, a broker, and a map of which gateway holds each user')


def sd_orders():
	b = [box(10, 85, 175, 60, 'checkout (ACID txn)\nlock · deduct · insert', 'g'), box(240, 85, 140, 60, 'broker\ntopic', 'p')]
	b.append(arrow(185, 115, 238, 115, label='OrderCreated', ly=75))
	for y, name in [(15, 'payment service'), (93, 'inventory · fulfil'), (171, 'notification')]:
		b.append(box(440, y, 165, 44, name, 'b'))
		b.append(arrow(380, 115, 438, y + 22))
	b.append(box(650, 93, 135, 44, 'dead letter\nqueue', 'r'))
	b.append(curve('M 605 193 C 717 193, 717 170, 717 139', 'r', True, 'after N retries', 690, 218))
	return fig(790, 228, ''.join(b), 'Sync ACID checkout, then async consumers; poison messages park in a DLQ')


def sd_video():
	b = [box(10, 30, 110, 50, 'creator', 'b'), box(175, 30, 150, 50, 'object storage\n(S3)', 'o'),
		 box(380, 30, 150, 50, 'transcode\nqueue', 'p'), box(585, 30, 195, 50, 'GPU workers\nH.264 / AV1', 'g'),
		 box(585, 150, 195, 50, 'renditions\n1080p · 720p · 480p', 'y'), box(380, 150, 150, 50, 'CDN edge', 'b'),
		 box(175, 150, 150, 50, 'player\nABR picks bitrate', 'g')]
	b.append(arrow(120, 55, 173, 55, label='pre-signed', ly=22))
	b.append(arrow(325, 55, 378, 55, label='event', ly=22))
	b.append(arrow(530, 55, 583, 55))
	b.append(arrow(682, 80, 682, 148, label='2–10 s segments', lx=692, ly=118, anchor='start'))
	b.append(arrow(585, 175, 532, 175))
	b.append(arrow(380, 175, 327, 175, label='manifest', ly=143))
	b.append(txt(147, 102, 'bypasses API servers'))
	return fig(790, 215, ''.join(b), 'Video: upload straight to storage, transcode on GPUs, stream adaptive bitrates from the CDN')


def sd_caching():
	b = []
	panels = [
		(10, 10, 'read-through', [('ab', '1 get'), ('cd', '2 on miss'), ('ca', '3 return')], 'cache loads data itself on a miss', ''),
		(400, 10, 'write-through', [('ab', '1 write'), ('cd', '2 sync write'), ('ca', '3 ack')], 'always consistent · slower writes', ''),
		(10, 190, 'write-around', [('ad', '1 write → DB'), ('dc', '2 filled on next read')], 'no cache pollution on write-heavy data', ''),
		(400, 190, 'write-back', [('ab', '1 write + ack'), ('cd', '2 async flush')], 'fast writes · lost if cache dies first', 'r'),
	]
	for px, py, title, flows, note, note_tone in panels:
		b.append(f'<rect class="pn" x="{px}" y="{py}" width="380" height="170" rx="10"/>')
		b.append(txt(px + 15, py + 26, title, 'h', 'start'))
		b += [box(px + 15, py + 62, 80, 40, 'app', 'b'), box(px + 150, py + 62, 80, 40, 'cache', 'o'),
			  box(px + 285, py + 62, 80, 40, 'DB', 'g')]
		for kind, label in flows:
			if kind == 'ab':
				b.append(arrow(px + 95, py + 75, px + 148, py + 75, label=label, ly=py + 54))
			elif kind == 'cd':
				b.append(arrow(px + 230, py + 75, px + 283, py + 75, dash=title == 'write-back', label=label, ly=py + 54))
			elif kind == 'ca':
				b.append(arrow(px + 148, py + 90, px + 97, py + 90, dash=True, label=label, ly=py + 120))
			elif kind == 'ad':
				b.append(curve(f'M {px + 55} {py + 62} C {px + 55} {py + 36}, {px + 325} {py + 36}, {px + 325} {py + 60}',
							   label=label, lx=px + 190, ly=py + 40))
			elif kind == 'dc':
				b.append(arrow(px + 283, py + 90, px + 232, py + 90, dash=True, label=label, lx=px + 258, ly=py + 120))
		b.append(txt(px + 15, py + 152, note, f'lb {note_tone}', 'start'))
	return fig(790, 370, ''.join(b), 'Four caching strategies: who writes to the database, and when')


def sd_replication():
	b = [txt(130, 20, 'all writes ↓'), box(80, 28, 100, 40, 'leader', 'g'), box(20, 130, 95, 36, 'replica', 'b'),
		 box(145, 130, 95, 36, 'replica', 'b')]
	b.append(arrow(115, 68, 70, 128, label='WAL', lx=80, ly=100, anchor='end'))
	b.append(arrow(145, 68, 190, 128, label='WAL', lx=180, ly=100, anchor='start'))
	b.append(txt(130, 200, 'single-leader', 'h'))
	b += [box(275, 40, 100, 40, 'leader DC1', 'g'), box(420, 40, 100, 40, 'leader DC2', 'g')]
	b.append(arrow(375, 60, 418, 60, both=True))
	b.append(txt(397, 112, 'both accept writes'))
	b.append(txt(397, 130, 'conflicts: LWW / merge', 'lb o'))
	b.append(txt(397, 200, 'multi-leader', 'h'))
	b += [box(570, 30, 60, 34, 'n1', 'b'), box(645, 30, 60, 34, 'n2', 'b'), box(720, 30, 60, 34, 'n3', 'b'),
		  box(625, 120, 100, 34, 'client', 'o')]
	b.append(arrow(650, 120, 602, 66, 'g', label='W', lx=614, ly=100, anchor='end'))
	b.append(arrow(675, 120, 675, 66, 'g'))
	b.append(arrow(700, 120, 748, 66, dash=True))
	b.append(txt(675, 178, 'R + W > N  →  2 + 2 > 3', 'lb g'))
	b.append(txt(675, 200, 'leaderless (quorum)', 'h'))
	return fig(790, 210, ''.join(b), 'Replication topologies')


def sd_sharding():
	b = [txt(10, 22, 'key-range', 'h', 'start'), box(10, 40, 360, 30, 'sorted key space  A → Z')]
	for i, (k, tone) in enumerate([('A–H', 'b'), ('I–P', 'b'), ('Q–Z  (hot)', 'r')]):
		x = 10 + i * 125
		b.append(box(x, 110, 110, 40, k, tone))
		b.append(arrow(x + 55, 70, x + 55, 108))
	b.append(txt(10, 180, 'range scans easy · new keys can pile onto one shard', 'lb', 'start'))
	b += [txt(420, 22, 'hash-based', 'h', 'start'), box(420, 40, 360, 30, 'hash(user_id) % 3', 'p')]
	for i in range(3):
		x = 420 + i * 125
		b.append(box(x, 110, 110, 40, f'shard {i}', 'g'))
		b.append(arrow(600, 70, x + 55, 108))
	b.append(txt(420, 180, 'even spread · range queries hit every shard', 'lb', 'start'))
	return fig(790, 195, ''.join(b), 'Range vs hash sharding')


def sd_cap():
	b = [line(395, 32, 600, 205, 'ln g strong'), line(190, 205, 600, 205, 'ln b strong'), line(395, 32, 190, 205, 'ln dash')]
	for x, y, k in [(395, 32, 'C'), (190, 205, 'A'), (600, 205, 'P')]:
		b.append(f'<circle class="bx" cx="{x}" cy="{y}" r="20"/>')
		b.append(f'<text class="t tb" x="{x}" y="{y}" text-anchor="middle" dominant-baseline="central">{k}</text>')
	b.append(txt(515, 112, 'CP · banking, inventory', 'lb g', 'start'))
	b.append(txt(515, 128, 'Spanner, YugabyteDB', 'lb g', 'start'))
	b.append(txt(395, 238, 'AP · feeds, likes, comments · Cassandra, DynamoDB', 'lb b'))
	b.append(txt(278, 112, 'CA · only possible', 'lb', 'end'))
	b.append(txt(278, 128, 'without partitions', 'lb', 'end'))
	return fig(790, 250, ''.join(b), 'CAP: when the network partitions, choose consistency (CP) or availability (AP)')
