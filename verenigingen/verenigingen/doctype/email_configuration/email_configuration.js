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
