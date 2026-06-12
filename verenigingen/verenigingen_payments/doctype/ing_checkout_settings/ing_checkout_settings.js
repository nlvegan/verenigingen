// Copyright (c) 2026, Vegan Netwerk Nederland and contributors
// For license information, please see license.txt

frappe.ui.form.on('ING Checkout Settings', {
	refresh(frm) {
		verenigingen.suppressPasswordAutofill(frm, ['api_token']);
	}
});
