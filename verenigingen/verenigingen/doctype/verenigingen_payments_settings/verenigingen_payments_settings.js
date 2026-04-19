// Copyright (c) 2024, Verenigingen and contributors
// For license information, please see license.txt

frappe.ui.form.on("Verenigingen Payments Settings", {
	refresh: function (frm) {
		verenigingen.suppressPasswordAutofill(frm, [
			"membership_webhook_secret",
			"ing_checkout_webhook_secret",
		]);

		// Also suppress autofill on webhook_user (a plain Data field that
		// gets caught by browsers' "looks like a login form" heuristics).
		const webhookUserField = frm.fields_dict.webhook_user;
		if (webhookUserField && webhookUserField.$input) {
			webhookUserField.$input.attr({
				autocomplete: "new-password",
				"data-lpignore": "true",
				"data-1p-ignore": "true",
				"data-form-type": "other",
			});
		}
	},
});
