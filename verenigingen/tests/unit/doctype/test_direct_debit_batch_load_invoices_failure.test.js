/**
 * @fileoverview Direct Debit Batch: server failures in the batch form reach the operator (#1220)
 *
 * MEASURED through the real WSGI app (logged-in user with the "Verenigingen System Administrator"
 * role profile, 2026-11-18): `load_unpaid_invoices(date_range="bogus")` answers HTTP **400** with
 * the body below. @handle_api_error sets the real HTTP status (#481), and frappe's request.js only
 * runs `opts.callback` for a 200, so a failure NEVER reaches `callback`: with no 400 handler it goes
 * to `opts.error(xhr)` (xhr.responseJSON is this body). The tests therefore drive `opts.error`, not
 * `callback({message: failure})`. `validate_invoice_mandate` / `get_invoice_mandate_info` are NOT
 * @handle_api_error endpoints: a refusal is a plain 200 `{valid: false, error}`, a missing record
 * a 200 with no `message` at all.
 */

/* global describe, it, expect, jest, beforeEach, afterEach, beforeAll */

const { setupTestMocks, cleanupTestMocks, createMockForm } = require('../../setup/frappe-mocks');
const { loadFrappeController, testFormEvent } = require('../../setup/controller-loader');

setupTestMocks();

global.$ = jest.fn(() => ({
	appendTo: jest.fn(() => global.$()),
	find: jest.fn(() => global.$()),
	prepend: jest.fn(),
	text: jest.fn(),
	html: jest.fn(),
	toggle: jest.fn(),
	each: jest.fn(),
	on: jest.fn(),
	length: 1
}));

const LOAD_METHOD = 'verenigingen.verenigingen_payments.api.sepa_batch_ui.load_unpaid_invoices';
const CAN_LOAD_METHOD =
	'verenigingen.verenigingen_payments.doctype.direct_debit_batch.direct_debit_batch.can_load_unpaid_invoices';
const NO_INVOICES = 'No unpaid invoices found matching criteria';

describe('Direct Debit Batch: Load Unpaid Invoices failure vs empty (#1220)', () => {
	let batchHandlers;
	let childHandlers;
	let frm;
	let dialogConfig;
	let originalCall;
	let originalDialog;

	beforeAll(() => {
		// Real helpers, not the mock-suite approximations.
		global.frappe.provide = global.frappe.provide || jest.fn();
		global.verenigingen.utils = {};
		global.locals = {};
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
		childHandlers = allHandlers['Direct Debit Batch Invoice'];
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

	// Body measured for date_range='bogus' (HTTP 400); the headers/token keys are the framework's own.
	const MEASURED_400_BODY = {
		headers: { 'X-RateLimit-Limit': '5000', 'X-CSRF-Token': 'redacted' },
		message: {
			success: false,
			timestamp: '2026-11-18 13:57:26.435040',
			error: {
				message: 'Invalid date_range. Valid options: overdue, due_this_week, due_this_month, all',
				errors: ['SEPAError'],
				code: 'SEPA_ERROR',
				http_status: 400
			},
			meta: { details: {}, trace_id: 'c31933debe1e4095' }
		}
	};
	const MEASURED_MESSAGE = 'Invalid date_range. Valid options: overdue, due_this_week, due_this_month, all';

	/** Open the dialog via the real refresh -> button -> load_unpaid_invoices path. */
	function openDialogAndSubmit(respond) {
		global.frappe.call = jest.fn((opts) => {
			if (opts.method === CAN_LOAD_METHOD) opts.callback({ message: true });
			if (opts.method === LOAD_METHOD) respond(opts);
		});
		testFormEvent('Direct Debit Batch', 'refresh', frm, { 'Direct Debit Batch': batchHandlers });
		const loadButton = frm.add_custom_button.mock.calls.find((c) => c[0] === 'Load Unpaid Invoices');
		loadButton[1]();
		dialogConfig.primary_action({ limit: 100 });
	}

	function msgprintTexts() {
		return global.frappe.msgprint.mock.calls.map((c) => (typeof c[0] === 'string' ? c[0] : c[0].message));
	}

	describe('Load Unpaid Invoices', () => {
		it('a real 400 (opts.error with the xhr) shows the server message, not "no invoices"', () => {
			openDialogAndSubmit((opts) => opts.error({ status: 400, responseJSON: MEASURED_400_BODY }));

			const texts = msgprintTexts();
			expect(texts.some((t) => t.includes(MEASURED_MESSAGE))).toBe(true);
			expect(texts).not.toContain(NO_INVOICES);
			expect(frm.add_child).not.toHaveBeenCalled();
		});

		it('a 417 (opts.error with the parsed body) shows the server message too', () => {
			openDialogAndSubmit((opts) => opts.error(MEASURED_400_BODY));

			expect(msgprintTexts().some((t) => t.includes(MEASURED_MESSAGE))).toBe(true);
		});

		it('escapes the server message', () => {
			const body = JSON.parse(JSON.stringify(MEASURED_400_BODY));
			body.message.error.message = '<img src=x onerror=alert(1)>';
			openDialogAndSubmit((opts) => opts.error({ status: 400, responseJSON: body }));

			const texts = msgprintTexts();
			expect(texts.some((t) => t.includes('&lt;img'))).toBe(true);
			expect(texts.some((t) => t.includes('<img'))).toBe(false);
		});

		it('adds nothing when frappe passes no body (403/500: frappe already showed its dialog)', () => {
			openDialogAndSubmit((opts) => opts.error());

			expect(global.frappe.msgprint).not.toHaveBeenCalled();
			expect(frm.add_child).not.toHaveBeenCalled();
		});

		it('keeps "No unpaid invoices found" for a genuine empty success', () => {
			openDialogAndSubmit((opts) =>
				opts.callback({ message: { success: true, data: [], meta: {} }, total_eligible: 0 })
			);

			expect(msgprintTexts()).toContain(NO_INVOICES);
		});

		it('adds rows for a success with data', () => {
			openDialogAndSubmit((opts) =>
				opts.callback({
					message: { success: true, data: [{ invoice: 'SINV-1', amount: 10 }], meta: {} },
					total_eligible: 1
				})
			);

			expect(frm.add_child).toHaveBeenCalledWith('invoices', { invoice: 'SINV-1', amount: 10 });
			expect(msgprintTexts()).not.toContain(NO_INVOICES);
		});
	});

	describe('invoices_add (get_invoice_mandate_info: plain 200, not an OperationResult)', () => {
		const REFUSAL =
			'Member Jan has 2 active SEPA mandates; refusing to guess which IBAN to debit. Cancel all but one.';

		beforeEach(() => {
			global.frappe.model = global.frappe.model || {};
			global.frappe.model.set_value = jest.fn();
			global.locals['Direct Debit Batch Invoice'] = { ROW1: { invoice: 'SINV-1', member: 'M-1' } };
		});

		function addRowWith(response) {
			global.frappe.call = jest.fn(({ callback }) => callback(response));
			childHandlers.invoices_add(frm, 'Direct Debit Batch Invoice', 'ROW1');
		}

		it('shows the refusal and leaves the row fields untouched on {valid: false, error}', () => {
			addRowWith({ message: { valid: false, error: REFUSAL } });

			expect(msgprintTexts().some((t) => t.includes(REFUSAL))).toBe(true);
			expect(global.frappe.model.set_value).not.toHaveBeenCalled();
		});

		it('still fills the row for {valid: true, ...}', () => {
			addRowWith({
				message: { iban: 'NL01', bic: 'B', mandate_reference: 'MR', mandate_date: '2026-01-01', valid: true }
			});

			const setValue = global.frappe.model.set_value;
			expect(setValue).toHaveBeenCalledWith('Direct Debit Batch Invoice', 'ROW1', 'iban', 'NL01');
			expect(setValue).toHaveBeenCalledWith(
				'Direct Debit Batch Invoice',
				'ROW1',
				'mandate_sign_date',
				'2026-01-01'
			);
			expect(global.frappe.msgprint).not.toHaveBeenCalled();
		});

		it('does nothing for a missing record (200 with no message at all)', () => {
			addRowWith({});

			expect(global.frappe.model.set_value).not.toHaveBeenCalled();
			expect(global.frappe.msgprint).not.toHaveBeenCalled();
		});
	});
});
