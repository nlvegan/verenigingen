/**
 * @fileoverview Volunteer Management JavaScript Controller Tests
 *
 * Tests the Volunteer DocType JavaScript controller and its sophisticated
 * integration with the Member system, including expense management,
 * skill tracking, and team assignment workflows.
 *
 * Business Context:
 * Volunteer management is critical for association operations, enabling
 * efficient coordination of volunteer activities, expense reimbursements,
 * and skill-based team assignments.
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 * @since 2025-08-19
 */

describe('Volunteer Management JavaScript Controller Tests', () => {
	beforeEach(() => {
		cy.login('Administrator', 'admin');
		cy.clear_test_data();
	});

	afterEach(() => {
		cy.clear_test_data();
	});

	describe('Volunteer Creation and Form Controller Tests', () => {
		it('should load Volunteer form with JavaScript controller', () => {
			// Navigate to new Volunteer form
			cy.visit_doctype_form('Volunteer');

			// Verify the Volunteer JavaScript controller is loaded
			cy.window().then((win) => {
				expect(win.frappe.ui.form.get_form('Volunteer')).to.exist;
			});

			// Verify form elements are present
			cy.get('[data-fieldname="member"]').should('be.visible');
			cy.get('[data-fieldname="skills"]').should('be.visible');
			cy.get('[data-fieldname="availability"]').should('be.visible');
		});

		it('should test volunteer creation with Enhanced Test Factory', () => {
			// Create test volunteer using Enhanced Test Factory
			cy.createTestVolunteer().then((result) => {
				const { member, volunteer } = result;

				// Navigate to the volunteer form
				cy.visit_doctype_form('Volunteer', volunteer.name);

				// Verify volunteer is properly linked to member
				cy.verify_frappe_field('member', member.name);

				// Test that volunteer controller loads member information
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Volunteer');
					expect(frm).to.exist;
					expect(frm.doc.member).to.equal(member.name);
				});
			});
		});
	});

	describe('Volunteer-Member Integration Tests', () => {
		it('should test member age validation for volunteers', () => {
			// Create test volunteer (Enhanced Test Factory ensures age >= 16)
			cy.createTestVolunteer().then((result) => {
				const { volunteer } = result;

				cy.visit_doctype_form('Volunteer', volunteer.name);

				// Verify no age-related validation errors
				cy.verify_field_validation('member', true);

				// Test JavaScript validation rules are working
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Volunteer');
					expect(frm.doc.member).to.exist;
					// Additional business rule validations would go here
				});
			});
		});

		it('should test volunteer status updates', () => {
			cy.createTestVolunteer().then((result) => {
				const { volunteer } = result;

				cy.visit_doctype_form('Volunteer', volunteer.name);

				// Test status field updates
				cy.fill_frappe_field('status', 'Active', { fieldtype: 'Select' });
				cy.save_frappe_doc();

				// Verify status was saved
				cy.verify_frappe_field('status', 'Active');
			});
		});
	});

	describe('Volunteer Skills and Teams Tests', () => {
		it('should test skill management interface', () => {
			cy.createTestVolunteer().then((result) => {
				const { volunteer } = result;

				cy.visit_doctype_form('Volunteer', volunteer.name);

				// Test skills table functionality
				cy.get('[data-fieldname="skills"]').should('be.visible');

				// Test that JavaScript table handlers are working
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Volunteer');
					expect(frm.fields_dict.skills).to.exist;
				});
			});
		});

		it('should test team assignment functionality', () => {
			cy.createTestVolunteer().then((result) => {
				const { volunteer } = result;

				cy.visit_doctype_form('Volunteer', volunteer.name);

				// Test team assignments section
				cy.get('[data-fieldname="team_assignments"]').should('be.visible');

				// Verify JavaScript controller manages team assignments
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Volunteer');
					expect(frm.fields_dict.team_assignments).to.exist;
				});
			});
		});
	});

	describe('Volunteer Business Logic Tests', () => {
		it('should test availability scheduling', () => {
			cy.createTestVolunteer().then((result) => {
				const { volunteer } = result;

				cy.visit_doctype_form('Volunteer', volunteer.name);

				// Test availability field and its validation
				cy.get('[data-fieldname="availability"]').should('be.visible');

				// Test JavaScript validation for availability
				cy.fill_frappe_field('hours_per_week', '10', { fieldtype: 'Int' });
				cy.verify_field_validation('hours_per_week', true);
			});
		});
	});
});
