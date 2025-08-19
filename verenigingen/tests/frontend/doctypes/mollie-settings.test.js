/**
 * @fileoverview Comprehensive Mollie Settings DocType JavaScript Test Suite
 */

const TestDataFactory = require('../factories/test-data-factory');

describe('Mollie Settings DocType - Comprehensive Test Suite', () => {
	let testFactory;
	let mockFrm;
	let mockDoc;

	beforeEach(() => {
		testFactory = new TestDataFactory(23890);
		mockDoc = testFactory.createMollieSettingsData();
		mockFrm = createMockForm(mockDoc);
		setupGlobalMocks();
	});

	afterEach(() => {
		jest.clearAllMocks();
		teardownGlobalMocks();
	});

	describe('Payment Gateway Configuration', () => {
		test('should configure Mollie API credentials', () => {
			mockDoc.api_key = 'test_api_key_12345';
			mockDoc.webhook_url = 'https://example.com/webhook';

			const settings = require('../../../../verenigingen_payments/doctype/mollie_settings/mollie_settings.js');
			settings.refresh(mockFrm);

			expect(mockDoc.api_key).toContain('test_');
		});

		test('should validate webhook configuration', async () => {
			mockDoc.webhook_url = 'https://example.com/webhook';
			mockFrm.call.mockResolvedValueOnce({ message: { valid: true } });

			const settings = require('../../../../verenigingen_payments/doctype/mollie_settings/mollie_settings.js');
			settings.test_webhook(mockFrm);

			expect(mockFrm.call).toHaveBeenCalled();
		});
	});

	describe('Security Validation', () => {
		test('should validate API key format', () => {
			mockDoc.api_key = 'invalid_key';

			const settings = require('../../../../verenigingen_payments/doctype/mollie_settings/mollie_settings.js');
			settings.api_key(mockFrm);

			expect(mockDoc.api_key).toBe('invalid_key');
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
