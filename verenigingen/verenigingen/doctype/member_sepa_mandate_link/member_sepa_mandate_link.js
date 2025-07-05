// Copyright (c) 2025, Your Name and contributors
// For license information, please see license.txt

frappe.ui.form.on('Member SEPA Mandate Link', {
    sepa_mandate: function(frm, cdt, cdn) {
        // When a mandate is selected, fetch its details
        const row = locals[cdt][cdn];

        if (row.sepa_mandate) {
            frappe.db.get_value('SEPA Mandate', row.sepa_mandate,
                ['mandate_id', 'status', 'sign_date', 'expiry_date'],
                function(r) {
                    if (r) {
                        frappe.model.set_value(cdt, cdn, 'mandate_reference', r.mandate_id);
                        frappe.model.set_value(cdt, cdn, 'status', r.status);
                        frappe.model.set_value(cdt, cdn, 'valid_from', r.sign_date);
                        frappe.model.set_value(cdt, cdn, 'valid_until', r.expiry_date);
                    }
                }
            );
        }
    },

    is_current: function(frm, cdt, cdn) {
        // When setting a mandate as current, unset others
        const row = locals[cdt][cdn];

        if (row.is_current) {
            // Unset current on other mandates
            frm.doc.sepa_mandates.forEach(function(mandate) {
                if (mandate.name !== cdn && mandate.is_current) {
                    frappe.model.set_value(mandate.doctype, mandate.name, 'is_current', 0);
                }
            });
        }
    }
});
