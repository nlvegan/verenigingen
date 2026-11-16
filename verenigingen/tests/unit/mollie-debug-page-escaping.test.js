/**
 * @fileoverview The Mollie debug page must escape every server-supplied value it
 * renders as HTML (issue #2413).
 *
 * `verenigingen/templates/pages/mollie_payments_debug.html` builds HTML strings and
 * hands them to `innerHTML` (displayResult, the bulk payments table). Bank-supplied
 * text (a Bank Transaction description, reference, a Mollie payment description) is
 * payer-controlled, so an unescaped value is stored XSS against whoever uses the page.
 *
 * Two complementary checks, both driving the REAL shipped script (extracted from the
 * template, Jinja `{{ _("...") }}` replaced by its text, other `{{ }}` by an empty string):
 *
 * 1. Behavioural: every `format*Result` function (and the bulk table renderer) is
 *    called with "tainted" data in which EVERY value reads as an HTML payload, and the
 *    produced HTML is PARSED by jsdom. No element the payload carries (`<img>`,
 *    an `onerror` attribute, an attribute breakout) may exist. Parsing, not substring
 *    matching: "no <img> exists" is the property that matters. The renderers are run
 *    with several "absent" key sets, because a truthy `data.error` otherwise returns
 *    before the rest of the function is reached.
 * 2. Structural: every `${...}` interpolated into an HTML-building line in the script
 *    must be wrapped in `escapeHtml(...)`. This covers the sinks the behavioural run
 *    cannot reach (the fetch `.catch` branches, the confirm dialogs).
 *
 * A mutation (remove escapeHtml from one field) turns both red; see the control
 * tests at the bottom, which prove the harness sees an unescaped value.
 */

const fs = require('fs');
const path = require('path');

const TEMPLATE = path.join(__dirname, '../../templates/pages/mollie_payments_debug.html');
const PAYLOAD = '"\'><img src=x onerror=alert(1)>';

function loadScript(source) {
	const match = source.match(/<script>([\s\S]*)<\/script>\s*{% endblock %}/);
	if (!match) throw new Error('inline <script> not found in the template');
	return match[1].replace(/\{\{\s*_\(\s*"([^"]*)"\s*\)\s*\}\}/g, '$1').replace(/\{\{[^}]*\}\}/g, "''"); // csrf_token and similar server-side values
}

/** Evaluate the page script and return every top-level function it declares. */
const frappeStub = { csrf_token: 'x', confirm() {}, msgprint() {} };

function loadPage(script) {
	const names = [...script.matchAll(/^function (\w+)\(/gm)].map((m) => m[1]);
	// The shipped page script is plain browser JS in a template, so evaluating it is the only way
	// to drive the real code.
	// eslint-disable-next-line no-new-func
	const factory = new Function(
		'frappe',
		'document',
		'window',
		'console',
		`${script}\nreturn { ${names.join(', ')} };`
	);
	const quiet = { log() {}, error() {}, warn() {} };
	return factory(frappeStub, document, window, quiet);
}

/**
 * A value that reads as PAYLOAD however it is used: interpolated, `.toFixed()`ed,
 * upper-cased, JSON-stringified, passed to `new Date`. It also behaves as a one-element
 * array (`.length`, `.map`, `.filter`, `.forEach`), so list branches render once.
 */
function taint(absent) {
	const arrayLike = {
		map: (self) => (fn) => [fn(self, 0)],
		filter: (self) => () => [self],
		forEach: (self) => (fn) => fn(self, 0),
		slice: (self) => () => [self],
		some: () => () => false,
		includes: () => () => false
	};
	const text = [
		'toFixed',
		'toUpperCase',
		'toLowerCase',
		'toLocaleString',
		'toLocaleDateString',
		'trim',
		'toString',
		'valueOf',
		'toJSON',
		'join'
	];
	const self = new Proxy(() => {}, {
		get(_target, key) {
			if (key === Symbol.toPrimitive) return () => PAYLOAD;
			if (key === Symbol.iterator) return () => [self][Symbol.iterator]();
			if (typeof key === 'symbol') return undefined;
			if (absent.has(key)) return undefined;
			if (key === 'length') return 1;
			if (key in arrayLike) return arrayLike[key](self);
			if (text.includes(key)) return () => PAYLOAD;
			return taint(absent);
		},
		apply: () => PAYLOAD
	});
	return self;
}

const ABSENT_SETS = [
	[],
	['error'],
	['error', 'mollie_api_error', 'error_detail', 'note', 'message', 'failure_reason'],
	['error', 'dry_run', 'status', 'bank_transaction', 'mollie']
];

function renderedHtml(fn, arity, absent) {
	const args = Array.from({ length: arity }, () => taint(new Set(absent)));
	return String(fn(...args));
}

/** Parse like a browser; report what the payload managed to create. */
function leaks(html) {
	const box = document.createElement('div');
	box.innerHTML = html;
	const found = [];
	if (box.querySelector('img')) found.push('<img> element');
	if (box.querySelector('[onerror]')) found.push('onerror attribute');
	return found;
}

describe('mollie_payments_debug.html escapes server-supplied values (#2413)', () => {
	const source = fs.readFileSync(TEMPLATE, 'utf8');
	const script = loadScript(source);
	const page = loadPage(script);

	const RENDERERS = Object.keys(page)
		.filter((n) => /^format[A-Z]/.test(n))
		.sort();

	test('the extraction found the renderers this guards (control)', () => {
		for (const name of [
			'formatSearchResults',
			'formatTransactionStatus',
			'formatCustomerResult',
			'formatAdminResult',
			'formatPaymentResult',
			'formatSyncEndDatesResult'
		]) {
			expect(RENDERERS).toContain(name);
		}
		expect(RENDERERS.length).toBeGreaterThanOrEqual(20);
	});

	test('the harness sees an unescaped value (control)', () => {
		const html = `<p>${taint(new Set()).description}</p>`;
		expect(leaks(html)).toEqual(['<img> element', 'onerror attribute']);
		expect(leaks(`<p>${page.escapeHtml(PAYLOAD)}</p>`)).toEqual([]);
	});

	test.each(RENDERERS)('%s renders no payload element for any value', (name) => {
		const fn = page[name];
		document.body.innerHTML = '<input type="checkbox" id="hide-canceled-items">';
		const hideCanceled = document.getElementById('hide-canceled-items');
		ABSENT_SETS.flatMap((absent, index) => [
			[absent, index, false],
			[absent, index, true]
		]).forEach(([absent, index, checked]) => {
			hideCanceled.checked = checked;
			let html;
			try {
				html = renderedHtml(fn, fn.length, absent);
			} catch (error) {
				// Hiding keys the renderer dereferences unconditionally can throw; only the
				// first two sets (everything present, only `error` absent) must render.
				if (index < 2) throw error;
				return;
			}
			expect({ name, absent, leaks: leaks(html) }).toEqual({ name, absent, leaks: [] });
		});
	});

	describe('the named fields from #2413', () => {
		const tx = (over) => ({
			name: 'ACC-BTN-1',
			date: '2026-01-01',
			currency: 'EUR',
			amount: 1.5,
			description: 'plain',
			reference_number: 'REF',
			transaction_id: 'TID',
			bank_account: 'Account',
			status: 'Pending',
			outcome: 'pending',
			processing_status: null,
			...over
		});
		const search = (over) =>
			page.formatSearchResults({
				search_term: 'x',
				total_found: 1,
				limit: 10,
				results: [tx(over)]
			});

		test.each(['description', 'name', 'reference_number', 'transaction_id', 'bank_account'])(
			'formatSearchResults escapes tx.%s',
			(field) => {
				const html = search({
					[field]: PAYLOAD,
					reference_number: 'REF',
					transaction_id: 'TID',
					...{ [field]: PAYLOAD }
				});
				expect(leaks(html)).toEqual([]);
				const box = document.createElement('div');
				box.innerHTML = html;
				expect(box.textContent).toContain(PAYLOAD);
			}
		);

		test('formatSearchResults escapes the search term', () => {
			const html = page.formatSearchResults({ search_term: PAYLOAD, total_found: 0, limit: 5, results: [] });
			expect(leaks(html)).toEqual([]);
		});

		test('the href of a result cannot be broken out of', () => {
			const box = document.createElement('div');
			box.innerHTML = search({ name: '"><a id=pwn href=javascript:alert(1)>' });
			expect(box.querySelector('#pwn')).toBeNull();
			expect(box.querySelector('a').getAttribute('href')).toBe(
				'/app/bank-transaction/"><a id=pwn href=javascript:alert(1)>'
			);
		});

		const status = (bt) =>
			page.formatTransactionStatus({
				transaction_id: 'T',
				processed: true,
				bank_transaction: {
					name: 'BT',
					date: '2026-01-01',
					currency: 'EUR',
					amount: 2,
					description: 'plain',
					status: 'Pending',
					outcome: 'pending',
					...bt
				}
			});

		test.each(['name', 'description', 'currency'])('formatTransactionStatus escapes bt.%s', (field) => {
			expect(leaks(status({ [field]: PAYLOAD }))).toEqual([]);
		});
	});

	describe('attribute contexts', () => {
		test('a customer id cannot break out of the onclick handler (no inline JS string)', () => {
			const id = "cst_x');alert(1);('";
			const html = page.formatCustomerListResult({
				test_mode: true,
				limit: 1,
				timestamp: 't',
				customers: [{ id, name: 'n', email: 'e', created_at: '2026-01-01', mode: 'test' }]
			});
			const box = document.createElement('div');
			box.innerHTML = html;
			for (const button of box.querySelectorAll('button[onclick]')) {
				expect(button.getAttribute('onclick')).not.toContain(id);
				expect(button.dataset.customerId).toBe(id);
			}
			expect(box.querySelectorAll('button[onclick]').length).toBeGreaterThan(0);
		});
	});

	describe('structure: every interpolation into HTML is escaped', () => {
		/**
		 * Tokenise the script into template literals (nested ones included), skipping strings,
		 * comments and regex literals. Returns { start, end, text, exprs } where `text` is the
		 * literal's static part and `exprs` its top-level `${...}` expressions.
		 */
		function templateLiterals(src) {
			const found = [];
			const skipString = (i) => {
				const q = src[i];
				for (i++; i < src.length && src[i] !== q; i++) if (src[i] === '\\') i++;
				return i + 1;
			};
			function literal(i) {
				const start = i;
				let text = '';
				const exprs = [];
				for (i++; src[i] !== '`'; ) {
					if (src[i] === '\\') {
						i += 2;
					} else if (src[i] === '$' && src[i + 1] === '{') {
						const close = code(i + 2, true);
						exprs.push(src.slice(i + 2, close).trim());
						i = close + 1;
					} else text += src[i++];
				}
				found.push({ start, end: i, text, exprs });
				return i + 1;
			}
			function code(i, untilBrace) {
				let depth = 0;
				while (i < src.length) {
					const c = src[i];
					if (c === "'" || c === '"') i = skipString(i);
					else if (c === '`') i = literal(i);
					else if (c === '/' && src[i + 1] === '/') i = src.indexOf('\n', i);
					else if (c === '/' && src[i + 1] === '*') i = src.indexOf('*/', i) + 2;
					else if (c === '/' && /[(,=:[!&|?{};]/.test(src.slice(0, i).trimEnd().slice(-1))) {
						for (i++; src[i] !== '/'; i++) if (src[i] === '\\') i++;
						i++;
					} else {
						if (c === '{') depth++;
						else if (c === '}') {
							if (untilBrace && depth === 0) return i;
							depth--;
						}
						i++;
					}
				}
				return i;
			}
			code(0, false);
			return found;
		}

		// Where the literal's value goes: the statement text before it.
		const TEXT_SINK = /(textContent|\balert\(|(?<![.\w])confirm\(|console\.\w+\(|\.push\()[^;]*$/;
		const statementBefore = (src, start) => {
			const from = Math.max(
				src.lastIndexOf(';', start),
				src.lastIndexOf('{', start),
				src.lastIndexOf('}', start)
			);
			return src.slice(from + 1, start);
		};

		const literals = templateLiterals(script);
		const candidates = literals.filter(
			(l) => l.exprs.length && l.text.includes('<') && !TEXT_SINK.test(statementBefore(script, l.start))
		);
		// Variables that hold markup this page built itself; their parts are candidates too.
		const MARKUP_VARS = new Set(['checkbox', 'memberDisplay', 'modeBadge', 'processedBadge']);
		const unescaped = (l) => l.exprs.filter((e) => !e.startsWith('escapeHtml(') && !MARKUP_VARS.has(e));

		test('the scanner finds the literals this guards (control)', () => {
			const demo = templateLiterals('x = `<p>${a.b}</p>` + `a${`<i>${c}</i>`}`; y = "`"; z = /`/g;');
			expect(demo.map((l) => l.exprs)).toEqual([['a.b'], ['c'], ['`<i>${c}</i>`']]);
			expect(candidates.length).toBeGreaterThan(300);
			// continuation lines and confirm messages are literals too
			const texts = candidates.map((l) => l.text).join('\n');
			expect(texts).toContain('Subscription ID: <br>');
			expect(texts).toContain('PERMANENTLY DELETE customer');
			expect(texts).toContain('text-center py-4 text-gray-600');
		});

		test('no HTML-building template literal interpolates an unescaped value', () => {
			const offenders = candidates
				.filter((l) => unescaped(l).length)
				.map((l) => `${unescaped(l).join(', ')} in: ${l.text.trim().slice(0, 60)}`);
			expect(offenders).toEqual([]);
		});

		test.each([
			'adminCancelSubscription',
			'adminRevokeMandate',
			'adminDeleteCustomer',
			'adminCancelPayment',
			'createSubscription',
			'createScheduledSubscription'
		])('%s: the confirm dialog shows typed values as text (behavioural)', (name) => {
			const ids = [...page[name].toString().matchAll(/getElementById\('([^']+)'\)/g)].map((m) => m[1]);
			const value = (id) => {
				if (/amount$/.test(id)) return '5';
				if (/interval-count$/.test(id)) return '1';
				if (/confirmation$/.test(id)) return 'DELETE CUSTOMER';
				return PAYLOAD;
			};
			document.body.innerHTML = ids
				.map((id) => `<input id="${id}" value="${value(id).replace(/"/g, '&quot;')}">`)
				.join('');
			const seen = [];
			const callbacks = [];
			frappeStub.confirm = (message, onYes) => {
				seen.push(message);
				callbacks.push(onYes);
			};
			const realFetch = global.fetch;
			global.fetch = () => new Promise(() => {});
			try {
				page[name]();
				// adminDeleteCustomer asks twice; the second message is built in the first callback
				if (callbacks[0] && name === 'adminDeleteCustomer') callbacks[0]();
			} finally {
				global.fetch = realFetch;
			}

			expect(seen.length).toBeGreaterThan(0);
			for (const message of seen) {
				expect(leaks(message)).toEqual([]);
				const box = document.createElement('div');
				box.innerHTML = message;
				expect(box.textContent).toContain(PAYLOAD);
			}
		});

		test('the empty bulk-payments message is escaped (behavioural)', () => {
			const spans = [
				'bulk-total-members',
				'bulk-members-checked',
				'bulk-total-payments',
				'bulk-unprocessed-payments',
				'bulk-api-calls',
				'bulk-selected-count'
			]
				.map((id) => `<span id="${id}"><span></span></span>`)
				.join('');
			document.body.innerHTML = `${spans}<table><tbody id="bulk-payments-table-body"></tbody></table>`;
			// compares as 5 (`> 0`) but interpolates as the payload, to reach the counts branch
			const count = { valueOf: () => 5, toString: () => PAYLOAD };
			page.displayBulkPaymentsResults({
				customers: [],
				total_payments_found: count,
				total_filtered_by_customer: count
			});
			const tbody = document.getElementById('bulk-payments-table-body');
			expect(leaks(tbody.innerHTML)).toEqual([]);
			expect(tbody.textContent).toContain(PAYLOAD);
			expect(tbody.querySelectorAll('td').length).toBe(1);
		});

		test('the bulk payments table renders payer-controlled values as text, markup intact', () => {
			const spans = [
				'bulk-total-members',
				'bulk-members-checked',
				'bulk-total-payments',
				'bulk-unprocessed-payments',
				'bulk-api-calls',
				'bulk-selected-count'
			]
				.map((id) => `<span id="${id}"><span></span></span>`)
				.join('');
			document.body.innerHTML = `${spans}<table><tbody id="bulk-payments-table-body"></tbody></table>`;
			page.displayBulkPaymentsResults({
				customers: [
					{
						member: PAYLOAD,
						full_name: PAYLOAD,
						payments: [
							{
								id: PAYLOAD,
								status: PAYLOAD,
								amount_display: PAYLOAD,
								created_at: '2026-01-01',
								processing_mode: 'bt_pe_reconcile',
								matching_invoice: { invoice_name: PAYLOAD }
							}
						]
					}
				]
			});
			const tbody = document.getElementById('bulk-payments-table-body');
			expect(leaks(tbody.innerHTML)).toEqual([]);
			expect(tbody.querySelector('input.bulk-payment-checkbox').dataset.paymentId).toBe(PAYLOAD);
			expect(tbody.querySelector('input.bulk-payment-checkbox').dataset.matchingInvoice).toBe(PAYLOAD);
			expect(tbody.querySelector('[title^="Will reconcile with"]').getAttribute('title')).toBe(
				`Will reconcile with ${PAYLOAD}`
			);
			// the markup the page itself builds still renders as elements, not as text
			expect(tbody.querySelectorAll('td').length).toBe(8);
			expect(tbody.querySelector('code').textContent).toBe(PAYLOAD);
		});

		test('the bulk payments table escapes every cell it builds', () => {
			const rowBlock = script.slice(
				script.indexOf('row.innerHTML = `'),
				script.indexOf('tbody.appendChild(row)')
			);
			const cells = [...rowBlock.matchAll(/\$\{([^}]*(?:\([^)]*\))?[^}]*)\}/g)].map((m) => m[1]);
			const htmlVars = new Set(['checkbox', 'memberDisplay', 'modeBadge', 'processedBadge']);
			expect(cells.length).toBeGreaterThanOrEqual(8);
			for (const cell of cells) {
				expect(htmlVars.has(cell.trim()) || cell.trim().startsWith('escapeHtml(')).toBe(true);
			}
			// the builders of those variables are template literals the scan above covers
		});
	});
});
