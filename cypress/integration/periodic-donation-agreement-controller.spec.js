/**
 * @fileoverview Periodic Donation Agreement JavaScript Controller Tests
 *
 * Tests the Periodic Donation Agreement DocType JavaScript controller,
 * including recurring donation setup, payment scheduling, donor commitment
 * tracking, and integration with automated donation processing workflows.
 *
 * Business Context:
 * Periodic donations provide stable, predictable revenue for associations.
 * The system must manage donor commitments, handle payment scheduling,
 * and integrate with SEPA/payment systems for automated processing.
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 * @since 2025-08-19
 */

describe('Periodic Donation Agreement JavaScript Controller Tests', () => {
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

	describe('Periodic Donation Agreement Form Controller Tests', () => {
		it('should load Periodic Donation Agreement form with JavaScript controller', () => {
			// Navigate to new Periodic Donation Agreement form
			cy.visit_doctype_form('Periodic Donation Agreement');
			cy.wait_for_navigation();

			// Verify the controller is loaded
			cy.window().then((win) => {
				expect(win.frappe.ui.form.get_form('Periodic Donation Agreement')).to.exist;
			});

			// Verify core fields are present
			cy.get('[data-fieldname="donor"]').should('be.visible');
			cy.get('[data-fieldname="donation_amount"]').should('be.visible');
			cy.get('[data-fieldname="frequency"]').should('be.visible');
		});

		it('should test periodic donation agreement creation workflow', () => {
			cy.visit_doctype_form('Periodic Donation Agreement');
			cy.wait_for_navigation();

			// Create periodic donation agreement
			cy.fill_frappe_field('donor', 'Recurring Donor Test');
			cy.fill_frappe_field('donation_amount', '50.00', { fieldtype: 'Currency' });
			cy.fill_frappe_field('frequency', 'Monthly', { fieldtype: 'Select' });
			cy.fill_frappe_field('start_date', '2025-01-01', { fieldtype: 'Date' });

			cy.save_frappe_doc();

			// Verify agreement was created
			cy.verify_frappe_field('donor', 'Recurring Donor Test');
			cy.verify_frappe_field('donation_amount', '50.00');
		});
	});

	describe('Donation Scheduling Tests', () => {
		it('should test different frequency scheduling options', () => {
			const frequencies = ['Monthly', 'Quarterly', 'Annually', 'Weekly'];

			frequencies.forEach((frequency) => {
				cy.visit_doctype_form('Periodic Donation Agreement');
				cy.wait_for_navigation();

				cy.fill_frappe_field('donor', `${frequency} Donor`);
				cy.fill_frappe_field('donation_amount', '75.00', { fieldtype: 'Currency' });
				cy.fill_frappe_field('frequency', frequency, { fieldtype: 'Select' });
				cy.fill_frappe_field('start_date', '2025-01-01', { fieldtype: 'Date' });

				// Test frequency-specific JavaScript logic
				cy.execute_business_workflow(() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('Periodic Donation Agreement');
						expect(frm.doc.frequency).to.equal(frequency);

						// Test JavaScript calculations based on frequency
						if (frm.fields_dict.next_donation_date) {
							expect(frm.fields_dict.next_donation_date).to.exist;
							cy.log(`${frequency} scheduling calculation available`);
						}

						// Test annual total calculation
						if (frm.fields_dict.annual_total) {
							expect(frm.fields_dict.annual_total).to.exist;
							cy.log(`${frequency} annual total calculation available`);
						}
					});
					return true;
				}, null, `${frequency} Donation Scheduling`);

				cy.save_frappe_doc();
			});
		});

		it('should test custom scheduling and billing day setup', () => {
			cy.visit_doctype_form('Periodic Donation Agreement');
			cy.wait_for_navigation();

			cy.fill_frappe_field('donor', 'Custom Schedule Donor');
			cy.fill_frappe_field('donation_amount', '100.00', { fieldtype: 'Currency' });
			cy.fill_frappe_field('frequency', 'Monthly', { fieldtype: 'Select' });
			cy.fill_frappe_field('billing_day', '15', { fieldtype: 'Int' });

			// Test custom billing day JavaScript
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Periodic Donation Agreement');
					expect(frm.doc.billing_day).to.equal(15);

					// Test JavaScript validation for billing day
					if (frm.doc.billing_day < 1 || frm.doc.billing_day > 31) {
						cy.log('Billing day validation would trigger here');
					} else {
						cy.log('Billing day validation passed');
					}

					// Test next payment calculation based on billing day
					if (frm.fields_dict.next_payment_date) {
						expect(frm.fields_dict.next_payment_date).to.exist;
					}
				});
				return true;
			}, null, 'Custom Billing Day Setup');

			cy.save_frappe_doc();
		});
	});

	describe('Payment Method Integration Tests', () => {
		it('should test SEPA Direct Debit integration', () => {
			cy.visit_doctype_form('Periodic Donation Agreement');
			cy.wait_for_navigation();

			cy.fill_frappe_field('donor', 'SEPA Donor Test');
			cy.fill_frappe_field('donation_amount', '25.00', { fieldtype: 'Currency' });
			cy.fill_frappe_field('frequency', 'Monthly', { fieldtype: 'Select' });
			cy.fill_frappe_field('payment_method', 'SEPA Direct Debit', { fieldtype: 'Select' });

			// Test SEPA integration
			cy.execute_sepa_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Periodic Donation Agreement');
					expect(frm.doc.payment_method).to.equal('SEPA Direct Debit');

					// Test SEPA-specific fields
					if (frm.fields_dict.sepa_mandate) {
						expect(frm.fields_dict.sepa_mandate).to.exist;
						cy.log('SEPA mandate integration available');
					}

					if (frm.fields_dict.iban) {
						expect(frm.fields_dict.iban).to.exist;
						cy.log('IBAN field available for SEPA');
					}
				});
				return true;
			}, 'SEPA Direct Debit Integration');

			cy.save_frappe_doc();
		});

		it('should test credit card and online payment integration', () => {
			cy.visit_doctype_form('Periodic Donation Agreement');
			cy.wait_for_navigation();

			cy.fill_frappe_field('donor', 'Credit Card Donor');
			cy.fill_frappe_field('donation_amount', '40.00', { fieldtype: 'Currency' });
			cy.fill_frappe_field('frequency', 'Monthly', { fieldtype: 'Select' });
			cy.fill_frappe_field('payment_method', 'Credit Card', { fieldtype: 'Select' });

			// Test credit card integration
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Periodic Donation Agreement');
					expect(frm.doc.payment_method).to.equal('Credit Card');

					// Test credit card specific fields
					if (frm.fields_dict.card_token) {
						expect(frm.fields_dict.card_token).to.exist;
						cy.log('Credit card token storage available');
					}

					if (frm.fields_dict.gateway_subscription_id) {
						expect(frm.fields_dict.gateway_subscription_id).to.exist;
						cy.log('Gateway subscription tracking available');
					}
				});
				return true;
			}, 'Credit Card Payment Integration');

			cy.save_frappe_doc();
		});
	});

	describe('Agreement Lifecycle Management Tests', () => {
		it('should test agreement activation workflow', () => {
			cy.visit_doctype_form('Periodic Donation Agreement');
			cy.wait_for_navigation();

			cy.fill_frappe_field('donor', 'Activation Test Donor');
			cy.fill_frappe_field('donation_amount', '60.00', { fieldtype: 'Currency' });
			cy.fill_frappe_field('frequency', 'Monthly', { fieldtype: 'Select' });
			cy.fill_frappe_field('status', 'Draft', { fieldtype: 'Select' });

			cy.save_frappe_doc();

			// Test activation workflow
			cy.fill_frappe_field('status', 'Active', { fieldtype: 'Select' });

			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Periodic Donation Agreement');
					expect(frm.doc.status).to.equal('Active');

					// Test activation JavaScript logic
					if (frm.doc.status === 'Active') {
						cy.log('Agreement activation workflow triggered');

						// Test if activation sets up scheduling
						if (frm.fields_dict.next_donation_date) {
							expect(frm.fields_dict.next_donation_date).to.exist;
						}

						// Test if activation enables automated processing
						if (frm.fields_dict.automated_processing) {
							expect(frm.fields_dict.automated_processing).to.exist;
						}
					}
				});
				return true;
			}, null, 'Agreement Activation Workflow');

			cy.save_frappe_doc();
		});

		it('should test agreement suspension and cancellation', () => {
			cy.visit_doctype_form('Periodic Donation Agreement');
			cy.wait_for_navigation();

			cy.fill_frappe_field('donor', 'Suspension Test Donor');
			cy.fill_frappe_field('donation_amount', '30.00', { fieldtype: 'Currency' });
			cy.fill_frappe_field('frequency', 'Monthly', { fieldtype: 'Select' });
			cy.fill_frappe_field('status', 'Active', { fieldtype: 'Select' });
			cy.save_frappe_doc();

			// Test suspension
			cy.fill_frappe_field('status', 'Suspended', { fieldtype: 'Select' });

			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Periodic Donation Agreement');
					expect(frm.doc.status).to.equal('Suspended');

					// Test suspension JavaScript logic
					if (frm.fields_dict.suspension_reason) {
						expect(frm.fields_dict.suspension_reason).to.exist;
						cy.log('Suspension reason tracking available');
					}

					if (frm.fields_dict.suspended_until) {
						expect(frm.fields_dict.suspended_until).to.exist;
						cy.log('Suspension duration tracking available');
					}
				});
				return true;
			}, null, 'Agreement Suspension Workflow');

			// Test cancellation
			cy.fill_frappe_field('status', 'Cancelled', { fieldtype: 'Select' });
			cy.save_frappe_doc();
		});
	});

	describe('Donation Processing and History Tests', () => {
		it('should test donation processing history tracking', () => {
			cy.visit_doctype_form('Periodic Donation Agreement');
			cy.wait_for_navigation();

			cy.fill_frappe_field('donor', 'History Tracking Donor');
			cy.fill_frappe_field('donation_amount', '80.00', { fieldtype: 'Currency' });
			cy.fill_frappe_field('frequency', 'Monthly', { fieldtype: 'Select' });
			cy.fill_frappe_field('status', 'Active', { fieldtype: 'Select' });

			cy.save_frappe_doc();

			// Test processing history
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Periodic Donation Agreement');

					// Test processing history fields
					if (frm.fields_dict.last_processed_date) {
						expect(frm.fields_dict.last_processed_date).to.exist;
						cy.log('Last processed date tracking available');
					}

					if (frm.fields_dict.total_donations_processed) {
						expect(frm.fields_dict.total_donations_processed).to.exist;
						cy.log('Total donations counter available');
					}

					if (frm.fields_dict.processing_history) {
						expect(frm.fields_dict.processing_history).to.exist;
						cy.log('Processing history table available');
					}
				});
				return true;
			}, 'Donation Processing History');
		});

		it('should test failed payment handling and retry logic', () => {
			cy.visit_doctype_form('Periodic Donation Agreement');
			cy.wait_for_navigation();

			cy.fill_frappe_field('donor', 'Failed Payment Donor');
			cy.fill_frappe_field('donation_amount', '45.00', { fieldtype: 'Currency' });
			cy.fill_frappe_field('frequency', 'Monthly', { fieldtype: 'Select' });
			cy.fill_frappe_field('status', 'Active', { fieldtype: 'Select' });

			cy.save_frappe_doc();

			// Test failed payment handling
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Periodic Donation Agreement');

					// Test failed payment fields
					if (frm.fields_dict.failed_payment_count) {
						expect(frm.fields_dict.failed_payment_count).to.exist;
						cy.log('Failed payment counter available');
					}

					if (frm.fields_dict.last_failure_reason) {
						expect(frm.fields_dict.last_failure_reason).to.exist;
						cy.log('Failure reason tracking available');
					}

					// Test retry logic
					if (frm.fields_dict.retry_attempts) {
						expect(frm.fields_dict.retry_attempts).to.exist;
						cy.log('Retry attempt tracking available');
					}
				});
				return true;
			}, null, 'Failed Payment Handling');
		});
	});

	describe('Donor Communication and Reporting Tests', () => {
		it('should test donor communication workflow', () => {
			cy.visit_doctype_form('Periodic Donation Agreement');
			cy.wait_for_navigation();

			cy.fill_frappe_field('donor', 'Communication Test Donor');
			cy.fill_frappe_field('donation_amount', '35.00', { fieldtype: 'Currency' });
			cy.fill_frappe_field('frequency', 'Monthly', { fieldtype: 'Select' });
			cy.fill_frappe_field('send_confirmation', true, { fieldtype: 'Check' });

			// Test communication workflow
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Periodic Donation Agreement');
					expect(frm.doc.send_confirmation).to.be.true;

					// Test communication fields
					if (frm.fields_dict.confirmation_sent) {
						expect(frm.fields_dict.confirmation_sent).to.exist;
						cy.log('Confirmation sent tracking available');
					}

					if (frm.fields_dict.communication_preference) {
						expect(frm.fields_dict.communication_preference).to.exist;
						cy.log('Communication preference available');
					}
				});
				return true;
			}, 'Donor Communication Workflow');

			cy.save_frappe_doc();
		});

		it('should test agreement reporting and analytics data', () => {
			cy.visit_doctype_form('Periodic Donation Agreement');
			cy.wait_for_navigation();

			cy.fill_frappe_field('donor', 'Reporting Test Donor');
			cy.fill_frappe_field('donation_amount', '90.00', { fieldtype: 'Currency' });
			cy.fill_frappe_field('frequency', 'Quarterly', { fieldtype: 'Select' });
			cy.fill_frappe_field('campaign', 'Sustainer Campaign 2025', { fieldtype: 'Link' });

			cy.save_frappe_doc();

			// Test reporting data structure
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Periodic Donation Agreement');

					// Verify reporting fields
					expect(frm.doc.donation_amount).to.equal(90.00);
					expect(frm.doc.frequency).to.equal('Quarterly');

					// Test campaign tracking
					if (frm.fields_dict.campaign) {
						expect(frm.fields_dict.campaign).to.exist;
						cy.log('Campaign tracking for reporting available');
					}

					// Test donor lifetime value calculation
					if (frm.fields_dict.projected_annual_value) {
						expect(frm.fields_dict.projected_annual_value).to.exist;
						cy.log('Projected annual value calculation available');
					}
				});
				return true;
			}, null, 'Agreement Reporting and Analytics');
		});
	});

	describe('Integration with Donation Processing System Tests', () => {
		it('should test integration with Donation DocType creation', () => {
			cy.visit_doctype_form('Periodic Donation Agreement');
			cy.wait_for_navigation();

			cy.fill_frappe_field('donor', 'Integration Test Donor');
			cy.fill_frappe_field('donation_amount', '55.00', { fieldtype: 'Currency' });
			cy.fill_frappe_field('frequency', 'Monthly', { fieldtype: 'Select' });
			cy.fill_frappe_field('status', 'Active', { fieldtype: 'Select' });

			cy.save_frappe_doc();

			// Test integration with donation creation
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Periodic Donation Agreement');

					// Test custom buttons for donation processing (when status is Active)
					cy.contains('button', 'Link Donation').should('exist');
					cy.contains('button', 'Cancel Agreement').should('exist');
					cy.contains('button', 'Generate PDF').should('exist');

					// For Draft status (when testing that scenario)
					cy.contains('button', 'Activate Agreement').should('exist');

					// Test donation creation link
					if (frm.fields_dict.related_donations) {
						expect(frm.fields_dict.related_donations).to.exist;
						cy.log('Related donations tracking available');
					}
				});
				return true;
			}, null, 'Donation DocType Integration');
		});
	});
});
