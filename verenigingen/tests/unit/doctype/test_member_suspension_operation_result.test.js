/* eslint-env jest */
/**
 * @fileoverview member.js suspension-related OperationResult misreads (#1420, "related,
 * lower-severity finding")
 *
 * Three call sites in member.js read a FAILED OperationResult envelope wrongly:
 *
 * 1. `show_suspension_dialog`'s `suspend_member` failure branch read
 *    `resp.message.message` -- always undefined on the real nested failure envelope,
 *    where the text lives at `resp.message.error.message`. Same for
 *    `show_unsuspension_dialog`'s `unsuspend_member` failure branch.
 * 2. `add_suspension_action_button` / `display_suspension_status`'s
 *    `get_suspension_status_safe` failure branch checked
 *    `status_result.message.data.access_denied` -- there is no top-level "data" key on a
 *    nested OperationResult failure at all (only `error` and `meta`). The PERMISSION_DENIED
 *    failure's `access_denied` flag actually lives at `meta.data.access_denied` (the `data=`
 *    kwarg passed to `OperationResult.fail(..., data={...})` lands in **metadata**, not a
 *    top-level `data`). The old code's guard never fired, so a permission-denied response
 *    always fell through to the generic `console.warn(..., undefined)` branch instead of
 *    silently returning.
 *
 * Both real shapes were captured via an actual dispatch through the security-decorator
 * stack on test_site_6 (a Guest querying another member's `get_suspension_status_safe`):
 *   {'success': False, 'error': {'message': 'You can only view your own suspension status',
 *    'code': 'PERMISSION_DENIED'},
 *    'meta': {'data': {'access_denied': True, 'help': "..."}}}
 * `suspend_member`/`unsuspend_member` share the same `OperationResult.to_dict()` nested
 * failure shape (`error: {message, code}`, no top-level `message`).
 */

const { setupTestMocks, cleanupTestMocks, createMockForm } = require('../../setup/frappe-mocks');
const { loadFrappeController, testFormEvent } = require('../../setup/controller-loader');

setupTestMocks();

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

const CAN_SUSPEND_METHOD = 'verenigingen.api.suspension_api.can_suspend_member';
const SUSPENSION_STATUS_METHOD = 'verenigingen.api.suspension_api.get_suspension_status_safe';
const SUSPEND_METHOD = 'verenigingen.api.suspension_api.suspend_member';
const UNSUSPEND_METHOD = 'verenigingen.api.suspension_api.unsuspend_member';

// Real dispatched failure envelope shape (see file header).
const REAL_ACCESS_DENIED_FAILURE = {
	success: false,
	error: { message: 'You can only view your own suspension status', code: 'PERMISSION_DENIED' },
	meta: { data: { access_denied: true, help: 'You need administrative privileges' } }
};

const REAL_OTHER_FAILURE = {
	success: false,
	error: { message: 'Unable to retrieve suspension status at this time', code: 'INTERNAL_ERROR' }
};

const REAL_SUSPEND_FAILURE = {
	success: false,
	error: { message: 'Member is already suspended', code: 'ALREADY_SUSPENDED' }
};

describe('Member suspension OperationResult handling (#1420)', () => {
	let memberHandlers;
	let frm;
	let consoleWarnSpy;

	beforeAll(() => {
		const controllerPath =
			'/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/member/member.js';
		const allHandlers = loadFrappeController(controllerPath);
		memberHandlers = allHandlers.Member;
	});

	beforeEach(() => {
		cleanupTestMocks();
		global.frappe.user_roles = ['System Manager'];
		global.frappe.user.has_role = jest.fn(() => true);
		global.frappe.model = global.frappe.model || {};
		global.frappe.model.with_doctype = jest.fn((_doctype, cb) => cb && cb());
		global.frappe.perm = global.frappe.perm || {};
		global.frappe.perm.has_perm = jest.fn((_doctype, _level, _perm, cb) => cb && cb(true));

		// Minimal Dialog mock: captures the fields/primary_action member.js configures so
		// the test can invoke primary_action(values) directly, like a real button click.
		global.frappe.ui = global.frappe.ui || {};
		global.frappe.ui.Dialog = jest.fn(function (opts) {
			Object.assign(this, opts);
			this.show = jest.fn();
			this.hide = jest.fn();
			return this;
		});
		global.frappe.confirm = jest.fn((_msg, onYes) => onYes && onYes());

		consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {});

		frm = createMockForm({
			doc: {
				name: 'MEM-2026-001',
				doctype: 'Member',
				docstatus: 1,
				full_name: 'Test Member',
				status: 'Active'
			}
		});
		frm.fields_dict = {};
	});

	afterEach(() => {
		consoleWarnSpy.mockRestore();
	});

	function runRefreshWith(methodResponses) {
		global.frappe.call = jest.fn(({ method, callback }) => {
			if (Object.prototype.hasOwnProperty.call(methodResponses, method)) {
				callback({ message: methodResponses[method] });
			} else if (callback) {
				callback({ message: { success: true } });
			}
		});
		testFormEvent('Member', 'refresh', frm, { Member: memberHandlers });
	}

	describe('access_denied handling', () => {
		it('silently returns on a PERMISSION_DENIED failure (access_denied under meta.data)', () => {
			runRefreshWith({
				[SUSPENSION_STATUS_METHOD]: REAL_ACCESS_DENIED_FAILURE
			});

			expect(consoleWarnSpy).not.toHaveBeenCalled();
			expect(frm.dashboard.add_indicator).not.toHaveBeenCalled();
		});

		it('logs the real server error text for a non-access-denied failure', () => {
			runRefreshWith({
				[SUSPENSION_STATUS_METHOD]: REAL_OTHER_FAILURE
			});

			expect(consoleWarnSpy).toHaveBeenCalledWith(
				expect.stringContaining('Suspension status'),
				'Unable to retrieve suspension status at this time'
			);
		});
	});

	describe('suspend_member / unsuspend_member failure text', () => {
		it('shows the real server error text when suspend_member fails', () => {
			runRefreshWith({
				[CAN_SUSPEND_METHOD]: { success: true, data: { can_suspend: true } },
				[SUSPENSION_STATUS_METHOD]: { success: true, data: { is_suspended: false } }
			});

			const suspendBtnCall = frm.add_custom_button.mock.calls.find((c) => c[0] === 'Suspend Member');
			expect(suspendBtnCall).toBeDefined();
			suspendBtnCall[1](); // open the dialog

			const dialogInstance = global.frappe.ui.Dialog.mock.instances[0];
			global.frappe.call = jest.fn(({ method, callback }) => {
				if (method === SUSPEND_METHOD) {
					callback({ message: REAL_SUSPEND_FAILURE });
				}
			});
			dialogInstance.primary_action({ suspension_reason: 'test' });

			expect(global.frappe.show_alert).toHaveBeenCalledWith({
				message: 'Member is already suspended',
				indicator: 'red'
			});
		});

		it('shows the real server error text when unsuspend_member fails', () => {
			runRefreshWith({
				[CAN_SUSPEND_METHOD]: { success: true, data: { can_suspend: true } },
				[SUSPENSION_STATUS_METHOD]: { success: true, data: { is_suspended: true } }
			});

			const unsuspendBtnCall = frm.add_custom_button.mock.calls.find((c) => c[0] === 'Unsuspend Member');
			expect(unsuspendBtnCall).toBeDefined();
			unsuspendBtnCall[1](); // open the dialog

			const dialogInstance = global.frappe.ui.Dialog.mock.instances[0];
			global.frappe.call = jest.fn(({ method, callback }) => {
				if (method === UNSUSPEND_METHOD) {
					callback({
						message: {
							success: false,
							error: { message: 'Member is not suspended', code: 'NOT_SUSPENDED' }
						}
					});
				}
			});
			dialogInstance.primary_action({ unsuspension_reason: 'test' });

			expect(global.frappe.show_alert).toHaveBeenCalledWith({
				message: 'Member is not suspended',
				indicator: 'red'
			});
		});
	});
});
