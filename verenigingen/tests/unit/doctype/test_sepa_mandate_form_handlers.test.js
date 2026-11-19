/**
 * @fileoverview SEPA Mandate form handlers: direct behavioural tests (#2824)
 *
 * sepa_mandate.js registers five handlers (refresh, status, is_active,
 * sign_date, iban). The older *_controller_refactored suite asserts none of
 * their behaviour, so these tests load the real controller and assert what
 * each handler does to the form.
 */

/* global describe, it, expect, jest, beforeEach, beforeAll */

const { setupTestMocks, cleanupTestMocks, createMockForm } = require('../../setup/frappe-mocks');
const { loadFrappeController } = require('../../setup/controller-loader');

setupTestMocks();

describe('SEPA Mandate form handlers (#2824)', () => {
	let handlers;
	let frm;

	beforeAll(() => {
		const controllerPath =
			'/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen_payments/doctype/sepa_mandate/sepa_mandate.js';
		handlers = loadFrappeController(controllerPath)['SEPA Mandate'];
		['refresh', 'status', 'is_active', 'sign_date', 'iban'].forEach((name) => {
			expect(typeof handlers[name]).toBe('function');
		});
	});

	beforeEach(() => {
		cleanupTestMocks();
		frm = createMockForm({ doc: { doctype: 'SEPA Mandate', docstatus: 0, status: 'Draft', is_active: 0 } });
		frm.scroll_to_field = jest.fn();
	});

	const labels = () => frm.add_custom_button.mock.calls.map((call) => call[0]);
	const clickButton = (label) => {
		const call = frm.add_custom_button.mock.calls.find((c) => c[0] === label);
		call[1]();
	};
	const setValueCalls = () => frm.set_value.mock.calls.map((c) => [c[0], c[1]]);

	describe('refresh: buttons', () => {
		it('Draft shows only Activate, and it activates and saves', () => {
			frm.doc.status = 'Draft';
			handlers.refresh(frm);
			expect(labels()).toEqual(['Activate']);

			clickButton('Activate');
			expect(frm.doc.status).toBe('Active');
			expect(frm.doc.is_active).toBe(1);
			expect(frm.save).toHaveBeenCalledTimes(1);
		});

		it('Active and is_active shows Suspend and Cancel, no Activate/Reactivate', () => {
			frm.doc.status = 'Active';
			frm.doc.is_active = 1;
			handlers.refresh(frm);
			expect(labels()).toEqual(['Suspend', 'Cancel']);
		});

		it('Suspend sets Suspended / inactive and saves', () => {
			frm.doc.status = 'Active';
			frm.doc.is_active = 1;
			handlers.refresh(frm);
			clickButton('Suspend');
			expect(frm.doc.status).toBe('Suspended');
			expect(frm.doc.is_active).toBe(0);
			expect(frm.save).toHaveBeenCalledTimes(1);
		});

		it('Cancel is gated behind frappe.confirm: declining changes nothing', () => {
			global.frappe.confirm = jest.fn(); // never invokes the yes-callback
			frm.doc.status = 'Active';
			frm.doc.is_active = 1;
			handlers.refresh(frm);
			clickButton('Cancel');
			expect(global.frappe.confirm).toHaveBeenCalledTimes(1);
			expect(frm.doc.status).toBe('Active');
			expect(frm.doc.is_active).toBe(1);
			expect(frm.save).not.toHaveBeenCalled();
		});

		it('Cancel, once confirmed, cancels, deactivates, stamps today and saves', () => {
			let onYes;
			global.frappe.confirm = jest.fn((message, callback) => {
				onYes = callback;
			});
			frm.doc.status = 'Active';
			frm.doc.is_active = 1;
			handlers.refresh(frm);
			clickButton('Cancel');
			onYes();
			expect(frm.doc.status).toBe('Cancelled');
			expect(frm.doc.is_active).toBe(0);
			expect(frm.doc.cancelled_date).toBe(global.frappe.datetime.get_today());
			expect(frm.save).toHaveBeenCalledTimes(1);
		});

		it('Suspended shows only Reactivate, and it reactivates and saves', () => {
			frm.doc.status = 'Suspended';
			handlers.refresh(frm);
			expect(labels()).toEqual(['Reactivate']);
			clickButton('Reactivate');
			expect(frm.doc.status).toBe('Active');
			expect(frm.doc.is_active).toBe(1);
			expect(frm.save).toHaveBeenCalledTimes(1);
		});

		it('Active but not is_active shows no Suspend/Cancel (control for the is_active gate)', () => {
			frm.doc.status = 'Active';
			frm.doc.is_active = 0;
			handlers.refresh(frm);
			expect(labels()).toEqual([]);
		});

		it.each(['Cancelled', 'Expired'])('%s shows no status buttons', (status) => {
			frm.doc.status = status;
			handlers.refresh(frm);
			expect(labels()).toEqual([]);
		});

		it.each([1, 2])('docstatus %i shows no status buttons even when Draft/Active/Suspended', (docstatus) => {
			frm.doc.docstatus = docstatus;
			['Draft', 'Active', 'Suspended'].forEach((status) => {
				frm.add_custom_button.mockClear();
				frm.doc.status = status;
				frm.doc.is_active = 1;
				handlers.refresh(frm);
				expect(labels()).toEqual([]);
			});
		});

		it('adds a Member view button only when a member is linked, routing to that member', () => {
			frm.doc.status = 'Cancelled';
			frm.doc.member = 'MEM-2024-001';
			handlers.refresh(frm);
			expect(labels()).toEqual(['Member']);
			clickButton('Member');
			expect(global.frappe.set_route).toHaveBeenCalledWith('Form', 'Member', 'MEM-2024-001');

			frm.add_custom_button.mockClear();
			frm.doc.member = '';
			handlers.refresh(frm);
			expect(labels()).toEqual([]);
		});
	});

	describe('refresh: status indicator', () => {
		it.each([
			['Active', 'green'],
			['Suspended', 'orange'],
			['Cancelled', 'red'],
			['Expired', 'red'],
			['Draft', 'blue'],
			['SomethingElse', 'gray']
		])('%s -> %s', (status, colour) => {
			frm.doc.status = status;
			handlers.refresh(frm);
			expect(frm.page.set_indicator).toHaveBeenCalledWith(status, colour);
		});

		it('sets no indicator when status is empty', () => {
			frm.doc.status = '';
			handlers.refresh(frm);
			expect(frm.page.set_indicator).not.toHaveBeenCalled();
		});
	});

	describe('status handler: is_active sync', () => {
		it('Active sets is_active to 1', () => {
			frm.doc.status = 'Active';
			frm.doc.is_active = 0;
			handlers.status(frm);
			expect(setValueCalls()).toContainEqual(['is_active', 1]);
			expect(frm.doc.is_active).toBe(1);
		});

		it.each(['Suspended', 'Cancelled', 'Expired'])('%s sets is_active to 0', (status) => {
			frm.doc.status = status;
			frm.doc.is_active = 1;
			handlers.status(frm);
			expect(frm.doc.is_active).toBe(0);
		});

		it('Draft leaves is_active alone', () => {
			frm.doc.status = 'Draft';
			frm.doc.is_active = 1;
			handlers.status(frm);
			expect(setValueCalls().filter(([field]) => field === 'is_active')).toEqual([]);
			expect(frm.doc.is_active).toBe(1);
		});

		// The controller runs in a vm sandbox holding the REAL setTimeout (captured at
		// load), so jest fake timers cannot drive it; wait out the 500ms instead.
		const afterTimeout = () => new Promise((resolve) => setTimeout(resolve, 650));

		it('Cancelled without a cancelled_date stamps today and scrolls to the reason after 500ms', async () => {
			frm.doc.status = 'Cancelled';
			handlers.status(frm);
			expect(frm.doc.cancelled_date).toBe(global.frappe.datetime.get_today());
			expect(frm.scroll_to_field).not.toHaveBeenCalled();
			await afterTimeout();
			expect(frm.scroll_to_field).toHaveBeenCalledWith('cancellation_reason');
		});

		it('Cancelled with an existing cancelled_date keeps it and does not scroll', async () => {
			frm.doc.status = 'Cancelled';
			frm.doc.cancelled_date = '2023-05-01';
			handlers.status(frm);
			await afterTimeout();
			expect(frm.doc.cancelled_date).toBe('2023-05-01');
			expect(frm.scroll_to_field).not.toHaveBeenCalled();
		});

		it('non-Cancelled statuses do not stamp cancelled_date', () => {
			['Active', 'Suspended', 'Expired', 'Draft'].forEach((status) => {
				frm.doc.status = status;
				handlers.status(frm);
			});
			expect(frm.doc.cancelled_date).toBeUndefined();
		});
	});

	describe('is_active handler: status sync', () => {
		it('checked while Suspended -> Active', () => {
			frm.doc.status = 'Suspended';
			frm.doc.is_active = 1;
			handlers.is_active(frm);
			expect(frm.doc.status).toBe('Active');
		});

		it('unchecked while Active -> Suspended', () => {
			frm.doc.status = 'Active';
			frm.doc.is_active = 0;
			handlers.is_active(frm);
			expect(frm.doc.status).toBe('Suspended');
		});

		it.each(['Draft', 'Cancelled', 'Expired'])('%s status is left alone either way', (status) => {
			[0, 1].forEach((flag) => {
				frm.doc.status = status;
				frm.doc.is_active = flag;
				handlers.is_active(frm);
				expect(frm.doc.status).toBe(status);
			});
			expect(frm.set_value).not.toHaveBeenCalled();
		});

		it('checked while already Active does not rewrite status (control)', () => {
			frm.doc.status = 'Active';
			frm.doc.is_active = 1;
			handlers.is_active(frm);
			expect(frm.set_value).not.toHaveBeenCalled();
		});
	});

	describe('status <-> is_active ping-pong converges', () => {
		// Frappe fires a field's handler only when its value actually changes;
		// model that so the two handlers can feed each other.
		function wireCascadingForm(doc) {
			const form = createMockForm({ doc: { doctype: 'SEPA Mandate', docstatus: 0, ...doc } });
			form.scroll_to_field = jest.fn();
			let fired = 0;
			form.set_value = jest.fn((field, value) => {
				if (form.doc[field] === value) return Promise.resolve();
				form.doc[field] = value;
				fired += 1;
				if (fired > 20) throw new Error('handlers do not converge');
				if (handlers[field]) handlers[field](form);
				return Promise.resolve();
			});
			return form;
		}

		it.each([
			// [description, start doc, field the user edits, new value, settled status, settled is_active]
			[
				'untick is_active on an Active mandate',
				{ status: 'Active', is_active: 1 },
				'is_active',
				0,
				'Suspended',
				0
			],
			[
				'tick is_active on a Suspended mandate',
				{ status: 'Suspended', is_active: 0 },
				'is_active',
				1,
				'Active',
				1
			],
			[
				'set status Suspended while ticked',
				{ status: 'Active', is_active: 1 },
				'status',
				'Suspended',
				'Suspended',
				0
			],
			[
				'set status Active while unticked',
				{ status: 'Suspended', is_active: 0 },
				'status',
				'Active',
				'Active',
				1
			],
			[
				'set status Cancelled while ticked',
				{ status: 'Active', is_active: 1 },
				'status',
				'Cancelled',
				'Cancelled',
				0
			],
			['set status Expired while ticked', { status: 'Active', is_active: 1 }, 'status', 'Expired', 'Expired', 0]
		])('%s', (_label, start, field, value, endStatus, endFlag) => {
			const form = wireCascadingForm(start);
			form.set_value(field, value);
			expect(form.doc.status).toBe(endStatus);
			expect(form.doc.is_active).toBe(endFlag);
		});
	});

	describe('sign_date handler', () => {
		it('a future date is refused with a message and reset to today', () => {
			const today = global.frappe.datetime.get_today();
			frm.doc.sign_date = global.frappe.datetime.add_days(today, 1);
			handlers.sign_date(frm);
			expect(global.frappe.msgprint).toHaveBeenCalledWith('Sign date cannot be in the future');
			expect(frm.doc.sign_date).toBe(today);
		});

		it('today is accepted unchanged', () => {
			const today = global.frappe.datetime.get_today();
			frm.doc.sign_date = today;
			handlers.sign_date(frm);
			expect(global.frappe.msgprint).not.toHaveBeenCalled();
			expect(frm.set_value).not.toHaveBeenCalled();
		});

		it('a past date is accepted unchanged', () => {
			const today = global.frappe.datetime.get_today();
			frm.doc.sign_date = global.frappe.datetime.add_days(today, -30);
			handlers.sign_date(frm);
			expect(global.frappe.msgprint).not.toHaveBeenCalled();
			expect(frm.set_value).not.toHaveBeenCalled();
		});

		it('an empty date does nothing', () => {
			frm.doc.sign_date = '';
			handlers.sign_date(frm);
			expect(global.frappe.msgprint).not.toHaveBeenCalled();
			expect(frm.set_value).not.toHaveBeenCalled();
		});
	});

	describe('iban handler', () => {
		it.each([
			['nl91abna0417164300', 'NL91 ABNA 0417 1643 00'],
			['NL91 ABNA 0417 1643 00', 'NL91 ABNA 0417 1643 00'],
			['  nl91 abna0417 164300 ', 'NL91 ABNA 0417 1643 00'],
			['DE89370400440532013000', 'DE89 3704 0044 0532 0130 00'],
			['NL91ABNA04171643001', 'NL91 ABNA 0417 1643 001'],
			// length a multiple of 4: the regroup leaves a trailing space that must be trimmed
			['be68539007547034', 'BE68 5390 0754 7034']
		])('%j -> %j', (typed, expected) => {
			frm.doc.iban = typed;
			handlers.iban(frm);
			expect(frm.doc.iban).toBe(expected);
		});

		it('an empty iban is not touched', () => {
			frm.doc.iban = '';
			handlers.iban(frm);
			expect(frm.set_value).not.toHaveBeenCalled();
		});
	});
});
