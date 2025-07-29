"""
Security Configuration Onboarding Step
Guides administrators through critical security settings identified during test infrastructure implementation
"""

import frappe
from frappe import _
from frappe.model.document import Document


class VereningingenConfigureSecurity(Document):
    """Onboarding step for configuring critical security settings"""

    def validate(self):
        """Validate security configuration step"""
        pass

    @frappe.whitelist()
    def get_security_checklist(self):
        """Return security configuration checklist for administrators"""
        return {
            "title": _("Critical Security Configuration Required"),
            "description": _(
                "The test infrastructure has identified 4 critical security issues that require administrative configuration:"
            ),
            "issues": [
                {
                    "id": "guest_access_control",
                    "title": _("Guest Access Control Gap"),
                    "severity": "Critical",
                    "description": _(
                        "Guest users can currently access member personal data and financial information"
                    ),
                    "risk": _("Data privacy violation, potential GDPR compliance issues"),
                    "solution": {
                        "title": _("Configure Guest User Permissions"),
                        "steps": [
                            _("Go to: Setup > Users and Permissions > Role Permissions Manager"),
                            _("Select Role: 'Guest'"),
                            _("For DocType 'Member': Remove all permissions (read, write, create, delete)"),
                            _("For DocType 'SEPA Mandate': Remove all permissions"),
                            _("For DocType 'Membership': Remove all permissions"),
                            _("For DocType 'Volunteer Expense': Remove all permissions"),
                            _("Save changes and test with guest login"),
                        ],
                        "validation": _(
                            "Test by logging out and accessing /app - should not see member data"
                        ),
                    },
                },
                {
                    "id": "document_level_permissions",
                    "title": _("Document-Level Permission Enforcement"),
                    "severity": "High",
                    "description": _("Users can access documents from other organizational units (chapters)"),
                    "risk": _("Cross-organizational data leakage"),
                    "solution": {
                        "title": _("Configure Chapter-Based Data Isolation"),
                        "steps": [
                            _("Go to: Setup > Users and Permissions > Role Permissions Manager"),
                            _("Select Role: 'Chapter Manager'"),
                            _(
                                "For DocType 'Member': Enable 'User Permission' and set condition: user.chapter == doc.chapter"
                            ),
                            _("For DocType 'Volunteer': Enable 'User Permission' with chapter restriction"),
                            _("Go to: Setup > Users and Permissions > User Permissions"),
                            _(
                                "For each Chapter Manager user, add User Permission for their specific Chapter"
                            ),
                            _("Test cross-chapter access is blocked"),
                        ],
                        "validation": _(
                            "Chapter Manager should only see members from their assigned chapter"
                        ),
                    },
                },
                {
                    "id": "financial_data_isolation",
                    "title": _("Financial Data Isolation"),
                    "severity": "Critical",
                    "description": _("Guest users can view SEPA mandate and financial information"),
                    "risk": _("Financial fraud, privacy violations, regulatory compliance issues"),
                    "solution": {
                        "title": _("Restrict Financial DocType Access"),
                        "steps": [
                            _("Go to: Setup > Users and Permissions > Role Permissions Manager"),
                            _("Select Role: 'Guest'"),
                            _("For DocType 'SEPA Mandate': Remove ALL permissions"),
                            _("For DocType 'Direct Debit Batch': Remove ALL permissions"),
                            _("For DocType 'Sales Invoice': Remove ALL permissions"),
                            _("For DocType 'Payment Entry': Remove ALL permissions"),
                            _("Select Role: 'Verenigingen Member'"),
                            _("For financial DocTypes: Only allow 'read' for own records (if needed)"),
                            _("Test financial data access is properly restricted"),
                        ],
                        "validation": _("Non-financial users should not access payment/mandate information"),
                    },
                },
                {
                    "id": "audit_trail_compliance",
                    "title": _("Audit Trail Compliance"),
                    "severity": "Medium",
                    "description": _("Document version tracking is disabled"),
                    "risk": _("Regulatory compliance gaps, inability to track changes for audit purposes"),
                    "solution": {
                        "title": _("Enable Version Tracking"),
                        "steps": [
                            _("Go to: Setup > System Settings"),
                            _("Check 'Track Changes' option"),
                            _("Go to: Setup > Customize > DocType List"),
                            _("For critical DocTypes (Member, Membership, SEPA Mandate, Volunteer):"),
                            _("  - Open each DocType"),
                            _("  - Check 'Track Changes' in Settings tab"),
                            _("  - Save the DocType"),
                            _("Test: Make changes to member records and verify Version history is created"),
                            _("Go to: Setup > Document > Version to view change history"),
                        ],
                        "validation": _(
                            "Version documents should be created when critical records are modified"
                        ),
                    },
                },
            ],
            "post_configuration": {
                "title": _("Post-Configuration Validation"),
                "description": _(
                    "After implementing the security configurations above, run the security test suite to verify fixes:"
                ),
                "validation_command": "bench --site {site} run-tests --app verenigingen --module verenigingen.tests.backend.security.test_security_core",
                "expected_result": _(
                    "Security tests should show improved results with fewer permission-related failures"
                ),
                "monitoring": [
                    _("Regularly review User Permissions to ensure chapter isolation is maintained"),
                    _("Monitor Version documents to ensure audit trails are functioning"),
                    _("Periodically test guest access to verify data protection"),
                    _("Review Role Permissions after system updates or changes"),
                ],
            },
            "emergency_contacts": {
                "title": _("Support and Escalation"),
                "description": _("If you encounter issues during security configuration:"),
                "contacts": [
                    _("System Administrator: Check logs in Setup > System Console"),
                    _("Database Access: Use bench --site {site} mariadb to verify permission changes"),
                    _("Test Validation: Use security test suite to verify configuration"),
                    _("Documentation: Refer to Frappe Framework security documentation"),
                ],
            },
        }


@frappe.whitelist()
def get_security_configuration_guide():
    """API endpoint to get complete security configuration guide"""
    step = frappe.get_doc("Onboarding Step", "Verenigingen-Configure-Security")
    return step.get_security_checklist()


@frappe.whitelist()
def validate_security_configuration():
    """Validate that security configurations have been applied"""
    issues_found = []

    # Check guest permissions for Member doctype
    guest_member_perms = frappe.get_all(
        "DocPerm", filters={"parent": "Member", "role": "Guest", "read": 1}, fields=["name"]
    )

    if guest_member_perms:
        issues_found.append(
            {
                "issue": "Guest users still have read access to Member records",
                "action": "Remove Guest role permissions for Member DocType",
            }
        )

    # Check if version tracking is enabled
    system_settings = frappe.get_single("System Settings")
    if not system_settings.enable_version_control:
        issues_found.append(
            {"issue": "Version tracking is disabled", "action": "Enable 'Track Changes' in System Settings"}
        )

    # Check if critical DocTypes have tracking enabled
    critical_doctypes = ["Member", "Membership", "SEPA Mandate", "Volunteer"]
    for doctype in critical_doctypes:
        try:
            meta = frappe.get_meta(doctype)
            if not meta.track_changes:
                issues_found.append(
                    {
                        "issue": f"{doctype} DocType does not have change tracking enabled",
                        "action": f"Enable 'Track Changes' for {doctype} DocType in Customize DocType",
                    }
                )
        except Exception:
            # DocType might not exist
            pass

    return {
        "configuration_complete": len(issues_found) == 0,
        "issues_remaining": issues_found,
        "next_steps": "Address remaining issues and re-run validation"
        if issues_found
        else "Security configuration validated successfully",
    }
