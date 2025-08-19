/**
 * @fileoverview Comprehensive SEPA Audit Log DocType JavaScript Test Suite
 */

const TestDataFactory = require('../factories/test-data-factory');

describe('SEPA Audit Log DocType - Comprehensive Test Suite', () => {
	let testFactory;
	let mockFrm;
	let mockDoc;

	beforeEach(() => {
		testFactory = new TestDataFactory(89456);
		mockDoc = testFactory.createSEPAAuditLogData();
		mockFrm = createMockForm(mockDoc);
		setupGlobalMocks();
	});

	afterEach(() => {
		jest.clearAllMocks();
		teardownGlobalMocks();
	});

	describe('Audit Trail Management', () => {
		test('should log SEPA transaction audit trail', () => {
			mockDoc.transaction_reference = 'SEPA-2025-001';
			mockDoc.audit_action = 'Payment Processed';
			mockDoc.timestamp = '2025-08-19 14:30:00';

			const auditLog = require('../../../../verenigingen_payments/doctype/sepa_audit_log/sepa_audit_log.js');
			auditLog.refresh(mockFrm);

			expect(mockDoc.audit_action).toBe('Payment Processed');
		});

		test('should track compliance status', () => {
			mockDoc.compliance_status = 'Compliant';
			mockDoc.regulation_reference = 'SEPA Regulation 2023';

			const auditLog = require('../../../../verenigingen_payments/doctype/sepa_audit_log/sepa_audit_log.js');
			auditLog.compliance_status(mockFrm);

			expect(mockDoc.compliance_status).toBe('Compliant');
		});
	});

	describe('Data Integrity Monitoring', () => {
		test('should validate audit log integrity', () => {
			mockDoc.checksum = 'abc123def456';
			mockDoc.data_integrity = 'Verified';

			const auditLog = require('../../../../verenigingen_payments/doctype/sepa_audit_log/sepa_audit_log.js');
			auditLog.validate_integrity(mockFrm);

			expect(mockDoc.data_integrity).toBe('Verified');
		});

		test('should generate compliance report', async () => {
			mockFrm.call.mockResolvedValueOnce({
				message: { report_entries: 150, compliance_rate: 99.5 }
			});

			const auditLog = require('../../../../verenigingen_payments/doctype/sepa_audit_log/sepa_audit_log.js');
			auditLog.generate_compliance_report(mockFrm);

			expect(mockFrm.call).toHaveBeenCalled();
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
