// Account Creation Request JavaScript Controller
// Provides admin interface for monitoring and managing account creation requests

frappe.ui.form.on('Account Creation Request', {
    refresh: function(frm) {
        // Add custom buttons based on status
        if (frm.doc.status === 'Failed') {
            frm.add_custom_button(__('Retry Processing'), function() {
                retry_account_creation_request(frm);
            }, __('Actions')).addClass('btn-warning');
        }

        if (frm.doc.status === 'Requested') {
            frm.add_custom_button(__('Queue for Processing'), function() {
                queue_account_creation_request(frm);
            }, __('Actions')).addClass('btn-primary');
        }

        if (frm.doc.status in ['Requested', 'Queued', 'Processing']) {
            frm.add_custom_button(__('Cancel Request'), function() {
                cancel_account_creation_request(frm);
            }, __('Actions')).addClass('btn-secondary');
        }

        // Add refresh status button
        frm.add_custom_button(__('Refresh Status'), function() {
            frm.reload_doc();
        });

        // Show status indicator
        update_status_indicator(frm);

        // Auto-refresh for processing requests
        if (frm.doc.status === 'Processing' || frm.doc.status === 'Queued') {
            setTimeout(function() {
                if (frm.doc && !frm.is_dirty()) {
                    frm.reload_doc();
                }
            }, 10000); // Refresh every 10 seconds
        }
    },

    status: function(frm) {
        update_status_indicator(frm);
    }
});

function retry_account_creation_request(frm) {
    if (!frm.doc.name) {
        frappe.msgprint(__('Please save the document first'));
        return;
    }

    frappe.confirm(
        __('Are you sure you want to retry this account creation request?'),
        function() {
            frappe.call({
                method: 'retry_processing',
                doc: frm.doc,
                callback: function(r) {
                    if (r.message && r.message.success) {
                        frappe.msgprint(__('Account creation request has been queued for retry'));
                        frm.reload_doc();
                    } else {
                        frappe.msgprint(__('Failed to retry request: ') + (r.message.error || 'Unknown error'));
                    }
                }
            });
        }
    );
}

function queue_account_creation_request(frm) {
    if (!frm.doc.name) {
        frappe.msgprint(__('Please save the document first'));
        return;
    }

    frappe.call({
        method: 'queue_processing',
        doc: frm.doc,
        callback: function(r) {
            if (r.message && r.message.success) {
                frappe.msgprint(__('Account creation request has been queued for processing'));
                frm.reload_doc();
            } else {
                frappe.msgprint(__('Failed to queue request: ') + (r.message.error || 'Unknown error'));
            }
        }
    });
}

function cancel_account_creation_request(frm) {
    if (!frm.doc.name) {
        frappe.msgprint(__('Please save the document first'));
        return;
    }

    frappe.prompt([
        {
            label: 'Cancellation Reason',
            fieldname: 'reason',
            fieldtype: 'Small Text',
            reqd: 1
        }
    ], function(values) {
        frappe.call({
            method: 'cancel_request',
            doc: frm.doc,
            args: {
                reason: values.reason
            },
            callback: function(r) {
                frappe.msgprint(__('Account creation request has been cancelled'));
                frm.reload_doc();
            }
        });
    }, __('Cancel Account Creation Request'));
}

function update_status_indicator(frm) {
    // Remove existing indicators
    frm.dashboard.clear_headline();

    const status = frm.doc.status;
    let color = 'blue';
    let message = '';

    switch(status) {
        case 'Requested':
            color = 'orange';
            message = __('Request is waiting to be queued for processing');
            break;
        case 'Queued':
            color = 'blue';
            message = __('Request is queued for background processing');
            break;
        case 'Processing':
            color = 'yellow';
            message = __('Request is currently being processed: ') + (frm.doc.pipeline_stage || 'Unknown stage');
            break;
        case 'Completed':
            color = 'green';
            message = __('Account creation completed successfully');
            if (frm.doc.created_user) {
                message += ' - ' + __('User: ') + frm.doc.created_user;
            }
            break;
        case 'Failed':
            color = 'red';
            message = __('Account creation failed');
            if (frm.doc.retry_count) {
                message += ' (' + __('Retry ') + frm.doc.retry_count + ')';
            }
            break;
        case 'Cancelled':
            color = 'grey';
            message = __('Request was cancelled');
            break;
        default:
            color = 'blue';
            message = __('Status: ') + status;
    }

    frm.dashboard.set_headline_alert(
        '<div class="row">' +
            '<div class="col-xs-12">' +
                '<span class="indicator ' + color + '">' + message + '</span>' +
            '</div>' +
        '</div>'
    );
}
