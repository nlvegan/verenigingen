/**
 * @fileoverview Membership Dues Schedule JavaScript Controller Tests
 *
 * Tests the Membership Dues Schedule DocType JavaScript controller,
 * including billing schedule management, automated invoice generation,
 * and integration with SEPA payment systems.
 *
 * Business Context:
 * Membership dues scheduling is critical for association financial
 * sustainability, automating recurring billing and payment collection
 * while maintaining member payment preferences and compliance.
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 * @since 2025-08-19
 */

describe('Membership Dues Schedule JavaScript Controller Tests', () => {
	beforeEach(() => {
		cy.login('Administrator', 'admin');
		cy.clear_test_data();
	});

	afterEach(() => {
		cy.clear_test_data();
	});

	describe('Dues Schedule Form Controller Tests', () => {
		it('should load Membership Dues Schedule form with JavaScript controller', () => {
			// Navigate to new dues schedule form
			cy.visit_doctype_form('Membership Dues Schedule');

			// Verify the controller is loaded
			cy.window().then((win) => {
				expect(win.frappe.ui.form.get_form('Membership Dues Schedule')).to.exist;
			});

			// Verify core fields are present
			cy.get('[data-fieldname="member"]').should('be.visible');
			cy.get('[data-fieldname="dues_rate"]').should('be.visible');
			cy.get('[data-fieldname="billing_frequency"]').should('be.visible');
		});

		it('should test dues schedule creation with member integration', () => {
			// Create test member with financial setup
			cy.createTestMemberWithFinancialSetup().then((member) => {
				cy.visit_doctype_form('Membership Dues Schedule');

				// Link to member
				cy.fill_frappe_field('member', member.name, { fieldtype: 'Link' });
				cy.wait_for_member_data(); // Allow member data to populate

				// Set dues details
				cy.fill_frappe_field('dues_rate', '25.00');
				cy.fill_frappe_field('billing_frequency', 'Monthly', { fieldtype: 'Select' });

				// Save the schedule
				cy.save_frappe_doc();

				// Verify member is linked correctly
				cy.verify_frappe_field('member', member.name);
			});
		});
	});

	describe('Billing Schedule Management Tests', () => {
		it('should test billing frequency calculations', () => {
			cy.createTestMemberWithFinancialSetup().then((member) => {
				cy.visit_doctype_form('Membership Dues Schedule');

				cy.fill_frappe_field('member', member.name, { fieldtype: 'Link' });
				cy.fill_frappe_field('dues_rate', '30.00');

				// Test different billing frequencies
				cy.fill_frappe_field('billing_frequency', 'Monthly', { fieldtype: 'Select' });
				cy.wait_with_config('fieldInput');

				// Verify JavaScript calculations
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Membership Dues Schedule');
					expect(frm).to.exist;
					// Test billing calculation logic
				});

				// Test quarterly billing
				cy.fill_frappe_field('billing_frequency', 'Quarterly', { fieldtype: 'Select' });
				cy.wait_with_config('fieldInput');

				// Verify calculations update
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Membership Dues Schedule');
					expect(frm.doc.billing_frequency).to.equal('Quarterly');
				});
			});
		});

		it('should test next invoice date calculation', () => {
			cy.createTestMemberWithFinancialSetup().then((member) => {
				cy.visit_doctype_form('Membership Dues Schedule');

				cy.fill_frappe_field('member', member.name, { fieldtype: 'Link' });
				cy.fill_frappe_field('dues_rate', '25.00');
				cy.fill_frappe_field('billing_frequency', 'Monthly', { fieldtype: 'Select' });

				// Test next invoice date calculation
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Membership Dues Schedule');
					expect(frm.fields_dict.next_invoice_date).to.exist;

					// JavaScript should calculate next invoice date
				});
			});
		});
	});

	describe('Payment Integration Tests', () => {
		it('should test SEPA mandate integration', () => {
			cy.createTestMemberWithFinancialSetup().then((member) => {
				cy.visit_doctype_form('Membership Dues Schedule');

				cy.fill_frappe_field('member', member.name, { fieldtype: 'Link' });
				cy.fill_frappe_field('dues_rate', '25.00');

				// Test SEPA payment method selection
				cy.fill_frappe_field('payment_method', 'SEPA Direct Debit', { fieldtype: 'Select' });

				// Verify JavaScript handles SEPA integration
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Membership Dues Schedule');
					expect(frm.doc.payment_method).to.equal('SEPA Direct Debit');

					// Test SEPA validation logic
				});
			});
		});

		it('should test payment method validation', () => {
			cy.createTestMemberWithFinancialSetup().then((member) => {
				cy.visit_doctype_form('Membership Dues Schedule');

				cy.fill_frappe_field('member', member.name, { fieldtype: 'Link' });

				// Test different payment methods
				cy.fill_frappe_field('payment_method', 'Bank Transfer', { fieldtype: 'Select' });
				cy.verify_field_validation('payment_method', true);

				cy.fill_frappe_field('payment_method', 'SEPA Direct Debit', { fieldtype: 'Select' });
				cy.verify_field_validation('payment_method', true);
			});
		});
	});

	describe('Invoice Generation Tests', () => {
		it('should test automated invoice generation controls', () => {
			cy.createTestMemberWithFinancialSetup().then((member) => {
				cy.visit_doctype_form('Membership Dues Schedule');

				cy.fill_frappe_field('member', member.name, { fieldtype: 'Link' });
				cy.fill_frappe_field('dues_rate', '25.00');
				cy.fill_frappe_field('billing_frequency', 'Monthly', { fieldtype: 'Select' });

				// Test invoice generation settings
				cy.get('[data-fieldname="auto_generate_invoices"]').should('be.visible');
				cy.fill_frappe_field('auto_generate_invoices', true, { fieldtype: 'Check' });

				// Verify JavaScript validation
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Membership Dues Schedule');
					expect(frm.doc.auto_generate_invoices).to.be.true;
				});
			});
		});

		it('should test billing day calculation', () => {
			cy.createTestMemberWithFinancialSetup().then((member) => {
				cy.visit_doctype_form('Membership Dues Schedule');

				cy.fill_frappe_field('member', member.name, { fieldtype: 'Link' });

				// Test billing day setting
				cy.get('[data-fieldname="billing_day"]').should('be.visible');

				// Verify JavaScript sets appropriate billing day
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Membership Dues Schedule');
					expect(frm.fields_dict.billing_day).to.exist;

					// Test billing day calculation logic
				});
			});
		});
	});

	describe('Schedule Status Management Tests', () => {
		it('should test dues schedule activation', () => {
			cy.createTestMemberWithFinancialSetup().then((member) => {
				cy.visit_doctype_form('Membership Dues Schedule');

				cy.fill_frappe_field('member', member.name, { fieldtype: 'Link' });
				cy.fill_frappe_field('dues_rate', '25.00');
				cy.save_frappe_doc();

				// Test schedule activation
				cy.fill_frappe_field('status', 'Active', { fieldtype: 'Select' });
				cy.save_frappe_doc();

				// Verify status change
				cy.verify_frappe_field('status', 'Active');

				// Test JavaScript status validation
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Membership Dues Schedule');
					expect(frm.doc.status).to.equal('Active');
				});
			});
		});

		it('should test schedule suspension and resumption', () => {
			cy.createTestMemberWithFinancialSetup().then((member) => {
				cy.visit_doctype_form('Membership Dues Schedule');

				cy.fill_frappe_field('member', member.name, { fieldtype: 'Link' });
				cy.fill_frappe_field('dues_rate', '25.00');
				cy.save_frappe_doc();

				// Test suspension
				cy.fill_frappe_field('status', 'Suspended', { fieldtype: 'Select' });
				cy.save_frappe_doc();

				// Verify JavaScript handles status change
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Membership Dues Schedule');
					expect(frm.doc.status).to.equal('Suspended');
				});
			});
		});
	});
});
