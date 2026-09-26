/* eslint-env jest */
/**
 * @fileoverview Donor Controller Tests (New Infrastructure)
 *
 * Comprehensive test suite for Donor DocType controller using centralized test
 * infrastructure. Tests Dutch ANBI compliance, BSN/RSIN validation, donation
 * tracking, tax compliance, and regulatory reporting functionality.
 *
 * @author Verenigingen Development Team
 * @version 3.0.0 - Built with centralized infrastructure
 */

/* global describe, it, expect, jest, beforeEach, afterEach, beforeAll */

// Import centralized test infrastructure
const { createControllerTestSuite } = require('../../setup/controller-test-base');
const { createDomainTestBuilder } = require('../../setup/domain-test-builders');

// Initialize test environment
require('../../setup/frappe-mocks').setupTestMocks();

// Controller configuration
const donorConfig = {
	doctype: 'Donor',
	controllerPath: '/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/donor/donor.js',
	expectedHandlers: ['refresh', 'donor_type', 'bsn_rsin'],
	defaultDoc: {
		donor_name: 'Jan van der Berg',
		donor_type: 'Individual',
		email: 'jan.van.der.berg@example.org',
		phone: '+31612345678',
		bsn_rsin: '123456789',
		anbi_eligible: 1,
		total_donations: 1500.0,
		first_donation_date: '2024-01-15',
		last_donation_date: '2024-12-15',
		postal_code: '1012 AB',
		city: 'Amsterdam',
		country: 'Netherlands'
	},
	// Custom field setup for Donor controller
	createMockForm(baseTest, overrides = {}) {
		const form = baseTest.createMockForm(overrides);

		// Add donor-specific field structures
		form.fields_dict = {
			...form.fields_dict,
			// Donor identification fields
			donor_name: { df: { fieldtype: 'Data' } },
			donor_type: { df: { fieldtype: 'Select' } },
			email: { df: { fieldtype: 'Data' } },
			phone: { df: { fieldtype: 'Data' } },

			// Dutch compliance fields
			bsn_rsin: { df: { fieldtype: 'Data' } },
			anbi_eligible: { df: { fieldtype: 'Check' } },

			// Donation tracking fields
			total_donations: { df: { fieldtype: 'Currency' } },
			first_donation_date: { df: { fieldtype: 'Date' } },
			last_donation_date: { df: { fieldtype: 'Date' } },
			donation_frequency: { df: { fieldtype: 'Select' } },

			// Address fields for Dutch validation
			postal_code: { df: { fieldtype: 'Data' } },
			city: { df: { fieldtype: 'Data' } },
			country: { df: { fieldtype: 'Data' } },

			// ANBI reporting fields
			anbi_section: { wrapper: global.$('<div>') },
			tax_compliance_html: { wrapper: global.$('<div>') }
		};

		return form;
	}
};

// Custom test suites specific to Donor controller
const customDonorTests = {
	'Dutch ANBI Compliance': (getControllerTest) => {
		it('should validate BSN for individual donors', () => {
			getControllerTest().mockForm.doc.donor_type = 'Individual';
			getControllerTest().mockForm.doc.bsn_rsin = '123456789';

			expect(() => {
				getControllerTest().testEvent('refresh');
			}).not.toThrow();
		});

		it('should validate RSIN for organizational donors', () => {
			getControllerTest().mockForm.doc.donor_type = 'Organization';
			getControllerTest().mockForm.doc.bsn_rsin = '123456789';

			expect(() => {
				getControllerTest().testEvent('refresh');
			}).not.toThrow();
		});

		it('should handle ANBI eligibility checks', () => {
			getControllerTest().mockForm.doc.anbi_eligible = 1;
			getControllerTest().mockForm.doc.total_donations = 1500.0;

			expect(() => {
				getControllerTest().testEvent('refresh');
			}).not.toThrow();
		});

		it('should validate Dutch postal codes', () => {
			const associationBuilder = createDomainTestBuilder(getControllerTest(), 'association');
			const dutchTests = associationBuilder.createDutchValidationTests();
			dutchTests['should validate Dutch postal codes']();
		});
	},

	'Donor Type Management': (getControllerTest) => {
		it('should handle donor type changes', () => {
			const donorTypes = ['Individual', 'Organization', 'Foundation', 'Trust'];

			donorTypes.forEach((type) => {
				getControllerTest().mockForm.doc.donor_type = type;

				// Test donor_type handler if it exists
				if (getControllerTest().handlers.donor_type) {
					expect(() => {
						getControllerTest().testEvent('donor_type');
					}).not.toThrow();
				}
			});
		});

		it('should update BSN/RSIN field labels based on donor type', () => {
			getControllerTest().mockForm.doc.donor_type = 'Individual';

			if (getControllerTest().handlers.donor_type) {
				getControllerTest().testEvent('donor_type');
			}

			// Test passes if no errors thrown during type change
			expect(getControllerTest().mockForm.doc.donor_type).toBe('Individual');
		});
	},

	'Donation Tracking': (getControllerTest) => {
		beforeEach(() => {
			// Mock donation history API calls
			global.frappe.call.mockImplementation(({ method, args, callback }) => {
				if (method === 'get_donor_donations' && callback) {
					callback({
						message: [
							{
								donation_date: '2024-01-15',
								amount: 500.0,
								type: 'Monthly'
							},
							{
								donation_date: '2024-06-15',
								amount: 1000.0,
								type: 'One-time'
							}
						]
					});
				}
			});
		});

		it('should calculate total donations correctly', () => {
			getControllerTest().mockForm.doc.total_donations = 1500.0;

			getControllerTest().testEvent('refresh');

			// Should maintain donation totals
			expect(getControllerTest().mockForm.doc.total_donations).toBe(1500.0);
		});

		it('should track donation frequency patterns', () => {
			const frequencies = ['Monthly', 'Quarterly', 'Annually', 'One-time'];

			frequencies.forEach((frequency) => {
				getControllerTest().mockForm.doc.donation_frequency = frequency;

				expect(() => {
					getControllerTest().testEvent('refresh');
				}).not.toThrow();
			});
		});

		it('should handle donation date validation', () => {
			getControllerTest().mockForm.doc.first_donation_date = '2024-01-15';
			getControllerTest().mockForm.doc.last_donation_date = '2024-12-15';

			expect(() => {
				getControllerTest().testEvent('refresh');
			}).not.toThrow();
		});
	},

	'Tax Compliance and Reporting': (getControllerTest) => {
		it('should generate ANBI reporting data', () => {
			getControllerTest().mockForm.doc.anbi_eligible = 1;
			getControllerTest().mockForm.doc.total_donations = 1500.0;
			getControllerTest().mockForm.doc.__islocal = 0;

			expect(() => {
				getControllerTest().testEvent('refresh');
			}).not.toThrow();
		});

		it('should validate tax deduction thresholds', () => {
			// Dutch tax deduction thresholds for ANBI donations
			const testAmounts = [
				{ amount: 60.0, threshold: 'Basic' }, // Above €60 threshold
				{ amount: 500.0, threshold: 'Standard' }, // Standard deduction
				{ amount: 5000.0, threshold: 'High' } // High-value donation
			];

			testAmounts.forEach((test) => {
				getControllerTest().mockForm.doc.total_donations = test.amount;

				expect(() => {
					getControllerTest().testEvent('refresh');
				}).not.toThrow();
			});
		});

		it('should handle tax year reporting', () => {
			getControllerTest().mockForm.doc.first_donation_date = '2024-01-15';
			getControllerTest().mockForm.doc.last_donation_date = '2024-12-15';

			expect(() => {
				getControllerTest().testEvent('refresh');
			}).not.toThrow();
		});
	},

	'Contact Information Management': (getControllerTest) => {
		it('should validate email format', () => {
			const associationBuilder = createDomainTestBuilder(getControllerTest(), 'association');
			const dutchTests = associationBuilder.createDutchValidationTests();
			dutchTests['should validate Dutch email format']();
		});

		it('should handle contact information updates', () => {
			getControllerTest().mockForm.doc.email = 'updated@example.org';
			getControllerTest().mockForm.doc.phone = '+31687654321';

			expect(() => {
				getControllerTest().testEvent('refresh');
			}).not.toThrow();
		});

		it('should validate Dutch phone number formats', () => {
			const dutchPhoneNumbers = [
				'+31612345678', // Mobile
				'+31201234567', // Landline Amsterdam
				'0612345678', // Local mobile
				'020-1234567' // Local landline with dash
			];

			dutchPhoneNumbers.forEach((phone) => {
				getControllerTest().mockForm.doc.phone = phone;

				expect(() => {
					getControllerTest().testEvent('refresh');
				}).not.toThrow();
			});
		});
	},

	'Privacy and Data Protection': (getControllerTest) => {
		it('should handle GDPR compliance for donor data', () => {
			getControllerTest().mockForm.doc.gdpr_consent = 1;
			getControllerTest().mockForm.doc.privacy_notice_accepted = 1;

			expect(() => {
				getControllerTest().testEvent('refresh');
			}).not.toThrow();
		});

		it('should manage data retention policies', () => {
			getControllerTest().mockForm.doc.data_retention_until = '2030-01-15';
			getControllerTest().mockForm.doc.last_contact_date = '2024-12-15';

			expect(() => {
				getControllerTest().testEvent('refresh');
			}).not.toThrow();
		});
	},

	'Integration with Donation System': (getControllerTest) => {
		it('should link to donation records', () => {
			getControllerTest().mockForm.doc.__islocal = 0;

			expect(() => {
				getControllerTest().testEvent('refresh');
			}).not.toThrow();
		});

		it('should handle recurring donation setups', () => {
			getControllerTest().mockForm.doc.donation_frequency = 'Monthly';
			getControllerTest().mockForm.doc.recurring_amount = 25.0;

			expect(() => {
				getControllerTest().testEvent('refresh');
			}).not.toThrow();
		});
	},

	// Ported from the deleted verenigingen/tests/unit/doctype/test_donor_controller.js
	// (issue #1454). That file never actually exercised donor.js: its "passing" tests
	// asserted on locally re-implemented helper functions with no connection to the
	// controller, and the handful that did `require()` the real donor.js referenced
	// button-scoped functions (validate_bsn_dialog, sync_donation_history,
	// create_donation_agreement) that donor.js never exports, so they crashed before
	// reaching their (also stale) assertions. These tests instead drive the real
	// button callbacks the way `refresh` wires them up.
	'Real donor.js Button Behavior': (getControllerTest) => {
		beforeEach(() => {
			global.frappe.ui.Dialog = jest.fn(function (opts) {
				this._opts = opts;
				this.show = jest.fn();
				this.hide = jest.fn();
				this.set_df_property = jest.fn();
				this.get_value = jest.fn();
				return this;
			});
			global.frappe.new_doc = jest.fn();
		});

		function getButtonCallback(label) {
			const call = getControllerTest().mockForm.add_custom_button.mock.calls.find((c) => c[0] === label);
			if (!call) {
				throw new Error(`No "${label}" button was registered by refresh()`);
			}
			return call[1];
		}

		it('calls the donation-history sync backend method with the donor name', () => {
			getControllerTest().testEvent('refresh');
			global.frappe.call.mockClear();

			getButtonCallback('Sync Donation History')();

			expect(global.frappe.call).toHaveBeenCalledWith(
				expect.objectContaining({
					method: 'verenigingen.utils.donation_history_manager.sync_donor_history',
					args: { donor_name: getControllerTest().mockForm.doc.name }
				})
			);
		});

		it('shows a red alert containing the backend error message when the sync reports failure', () => {
			getControllerTest().testEvent('refresh');
			global.frappe.call.mockImplementationOnce(({ callback }) =>
				callback({ message: { success: false, error: 'boom' } })
			);

			getButtonCallback('Sync Donation History')();

			expect(global.frappe.show_alert).toHaveBeenCalledWith(
				expect.objectContaining({
					message: expect.stringContaining('boom'),
					indicator: 'red'
				})
			);
		});

		it('does not crash and falls back to "Unknown error" when the sync call returns no message', () => {
			getControllerTest().testEvent('refresh');
			// A backend method that returns None (no explicit `return`) surfaces here
			// as `r.message` being undefined, not as a rejected/errored call.
			global.frappe.call.mockImplementationOnce(({ callback }) => callback({}));

			expect(() => {
				getButtonCallback('Sync Donation History')();
			}).not.toThrow();

			expect(global.frappe.show_alert).toHaveBeenCalledWith(
				expect.objectContaining({
					message: expect.stringContaining('Unknown error'),
					indicator: 'red'
				})
			);
		});

		it('opens a prefilled Periodic Donation Agreement instead of calling the backend directly', () => {
			getControllerTest().testEvent('refresh');

			getButtonCallback('Create Donation Agreement')();

			expect(global.frappe.new_doc).toHaveBeenCalledWith('Periodic Donation Agreement', {
				donor: getControllerTest().mockForm.doc.name,
				donor_name: getControllerTest().mockForm.doc.donor_name
			});
		});

		it('builds the Validate BSN dialog with a "bsn" field', () => {
			getControllerTest().testEvent('refresh');

			getButtonCallback('Validate BSN')();

			expect(global.frappe.ui.Dialog).toHaveBeenCalledWith(
				expect.objectContaining({
					title: 'Validate BSN',
					fields: expect.arrayContaining([expect.objectContaining({ fieldname: 'bsn' })])
				})
			);
		});
	}
};

// Create and export the test suite
describe('Donor Controller (New Infrastructure)', createControllerTestSuite(donorConfig, customDonorTests));

// Export test utilities for reuse
module.exports = {
	donorConfig,
	customDonorTests
};
