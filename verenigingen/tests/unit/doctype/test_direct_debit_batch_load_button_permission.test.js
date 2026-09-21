/**
 * @fileoverview Direct Debit Batch: "Load Unpaid Invoices" button visibility (#1221)
 *
 * The button used to be shown unconditionally on any Draft batch, purely on
 * `docstatus === 0`. But the endpoint it calls (`load_unpaid_invoices`) is
 * gated at the CRITICAL security level, which the DocType's own
 * "Verenigingen Staff" role (create/write) does not clear -- so a Staff user
 * saw a button that always ended in "Access denied".
 *
 * The fix asks the server (`can_load_unpaid_invoices`) before rendering the
 * button. These tests drive the real controller through that async check with
 * both answers and assert the button is added only when authorized.
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

describe('Direct Debit Batch: Load Unpaid Invoices button gating (#1221)', () => {
	let batchHandlers;
	let frm;
	let originalCall;

	beforeAll(() => {
		const controllerPath =
			'/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen_payments/doctype/direct_debit_batch/direct_debit_batch.js';
		const allHandlers = loadFrappeController(controllerPath);
		batchHandlers = allHandlers['Direct Debit Batch'];
		expect(batchHandlers.refresh).toBeDefined();
	});

	beforeEach(() => {
		cleanupTestMocks();
		originalCall = global.frappe.call;

		frm = createMockForm({
			doc: {
				name: 'DD-BATCH-2026-001',
				doctype: 'Direct Debit Batch',
				docstatus: 0,
				status: 'Draft',
				invoices: []
			}
		});
		frm.fields_dict = { invoices: { wrapper: global.$() } };
	});

	afterEach(() => {
		global.frappe.call = originalCall;
	});

	function methodNamesCalled(mockCall) {
		return mockCall.mock.calls.map((call) => call[0].method);
	}

	function customButtonLabels(mockAddCustomButton) {
		return mockAddCustomButton.mock.calls.map((call) => call[0]);
	}

	const CAN_LOAD_METHOD =
		'verenigingen.verenigingen_payments.doctype.direct_debit_batch.direct_debit_batch.can_load_unpaid_invoices';

	it('queries can_load_unpaid_invoices on a Draft batch', () => {
		global.frappe.call = jest.fn(({ callback }) => {
			if (callback) callback({ message: false });
		});

		testFormEvent('Direct Debit Batch', 'refresh', frm, { 'Direct Debit Batch': batchHandlers });

		expect(methodNamesCalled(global.frappe.call)).toContain(CAN_LOAD_METHOD);
	});

	it('shows "Load Unpaid Invoices" when the server grants CRITICAL access', () => {
		global.frappe.call = jest.fn(({ method, callback }) => {
			if (method === CAN_LOAD_METHOD && callback) {
				callback({ message: true });
			}
		});

		testFormEvent('Direct Debit Batch', 'refresh', frm, { 'Direct Debit Batch': batchHandlers });

		expect(customButtonLabels(frm.add_custom_button)).toContain('Load Unpaid Invoices');
	});

	it('hides "Load Unpaid Invoices" when the server denies CRITICAL access (Staff role/profile)', () => {
		global.frappe.call = jest.fn(({ method, callback }) => {
			if (method === CAN_LOAD_METHOD && callback) {
				callback({ message: false });
			}
		});

		testFormEvent('Direct Debit Batch', 'refresh', frm, { 'Direct Debit Batch': batchHandlers });

		expect(customButtonLabels(frm.add_custom_button)).not.toContain('Load Unpaid Invoices');
	});

	it('still shows "Validate Mandates" regardless of the CRITICAL check (unaffected button)', () => {
		global.frappe.call = jest.fn(({ method, callback }) => {
			if (method === CAN_LOAD_METHOD && callback) {
				callback({ message: false });
			}
		});

		testFormEvent('Direct Debit Batch', 'refresh', frm, { 'Direct Debit Batch': batchHandlers });

		expect(customButtonLabels(frm.add_custom_button)).toContain('Validate Mandates');
	});
});
