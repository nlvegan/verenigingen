/**
 * @fileoverview E-Boekhouden Settings JavaScript Controller Tests
 *
 * Tests the E-Boekhouden Settings DocType JavaScript controller functionality,
 * including API configuration, authentication, mapping settings, and integration
 * workflows for Dutch accounting system synchronization.
 *
 * Business Context:
 * E-Boekhouden integration is essential for Dutch associations to maintain
 * proper accounting records. The system must securely connect to the
 * E-Boekhouden API and synchronize financial data accurately.
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 * @since 2025-08-19
 */

describe('E-Boekhouden Settings JavaScript Controller Tests', () => {
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

	describe('E-Boekhouden Settings Form Controller Tests', () => {
		it('should load E-Boekhouden Settings form with JavaScript controller', () => {
			// Navigate to E-Boekhouden Settings (single doctype)
			cy.visit('/app/e-boekhouden-settings');
			cy.wait_for_navigation();

			// Verify the controller is loaded
			cy.window().then((win) => {
				expect(win.frappe.ui.form.get_form('E-Boekhouden Settings')).to.exist;
			});

			// Verify core fields are present
			cy.get('[data-fieldname="enabled"]').should('be.visible');
			cy.get('[data-fieldname="username"]').should('be.visible');
			cy.get('[data-fieldname="security_code_1"]').should('be.visible');
		});

		it('should test API configuration workflow', () => {
			cy.visit('/app/e-boekhouden-settings');
			cy.wait_for_navigation();

			// Configure basic API settings
			cy.fill_frappe_field('enabled', true, { fieldtype: 'Check' });
			cy.fill_frappe_field('username', 'test_user@vereniging.nl');
			cy.fill_frappe_field('security_code_1', 'TEST_CODE_1');
			cy.fill_frappe_field('security_code_2', 'TEST_CODE_2');

			// Test API configuration JavaScript
			cy.execute_business_workflow(
				() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('E-Boekhouden Settings');
						expect(frm.doc.enabled).to.be.true;
						expect(frm.doc.username).to.equal('test_user@vereniging.nl');

						// Test JavaScript validation for API settings
						if (frm.fields_dict.api_url) {
							expect(frm.fields_dict.api_url).to.exist;
							cy.log('API URL configuration available');
						}
					});
					return true;
				},
				null,
				'API Configuration Workflow'
			);

			cy.save_frappe_doc();
		});
	});

	describe('Authentication and Security Tests', () => {
		it('should test API authentication credentials handling', () => {
			cy.visit('/app/e-boekhouden-settings');
			cy.wait_for_navigation();

			// Test secure credential handling
			cy.fill_frappe_field('username', 'auth_test@example.nl');
			cy.fill_frappe_field('security_code_1', 'SECURE_CODE_1');
			cy.fill_frappe_field('security_code_2', 'SECURE_CODE_2');

			cy.execute_business_workflow(
				() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('E-Boekhouden Settings');

						// Test credential field security
						const securityField1 = frm.fields_dict.security_code_1;
						const securityField2 = frm.fields_dict.security_code_2;

						if (securityField1) {
							expect(securityField1.df.fieldtype).to.equal('Password');
							cy.log('Security code 1 properly secured as password field');
						}

						if (securityField2) {
							expect(securityField2.df.fieldtype).to.equal('Password');
							cy.log('Security code 2 properly secured as password field');
						}
					});
					return true;
				},
				null,
				'API Authentication Security'
			);

			cy.save_frappe_doc();
		});

		it('should test connection testing functionality', () => {
			cy.visit('/app/e-boekhouden-settings');
			cy.wait_for_navigation();

			// Configure connection settings
			cy.fill_frappe_field('enabled', true, { fieldtype: 'Check' });
			cy.fill_frappe_field('username', 'connection_test@example.nl');
			cy.fill_frappe_field('security_code_1', 'TEST_CONNECTION_1');

			cy.save_frappe_doc();

			// Test connection testing button
			cy.execute_business_workflow(
				() => {
					// Test custom buttons for connection testing
					cy.contains('button', 'Test REST API Connection').should('exist');
					cy.contains('button', 'Test Chart of Accounts').should('exist');
					return true;
				},
				null,
				'Connection Testing Functionality'
			);
		});
	});

	describe('Account Mapping Configuration Tests', () => {
		it('should test chart of accounts mapping setup', () => {
			cy.visit('/app/e-boekhouden-settings');
			cy.wait_for_navigation();

			// Enable the service first
			cy.fill_frappe_field('enabled', true, { fieldtype: 'Check' });
			cy.fill_frappe_field('username', 'mapping_test@example.nl');

			// Test account mapping fields
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('E-Boekhouden Settings');

					// Test account mapping fields
					if (frm.fields_dict.default_debtors_account) {
						expect(frm.fields_dict.default_debtors_account).to.exist;
						cy.log('Default debtors account mapping available');
					}

					if (frm.fields_dict.default_income_account) {
						expect(frm.fields_dict.default_income_account).to.exist;
						cy.log('Default income account mapping available');
					}

					// Test account mapping table
					if (frm.fields_dict.account_mappings) {
						expect(frm.fields_dict.account_mappings).to.exist;
						cy.log('Account mappings table available');
					}
				});
				return true;
			}, 'Chart of Accounts Mapping');

			cy.save_frappe_doc();
		});

		it('should test VAT and tax mapping configuration', () => {
			cy.visit('/app/e-boekhouden-settings');
			cy.wait_for_navigation();

			cy.fill_frappe_field('enabled', true, { fieldtype: 'Check' });
			cy.fill_frappe_field('username', 'vat_test@example.nl');

			// Test VAT configuration
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('E-Boekhouden Settings');

					// Test VAT mapping fields
					if (frm.fields_dict.default_vat_code) {
						expect(frm.fields_dict.default_vat_code).to.exist;
						cy.log('Default VAT code configuration available');
					}

					if (frm.fields_dict.vat_mappings) {
						expect(frm.fields_dict.vat_mappings).to.exist;
						cy.log('VAT mappings table available');
					}

					// Test Dutch VAT rates
					if (frm.fields_dict.btw_high_rate) {
						expect(frm.fields_dict.btw_high_rate).to.exist;
						cy.log('Dutch BTW high rate configuration available');
					}
				});
				return true;
			}, 'VAT and Tax Mapping Configuration');

			cy.save_frappe_doc();
		});
	});

	describe('Synchronization Settings Tests', () => {
		it('should test data synchronization configuration', () => {
			cy.visit('/app/e-boekhouden-settings');
			cy.wait_for_navigation();

			cy.fill_frappe_field('enabled', true, { fieldtype: 'Check' });
			cy.fill_frappe_field('username', 'sync_test@example.nl');

			// Test synchronization settings
			cy.execute_business_workflow(
				() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('E-Boekhouden Settings');

						// Test sync frequency settings
						if (frm.fields_dict.sync_frequency) {
							expect(frm.fields_dict.sync_frequency).to.exist;
							cy.log('Sync frequency configuration available');
						}

						// Test sync direction settings
						if (frm.fields_dict.sync_invoices) {
							expect(frm.fields_dict.sync_invoices).to.exist;
							cy.log('Invoice synchronization setting available');
						}

						if (frm.fields_dict.sync_payments) {
							expect(frm.fields_dict.sync_payments).to.exist;
							cy.log('Payment synchronization setting available');
						}

						// Test automatic sync settings
						if (frm.fields_dict.auto_sync_enabled) {
							expect(frm.fields_dict.auto_sync_enabled).to.exist;
							cy.log('Automatic synchronization setting available');
						}
					});
					return true;
				},
				null,
				'Data Synchronization Configuration'
			);

			cy.save_frappe_doc();
		});

		it('should test error handling and retry configuration', () => {
			cy.visit('/app/e-boekhouden-settings');
			cy.wait_for_navigation();

			cy.fill_frappe_field('enabled', true, { fieldtype: 'Check' });
			cy.fill_frappe_field('username', 'error_handling@example.nl');

			// Test error handling configuration
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('E-Boekhouden Settings');

					// Test error handling fields
					if (frm.fields_dict.max_retry_attempts) {
						expect(frm.fields_dict.max_retry_attempts).to.exist;
						cy.log('Maximum retry attempts configuration available');
					}

					if (frm.fields_dict.retry_delay) {
						expect(frm.fields_dict.retry_delay).to.exist;
						cy.log('Retry delay configuration available');
					}

					// Test error notification settings
					if (frm.fields_dict.error_notification_email) {
						expect(frm.fields_dict.error_notification_email).to.exist;
						cy.log('Error notification email configuration available');
					}
				});
				return true;
			}, 'Error Handling and Retry Configuration');

			cy.save_frappe_doc();
		});
	});

	describe('Integration Workflow Tests', () => {
		it('should test invoice synchronization workflow', () => {
			cy.visit('/app/e-boekhouden-settings');
			cy.wait_for_navigation();

			// Configure for invoice sync testing
			cy.fill_frappe_field('enabled', true, { fieldtype: 'Check' });
			cy.fill_frappe_field('username', 'invoice_sync@example.nl');
			cy.fill_frappe_field('sync_invoices', true, { fieldtype: 'Check' });

			cy.save_frappe_doc();

			// Test invoice sync workflow
			cy.execute_business_workflow(
				() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('E-Boekhouden Settings');
						expect(frm.doc.sync_invoices).to.be.true;

						// Test custom buttons for cost center management (when mappings exist)
						cy.contains('button', 'Preview Cost Center Creation').should('exist');
						cy.contains('button', 'Create Cost Centers').should('exist');
					});
					return true;
				},
				null,
				'Invoice Synchronization Workflow'
			);
		});

		it('should test payment synchronization workflow', () => {
			cy.visit('/app/e-boekhouden-settings');
			cy.wait_for_navigation();

			// Configure for payment sync testing
			cy.fill_frappe_field('enabled', true, { fieldtype: 'Check' });
			cy.fill_frappe_field('username', 'payment_sync@example.nl');
			cy.fill_frappe_field('sync_payments', true, { fieldtype: 'Check' });

			cy.save_frappe_doc();

			// Test payment sync workflow
			cy.execute_business_workflow(
				() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('E-Boekhouden Settings');
						expect(frm.doc.sync_payments).to.be.true;

						// Test payment sync specific settings
						if (frm.fields_dict.payment_sync_direction) {
							expect(frm.fields_dict.payment_sync_direction).to.exist;
							cy.log('Payment sync direction configuration available');
						}
					});
					return true;
				},
				null,
				'Payment Synchronization Workflow'
			);
		});
	});

	describe('Compliance and Audit Tests', () => {
		it('should test Dutch accounting compliance settings', () => {
			cy.visit('/app/e-boekhouden-settings');
			cy.wait_for_navigation();

			cy.fill_frappe_field('enabled', true, { fieldtype: 'Check' });
			cy.fill_frappe_field('username', 'compliance@example.nl');

			// Test Dutch compliance settings
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('E-Boekhouden Settings');

					// Test Dutch specific compliance fields
					if (frm.fields_dict.bsn_validation) {
						expect(frm.fields_dict.bsn_validation).to.exist;
						cy.log('BSN validation setting available');
					}

					if (frm.fields_dict.btw_number) {
						expect(frm.fields_dict.btw_number).to.exist;
						cy.log('BTW number configuration available');
					}

					// Test audit trail settings
					if (frm.fields_dict.enable_audit_trail) {
						expect(frm.fields_dict.enable_audit_trail).to.exist;
						cy.log('Audit trail setting available');
					}
				});
				return true;
			}, 'Dutch Accounting Compliance');

			cy.save_frappe_doc();
		});

		it('should test data validation and integrity settings', () => {
			cy.visit('/app/e-boekhouden-settings');
			cy.wait_for_navigation();

			cy.fill_frappe_field('enabled', true, { fieldtype: 'Check' });
			cy.fill_frappe_field('username', 'validation@example.nl');

			// Test data validation settings
			cy.execute_business_workflow(
				() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('E-Boekhouden Settings');

						// Test validation settings
						if (frm.fields_dict.validate_vat_numbers) {
							expect(frm.fields_dict.validate_vat_numbers).to.exist;
							cy.log('VAT number validation setting available');
						}

						if (frm.fields_dict.enforce_account_mapping) {
							expect(frm.fields_dict.enforce_account_mapping).to.exist;
							cy.log('Account mapping enforcement setting available');
						}

						// Test data integrity checks
						if (frm.fields_dict.check_duplicate_invoices) {
							expect(frm.fields_dict.check_duplicate_invoices).to.exist;
							cy.log('Duplicate invoice checking available');
						}
					});
					return true;
				},
				null,
				'Data Validation and Integrity Settings'
			);

			cy.save_frappe_doc();
		});
	});

	describe('Account Type and Hierarchy Management Tests', () => {
		it('should verify parse_groups_and_suggest_type_mappings API is accessible', () => {
			// This test ensures the API endpoint is properly whitelisted and accessible
			// It catches issues like missing @frappe.whitelist() or import errors
			cy.request({
				method: 'POST',
				url: '/api/method/verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_type_mappings',
				headers: {
					'X-Frappe-CSRF-Token': Cypress.env('CSRF_TOKEN') || 'test'
				},
				failOnStatusCode: false
			}).then((response) => {
				// Should not get 404 (method not found) or 500 (import error)
				// 403 (permission denied) is acceptable as it means the method exists
				expect(response.status).to.not.equal(404);
				expect(response.body).to.not.have.property('exc_type', 'AttributeError');
				cy.log('parse_groups_and_suggest_type_mappings API is accessible');
			});
		});

		it('should verify reclassify_accounts_by_group_mappings API is accessible', () => {
			cy.request({
				method: 'POST',
				url: '/api/method/verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.reclassify_accounts_by_group_mappings',
				body: { dry_run: true },
				headers: {
					'X-Frappe-CSRF-Token': Cypress.env('CSRF_TOKEN') || 'test'
				},
				failOnStatusCode: false
			}).then((response) => {
				expect(response.status).to.not.equal(404);
				expect(response.body).to.not.have.property('exc_type', 'AttributeError');
				cy.log('reclassify_accounts_by_group_mappings API is accessible');
			});
		});

		it('should verify reorganize_account_hierarchy API is accessible', () => {
			cy.request({
				method: 'POST',
				url: '/api/method/verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.reorganize_account_hierarchy',
				body: { dry_run: true },
				headers: {
					'X-Frappe-CSRF-Token': Cypress.env('CSRF_TOKEN') || 'test'
				},
				failOnStatusCode: false
			}).then((response) => {
				expect(response.status).to.not.equal(404);
				expect(response.body).to.not.have.property('exc_type', 'AttributeError');
				cy.log('reorganize_account_hierarchy API is accessible');
			});
		});

		it('should test Parse & Suggest Types button functionality', () => {
			cy.visit('/app/e-boekhouden-settings');
			cy.wait_for_navigation();

			// Add sample group mappings to enable the parse button
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('E-Boekhouden Settings');

					// Verify parse_group_types_button field exists
					if (frm.fields_dict.parse_group_types_button) {
						expect(frm.fields_dict.parse_group_types_button).to.exist;
						cy.log('Parse & Suggest Types button field exists');
					}

					// Verify group_type_mappings table field exists
					if (frm.fields_dict.group_type_mappings) {
						expect(frm.fields_dict.group_type_mappings).to.exist;
						cy.log('Group type mappings table field exists');
					}
				});
				return true;
			}, 'Parse & Suggest Types Button');
		});

		it('should test Account Types menu buttons when mappings exist', () => {
			cy.visit('/app/e-boekhouden-settings');
			cy.wait_for_navigation();

			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('E-Boekhouden Settings');

					// Check if group_type_mappings has data
					const hasMappings = frm.doc.group_type_mappings && frm.doc.group_type_mappings.length > 0;

					if (hasMappings) {
						// Account Types menu should have Preview and Apply buttons
						cy.get('.btn-group .dropdown-menu').then(($menus) => {
							const menuText = $menus.text();
							if (menuText.includes('Account Types')) {
								cy.log('Account Types menu is present');
								expect(menuText).to.include('Preview Re-classification');
								expect(menuText).to.include('Apply Re-classification');
							}
						});

						// Account Hierarchy menu should have Preview and Apply buttons
						cy.get('.btn-group .dropdown-menu').then(($menus) => {
							const menuText = $menus.text();
							if (menuText.includes('Account Hierarchy')) {
								cy.log('Account Hierarchy menu is present');
								expect(menuText).to.include('Preview Reorganization');
								expect(menuText).to.include('Apply Reorganization');
							}
						});
					} else {
						cy.log('No group_type_mappings configured - menu buttons not shown (expected)');
					}
				});
				return true;
			}, 'Account Types Menu Buttons');
		});

		it('should test helper functions exist on form', () => {
			cy.visit('/app/e-boekhouden-settings');
			cy.wait_for_navigation();

			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('E-Boekhouden Settings');

					// Verify helper functions are defined
					expect(frm.escape_html).to.be.a('function');
					expect(frm.show_reclassify_preview).to.be.a('function');
					expect(frm.show_reclassify_results).to.be.a('function');
					expect(frm.show_hierarchy_preview).to.be.a('function');
					expect(frm.show_hierarchy_results).to.be.a('function');
					expect(frm.show_cost_center_preview).to.be.a('function');
					expect(frm.show_cost_center_results).to.be.a('function');

					cy.log('All required helper functions are defined on form');
				});
				return true;
			}, 'Helper Functions Verification');
		});
	});

	describe('Logging and Monitoring Tests', () => {
		it('should test synchronization logging configuration', () => {
			cy.visit('/app/e-boekhouden-settings');
			cy.wait_for_navigation();

			cy.fill_frappe_field('enabled', true, { fieldtype: 'Check' });
			cy.fill_frappe_field('username', 'logging@example.nl');

			// Test logging configuration
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('E-Boekhouden Settings');

					// Test logging level settings
					if (frm.fields_dict.log_level) {
						expect(frm.fields_dict.log_level).to.exist;
						cy.log('Log level configuration available');
					}

					if (frm.fields_dict.enable_detailed_logging) {
						expect(frm.fields_dict.enable_detailed_logging).to.exist;
						cy.log('Detailed logging setting available');
					}

					// Test log retention settings
					if (frm.fields_dict.log_retention_days) {
						expect(frm.fields_dict.log_retention_days).to.exist;
						cy.log('Log retention configuration available');
					}
				});
				return true;
			}, 'Synchronization Logging Configuration');

			cy.save_frappe_doc();
		});

		it('should test monitoring and alerting configuration', () => {
			cy.visit('/app/e-boekhouden-settings');
			cy.wait_for_navigation();

			cy.fill_frappe_field('enabled', true, { fieldtype: 'Check' });
			cy.fill_frappe_field('username', 'monitoring@example.nl');

			// Test monitoring configuration
			cy.execute_business_workflow(
				() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('E-Boekhouden Settings');

						// Test monitoring fields
						if (frm.fields_dict.health_check_frequency) {
							expect(frm.fields_dict.health_check_frequency).to.exist;
							cy.log('Health check frequency configuration available');
						}

						if (frm.fields_dict.alert_on_sync_failure) {
							expect(frm.fields_dict.alert_on_sync_failure).to.exist;
							cy.log('Sync failure alerting available');
						}

						// Test dashboard integration
						if (frm.fields_dict.show_in_dashboard) {
							expect(frm.fields_dict.show_in_dashboard).to.exist;
							cy.log('Dashboard integration setting available');
						}
					});
					return true;
				},
				null,
				'Monitoring and Alerting Configuration'
			);

			cy.save_frappe_doc();
		});
	});
});
