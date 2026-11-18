/**
 * @fileoverview Direct Debit Batch: "Load Unpaid Invoices" failure vs empty (#1220)
 *
 * `load_unpaid_invoices` is @handle_api_error-wrapped, so a validation failure comes back as
 * {success: false, error: {message}} and `unwrapOperationResult` returns null for it. The dialog
 * callback used to treat that null like "nothing matched" and showed "No unpaid invoices found"
 * for every failure. These tests drive the real controller and dialog callback with the REAL
 * operation-result helpers (the shared mock getErrorMessage reads a top-level `message`, which a
 * real failure does not have).
 */

/* global describe, it, expect, jest, beforeEach, afterEach, beforeAll */

const { setupTestMocks, cleanupTestMocks, createMockForm } = require('../../setup/frappe-mocks');
const { loadFrappeController, testFormEvent } = require('../../setup/controller-loader');

setupTestMocks();

global.$ = jest.fn(() => ({
	appendTo: jest.fn(() => global.$()),
	find: jest.fn(() => global.$()),
	prepend: jest.fn(),
	on: jest.fn(),
	length: 1
}));

const LOAD_METHOD = 'verenigingen.verenigingen_payments.api.sepa_batch_ui.load_unpaid_invoices';
const CAN_LOAD_METHOD =
	'verenigingen.verenigingen_payments.doctype.direct_debit_batch.direct_debit_batch.can_load_unpaid_invoices';
const NO_INVOICES = 'No unpaid invoices found matching criteria';

describe('Direct Debit Batch: Load Unpaid Invoices failure vs empty (#1220)', () => {
	let batchHandlers;
	let frm;
	let dialogConfig;
	let originalCall;
	let originalDialog;

	beforeAll(() => {
		// Real helpers, not the mock-suite approximations.
		global.frappe.provide = global.frappe.provide || jest.fn();
		global.verenigingen.utils = {};
		jest.isolateModules(() => {
			require('../../../public/js/utils/operation-result-helpers.js');
		});
		global.unwrapOperationResult = global.verenigingen.utils.unwrapOperationResult;
		global.getErrorMessage = global.verenigingen.utils.getErrorMessage;
		global.isFailureResult = global.verenigingen.utils.isFailureResult;

		const allHandlers = loadFrappeController(
			'verenigingen/verenigingen_payments/doctype/direct_debit_batch/direct_debit_batch.js'
		);
		batchHandlers = allHandlers['Direct Debit Batch'];
	});

	beforeEach(() => {
		cleanupTestMocks();
		originalCall = global.frappe.call;
		originalDialog = global.frappe.ui.Dialog;
		global.frappe.ui.Dialog = jest.fn(function (config) {
			dialogConfig = config;
			this.show = jest.fn();
			this.hide = jest.fn();
		});
		global.frappe.msgprint = jest.fn();
		global.frappe.utils = global.frappe.utils || {};
		global.frappe.utils.escape_html = (v) => String(v).replace(/</g, '&lt;');
		global.frappe.show_alert = jest.fn();

		frm = createMockForm({
			doc: { name: 'DD-BATCH-1', doctype: 'Direct Debit Batch', docstatus: 0, status: 'Draft', invoices: [] }
		});
		frm.fields_dict = { invoices: { wrapper: global.$() } };
		frm.add_child = jest.fn();
		frm.refresh_field = jest.fn();
		frm.set_value = jest.fn();
		frm.dirty = jest.fn();
	});

	afterEach(() => {
		global.frappe.call = originalCall;
		global.frappe.ui.Dialog = originalDialog;
	});

	/** Open the dialog via the real refresh -> button -> load_unpaid_invoices path. */
	function openDialogAndSubmit(loadResponse) {
		global.frappe.call = jest.fn(({ method, callback }) => {
			if (method === CAN_LOAD_METHOD) callback({ message: true });
			if (method === LOAD_METHOD) callback(loadResponse);
		});
		testFormEvent('Direct Debit Batch', 'refresh', frm, { 'Direct Debit Batch': batchHandlers });
		const loadButton = frm.add_custom_button.mock.calls.find((c) => c[0] === 'Load Unpaid Invoices');
		loadButton[1]();
		dialogConfig.primary_action({ limit: 100 });
	}

	function msgprintTexts() {
		return global.frappe.msgprint.mock.calls.map((c) => (typeof c[0] === 'string' ? c[0] : c[0].message));
	}

	it('shows the server error message on an OperationResult failure, not "no invoices"', () => {
		openDialogAndSubmit({
			message: {
				success: false,
				error: { message: 'Invalid limit. Must be between 1 and 10000', code: 'SEPA_ERROR' },
				meta: {}
			}
		});

		const texts = msgprintTexts();
		expect(texts.some((t) => t.includes('Invalid limit. Must be between 1 and 10000'))).toBe(true);
		expect(texts).not.toContain(NO_INVOICES);
		expect(frm.add_child).not.toHaveBeenCalled();
	});

	it('keeps "No unpaid invoices found" for a genuine empty success', () => {
		openDialogAndSubmit({ message: { success: true, data: [], meta: {} }, total_eligible: 0 });

		expect(msgprintTexts()).toContain(NO_INVOICES);
	});

	it('adds rows for a success with data', () => {
		openDialogAndSubmit({
			message: { success: true, data: [{ invoice: 'SINV-1', amount: 10 }], meta: {} },
			total_eligible: 1
		});

		expect(frm.add_child).toHaveBeenCalledWith('invoices', { invoice: 'SINV-1', amount: 10 });
		expect(msgprintTexts()).not.toContain(NO_INVOICES);
	});
});
