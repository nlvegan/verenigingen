// Copyright (c) 2025, Vegan Netwerk Nederland and contributors
// For license information, please see license.txt

frappe.ui.form.on("Ponto Settings", {
	refresh: function (frm) {
		// Guard against undefined doc (can happen during singleton initialization)
		if (!frm.doc) {
			return;
		}

		// Add custom button for fetching accounts
		if (!frm.is_new()) {
			frm.add_custom_button(__("Test Connection"), function () {
				frm.call({
					method: "test_connection",
					doc: frm.doc,
					freeze: true,
					freeze_message: __("Testing Ponto connection..."),
					callback: function (r) {
						if (r.message) {
							if (r.message.success) {
								frappe.msgprint({
									title: __("Connection Successful"),
									indicator: "green",
									message: __(
										"{0}<br>Accounts found: {1}",
										[r.message.message, r.message.accounts_found]
									),
								});
							} else {
								frappe.msgprint({
									title: __("Connection Failed"),
									indicator: "red",
									message: r.message.message,
								});
							}
						}
					},
				});
			});

			// Update Ibanity authorization status if mTLS is enabled
			if (frm.doc.use_ibanity_mtls) {
				frm.trigger("update_ibanity_authorization_status");
			}
		}
	},

	use_ibanity_mtls: function (frm) {
		// Update authorization status when mTLS is toggled
		if (frm.doc && frm.doc.use_ibanity_mtls) {
			frm.trigger("update_ibanity_authorization_status");
		}
	},

	update_ibanity_authorization_status: function (frm) {
		// Guard: Check if form and field are available
		if (
			!frm.doc ||
			!frm.fields_dict ||
			!frm.fields_dict.ibanity_authorization_status
		) {
			return;
		}

		// Check and display Ibanity authorization status
		frappe.call({
			method:
				"verenigingen.verenigingen_payments.ponto.api.oauth2_callback.check_authorization_status",
			callback: function (r) {
				// Guard: Verify form is still valid when callback fires
				if (
					!frm.doc ||
					!frm.fields_dict ||
					!frm.fields_dict.ibanity_authorization_status ||
					!frm.fields_dict.ibanity_authorization_status.$wrapper
				) {
					return;
				}

				if (r.message) {
					let status_html = "";
					if (r.message.is_authorized) {
						status_html = `
							<div class="alert alert-success" role="alert">
								<strong>${__("Authorized")}</strong> - Ponto Connect is ready for payment initiation.
							</div>
						`;
					} else {
						status_html = `
							<div class="alert alert-warning" role="alert">
								<strong>${__("Not Authorized")}</strong> - Click "Authorize with Ibanity" to enable payment initiation.
							</div>
						`;
					}
					frm.fields_dict.ibanity_authorization_status.$wrapper.html(status_html);
				}
			},
			error: function () {
				// Silently handle errors - the status field will just not be updated
				// This prevents console errors when authorization check fails
			},
		});
	},

	authorize_ibanity_button: function (frm) {
		// Called when the "Authorize with Ibanity" button is clicked
		// Open window immediately to avoid popup blocker, then set location after API call
		let authWindow = window.open("", "_blank");

		frappe.call({
			method:
				"verenigingen.verenigingen_payments.ponto.api.oauth2_callback.get_authorization_url",
			freeze: true,
			freeze_message: __("Generating authorization URL..."),
			callback: function (r) {
				if (r.message && r.message.success) {
					// Navigate the already-opened window to the authorization URL
					authWindow.location.href = r.message.authorization_url;
				} else {
					// Close the blank window on error
					authWindow.close();
					frappe.msgprint({
						title: __("Error"),
						indicator: "red",
						message: r.message ? r.message.error : __("Failed to get authorization URL"),
					});
				}
			},
			error: function () {
				// Close the blank window on error
				authWindow.close();
				frappe.msgprint({
					title: __("Error"),
					indicator: "red",
					message: __("Failed to connect to server"),
				});
			},
		});
	},

	fetch_accounts_button: function (frm) {
		// Called when the "Fetch Accounts from Ponto" button is clicked
		frm.call({
			method: "fetch_ponto_accounts",
			doc: frm.doc,
			freeze: true,
			freeze_message: __("Fetching accounts from Ponto..."),
			callback: function (r) {
				if (r.message && r.message.success && frm.doc) {
					// Reload the form to show the new mappings
					frm.reload_doc();
				}
			},
		});
	},

	trigger_sync_button: function (frm) {
		// Called when the "Import Transactions" button is clicked
		frm.call({
			method: "trigger_manual_sync",
			doc: frm.doc,
			freeze: true,
			freeze_message: __("Importing transactions from Ponto..."),
			callback: function (r) {
				if (r.message && r.message.success && frm.doc) {
					// Reload the form to show updated last_sync_time
					frm.reload_doc();
				}
			},
		});
	},

	refresh_status_button: function (frm) {
		// Called when the "Refresh Status from Ponto" button is clicked
		frm.call({
			method: "refresh_user_info",
			doc: frm.doc,
			freeze: true,
			freeze_message: __("Fetching status from Ponto..."),
			callback: function (r) {
				if (r.message && r.message.success && frm.doc) {
					// Reload the form to show updated activation status
					frm.reload_doc();
				}
			},
		});
	},

	sandbox_mode: function (frm) {
		// Clear token cache when switching environments
		// The form will show/hide the appropriate credential sections automatically
		if (frm.doc) {
			frm.trigger("refresh");
		}
	},
});

// Child table events for Ponto Bank Account Mapping
frappe.ui.form.on("Ponto Bank Account Mapping", {
	bank_account: function (frm, cdt, cdn) {
		// When a bank account is selected, mark the form as dirty
		frm.dirty();
	},

	enabled: function (frm, cdt, cdn) {
		// When enabled/disabled changes, mark the form as dirty
		frm.dirty();
	},
});
