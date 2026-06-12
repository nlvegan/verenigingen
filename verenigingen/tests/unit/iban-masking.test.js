/**
 * @fileoverview Unit tests for the IBAN masking utility.
 *
 * Exercises the REAL module (verenigingen/public/js/utils/iban-masking.js) via a
 * direct require so coverage is measured. Framework globals (frappe.provide,
 * frappe.user_roles, frappe.ui.form, jQuery's $(document).ready) are stubbed —
 * the masking/role-gating/restore logic is the system under test.
 *
 * Business context: IBANs are sensitive financial data. Non-privileged users must
 * see only a masked form, and the original value must be restored before save so
 * a masked placeholder is never persisted to the database.
 */

// --- Framework boundary setup (runs before the module's load-time side effects:
// frappe.provide + $(document).ready -> verenigingen.iban.setup()). ---
const formOn = jest.fn();
global.frappe = global.frappe || {};
global.frappe.provide = function provide(path) {
	const parts = path.split('.');
	let obj = global;
	for (const part of parts) {
		obj[part] = obj[part] || {};
		obj = obj[part];
	}
	return obj;
};
global.frappe.user_roles = [];
global.frappe.ui = { form: { on: formOn } };
// $(document).ready(cb) must invoke cb so setup() runs at load.
global.$ = function $() {
	return { ready: (cb) => cb && cb() };
};

require('../../public/js/utils/iban-masking.js');
const iban = global.verenigingen.iban;

const FULL_IBAN = 'NL91ABNA0417164300';

function makeForm(value = FULL_IBAN) {
	return {
		doc: { iban: value },
		refresh_field: jest.fn(),
		set_df_property: jest.fn()
	};
}

beforeEach(() => {
	frappe.user_roles = [];
});

describe('IBAN masking utility', () => {
	describe('mask', () => {
		test('shows only the first 4 and last 4 characters', () => {
			expect(iban.mask('NL91ABNA0417164300')).toBe('NL91****4300');
		});

		test('strips spaces before masking', () => {
			expect(iban.mask('NL91 ABNA 0417 1643 00')).toBe('NL91****4300');
		});

		test('returns the input unchanged when too short to mask', () => {
			expect(iban.mask('NL91')).toBe('NL91');
			expect(iban.mask('NL911234')).toBe('NL91****1234'); // exactly 8 chars masks
		});

		test('returns falsy input unchanged (no crash)', () => {
			expect(iban.mask('')).toBe('');
			expect(iban.mask(null)).toBeNull();
			expect(iban.mask(undefined)).toBeUndefined();
		});
	});

	describe('canViewFull', () => {
		test('is true for Accounts Manager', () => {
			frappe.user_roles = ['Accounts Manager'];
			expect(iban.canViewFull()).toBe(true);
		});

		test('is true for System Manager', () => {
			frappe.user_roles = ['System Manager'];
			expect(iban.canViewFull()).toBe(true);
		});

		test('is false for an ordinary member', () => {
			frappe.user_roles = ['Verenigingen Member'];
			expect(iban.canViewFull()).toBe(false);
		});
	});

	describe('applyMasking', () => {
		test('masks the field, stores the original, and locks it for non-privileged users', () => {
			frappe.user_roles = ['Verenigingen Member'];
			const frm = makeForm();

			iban.applyMasking(frm, 'iban');

			expect(frm.doc.iban).toBe('NL91****4300');
			expect(frm._original_iban.iban).toBe(FULL_IBAN);
			expect(frm.refresh_field).toHaveBeenCalledWith('iban');
			expect(frm.set_df_property).toHaveBeenCalledWith('iban', 'read_only', 1);
		});

		test('leaves the full IBAN untouched for privileged users', () => {
			frappe.user_roles = ['Accounts Manager'];
			const frm = makeForm();

			iban.applyMasking(frm, 'iban');

			expect(frm.doc.iban).toBe(FULL_IBAN);
			expect(frm.set_df_property).not.toHaveBeenCalled();
		});

		test('does nothing when the field has no value', () => {
			frappe.user_roles = ['Verenigingen Member'];
			const frm = makeForm('');

			iban.applyMasking(frm, 'iban');

			expect(frm.refresh_field).not.toHaveBeenCalled();
		});
	});

	describe('restoreOriginal', () => {
		test('puts the unmasked value back before save', () => {
			frappe.user_roles = ['Verenigingen Member'];
			const frm = makeForm();
			iban.applyMasking(frm, 'iban');
			expect(frm.doc.iban).toBe('NL91****4300');

			iban.restoreOriginal(frm, 'iban');

			expect(frm.doc.iban).toBe(FULL_IBAN);
		});

		test('is a no-op when nothing was masked', () => {
			const frm = makeForm();
			iban.restoreOriginal(frm, 'iban');
			expect(frm.doc.iban).toBe(FULL_IBAN);
		});
	});

	describe('setup', () => {
		test('registers refresh/before_save handlers for SEPA Mandate and Member', () => {
			formOn.mockClear();
			iban.setup();

			const registeredDoctypes = formOn.mock.calls.map((c) => c[0]);
			expect(registeredDoctypes).toContain('SEPA Mandate');
			expect(registeredDoctypes).toContain('Member');
		});

		test('the registered Member refresh handler only masks when an iban field exists', () => {
			frappe.user_roles = ['Verenigingen Member'];
			formOn.mockClear();
			iban.setup();

			const memberHandlers = formOn.mock.calls.find((c) => c[0] === 'Member')[1];
			const frmWithoutIban = { doc: {}, fields_dict: {}, refresh_field: jest.fn(), set_df_property: jest.fn() };
			expect(() => memberHandlers.refresh(frmWithoutIban)).not.toThrow();
			expect(frmWithoutIban.set_df_property).not.toHaveBeenCalled();
		});

		test('the SEPA Mandate handlers mask on refresh and restore on before_save', () => {
			frappe.user_roles = ['Verenigingen Member'];
			formOn.mockClear();
			iban.setup();

			const sepaHandlers = formOn.mock.calls.find((c) => c[0] === 'SEPA Mandate')[1];
			const frm = makeForm();

			sepaHandlers.refresh(frm);
			expect(frm.doc.iban).toBe('NL91****4300');

			sepaHandlers.before_save(frm);
			expect(frm.doc.iban).toBe(FULL_IBAN);
		});

		test('the Member handlers mask and restore when an iban field is present', () => {
			frappe.user_roles = ['Verenigingen Member'];
			formOn.mockClear();
			iban.setup();

			const memberHandlers = formOn.mock.calls.find((c) => c[0] === 'Member')[1];
			const frm = makeForm();
			frm.fields_dict = { iban: {} };

			memberHandlers.refresh(frm);
			expect(frm.doc.iban).toBe('NL91****4300');

			memberHandlers.before_save(frm);
			expect(frm.doc.iban).toBe(FULL_IBAN);
		});

		test('the Member before_save is a no-op without an iban field', () => {
			formOn.mockClear();
			iban.setup();
			const memberHandlers = formOn.mock.calls.find((c) => c[0] === 'Member')[1];
			const frm = { doc: { iban: FULL_IBAN }, fields_dict: {} };
			expect(() => memberHandlers.before_save(frm)).not.toThrow();
		});
	});
});
