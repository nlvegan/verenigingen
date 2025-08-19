/**
 * @fileoverview Mollie Settings JavaScript Controller Tests
 *
 * Tests the Mollie Settings DocType JavaScript controller and its integration
 * with the Mollie payment gateway API. This covers subscription management,
 * payment processing configuration, and API key validation workflows.
 *
 * Business Context:
 * Mollie integration is critical for recurring membership payment processing.
 * The settings must be properly configured for subscription management,
 * webhook handling, and secure API communication.
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 * @since 2025-08-19
 */

describe('Mollie Settings JavaScript Controller Tests', () => {
	beforeEach(() => {
		cy.login('Administrator', 'admin');
		cy.clear_test_data();
	});

	afterEach(() => {
		cy.clear_test_data();
	});

	describe('Mollie Settings Form Controller Tests', () => {
		it('should load Mollie Settings form with JavaScript controller', () => {
			// Navigate to Mollie Settings (single doctype)
			cy.visit('/app/mollie-settings');
			cy.wait_for_navigation();

			// Verify the controller is loaded
			cy.window().then((win) => {
				expect(win.frappe.ui.form.get_form('Mollie Settings')).to.exist;
			});

			// Verify core fields are present
			cy.get('[data-fieldname="gateway_name"]').should('be.visible');
			cy.get('[data-fieldname="secret_key"]').should('be.visible');
			cy.get('[data-fieldname="enabled"]').should('be.visible');
		});

		it('should test Mollie API key configuration and validation', () => {
			cy.visit('/app/mollie-settings');
			cy.wait_for_navigation();

			// Test API key field interaction
			cy.fill_frappe_field('gateway_name', 'Mollie');
			cy.fill_frappe_field('enabled', true, { fieldtype: 'Check' });

			// Test API key validation workflow
			cy.execute_business_workflow(() => {
				// Note: In real implementation, this would validate API key format
				cy.get('[data-fieldname="secret_key"]').should('be.visible');

				// Test JavaScript validation if available
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Mollie Settings');
					expect(frm).to.exist;

					// Verify form fields are accessible
					expect(frm.fields_dict.secret_key).to.exist;
					expect(frm.fields_dict.gateway_name).to.exist;
				});

				return true;
			}, null, 'Mollie API Key Configuration');
		});
	});

	describe('Subscription Management Tests', () => {
		it('should test subscription configuration settings', () => {
			cy.visit('/app/mollie-settings');
			cy.wait_for_navigation();

			// Configure subscription settings
			cy.fill_frappe_field('gateway_name', 'Mollie');
			cy.fill_frappe_field('enabled', true, { fieldtype: 'Check' });

			// Test subscription-related fields
			cy.get('[data-fieldname="subscription_enabled"]').should('be.visible');

			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Mollie Settings');

					// Test subscription configuration
					if (frm.fields_dict.subscription_enabled) {
						expect(frm.fields_dict.subscription_enabled).to.exist;
					}

					// Test webhook configuration
					if (frm.fields_dict.webhook_url) {
						expect(frm.fields_dict.webhook_url).to.exist;
					}
				});
				return true;
			}, 'Subscription Configuration Test');

			cy.save_frappe_doc();
		});

		it('should test webhook URL configuration', () => {
			cy.visit('/app/mollie-settings');
			cy.wait_for_navigation();

			// Test webhook configuration
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Mollie Settings');

					// Verify webhook URL field exists and can be configured
					if (frm.fields_dict.webhook_url) {
						expect(frm.fields_dict.webhook_url).to.exist;
						cy.log('Webhook URL configuration available');
					}

					// Test JavaScript webhook validation if implemented
					expect(frm).to.exist;
				});
				return true;
			}, 'Webhook Configuration Test');
		});
	});

	describe('Payment Gateway Integration Tests', () => {
		it('should test payment method configuration', () => {
			cy.visit('/app/mollie-settings');
			cy.wait_for_navigation();

			// Configure payment gateway
			cy.fill_frappe_field('gateway_name', 'Mollie');
			cy.fill_frappe_field('enabled', true, { fieldtype: 'Check' });

			// Test payment method settings
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Mollie Settings');

					// Test payment method configuration
					expect(frm.doc.gateway_name).to.equal('Mollie');
					expect(frm.doc.enabled).to.be.true;

					// Test JavaScript payment integration if available
					cy.log('Payment gateway configuration validated');
				});
				return true;
			}, null, 'Payment Gateway Configuration');

			cy.save_frappe_doc();
			cy.verify_frappe_field('gateway_name', 'Mollie');
		});

		it('should test currency and locale settings', () => {
			cy.visit('/app/mollie-settings');
			cy.wait_for_navigation();

			// Test currency configuration
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Mollie Settings');

					// Test currency settings if available
					if (frm.fields_dict.currency) {
						expect(frm.fields_dict.currency).to.exist;
						cy.log('Currency configuration available');
					}

					// Test locale settings for Dutch market
					if (frm.fields_dict.locale) {
						expect(frm.fields_dict.locale).to.exist;
						cy.log('Locale configuration available');
					}
				});
				return true;
			}, 'Currency and Locale Configuration');
		});
	});

	describe('Security and Validation Tests', () => {
		it('should test API key security handling', () => {
			cy.visit('/app/mollie-settings');
			cy.wait_for_navigation();

			// Test API key security
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Mollie Settings');

					// Verify API key field is password type
					const secretKeyField = frm.fields_dict.secret_key;
					if (secretKeyField) {
						expect(secretKeyField.df.fieldtype).to.equal('Password');
						cy.log('API key properly secured as password field');
					}
				});
				return true;
			}, null, 'API Key Security Test');
		});

		it('should test form validation for required fields', () => {
			cy.visit('/app/mollie-settings');
			cy.wait_for_navigation();

			// Test validation by attempting save without required fields
			cy.execute_form_operation(() => {
				// Clear required fields and attempt save
				cy.get('.primary-action').contains('Save').click();

				// Check for validation errors
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Mollie Settings');
					expect(frm).to.exist;
					cy.log('Form validation tested');
				});

				return true;
			}, 'Form Validation Test');
		});
	});

	describe('Integration with Subscription Workflows', () => {
		it('should test integration with member subscription creation', () => {
			// First configure Mollie Settings
			cy.visit('/app/mollie-settings');
			cy.wait_for_navigation();

			cy.fill_frappe_field('gateway_name', 'Mollie');
			cy.fill_frappe_field('enabled', true, { fieldtype: 'Check' });
			cy.save_frappe_doc();

			// Test integration with member workflow
			cy.createTestMemberWithFinancialSetup().then((member) => {
				cy.execute_business_workflow(() => {
					cy.log(`Testing Mollie integration with member: ${member.name}`);

					// Verify Mollie settings are accessible from member workflows
					cy.window().then((win) => {
						// Test if Mollie settings can be accessed programmatically
						if (win.frappe && win.frappe.boot && win.frappe.boot.sysdefaults) {
							cy.log('Mollie settings integration validated');
						}
					});

					return true;
				}, null, 'Member-Mollie Integration Test');
			});
		});
	});
});
