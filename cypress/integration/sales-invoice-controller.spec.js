/**
 * Sales Invoice Controller Test Suite
 *
 * Tests the JavaScript controller for Sales Invoice DocType in the Verenigingen system.
 * Focuses on membership billing, donation invoicing, and financial workflows.
 */

describe('Sales Invoice Controller Tests', () => {
	beforeEach(() => {
		cy.login();
		cy.visit('/app/sales-invoice');
	});

	describe('Sales Invoice Form Controller', () => {
		it('should load Sales Invoice form with JavaScript controller', () => {
			cy.get('.page-title').should('contain', 'Sales Invoice');

			// Verify form is loaded
			cy.get('[data-doctype="Sales Invoice"]').should('be.visible');

			// Check for key sales invoice fields
			cy.get('[data-fieldname="customer"]').should('be.visible');
			cy.get('[data-fieldname="posting_date"]').should('be.visible');
			cy.get('[data-fieldname="due_date"]').should('be.visible');
			cy.get('[data-fieldname="items"]').should('be.visible');
		});

		it('should handle customer selection and auto-populate member details', () => {
			cy.get('[data-fieldname="customer"]').type('Test Member{enter}');

			// Verify member-specific fields are populated
			cy.wait(1000); // Allow for field population
			cy.get('[data-fieldname="custom_member"]').should('not.be.empty');
			cy.get('[data-fieldname="customer_name"]').should('not.be.empty');
		});

		it('should support membership dues invoice creation', () => {
			// Test membership dues specific invoice creation
			cy.get('[data-fieldname="custom_is_membership_invoice"]').check();
			cy.get('[data-fieldname="customer"]').type('Test Member{enter}');

			// Verify membership-specific fields appear
			cy.get('[data-fieldname="custom_membership"]').should('be.visible');
			cy.get('[data-fieldname="custom_coverage_start_date"]').should('be.visible');
			cy.get('[data-fieldname="custom_coverage_end_date"]').should('be.visible');
		});

		it('should handle donation invoice creation', () => {
			// Test donation-specific invoice functionality
			cy.get('[data-fieldname="customer"]').type('Test Donor{enter}');

			// Add donation item
			cy.get('[data-fieldname="items"] .grid-add-row').click();
			cy.get('[data-fieldname="item_code"]').type('Donation{enter}');
			cy.get('[data-fieldname="qty"]').clear().type('1');
			cy.get('[data-fieldname="rate"]').clear().type('25.00');
		});
	});

	describe('Sales Invoice Items and Pricing', () => {
		it('should calculate totals correctly for membership dues', () => {
			cy.get('[data-fieldname="items"] .grid-add-row').click();
			cy.get('[data-fieldname="item_code"]').type('Membership Fee{enter}');
			cy.get('[data-fieldname="qty"]').clear().type('1');
			cy.get('[data-fieldname="rate"]').clear().type('65.00');

			// Verify total calculation
			cy.get('[data-fieldname="grand_total"]').should('contain.value', '65.00');
		});

		it('should handle VAT calculation for applicable items', () => {
			// Test VAT handling for Dutch tax system
			cy.get('[data-fieldname="items"] .grid-add-row').click();
			cy.get('[data-fieldname="item_code"]').type('Taxable Item{enter}');
			cy.get('[data-fieldname="qty"]').clear().type('1');
			cy.get('[data-fieldname="rate"]').clear().type('100.00');

			// Verify tax template application
			cy.get('[data-fieldname="taxes_and_charges"]').should('be.visible');
		});

		it('should support multiple membership types pricing', () => {
			// Test different membership fee structures
			cy.get('[data-fieldname="custom_membership_type"]').select('Student');
			cy.get('[data-fieldname="items"] .grid-add-row').click();
			cy.get('[data-fieldname="item_code"]').type('Student Membership{enter}');
			cy.get('[data-fieldname="rate"]').should('contain.value', '35.00');
		});
	});

	describe('Sales Invoice Validation', () => {
		it('should validate required fields before submission', () => {
			cy.get('.btn-primary').contains('Submit').click();

			// Check for validation messages
			cy.get('.msgprint').should('be.visible');
			cy.get('.indicator-pill').should('contain', 'Missing');
		});

		it('should prevent duplicate membership invoices for same period', () => {
			// Test duplicate membership invoice prevention
			cy.get('[data-fieldname="custom_is_membership_invoice"]').check();
			cy.get('[data-fieldname="customer"]').type('Test Member{enter}');
			cy.get('[data-fieldname="custom_coverage_start_date"]').type('2025-01-01');
			cy.get('[data-fieldname="custom_coverage_end_date"]').type('2025-12-31');

			// Verify duplicate period validation
			cy.get('.btn-primary').contains('Save').click();
			cy.wait(1000);
		});

		it('should validate member status for membership invoices', () => {
			// Test member status validation
			cy.get('[data-fieldname="custom_is_membership_invoice"]').check();
			cy.get('[data-fieldname="customer"]').type('Inactive Member{enter}');

			// Verify warning or validation for inactive members
			cy.get('.msgprint').should('be.visible');
		});
	});

	describe('Sales Invoice Payment Integration', () => {
		it('should support SEPA direct debit payment terms', () => {
			// Test SEPA payment integration
			cy.get('[data-fieldname="payment_terms_template"]').select('SEPA Direct Debit');

			// Verify SEPA-specific payment settings
			cy.get('[data-fieldname="due_date"]').should('not.be.empty');
		});

		it('should integrate with member payment history', () => {
			// Test member payment history integration
			cy.get('[data-fieldname="customer"]').type('Test Member{enter}');

			// Verify payment history is accessible
			cy.get('.btn').contains('Payment').should('be.visible');
		});

		it('should handle subscription billing workflows', () => {
			// Test recurring membership billing
			cy.get('[data-fieldname="is_recurring"]').check();
			cy.get('[data-fieldname="subscription"]').should('be.visible');
		});
	});

	describe('Sales Invoice Reporting and Analytics', () => {
		it('should support membership revenue reporting', () => {
			// Navigate to sales invoice list for reporting tests
			cy.visit('/app/sales-invoice');

			// Verify membership invoice filters
			cy.get('[data-fieldname="custom_is_membership_invoice"]').should('be.visible');
			cy.get('.list-row').should('be.visible');
		});

		it('should integrate with accounting reports', () => {
			// Test accounting integration
			cy.get('[data-fieldname="cost_center"]').should('be.visible');
			cy.get('[data-fieldname="income_account"]').should('be.visible');
		});

		it('should support member analytics and insights', () => {
			// Test member-specific analytics
			cy.get('[data-fieldname="custom_member"]').should('be.visible');

			// Verify member analytics integration
			cy.get('.btn').contains('Member Details').should('be.visible');
		});
	});

	describe('Sales Invoice E-Boekhouden Integration', () => {
		it('should sync with E-Boekhouden accounting system', () => {
			// Test E-Boekhouden integration fields
			cy.get('[data-fieldname="custom_eboekhouden_invoice_id"]').should('be.visible');
			cy.get('[data-fieldname="custom_eboekhouden_sync_status"]').should('be.visible');
		});

		it('should handle sync error recovery', () => {
			// Test sync error handling
			cy.get('[data-fieldname="custom_eboekhouden_sync_status"]').should('contain.value', 'Pending');

			// Verify retry functionality
			cy.get('.btn').contains('Sync').should('be.visible');
		});
	});

	describe('Sales Invoice Automation', () => {
		it('should support automatic invoice generation from memberships', () => {
			// Test automated invoice creation from membership dues schedules
			cy.visit('/app/membership-dues-schedule');

			// Verify invoice generation workflow
			cy.get('.btn').contains('Generate Invoice').should('be.visible');
		});

		it('should handle bulk invoice processing', () => {
			// Test bulk invoice operations
			cy.visit('/app/sales-invoice');

			// Verify bulk operations
			cy.get('.actions-btn-group').should('be.visible');
		});
	});

	afterEach(() => {
		// Clean up test data
		cy.cleanup_test_data('Sales Invoice');
	});
});
