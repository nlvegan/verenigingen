// Email Configuration form script
frappe.ui.form.on("Email Configuration", {
	refresh: function (frm) {
		// Add status indicator based on email mode
		if (!frm.doc.master_email_enabled) {
			frm.page.set_indicator(__("Emails Disabled"), "red");
		} else if (frm.doc.email_mode === "Paused") {
			frm.page.set_indicator(__("Emails Paused"), "orange");
		} else {
			frm.page.set_indicator(__("Emails Active"), "green");
		}

		// Add quick action buttons
		if (frm.doc.master_email_enabled && frm.doc.email_mode === "Active") {
			frm.add_custom_button(
				__("Pause All Emails"),
				function () {
					frappe.prompt(
						[
							{
								label: __("Pause Until"),
								fieldname: "pause_until",
								fieldtype: "Datetime",
								reqd: 1,
								default: frappe.datetime.add_days(frappe.datetime.now_datetime(), 1),
							},
							{
								label: __("Reason"),
								fieldname: "reason",
								fieldtype: "Small Text",
							},
						],
						function (values) {
							frm.set_value("email_mode", "Paused");
							frm.set_value("pause_until", values.pause_until);
							frm.set_value("pause_reason", values.reason);
							frm.save();
						},
						__("Pause Email Notifications"),
						__("Pause")
					);
				},
				__("Actions")
			);
		} else if (frm.doc.email_mode === "Paused") {
			frm.add_custom_button(
				__("Resume Emails Now"),
				function () {
					frm.set_value("email_mode", "Active");
					frm.set_value("pause_until", null);
					frm.set_value("pause_reason", null);
					frm.save();
				},
				__("Actions")
			);
		}

		// Add button to enable all notifications
		frm.add_custom_button(
			__("Enable All"),
			function () {
				frm.doc.notification_types.forEach(function (row) {
					frappe.model.set_value(row.doctype, row.name, "enabled", 1);
				});
				frm.refresh_field("notification_types");
				frappe.show_alert({ message: __("All notifications enabled"), indicator: "green" });
			},
			__("Notification Types")
		);

		// Add button to disable all notifications
		frm.add_custom_button(
			__("Disable All"),
			function () {
				frappe.confirm(__("Are you sure you want to disable all notification types?"), function () {
					frm.doc.notification_types.forEach(function (row) {
						frappe.model.set_value(row.doctype, row.name, "enabled", 0);
					});
					frm.refresh_field("notification_types");
					frappe.show_alert({ message: __("All notifications disabled"), indicator: "orange" });
				});
			},
			__("Notification Types")
		);

		// Add Test Email button
		frm.add_custom_button(
			__("Send Test Email"),
			function () {
				frappe.prompt(
					[
						{
							label: __("Recipient Email"),
							fieldname: "recipient",
							fieldtype: "Data",
							options: "Email",
							reqd: 1,
							default: frappe.session.user,
						},
					],
					function (values) {
						frappe.call({
							method: "verenigingen.verenigingen.doctype.email_configuration.email_configuration.send_test_email",
							args: { recipient: values.recipient },
							freeze: true,
							freeze_message: __("Sending test email..."),
							callback: function (r) {
								if (r.message && r.message.success) {
									frappe.show_alert({
										message: __("Test email queued for {0}", [values.recipient]),
										indicator: "green",
									});
								} else {
									frappe.msgprint({
										title: __("Test Email Failed"),
										message: r.message ? r.message.error : __("Unknown error"),
										indicator: "red",
									});
								}
							},
						});
					},
					__("Send Test Email"),
					__("Send")
				);
			},
			__("Actions")
		);

		// Add Sync Notification Registry button
		frm.add_custom_button(
			__("Sync Registry"),
			function () {
				frappe.call({
					method: "verenigingen.verenigingen.doctype.email_configuration.email_configuration.discover_notification_keys",
					freeze: true,
					freeze_message: __("Scanning codebase for notification keys..."),
					callback: function (r) {
						if (r.message) {
							show_sync_dialog(frm, r.message);
						}
					},
				});
			},
			__("Actions")
		);

		// Add category filter buttons
		frm.add_custom_button(
			__("Show All"),
			function () {
				frm.fields_dict.notification_types.grid.filter = null;
				frm.fields_dict.notification_types.grid.refresh();
				frappe.show_alert({ message: __("Showing all notification types"), indicator: "blue" });
			},
			__("Filter by Category")
		);

		const categories = ["Member", "Chapter", "Payment", "Admin", "System", "Volunteer"];
		categories.forEach(function (category) {
			frm.add_custom_button(
				__(category),
				function () {
					// Filter the child table by category
					frm.fields_dict.notification_types.grid.filter = [["category", "=", category]];
					frm.fields_dict.notification_types.grid.refresh();
					frappe.show_alert({
						message: __("Showing {0} notifications", [category]),
						indicator: "blue",
					});
				},
				__("Filter by Category")
			);
		});
	},

	master_email_enabled: function (frm) {
		if (!frm.doc.master_email_enabled) {
			frappe.show_alert({
				message: __("All email notifications are now disabled"),
				indicator: "red",
			});
		}
	},

	email_mode: function (frm) {
		if (frm.doc.email_mode === "Active") {
			frm.set_value("pause_until", null);
			frm.set_value("pause_reason", null);
		}
	},
});

// Child table script for notification types
frappe.ui.form.on("Email Notification Type", {
	notification_types_add: function (frm, cdt, cdn) {
		// Set sensible defaults for new rows
		frappe.model.set_value(cdt, cdn, "enabled", 1);
		frappe.model.set_value(cdt, cdn, "priority", "Medium");
		frappe.model.set_value(cdt, cdn, "cooldown_minutes", 60);
		frappe.model.set_value(cdt, cdn, "recipient_policy", "Document-Field");
	},

	recipient_policy: function (frm, cdt, cdn) {
		// Clear irrelevant fields when policy changes
		const row = locals[cdt][cdn];
		if (row.recipient_policy !== "Fixed") {
			frappe.model.set_value(cdt, cdn, "fixed_recipients", null);
		}
		if (row.recipient_policy !== "Role-Based") {
			frappe.model.set_value(cdt, cdn, "recipient_roles", null);
		}
		if (row.recipient_policy !== "Document-Field") {
			frappe.model.set_value(cdt, cdn, "recipient_field", null);
		}
	},
});

/**
 * Show sync dialog with discovered notification keys
 */
function show_sync_dialog(frm, data) {
	const summary = data.summary;
	const new_keys = data.new_keys || [];
	const orphaned_keys = data.orphaned_keys || [];
	const undocumented_keys = data.undocumented_keys || [];
	const errors = data.errors || [];

	// Build summary HTML
	let summary_html = `
		<div class="sync-summary" style="margin-bottom: 15px;">
			<div class="row">
				<div class="col-sm-3 text-center">
					<div style="font-size: 24px; font-weight: bold;">${summary.total_discovered}</div>
					<div class="text-muted">${__("In Codebase")}</div>
				</div>
				<div class="col-sm-3 text-center">
					<div style="font-size: 24px; font-weight: bold;">${summary.total_configured}</div>
					<div class="text-muted">${__("Configured")}</div>
				</div>
				<div class="col-sm-3 text-center">
					<div style="font-size: 24px; font-weight: bold; color: var(--green);">${summary.new_count}</div>
					<div class="text-muted">${__("Not Configured")}</div>
				</div>
				<div class="col-sm-3 text-center">
					<div style="font-size: 24px; font-weight: bold; color: var(--orange);">${summary.orphaned_count}</div>
					<div class="text-muted">${__("Orphaned")}</div>
				</div>
			</div>
		</div>
	`;

	// Build undocumented keys warning if any
	let undocumented_html = "";
	if (undocumented_keys.length > 0) {
		undocumented_html = `
			<div class="alert alert-info" style="margin-bottom: 15px;">
				<strong><i class="fa fa-info-circle"></i> ${__("Undocumented Keys")}</strong>
				<p class="mb-1 small">${__(
					"These {0} keys are used in code but not documented in notification_registry.py. Consider adding descriptions.",
					[undocumented_keys.length]
				)}</p>
				<div style="max-height: 80px; overflow-y: auto;">
					<code class="small">${undocumented_keys.join(", ")}</code>
				</div>
			</div>
		`;
	}

	// Build new keys table if any
	let new_keys_html = "";
	if (new_keys.length > 0) {
		new_keys_html = `
			<div class="new-keys-section" style="margin-bottom: 15px;">
				<h5>${__("New Notification Keys")} <span class="badge badge-success">${new_keys.length}</span></h5>
				<p class="text-muted small">${__("These keys are used in code but not configured. Select which ones to add.")}</p>
				<div style="max-height: 350px; overflow-y: auto; border: 1px solid var(--border-color); border-radius: 4px;">
					<table class="table table-bordered table-sm" style="margin: 0;">
						<thead style="position: sticky; top: 0; background: var(--bg-color); z-index: 1;">
							<tr>
								<th style="width: 30px;"><input type="checkbox" class="select-all-new" checked></th>
								<th style="width: 180px;">${__("Notification Key")}</th>
								<th style="width: 80px;">${__("Category")}</th>
								<th>${__("Description")}</th>
							</tr>
						</thead>
						<tbody>
							${new_keys
								.map(
									(k, idx) => `
								<tr${!k.in_registry ? ' class="table-warning"' : ""}>
									<td><input type="checkbox" class="new-key-checkbox" data-idx="${idx}" checked></td>
									<td>
										<code class="small">${k.notification_key}</code>
										${!k.in_registry ? '<br><span class="badge badge-warning" style="font-size: 9px;">undocumented</span>' : ""}
									</td>
									<td><span class="badge badge-secondary">${k.category}</span></td>
									<td class="small">${k.description || '<span class="text-muted">No description</span>'}</td>
								</tr>
							`
								)
								.join("")}
						</tbody>
					</table>
				</div>
			</div>
		`;
	}

	// Build orphaned keys section if any
	let orphaned_html = "";
	if (orphaned_keys.length > 0) {
		orphaned_html = `
			<div class="orphaned-keys-section" style="margin-bottom: 15px;">
				<h5>${__("Orphaned Configuration Entries")} <span class="badge badge-warning">${orphaned_keys.length}</span></h5>
				<p class="text-muted small">${__("These keys are configured but not found in code. They may be obsolete and can be manually removed.")}</p>
				<div style="max-height: 120px; overflow-y: auto;">
					<ul class="list-unstyled mb-0">
						${orphaned_keys.map((k) => `<li><code>${k}</code></li>`).join("")}
					</ul>
				</div>
			</div>
		`;
	}

	// Build errors section if any
	let errors_html = "";
	if (errors.length > 0) {
		errors_html = `
			<div class="alert alert-danger" style="margin-bottom: 15px;">
				<strong>${__("Errors:")}</strong>
				<ul class="mb-0">${errors.map((e) => `<li>${e}</li>`).join("")}</ul>
			</div>
		`;
	}

	// All synced message
	let all_synced_html = "";
	if (new_keys.length === 0 && orphaned_keys.length === 0) {
		all_synced_html = `
			<div class="alert alert-success" style="margin-bottom: 15px;">
				<i class="fa fa-check-circle"></i> ${__("Configuration is fully synchronized with the codebase.")}
			</div>
		`;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Sync Notification Registry"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "content",
				options:
					summary_html + errors_html + undocumented_html + all_synced_html + new_keys_html + orphaned_html,
			},
		],
		primary_action_label: new_keys.length > 0 ? __("Add Selected ({0})", [new_keys.length]) : __("Close"),
		primary_action: function () {
			if (new_keys.length === 0) {
				dialog.hide();
				return;
			}

			// Get selected keys
			const selected = [];
			dialog.$wrapper.find(".new-key-checkbox:checked").each(function () {
				const idx = $(this).data("idx");
				selected.push(new_keys[idx]);
			});

			if (selected.length === 0) {
				frappe.show_alert({ message: __("No keys selected"), indicator: "orange" });
				return;
			}

			// Add selected notification types
			frappe.call({
				method: "verenigingen.verenigingen.doctype.email_configuration.email_configuration.add_notification_types",
				args: { notification_types: JSON.stringify(selected) },
				freeze: true,
				freeze_message: __("Adding notification types..."),
				callback: function (r) {
					if (r.message && r.message.success) {
						frappe.show_alert({
							message: __("Added {0} notification type(s)", [r.message.added]),
							indicator: "green",
						});
						dialog.hide();
						frm.reload_doc();
					} else {
						frappe.msgprint({
							title: __("Error"),
							message: r.message ? r.message.error : __("Unknown error"),
							indicator: "red",
						});
					}
				},
			});
		},
		secondary_action_label: __("Cancel"),
		secondary_action: function () {
			dialog.hide();
		},
	});

	// Handle select all checkbox
	dialog.$wrapper.find(".select-all-new").on("change", function () {
		const checked = $(this).prop("checked");
		dialog.$wrapper.find(".new-key-checkbox").prop("checked", checked);
		update_button_count();
	});

	// Update button count when individual checkboxes change
	dialog.$wrapper.find(".new-key-checkbox").on("change", function () {
		update_button_count();
	});

	function update_button_count() {
		const count = dialog.$wrapper.find(".new-key-checkbox:checked").length;
		dialog.set_primary_action_label(count > 0 ? __("Add Selected ({0})", [count]) : __("Close"));
	}

	dialog.show();
}
