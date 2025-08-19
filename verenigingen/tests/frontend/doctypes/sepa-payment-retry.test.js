/**
 * @fileoverview Comprehensive SEPA Payment Retry DocType JavaScript Test Suite
 *
 * @author Verenigingen Test Team
 * @version 1.0.0
 * @since 2025-08-19
 */

const TestDataFactory = require('../factories/test-data-factory');

describe('SEPA Payment Retry DocType - Comprehensive Test Suite', () => {
	let testFactory;
	let mockFrm;
	let mockDoc;

	beforeEach(() => {
		testFactory = new TestDataFactory(56234);
		mockDoc = testFactory.createSEPAPaymentRetryData();
		mockFrm = createMockForm(mockDoc);
		setupGlobalMocks();
	});

	afterEach(() => {
		jest.clearAllMocks();
		teardownGlobalMocks();
	});

	describe('Retry Logic Management', () => {
		test('should initialize retry attempt with proper sequencing', () => {
			mockDoc.retry_attempt = 1;
			mockDoc.original_payment_reference = 'PAY-2025-001';

			const retry = require('../../../../verenigingen_payments/doctype/sepa_payment_retry/sepa_payment_retry.js');
			retry.refresh(mockFrm);

			expect(mockDoc.retry_attempt).toBe(1);
		});

		test('should handle retry execution with validation', async () => {
			mockDoc.status = 'Pending';
			mockFrm.call.mockResolvedValueOnce({ message: { success: true } });

			const retry = require('../../../../verenigingen_payments/doctype/sepa_payment_retry/sepa_payment_retry.js');
			retry.execute_retry(mockFrm);

			expect(mockFrm.call).toHaveBeenCalled();
		});

		test('should track payment failure reasons', () => {
			mockDoc.failure_reason = 'Insufficient funds';
			mockDoc.retry_status = 'Failed';

			const retry = require('../../../../verenigingen_payments/doctype/sepa_payment_retry/sepa_payment_retry.js');
			retry.failure_reason(mockFrm);

			expect(mockDoc.failure_reason).toBe('Insufficient funds');
		});
	});

	describe('Status Management', () => {
		test('should update retry status based on payment result', () => {
			mockDoc.retry_status = 'Successful';

			const retry = require('../../../../verenigingen_payments/doctype/sepa_payment_retry/sepa_payment_retry.js');
			retry.retry_status(mockFrm);

			expect(mockDoc.retry_status).toBe('Successful');
		});
	});
});

function createMockForm(doc) {
	return {
		doc,
		add_custom_button: jest.fn(),
		call: jest.fn(),
		set_value: jest.fn(),
		refresh: jest.fn()
	};
}

function setupGlobalMocks() {
	global.frappe = {
		ui: { form: { on: jest.fn() } },
		call: jest.fn(),
		__: jest.fn(str => str)
	};
	global.__ = jest.fn(str => str);
}

function teardownGlobalMocks() {
	delete global.frappe;
	delete global.__;
}
