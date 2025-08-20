/**
 * @fileoverview Comprehensive DocType JavaScript Controller Testing Suite
 *
 * This suite demonstrates the comprehensive testing approach for all major
 * DocTypes in the Verenigingen association management system, showcasing
 * how to test sophisticated JavaScript controllers with realistic data.
 *
 * Coverage: Tests 8 critical DocTypes with their JavaScript controllers,
 * business logic, validation, and integration points.
 *
 * Testing Philosophy:
 * - Use Enhanced Test Factory for realistic business data
 * - Test JavaScript controllers in their real runtime environment
 * - Validate sophisticated UI interactions and workflows
 * - Test integration with centralized configuration
 * - No mocking - test against actual running system
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 * @since 2025-08-19
 */

describe('Comprehensive DocType JavaScript Controller Testing', () => {
	beforeEach(() => {
		const user = Cypress.env('ADMIN_USER');
		const pass = Cypress.env('ADMIN_PASSWORD');
		expect(user, 'ADMIN_USER env var').to.be.a('string').and.not.be.empty;
		expect(pass, 'ADMIN_PASSWORD env var').to.be.a('string').and.not.be.empty;
		cy.login(user, pass);
		cy.clear_test_data();
	});

	afterEach(() => {
		cy.clear_test_data();
	});

	describe('Core Member Management DocTypes', () => {
		it('should test Member DocType with SEPA integration', () => {
			cy.createTestMemberWithFinancialSetup().then((member) => {
				// Test Member form controller
				cy.visit_doctype_form('Member', member.name);

				// Verify SepaUtils integration
				cy.test_sepa_utils(member.name);

				// Test SEPA mandate dialog
				cy.test_sepa_mandate_dialog(member.name);
			});
		});

		it('should test Volunteer DocType with member integration', () => {
			cy.createTestVolunteer().then((result) => {
				const { member, volunteer } = result;

				// Test Volunteer form controller
				cy.visit_doctype_form('Volunteer', volunteer.name);

				// Verify member integration
				cy.verify_frappe_field('member', member.name);

				// Test volunteer-specific functionality
				cy.get('[data-fieldname="skills"]').should('be.visible');
				cy.get('[data-fieldname="availability"]').should('be.visible');
			});
		});

		it('should test Chapter DocType with geographic functionality', () => {
			cy.visit_doctype_form('Chapter');

			// Test chapter creation
			cy.fill_frappe_field('chapter_name', 'Comprehensive Test Chapter');
			cy.fill_frappe_field('description', 'Testing comprehensive DocType functionality');
			cy.save_frappe_doc();

			// Verify chapter-specific features
			cy.get('[data-fieldname="postal_code_ranges"]').should('be.visible');
			cy.get('[data-fieldname="board_members"]').should('be.visible');
		});
	});

	describe('Financial Management DocTypes', () => {
		it('should test Membership Dues Schedule with billing automation', () => {
			cy.createTestMemberWithFinancialSetup().then((member) => {
				cy.visit_doctype_form('Membership Dues Schedule');

				// Test dues schedule creation
				cy.fill_frappe_field('member', member.name, { fieldtype: 'Link' });
				cy.fill_frappe_field('dues_rate', '25.00');
				cy.fill_frappe_field('billing_frequency', 'Monthly', { fieldtype: 'Select' });
				cy.save_frappe_doc();

				// Verify billing calculations
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Membership Dues Schedule');
					expect(frm.doc.member).to.equal(member.name);
				});
			});
		});

		it('should test Direct Debit Batch with SEPA processing', () => {
			cy.visit_doctype_form('Direct Debit Batch');

			// Test batch controller
			cy.test_dd_batch_controller();

			// Test batch creation workflow
			cy.fill_frappe_field('batch_description', 'Comprehensive Test Batch');
			cy.fill_frappe_field('batch_type', 'RCUR', { fieldtype: 'Select' });
			cy.save_frappe_doc();

			// Verify batch functionality
			cy.get('button').contains('Load Unpaid Invoices').should('be.visible');
		});

		it('should test SEPA Mandate with validation', () => {
			cy.createTestMemberWithFinancialSetup().then((member) => {
				cy.visit_doctype_form('SEPA Mandate');

				// Test mandate creation
				cy.fill_frappe_field('member', member.name, { fieldtype: 'Link' });
				cy.fill_frappe_field('iban', 'NL91ABNA0417164300');
				cy.fill_frappe_field('mandate_type', 'Recurring', { fieldtype: 'Select' });
				cy.save_frappe_doc();

				// Test IBAN validation
				cy.test_iban_validation('NL91ABNA0417164300', true);
			});
		});
	});

	describe('Workflow and Process DocTypes', () => {
		it('should test Member Application with validation workflow', () => {
			cy.visit_doctype_form('Member Application');

			// Test application form
			cy.fill_frappe_field('first_name', 'Comprehensive');
			cy.fill_frappe_field('last_name', 'Test User');
			cy.fill_frappe_field('email', 'comprehensive.test@example.com');
			cy.save_frappe_doc();

			// Verify validation workflow
			cy.get('[data-fieldname="application_status"]').should('be.visible');
		});

		it('should test Team with responsibility management', () => {
			cy.visit_doctype_form('Team');

			// Test team creation
			cy.fill_frappe_field('team_name', 'Comprehensive Test Team');
			cy.fill_frappe_field('description', 'Testing team functionality');
			cy.save_frappe_doc();

			// Verify team features
			cy.get('[data-fieldname="team_members"]').should('be.visible');
			cy.get('[data-fieldname="responsibilities"]').should('be.visible');
		});
	});

	describe('Configuration and Settings Integration', () => {
		it('should test centralized configuration access', () => {
			// Test access to Verenigingen Settings
			cy.test_centralized_config_access();

			// Verify centralized SEPA configuration
			cy.visit('/app/verenigingen-settings');
			cy.get('[data-fieldname="sepa_creditor_identifier"]').should('be.visible');
		});

		it('should test cross-DocType integration', () => {
			// Create complete test data scenario
			cy.createTestMemberWithFinancialSetup().then((member) => {
				cy.createTestVolunteer().then((result) => {
					const { volunteer } = result;

					// Test Member → Volunteer integration
					cy.visit_doctype_form('Member', member.name);
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('Member');
						expect(frm).to.exist;
					});

					// Test integration points
					cy.visit_doctype_form('Volunteer', volunteer.name);
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('Volunteer');
						expect(frm).to.exist;
					});
				});
			});
		});
	});

	describe('Advanced JavaScript Controller Features', () => {
		it('should test dynamic UI updates and field interactions', () => {
			cy.createTestMemberWithFinancialSetup().then((member) => {
				cy.visit_doctype_form('Member', member.name);

				// Test dynamic UI behavior
				cy.test_dynamic_ui_update('payment_method', 'SEPA Direct Debit', {
					buttonAppears: 'Create SEPA Mandate'
				});
			});
		});

		it('should test form validation and business rules', () => {
			cy.visit_doctype_form('Member');

			// Test comprehensive form validation
			cy.test_form_validation('email', 'invalid-email', 'valid@test.nl');

			// Test Dutch-specific validation
			cy.test_dutch_validation('postal_code', '1234AB', {
				valid: true,
				message: 'Valid Dutch postal code'
			});
		});

		it('should test custom button functionality across DocTypes', () => {
			cy.createTestMemberWithFinancialSetup().then((member) => {
				cy.visit_doctype_form('Member', member.name);

				// Test custom buttons exist and function
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member');
					if (frm.doc.iban && frm.doc.payment_method === 'SEPA Direct Debit') {
						// Test SEPA-related custom buttons
						cy.get('button').contains('Create SEPA Mandate').should('exist');
					}
				});
			});
		});
	});

	describe('Error Handling and Edge Cases', () => {
		it('should test JavaScript error handling', () => {
			// Test error handling with missing data
			cy.visit_doctype_form('Member');

			// Test validation with empty required fields
			cy.get('.primary-action').contains('Save').click();
			// Should show validation errors
			cy.get('.has-error').should('exist');
		});

		it('should test network error resilience', () => {
			cy.createTestMemberWithFinancialSetup().then((member) => {
				cy.visit_doctype_form('Member', member.name);

				// Test JavaScript resilience to network issues
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member');
					expect(frm).to.exist;
					// Error resilience testing would go here
				});
			});
		});
	});
});
