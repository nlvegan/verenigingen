import frappe
from frappe.utils import add_days, format_datetime, getdate, today

from verenigingen.services.member.application.pending_applications import (
    SUBMISSION,
    pending_review_applications,
)
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_pending_applications(chapter: str = None):
    """Pending Review applications (Membership Application Submissions) the caller may read.

    Scope is the MAS permission query (`frappe.get_list`): a board member sees the chapters of their
    seats, an admin everything, anyone without a seat nothing (#1765, #1486 item 3).
    """
    applications = pending_review_applications(chapter=chapter)
    for app in applications:
        app["full_name"] = app["applicant_name"]
        app["application_date_formatted"] = format_datetime(app["application_date"])
        app["suggested_chapter"] = app["chapter"]
        app["communications"] = frappe.db.count(
            "Communication", {"reference_doctype": SUBMISSION, "reference_name": app["name"]}
        )
    return applications


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_application_stats():
    """Statistics for membership applications, over the applications the caller may read."""
    stats = {
        "total_pending": 0,
        "pending_by_chapter": {},
        "avg_processing_time": 0,
        "recent_approvals": [],
        "recent_rejections": [],
    }

    pending = pending_review_applications()
    stats["total_pending"] = len(pending)
    for app in pending:
        if app["chapter"]:
            stats["pending_by_chapter"][app["chapter"]] = (
                stats["pending_by_chapter"].get(app["chapter"], 0) + 1
            )

    approved = _readable_decided("Approved", ["confirmed_on", "review_date"])
    if approved:
        total_days = sum((getdate(a.review_date) - getdate(a.confirmed_on)).days for a in approved)
        stats["avg_processing_time"] = round(total_days / len(approved), 1)

    since = add_days(today(), -30)
    stats["recent_approvals"] = _readable_decided(
        "Approved",
        ["name", "applicant_name", "chapter", "review_date", "reviewed_by"],
        {"review_date": [">=", since]},
        limit=5,
    )
    for approval in stats["recent_approvals"]:
        approval["full_name"] = approval["applicant_name"]
        approval["current_chapter_display"] = approval["chapter"]
    stats["recent_rejections"] = _readable_decided(
        "Rejected",
        ["applicant_name", "review_date", "reviewed_by", "review_notes"],
        {"review_date": [">=", since]},
        limit=5,
    )
    for rejection in stats["recent_rejections"]:
        rejection["full_name"] = rejection["applicant_name"]
    return stats


def _readable_decided(status, fields, extra_filters=None, limit=None):
    """Decided applications (`status`) the caller may read; [] for a caller who may not read any."""
    try:
        return frappe.get_list(
            SUBMISSION,
            filters={"status": status, "review_date": ["is", "set"], **(extra_filters or {})},
            fields=fields,
            order_by="review_date desc",
            limit_page_length=limit or 0,
        )
    except frappe.PermissionError:
        return []


@frappe.whitelist()
@standard_api(operation_type=OperationType.ADMIN)
def bulk_approve_applications(application_names: str, membership_type: str, create_invoices: bool = True):
    """Bulk approve multiple membership applications (by application name)"""
    if isinstance(application_names, str):
        import json

        application_names = json.loads(application_names)

    results = {"success": [], "failed": []}

    for application_name in application_names:
        try:
            from verenigingen.api.membership_application_review import approve_application

            approve_application(
                application_name, create_invoice=create_invoices, membership_type=membership_type
            )
            results["success"].append(application_name)
        except Exception as e:
            results["failed"].append({"application": application_name, "error": str(e)})

    return results


# Create the dashboard HTML template
dashboard_html = """
<!-- verenigingen/verenigingen/page/membership_applications/membership_applications.html -->
<div class="membership-applications-dashboard">
    <div class="page-header">
        <h2>{{ _("Membership Applications") }}</h2>
        <div class="page-actions">
            <button class="btn btn-primary btn-sm" onclick="refresh_applications()">
                <i class="fa fa-refresh"></i> {{ _("Refresh") }}
            </button>
        </div>
    </div>

    <!-- Statistics Cards -->
    <div class="stats-section mb-4">
        <div class="row">
            <div class="col-md-3">
                <div class="card stat-card">
                    <div class="card-body">
                        <h4 class="stat-number" id="total-pending">0</h4>
                        <p class="stat-label">{{ _("Pending Applications") }}</p>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card stat-card">
                    <div class="card-body">
                        <h4 class="stat-number" id="avg-processing-time">0</h4>
                        <p class="stat-label">{{ _("Avg. Processing Days") }}</p>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card stat-card">
                    <div class="card-body">
                        <h4 class="stat-number" id="recent-approvals">0</h4>
                        <p class="stat-label">{{ _("Recent Approvals") }}</p>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card stat-card">
                    <div class="card-body">
                        <h4 class="stat-number" id="recent-rejections">0</h4>
                        <p class="stat-label">{{ _("Recent Rejections") }}</p>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Filters -->
    <div class="filters-section mb-4">
        <div class="row">
            <div class="col-md-4">
                <label>{{ _("Filter by Chapter") }}</label>
                <select class="form-control" id="chapter-filter">
                    <option value="">{{ _("All Chapters") }}</option>
                </select>
            </div>
            <div class="col-md-4">
                <label>{{ _("Bulk Actions") }}</label>
                <button class="btn btn-success btn-block" onclick="bulk_approve_selected()" disabled id="bulk-approve-btn">
                    {{ _("Approve Selected") }}
                </button>
            </div>
        </div>
    </div>

    <!-- Applications Table -->
    <div class="applications-table">
        <table class="table table-bordered" id="applications-list">
            <thead>
                <tr>
                    <th width="30">
                        <input type="checkbox" id="select-all-applications">
                    </th>
                    <th>{{ _("Name") }}</th>
                    <th>{{ _("Email") }}</th>
                    <th>{{ _("Chapter") }}</th>
                    <th>{{ _("Applied") }}</th>
                    <th>{{ _("Days Pending") }}</th>
                    <th>{{ _("Actions") }}</th>
                </tr>
            </thead>
            <tbody id="applications-tbody">
                <!-- Applications will be loaded here -->
            </tbody>
        </table>
    </div>
</div>

<style>
.stat-card {
    text-align: center;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    padding: 20px;
}

.stat-number {
    font-size: 2.5em;
    font-weight: bold;
    color: #333;
    margin: 0;
}

.stat-label {
    color: #666;
    margin: 0;
}

.applications-table {
    background: white;
    padding: 20px;
    border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.action-buttons .btn {
    margin-right: 5px;
}
</style>

<script>
var selected_applications = [];

$(document).ready(function() {
    load_stats();
    load_applications();
    load_chapters();

    // Select all checkbox
    $('#select-all-applications').change(function() {
        var checked = $(this).is(':checked');
        $('.application-checkbox').prop('checked', checked);
        update_selected_applications();
    });

    // Chapter filter
    $('#chapter-filter').change(function() {
        load_applications();
    });
});

function load_stats() {
    frappe.call({
        method: 'verenigingen.verenigingen.page.membership_applications.get_application_stats',
        callback: function(r) {
            if (r.message) {
                var stats = r.message;
                $('#total-pending').text(stats.total_pending);
                $('#avg-processing-time').text(stats.avg_processing_time + ' days');
                $('#recent-approvals').text(stats.recent_approvals.length);
                $('#recent-rejections').text(stats.recent_rejections.length);
            }
        }
    });
}

function load_applications() {
    var chapter = $('#chapter-filter').val();

    frappe.call({
        method: 'verenigingen.verenigingen.page.membership_applications.get_pending_applications',
        args: {
            chapter: chapter
        },
        callback: function(r) {
            if (r.message) {
                render_applications(r.message);
            }
        }
    });
}

function render_applications(applications) {
    var tbody = $('#applications-tbody');
    tbody.empty();

    if (applications.length === 0) {
        tbody.append('<tr><td colspan="7" class="text-center">{{ _("No pending applications") }}</td></tr>');
        return;
    }

    applications.forEach(function(app) {
        var row = `
            <tr>
                <td>
                    <input type="checkbox" class="application-checkbox" value="${app.name}">
                </td>
                <td>
                    <a href="/app/membership-application-submission/${encodeURIComponent(app.name)}" target="_blank">${frappe.utils.escape_html(app.full_name)}</a>
                </td>
                <td>${frappe.utils.escape_html(app.email)}</td>
                <td>${frappe.utils.escape_html(app.suggested_chapter || '-')}</td>
                <td>${app.application_date_formatted}</td>
                <td>
                    <span class="badge ${app.days_pending > 7 ? 'badge-warning' : 'badge-info'}">
                        ${app.days_pending} days
                    </span>
                </td>
                <td class="action-buttons">
                    <button class="btn btn-success btn-xs" onclick="approve_application('${app.name}')">
                        {{ _("Approve") }}
                    </button>
                    <button class="btn btn-danger btn-xs" onclick="reject_application('${app.name}')">
                        {{ _("Reject") }}
                    </button>
                    <button class="btn btn-default btn-xs" onclick="view_application('${app.name}')">
                        {{ _("View") }}
                    </button>
                </td>
            </tr>
        `;
        tbody.append(row);
    });

    // Re-bind checkbox events
    $('.application-checkbox').change(function() {
        update_selected_applications();
    });
}

function update_selected_applications() {
    selected_applications = [];
    $('.application-checkbox:checked').each(function() {
        selected_applications.push($(this).val());
    });

    $('#bulk-approve-btn').prop('disabled', selected_applications.length === 0);
}

function approve_application(application_name) {
    window.open('/app/membership-application-submission/' + encodeURIComponent(application_name), '_blank');
}

function reject_application(application_name) {
    window.open('/app/membership-application-submission/' + encodeURIComponent(application_name), '_blank');
}

function view_application(application_name) {
    window.open('/app/membership-application-submission/' + encodeURIComponent(application_name), '_blank');
}

function bulk_approve_selected() {
    if (selected_applications.length === 0) return;

    // Show dialog to select membership type
    var d = new frappe.ui.Dialog({
        title: __('Bulk Approve Applications'),
        fields: [
            {
                fieldname: 'membership_type',
                fieldtype: 'Link',
                label: __('Membership Type'),
                options: 'Membership Type',
                reqd: 1
            },
            {
                fieldname: 'create_invoices',
                fieldtype: 'Check',
                label: __('Create Invoices'),
                default: 1
            }
        ],
        primary_action_label: __('Approve {0} Applications', [selected_applications.length]),
        primary_action: function(values) {
            frappe.call({
                method: 'verenigingen.verenigingen.page.membership_applications.bulk_approve_applications',
                args: {
                    application_names: selected_applications,
                    membership_type: values.membership_type,
                    create_invoices: values.create_invoices
                },
                freeze: true,
                freeze_message: __('Processing applications...'),
                callback: function(r) {
                    if (r.message) {
                        var result = r.message;
                        frappe.show_alert({
                            message: __('Approved {0} applications successfully', [result.success.length]),
                            indicator: 'green'
                        }, 5);

                        if (result.failed.length > 0) {
                            frappe.msgprint(__('Failed to approve {0} applications', [result.failed.length]));
                        }

                        d.hide();
                        refresh_applications();
                    }
                }
            });
        }
    });

    d.show();
}

function load_chapters() {
    frappe.call({
        method: 'frappe.client.get_list',
        args: {
            doctype: 'Chapter',
            fields: ['name'],
            filters: { published: 1 },
            order_by: 'name'
        },
        callback: function(r) {
            if (r.message) {
                var select = $('#chapter-filter');
                r.message.forEach(function(chapter) {
                    select.append(`<option value="${chapter.name}">${chapter.name}</option>`);
                });
            }
        }
    });
}

function refresh_applications() {
    load_stats();
    load_applications();
}
</script>
"""
