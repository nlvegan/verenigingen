# Copyright (c) 2025, R.S.P. and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.model.document import Document
from frappe.utils import format_datetime, now_datetime


class EBoekhoudenDashboard(Document):
    @frappe.whitelist()
    def load_dashboard_data(self):
        """Load and update dashboard data"""
        try:
            # Update connection status
            self.update_connection_status()

            # Update migration statistics
            self.update_migration_stats()

            # Update data availability
            self.update_data_availability()

            # Generate dashboard HTML
            self.generate_dashboard_html()

            # Generate recent migrations HTML
            self.generate_recent_migrations_html()

            self.last_sync_time = now_datetime()
            self.save()

        except Exception as e:
            frappe.log_error(f"Error loading dashboard data: {str(e)}", "E-Boekhouden Dashboard")

    def update_connection_status(self):
        """Update API connection status"""
        try:
            from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

            settings = frappe.get_single("E-Boekhouden Settings")
            api = EBoekhoudenAPI(settings)

            # Test connection with a simple session token request
            session_token = api.get_session_token()

            if session_token:
                self.connection_status = "✅ Connected"
            else:
                self.connection_status = "❌ Connection Failed: Unable to get session token"

        except Exception as e:
            self.connection_status = f"❌ Error: {str(e)[:50]}"

    def update_migration_stats(self):
        """Update migration statistics"""
        try:
            # Get migration counts
            total_migrations = frappe.db.count("E-Boekhouden Migration")
            active_migrations = frappe.db.count("E-Boekhouden Migration", {"migration_status": "In Progress"})
            failed_migrations = frappe.db.count("E-Boekhouden Migration", {"migration_status": "Failed"})

            self.total_migrations = total_migrations
            self.active_migrations = active_migrations
            self.failed_migrations = failed_migrations

        except Exception as e:
            frappe.log_error(f"Error updating migration stats: {str(e)}", "E-Boekhouden Dashboard")

    def update_data_availability(self):
        """Update available data counts from e-Boekhouden"""
        try:
            from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

            settings = frappe.get_single("E-Boekhouden Settings")
            api = EBoekhoudenAPI(settings)

            # Get Chart of Accounts count
            result = api.get_chart_of_accounts()
            if result["success"]:
                try:
                    data = json.loads(result["data"])
                    self.accounts_available = len(data.get("items", []))
                except Exception:
                    self.accounts_available = 0
            else:
                self.accounts_available = 0

            # Get Cost Centers count
            result = api.get_cost_centers()
            if result["success"]:
                try:
                    data = json.loads(result["data"])
                    self.cost_centers_available = len(data.get("items", []))
                except Exception:
                    self.cost_centers_available = 0
            else:
                self.cost_centers_available = 0

            # Get Customers count
            result = api.get_customers()
            if result["success"]:
                try:
                    data = json.loads(result["data"])
                    self.customers_available = len(data.get("items", []))
                except Exception:
                    self.customers_available = 0
            else:
                self.customers_available = 0

            # Get Suppliers count
            result = api.get_suppliers()
            if result["success"]:
                try:
                    data = json.loads(result["data"])
                    self.suppliers_available = len(data.get("items", []))
                except Exception:
                    self.suppliers_available = 0
            else:
                self.suppliers_available = 0

        except Exception as e:
            frappe.log_error(f"Error updating data availability: {str(e)}", "E-Boekhouden Dashboard")
            self.accounts_available = 0
            self.cost_centers_available = 0
            self.customers_available = 0
            self.suppliers_available = 0

    def generate_dashboard_html(self):
        """Generate main dashboard HTML"""
        try:
            # Status indicators
            "green" if "✅" in (self.connection_status or "") else "red"

            # Calculate percentages and status
            # total_available = (
            #     (self.accounts_available or 0)
            #     + (self.cost_centers_available or 0)
            #     + (self.customers_available or 0)
            #     + (self.suppliers_available or 0)
            # )

            html = """
            <div class="dashboard-container">
                <style>
                    .dashboard-container {{
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                    }}
                    .dashboard-cards {{
                        display: grid;
                        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                        gap: 20px;
                        margin-bottom: 30px;
                    }}
                    .dashboard-card {{
                        background: white;
                        border: 1px solid #d1d8dd;
                        border-radius: 8px;
                        padding: 20px;
                        text-align: center;
                        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                    }}
                    .card-number {{
                        font-size: 2em;
                        font-weight: bold;
                        margin-bottom: 5px;
                    }}
                    .card-label {{
                        color: #6c757d;
                        font-size: 0.9em;
                    }}
                    .status-green {{ color: #28a745; }}
                    .status-red {{ color: #dc3545; }}
                    .status-blue {{ color: #007bff; }}
                    .progress-bar {{
                        background-color: #e9ecef;
                        border-radius: 4px;
                        overflow: hidden;
                        height: 8px;
                        margin-top: 10px;
                    }}
                    .progress-fill {{
                        height: 100%;
                        background-color: #007bff;
                        transition: width 0.3s ease;
                    }}
                    .quick-actions {{
                        margin-top: 20px;
                    }}
                    .btn-custom {{
                        display: inline-block;
                        padding: 8px 16px;
                        margin: 5px;
                        background-color: #007bff;
                        color: white;
                        text-decoration: none;
                        border-radius: 4px;
                        border: none;
                        cursor: pointer;
                        font-size: 0.9em;
                    }}
                    .btn-custom:hover {{
                        background-color: #0056b3;
                        color: white;
                        text-decoration: none;
                    }}
                    .btn-success {{ background-color: #28a745; }}
                    .btn-success:hover {{ background-color: #1e7e34; }}
                    .btn-warning {{ background-color: #ffc107; color: #212529; }}
                    .btn-warning:hover {{ background-color: #e0a800; }}
                </style>

                <div class="dashboard-cards">
                    <div class="dashboard-card">
                        <div class="card-number status-{connection_color}">
                            {'✅' if connection_color == 'green' else '❌'}
                        </div>
                        <div class="card-label">API Connection</div>
                    </div>

                    <div class="dashboard-card">
                        <div class="card-number status-blue">{total_available}</div>
                        <div class="card-label">Total Records Available</div>
                    </div>

                    <div class="dashboard-card">
                        <div class="card-number status-blue">{self.total_migrations or 0}</div>
                        <div class="card-label">Total Migrations</div>
                    </div>

                    <div class="dashboard-card">
                        <div class="card-number {'status-red' if (self.failed_migrations or 0) > 0 else 'status-green'}">{self.failed_migrations or 0}</div>
                        <div class="card-label">Failed Migrations</div>
                    </div>
                </div>

                <div class="quick-actions">
                    <h4>Quick Actions</h4>
                    <button class="btn-custom" onclick="frappe.set_route('Form', 'E-Boekhouden Migration', 'new-e-boekhouden-migration-1');">
                        🚀 New Migration
                    </button>
                    <button class="btn-custom" onclick="frappe.set_route('List', 'E-Boekhouden Migration');">
                        📋 View All Migrations
                    </button>
                    <button class="btn-custom btn-success" onclick="frappe.set_route('Form', 'E-Boekhouden Settings');">
                        ⚙️ Settings
                    </button>
                    <button class="btn-custom btn-warning" onclick="refresh_dashboard();">
                        🔄 Refresh Dashboard
                    </button>
                </div>

                <script>
                    function refresh_dashboard() {{
                        frappe.call({{
                            method: 'verenigingen.verenigingen.doctype.e_boekhouden_dashboard.e_boekhouden_dashboard.refresh_dashboard_data',
                            callback: function(r) {{
                                if (r.message && r.message.success) {{
                                    frappe.show_alert({{
                                        message: 'Dashboard refreshed successfully',
                                        indicator: 'green'
                                    }});
                                    location.reload();
                                }} else {{
                                    frappe.show_alert({{
                                        message: 'Failed to refresh dashboard',
                                        indicator: 'red'
                                    }});
                                }}
                            }}
                        }});
                    }}
                </script>
            </div>
            """

            self.dashboard_html = html

        except Exception as e:
            frappe.log_error(f"Error generating dashboard HTML: {str(e)}", "E-Boekhouden Dashboard")
            self.dashboard_html = "<p>Error loading dashboard</p>"

    def generate_recent_migrations_html(self):
        """Generate recent migrations HTML"""
        try:
            # Get recent migrations
            recent_migrations = frappe.get_all(
                "E-Boekhouden Migration",
                fields=[
                    "name",
                    "migration_name",
                    "migration_status",
                    "progress_percentage",
                    "start_time",
                    "end_time",
                    "current_operation",
                ],
                order_by="start_time desc",
                limit=10,
            )

            if not recent_migrations:
                self.recent_migrations_html = "<p>No migrations found.</p>"
                return

            html = """
            <div class="recent-migrations">
                <style>
                    .migration-table {
                        width: 100%;
                        border-collapse: collapse;
                        margin-top: 10px;
                    }
                    .migration-table th,
                    .migration-table td {
                        padding: 12px;
                        text-align: left;
                        border-bottom: 1px solid #ddd;
                    }
                    .migration-table th {
                        background-color: #f8f9fa;
                        font-weight: 600;
                    }
                    .status-completed { color: #28a745; font-weight: bold; }
                    .status-failed { color: #dc3545; font-weight: bold; }
                    .status-in-progress { color: #007bff; font-weight: bold; }
                    .status-draft { color: #6c757d; font-weight: bold; }
                    .migration-link {
                        color: #007bff;
                        text-decoration: none;
                        cursor: pointer;
                    }
                    .migration-link:hover {
                        text-decoration: underline;
                    }
                    .progress-cell {
                        min-width: 100px;
                    }
                </style>

                <table class="migration-table">
                    <thead>
                        <tr>
                            <th>Migration Name</th>
                            <th>Status</th>
                            <th>Progress</th>
                            <th>Started</th>
                            <th>Current Operation</th>
                        </tr>
                    </thead>
                    <tbody>
            """

            for migration in recent_migrations:
                status_class = f"status-{migration.migration_status.lower().replace(' ', '-')}"
                progress = migration.progress_percentage or 0
                start_time = format_datetime(migration.start_time) if migration.start_time else "-"
                current_op = migration.current_operation or "-"

                # Truncate long operations
                if len(current_op) > 50:
                    current_op = current_op[:47] + "..."

                html += f"""
                        <tr>
                            <td>
                                <a href="/app/e-boekhouden-migration/{migration.name}" class="migration-link">
                                    {migration.migration_name}
                                </a>
                            </td>
                            <td><span class="{status_class}">{migration.migration_status}</span></td>
                            <td class="progress-cell">{progress}%</td>
                            <td>{start_time}</td>
                            <td>{current_op}</td>
                        </tr>
                """

            html += """
                    </tbody>
                </table>
            </div>
            """

            self.recent_migrations_html = html

        except Exception as e:
            frappe.log_error(f"Error generating recent migrations HTML: {str(e)}", "E-Boekhouden Dashboard")
            self.recent_migrations_html = "<p>Error loading recent migrations</p>"


@frappe.whitelist()
def refresh_dashboard_data():
    """Refresh dashboard data"""
    try:
        dashboard = frappe.get_single("E-Boekhouden Dashboard")
        dashboard.load_dashboard_data()

        return {"success": True, "message": "Dashboard data refreshed successfully"}

    except Exception as e:
        frappe.log_error(f"Error refreshing dashboard: {str(e)}", "E-Boekhouden Dashboard")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_migration_summary():
    """Get migration summary statistics"""
    try:
        # Migration status counts
        status_counts = frappe.db.sql(
            """
            SELECT migration_status, COUNT(*) as count
            FROM `tabE-Boekhouden Migration`
            GROUP BY migration_status
        """,
            as_dict=True,
        )

        # Recent activity
        recent_activity = frappe.db.sql(
            """
            SELECT name, migration_name, migration_status, progress_percentage, start_time
            FROM `tabE-Boekhouden Migration`
            ORDER BY start_time DESC
            LIMIT 5
        """,
            as_dict=True,
        )

        # Data migration counts
        migration_counts = frappe.db.sql(
            """
            SELECT
                SUM(total_records) as total_migrated,
                SUM(imported_records) as successful_imports,
                SUM(failed_records) as failed_imports
            FROM `tabE-Boekhouden Migration`
            WHERE migration_status = 'Completed'
        """,
            as_dict=True,
        )

        return {
            "success": True,
            "status_counts": status_counts,
            "recent_activity": recent_activity,
            "migration_counts": migration_counts[0] if migration_counts else {},
        }

    except Exception as e:
        frappe.log_error(f"Error getting migration summary: {str(e)}", "E-Boekhouden Dashboard")
        return {"success": False, "error": str(e)}
