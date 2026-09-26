/* eslint-env jest */
/**
 * @fileoverview member.js "Rebuild Fee Change History" button response handling (#1420)
 *
 * `refresh_fee_change_history` (member.js) called
 * `verenigingen.verenigingen.doctype.member.member.refresh_fee_change_history` and read
 * the response FLAT (`r.message.reload_doc`, `r.message.history_count`). The endpoint is
 * decorated with `@high_security_api`, which serializes its `OperationResult` via
 * `to_dict(scrub_sensitive=True)` -- the NESTED schema: those fields live under
 * `r.message.data`, never at the top level, even though `r.message.success` IS a real
 * top-level key. So the "reload needed" branch never ran.
 *
 * The fixtures below are the REAL shapes captured via an actual dispatch through the
 * `@high_security_api` decorator stack on test_site_6
 * (verenigingen/tests/services/test_member_history_update_service_realdb.py::
 * TestRefreshFeeChangeHistoryWireEnvelopeRealDB), not hand-written guesses:
 *
 *   success (changes made):
 *     {success: true, data: {history_count, reload_doc: true, dues_schedules_found, ...}}
 *   success (no changes -- reload_doc key absent, method: "no_changes"):
 *     {success: true, data: {history_count, dues_schedules_found, ...}}  // no reload_doc
 *   failure:
 *     {success: false, error: {message: "...", code: "HIST_006"}}
 *
 * These tests drive the REAL `refresh_fee_change_history(frm)` function through the
 * "Rebuild Fee Change History" button the real controller registers (loaded via
 * loadFrappeController), not a reimplementation of it.
 */

const { setupTestMocks, cleanupTestMocks, createMockForm } = require('../../setup/frappe-mocks');
const { loadFrappeController, testFormEvent } = require('../../setup/controller-loader');

setupTestMocks();

// setupTestMocks()'s frappe.provide is a no-op jest.fn(), so it never actually builds the
// verenigingen.utils namespace operation-result-helpers.js writes to. Install the real
// namespacing behaviour (same as operation-result-helpers.test.js) and require the REAL
// helpers module, so this test exercises the same window.unwrapOperationResult/
// getErrorMessage member.js gets in production (via app_include_js) -- not member.js's own
// `if (!window.unwrapOperationResult)` fallback shim, which is a narrower reimplementation
// only meant for a stale-cache edge case and diverges from the real helper (#674's fix was
// never mirrored into it).
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

const REFRESH_METHOD = 'verenigingen.verenigingen.doctype.member.member.refresh_fee_change_history';

// Real dispatched envelopes (see file header) -- reload_doc: true is the "changes made"
// branch (method: "atomic_with_amendments"); the "no_changes" branch omits reload_doc
// entirely rather than sending it as false.
const REAL_SUCCESS_WITH_RELOAD = {
	success: true,
	timestamp: '2026-09-26 10:58:00.000000',
	data: {
		history_count: 3,
		reload_doc: true,
		amendments_found: 0,
		dues_schedules_found: 2,
		removed_entries: 0,
		cleanup_details: { removed: 0, reasons: { total: 0 }, errors: [] },
		method: 'atomic_with_amendments'
	}
};

const REAL_SUCCESS_NO_CHANGES = {
	success: true,
	timestamp: '2026-09-26 10:58:00.000000',
	data: {
		history_count: 0,
		amendments_found: 0,
		dues_schedules_found: 0,
		removed_entries: 0,
		cleanup_details: { removed: 0, reasons: { total: 0 }, errors: [] },
		method: 'no_changes'
	}
};

const REAL_FAILURE = {
	success: false,
	timestamp: '2026-09-26 10:58:51.850042',
	error: {
		message: 'Error: Member MEM-DOES-NOT-EXIST-XYZ not found',
		code: 'HIST_006'
	}
};

describe('Member "Rebuild Fee Change History" button (#1420)', () => {
	let memberHandlers;
	let frm;
	let originalCall;

	beforeAll(() => {
		const controllerPath =
			'/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/member/member.js';
		const allHandlers = loadFrappeController(controllerPath);
		memberHandlers = allHandlers.Member;
		expect(memberHandlers.refresh).toBeDefined();
	});

	beforeEach(() => {
		cleanupTestMocks();
		originalCall = global.frappe.call;
		global.frappe.user_roles = ['System Manager'];
		global.frappe.user.has_role = jest.fn(() => true);
		global.frappe.model = global.frappe.model || {};
		global.frappe.model.with_doctype = jest.fn((_doctype, cb) => cb && cb());
		global.frappe.perm = global.frappe.perm || {};
		global.frappe.perm.has_perm = jest.fn((_doctype, _level, _perm, cb) => cb && cb(true));

		frm = createMockForm({
			doc: {
				name: 'MEM-2026-001',
				doctype: 'Member',
				docstatus: 1,
				customer: 'CUST-001',
				status: 'Active'
			}
		});
		frm.fields_dict = {};
		frm.call = jest.fn();
		frm.reload_doc = jest.fn(() => Promise.resolve());
	});

	afterEach(() => {
		global.frappe.call = originalCall;
	});

	/** Drives `refresh(frm)`, captures the "Rebuild Fee Change History" button's onclick,
	 * and returns it so the test can invoke it (and only it) directly. */
	function getRebuildFeeHistoryCallback() {
		// refresh() itself makes several other frappe.call requests (donor check,
		// suspension status, termination status, ...); answer all of those genially so
		// refresh() completes, without touching REFRESH_METHOD (not called during
		// refresh -- only when the button is clicked).
		global.frappe.call = jest.fn(({ callback }) => {
			if (callback) callback({ message: { success: true } });
		});

		testFormEvent('Member', 'refresh', frm, { Member: memberHandlers });

		const call = frm.add_custom_button.mock.calls.find((c) => c[0] === 'Rebuild Fee Change History');
		expect(call).toBeDefined();
		return call[1];
	}

	it('reloads the document and reports the real history_count when the server sets reload_doc (changes made)', () => {
		const onClick = getRebuildFeeHistoryCallback();

		global.frappe.call = jest.fn(({ method, callback }) => {
			if (method === REFRESH_METHOD) {
				callback({ message: REAL_SUCCESS_WITH_RELOAD });
			} else if (callback) {
				callback({ message: { success: true } });
			}
		});

		onClick();

		expect(frm.reload_doc).toHaveBeenCalled();
		const alertCall = global.frappe.show_alert.mock.calls[0][0];
		expect(alertCall.message).toContain('3 entries');
		expect(alertCall.indicator).toBe('green');
	});

	it('does NOT reload and refreshes the field in place when the server omits reload_doc (no changes)', () => {
		const onClick = getRebuildFeeHistoryCallback();

		global.frappe.call = jest.fn(({ method, callback }) => {
			if (method === REFRESH_METHOD) {
				callback({ message: REAL_SUCCESS_NO_CHANGES });
			} else if (callback) {
				callback({ message: { success: true } });
			}
		});
		frm.call.mockImplementation(({ callback }) => {
			if (callback) callback({ message: { success: true, added_entries: 0 } });
		});

		onClick();

		expect(frm.reload_doc).not.toHaveBeenCalled();
		expect(frm.refresh_field).toHaveBeenCalledWith('fee_change_history');
	});

	it('shows the real server error text on failure, not a generic fallback', () => {
		const onClick = getRebuildFeeHistoryCallback();

		global.frappe.call = jest.fn(({ method, callback }) => {
			if (method === REFRESH_METHOD) {
				callback({ message: REAL_FAILURE });
			} else if (callback) {
				callback({ message: { success: true } });
			}
		});

		onClick();

		expect(frm.reload_doc).not.toHaveBeenCalled();
		const alertCall = global.frappe.show_alert.mock.calls[0][0];
		expect(alertCall.message).toBe('Error: Member MEM-DOES-NOT-EXIST-XYZ not found');
		expect(alertCall.indicator).toBe('red');
	});
});
