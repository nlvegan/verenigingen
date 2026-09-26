/* eslint-env jest */
/**
 * @fileoverview member.js OperationResult envelope misreads in manual invoice
 * generation and user-account creation call sites (#1452, discovered while
 * sweeping the same file for the same bug class as #1420).
 *
 * Three call sites read a nested OperationResult envelope FLAT:
 *
 * 1. `show_manual_invoice_dialog`'s `get_member_invoice_info` callback read
 *    `r.message.has_customer` / `r.message.has_dues_schedule` etc directly off
 *    the envelope -- always `undefined`, since the payload lives under
 *    `r.message.data`. `!info.has_customer` was therefore ALWAYS true, so
 *    every click on "Generate Invoice" showed "Customer Record Required"
 *    regardless of whether the member actually had one (the feature was
 *    unconditionally broken).
 * 2. `generate_manual_invoice_for_member`'s callback read `r.message.message`
 *    (the success text) and `r.message.invoice_name` directly -- both always
 *    `undefined`; the success message lives under `r.message.meta.message`
 *    and the invoice name under `r.message.data.invoice_name`.
 * 3. `create_user_account_dialog`'s callback read `r.message.message` (always
 *    `undefined`; lives under `r.message.meta.message`) and, on failure,
 *    `r.message.error` directly as the msgprint message -- an OBJECT
 *    (`{message, ...}`), not a string, so it would render as
 *    "[object Object]".
 *
 * All fixtures below are REAL dispatched envelopes, captured by calling the
 * whitelisted endpoints directly (which runs through the real
 * @standard_api / @critical_api decorator stack, serializing the
 * OperationResult via to_dict(scrub_sensitive=True)) on test_site_9 -- not
 * hand-written guesses. See
 * verenigingen/tests/api/test_manual_invoice_generation.py and
 * verenigingen/tests/api/test_create_member_user_account_wire_contract.py for
 * the Python-side pin of these same shapes.
 */

const { setupTestMocks, cleanupTestMocks, createMockForm } = require('../../setup/frappe-mocks');
const { loadFrappeController, testFormEvent } = require('../../setup/controller-loader');

setupTestMocks();

// setupTestMocks()'s frappe.provide is a no-op jest.fn(), so it never builds the
// verenigingen.utils namespace operation-result-helpers.js writes to. Install the
// real namespacing behaviour (same as operation-result-helpers.test.js) and require
// the REAL helpers module, so this test exercises the same
// window.unwrapOperationResult/getErrorMessage member.js gets in production (via
// app_include_js), not member.js's own narrower fallback shim.
global.frappe.provide = function provide(path) {
	const parts = path.split('.');
	let obj = global;
	for (const part of parts) {
		obj[part] = obj[part] || {};
		obj = obj[part];
	}
	return obj;
};
require('../../../public/js/utils/operation-result-helpers.js');

global.$ = jest.fn(() => ({
	appendTo: jest.fn(() => global.$()),
	find: jest.fn(() => ({ length: 0 })),
	length: 0,
	show: jest.fn(),
	css: jest.fn()
}));

const flushPromises = () => new Promise((resolve) => process.nextTick(resolve));

const GET_INVOICE_INFO_METHOD = 'verenigingen.api.manual_invoice_generation.get_member_invoice_info';
const GENERATE_INVOICE_METHOD = 'verenigingen.api.manual_invoice_generation.generate_manual_invoice';
const CREATE_USER_ACCOUNT_METHOD = 'verenigingen.verenigingen.doctype.member.member.create_member_user_account';

// Real dispatched envelopes (see file header).
const REAL_INVOICE_INFO_SUCCESS = {
	success: true,
	timestamp: '2026-09-26 16:13:56.225694',
	data: {
		member_name: 'Capture Xdbb9312462001',
		has_customer: true,
		customer: 'Capture Xdbb9312462001',
		has_dues_schedule: true,
		dues_schedule_name: 'Test-CAP-a0d1a752fc',
		current_rate: 27.5,
		billing_frequency: 'Monthly',
		next_invoice_date: '2026-09-26',
		last_invoice_date: null,
		recent_invoices: []
	},
	meta: { message: 'Member invoice information retrieved successfully' }
};

const REAL_INVOICE_INFO_FAILURE = {
	success: false,
	timestamp: '2026-09-26 16:13:56.227659',
	error: { message: 'Member MEM-NOPE-XYZ not found', code: 'MEMBER_NOT_FOUND' }
};

const REAL_GENERATE_INVOICE_SUCCESS = {
	success: true,
	timestamp: '2026-09-26 16:13:57.693554',
	data: {
		invoice_name: 'ACC-SINV-2026-00006',
		amount: 27.5,
		customer: 'Capture Xdbb9312462001',
		dues_schedule: 'Test-CAP-a0d1a752fc'
	},
	meta: { message: 'Invoice ACC-SINV-2026-00006 generated successfully' }
};

const REAL_GENERATE_INVOICE_FAILURE = {
	success: false,
	timestamp: '2026-09-26 16:13:57.698550',
	error: { message: 'Member MEM-NOPE-XYZ not found', code: 'MEMBER_NOT_FOUND' }
};

const REAL_CREATE_USER_ACCOUNT_SUCCESS = {
	success: true,
	timestamp: '2026-09-26 16:13:58.406882',
	data: 'capture2.1790419437.mjwokw@example.com',
	meta: { message: 'User account created successfully', action: 'created_new' }
};

// A SECOND real success shape (data is still a bare username; the message and
// action differ) -- exists specifically so a "read data.message instead of
// meta.message" mutant can be told apart. Both real messages are hardcoded
// strings in MemberUserAccountService.create_member_user_account: the
// "created_new" message happens to equal the JS's own hardcoded fallback
// text, so a test using ONLY that fixture cannot distinguish "read the real
// meta.message" from "fell through to the fallback default" -- see the
// mutation note below.
const REAL_CREATE_USER_ACCOUNT_LINKED_EXISTING = {
	success: true,
	timestamp: '2026-09-26 16:21:24.357052',
	data: 'linkcap.1790419879.v0t5zr@example.com',
	meta: { message: 'Linked existing user account to member', action: 'linked_existing' }
};

const REAL_CREATE_USER_ACCOUNT_FAILURE = {
	success: false,
	timestamp: '2026-09-26 16:13:58.416288',
	error: { message: 'User account already exists for this member', errors: ['User already exists'] },
	meta: { user: 'capture2.1790419437.mjwokw@example.com', action: 'already_exists' }
};

describe('Member manual invoice + user account OperationResult handling (#1452)', () => {
	let memberHandlers;
	let frm;

	beforeAll(() => {
		const controllerPath =
			'/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/member/member.js';
		const allHandlers = loadFrappeController(controllerPath);
		memberHandlers = allHandlers.Member;
		expect(memberHandlers.refresh).toBeDefined();
	});

	beforeEach(() => {
		cleanupTestMocks();
		global.frappe.user_roles = ['System Manager'];
		global.frappe.user.has_role = jest.fn(() => true);
		global.frappe.model = global.frappe.model || {};
		global.frappe.model.with_doctype = jest.fn((_doctype, cb) => cb && cb());
		global.frappe.perm = global.frappe.perm || {};
		global.frappe.perm.has_perm = jest.fn((_doctype, _level, _perm, cb) => cb && cb(true));
		global.frappe.confirm = jest.fn((_msg, onYes) => onYes && onYes());
	});

	/** Runs refresh() with a generic frappe.call/db mock so the rest of refresh's
	 * many calls answer genially, then flushes the microtask queue so the
	 * `frappe.db.get_value(...).then(...)` dues-schedule button chain resolves
	 * before button callbacks are captured. */
	async function refreshAndFlush(docOverrides, dbGetValueResponse) {
		global.frappe.db.get_value = jest.fn(() => Promise.resolve({ message: dbGetValueResponse }));
		global.frappe.db.exists = jest.fn(() => Promise.resolve(true));
		global.frappe.call = jest.fn(({ callback }) => {
			if (callback) callback({ message: { success: true } });
		});

		frm = createMockForm({ doc: docOverrides });
		frm.fields_dict = {};
		frm.call = jest.fn(({ callback }) => {
			if (callback) callback({ message: { success: true } });
		});

		testFormEvent('Member', 'refresh', frm, { Member: memberHandlers });
		await flushPromises();
		return frm;
	}

	function getButtonCallback(label) {
		const call = frm.add_custom_button.mock.calls.find((c) => c[0] === label);
		expect(call).toBeDefined();
		return call[1];
	}

	// ================================================================== //
	// show_manual_invoice_dialog / generate_manual_invoice_for_member     //
	// ================================================================== //
	describe('"Generate Invoice" button (show_manual_invoice_dialog)', () => {
		async function setupWithScheduleAndClick() {
			await refreshAndFlush(
				{
					name: 'MEM-2026-001',
					doctype: 'Member',
					docstatus: 1,
					customer: 'CUST-001',
					status: 'Active'
				},
				{ name: 'MDS-TEST-001', dues_rate: 27.5, billing_frequency: 'Monthly', status: 'Active' }
			);
			return getButtonCallback('Generate Invoice');
		}

		it('does NOT show "Customer Record Required" for a member who HAS a customer and an active schedule', async () => {
			const onClick = await setupWithScheduleAndClick();

			global.frappe.call = jest.fn(({ method, callback }) => {
				if (method === GET_INVOICE_INFO_METHOD) {
					callback({ message: REAL_INVOICE_INFO_SUCCESS });
				}
			});

			onClick();

			expect(global.frappe.msgprint).not.toHaveBeenCalledWith(
				expect.objectContaining({ title: expect.stringContaining('Customer Record Required') })
			);
		});

		it('opens the confirm dialog with the real rate and dues schedule name from data', async () => {
			const onClick = await setupWithScheduleAndClick();

			global.frappe.call = jest.fn(({ method, callback }) => {
				if (method === GET_INVOICE_INFO_METHOD) {
					callback({ message: REAL_INVOICE_INFO_SUCCESS });
				}
			});
			global.frappe.confirm = jest.fn();

			onClick();

			expect(global.frappe.confirm).toHaveBeenCalled();
			const dialogHtml = global.frappe.confirm.mock.calls[0][0];
			expect(dialogHtml).toContain('27.5');
			expect(dialogHtml).toContain('Test-CAP-a0d1a752fc');
		});

		it('shows the real server error text (a string) on failure, not "[object Object]"', async () => {
			const onClick = await setupWithScheduleAndClick();

			global.frappe.call = jest.fn(({ method, callback }) => {
				if (method === GET_INVOICE_INFO_METHOD) {
					callback({ message: REAL_INVOICE_INFO_FAILURE });
				}
			});

			onClick();

			const msgprintCall = global.frappe.msgprint.mock.calls.find((c) => c[0] && c[0].title === 'Error');
			expect(msgprintCall).toBeDefined();
			expect(typeof msgprintCall[0].message).toBe('string');
			expect(msgprintCall[0].message).toBe('Member MEM-NOPE-XYZ not found');
		});

		it('generates the invoice: reports the real invoice name (not "undefined") and offers to view it', async () => {
			const onClick = await setupWithScheduleAndClick();

			global.frappe.call = jest.fn(({ method, callback }) => {
				if (method === GET_INVOICE_INFO_METHOD) {
					callback({ message: REAL_INVOICE_INFO_SUCCESS });
				} else if (method === GENERATE_INVOICE_METHOD) {
					callback({ message: REAL_GENERATE_INVOICE_SUCCESS });
				}
			});
			let confirmedMessage = null;
			global.frappe.confirm = jest.fn((msg, onYes) => {
				confirmedMessage = msg;
				if (onYes) onYes();
			});

			onClick(); // opens the "Generate Manual Invoice" confirm -> confirms -> generate_manual_invoice_for_member

			const alertCall = global.frappe.show_alert.mock.calls.find(
				(c) => c[0] && typeof c[0].message === 'string' && c[0].message.includes('generated successfully')
			);
			expect(alertCall).toBeDefined();
			expect(alertCall[0].message).toBe('Invoice ACC-SINV-2026-00006 generated successfully');

			// The final frappe.confirm call is "would you like to view it now?" --
			// assert on the raw __() call args (the translation mock does not
			// substitute "{0}", so `confirmedMessage` itself stays literal; the
			// substitution ARRAY is where the real invoice name must appear).
			expect(confirmedMessage).toBe(
				'Invoice {0} has been generated successfully. Would you like to view it now?'
			);
			const confirmTranslationCall = global.__.mock.calls.find(
				(c) => c[0] === 'Invoice {0} has been generated successfully. Would you like to view it now?'
			);
			expect(confirmTranslationCall).toBeDefined();
			expect(confirmTranslationCall[1]).toEqual(['ACC-SINV-2026-00006']);
			expect(global.frappe.set_route).toHaveBeenCalledWith('Form', 'Sales Invoice', 'ACC-SINV-2026-00006');
		});

		it('shows the real server error text on invoice generation failure', async () => {
			const onClick = await setupWithScheduleAndClick();

			global.frappe.call = jest.fn(({ method, callback }) => {
				if (method === GET_INVOICE_INFO_METHOD) {
					callback({ message: REAL_INVOICE_INFO_SUCCESS });
				} else if (method === GENERATE_INVOICE_METHOD) {
					callback({ message: REAL_GENERATE_INVOICE_FAILURE });
				}
			});
			global.frappe.confirm = jest.fn((_msg, onYes) => onYes && onYes());

			onClick();

			const msgprintCall = global.frappe.msgprint.mock.calls.find(
				(c) => c[0] && c[0].title === 'Invoice Generation Failed'
			);
			expect(msgprintCall).toBeDefined();
			expect(typeof msgprintCall[0].message).toBe('string');
			expect(msgprintCall[0].message).toBe('Member MEM-NOPE-XYZ not found');
		});
	});

	// ================================================================== //
	// create_user_account_dialog                                          //
	// ================================================================== //
	describe('"Create User Account" button (create_user_account_dialog)', () => {
		async function setupAndClick() {
			await refreshAndFlush(
				{
					name: 'MEM-2026-002',
					doctype: 'Member',
					docstatus: 1,
					email: 'newmember@example.com',
					user: null,
					full_name: 'New Member',
					status: 'Active'
				},
				null
			);
			return getButtonCallback('Create User Account');
		}

		it('shows the real success message from meta.message, not undefined', async () => {
			const onClick = await setupAndClick();

			global.frappe.call = jest.fn(({ method, callback }) => {
				if (method === CREATE_USER_ACCOUNT_METHOD) {
					callback({ message: REAL_CREATE_USER_ACCOUNT_SUCCESS });
				}
			});

			onClick();

			expect(global.frappe.show_alert).toHaveBeenCalledWith(
				{ message: 'User account created successfully', indicator: 'green' },
				5
			);
		});

		it('shows the DIFFERENT real "linked existing" message, not the "created new" fallback text', async () => {
			// Distinguishes reading meta.message from a mutant that reads
			// data.message (or falls through to the hardcoded default): this
			// envelope's real message differs from both the OTHER success test's
			// message and the JS's own fallback default, so only a correct read
			// of meta.message produces the right text.
			const onClick = await setupAndClick();

			global.frappe.call = jest.fn(({ method, callback }) => {
				if (method === CREATE_USER_ACCOUNT_METHOD) {
					callback({ message: REAL_CREATE_USER_ACCOUNT_LINKED_EXISTING });
				}
			});

			onClick();

			expect(global.frappe.show_alert).toHaveBeenCalledWith(
				{ message: 'Linked existing user account to member', indicator: 'green' },
				5
			);
		});

		it('shows the real server error text (a string) on failure, not the error object', async () => {
			const onClick = await setupAndClick();

			global.frappe.call = jest.fn(({ method, callback }) => {
				if (method === CREATE_USER_ACCOUNT_METHOD) {
					callback({ message: REAL_CREATE_USER_ACCOUNT_FAILURE });
				}
			});

			onClick();

			expect(global.frappe.msgprint).toHaveBeenCalled();
			const msgArg = global.frappe.msgprint.mock.calls[0][0];
			expect(typeof msgArg.message).toBe('string');
			expect(msgArg.message).toBe('User account already exists for this member');
		});
	});
});
