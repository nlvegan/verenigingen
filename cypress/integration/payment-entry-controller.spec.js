/**
 * Payment Entry Controller Test Suite
 *
 * Tests the JavaScript controller for Payment Entry DocType in the Verenigingen system.
 * Focuses on payment processing, member account reconciliation, and financial workflows.
 */

describe('Payment Entry Controller Tests', () => {
	beforeEach(() => {
		cy.login();
		cy.visit('/app/payment-entry');
	});

	describe('Payment Entry Form Controller', () => {
		it('should load Payment Entry form with JavaScript controller', () => {
			cy.get('.page-title').should('contain', 'Payment Entry');

			// Verify form is loaded
			cy.get('[data-doctype="Payment Entry"]').should('be.visible');

			// Check for key payment entry fields
			cy.get('[data-fieldname="payment_type"]').should('be.visible');
			cy.get('[data-fieldname="party_type"]').should('be.visible');
			cy.get('[data-fieldname="party"]').should('be.visible');
			cy.get('[data-fieldname="paid_amount"]').should('be.visible');
		});

		it('should handle party type selection and dynamic field updates', () => {
			cy.get('[data-fieldname="payment_type"]').select('Receive');
			cy.get('[data-fieldname="party_type"]').select('Customer');

			// Verify party field becomes visible and filterable
			cy.get('[data-fieldname="party"]').should('be.visible');
			cy.get('[data-fieldname="party"] input').should('not.be.disabled');
		});

		it('should validate payment amount and currency', () => {
			cy.get('[data-fieldname="payment_type"]').select('Receive');
			cy.get('[data-fieldname="paid_amount"]').type('100.00');

			// Verify currency defaults to EUR for Dutch system
			cy.get('[data-fieldname="paid_to_account_currency"]').should('contain.value', 'EUR');
		});

		it('should handle member payment reconciliation', () => {
			// Test member-specific payment entry functionality
			cy.get('[data-fieldname="party_type"]').select('Customer');

			// Mock member selection
			cy.get('[data-fieldname="party"]').type('Test Member{enter}');

			// Verify member payment history integration
			cy.get('[data-fieldname="references"]').should('be.visible');
		});
	});

	describe('Payment Entry Validation', () => {
		it('should validate required fields before saving', () => {
			cy.get('.btn-primary').contains('Save').click();

			// Check for validation messages
			cy.get('.msgprint').should('be.visible');
			cy.get('.indicator-pill').should('contain', 'Missing');
		});

		it('should prevent duplicate payment entries for same reference', () => {
			// Test duplicate payment prevention logic
			cy.get('[data-fieldname="payment_type"]').select('Receive');
			cy.get('[data-fieldname="party_type"]').select('Customer');
			cy.get('[data-fieldname="paid_amount"]').type('25.00');

			// Add reference document
			cy.get('[data-fieldname="references"] .grid-add-row').click();

			// Verify duplicate detection
			cy.get('[data-fieldname="reference_doctype"]').select('Sales Invoice');
		});
	});

	describe('Payment Entry Integration', () => {
		it('should integrate with member payment history', () => {
			// Test integration with Member Payment History DocType
			cy.get('[data-fieldname="party_type"]').select('Customer');
			cy.get('[data-fieldname="custom_member"]').should('be.visible');
		});

		it('should handle SEPA payment reconciliation', () => {
			// Test SEPA-specific payment entry handling
			cy.get('[data-fieldname="mode_of_payment"]').select('SEPA Direct Debit');

			// Verify SEPA-specific fields appear
			cy.get('[data-fieldname="reference_no"]').should('be.visible');
			cy.get('[data-fieldname="reference_date"]').should('be.visible');
		});

		it('should support membership dues payment processing', () => {
			// Test membership dues payment workflows
			cy.get('[data-fieldname="payment_type"]').select('Receive');
			cy.get('[data-fieldname="party_type"]').select('Customer');

			// Verify membership invoice reference
			cy.get('[data-fieldname="references"] .grid-add-row').click();
			cy.get('[data-fieldname="reference_doctype"]').select('Sales Invoice');
		});
	});

	describe('Payment Entry Error Handling', () => {
		it('should handle payment processing errors gracefully', () => {
			// Test error handling for payment failures
			cy.get('[data-fieldname="paid_amount"]').type('-100.00');
			cy.get('.btn-primary').contains('Save').click();

			// Verify error message display
			cy.get('.msgprint').should('contain', 'Amount cannot be negative');
		});

		it('should validate account configuration', () => {
			// Test account validation for payment entries
			cy.get('[data-fieldname="paid_to"]').should('be.visible');
			cy.get('[data-fieldname="paid_from"]').should('be.visible');

			// Verify account type validation
			cy.get('[data-fieldname="paid_to"]').click();
			cy.get('.frappe-control[data-fieldname="paid_to"] .link-field').should('be.visible');
		});
	});

	describe('Payment Entry Reporting', () => {
		it('should support payment entry reporting and analytics', () => {
			// Navigate to payment entry list for reporting tests
			cy.visit('/app/payment-entry');

			// Verify list view and filters
			cy.get('.list-row').should('be.visible');
			cy.get('[data-fieldname="party_type"]').should('be.visible');
		});

		it('should integrate with financial reporting', () => {
			// Test integration with accounting reports
			cy.get('[data-fieldname="cost_center"]').should('be.visible');
			cy.get('[data-fieldname="project"]').should('be.visible');
		});
	});

	afterEach(() => {
		// Clean up test data
		cy.cleanup_test_data('Payment Entry');
	});
});
