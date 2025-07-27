// Copyright (c) 2025, Verenigingen and contributors
// For license information, please see license.txt

frappe.ui.form.on('API Audit Log', {
    refresh: function(frm) {
        // Make form read-only to prevent modifications
        frm.disable_save();
        frm.set_read_only();

        // Add custom buttons for viewing related records
        if (frm.doc.reference_doctype && frm.doc.reference_name) {
            frm.add_custom_button(__('View Reference Document'), function() {
                frappe.set_route('Form', frm.doc.reference_doctype, frm.doc.reference_name);
            });
        }

        if (frm.doc.user && frm.doc.user !== 'System') {
            frm.add_custom_button(__('View User'), function() {
                frappe.set_route('Form', 'User', frm.doc.user);
            });
        }

        // Show details in a formatted way
        if (frm.doc.details) {
            try {
                const details = typeof frm.doc.details === 'string' ?
                    JSON.parse(frm.doc.details) : frm.doc.details;

                if (Object.keys(details).length > 0) {
                    frm.add_custom_button(__('View Details'), function() {
                        let dialog = new frappe.ui.Dialog({
                            title: __('Event Details'),
                            size: 'large',
                            fields: [{
                                fieldtype: 'Code',
                                fieldname: 'details_json',
                                label: __('Details'),
                                options: 'JSON',
                                value: JSON.stringify(details, null, 2),
                                read_only: 1
                            }]
                        });
                        dialog.show();
                    });
                }
            } catch (e) {
                console.warn('Failed to parse audit log details:', e);
            }
        }

        // Add severity-based styling
        if (frm.doc.severity) {
            const severityColors = {
                'info': '#17a2b8',
                'warning': '#ffc107',
                'error': '#dc3545',
                'critical': '#6f42c1'
            };

            const color = severityColors[frm.doc.severity] || '#6c757d';
            frm.set_indicator(frm.doc.severity.toUpperCase(), color);
        }
    },

    onload: function(frm) {
        // Format timestamp display
        if (frm.doc.timestamp) {
            frm.set_value('timestamp', moment(frm.doc.timestamp).format('YYYY-MM-DD HH:mm:ss'));
        }
    }
});
