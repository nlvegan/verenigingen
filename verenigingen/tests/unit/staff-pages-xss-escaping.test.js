/* eslint-disable no-eval, no-new-func, no-script-url -- the shipped page scripts are plain browser JS in templates; evaluating them is the only way to drive the real code, and javascript: URLs are the attack input. */
/**
 * @fileoverview Staff/portal pages must escape server text they render as HTML (issue #2586,
 * siblings of #2413).
 *
 * Each page below builds HTML strings from API data (bank descriptions, member names,
 * e-Boekhouden account names, Mollie/Ponto text, error messages) and hands them to
 * innerHTML / jQuery `.append()` / `frappe.msgprint`. Like mollie-debug-page-escaping.test.js
 * (#2413) this drives the REAL shipped script, extracted from the template, with tainted data
 * and PARSES the produced HTML: the property is "no payload element exists", not a substring.
 *
 * Inline `onclick="fn('${x}')"` needs more than escaping: the browser decodes `&#39;` back to
 * `'` before the handler runs, so the tests CLICK the rendered buttons with an id that
 * breaks out of a JS string and assert the injected statement never executes and the
 * handler receives the id verbatim.
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '../../..');
const PAYLOAD = '"\'><img src=x onerror=alert(1)>';
// Breaks out of a single-quoted JS string inside an inline handler.
const BREAKOUT = "x');window.__pwned=1;('";

function read(rel) {
	return fs.readFileSync(path.join(ROOT, rel), 'utf8');
}

/** The inline <script> that contains `marker`, with Jinja neutralised. */
function pageScript(rel, marker) {
	// Case-insensitive and attribute/whitespace tolerant (CodeQL js/bad-tag-filter); this
	// extracts our own templates' scripts for the test, it is not a sanitiser.
	const blocks = [...read(rel).matchAll(/<script\b[^>]*>([\s\S]*?)<\/script\b[^>]*>/gi)].map((m) => m[1]);
	const block = blocks.find((b) => b.includes(marker));
	if (!block) throw new Error(`no inline <script> containing ${marker} in ${rel}`);
	return block
		.replace(/\{\{\s*_\(\s*"([^"]*)"\s*\)\s*\}\}/g, '$1')
		.replace(/\{\{\s*default_company[^}]*\}\}/g, "''")
		.replace(/\{\{[^}]*\|tojson\s*\}\}/g, '[]')
		.replace(/\{\{[^}]*\}\}/g, "''")
		.replace(/\{%[^%]*%\}/g, '');
}

/** ids a script looks up, so the page skeleton has them. */
function skeleton(script, extra = '') {
	const ids = new Set([...script.matchAll(/getElementById\('([^']+)'\)/g)].map((m) => m[1]));
	document.body.innerHTML =
		[...ids]
			.map((id) => {
				if (/^btn-/.test(id) || /^run-/.test(id)) return `<button id="${id}"></button>`;
				if (/result|container|messages|list|items|section|log|tbody|body|table|transactions/.test(id))
					return `<div id="${id}"></div>`;
				if (/^filter-(issues|active)$/.test(id)) return `<input type="checkbox" id="${id}">`;
				return `<input id="${id}">`;
			})
			.join('') + extra;
}

function injected() {
	return {
		img: document.body.querySelector('img'),
		onerror: document.body.querySelector('[onerror]')
	};
}

function expectNoInjection(html) {
	const box = document.createElement('div');
	box.innerHTML = html;
	expect({ img: !!box.querySelector('img'), onerror: !!box.querySelector('[onerror]') }).toEqual({
		img: false,
		onerror: false
	});
}

function installHelpers() {
	window.frappe = window.frappe || {};
	window.frappe.provide = (ns) => {
		ns.split('.').reduce((o, k) => (o[k] = o[k] || {}), window);
	};
	window.eval(read('verenigingen/public/js/utils/operation-result-helpers.js'));
}

function baseFrappe(overrides = {}) {
	const calls = [];
	const stub = {
		calls,
		call: (opts) => {
			calls.push(opts);
			return undefined;
		},
		msgprint: jest.fn(),
		confirm: jest.fn(),
		show_alert: jest.fn(),
		ready: (fn) => fn(),
		realtime: null,
		set_route: jest.fn(),
		show_progress: jest.fn(),
		hide_progress: jest.fn(),
		csrf_token: 'x',
		...overrides
	};
	window.frappe = Object.assign(window.frappe, stub);
	window.__ = (s, args) => String(s).replace(/\{(\d+)\}/g, (_m, i) => (args || [])[i]);
	return stub;
}

/** Chainable jQuery stand-in that records every HTML string handed to append/html. */
function makeJquery() {
	const sinks = [];
	const handlers = {};
	const wrap = (sel) => {
		const self = new Proxy(() => {}, {
			get(_t, key) {
				if (key === Symbol.toPrimitive) return () => '';
				if (typeof key === 'symbol') return undefined;
				if (key === 'length') return 1;
				if (key === 'append' || key === 'html') {
					return (arg) => {
						if (typeof arg === 'string') sinks.push(arg);
						return arg === undefined ? '' : self;
					};
				}
				if (key === 'click') {
					return (fn) => {
						if (fn) handlers[sel] = fn.bind(self);
						return self;
					};
				}
				if (key === 'on') {
					return (_ev, a, b) => {
						if (typeof a === 'string' && b) handlers[a] = b.bind(self);
						return self;
					};
				}
				if (key === 'ready') {
					return (fn) => {
						fn();
						return self;
					};
				}
				if (key === 'val') return (v) => (v === undefined ? 'Test Co' : self);
				return () => self;
			}
		});
		return self;
	};
	const $ = (sel) => wrap(typeof sel === 'string' ? sel : '#object');
	return { $, sinks, handlers };
}

// Pages register DOMContentLoaded listeners on `document`, which outlive a test. Capture them
// instead, so a page's startup code runs only when a test asks for it.
const realAddEventListener = document.addEventListener;
let domReadyListeners;

beforeEach(() => {
	delete window.__pwned;
	domReadyListeners = [];
	document.addEventListener = function (type, fn, ...rest) {
		if (type === 'DOMContentLoaded') domReadyListeners.push(fn);
		else realAddEventListener.call(this, type, fn, ...rest);
	};
	installHelpers();
});

afterEach(() => {
	document.addEventListener = realAddEventListener;
	document.body.innerHTML = '';
});

describe('mollie_member_reconciliation.html', () => {
	const REL = 'verenigingen/www/mollie_member_reconciliation.html';
	let confirmMessages;

	function load() {
		const script = pageScript(REL, 'function displayMembers');
		skeleton(script);
		baseFrappe();
		confirmMessages = [];
		window.confirm = (m) => {
			confirmMessages.push(m);
			return false;
		};
		window.eval(script);
	}

	const sub = (id) => ({
		subscription_id: id,
		description: PAYLOAD,
		status: PAYLOAD,
		amount: PAYLOAD,
		interval: PAYLOAD,
		next_payment_date: PAYLOAD,
		cancelled_at: PAYLOAD
	});
	const member = (over = {}) => ({
		member_id: 'MEM-1',
		member_name: PAYLOAD,
		member_status: PAYLOAD,
		customer_id: PAYLOAD,
		has_issues: true,
		current_subscription_status: PAYLOAD,
		current_subscription_id: PAYLOAD,
		current_next_payment_date: PAYLOAD,
		active_subscriptions: [sub('sub_1')],
		inactive_subscriptions: [sub('sub_2')],
		discrepancies: [PAYLOAD],
		suggested_subscription_id: 'sub_1',
		suggested_status: 'active',
		suggested_next_invoice_date: '2026-01-01',
		...over
	});

	test('member cards render no payload element, and the payload is shown as text', () => {
		load();
		window.displayMembers([member()]);
		expect(injected()).toEqual({ img: null, onerror: null });
		expect(document.getElementById('member-list').textContent).toContain(PAYLOAD);
	});

	test('a tag-bearing member id is URL-encoded in the member link and renders no element', () => {
		load();
		window.displayMembers([member({ member_id: PAYLOAD })]);
		expect(injected()).toEqual({ img: null, onerror: null });
		const href = document.querySelector('#member-list h5 a').getAttribute('href');
		expect(href).toBe(`/app/member/${encodeURIComponent(PAYLOAD)}`);
	});

	test('Apply Quick Fix button: an id with a quote cannot run script and arrives verbatim', () => {
		load();
		window.displayMembers([member({ member_id: BREAKOUT, suggested_subscription_id: BREAKOUT })]);
		const button = document.querySelector('.update-buttons button');
		expect(button).not.toBeNull();
		button.click();
		expect(window.__pwned).toBeUndefined();
		expect(confirmMessages).toEqual([`Apply suggested fix to member ${BREAKOUT}?`]);
	});

	test('Set as Current button: an id with a quote cannot run script and arrives verbatim', () => {
		load();
		window.displayMembers([
			member({ member_id: BREAKOUT, active_subscriptions: [sub(BREAKOUT)], suggested_status: '' })
		]);
		const button = document.querySelector('.subscription-item button');
		expect(button).not.toBeNull();
		button.click();
		expect(window.__pwned).toBeUndefined();
		expect(confirmMessages).toEqual([`Set subscription ${BREAKOUT} as current for member ${BREAKOUT}?`]);
	});

	test.each([
		['dues keywords and member rows', 'success'],
		['reconciliation error text', 'error'],
		['request failure text', 'failed']
	])('runReconciliation: %s is escaped', (_label, mode) => {
		load();
		window.frappe.call = (opts) => {
			if (mode === 'success') {
				opts.callback({
					message: {
						success: true,
						data: { members: [member()], total_members: 1, dues_keywords: [PAYLOAD], test_mode: false }
					}
				});
			} else if (mode === 'error') {
				opts.callback({ message: { success: false, error_message: PAYLOAD } });
			} else {
				opts.error({ message: PAYLOAD });
			}
		};
		window.runReconciliation();
		expect(injected()).toEqual({ img: null, onerror: null });
	});

	test.each([
		['error', { success: false, error: { message: PAYLOAD } }],
		['request failure', null]
	])('executeMandateSync: %s is escaped', (_label, message) => {
		load();
		window.frappe.call = (opts) => (message ? opts.callback({ message }) : opts.error({ message: PAYLOAD }));
		window.executeMandateSync(true);
		expect(injected()).toEqual({ img: null, onerror: null });
		expect(document.getElementById('status-messages').textContent).toContain(PAYLOAD);
	});
});

describe('sepa_reconciliation_dashboard.html', () => {
	const REL = 'verenigingen/templates/pages/sepa_reconciliation_dashboard.html';

	function load() {
		const script = pageScript(REL, 'function updateTabContent');
		skeleton(script);
		baseFrappe();
		window.open = jest.fn();
		window.eval(script);
	}

	test('reconciled and pending-review lists render no payload element (bank text is payer-controlled)', () => {
		load();
		window.updateTabContent({
			linked_transactions: [
				{
					name: PAYLOAD,
					deposit: '1',
					date: PAYLOAD,
					custom_sepa_batch: PAYLOAD,
					custom_processing_status: PAYLOAD
				}
			],
			pending_reviews: [{ name: PAYLOAD, reference_name: PAYLOAD, description: PAYLOAD, creation: PAYLOAD }]
		});
		expect(injected()).toEqual({ img: null, onerror: null });
		expect(document.getElementById('pending-review-items').textContent).toContain(PAYLOAD.slice(0, 20));
	});

	test('View Task button: a task name with a quote cannot run script', () => {
		load();
		window.updateTabContent({
			linked_transactions: [],
			pending_reviews: [{ name: BREAKOUT, reference_name: 'r', description: 'd', creation: 'c' }]
		});
		document.querySelector('#pending-review-items button').click();
		expect(window.__pwned).toBeUndefined();
		expect(window.open).toHaveBeenCalledTimes(1);
		expect(decodeURIComponent(window.open.mock.calls[0][0])).toBe(`/app/todo/${BREAKOUT}`);
	});

	test('unmatched transactions render no payload element', () => {
		load();
		window.displayUnmatchedTransactions([
			{
				bank_transaction: PAYLOAD,
				description: PAYLOAD,
				transaction_amount: 1,
				matching_batches: [{ batch_name: PAYLOAD, confidence: PAYLOAD }]
			}
		]);
		expect(injected()).toEqual({ img: null, onerror: null });
	});

	test('Match button: ids with a quote cannot run script and reach the API verbatim', () => {
		load();
		window.displayUnmatchedTransactions([
			{
				bank_transaction: BREAKOUT,
				description: 'd',
				transaction_amount: 1,
				matching_batches: [{ batch_name: BREAKOUT, confidence: 'high' }]
			}
		]);
		document.querySelector('#unmatched-transactions button').click();
		expect(window.__pwned).toBeUndefined();
		expect(window.frappe.calls.map((c) => c.args)).toContainEqual({
			bank_transaction_name: BREAKOUT,
			sepa_batch_name: BREAKOUT
		});
	});

	test('error text in the msgprint dialogs is escaped', () => {
		load();
		window.frappe.call = (opts) => opts.callback({ message: { success: false, error: { message: PAYLOAD } } });
		window.processSepaBatch('a', 'b');
		const message = window.frappe.msgprint.mock.calls[0][0];
		expectNoInjection(message);
	});
});

describe('ponto_api_debug.html', () => {
	const REL = 'verenigingen/templates/pages/ponto_api_debug.html';

	function load(responder) {
		const script = pageScript(REL, 'renderLinksTable');
		skeleton(script, '<button class="tab-button" data-tab="x"></button>');
		baseFrappe({ call: (opts) => responder(opts) });
		window.eval(script);
		domReadyListeners.forEach((fn) => fn());
	}

	const link = (over = {}) => ({
		name: 'PL-1',
		amount: 5,
		currency: 'EUR',
		payment_type: 'One-Time',
		frequency: PAYLOAD,
		status: PAYLOAD,
		description: PAYLOAD,
		redirect_link: 'https://example.org/pay',
		...over
	});

	test('the payment-link table renders no payload element', () => {
		load((opts) =>
			opts.callback({ message: { success: true, links: [link({ name: PAYLOAD, currency: PAYLOAD })] } })
		);
		document.getElementById('btn-list').click();
		expect(injected()).toEqual({ img: null, onerror: null });
	});

	test('Refresh button: a link name with a quote cannot run script and arrives verbatim', () => {
		const seen = [];
		load((opts) => {
			if (/list_payment_links/.test(opts.method)) {
				opts.callback({ message: { success: true, links: [link({ name: BREAKOUT })] } });
			} else seen.push(opts.args);
		});
		document.getElementById('btn-list').click();
		document.querySelector('#links-table-container button').click();
		expect(window.__pwned).toBeUndefined();
		expect(seen).toEqual([{ payment_link_name: BREAKOUT }]);
	});

	test('a javascript: redirect link never becomes an href', () => {
		load((opts) =>
			opts.callback({
				message: { success: true, links: [link({ redirect_link: 'javascript:alert(1)' })] }
			})
		);
		document.getElementById('btn-list').click();
		expect(document.querySelector('#links-table-container a[href^="javascript"]')).toBeNull();
		expect(document.querySelector('#links-table-container a.btn-brutal--info')).toBeNull();
	});

	test('submitting a link does not re-parse the JSON response as HTML', () => {
		load((opts) => {
			if (/create_payment_link/.test(opts.method)) {
				opts.callback({ message: { success: true, name: 'PL-1' } });
			} else {
				opts.callback({
					message: {
						success: true,
						description: PAYLOAD,
						redirect_link: 'https://example.org/authorize'
					}
				});
			}
		});
		document.getElementById('btn-create-submit').click();
		const area = document.getElementById('create-result');
		expect(injected()).toEqual({ img: null, onerror: null });
		expect(area.textContent).toContain(PAYLOAD.slice(2));
		expect(area.querySelector('a.redirect-link').getAttribute('href')).toBe('https://example.org/authorize');
	});

	test('a javascript: authorization link is shown as text, not linked', () => {
		load((opts) => {
			if (/create_payment_link/.test(opts.method)) {
				opts.callback({ message: { success: true, name: 'PL-1' } });
			} else {
				opts.callback({ message: { success: true, redirect_link: 'javascript:alert(1)' } });
			}
		});
		document.getElementById('btn-create-submit').click();
		expect(document.getElementById('create-result').querySelector('a')).toBeNull();
	});
});

describe('eboekhouden_mapping_review.html', () => {
	const REL = 'verenigingen/templates/pages/eboekhouden_mapping_review.html';

	function run(accountOverrides = {}, loadResponse = null) {
		const script = pageScript(REL, 'function displayAccountTypes');
		const jq = makeJquery();
		const account = {
			account: PAYLOAD,
			account_code: PAYLOAD,
			account_name: PAYLOAD, // external: the e-Boekhouden chart of accounts
			current_type: 'Bank',
			recommended_type: PAYLOAD,
			is_group: 0,
			...accountOverrides
		};
		baseFrappe({
			call: (opts) => {
				if (/get_account_type_recommendations/.test(opts.method)) {
					opts.callback({ message: loadResponse || { success: true, recommendations: [account] } });
				} else if (/frappe.client.get_list/.test(opts.method) && opts.args.doctype === 'Company') {
					opts.callback({ message: [{ name: 'Test Co' }] });
				} else if (/frappe.client.get_list/.test(opts.method)) {
					opts.callback({
						message: [
							{
								name: PAYLOAD,
								account_code: PAYLOAD,
								account_name: PAYLOAD,
								document_type: PAYLOAD,
								transaction_category: PAYLOAD,
								usage_count: 1
							}
						]
					});
				}
			}
		});
		window.$ = jq.$;
		new Function('$', 'frappe', 'document', script)(jq.$, window.frappe, document);
		jq.handlers['#load-account-types']();
		return jq;
	}

	test('a load error from the server is escaped in the msgprint', () => {
		run({}, { success: false, error: PAYLOAD });
		const dialog = window.frappe.msgprint.mock.calls.map((c) => c[0]).find((c) => c && c.title === 'Error');
		expect(dialog).toBeDefined();
		expectNoInjection(dialog.message);
	});

	test('account table and existing-mapping rows render no payload element', () => {
		const jq = run();
		expect(jq.sinks.length).toBeGreaterThan(5);
		const joined = jq.sinks.filter((h) => /<td/.test(h)).join('');
		expectNoInjection(`<table><tbody><tr>${joined}</tr></tbody></table>`);
		// control: the rows the page builds do reach the sink and carry the payload as text
		const box = document.createElement('div');
		box.innerHTML = `<table><tbody><tr>${joined}</tr></tbody></table>`;
		expect(box.textContent).toContain(PAYLOAD);
	});

	test('displayAnalysisResults (not wired to any caller today) escapes too, and the suggestion JSON round-trips', () => {
		const script = pageScript(REL, 'function displayAccountTypes');
		const start = script.indexOf('function displayAnalysisResults');
		const end = script.indexOf('// Create individual mapping');
		const body = script.slice(start, end);
		const raw = body.match(
			/\$\{(?!escapeHtml\()[^}]*(account_code|account_name|transaction_category|suggested_type)[^}]*\}/g
		);
		expect(raw).toBeNull();
		expect(body).toContain('data-suggestion="${escapeHtml(JSON.stringify(suggestion))}"');
	});

	test('error text collected for the update summary is escaped', () => {
		const script = pageScript(REL, 'function displayAccountTypes');
		const pushes = script.match(/errors\.push\(`[^`]*`\)/g);
		expect(pushes.length).toBe(2);
		for (const push of pushes) {
			expect(push).toContain('escapeHtml(change.account)');
			expect(push).toContain('escapeHtml(errorMsg)');
		}
	});
});

describe('mollie_payment_processing.html', () => {
	const REL = 'verenigingen/templates/pages/mollie_payment_processing.html';

	function load(responder) {
		const script = pageScript(REL, 'function displayProcessingResults');
		skeleton(script);
		baseFrappe({ call: async (opts) => responder(opts) });
		window.eval(script);
	}

	test('processing results render no payload element (errors can carry payer text)', () => {
		load(() => ({}));
		window.displayProcessingResults({
			total_requested: 1,
			processed: 0,
			skipped: 0,
			errors: 1,
			results: [
				{
					payment_id: PAYLOAD,
					status: PAYLOAD,
					member: PAYLOAD,
					payment_entry: PAYLOAD,
					error: PAYLOAD
				},
				{ payment_id: 'tr_2', status: 'skipped', bank_transaction: PAYLOAD, skipped_reason: PAYLOAD }
			]
		});
		expect(injected()).toEqual({ img: null, onerror: null });
		expect(document.getElementById('dues-processing-results').textContent).toContain(PAYLOAD);
	});

	test('a server error shown through msgprint is escaped', async () => {
		load(() => ({ message: { error: PAYLOAD } }));
		document.getElementById('dues-customer-id').value = 'cst_1';
		await window.retrieveCustomerPayments();
		expect(window.frappe.msgprint).toHaveBeenCalled();
		expectNoInjection(window.frappe.msgprint.mock.calls[0][0].message);
	});

	test('a thrown error shown through msgprint is escaped', async () => {
		load((opts) => {
			if (/retrieve_customer_payments/.test(opts.method)) throw new Error(PAYLOAD);
			return {};
		});
		document.getElementById('dues-customer-id').value = 'cst_1';
		await window.retrieveCustomerPayments();
		expectNoInjection(window.frappe.msgprint.mock.calls[0][0].message);
	});
});

describe('www/email-group-admin.html', () => {
	const REL = 'verenigingen/www/email-group-admin.html';

	function load(statsGroups, syncMessage) {
		const script = pageScript(REL, 'updateGroupsTable');
		const jq = makeJquery();
		baseFrappe({
			call: (opts) => {
				if (/get_email_group_stats/.test(opts.method)) {
					opts.callback({ message: { success: true, total_groups: 1, groups: statsGroups } });
				} else if (syncMessage) {
					opts.callback({ message: syncMessage });
				}
			}
		});
		new Function('$', 'frappe', 'document', '__', 'localStorage', script)(
			jq.$,
			window.frappe,
			document,
			window.__,
			{ getItem: () => null, setItem() {} }
		);
		return jq;
	}

	const group = (over = {}) => ({
		name: 'G1',
		title: PAYLOAD,
		description: PAYLOAD,
		member_count: 1,
		unsubscribed_count: 0,
		total_count: 1,
		...over
	});

	test('group rows render no payload element', () => {
		const jq = load([group()]);
		const rows = jq.sinks.filter((h) => /<tr>/.test(h)).join('');
		expect(rows).toContain('<td>');
		expectNoInjection(`<table><tbody>${rows}</tbody></table>`);
	});

	test('View button: a group name with a quote cannot run script', () => {
		const jq = load([group({ name: BREAKOUT })]);
		const rows = jq.sinks.filter((h) => /<tr>/.test(h)).join('');
		document.body.innerHTML = `<table><tbody>${rows}</tbody></table>`;
		document.querySelector('button').click();
		expect(window.__pwned).toBeUndefined();
		expect(window.frappe.set_route).toHaveBeenCalledWith('Form', 'Email Group', BREAKOUT);
	});

	test('sync errors are escaped in the dialog and in the sync log', () => {
		const jq = load([group()], { success: false, errors: [PAYLOAD] });
		jq.handlers['#btn-sync-groups']();
		expectNoInjection(window.frappe.msgprint.mock.calls[0][0].message);

		const ok = load([group()], { success: true, message: 'ok', added: 1, removed: 0, errors: [PAYLOAD] });
		ok.handlers['#btn-sync-groups']();
		const log = ok.sinks.filter((h) => h.includes('Added')).join('');
		expect(log).toContain('Added');
		expectNoInjection(log);
	});
});

describe('www/dues-coverage-manager.html', () => {
	const REL = 'verenigingen/www/dues-coverage-manager.html';

	function render(over = {}) {
		const script = pageScript(REL, 'function renderMembersTable');
		skeleton(script);
		baseFrappe();
		window.open = jest.fn();
		window.eval(script);
		window.renderMembersTable([
			{
				member: 'MEM-1',
				member_name: PAYLOAD, // member-typed
				coverage_percentage: 50,
				gap_days: 3,
				current_gaps: 'No gaps',
				catchup_required: true,
				catchup_amount: 10,
				...over
			}
		]);
	}

	test('the member name renders as text', () => {
		render();
		expect(injected()).toEqual({ img: null, onerror: null });
		expect(document.getElementById('members-tbody').textContent).toContain(PAYLOAD);
	});

	test('a tag-bearing member id renders no element and is URL-encoded in the href', () => {
		render({ member: PAYLOAD });
		expect(injected()).toEqual({ img: null, onerror: null });
		const href = document.querySelector('#members-tbody a').getAttribute('href');
		expect(href).toBe(`/app/member/${encodeURIComponent(PAYLOAD)}`);
		expect(document.querySelector('.member-checkbox').dataset.member).toBe(PAYLOAD);
	});

	test('Details button and checkbox: a member id with a quote cannot run script', () => {
		render({ member: BREAKOUT });
		document.querySelector('#members-tbody button').click();
		expect(window.__pwned).toBeUndefined();
		expect(window.open).toHaveBeenCalledTimes(1);
		expect(decodeURIComponent(window.open.mock.calls[0][0])).toBe(`/app/member/${BREAKOUT}`);
		expect(document.querySelector('.member-checkbox').dataset.member).toBe(BREAKOUT);
	});
});

describe('www/dues-invoice-manager.html', () => {
	const REL = 'verenigingen/www/dues-invoice-manager.html';

	/** Run the real page script; `reply(opts)` answers each frappe.call. Returns its functions. */
	function load(reply) {
		// Jinja is neutralised, so the page's config falls back to can_generate_invoices:false;
		// grant it so generateMissingInvoices reaches the code under test.
		const script = pageScript(REL, 'function showResults').replace(
			'can_generate_invoices: false',
			'can_generate_invoices: true'
		);
		skeleton(script, ['status', 'generation', 'sepa'].map((k) => `<div id="${k}-spinner"></div>`).join(''));
		baseFrappe({
			call: (opts) => {
				reply(opts);
				return { fail: () => ({}) }; // the page chains .fail() for 403s
			}
		});
		window.HTMLElement.prototype.scrollIntoView = jest.fn();
		window.confirm = jest.fn(() => true);
		return new Function(`${script}; return { checkMemberStatus, generateMissingInvoices };`)();
	}

	const status = (categories) => (opts) =>
		opts.callback({
			message: {
				success: true,
				data: { summary: { members_without_membership: 0 }, member_categories: categories }
			}
		});

	test('member names, ids and category descriptions render as text', () => {
		const member = { member_name: PAYLOAD, member_id: PAYLOAD };
		const page = load(
			status({
				already_covered: { count: 1, description: PAYLOAD },
				needs_invoicing: { count: 1, description: PAYLOAD, members: [member] },
				gap_reset: { count: 1, description: PAYLOAD, members: [PAYLOAD] },
				ineligible_status: { count: 1, description: PAYLOAD },
				no_customer: { count: 1, description: PAYLOAD },
				duplicate_coverage: { count: 2, description: PAYLOAD, members: [PAYLOAD, member, { x: PAYLOAD }] }
			})
		);
		page.checkMemberStatus();
		expect(injected()).toEqual({ img: null, onerror: null });
		expect(document.getElementById('analysis-content').textContent).toContain(PAYLOAD);
		const hrefs = [...document.querySelectorAll('#analysis-content a')].map((a) => a.getAttribute('href'));
		expect(hrefs.length).toBe(2);
		hrefs.forEach((h) => expect(h).toBe(`/app/member/${encodeURIComponent(PAYLOAD)}`));
	});

	test('server error text in the results panel renders as text', () => {
		const page = load((opts) => opts.error({ message: PAYLOAD }));
		page.checkMemberStatus();
		expect(injected()).toEqual({ img: null, onerror: null });
		expect(document.getElementById('results-content').textContent).toContain(PAYLOAD);
	});

	test('queued-job message, note, job id and failure list render as text', () => {
		const queued = load((opts) =>
			opts.callback({ message: { success: true, message: PAYLOAD, data: { job_id: PAYLOAD, note: PAYLOAD } } })
		);
		queued.generateMissingInvoices();
		expect(injected()).toEqual({ img: null, onerror: null });
		expect(document.getElementById('results-content').textContent).toContain(PAYLOAD);

		const failed = load((opts) => opts.callback({ message: { success: false, errors: [PAYLOAD] } }));
		failed.generateMissingInvoices();
		expect(injected()).toEqual({ img: null, onerror: null });
		expect(document.getElementById('results-content').textContent).toContain(PAYLOAD);
	});

	test('control: ordinary text and markup-free ids survive unchanged', () => {
		const page = load(
			status({
				needs_invoicing: {
					count: 1,
					description: 'Plain note',
					members: [{ member_name: 'Jan Jansen', member_id: 'MEM-1' }]
				}
			})
		);
		page.checkMemberStatus();
		expect(document.querySelector('#analysis-content a').getAttribute('href')).toBe('/app/member/MEM-1');
		const text = document.getElementById('analysis-content').textContent;
		expect(text).toContain('Jan Jansen');
		expect(text).toContain('Plain note');
	});
});
