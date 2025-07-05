// Copyright (c) 2025, Your Organization and contributors
// For license information, please see license.txt

frappe.ui.form.on('Volunteer Interest Category', {
    refresh: function(frm) {
        // Add button to view related volunteers
        if (!frm.is_new()) {
            frm.add_custom_button(__('View Volunteers'), function() {
                frappe.route_options = {
                    'interests': frm.doc.name
                };
                frappe.set_route('List', 'Volunteer');
            });
        }
    },

    parent_category: function(frm) {
        // Prevent setting self as parent
        if (frm.doc.parent_category === frm.doc.name) {
            frappe.msgprint(__("You cannot set a category as its own parent"));
            frm.set_value('parent_category', '');
        }
    }
});
