// Copyright (c) 2024, Verenigingen and contributors
// For license information, please see license.txt

frappe.ui.form.on("Verenigingen Payments Settings", {
	refresh: function (frm) {
		// Disable browser autocomplete on webhook_user field to prevent
		// Firefox from autofilling with website login credentials
		const webhookUserField = frm.fields_dict.webhook_user;
		if (webhookUserField && webhookUserField.$input) {
			webhookUserField.$input.attr("autocomplete", "off");
		}
	},
});
