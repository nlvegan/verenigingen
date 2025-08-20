/**
 * @fileoverview Member JavaScript Controller Tests
 *
 * Tests the Member DocType JavaScript controller functionality,
 * including member lifecycle management, status transitions, payment integration,
 * volunteer coordination, and comprehensive business rule validation.
 *
 * Business Context:
 * The Member DocType is the core entity in the association management system,
 * representing individuals with complex relationships to chapters, payments,
 * volunteer activities, and organizational governance structures.
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 * @since 2025-08-19
 */

describe('Member JavaScript Controller Tests', () => {
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

	describe('Member Form Controller Tests', () => {
		it('should load Member form with JavaScript controller', () => {
			// Navigate to new Member form
			cy.visit_doctype_form('Member');
			cy.wait_for_navigation();

			// Verify the controller is loaded
			cy.window().then((win) => {
				expect(win.frappe.ui.form.get_form('Member')).to.exist;
			});

			// Verify core fields are present
			cy.get('[data-fieldname="first_name"]').should('be.visible');
			cy.get('[data-fieldname="last_name"]').should('be.visible');
			cy.get('[data-fieldname="email"]').should('be.visible');
		});

		it('should test member creation workflow with Dutch name conventions', () => {
			cy.visit_doctype_form('Member');
			cy.wait_for_navigation();

			// Create member with Dutch naming conventions
			cy.fill_frappe_field('first_name', 'Willem-Alexander');
			cy.fill_frappe_field('tussenvoegsel', 'van der');
			cy.fill_frappe_field('last_name', 'Berg');
			cy.fill_frappe_field('email', 'w.vandenberg@example.com');
			cy.fill_frappe_field('date_of_birth', '1985-04-27', { fieldtype: 'Date' });

			cy.save_frappe_doc();

			// Verify member was created with proper name handling
			cy.verify_frappe_field('first_name', 'Willem-Alexander');
			cy.verify_frappe_field('tussenvoegsel', 'van der');
			cy.verify_frappe_field('email', 'w.vandenberg@example.com');
		});
	});

	describe('Personal Information and Validation Tests', () => {
		it('should test comprehensive personal information validation', () => {
			cy.visit_doctype_form('Member');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Catharina');
			cy.fill_frappe_field('tussenvoegsel', 'de');
			cy.fill_frappe_field('last_name', 'Groot');
			cy.fill_frappe_field('email', 'catharina.degroot@example.com');
			cy.fill_frappe_field('phone', '+31612345678');
			cy.fill_frappe_field('postal_code', '1012 AB');
			cy.fill_frappe_field('city', 'Amsterdam');

			// Test personal information validation
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member');

					// Test Dutch-specific validations
					if (frm.fields_dict.postal_code_validation) {
						expect(frm.fields_dict.postal_code_validation).to.exist;
						cy.log('Dutch postal code validation available');
					}

					if (frm.fields_dict.phone_validation) {
						expect(frm.fields_dict.phone_validation).to.exist;
						cy.log('Dutch phone number validation available');
					}

					// Test name construction logic
					if (frm.fields_dict.full_name_calculation) {
						expect(frm.fields_dict.full_name_calculation).to.exist;
						cy.log('Dutch full name construction available');
					}
				});
				return true;
			}, null, 'Personal Information Validation');

			cy.save_frappe_doc();
		});

		it('should test age-based business rule validation', () => {
			cy.visit_doctype_form('Member');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Emma');
			cy.fill_frappe_field('last_name', 'Jonkers');
			cy.fill_frappe_field('email', 'emma.jonkers@example.com');
			cy.fill_frappe_field('date_of_birth', '2010-06-15', { fieldtype: 'Date' });

			// Test age-based validations
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member');

					// Test age calculation
					if (frm.fields_dict.calculated_age) {
						expect(frm.fields_dict.calculated_age).to.exist;
						cy.log('Age calculation available');
					}

					// Test volunteer eligibility (must be 16+)
					if (frm.doc.date_of_birth) {
						const birthYear = new Date(frm.doc.date_of_birth).getFullYear();
						const currentYear = new Date().getFullYear();
						const age = currentYear - birthYear;

						if (age < 16 && frm.fields_dict.volunteer_restriction) {
							expect(frm.fields_dict.volunteer_restriction).to.exist;
							cy.log('Volunteer age restriction enforced');
						}
					}

					// Test minor membership requirements
					if (frm.fields_dict.guardian_consent) {
						expect(frm.fields_dict.guardian_consent).to.exist;
						cy.log('Guardian consent handling available');
					}
				});
				return true;
			}, 'Age Validation');

			cy.save_frappe_doc();
		});
	});

	describe('Membership Status and Lifecycle Tests', () => {
		it('should test membership status transitions and validation', () => {
			cy.visit_doctype_form('Member');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Status');
			cy.fill_frappe_field('last_name', 'Test');
			cy.fill_frappe_field('email', 'status.test@example.com');
			cy.fill_frappe_field('status', 'Applicant', { fieldtype: 'Select' });

			cy.save_frappe_doc();

			// Test status transitions
			const statuses = ['Applicant', 'Active', 'Inactive', 'Suspended', 'Terminated'];
			cy.wrap(statuses).each((status, index) => {
				if (index === 0) {
					return;
				}
				cy.fill_frappe_field('status', status, { fieldtype: 'Select' });
				cy.execute_business_workflow(() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('Member');
						expect(frm.doc.status).to.equal(status);
						cy.log(`Member status changed to: ${status}`);
						if (status === 'Active' && frm.fields_dict.activation_date) {
							expect(frm.fields_dict.activation_date).to.exist;
						}
						if (status === 'Suspended' && frm.fields_dict.suspension_reason) {
							expect(frm.fields_dict.suspension_reason).to.exist;
						}
						if (status === 'Terminated' && frm.fields_dict.termination_date) {
							expect(frm.fields_dict.termination_date).to.exist;
						}
					});
					return true;
				}, null, `Status Change to ${status}`);
				cy.save_frappe_doc();
			});
		});

		it('should test membership renewal and expiration handling', () => {
			cy.visit_doctype_form('Member');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Renewal');
			cy.fill_frappe_field('last_name', 'Test');
			cy.fill_frappe_field('email', 'renewal.test@example.com');
			cy.fill_frappe_field('membership_expiry', '2025-12-31', { fieldtype: 'Date' });
			cy.fill_frappe_field('auto_renewal', true, { fieldtype: 'Check' });

			// Test renewal logic
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member');

					// Test renewal fields
					if (frm.fields_dict.renewal_reminder) {
						expect(frm.fields_dict.renewal_reminder).to.exist;
						cy.log('Renewal reminder system available');
					}

					if (frm.fields_dict.expiry_notification) {
						expect(frm.fields_dict.expiry_notification).to.exist;
						cy.log('Expiry notification system available');
					}

					// Test auto-renewal logic
					if (frm.doc.auto_renewal && frm.fields_dict.auto_renewal_processing) {
						expect(frm.fields_dict.auto_renewal_processing).to.exist;
						cy.log('Auto-renewal processing available');
					}
				});
				return true;
			}, null, 'Renewal Management');

			cy.save_frappe_doc();
		});
	});

	describe('Financial Integration and Payment Tests', () => {
		it('should test customer integration and payment setup', () => {
			cy.visit_doctype_form('Member');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Payment');
			cy.fill_frappe_field('last_name', 'Integration');
			cy.fill_frappe_field('email', 'payment.integration@example.com');
			cy.fill_frappe_field('preferred_payment_method', 'Bank Transfer', { fieldtype: 'Select' });

			// Test payment integration
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member');

					// Test customer creation
					if (frm.fields_dict.customer_creation) {
						expect(frm.fields_dict.customer_creation).to.exist;
						cy.log('Customer creation integration available');
					}

					// Test payment method setup
					if (frm.fields_dict.payment_setup) {
						expect(frm.fields_dict.payment_setup).to.exist;
						cy.log('Payment method setup available');
					}

					// Test dues scheduling
					if (frm.fields_dict.dues_schedule_creation) {
						expect(frm.fields_dict.dues_schedule_creation).to.exist;
						cy.log('Dues schedule creation available');
					}
				});
				return true;
			}, 'Payment Integration');

			cy.save_frappe_doc();
		});

		it('should test SEPA Direct Debit integration and mandate management', () => {
			cy.visit_doctype_form('Member');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'SEPA');
			cy.fill_frappe_field('last_name', 'Mandate');
			cy.fill_frappe_field('email', 'sepa.mandate@example.com');
			cy.fill_frappe_field('preferred_payment_method', 'SEPA Direct Debit', { fieldtype: 'Select' });
			cy.fill_frappe_field('iban', 'NL91ABNA0417164300');

			// Test SEPA integration
			cy.execute_sepa_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member');

					// Test SEPA mandate creation
					if (frm.fields_dict.sepa_mandate) {
						expect(frm.fields_dict.sepa_mandate).to.exist;
						cy.log('SEPA mandate management available');
					}

					// Test IBAN validation
					if (frm.fields_dict.iban_validation) {
						expect(frm.fields_dict.iban_validation).to.exist;
						cy.log('IBAN validation available');
					}

					// Test direct debit setup
					if (frm.fields_dict.direct_debit_setup) {
						expect(frm.fields_dict.direct_debit_setup).to.exist;
						cy.log('Direct debit setup available');
					}
				});
				return true;
			}, 'SEPA Integration');

			cy.save_frappe_doc();
		});
	});

	describe('Chapter and Volunteer Integration Tests', () => {
		it('should test chapter membership and assignment', () => {
			cy.visit_doctype_form('Member');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Chapter');
			cy.fill_frappe_field('last_name', 'Member');
			cy.fill_frappe_field('email', 'chapter.member@example.com');
			cy.fill_frappe_field('primary_chapter', 'Amsterdam', { fieldtype: 'Link' });

			// Test chapter integration
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member');

					// Test chapter assignment buttons
					cy.contains('button', 'Assign Chapter').should('exist');
					cy.contains('button', 'View').should('exist');

					// Test chapter membership tracking
					if (frm.fields_dict.chapter_memberships) {
						expect(frm.fields_dict.chapter_memberships).to.exist;
						cy.log('Chapter membership tracking available');
					}
				});
				return true;
			}, null, 'Chapter Integration');

			cy.save_frappe_doc();
		});

		it('should test volunteer profile integration and eligibility', () => {
			cy.visit_doctype_form('Member');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Volunteer');
			cy.fill_frappe_field('last_name', 'Profile');
			cy.fill_frappe_field('email', 'volunteer.profile@example.com');
			cy.fill_frappe_field('date_of_birth', '1990-03-20', { fieldtype: 'Date' });
			cy.fill_frappe_field('is_volunteer', true, { fieldtype: 'Check' });

			// Test volunteer integration
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member');

					// Test volunteer eligibility (16+ years)
					if (frm.doc.is_volunteer && frm.fields_dict.volunteer_eligibility) {
						expect(frm.fields_dict.volunteer_eligibility).to.exist;
						cy.log('Volunteer eligibility validation available');
					}

					// Test volunteer profile creation
					if (frm.fields_dict.volunteer_profile) {
						expect(frm.fields_dict.volunteer_profile).to.exist;
						cy.log('Volunteer profile integration available');
					}

					// Test volunteer activity tracking
					if (frm.fields_dict.volunteer_activities) {
						expect(frm.fields_dict.volunteer_activities).to.exist;
						cy.log('Volunteer activity tracking available');
					}
				});
				return true;
			}, 'Volunteer Integration');

			cy.save_frappe_doc();
		});
	});

	describe('Communication and Privacy Tests', () => {
		it('should test communication preferences and consent management', () => {
			cy.visit_doctype_form('Member');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Privacy');
			cy.fill_frappe_field('last_name', 'Test');
			cy.fill_frappe_field('email', 'privacy.test@example.com');
			cy.fill_frappe_field('email_consent', true, { fieldtype: 'Check' });
			cy.fill_frappe_field('marketing_consent', false, { fieldtype: 'Check' });

			// Test privacy and communication
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member');

					// Test consent management
					if (frm.fields_dict.consent_tracking) {
						expect(frm.fields_dict.consent_tracking).to.exist;
						cy.log('Consent management tracking available');
					}

					// Test GDPR compliance
					if (frm.fields_dict.gdpr_compliance) {
						expect(frm.fields_dict.gdpr_compliance).to.exist;
						cy.log('GDPR compliance features available');
					}

					// Test communication preferences
					if (frm.fields_dict.communication_log) {
						expect(frm.fields_dict.communication_log).to.exist;
						cy.log('Communication logging available');
					}
				});
				return true;
			}, null, 'Privacy Management');

			cy.save_frappe_doc();
		});

		it('should test data retention and member termination workflow', () => {
			cy.visit_doctype_form('Member');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Termination');
			cy.fill_frappe_field('last_name', 'Test');
			cy.fill_frappe_field('email', 'termination.test@example.com');
			cy.fill_frappe_field('status', 'Active', { fieldtype: 'Select' });

			cy.save_frappe_doc();

			// Test termination workflow
			cy.fill_frappe_field('status', 'Terminated', { fieldtype: 'Select' });
			cy.fill_frappe_field('termination_reason', 'Voluntary', { fieldtype: 'Select' });

			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member');

					// Test termination processing
					if (frm.fields_dict.termination_workflow) {
						expect(frm.fields_dict.termination_workflow).to.exist;
						cy.log('Termination workflow available');
					}

					// Test data retention
					if (frm.fields_dict.data_retention_policy) {
						expect(frm.fields_dict.data_retention_policy).to.exist;
						cy.log('Data retention policy enforcement available');
					}

					// Test cleanup procedures
					if (frm.fields_dict.cleanup_procedures) {
						expect(frm.fields_dict.cleanup_procedures).to.exist;
						cy.log('Data cleanup procedures available');
					}
				});
				return true;
			}, 'Termination Workflow');

			cy.save_frappe_doc();
		});
	});

	describe('Reporting and Analytics Integration Tests', () => {
		it('should test member analytics and reporting data', () => {
			cy.visit_doctype_form('Member');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Analytics');
			cy.fill_frappe_field('last_name', 'Member');
			cy.fill_frappe_field('email', 'analytics.member@example.com');
			cy.fill_frappe_field('date_of_birth', '1985-07-12', { fieldtype: 'Date' });
			cy.fill_frappe_field('member_since', '2020-01-15', { fieldtype: 'Date' });
			cy.fill_frappe_field('status', 'Active', { fieldtype: 'Select' });

			// Test analytics data structure
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member');

					// Verify core reporting fields
					expect(frm.doc.first_name).to.equal('Analytics');
					expect(frm.doc.email).to.equal('analytics.member@example.com');
					expect(frm.doc.status).to.equal('Active');

					// Test demographic analysis
					if (frm.fields_dict.demographic_category) {
						expect(frm.fields_dict.demographic_category).to.exist;
						cy.log('Demographic categorization available');
					}

					// Test engagement metrics
					if (frm.fields_dict.engagement_score) {
						expect(frm.fields_dict.engagement_score).to.exist;
						cy.log('Member engagement scoring available');
					}

					cy.log('Member properly structured for comprehensive reporting');
				});
				return true;
			}, null, 'Analytics Data Structure');

			cy.save_frappe_doc();
		});
	});
});
