// Copyright (c) 2025, R.S.P. and contributors
// For license information, please see license.txt

frappe.ui.form.on('E-Boekhouden Settings', {
	refresh: function(frm) {
		// Add custom buttons for testing
		frm.add_custom_button(__('Test Connection'), function() {
			if (!frm.doc.api_token) {
				frappe.msgprint(__('Please enter your API token first.'));
				return;
			}

			frappe.call({
				method: 'verenigingen.verenigingen.doctype.e_boekhouden_settings.e_boekhouden_settings.test_connection',
				callback: function(r) {
					if (r.message && r.message.success) {
						frappe.show_alert({
							message: __('Connection test successful!'),
							indicator: 'green'
						});
					} else {
						frappe.show_alert({
							message: __('Connection test failed. Check your API token.'),
							indicator: 'red'
						});
					}
					frm.reload_doc();
				}
			});
		}).addClass('btn-primary');

		// Add SOAP connection test button
		frm.add_custom_button(__('Test SOAP Connection'), function() {
			if (!frm.doc.soap_username) {
				frappe.msgprint(__('Please enter SOAP credentials first.'));
				return;
			}

			// Save the form first to ensure passwords are stored
			frm.save().then(() => {
				frappe.call({
					method: 'verenigingen.utils.eboekhouden_soap_api.test_connection',
					callback: function(r) {
						if (r.message && r.message.success) {
							frappe.show_alert({
								message: __('SOAP connection test successful!'),
								indicator: 'green'
							});
						} else {
							frappe.show_alert({
								message: __('SOAP connection test failed: ' + (r.message.error || 'Unknown error')),
								indicator: 'red'
							});
						}
					}
				});
			});
		});

		// Add test API call buttons
		if (frm.doc.connection_status && frm.doc.connection_status.includes('✅')) {
			frm.add_custom_button(__('Test Chart of Accounts'), function() {
				frappe.call({
					method: 'verenigingen.utils.eboekhouden_api.preview_chart_of_accounts',
					callback: function(r) {
						if (r.message && r.message.success) {
							let dialog = new frappe.ui.Dialog({
								title: 'Chart of Accounts Preview',
								fields: [{
									fieldtype: 'HTML',
									options: `<div class="text-muted">
										<h5>Found ${r.message.total_count} accounts:</h5>
										<pre style="max-height: 400px; overflow-y: auto; background: #f8f9fa; padding: 10px; border-radius: 3px;">${JSON.stringify(r.message.accounts, null, 2)}</pre>
									</div>`
								}],
								primary_action_label: 'Close',
								primary_action: function() { dialog.hide(); }
							});
							dialog.show();
						} else {
							frappe.msgprint({
								title: 'API Test Failed',
								message: r.message.error || 'Unknown error occurred',
								indicator: 'red'
							});
						}
					}
				});
			});

			frm.add_custom_button(__('Test Customers'), function() {
				frappe.call({
					method: 'verenigingen.utils.eboekhouden_api.preview_customers',
					callback: function(r) {
						if (r.message && r.message.success) {
							let dialog = new frappe.ui.Dialog({
								title: 'Customers Preview',
								fields: [{
									fieldtype: 'HTML',
									options: `<div class="text-muted">
										<h5>Found ${r.message.total_count} customers:</h5>
										<pre style="max-height: 400px; overflow-y: auto; background: #f8f9fa; padding: 10px; border-radius: 3px;">${JSON.stringify(r.message.customers, null, 2)}</pre>
									</div>`
								}],
								primary_action_label: 'Close',
								primary_action: function() { dialog.hide(); }
							});
							dialog.show();
						} else {
							frappe.msgprint({
								title: 'Customers Test Failed',
								message: r.message.error || 'Unknown error occurred',
								indicator: 'red'
							});
						}
					}
				});
			});

			frm.add_custom_button(__('Test Suppliers'), function() {
				frappe.call({
					method: 'verenigingen.utils.eboekhouden_api.preview_suppliers',
					callback: function(r) {
						if (r.message && r.message.success) {
							let dialog = new frappe.ui.Dialog({
								title: 'Suppliers Preview',
								fields: [{
									fieldtype: 'HTML',
									options: `<div class="text-muted">
										<h5>Found ${r.message.total_count} suppliers:</h5>
										<pre style="max-height: 400px; overflow-y: auto; background: #f8f9fa; padding: 10px; border-radius: 3px;">${JSON.stringify(r.message.suppliers, null, 2)}</pre>
									</div>`
								}],
								primary_action_label: 'Close',
								primary_action: function() { dialog.hide(); }
							});
							dialog.show();
						} else {
							frappe.msgprint({
								title: 'Suppliers Test Failed',
								message: r.message.error || 'Unknown error occurred',
								indicator: 'red'
							});
						}
					}
				});
			});

			frm.add_custom_button(__('Test Migrations'), function() {
				// Create submenu for different migration tests
				let migration_menu = [
					{
						label: __('Chart of Accounts'),
						action: function() {
							frappe.call({
								method: 'verenigingen.utils.eboekhouden_api.test_chart_of_accounts_migration',
								callback: function(r) {
									frm.show_migration_test_results(r, 'Chart of Accounts');
								}
							});
						}
					},
					{
						label: __('Cost Centers'),
						action: function() {
							frappe.call({
								method: 'verenigingen.utils.eboekhouden_api.test_cost_center_migration',
								callback: function(r) {
									frm.show_migration_test_results(r, 'Cost Centers');
								}
							});
						}
					},
					{
						label: __('Customers'),
						action: function() {
							frappe.call({
								method: 'verenigingen.utils.eboekhouden_api.test_customer_migration',
								callback: function(r) {
									frm.show_migration_test_results(r, 'Customers');
								}
							});
						}
					},
					{
						label: __('Suppliers'),
						action: function() {
							frappe.call({
								method: 'verenigingen.utils.eboekhouden_api.test_supplier_migration',
								callback: function(r) {
									frm.show_migration_test_results(r, 'Suppliers');
								}
							});
						}
					}
				];

				// Show menu
				let d = new frappe.ui.Dialog({
					title: 'Choose Migration Test',
					fields: [{
						fieldtype: 'HTML',
						options: migration_menu.map(item =>
							`<p><a href="#" onclick="cur_dialog.hide(); (${item.action.toString()})();">${item.label}</a></p>`
						).join('')
					}]
				});
				d.show();
			});
		}

		// Helper function for showing migration test results
		frm.show_migration_test_results = function(r, type) {
			if (r.message && r.message.success) {
				frappe.msgprint({
					title: `${type} Migration Test Results`,
					message: `
						<div>
							<p><strong>Result:</strong> ${r.message.result}</p>
							<p><strong>Total Records:</strong> ${r.message.total_records}</p>
							<p><strong>Would Import:</strong> ${r.message.imported_records}</p>
							<p><strong>Failures:</strong> ${r.message.failed_records}</p>
						</div>
					`,
					indicator: 'blue'
				});
			} else {
				frappe.msgprint({
					title: `${type} Migration Test Failed`,
					message: r.message.error || 'Unknown error occurred',
					indicator: 'red'
				});
			}
		};
	},

	default_company: function(frm) {
		// Auto-set cost center when company changes
		if (frm.doc.default_company) {
			frappe.db.get_value('Cost Center',
				{'company': frm.doc.default_company, 'is_group': 0},
				'name'
			).then(r => {
				if (r.message && r.message.name) {
					frm.set_value('default_cost_center', r.message.name);
				}
			});
		}
	}
});

// Add help text
frappe.ui.form.on('E-Boekhouden Settings', 'onload', function(frm) {
	frm.set_intro(__('Configure your e-Boekhouden API token to enable data migration to ERPNext. You can find your API token in your e-Boekhouden account settings under "API Access" or "Integrations".'));
});
