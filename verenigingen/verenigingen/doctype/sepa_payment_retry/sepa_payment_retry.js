frappe.ui.form.on('SEPA Payment Retry', {
    refresh: function(frm) {
        // Add status indicator
        const status_colors = {
            'Pending': 'blue',
            'Scheduled': 'orange',
            'Retried': 'yellow',
            'Failed': 'red',
            'Escalated': 'red',
            'Resolved': 'green',
            'Error': 'red'
        };

        if (frm.doc.status) {
            frm.page.set_indicator(__(frm.doc.status), status_colors[frm.doc.status] || 'gray');
        }

        // Add retry timeline visualization
        if (!frm.is_new() && frm.doc.retry_log && frm.doc.retry_log.length > 0) {
            add_retry_timeline(frm);
        }

        // Add action buttons based on status
        if (frm.doc.status === 'Scheduled' && frm.doc.next_retry_date) {
            frm.add_custom_button(__('Retry Now'), function() {
                retry_payment_now(frm);
            }, __('Actions'));

            frm.add_custom_button(__('Cancel Retry'), function() {
                cancel_retry(frm);
            }, __('Actions'));
        }

        if (frm.doc.status === 'Failed' || frm.doc.status === 'Error') {
            frm.add_custom_button(__('Schedule New Retry'), function() {
                schedule_new_retry(frm);
            }, __('Actions')).addClass('btn-primary');
        }

        if (frm.doc.status === 'Escalated') {
            frm.add_custom_button(__('Mark as Resolved'), function() {
                mark_as_resolved(frm);
            }, __('Actions'));
        }

        // Add helpful information
        add_retry_info_section(frm);
    },

    onload: function(frm) {
        // Set up field properties
        if (frm.is_new()) {
            frm.set_df_property('retry_count', 'hidden', 1);
            frm.set_df_property('last_retry_date', 'hidden', 1);
        }

        // Add custom CSS
        add_retry_custom_styles();
    }
});

function add_retry_timeline(frm) {
    let timeline_html = `
        <div class="retry-timeline">
            <h5>${__('Retry History')}</h5>
            <div class="timeline">
    `;

    frm.doc.retry_log.forEach((attempt, idx) => {
        const icon = attempt.reason_code === 'SUCCESS' ? 'check-circle' : 'times-circle';
        const color = attempt.reason_code === 'SUCCESS' ? 'success' : 'danger';

        timeline_html += `
            <div class="timeline-item">
                <div class="timeline-marker ${color}">
                    <i class="fa fa-${icon}"></i>
                </div>
                <div class="timeline-content">
                    <div class="timeline-date">${frappe.datetime.str_to_user(attempt.attempt_date)}</div>
                    <div class="timeline-title">${__('Attempt')} #${idx + 1}</div>
                    <div class="timeline-description">
                        ${__('Reason')}: ${attempt.reason_code || 'Unknown'}<br>
                        ${attempt.reason_message || ''}
                    </div>
                    ${attempt.scheduled_retry ?
                        `<div class="timeline-next">
                            ${__('Next retry scheduled for')}: ${frappe.datetime.str_to_user(attempt.scheduled_retry)}
                        </div>` : ''
                    }
                </div>
            </div>
        `;
    });

    timeline_html += `
            </div>
        </div>
    `;

    // Add timeline to form
    if (!frm.fields_dict.retry_timeline_html) {
        frm.add_field({
            fieldname: 'retry_timeline_html',
            fieldtype: 'HTML',
            options: timeline_html
        }, 'retry_log');
    } else {
        $(frm.fields_dict.retry_timeline_html.wrapper).html(timeline_html);
    }
}

function add_retry_info_section(frm) {
    let info_html = '<div class="retry-info-section">';

    // Add retry statistics
    const max_retries = 3; // Get from settings
    const attempts_left = Math.max(0, max_retries - frm.doc.retry_count);

    info_html += `
        <div class="row">
            <div class="col-md-3">
                <div class="info-card">
                    <div class="info-label">${__('Original Amount')}</div>
                    <div class="info-value">€${format_currency(frm.doc.original_amount)}</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="info-card">
                    <div class="info-label">${__('Retry Attempts')}</div>
                    <div class="info-value">${frm.doc.retry_count} / ${max_retries}</div>
                    <div class="info-subtitle">${attempts_left} ${__('attempts remaining')}</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="info-card">
                    <div class="info-label">${__('Next Retry')}</div>
                    <div class="info-value">
                        ${frm.doc.next_retry_date ?
                            frappe.datetime.str_to_user(frm.doc.next_retry_date) :
                            __('Not scheduled')}
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="info-card ${frm.doc.status === 'Escalated' ? 'warning' : ''}">
                    <div class="info-label">${__('Current Status')}</div>
                    <div class="info-value">${__(frm.doc.status)}</div>
                </div>
            </div>
        </div>
    `;

    // Add member information
    if (frm.doc.member) {
        info_html += `
            <div class="member-info mt-3">
                <h6>${__('Member Information')}</h6>
                <div class="row">
                    <div class="col-md-6">
                        <strong>${__('Member')}:</strong>
                        <a href="/app/member/${frm.doc.member}">${frm.doc.member}</a>
                    </div>
                    <div class="col-md-6">
                        <strong>${__('Invoice')}:</strong>
                        <a href="/app/sales-invoice/${frm.doc.invoice}">${frm.doc.invoice}</a>
                    </div>
                </div>
            </div>
        `;
    }

    info_html += '</div>';

    // Add to form
    if (!frm.fields_dict.retry_info_html) {
        frm.add_field({
            fieldname: 'retry_info_html',
            fieldtype: 'HTML',
            options: info_html
        }, 'section_break_1');
    } else {
        $(frm.fields_dict.retry_info_html.wrapper).html(info_html);
    }
}

function retry_payment_now(frm) {
    frappe.confirm(
        __('Are you sure you want to retry this payment immediately?'),
        function() {
            frappe.call({
                method: 'verenigingen.utils.payment_retry.execute_payment_retry',
                args: {
                    retry_record: frm.doc.name
                },
                callback: function(r) {
                    if (!r.exc) {
                        frappe.show_alert({
                            message: __('Payment retry initiated'),
                            indicator: 'green'
                        });
                        frm.reload_doc();
                    }
                }
            });
        }
    );
}

function cancel_retry(frm) {
    frappe.confirm(
        __('Are you sure you want to cancel the scheduled retry?'),
        function() {
            frm.set_value('status', 'Cancelled');
            frm.set_value('next_retry_date', null);
            frm.save();
        }
    );
}

function schedule_new_retry(frm) {
    const dialog = new frappe.ui.Dialog({
        title: __('Schedule New Retry'),
        fields: [
            {
                fieldname: 'retry_date',
                label: __('Retry Date'),
                fieldtype: 'Date',
                default: frappe.datetime.add_days(frappe.datetime.get_today(), 3),
                reqd: 1,
                description: __('Select a date for the retry attempt')
            },
            {
                fieldname: 'reason',
                label: __('Reason for Manual Retry'),
                fieldtype: 'Small Text',
                reqd: 1
            }
        ],
        primary_action_label: __('Schedule'),
        primary_action(values) {
            frappe.call({
                method: 'verenigingen.api.payment_dashboard.retry_failed_payment',
                args: {
                    invoice_id: frm.doc.invoice
                },
                callback: function(r) {
                    if (r.message && r.message.success) {
                        frappe.show_alert({
                            message: r.message.message,
                            indicator: 'green'
                        });
                        frm.reload_doc();
                        dialog.hide();
                    }
                }
            });
        }
    });

    dialog.show();
}

function mark_as_resolved(frm) {
    const dialog = new frappe.ui.Dialog({
        title: __('Mark as Resolved'),
        fields: [
            {
                fieldname: 'resolution_method',
                label: __('Resolution Method'),
                fieldtype: 'Select',
                options: [
                    __('Manual Payment Received'),
                    __('Alternative Payment Method'),
                    __('Write-off'),
                    __('Other')
                ],
                reqd: 1
            },
            {
                fieldname: 'resolution_notes',
                label: __('Resolution Notes'),
                fieldtype: 'Small Text',
                reqd: 1
            }
        ],
        primary_action_label: __('Mark Resolved'),
        primary_action(values) {
            frm.set_value('status', 'Resolved');
            frm.add_comment('Comment',
                `${__('Resolved')}: ${values.resolution_method}\n${values.resolution_notes}`);
            frm.save();
            dialog.hide();
        }
    });

    dialog.show();
}

function add_retry_custom_styles() {
    if (!$('#retry-custom-styles').length) {
        $('<style id="retry-custom-styles">').html(`
            .retry-timeline {
                margin-top: 20px;
                padding: 20px;
                background: #f8f9fa;
                border-radius: 8px;
            }
            .timeline {
                position: relative;
                padding-left: 40px;
            }
            .timeline::before {
                content: '';
                position: absolute;
                left: 15px;
                top: 0;
                bottom: 0;
                width: 2px;
                background: #dee2e6;
            }
            .timeline-item {
                position: relative;
                margin-bottom: 30px;
            }
            .timeline-marker {
                position: absolute;
                left: -25px;
                width: 30px;
                height: 30px;
                border-radius: 50%;
                background: white;
                border: 2px solid #dee2e6;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .timeline-marker.success {
                border-color: #28a745;
                color: #28a745;
            }
            .timeline-marker.danger {
                border-color: #dc3545;
                color: #dc3545;
            }
            .timeline-content {
                background: white;
                padding: 15px;
                border-radius: 6px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            }
            .timeline-date {
                font-size: 12px;
                color: #6c757d;
                margin-bottom: 5px;
            }
            .timeline-title {
                font-weight: 600;
                margin-bottom: 5px;
            }
            .timeline-description {
                font-size: 14px;
                color: #495057;
            }
            .timeline-next {
                margin-top: 10px;
                padding-top: 10px;
                border-top: 1px solid #e9ecef;
                font-size: 13px;
                color: #6c757d;
            }
            .retry-info-section {
                margin: 20px 0;
            }
            .info-card {
                background: #f8f9fa;
                padding: 15px;
                border-radius: 6px;
                text-align: center;
                height: 100%;
            }
            .info-card.warning {
                background: #fff3cd;
                border: 1px solid #ffeaa7;
            }
            .info-label {
                font-size: 12px;
                color: #6c757d;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                margin-bottom: 5px;
            }
            .info-value {
                font-size: 20px;
                font-weight: 600;
                color: #212529;
            }
            .info-subtitle {
                font-size: 12px;
                color: #6c757d;
                margin-top: 5px;
            }
            .member-info {
                background: #f8f9fa;
                padding: 15px;
                border-radius: 6px;
            }
        `).appendTo('head');
    }
}

function format_currency(amount) {
    return new Intl.NumberFormat('nl-NL', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(amount || 0);
}
