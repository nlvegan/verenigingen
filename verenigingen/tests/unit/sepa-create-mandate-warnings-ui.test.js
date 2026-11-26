/**
 * @fileoverview The staff "create SEPA mandate" dialog must not report a clean green
 * success when the server created the mandate but a follow-up step failed (#3100).
 *
 * Contract: create_and_link_mandate_enhanced returns {success: true, ..., warnings: [...]}
 * (SEPAMandateManager.create_mandate puts the lifecycle errors in data["warnings"], #2992).
 * The dialog handler must then show an ORANGE alert carrying the server's warning text,
 * and keep the green "created successfully" alert for a response with no warnings.
 *
 * Drives the REAL create_mandate_with_values from sepa-utils.js (evaluated, because the
 * module does not export it). Only the framework edge is stubbed: frappe.call (the
 * network) and frappe.show_alert (recorded).
 */

const fs = require('fs');
const path = require('path');

const SOURCE = path.join(__dirname, '../../public/js/member/js_modules/sepa-utils.js');

global.frappe = global.frappe || {};
global.frappe.provide = function provide(p) {
	let obj = global;
	for (const part of p.split('.')) {
		obj[part] = obj[part] || {};
		obj = obj[part];
	}
	return obj;
};
require('../../public/js/utils/operation-result-helpers.js');

function loadCreateMandateWithValues() {
	const source = fs.readFileSync(SOURCE, 'utf8');
	// The shipped file is plain browser JS (no module system), so evaluating it is the
	// only way to drive the real function.
	// eslint-disable-next-line no-new-func
	const factory = new Function(
		'frappe',
		'window',
		'$',
		'__',
		'verenigingen',
		`${source}\nreturn create_mandate_with_values;`
	);
	return factory(
		global.frappe,
		window,
		global.$,
		(s, args) => s.replace(/\{(\d+)\}/g, (_, i) => args[i]),
		global.verenigingen
	);
}

const VALUES = { iban: 'NL91ABNA0417164300', mandate_id: 'M-3100', used_for_memberships: 1, used_for_donations: 0 };

function run(createResponse) {
	const alerts = [];
	global.frappe.show_alert = jest.fn((opts) => alerts.push(typeof opts === 'string' ? { message: opts } : opts));
	global.frappe.msgprint = jest.fn();
	global.frappe.call = jest.fn((opts) => {
		if (opts.method.endsWith('validate_mandate_creation')) {
			opts.callback({ message: { success: true, data: {} } });
		} else {
			opts.callback({ message: createResponse });
		}
	});
	const frm = {
		doc: { name: 'Assoc-Member-1', payment_method: 'SEPA Direct Debit' },
		reload_doc() {},
		set_value() {}
	};
	jest.useFakeTimers();
	loadCreateMandateWithValues()(frm, VALUES, { hide() {} });
	jest.runAllTimers();
	jest.useRealTimers();
	return alerts;
}

describe('create_mandate_with_values result alert (#3100)', () => {
	test('server warnings are shown in an orange alert, not the green success', () => {
		const warnings = ['Member integration failed: <b>lock wait</b>', 'Second step failed'];
		const alerts = run({ success: true, valid: true, mandate_id: 'M-3100', warnings });
		const created = alerts.find((a) => /M-3100/.test(a.message));
		expect(created).toBeDefined();
		expect(created.indicator).toBe('orange');
		expect(created.message).not.toMatch(/created successfully/);
		expect(created.message).toContain('Second step failed');
		// warning text is server/driver supplied: it must not become markup
		expect(created.message).not.toContain('<b>');
		expect(created.message).toContain('&lt;b&gt;lock wait');
		expect(alerts.some((a) => a.indicator === 'green')).toBe(false);
	});

	test('control: a response with no warnings still shows the green success', () => {
		const alerts = run({ success: true, valid: true, mandate_id: 'M-3100' });
		const created = alerts.find((a) => /M-3100/.test(a.message));
		expect(created.indicator).toBe('green');
		expect(created.message).toMatch(/created successfully/);
	});

	test('control: an empty warnings list is not a warning', () => {
		const alerts = run({ success: true, valid: true, mandate_id: 'M-3100', warnings: [] });
		const created = alerts.find((a) => /M-3100/.test(a.message));
		expect(created.indicator).toBe('green');
		expect(created.message).toMatch(/created successfully/);
		expect(created.message).not.toMatch(/with warnings/);
	});
});
