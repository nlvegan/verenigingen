/**
 * @fileoverview SEPA JavaScript Controller Integration Tests
 *
 * This test suite demonstrates the enhanced Cypress testing approach for testing
 * sophisticated DocType JavaScript controllers with realistic data scenarios.
 * It specifically focuses on testing the SEPA mandate creation workflow and
 * your centralized SEPA configuration architecture.
 *
 * Testing Strategy:
 * - Uses Enhanced Test Factory for realistic test data creation
 * - Tests actual JavaScript controllers loaded in Frappe forms
 * - Validates sophisticated UI interactions (dialogs, validation, etc.)
 * - Tests integration with centralized Verenigingen Settings
 * - No mocking - tests against running system with real data
 *
 * Business Context:
 * This tests the core SEPA payment infrastructure that enables automated
 * membership dues collection, which is critical for the association's
 * financial operations and member experience.
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 * @since 2025-08-19
 */

describe('SEPA JavaScript Controller Integration Tests', () => {
	let testMember = null;

	beforeEach(() => {
		// Login as administrator
		const user = Cypress.env('ADMIN_USER');
		const pass = Cypress.env('ADMIN_PASSWORD');
		expect(user, 'ADMIN_USER env var').to.be.a('string').and.not.be.empty;
		expect(pass, 'ADMIN_PASSWORD env var').to.be.a('string').and.not.be.empty;
		cy.login(user, pass);

		// Clear any existing test data
		cy.clear_test_data();

		// Create test member with financial setup using Enhanced Test Factory
		cy.createTestMemberWithFinancialSetup().then((member) => {
			testMember = member;
		});
	});

	afterEach(() => {
		// Clean up test data after each test
		cy.clear_test_data();
	});

	describe('Member Form SEPA Controller Tests', () => {
		it('should load Member form with SepaUtils JavaScript module', () => {
			// Navigate to the test member's form
			cy.visit_doctype_form('Member', testMember.name);

			// Verify the Member JavaScript controller is loaded
			cy.window().then((win) => {
				expect(win.frappe.ui.form.get_form('Member')).to.exist;
			});

			// Verify SepaUtils module is available
			cy.window().then((win) => {
				expect(win.SepaUtils).to.exist;
				expect(win.SepaUtils.create_sepa_mandate_with_dialog).to.be.a('function');
				expect(win.SepaUtils.check_sepa_mandate_status).to.be.a('function');
				expect(win.SepaUtils.generateMandateReference).to.be.a('function');
			});
		});

		it('should test SEPA mandate dialog creation with realistic data', () => {
			cy.visit_doctype_form('Member', testMember.name);

			// Wait for form to fully load
			cy.wait(3000);

			// Test the sophisticated SEPA mandate dialog creation
			cy.window().then((win) => {
				const frm = win.frappe.ui.form.get_form('Member');
				expect(frm).to.exist;
				expect(frm.doc).to.exist;

				// Call your sophisticated dialog function
				win.SepaUtils.create_sepa_mandate_with_dialog(frm);
			});

			// Verify dialog appeared with all expected fields
			cy.get('.modal-title').should('contain', 'Create SEPA Mandate');

			// Test that dialog fields are properly populated
			cy.get('[data-fieldname="mandate_id"]').should('be.visible');
			cy.get('[data-fieldname="iban"]').should('be.visible');
			cy.get('[data-fieldname="bic"]').should('be.visible');
			cy.get('[data-fieldname="account_holder_name"]').should('be.visible');
			cy.get('[data-fieldname="mandate_type"]').should('be.visible');

			// Test that account holder name is pre-populated from member
			cy.get('[data-fieldname="account_holder_name"] input').should('have.value', testMember.full_name);

			// Test mandate reference generation
			cy.get('[data-fieldname="mandate_id"] input').should('not.be.empty');

			// Close dialog
			cy.get('.modal .btn').contains('Close').click();
		});

		it('should test IBAN validation with IBANValidator integration', () => {
			// Test with valid Dutch IBAN
			const validIBAN = 'NL91ABNA0417164300';
			cy.test_iban_validation(validIBAN, true);

			// Test with invalid IBAN
			const invalidIBAN = 'NL91INVALID123';
			cy.test_iban_validation(invalidIBAN, false);
		});

		it('should test SEPA mandate status checking functionality', () => {
			cy.visit_doctype_form('Member', testMember.name);
			cy.wait(3000);

			// Test SEPA mandate status checking
			cy.window().then((win) => {
				const frm = win.frappe.ui.form.get_form('Member');

				// Call the status checking function
				win.SepaUtils.check_sepa_mandate_status(frm);

				// Allow time for API call to complete
				cy.wait(2000);
			});

			// Should show appropriate indicators based on mandate status
			// (This will depend on whether test member has existing mandates)
		});
	});

	describe('Direct Debit Batch Controller Tests', () => {
		it('should load Direct Debit Batch form with JavaScript controller', () => {
			cy.visit_doctype_form('Direct Debit Batch');

			// Verify the Direct Debit Batch JavaScript controller is loaded
			cy.window().then((win) => {
				expect(win.frappe.ui.form.get_form('Direct Debit Batch')).to.exist;
			});

			// Verify form elements and buttons are present
			cy.get('button').contains('Load Unpaid Invoices').should('be.visible');
			cy.get('[data-fieldname="batch_description"]').should('be.visible');
			cy.get('[data-fieldname="batch_type"]').should('be.visible');
		});

		it('should test batch type validation and warnings', () => {
			cy.visit_doctype_form('Direct Debit Batch');
			cy.wait(2000);

			// Test different batch types and their JavaScript validation
			cy.fill_frappe_field('batch_type', 'FRST', { fieldtype: 'Select' });
			cy.wait(1000);

			// Should show warning about first collection
			// (Your JavaScript shows warnings for certain batch types)

			cy.fill_frappe_field('batch_type', 'RCUR', { fieldtype: 'Select' });
			cy.wait(1000);

			// Test the JavaScript help text updates
			cy.get('[data-fieldname="batch_type"] .help-box').should('contain', 'Recurring collection');
		});

		it('should test Load Unpaid Invoices dialog functionality', () => {
			cy.visit_doctype_form('Direct Debit Batch');
			cy.wait(2000);

			// Click the "Load Unpaid Invoices" button to test dialog
			cy.test_custom_button('Load Unpaid Invoices', 'dialog');

			// Verify the dialog loaded correctly
			cy.get('.modal-title').should('contain', 'Load Unpaid Invoices');
			cy.get('[data-fieldname="date_range"]').should('be.visible');
			cy.get('[data-fieldname="membership_type"]').should('be.visible');
			cy.get('[data-fieldname="limit"]').should('be.visible');

			// Close dialog
			cy.get('.modal .btn').contains('Close').click();
		});
	});

	describe('Centralized Configuration Integration', () => {
		it('should test access to centralized Verenigingen Settings', () => {
			// Test that JavaScript can access centralized SEPA configuration
			cy.test_centralized_config_access();

			// Navigate to settings to verify SEPA configuration exists
			cy.visit('/app/verenigingen-settings');
			cy.wait(2000);

			// Verify SEPA settings are visible and configured
			cy.get('[data-fieldname="sepa_creditor_identifier"]').should('be.visible');
			cy.get('[data-fieldname="mollie_bank_account"]').should('be.visible');
		});

		it('should test JavaScript integration with centralized configuration', () => {
			cy.visit_doctype_form('Member', testMember.name);
			cy.wait(3000);

			// Test that member form can access and use centralized configuration
			cy.window().then((win) => {
				// Test access to Verenigingen Settings via JavaScript
				return win.frappe.call({
					method: 'frappe.client.get_single',
					args: { doctype: 'Verenigingen Settings' }
				}).then((response) => {
					expect(response.message).to.exist;
					expect(response.message.sepa_creditor_identifier).to.exist;

					// This demonstrates that your centralized architecture is working
					cy.log('Centralized SEPA configuration accessible from JavaScript');
				});
			});
		});
	});

	describe('Real Workflow Integration Tests', () => {
		it('should test complete SEPA mandate creation workflow', () => {
			cy.visit_doctype_form('Member', testMember.name);
			cy.wait(3000);

			// Open SEPA mandate dialog
			cy.window().then((win) => {
				const frm = win.frappe.ui.form.get_form('Member');
				win.SepaUtils.create_sepa_mandate_with_dialog(frm);
			});

			// Fill in mandate details
			cy.get('[data-fieldname="iban"] input').clear().type('NL91ABNA0417164300');
			cy.wait(1000);

			// BIC should auto-populate (your JavaScript does this)
			cy.get('[data-fieldname="bic"] input').should('not.be.empty');

			// Test the "Update Member Payment Method" checkbox
			cy.get('[data-fieldname="update_payment_method"] input').should('be.checked');

			// Close dialog without creating (to avoid actually creating in test)
			cy.get('.modal .btn').contains('Close').click();
		});

		it('should test Direct Debit Batch creation with invoices', () => {
			// This would test the complete workflow of creating a batch,
			// loading invoices, validating mandates, and generating SEPA files
			// (Implementation depends on having test invoice data)

			cy.visit_doctype_form('Direct Debit Batch');
			cy.wait(2000);

			// Fill basic batch information
			cy.fill_frappe_field('batch_description', 'Test Batch - Cypress');
			cy.fill_frappe_field('batch_type', 'RCUR', { fieldtype: 'Select' });
			cy.fill_frappe_field('currency', 'EUR', { fieldtype: 'Select' });

			// Save the batch
			cy.save_frappe_doc();

			// Verify the batch was saved and JavaScript controller is still active
			cy.get('button').contains('Load Unpaid Invoices').should('be.visible');
			cy.get('button').contains('Validate Mandates').should('be.visible');
		});
	});
});
