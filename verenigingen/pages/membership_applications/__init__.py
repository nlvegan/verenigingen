import frappe
from frappe.utils import format_datetime, getdate


@frappe.whitelist()
def get_pending_applications(chapter=None):
    """Get pending membership applications"""
    filters = {"application_status": "Pending", "status": "Pending"}

    # If user is a chapter board member, filter by their chapter
    if not frappe.user.has_role(["Verenigingen Administrator", "Membership Manager"]):
        # Get chapters where user is a board member
        member = frappe.db.get_value("Member", {"user": frappe.session.user}, "name")
        if member:
            # Get chapters where this member is on the board
            board_chapters = frappe.db.sql(
                """
                SELECT DISTINCT c.name
                FROM `tabChapter` c
                JOIN `tabChapter Board Member` cbm ON cbm.parent = c.name
                JOIN `tabVolunteer` v ON cbm.volunteer = v.name
                WHERE v.member = %s AND cbm.is_active = 1
            """,
                (member,),
                as_dict=True,
            )

            if board_chapters:
                chapter_names = [ch.name for ch in board_chapters]
                filters["suggested_chapter"] = ["in", chapter_names]
            else:
                # No board memberships, return empty
                return []

    # Apply chapter filter if provided
    if chapter:
        filters["suggested_chapter"] = chapter

    # Get pending applications
    applications = frappe.get_all(
        "Member",
        filters=filters,
        fields=[
            "name",
            "full_name",
            "email",
            "contact_number",
            "application_date",
            "current_chapter_display",
            "address_display",
            "payment_method",
            "birth_date",
            "age",
        ],
        order_by="application_date desc",
    )

    # Enhance with additional info
    for app in applications:
        app["days_pending"] = (getdate() - getdate(app.application_date)).days
        app["application_date_formatted"] = format_datetime(app.application_date)

        # Get any existing communications
        app["communications"] = frappe.db.count(
            "Communication", {"reference_doctype": "Member", "reference_name": app.name}
        )

    return applications


@frappe.whitelist()
def get_application_stats():
    """Get statistics for membership applications"""
    stats = {
        "total_pending": 0,
        "pending_by_chapter": {},
        "avg_processing_time": 0,
        "recent_approvals": [],
        "recent_rejections": [],
    }

    # Get pending count
    stats["total_pending"] = frappe.db.count("Member", {"application_status": "Pending", "status": "Pending"})

    # Get pending by chapter
    pending_by_chapter = frappe.db.sql(
        """
        SELECT suggested_chapter, COUNT(*) as count
        FROM `tabMember`
        WHERE application_status = 'Pending' AND status = 'Pending'
        AND suggested_chapter IS NOT NULL
        GROUP BY suggested_chapter
    """,
        as_dict=True,
    )

    for row in pending_by_chapter:
        stats["pending_by_chapter"][row.suggested_chapter] = row.count

    # Get average processing time for approved applications
    avg_time = frappe.db.sql(
        """
        SELECT AVG(DATEDIFF(review_date, application_date)) as avg_days
        FROM `tabMember`
        WHERE application_status = 'Approved'
        AND review_date IS NOT NULL
        AND application_date IS NOT NULL
    """,
        as_dict=True,
    )

    if avg_time and avg_time[0].avg_days:
        stats["avg_processing_time"] = round(avg_time[0].avg_days, 1)

    # Get recent approvals
    stats["recent_approvals"] = frappe.get_all(
        "Member",
        filters={
            "application_status": "Approved",
            "review_date": [">=", frappe.utils.add_days(frappe.utils.today(), -30)],
        },
        fields=["full_name", "review_date", "reviewed_by", "primary_chapter"],
        order_by="review_date desc",
        limit=5,
    )

    # Get recent rejections
    stats["recent_rejections"] = frappe.get_all(
        "Member",
        filters={
            "application_status": "Rejected",
            "review_date": [">=", frappe.utils.add_days(frappe.utils.today(), -30)],
        },
        fields=["full_name", "review_date", "reviewed_by", "review_notes"],
        order_by="review_date desc",
        limit=5,
    )

    return stats


@frappe.whitelist()
def bulk_approve_applications(member_names, membership_type, create_invoices=True):
    """Bulk approve multiple membership applications"""
    if isinstance(member_names, str):
        import json

        member_names = json.loads(member_names)

    results = {"success": [], "failed": []}

    for member_name in member_names:
        try:
            # Use the existing approval function
            from verenigingen.verenigingen.web_form.membership_application import (
                approve_membership_application,
            )

            approve_membership_application(
                member_name, create_invoice=create_invoices, membership_type=membership_type
            )
            results["success"].append(member_name)
        except Exception as e:
            results["failed"].append({"member": member_name, "error": str(e)})

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
                    <a href="/app/member/${app.name}" target="_blank">${app.full_name}</a>
                </td>
                <td>${app.email}</td>
                <td>${app.suggested_chapter || '-'}</td>
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

function approve_application(member_name) {
    window.open('/app/member/' + member_name, '_blank');
}

function reject_application(member_name) {
    window.open('/app/member/' + member_name, '_blank');
}

function view_application(member_name) {
    window.open('/app/member/' + member_name, '_blank');
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
                    member_names: selected_applications,
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
