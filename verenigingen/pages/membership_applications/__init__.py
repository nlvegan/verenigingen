import frappe
from frappe.utils import format_datetime, getdate

from verenigingen.utils.constants import Roles
from verenigingen.utils.member_utils import get_current_user_member_name
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


def _manageable_chapters_for_current_user():
    """Chapters the caller may see applications for.

    Returns ``None`` for an unrestricted caller (Roles.ADMIN_ROLES: System
    Manager / Verenigingen Administrator / Verenigingen Staff). Otherwise
    resolves the caller's own active Chapter Board Member seat(s) via
    ``permissions._get_board_chapters_for_member()`` -- the same helper #1329's
    SEPA mandate diagnostics scoping reuses -- and returns that list, which is
    empty for a caller (e.g. Volunteer, Auditor) holding no active board seat.
    """
    if set(frappe.get_roles()) & Roles.ADMIN_ROLES:
        return None

    from verenigingen.permissions import _get_board_chapters_for_member

    member = get_current_user_member_name()
    return _get_board_chapters_for_member(member) if member else []


def _member_names_in_chapters(chapter_names):
    """Names of members holding a Chapter Member row on any of `chapter_names`.

    Member has no `suggested_chapter` field; the chapter an application is for
    lives on the Chapter Member child table row the application flow writes at
    submission time (application_helpers.py::create_pending_chapter_membership).
    `enabled=1`, no status filter -- mirrors
    api/membership_application_review.py::get_pending_applications, the
    already-working sibling this page duplicates.
    """
    if not chapter_names:
        return []
    return frappe.get_all(
        "Chapter Member",
        filters={"parent": ["in", chapter_names], "enabled": 1},
        pluck="member",
    )


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_pending_applications(chapter: str = None):
    """Get pending membership applications"""
    filters = {"application_status": "Pending", "status": "Pending"}

    allowed_chapters = _manageable_chapters_for_current_user()
    if allowed_chapters is not None and not allowed_chapters:
        # No active board seat anywhere: nothing to show.
        return []

    scoped_chapters = None
    if chapter:
        if allowed_chapters is not None and chapter not in allowed_chapters:
            return []
        scoped_chapters = [chapter]
    elif allowed_chapters is not None:
        scoped_chapters = allowed_chapters

    if scoped_chapters is not None:
        member_names = _member_names_in_chapters(scoped_chapters)
        if not member_names:
            return []
        filters["name"] = ["in", list(set(member_names))]

    # Get pending applications. `current_chapter_display` and `address_display`
    # are HTML-fieldtype fields with no DB column (confirmed live) and cannot
    # be requested here; chapter is attached below from Chapter Member instead.
    applications = frappe.get_all(
        "Member",
        filters=filters,
        fields=[
            "name",
            "full_name",
            "email",
            "contact_number",
            "application_date",
            "payment_method",
            "birth_date",
            "age",
        ],
        order_by="application_date desc",
    )

    # Batch-fetch each application's chapter for display (same query shape as
    # api/membership_application_review.py::get_pending_applications).
    app_names = [app.name for app in applications]
    chapter_by_member = {}
    if app_names:
        rows = frappe.db.sql(
            """
            SELECT member, parent as chapter_name
            FROM `tabChapter Member`
            WHERE member IN %(names)s AND enabled = 1
            ORDER BY chapter_join_date DESC
            """,
            {"names": app_names},
            as_dict=True,
        )
        for row in rows:
            chapter_by_member.setdefault(row.member, row.chapter_name)

    # Enhance with additional info
    for app in applications:
        app["days_pending"] = (getdate() - getdate(app.application_date)).days
        app["application_date_formatted"] = format_datetime(app.application_date)
        app["suggested_chapter"] = chapter_by_member.get(app.name)

        # Get any existing communications
        app["communications"] = frappe.db.count(
            "Communication", {"reference_doctype": "Member", "reference_name": app.name}
        )

    return applications


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_application_stats():
    """Get statistics for membership applications"""
    stats = {
        "total_pending": 0,
        "pending_by_chapter": {},
        "avg_processing_time": 0,
        "recent_approvals": [],
        "recent_rejections": [],
    }

    allowed_chapters = _manageable_chapters_for_current_user()
    if allowed_chapters is not None and not allowed_chapters:
        # No active board seat: same "sees nothing" outcome as
        # chapter_security's approval-permission checks for a caller who
        # clears the bare REPORTING tier (Volunteer/Auditor, #1486) but has no
        # legitimate front door to this data.
        return stats

    scope_filter = {}
    if allowed_chapters is not None:
        scoped_member_names = _member_names_in_chapters(allowed_chapters)
        if not scoped_member_names:
            return stats
        # A board member's view is scoped to members currently linked to
        # their chapter(s). Two cases fall out of that and are both visible
        # to admins only (safe -- nothing leaks -- though less complete than
        # admin's unrestricted view):
        #  - A rejected application's Chapter Member row is deleted on
        #    rejection (remove_all_pending_chapter_memberships), so it becomes
        #    invisible to non-admin callers once rejected.
        #  - An applicant with NO Chapter Member row at all: reachable, since
        #    _create_pending_chapter_membership_safe (application_helpers.py)
        #    is fire-and-forget and can silently fail to create it.
        scope_filter["name"] = ["in", list(set(scoped_member_names))]

    pending_filters = {"application_status": "Pending", "status": "Pending", **scope_filter}

    # Get pending count
    stats["total_pending"] = frappe.db.count("Member", pending_filters)

    # Get pending by chapter. Member has no `suggested_chapter` field; the
    # live equivalent is the Chapter Member child table row the application
    # flow writes at submission (create_pending_chapter_membership).
    pending_member_names = frappe.get_all("Member", filters=pending_filters, pluck="name")
    if pending_member_names:
        pending_by_chapter = frappe.db.sql(
            """
            SELECT parent as chapter_name, COUNT(DISTINCT member) as count
            FROM `tabChapter Member`
            WHERE member IN %(members)s AND enabled = 1
            GROUP BY parent
            """,
            {"members": pending_member_names},
            as_dict=True,
        )
        for row in pending_by_chapter:
            stats["pending_by_chapter"][row.chapter_name] = row.count

    # Get average processing time for approved applications
    approved_filters = {
        "application_status": "Approved",
        "review_date": ["is", "set"],
        "application_date": ["is", "set"],
        **scope_filter,
    }
    approved_dates = frappe.get_all(
        "Member", filters=approved_filters, fields=["application_date", "review_date"]
    )
    if approved_dates:
        total_days = sum((getdate(m.review_date) - getdate(m.application_date)).days for m in approved_dates)
        stats["avg_processing_time"] = round(total_days / len(approved_dates), 1)

    # Get recent approvals. `current_chapter_display` is an HTML-fieldtype
    # field with no DB column (confirmed live) and cannot be requested here;
    # chapter is attached below from Chapter Member instead.
    recent_approvals = frappe.get_all(
        "Member",
        filters={
            "application_status": "Approved",
            "review_date": [">=", frappe.utils.add_days(frappe.utils.today(), -30)],
            **scope_filter,
        },
        fields=["name", "full_name", "review_date", "reviewed_by"],
        order_by="review_date desc",
        limit=5,
    )
    approval_chapters = {}
    if recent_approvals:
        rows = frappe.db.sql(
            """
            SELECT member, parent as chapter_name
            FROM `tabChapter Member`
            WHERE member IN %(names)s AND enabled = 1
            ORDER BY chapter_join_date DESC
            """,
            {"names": [m.name for m in recent_approvals]},
            as_dict=True,
        )
        for row in rows:
            approval_chapters.setdefault(row.member, row.chapter_name)
    for approval in recent_approvals:
        approval["current_chapter_display"] = approval_chapters.get(approval.name)
    stats["recent_approvals"] = recent_approvals

    # Get recent rejections
    stats["recent_rejections"] = frappe.get_all(
        "Member",
        filters={
            "application_status": "Rejected",
            "review_date": [">=", frappe.utils.add_days(frappe.utils.today(), -30)],
            **scope_filter,
        },
        fields=["full_name", "review_date", "reviewed_by", "review_notes"],
        order_by="review_date desc",
        limit=5,
    )

    return stats


@frappe.whitelist()
@standard_api(operation_type=OperationType.ADMIN)
def bulk_approve_applications(member_names: str, membership_type: str, create_invoices: bool = True):
    """Bulk approve multiple membership applications"""
    if isinstance(member_names, str):
        import json

        member_names = json.loads(member_names)

    results = {"success": [], "failed": []}

    for member_name in member_names:
        try:
            # Use the existing approval function
            from verenigingen.api.membership_application_review import approve_membership_application

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
