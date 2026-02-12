// Copyright (c) 2025, Veganisme.org and contributors
// For license information, please see license.txt

frappe.ui.form.on('Organization Document', {
	setup(frm) {
		// Load document categories from Settings (single source of truth)
		frappe.call({
			method: 'verenigingen.utils.document_categories.get_document_category_options',
			callback(r) {
				if (r.message) {
					frm.set_df_property('document_type', 'options', r.message);
				}
			}
		});
	}
});
