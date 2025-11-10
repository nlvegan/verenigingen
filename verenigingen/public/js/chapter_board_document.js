// Copyright (c) 2025, Veganisme.org and contributors
// For license information, please see license.txt

frappe.ui.form.on('Chapter', {
    refresh: function(frm) {
        // Load dynamic document category options for board_documents table
        frappe.call({
            method: 'verenigingen.utils.document_categories.get_document_category_options',
            callback: function(r) {
                if (r.message) {
                    // Update the options for document_type field in the child table
                    frm.fields_dict.board_documents.grid.update_docfield_property(
                        'document_type',
                        'options',
                        r.message
                    );
                }
            }
        });
    }
});
