/**
 * @fileoverview Member Lifecycle Management E2E Tests
 *
 * This comprehensive test suite validates the complete member lifecycle workflow
 * using real Frappe DocType forms and actual business data. Tests the JavaScript
 * DocType controllers in their real runtime environment without mocking.
 *
 * Business Context:
 * Member lifecycle management is the core workflow of the association management
 * system. This includes member creation, profile updates, chapter assignments,
 * SEPA mandate setup, and volunteer coordination. These workflows must function
 * flawlessly as they represent the primary user interactions.
 *
 * Test Strategy:
 * - Use real Frappe forms and DocType JavaScript controllers
 * - Test with realistic Dutch member data and scenarios
 * - Validate actual UI interactions and form behaviors
 * - Test JavaScript form events and business logic
 * - No mocking - test against actual running system
 *
 * Prerequisites:
 * - Development server running on dev.veganisme.net:8000
 * - Test user account with appropriate permissions
 * - Sample chapters and membership types configured
 *
 * @author Verenigingen Test Team
 * @version 1.0.0
 * @since 2025-08-19
 */

describe('Member Lifecycle Management - Real Business Workflows', () => {
	beforeEach(() => {
		// Login as admin user for member management tests
		const user = Cypress.env('ADMIN_USER');
		const pass = Cypress.env('ADMIN_PASSWORD');
		expect(user, 'ADMIN_USER env var').to.be.a('string').and.not.be.empty;
		expect(pass, 'ADMIN_PASSWORD env var').to.be.a('string').and.not.be.empty;
		cy.login(user, pass);

		// Clear any existing test data
		cy.clear_test_data();
	});

	describe('Member Creation Workflow - JavaScript Controller Tests', () => {
		it('should test member list view and form navigation', () => {
			// Navigate to Member DocType list using enhanced command
			cy.visit_doctype_list('Member');

			// Test creating a new member form
			cy.get('button').contains('Add').click();
			cy.wait_for_navigation();

			// Verify the Member JavaScript controller is loaded
			cy.window().then((win) => {
				expect(win.frappe.ui.form.get_form('Member')).to.exist;
			});
		});

		it('should test member form with Enhanced Test Factory data', () => {
			// Create test member with financial setup using Enhanced Test Factory
			cy.createTestMemberWithFinancialSetup().then((member) => {
				// Navigate to the member form using enhanced command
				cy.visit_doctype_form('Member', member.name);

				// Verify the Member form loads with the JavaScript controller
				cy.window().then((win) => {
					expect(win.frappe.ui.form.get_form('Member')).to.exist;
				});

				// Test that member fields are properly populated using enhanced verify command
				cy.verify_frappe_field('first_name', member.first_name);
				cy.verify_frappe_field('last_name', member.last_name);
				cy.verify_frappe_field('email', member.email);

				// Test that the member has financial setup (IBAN, customer, etc.)
				if (member.iban) {
					cy.verify_frappe_field('iban', member.iban);
				}
				if (member.customer) {
					cy.verify_frappe_field('customer', member.customer);
				}
			});
		});

		it('should test member form JavaScript validation', () => {
			// Create test member first
			cy.createTestMemberWithFinancialSetup().then((member) => {
				cy.visit_doctype_form('Member', member.name);
				cy.wait_for_navigation();

				// Test email validation
				cy.test_form_validation('email', 'invalid-email', 'valid@test.nl');

				// Test IBAN validation if IBANValidator is available
				if (member.iban) {
					cy.test_form_validation('iban', 'INVALID123', 'NL91ABNA0417164300');
				}
			});
		});

		it('should test member form with chapter assignment', () => {
			// Create test member with chapter using Enhanced Test Factory
			cy.createTestMemberWithChapter().then((member) => {
				cy.visit_doctype_form('Member', member.name);
				cy.wait_for_navigation();

				// Verify member has chapter assignment
				// (This would depend on how your Enhanced Test Factory creates chapters)
				cy.get('[data-fieldname="chapters"]').should('be.visible');
			});
		});
	});

	afterEach(() => {
		// Clean up test data after each test
		cy.clear_test_data();
	});
});
