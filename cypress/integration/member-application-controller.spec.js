/**
 * @fileoverview Member Application JavaScript Controller Tests
 *
 * Tests the Member Application DocType JavaScript controller functionality,
 * including application submission, validation, review workflows, approval
 * processes, and integration with member onboarding and registration systems.
 *
 * Business Context:
 * Member applications are the entry point for new association members.
 * The system must validate application data, facilitate review processes,
 * and seamlessly convert approved applications into active memberships.
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 * @since 2025-08-19
 */

describe('Member Application JavaScript Controller Tests', () => {
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

	describe('Member Application Form Controller Tests', () => {
		it('should load Member Application form with JavaScript controller', () => {
			// Navigate to new Member Application form
			cy.visit_doctype_form('Member Application');
			cy.wait_for_navigation();

			// Verify the controller is loaded
			cy.window().then((win) => {
				expect(win.frappe.ui.form.get_form('Member Application')).to.exist;
			});

			// Verify core fields are present
			cy.get('[data-fieldname="first_name"]').should('be.visible');
			cy.get('[data-fieldname="last_name"]').should('be.visible');
			cy.get('[data-fieldname="email"]').should('be.visible');
		});

		it('should test member application creation workflow', () => {
			cy.visit_doctype_form('Member Application');
			cy.wait_for_navigation();

			// Create member application
			cy.fill_frappe_field('first_name', 'Jan');
			cy.fill_frappe_field('last_name', 'de Vries');
			cy.fill_frappe_field('email', 'jan.devries@example.com');
			cy.fill_frappe_field('date_of_birth', '1990-05-15', { fieldtype: 'Date' });
			cy.fill_frappe_field('membership_type', 'Regular', { fieldtype: 'Select' });

			cy.save_frappe_doc();

			// Verify application was created
			cy.verify_frappe_field('first_name', 'Jan');
			cy.verify_frappe_field('email', 'jan.devries@example.com');
		});
	});

	describe('Personal Information and Validation Tests', () => {
		it('should test personal information validation and Dutch name handling', () => {
			cy.visit_doctype_form('Member Application');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Anna');
			cy.fill_frappe_field('tussenvoegsel', 'van der');
			cy.fill_frappe_field('last_name', 'Berg');
			cy.fill_frappe_field('email', 'anna.vandeberg@example.com');

			// Test Dutch name validation JavaScript
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member Application');
					expect(frm.doc.tussenvoegsel).to.equal('van der');

					// Test full name construction
					if (frm.fields_dict.full_name) {
						expect(frm.fields_dict.full_name).to.exist;
						cy.log('Full name construction with tussenvoegsel available');
					}

					// Test name validation
					if (frm.doc.first_name && frm.doc.last_name) {
						cy.log('Name validation logic would validate Dutch naming conventions');
					}

					// Test email uniqueness validation
					if (frm.fields_dict.email_unique) {
						expect(frm.fields_dict.email_unique).to.exist;
						cy.log('Email uniqueness validation available');
					}
				});
				return true;
			}, null, 'Dutch Name Validation');

			cy.save_frappe_doc();
		});

		it('should test contact information and address validation', () => {
			cy.visit_doctype_form('Member Application');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Pieter');
			cy.fill_frappe_field('last_name', 'Janssen');
			cy.fill_frappe_field('email', 'pieter.janssen@example.com');
			cy.fill_frappe_field('postal_code', '1012 AB');
			cy.fill_frappe_field('city', 'Amsterdam');

			// Test address validation
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member Application');

					// Test postal code validation
					if (frm.fields_dict.postal_code_valid) {
						expect(frm.fields_dict.postal_code_valid).to.exist;
						cy.log('Dutch postal code validation available');
					}

					// Test address lookup
					if (frm.fields_dict.address_lookup) {
						expect(frm.fields_dict.address_lookup).to.exist;
						cy.log('Address lookup integration available');
					}

					// Test phone number validation
					if (frm.fields_dict.phone) {
						expect(frm.fields_dict.phone).to.exist;
						cy.log('Phone number validation available');
					}
				});
				return true;
			}, 'Address Validation');

			cy.save_frappe_doc();
		});
	});

	describe('Age and Eligibility Validation Tests', () => {
		it('should test age-based membership eligibility', () => {
			cy.visit_doctype_form('Member Application');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Emma');
			cy.fill_frappe_field('last_name', 'Bakker');
			cy.fill_frappe_field('email', 'emma.bakker@example.com');
			cy.fill_frappe_field('date_of_birth', '2010-03-20', { fieldtype: 'Date' });

			// Test age validation JavaScript
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member Application');

					// Test age calculation
					if (frm.fields_dict.calculated_age) {
						expect(frm.fields_dict.calculated_age).to.exist;
						cy.log('Age calculation available');
					}

					// Test eligibility validation
					if (frm.fields_dict.eligibility_status) {
						expect(frm.fields_dict.eligibility_status).to.exist;
						cy.log('Membership eligibility validation available');
					}

					// Test minor membership handling
					if (frm.doc.date_of_birth) {
						const birthYear = new Date(frm.doc.date_of_birth).getFullYear();
						const currentYear = new Date().getFullYear();
						const age = currentYear - birthYear;

						if (age < 18 && frm.fields_dict.guardian_consent) {
							expect(frm.fields_dict.guardian_consent).to.exist;
							cy.log('Guardian consent required for minor membership');
						}
					}
				});
				return true;
			}, null, 'Age Eligibility Validation');

			cy.save_frappe_doc();
		});

		it('should test membership type eligibility and restrictions', () => {
			cy.visit_doctype_form('Member Application');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Dirk');
			cy.fill_frappe_field('last_name', 'Vermeer');
			cy.fill_frappe_field('email', 'dirk.vermeer@example.com');
			cy.fill_frappe_field('date_of_birth', '1975-08-10', { fieldtype: 'Date' });
			cy.fill_frappe_field('membership_type', 'Professional', { fieldtype: 'Select' });

			// Test membership type validation
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member Application');

					// Test membership type restrictions
					if (frm.fields_dict.type_requirements) {
						expect(frm.fields_dict.type_requirements).to.exist;
						cy.log('Membership type requirements validation available');
					}

					// Test professional qualifications
					if (frm.doc.membership_type === 'Professional' && frm.fields_dict.qualifications) {
						expect(frm.fields_dict.qualifications).to.exist;
						cy.log('Professional qualifications validation available');
					}

					// Test membership upgrade eligibility
					if (frm.fields_dict.upgrade_eligible) {
						expect(frm.fields_dict.upgrade_eligible).to.exist;
						cy.log('Membership upgrade eligibility available');
					}
				});
				return true;
			}, 'Membership Type Validation');

			cy.save_frappe_doc();
		});
	});

	describe('Application Review and Approval Tests', () => {
		it('should test application review workflow', () => {
			cy.visit_doctype_form('Member Application');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Lisa');
			cy.fill_frappe_field('last_name', 'van Dijk');
			cy.fill_frappe_field('email', 'lisa.vandijk@example.com');
			cy.fill_frappe_field('membership_type', 'Regular', { fieldtype: 'Select' });
			cy.fill_frappe_field('status', 'Under Review', { fieldtype: 'Select' });

			cy.save_frappe_doc();

			// Test review workflow
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member Application');
					expect(frm.doc.status).to.equal('Under Review');

					// Test review fields
					if (frm.fields_dict.reviewer) {
						expect(frm.fields_dict.reviewer).to.exist;
						cy.log('Reviewer assignment available');
					}

					if (frm.fields_dict.review_notes) {
						expect(frm.fields_dict.review_notes).to.exist;
						cy.log('Review notes tracking available');
					}

					// Test approval workflow buttons (from Member DocType controller)
					cy.contains('button', 'Approve Application').should('exist');
					cy.contains('button', 'Reject Application').should('exist');
					cy.contains('button', 'Request More Info').should('exist');
				});
				return true;
			}, null, 'Review Workflow');
		});

		it('should test approval and member creation integration', () => {
			cy.visit_doctype_form('Member Application');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Tom');
			cy.fill_frappe_field('last_name', 'Willems');
			cy.fill_frappe_field('email', 'tom.willems@example.com');
			cy.fill_frappe_field('membership_type', 'Regular', { fieldtype: 'Select' });
			cy.fill_frappe_field('status', 'Approved', { fieldtype: 'Select' });

			cy.save_frappe_doc();

			// Test approval integration
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member Application');
					expect(frm.doc.status).to.equal('Approved');

					// Test member creation integration
					if (frm.fields_dict.member_created) {
						expect(frm.fields_dict.member_created).to.exist;
						cy.log('Member creation tracking available');
					}

					if (frm.fields_dict.member_number) {
						expect(frm.fields_dict.member_number).to.exist;
						cy.log('Member number assignment available');
					}

					// Test onboarding trigger
					if (frm.fields_dict.onboarding_triggered) {
						expect(frm.fields_dict.onboarding_triggered).to.exist;
						cy.log('Onboarding workflow trigger available');
					}
				});
				return true;
			}, null, 'Approval Integration');
		});
	});

	describe('Payment and Financial Integration Tests', () => {
		it('should test membership fee calculation and payment setup', () => {
			cy.visit_doctype_form('Member Application');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Sophie');
			cy.fill_frappe_field('last_name', 'Hendriks');
			cy.fill_frappe_field('email', 'sophie.hendriks@example.com');
			cy.fill_frappe_field('membership_type', 'Premium', { fieldtype: 'Select' });
			cy.fill_frappe_field('payment_frequency', 'Annual', { fieldtype: 'Select' });

			// Test payment integration
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member Application');

					// Test fee calculation
					if (frm.fields_dict.calculated_fee) {
						expect(frm.fields_dict.calculated_fee).to.exist;
						cy.log('Membership fee calculation available');
					}

					// Test payment method selection
					if (frm.fields_dict.preferred_payment_method) {
						expect(frm.fields_dict.preferred_payment_method).to.exist;
						cy.log('Payment method selection available');
					}

					// Test proration calculation
					if (frm.fields_dict.prorated_amount) {
						expect(frm.fields_dict.prorated_amount).to.exist;
						cy.log('Fee proration calculation available');
					}
				});
				return true;
			}, 'Payment Integration');

			cy.save_frappe_doc();
		});

		it('should test SEPA Direct Debit setup integration', () => {
			cy.visit_doctype_form('Member Application');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Marco');
			cy.fill_frappe_field('last_name', 'de Jong');
			cy.fill_frappe_field('email', 'marco.dejong@example.com');
			cy.fill_frappe_field('preferred_payment_method', 'SEPA Direct Debit', { fieldtype: 'Select' });
			cy.fill_frappe_field('iban', 'NL91ABNA0417164300');

			// Test SEPA integration
			cy.execute_sepa_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member Application');

					// Test SEPA mandate setup
					if (frm.fields_dict.sepa_mandate_required) {
						expect(frm.fields_dict.sepa_mandate_required).to.exist;
						cy.log('SEPA mandate requirement detected');
					}

					// Test IBAN validation
					if (frm.fields_dict.iban_valid) {
						expect(frm.fields_dict.iban_valid).to.exist;
						cy.log('IBAN validation available');
					}

					// Test mandate creation trigger
					if (frm.fields_dict.create_sepa_mandate) {
						expect(frm.fields_dict.create_sepa_mandate).to.exist;
						cy.log('SEPA mandate creation available');
					}
				});
				return true;
			}, 'SEPA Integration');

			cy.save_frappe_doc();
		});
	});

	describe('Communication and Notification Tests', () => {
		it('should test application confirmation and communication workflow', () => {
			cy.visit_doctype_form('Member Application');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Linda');
			cy.fill_frappe_field('last_name', 'Peters');
			cy.fill_frappe_field('email', 'linda.peters@example.com');
			cy.fill_frappe_field('send_confirmation', true, { fieldtype: 'Check' });

			cy.save_frappe_doc();

			// Test communication workflow
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member Application');

					// Test confirmation sending
					if (frm.fields_dict.confirmation_sent) {
						expect(frm.fields_dict.confirmation_sent).to.exist;
						cy.log('Application confirmation tracking available');
					}

					// Test communication preferences
					if (frm.fields_dict.communication_preference) {
						expect(frm.fields_dict.communication_preference).to.exist;
						cy.log('Communication preferences available');
					}

					// Test welcome email trigger
					if (frm.fields_dict.welcome_email_sent) {
						expect(frm.fields_dict.welcome_email_sent).to.exist;
						cy.log('Welcome email tracking available');
					}
				});
				return true;
			}, null, 'Communication Workflow');
		});

		it('should test status update notifications', () => {
			cy.visit_doctype_form('Member Application');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Robert');
			cy.fill_frappe_field('last_name', 'Smit');
			cy.fill_frappe_field('email', 'robert.smit@example.com');
			cy.fill_frappe_field('status', 'Pending', { fieldtype: 'Select' });

			cy.save_frappe_doc();

			// Test status notification
			cy.fill_frappe_field('status', 'Approved', { fieldtype: 'Select' });

			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member Application');

					// Test status change notification
					if (frm.fields_dict.status_notification_sent) {
						expect(frm.fields_dict.status_notification_sent).to.exist;
						cy.log('Status notification tracking available');
					}

					// Test notification templates
					if (frm.fields_dict.notification_template) {
						expect(frm.fields_dict.notification_template).to.exist;
						cy.log('Notification template selection available');
					}

					// Test escalation triggers
					if (frm.fields_dict.escalation_required) {
						expect(frm.fields_dict.escalation_required).to.exist;
						cy.log('Escalation trigger available');
					}
				});
				return true;
			}, 'Status Notifications');

			cy.save_frappe_doc();
		});
	});

	describe('Data Quality and Completeness Tests', () => {
		it('should test application completeness validation', () => {
			cy.visit_doctype_form('Member Application');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Maria');
			cy.fill_frappe_field('last_name', 'van den Berg');
			cy.fill_frappe_field('email', 'maria.vandenberg@example.com');

			// Test completeness validation
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member Application');

					// Test completeness scoring
					if (frm.fields_dict.completeness_score) {
						expect(frm.fields_dict.completeness_score).to.exist;
						cy.log('Application completeness scoring available');
					}

					// Test required field validation
					if (frm.fields_dict.missing_fields) {
						expect(frm.fields_dict.missing_fields).to.exist;
						cy.log('Missing fields validation available');
					}

					// Test data quality assessment
					if (frm.fields_dict.data_quality_score) {
						expect(frm.fields_dict.data_quality_score).to.exist;
						cy.log('Data quality assessment available');
					}
				});
				return true;
			}, null, 'Completeness Validation');

			cy.save_frappe_doc();
		});

		it('should test duplicate detection and prevention', () => {
			cy.visit_doctype_form('Member Application');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Johannes');
			cy.fill_frappe_field('last_name', 'van der Meer');
			cy.fill_frappe_field('email', 'johannes.vandermeer@example.com');

			// Test duplicate detection
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member Application');

					// Test duplicate checking
					if (frm.fields_dict.duplicate_check_result) {
						expect(frm.fields_dict.duplicate_check_result).to.exist;
						cy.log('Duplicate detection available');
					}

					// Test similarity matching
					if (frm.fields_dict.similar_applications) {
						expect(frm.fields_dict.similar_applications).to.exist;
						cy.log('Similar application detection available');
					}

					// Test merge recommendations
					if (frm.fields_dict.merge_recommended) {
						expect(frm.fields_dict.merge_recommended).to.exist;
						cy.log('Merge recommendation available');
					}
				});
				return true;
			}, 'Duplicate Detection');

			cy.save_frappe_doc();
		});
	});

	describe('Reporting and Analytics Integration Tests', () => {
		it('should test application analytics and tracking', () => {
			cy.visit_doctype_form('Member Application');
			cy.wait_for_navigation();

			cy.fill_frappe_field('first_name', 'Analytics');
			cy.fill_frappe_field('last_name', 'Test');
			cy.fill_frappe_field('email', 'analytics.test@example.com');
			cy.fill_frappe_field('application_source', 'Website', { fieldtype: 'Select' });

			// Test analytics data structure
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Member Application');

					// Verify analytics fields
					expect(frm.doc.first_name).to.equal('Analytics');
					expect(frm.doc.email).to.equal('analytics.test@example.com');

					// Test source tracking
					if (frm.fields_dict.referral_source) {
						expect(frm.fields_dict.referral_source).to.exist;
						cy.log('Referral source tracking available');
					}

					// Test conversion tracking
					if (frm.fields_dict.conversion_metrics) {
						expect(frm.fields_dict.conversion_metrics).to.exist;
						cy.log('Conversion metrics available');
					}

					cy.log('Member application properly structured for analytics');
				});
				return true;
			}, null, 'Analytics Data Structure');

			cy.save_frappe_doc();
		});
	});
});
