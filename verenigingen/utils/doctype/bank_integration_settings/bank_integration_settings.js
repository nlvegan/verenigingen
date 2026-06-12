// Copyright (c) 2026, Vegan Netwerk Nederland and contributors
// For license information, please see license.txt

frappe.ui.form.on('Bank Integration Settings', {
	refresh(frm) {
		verenigingen.suppressPasswordAutofill(frm, ['access_token', 'client_secret']);
	}
});
