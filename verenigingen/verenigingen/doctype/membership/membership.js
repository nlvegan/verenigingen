// Membership form controller with improved maintainability and custom amount handling
frappe.ui.form.on('Membership', {
    refresh: function(frm) {
        // Basic form setup would go here
        // Remove calls to undefined functions for now
    },

    membership_type: function(frm) {
        // Handle membership type change
        if (frm.doc.membership_type) {
            // Add any membership type specific logic here
        }
    },

    start_date: function(frm) {
        frm.trigger('calculate_renewal_date');
    },

    uses_custom_amount: function(frm) {
        // Clear custom amount fields if unchecked
        if (!frm.doc.uses_custom_amount) {
            frm.set_value('custom_amount', null);
            frm.set_value('amount_reason', '');
        }
    },

    custom_amount: function(frm) {
        // Custom amount validation would go here
    },

    payment_method: function(frm) {
        const is_direct_debit = frm.doc.payment_method === 'SEPA Direct Debit';
        frm.toggle_reqd(['sepa_mandate'], is_direct_debit);
    }
});
