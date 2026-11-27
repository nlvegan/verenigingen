/* eslint-env jest */
/**
 * @fileoverview JS readers of an OperationResult envelope that read the WRONG shape (#1485)
 *
 * Endpoints decorated with @critical_api / @high_security_api return their OperationResult through
 * `to_dict(scrub_sensitive=True)`, the NESTED schema (utils/operation_result.py):
 *
 *   success: {success: true,  timestamp, data: {...}, meta: {message: "..."}}   // ok(data, message=...)
 *   failure: {success: false, timestamp, error: {message, errors, code, http_status}}
 *
 * `success` is a real top-level key, which is why `if (r.message.success)` looks right. Everything else
 * is not top level. The sites below read `r.message.<field>` / `r.message.error` / `r.message.message`
 * flat. The fixtures are the nested schema exactly as to_dict emits it (same shape the #1420
 * test_member_fee_history_button fixtures captured from a real dispatch); no test site was used.
 *
 * Each test loads the REAL controller file in a vm and drives the real function. It supplies only the
 * browser globals and the REAL operation-result-helpers.js (what app_include_js loads in the desk).
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const APP = path.resolve(__dirname, '..', '..');
const HELPERS = path.join(APP, 'public/js/utils/operation-result-helpers.js');

/** Run `file` in a sandbox and return the named top-level functions plus the spies. */
function loadReal1485Functions(file, fnNames) {
	const alerts = [];
	const msgprints = [];
	const calls = [];
	const sandbox = {
		console,
		window: {},
		document: {},
		DOMParser: global.DOMParser,
		__: (s, args) => (args ? String(s).replace(/\{(\d+)\}/g, (_m, i) => args[i]) : s),
		$: () => ({ on: () => ({}), find: () => ({}) }),
		jQuery: () => ({}),
		frappe: {
			provide(p) {
				let o = sandbox;
				p.split('.').forEach((k) => {
					o[k] = o[k] || {};
					o = o[k];
				});
				return o;
			},
			ui: {
				form: { on: () => {} },
				Dialog: function Dialog() {
					return { show() {}, hide() {}, hide_msgprint() {} };
				}
			},
			query_reports: {},
			listview_settings: {},
			datetime: {
				str_to_user: (s) => s,
				year_start: () => '2026-01-01',
				year_end: () => '2026-12-31',
				get_today: () => '2026-11-27'
			},
			utils: { escape_html: (s) => s },
			show_alert: (a) => alerts.push(a),
			msgprint: (m) => msgprints.push(m),
			call: (opts) => calls.push(opts),
			set_route: () => {},
			confirm: () => {}
		}
	};
	vm.createContext(sandbox);
	vm.runInContext(fs.readFileSync(HELPERS, 'utf8'), sandbox);
	// expose the helpers as bare globals, as the desk bundle does
	['unwrapOperationResult', 'getErrorMessage', 'getSuccessMessage'].forEach((n) => {
		sandbox[n] = sandbox.window[n];
	});
	const exportLine = `\n;globalThis.__fns = {${fnNames.join(', ')}};`;
	vm.runInContext(fs.readFileSync(path.join(APP, file), 'utf8') + exportLine, sandbox);
	return { fns: sandbox.__fns, alerts, msgprints, calls, sandbox };
}

const OK = (data, message) => ({
	success: true,
	timestamp: '2026-11-27 10:00:00.000000',
	data,
	meta: message ? { message } : undefined
});
const FAIL = (message) => ({
	success: false,
	timestamp: '2026-11-27 10:00:00.000000',
	error: { message, errors: [message], code: 'X', http_status: 417 }
});

/** Make the real frappe.call answer with `message` and run its callback. */
function answerWith(ctx, message) {
	ctx.sandbox.frappe.call = (opts) => opts.callback({ message });
}

describe('donor.js ANBI endpoints (OperationResult, #1485)', () => {
	const FILE = 'verenigingen/doctype/donor/donor.js';

	it('update_tax_identifiers shows the real success text from meta.message', () => {
		const ctx = loadReal1485Functions(FILE, ['update_tax_identifiers']);
		ctx.sandbox.frappe.call = (opts) =>
			opts.callback({ message: OK({ donor: 'D-1' }, 'Server says: identifiers saved') });
		ctx.fns.update_tax_identifiers({ doc: { name: 'D-1' }, reload_doc() {} }, {});
		expect(ctx.alerts[0].message).toBe('Server says: identifiers saved');
		expect(ctx.alerts[0].indicator).toBe('green');
	});

	it('update_tax_identifiers shows the real failure text from error.message', () => {
		const ctx = loadReal1485Functions(FILE, ['update_tax_identifiers']);
		answerWith(ctx, FAIL('Failed to update tax identifiers: BSN failed eleven-proof'));
		ctx.fns.update_tax_identifiers({ doc: { name: 'D-1' } }, {});
		expect(ctx.alerts[0].message).toBe('Failed to update tax identifiers: BSN failed eleven-proof');
		expect(ctx.alerts[0].indicator).toBe('red');
	});

	it('generate_anbi_report hands the report (data) to the dialog, not the envelope', () => {
		const ctx = loadReal1485Functions(FILE, ['generate_anbi_report']);
		const report = {
			report_date: '2026-11-27 10:00:00',
			period: { from: '2026-01-01', to: '2026-12-31' },
			summary: { total_donations: 2, total_amount: 30, includes_tax_ids: false },
			donations: []
		};
		let dialogValues;
		ctx.sandbox.frappe.ui.Dialog = function Dialog(cfg) {
			dialogValues = cfg;
			return { show() {}, hide() {} };
		};
		ctx.fns.generate_anbi_report({ doc: { name: 'D-1' } });
		answerWith(ctx, OK(report, 'ANBI report generated successfully with 2 donations'));
		dialogValues.primary_action({});
		expect(ctx.msgprints).toHaveLength(1);
		expect(ctx.msgprints[0].message).toContain('<strong>Total Donations:</strong> 2');
	});

	it('generate_anbi_report shows the real failure text', () => {
		const ctx = loadReal1485Functions(FILE, ['generate_anbi_report']);
		let dialogValues;
		ctx.sandbox.frappe.ui.Dialog = function Dialog(cfg) {
			dialogValues = cfg;
			return { show() {}, hide() {} };
		};
		ctx.fns.generate_anbi_report({ doc: { name: 'D-1' } });
		answerWith(ctx, FAIL('Failed to generate ANBI report'));
		dialogValues.primary_action({});
		expect(ctx.alerts[0].message).toBe('Failed to generate ANBI report');
	});
});

describe('periodic_donation_agreement.js donor handler (get_donor_anbi_data, #1485)', () => {
	const FILE = 'verenigingen/doctype/periodic_donation_agreement/periodic_donation_agreement.js';

	function runDonorHandler(message) {
		const ctx = loadReal1485Functions(FILE, ['calculate_payment_amount']);
		let handlers;
		ctx.sandbox.frappe.ui.form.on = (_dt, h) => {
			if (h && h.donor) handlers = h;
		};
		vm.runInContext(fs.readFileSync(path.join(APP, FILE), 'utf8'), ctx.sandbox);
		answerWith(ctx, message);
		handlers.donor({ doc: { donor: 'D-1' } });
		return ctx.msgprints.map((m) => m.title);
	}

	it('does NOT warn when the donor has consent and a verified identification (both under data)', () => {
		const titles = runDonorHandler(OK({ anbi_consent: 1, identification_verified: 1 }));
		expect(titles).toEqual([]);
	});

	it('warns about each missing piece when the donor lacks them (control)', () => {
		const titles = runDonorHandler(OK({ anbi_consent: 0, identification_verified: 0 }));
		expect(titles).toEqual(['ANBI Consent Missing', 'Identification Not Verified']);
	});
});

describe('member_list.js merge dialogs (get_merge_preview / execute_merge, #1485)', () => {
	const FILE = 'verenigingen/doctype/member/member_list.js';

	it('show_merge_dialog shows the failure TEXT, not an error object', () => {
		const ctx = loadReal1485Functions(FILE, ['show_merge_dialog']);
		answerWith(ctx, FAIL('Insufficient permissions to merge members'));
		ctx.fns.show_merge_dialog('A', 'B', {});
		expect(ctx.msgprints[0].message).toBe('Insufficient permissions to merge members');
	});

	it('execute_merge shows the failure TEXT, not an error object', () => {
		const ctx = loadReal1485Functions(FILE, ['execute_merge']);
		answerWith(ctx, FAIL('Member not found'));
		ctx.fns.execute_merge('A', 'B', {}, {});
		expect(ctx.msgprints[0].message).toBe('Member not found');
	});
});

describe('members_without_chapter.js assign (assign_member_to_chapter, #1485)', () => {
	it('shows the failure TEXT, not an error object', () => {
		const ctx = loadReal1485Functions('verenigingen/report/members_without_chapter/members_without_chapter.js', [
			'assignMemberToChapter'
		]);
		answerWith(ctx, FAIL('Member is not eligible'));
		ctx.fns.assignMemberToChapter('M-1', 'C-1', null);
		expect(ctx.msgprints[0].message).toBe('Member is not eligible');
	});
});
