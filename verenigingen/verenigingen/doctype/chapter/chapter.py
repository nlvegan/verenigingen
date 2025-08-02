# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""
Chapter DocType Implementation

This module implements the Chapter DocType for the Verenigingen association
management system. It represents local chapters/branches of the organization
with comprehensive management capabilities including board management, member
coordination, and communication systems.

Key Features:
    - Board member management with role-based permissions
    - Member registration and coordination
    - Communication and announcement systems
    - Volunteer integration and coordination
    - Website integration with public chapter pages
    - Financial tracking and reporting

Architecture:
    - Manager Pattern: Delegates specific responsibilities to specialized managers
    - Validator Pattern: Centralized validation logic with comprehensive error handling
    - Website Generator: Automatic public website page generation
    - Event-driven: Hooks into document lifecycle for automated processing

Manager Components:
    - BoardManager: Handles board member appointments and permissions
    - MemberManager: Manages chapter membership and registration
    - CommunicationManager: Handles announcements and member communication
    - VolunteerIntegrationManager: Coordinates with volunteer management system
    - ChapterValidator: Comprehensive validation and business rule enforcement

Business Logic:
    - Chapter autonomy with central coordination
    - Board member role and permission management
    - Member application approval workflows
    - Financial dues and payment coordination
    - Event and activity management

Security Model:
    - Role-based access control for board positions
    - Chapter-specific permission scoping
    - Audit logging for sensitive operations
    - Validation of board member authorities

Integration Points:
    - Member DocType for membership management
    - Volunteer system for activity coordination
    - Financial systems for dues and payments
    - Communication systems for announcements
    - Website generator for public presence

Author: Verenigingen Development Team
License: MIT
"""

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.utils import getdate, now, today
from frappe.website.website_generator import WebsiteGenerator

from verenigingen.utils.error_handling import handle_api_error, log_error

# Import managers and validators
from .managers import BoardManager, CommunicationManager, MemberManager, VolunteerIntegrationManager
from .validators import ChapterValidator


class Chapter(WebsiteGenerator):
    """
    Chapter document with refactored manager pattern

    Core responsibilities:
    - Document lifecycle (validate, save, etc.)
    - Manager coordination
    - Public API compatibility

    Delegated responsibilities:
    - Board management -> BoardManager
    - Member management -> MemberManager
    - Communications -> CommunicationManager
    - Volunteer integration -> VolunteerIntegrationManager
    - Validation -> ChapterValidator
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._managers = {}
        self._validator = None

    # ========================================================================
    # CORE DOCUMENT LIFECYCLE
    # ========================================================================

    def validate(self):
        """Main validation - streamlined workflow with centralized error handling"""
        # Basic validations
        self._ensure_route()
        self._auto_fix_required_fields()

        # Comprehensive validation using validator - streamlined approach
        validation_result = self.validator.validate_before_save()
        self._process_validation_result(validation_result)

        # Handle board member changes (delegation to managers)
        self._handle_document_changes()

    def _process_validation_result(self, validation_result):
        """Process validation results with proper error handling"""
        if not validation_result.is_valid:
            # Log warnings but don't block save
            for warning in validation_result.warnings:
                frappe.msgprint(warning, indicator="orange", alert=True)

            # Throw errors that block save
            if validation_result.errors:
                error_context = {"chapter": self.name, "errors": validation_result.errors}
                log_error(
                    frappe.ValidationError(", ".join(validation_result.errors)),
                    context=error_context,
                    module="verenigingen.doctype.chapter",
                )
                frappe.throw(_("Validation failed: {0}").format(", ".join(validation_result.errors)))

    def before_save(self):
        """Before save hook - streamlined with safe manager operations"""
        old_doc = self.get_doc_before_save()
        if old_doc:
            self._safe_manager_operation(
                "board_member_changes", lambda: self.board_manager.handle_board_member_changes(old_doc)
            )
            self._safe_manager_operation(
                "board_member_additions", lambda: self.board_manager.handle_board_member_additions(old_doc)
            )

    def after_save(self):
        """After save hook - streamlined with safe operations"""
        # Sync with volunteer system if needed
        if self.has_value_changed("board_members"):
            self._safe_manager_operation(
                "volunteer_sync",
                lambda: self.volunteer_integration_manager.sync_board_members_with_volunteer_system(),
            )

    def _safe_manager_operation(self, operation_name: str, operation_func):
        """Execute manager operation safely with proper error handling"""
        try:
            operation_func()
        except Exception as e:
            error_context = {"chapter": self.name, "operation": operation_name}
            log_error(e, context=error_context, module="verenigingen.doctype.chapter")
            # Don't block save for manager operation errors, just log them

    def on_update(self):
        """On update hook"""
        self._clear_manager_caches()

    # ========================================================================
    # MANAGER PROPERTIES (Lazy Loading)
    # ========================================================================

    @property
    def board_manager(self) -> BoardManager:
        """Get board manager instance"""
        if "board" not in self._managers:
            self._managers["board"] = BoardManager(self)
        return self._managers["board"]

    @property
    def member_manager(self) -> MemberManager:
        """Get member manager instance"""
        if "member" not in self._managers:
            self._managers["member"] = MemberManager(self)
        return self._managers["member"]

    @property
    def communication_manager(self) -> CommunicationManager:
        """Get communication manager instance"""
        if "communication" not in self._managers:
            self._managers["communication"] = CommunicationManager(self)
        return self._managers["communication"]

    @property
    def volunteer_integration_manager(self) -> VolunteerIntegrationManager:
        """Get volunteer integration manager instance"""
        if "volunteer_integration" not in self._managers:
            self._managers["volunteer_integration"] = VolunteerIntegrationManager(self)
        return self._managers["volunteer_integration"]

    @property
    def validator(self) -> ChapterValidator:
        """Get validator instance"""
        if self._validator is None:
            self._validator = ChapterValidator(self)
        return self._validator

    # ========================================================================
    # BOARD MANAGEMENT API (Delegated)
    # ========================================================================

    @frappe.whitelist()
    def add_board_member(self, volunteer, role, from_date=None, to_date=None):
        """Add a new board member - delegates to BoardManager"""
        return self.board_manager.add_board_member(volunteer, role, from_date, to_date)

    @frappe.whitelist()
    def remove_board_member(self, volunteer, end_date=None):
        """Remove a board member - delegates to BoardManager"""
        return self.board_manager.remove_board_member(volunteer, end_date)

    @frappe.whitelist()
    def transition_board_role(self, volunteer, new_role, transition_date=None):
        """Transition a board member's role - delegates to BoardManager"""
        return self.board_manager.transition_board_role(volunteer, new_role, transition_date)

    @frappe.whitelist()
    def bulk_remove_board_members(self, board_members):
        """Bulk remove board members - delegates to BoardManager"""
        return self.board_manager.bulk_remove_board_members(board_members)

    @frappe.whitelist()
    def bulk_deactivate_board_members(self, board_members):
        """Bulk deactivate board members - delegates to BoardManager"""
        return self.board_manager.bulk_deactivate_board_members(board_members)

    @frappe.whitelist()
    def sync_board_members(self):
        """Sync board members with volunteer system - delegates to VolunteerIntegrationManager"""
        return self.volunteer_integration_manager.sync_board_members_with_volunteer_system()

    @frappe.whitelist()
    def update_volunteer_assignment_history(self, volunteer_id, role, start_date, end_date):
        """Update volunteer assignment history - delegates to BoardManager"""
        return self.board_manager.update_volunteer_assignment_history(
            volunteer_id, role, start_date, end_date
        )

    def get_board_members(self, include_inactive=False, role=None):
        """Get board members - delegates to BoardManager"""
        return self.board_manager.get_board_members(include_inactive, role)

    def is_board_member(self, member_name=None, user=None, volunteer_name=None):
        """Check if user is board member - delegates to BoardManager"""
        return self.board_manager.is_board_member(member_name, user, volunteer_name)

    def get_member_role(self, member_name=None, user=None, volunteer_name=None):
        """Get member's board role - delegates to BoardManager"""
        return self.board_manager.get_member_role(member_name, user, volunteer_name)

    def can_view_member_payments(self, member_name=None, user=None):
        """Check payment viewing permissions - delegates to BoardManager"""
        return self.board_manager.can_view_member_payments(member_name, user)

    def get_active_board_roles(self):
        """Get active board roles - delegates to BoardManager"""
        return self.board_manager.get_active_board_roles()

    # ========================================================================
    # MEMBER MANAGEMENT API (Delegated)
    # ========================================================================

    def add_member(self, member_id, introduction=None, website_url=None):
        """Add member to chapter - delegates to MemberManager"""
        result = self.member_manager.add_member(member_id, introduction, website_url)
        return result.get("success", False)

    def remove_member(self, member_id, leave_reason=None):
        """Remove member from chapter - delegates to MemberManager"""
        result = self.member_manager.remove_member(member_id, leave_reason)
        return result.get("success", False)

    def get_members(self, include_disabled=False):
        """Get chapter members - delegates to MemberManager"""
        return self.member_manager.get_members(include_disabled, with_details=True)

    @frappe.whitelist()
    def bulk_add_members(self, member_data_list):
        """Bulk add members - delegates to MemberManager"""
        return self.member_manager.bulk_add_members(member_data_list)

    # ========================================================================
    # COMMUNICATION API (Delegated)
    # ========================================================================

    def notify_board_member_added(self, volunteer, role):
        """Notify board member added - delegates to CommunicationManager"""
        self.communication_manager.notify_board_member_added(volunteer, role)

    def notify_board_member_removed(self, volunteer):
        """Notify board member removed - delegates to CommunicationManager"""
        self.communication_manager.notify_board_member_removed(volunteer)

    @frappe.whitelist()
    def send_chapter_newsletter(self, subject, content, recipient_filter="all"):
        """Send newsletter - delegates to CommunicationManager"""
        return self.communication_manager.send_chapter_newsletter(subject, content, recipient_filter)

    def get_communication_history(self, limit=50):
        """Get communication history - delegates to CommunicationManager"""
        return self.communication_manager.get_communication_history(limit)

    # ========================================================================
    # VALIDATION API (Delegated)
    # ========================================================================

    @frappe.whitelist()
    def validate_postal_codes(self):
        """Validate postal codes"""
        try:
            if self.postal_codes:
                result = self.validator.postal_validator.validate_postal_codes(self.postal_codes)
                if not result.is_valid:
                    return False
                return True
            return True
        except Exception as e:
            frappe.log_error(f"Error validating postal codes for {self.name}: {str(e)}")
            return False

    def matches_postal_code(self, postal_code):
        """Check if postal code matches chapter patterns"""
        return self.validator.validate_postal_code_match(postal_code)

    # ========================================================================
    # CORE CHAPTER FUNCTIONALITY (Kept in main class)
    # ========================================================================

    def update_chapter_head(self):
        """Update chapter_head based on board members with chair roles using atomic operations"""
        try:
            # Use atomic transaction to prevent race conditions
            frappe.db.begin()
            try:
                old_head = self.chapter_head

                if not self.board_members:
                    self.chapter_head = None
                    return False

                # Use single optimized query to get chair member
                chair_member = self.get_chapter_chair_optimized()

                if chair_member:
                    self.chapter_head = chair_member
                    chair_found = True
                else:
                    self.chapter_head = None
                    chair_found = False

                # Log change if head changed
                if old_head != self.chapter_head:
                    frappe.logger().info(
                        f"Chapter head updated for {self.name}: {old_head} -> {self.chapter_head}"
                    )

                return chair_found

            except Exception as transaction_error:
                # Rollback the transaction on error
                frappe.db.rollback()
                raise transaction_error

        except Exception as e:
            frappe.log_error(f"Error updating chapter head for {self.name}: {str(e)}")
            return False

    def get_chapter_chair_optimized(self):
        """Optimized single query to find chapter chair member"""
        if not self.board_members:
            return None

        # Extract active volunteers and roles
        active_board_data = []
        for board_member in self.board_members:
            if board_member.is_active and board_member.chapter_role and board_member.volunteer:
                active_board_data.append((board_member.volunteer, board_member.chapter_role))

        if not active_board_data:
            return None

        # Use single optimized query to find chair - modernized with proper escaping
        volunteer_list = [frappe.db.escape(v[0]) for v in active_board_data]
        role_list = [frappe.db.escape(v[1]) for v in active_board_data]

        chair_query = f"""
            SELECT v.member
            FROM `tabVolunteer` v
            JOIN `tabChapter Role` cr ON cr.name IN ({', '.join(role_list)})
            WHERE v.name IN ({', '.join(volunteer_list)})
            AND cr.is_chair = 1
            AND cr.is_active = 1
            AND v.member IS NOT NULL
            LIMIT 1
        """

        result = frappe.db.sql(chair_query, as_dict=True)
        return result[0].member if result else None

    def get_context(self, context):
        """Get context for web view with optimized data loading"""
        try:
            context.no_cache = True
            context.show_sidebar = True
            context.parents = [dict(label="View All Chapters", route="chapters", title="View Chapters")]

            # Use optimized permission checking
            user_permissions = self.get_user_permissions_optimized()

            context.is_board_member = user_permissions["is_board_member"]
            context.board_role = user_permissions["board_role"]
            context.is_system_manager = user_permissions["is_system_manager"]
            context.can_write_chapter = user_permissions["can_write_chapter"]

            # Only load sensitive member data if user has appropriate permissions
            if user_permissions["can_view_members"]:
                # Use optimized batch loading for member data
                context.members = self.get_members_optimized()
                context.board_members = self.get_board_members_optimized()
            else:
                # Regular members cannot see member lists
                context.members = []
                context.board_members = []

            # Add chapter head member details with optimized loading
            context.chapter_head_member = self.get_chapter_head_member_optimized()

            return context

        except Exception as e:
            frappe.log_error(f"Error getting context for chapter {self.name}: {str(e)}")
            # Return minimal context to prevent page crash
            context.members = []
            context.board_members = []
            context.is_board_member = False
            context.board_role = None
            context.chapter_head_member = None
            return context

    def get_user_permissions_optimized(self):
        """Single query to get all user permissions for this chapter"""
        try:
            user = frappe.session.user
            user_roles = frappe.get_roles(user)

            is_system_manager = "System Manager" in user_roles
            is_verenigingen_manager = "Verenigingen Administrator" in user_roles

            if is_system_manager or is_verenigingen_manager:
                return {
                    "is_board_member": True,
                    "board_role": "Admin",
                    "is_system_manager": is_system_manager,
                    "can_write_chapter": True,
                    "can_view_members": True,
                }

            # Single query to check board membership and get role
            board_query = """
                SELECT cbm.chapter_role, cbm.is_active
                FROM `tabChapter Board Member` cbm
                JOIN `tabVolunteer` v ON cbm.volunteer = v.name
                JOIN `tabMember` m ON v.member = m.name
                WHERE m.user = %s AND cbm.parent = %s AND cbm.is_active = 1
                LIMIT 1
            """

            board_result = frappe.db.sql(board_query, (user, self.name), as_dict=True)

            is_board_member = bool(board_result)
            board_role = board_result[0].chapter_role if board_result else None

            return {
                "is_board_member": is_board_member,
                "board_role": board_role,
                "is_system_manager": is_system_manager,
                "can_write_chapter": frappe.has_permission("Chapter", doc=self.name, ptype="write"),
                "can_view_members": is_board_member or is_system_manager or is_verenigingen_manager,
            }

        except Exception as e:
            frappe.log_error(f"Error getting user permissions for chapter {self.name}: {str(e)}")
            return {
                "is_board_member": False,
                "board_role": None,
                "is_system_manager": False,
                "can_write_chapter": False,
                "can_view_members": False,
            }

    def get_members_optimized(self):
        """Optimized query to get chapter members with details"""
        try:
            return self.member_manager.get_members(with_details=True)
        except Exception as e:
            frappe.log_error(f"Error getting optimized members for chapter {self.name}: {str(e)}")
            return []

    def get_board_members_optimized(self):
        """Optimized query to get board members with details"""
        try:
            return self.board_manager.get_board_members()
        except Exception as e:
            frappe.log_error(f"Error getting optimized board members for chapter {self.name}: {str(e)}")
            return []

    def get_chapter_head_member_optimized(self):
        """Optimized loading of chapter head member"""
        if not self.chapter_head:
            return None

        try:
            return frappe.get_doc("Member", self.chapter_head)
        except frappe.DoesNotExistError:
            frappe.log_error(f"Chapter head member {self.chapter_head} not found for chapter {self.name}")
            return None
        except Exception as e:
            frappe.log_error(f"Error loading chapter head member {self.chapter_head}: {str(e)}")
            return None

    # ========================================================================
    # UTILITY METHODS
    # ========================================================================

    def _auto_fix_required_fields(self):
        """Auto-fix missing required fields if possible"""
        try:
            # Auto-fix missing region
            if not self.region:
                if hasattr(self, "name") and self.name:
                    if "test" in self.name.lower():
                        # Use the actual test region name from database
                        test_region = frappe.db.get_value("Region", {"region_code": "TR"}, "name")
                        self.region = test_region or "test-region"
                        frappe.log_error(f"Auto-fixed missing region for test chapter {self.name}")
                    elif not self.get("__islocal"):  # If not a new document
                        # For existing documents, use a generic region
                        self.region = "Unspecified Region"
                        frappe.log_error(f"Auto-fixed missing region for existing chapter {self.name}")
                else:
                    # For new documents without region, set default
                    self.region = "General"
                    frappe.log_error("Auto-fixed missing region for new chapter")

            # Auto-fix missing introduction for unpublished chapters
            if not self.introduction and not self.published:
                if hasattr(self, "name") and self.name and "test" in self.name.lower():
                    self.introduction = f"This is a test chapter: {self.name}"
                    frappe.log_error(f"Auto-fixed missing introduction for test chapter {self.name}")
                else:
                    self.introduction = "Chapter introduction will be added soon."
                    frappe.log_error(
                        f"Auto-fixed missing introduction for chapter {getattr(self, 'name', 'unnamed')}"
                    )

        except Exception as e:
            frappe.log_error(f"Error auto-fixing chapter fields: {str(e)}")

    def _ensure_route(self):
        """Ensure route is set"""
        if not self.route:
            self.route = "chapters/" + self.scrub(self.name)

    def _handle_document_changes(self):
        """Handle changes between document versions"""
        old_doc = self.get_doc_before_save()
        if old_doc:
            # Handle board member changes
            self.board_manager.handle_board_member_changes(old_doc)
            self.board_manager.handle_board_member_additions(old_doc)

            # Handle regular member changes
            self.member_manager.handle_member_changes(old_doc)
            self.member_manager.handle_member_additions(old_doc)

    def _clear_manager_caches(self):
        """Clear all manager caches"""
        for manager in self._managers.values():
            if hasattr(manager, "clear_cache"):
                manager.clear_cache()

    # ========================================================================
    # BACKWARD COMPATIBILITY METHODS
    # ========================================================================

    # Keep some key methods for backward compatibility
    def _add_to_members(self, member_id):
        """Backward compatibility - delegates to MemberManager"""
        return self.member_manager.add_member(member_id)

    # ========================================================================
    # DASHBOARD AND STATISTICS
    # ========================================================================

    def get_chapter_statistics(self):
        """Get comprehensive chapter statistics"""
        try:
            return {
                "board_stats": self.board_manager.get_summary(),
                "member_stats": self.member_manager.get_summary(),
                "communication_stats": self.communication_manager.get_summary(),
                "volunteer_integration_stats": self.volunteer_integration_manager.get_summary(),
                "last_updated": getdate(now()),
            }
        except Exception as e:
            frappe.log_error(f"Error getting statistics for chapter {self.name}: {str(e)}")
            return {
                "board_stats": {},
                "member_stats": {},
                "communication_stats": {},
                "volunteer_integration_stats": {},
                "last_updated": getdate(today()),
            }


# ============================================================================
# UTILITY FUNCTIONS (Unchanged from original)
# ============================================================================


def validate_chapter_access(doc, method=None):
    """Validate chapter access permissions"""
    try:
        if frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles():
            return

        settings = frappe.get_single("Verenigingen Settings")
        if not settings.get("national_board_chapter"):
            return

        if doc.name == settings.national_board_chapter:
            user_roles = frappe.get_roles()
            if "Verenigingen Administrator" in user_roles and "System Manager" not in user_roles:
                frappe.throw(
                    _(
                        "Verenigingen Administrators cannot edit the National Board chapter. Please contact an administrator."
                    )
                )

    except Exception as e:
        frappe.log_error(f"Error validating chapter access for {doc.name}: {str(e)}")
        # Don't block access on validation errors


def get_list_context(context):
    """Get list context for chapter list view"""
    context.allow_guest = True
    context.no_cache = True
    context.show_sidebar = True
    context.title = "All Chapters"
    context.no_breadcrumbs = True
    context.order_by = "creation desc"

    # Get current user's member chapters
    context.user_chapters = []
    if frappe.session.user != "Guest":
        member = frappe.db.get_value("Member", {"email": frappe.session.user}, "name")
        if member:
            context.user_chapters = frappe.get_all(
                "Chapter Member", filters={"member": member, "enabled": 1}, pluck="parent"
            )


def get_chapter_permission_query_conditions(user=None):
    """Get permission query conditions for Chapters with optimized single query"""
    try:
        if not user:
            user = frappe.session.user

        if "System Manager" in frappe.get_roles(user) or "Verenigingen Administrator" in frappe.get_roles(
            user
        ):
            return ""

        # For regular users and members, show all published chapters
        # This allows users to see all chapters on the listing page
        return "`tabChapter`.published = 1"

    except Exception as e:
        frappe.log_error(f"Error in chapter permission query: {str(e)}")
        return "`tabChapter`.published = 1"


def get_user_accessible_chapters_optimized(user):
    """Single optimized query to get all chapters accessible to a user"""
    try:
        # Single query to get both board and member chapters
        query = """
            SELECT DISTINCT chapter_name FROM (
                SELECT cbm.parent as chapter_name
                FROM `tabChapter Board Member` cbm
                JOIN `tabVolunteer` v ON cbm.volunteer = v.name
                JOIN `tabMember` m ON v.member = m.name
                WHERE m.user = %s AND cbm.is_active = 1

                UNION

                SELECT cm.parent as chapter_name
                FROM `tabChapter Member` cm
                JOIN `tabMember` m ON cm.member = m.name
                WHERE m.user = %s AND cm.enabled = 1
            ) as accessible_chapters
        """

        result = frappe.db.sql(query, (user, user), as_dict=True)
        return [chapter.chapter_name for chapter in result]

    except Exception as e:
        frappe.log_error(f"Error in optimized chapter access query: {str(e)}")
        return []


@frappe.whitelist()
def leave(title, member_id, leave_reason):
    """Leave a chapter"""
    try:
        if not title or not member_id:
            frappe.throw(_("Chapter and Member ID are required"))

        chapter = frappe.get_doc("Chapter", title)
        return chapter.member_manager.remove_member(member_id, leave_reason)

    except frappe.DoesNotExistError:
        frappe.throw(_("Chapter {0} not found").format(title))
    except Exception as e:
        frappe.log_error(f"Error removing member {member_id} from chapter {title}: {str(e)}")
        frappe.throw(_("An error occurred while leaving the chapter"))


@frappe.whitelist()
def get_board_memberships(member_name):
    """Get board memberships for a member"""
    try:
        if not member_name:
            return []

        # Check if user has permission to view member information
        current_user = frappe.session.user
        user_roles = frappe.get_roles(current_user)

        # Allow if user is System Manager or Verenigingen Administrator
        if "System Manager" in user_roles or "Verenigingen Administrator" in user_roles:
            pass  # Full access
        else:
            # Check if user is requesting their own board memberships
            current_member = frappe.db.get_value("Member", {"user": current_user}, "name")
            if current_member != member_name:
                # Check if user is a board member of any chapter that this member belongs to
                member_chapters = frappe.db.sql(
                    """
                    SELECT parent FROM `tabChapter Member`
                    WHERE member = %s AND enabled = 1
                """,
                    (member_name,),
                    as_dict=True,
                )

                user_board_chapters = []
                if current_member:
                    # Get volunteer linked to this member
                    current_volunteer = frappe.db.get_value("Volunteer", {"member": current_member}, "name")
                    if current_volunteer:
                        user_board_chapters = frappe.db.sql(
                            """
                            SELECT parent FROM `tabChapter Board Member`
                            WHERE volunteer = %s AND is_active = 1
                        """,
                            (current_volunteer,),
                            as_dict=True,
                        )

                # Check if user has board access to any of the chapters this member belongs to
                has_access = False
                for member_chapter in member_chapters:
                    for user_chapter in user_board_chapters:
                        if member_chapter.parent == user_chapter.parent:
                            has_access = True
                            break
                    if has_access:
                        break

                if not has_access:
                    frappe.throw(_("You don't have permission to view this member's board information"))

        # First find the volunteer record for this member
        volunteer_name = frappe.db.get_value("Volunteer", {"member": member_name}, "name")
        if not volunteer_name:
            return []

        CBM = DocType("Chapter Board Member")
        board_memberships = (
            frappe.qb.from_(CBM)
            .select(CBM.parent, CBM.chapter_role)
            .where((CBM.volunteer == volunteer_name) & (CBM.is_active == 1))
        ).run(as_dict=True)

        return board_memberships

    except Exception as e:
        frappe.log_error(f"Error getting board memberships for {member_name}: {str(e)}")
        return []


@frappe.whitelist()
def remove_from_board(chapter_name, member_name, end_date=None):
    """Remove a member from the board"""
    try:
        if not chapter_name or not member_name:
            frappe.throw(_("Chapter and Member names are required"))

        chapter = frappe.get_doc("Chapter", chapter_name)
        return chapter.remove_board_member(member_name, end_date)

    except frappe.DoesNotExistError:
        frappe.throw(_("Chapter {0} not found").format(chapter_name))
    except Exception as e:
        frappe.log_error(f"Error removing {member_name} from board of {chapter_name}: {str(e)}")
        frappe.throw(_("An error occurred while removing the board member"))


@frappe.whitelist()
def get_chapter_board_history(chapter_name):
    """Get complete board history for a chapter"""
    try:
        if not chapter_name:
            frappe.throw(_("Chapter name is required"))

        # Check if user has permission to view chapter board information
        current_user = frappe.session.user
        user_roles = frappe.get_roles(current_user)

        # Allow if user is System Manager or Verenigingen Administrator
        if "System Manager" in user_roles or "Verenigingen Administrator" in user_roles:
            pass  # Full access
        else:
            # Check if user is a board member of this chapter
            current_member = frappe.db.get_value("Member", {"user": current_user}, "name")
            if current_member:
                # Get volunteer linked to this member
                current_volunteer = frappe.db.get_value("Volunteer", {"member": current_member}, "name")
                is_board_member = False
                if current_volunteer:
                    is_board_member = frappe.db.exists(
                        "Chapter Board Member",
                        {"parent": chapter_name, "volunteer": current_volunteer, "is_active": 1},
                    )
                if not is_board_member:
                    frappe.throw(_("You don't have permission to view board history for this chapter"))
            else:
                frappe.throw(_("You don't have permission to view board history"))

        chapter = frappe.get_doc("Chapter", chapter_name)
        return chapter.get_board_members(include_inactive=True)

    except frappe.DoesNotExistError:
        frappe.throw(_("Chapter {0} not found").format(chapter_name))
    except Exception as e:
        frappe.log_error(f"Error getting board history for {chapter_name}: {str(e)}")
        return []


@frappe.whitelist()
def get_chapter_stats(chapter_name):
    """Get statistics for a chapter"""
    try:
        if not chapter_name:
            frappe.throw(_("Chapter name is required"))

        chapter = frappe.get_doc("Chapter", chapter_name)
        return chapter.get_chapter_statistics()

    except frappe.DoesNotExistError:
        frappe.throw(_("Chapter {0} not found").format(chapter_name))
    except Exception as e:
        frappe.log_error(f"Error getting statistics for {chapter_name}: {str(e)}")
        return {}


@frappe.whitelist()
def get_chapters_by_postal_code(postal_code):
    """Get chapters that match a postal code"""
    if not postal_code:
        return []

    chapters = frappe.get_all(
        "Chapter", filters={"published": 1}, fields=["name", "region", "postal_codes", "introduction"]
    )

    matching_chapters = []

    for chapter in chapters:
        if not chapter.get("postal_codes"):
            continue

        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        if chapter_doc.matches_postal_code(postal_code):
            matching_chapters.append(chapter)

    return matching_chapters


@frappe.whitelist()
def suggest_chapters_for_member(member, postal_code=None, state=None, city=None):
    """Suggest appropriate chapters for a member based on location data"""
    if not is_chapter_management_enabled():
        return []

    # If no explicit location data provided, try to get it from member's address
    if not postal_code and not state and not city:
        member_doc = frappe.get_doc("Member", member)
        if member_doc.primary_address:
            try:
                address_doc = frappe.get_doc("Address", member_doc.primary_address)
                postal_code = address_doc.pincode
                state = address_doc.state
                city = address_doc.city
            except Exception as e:
                frappe.log_error(f"Error fetching address for member {member}: {str(e)}")

        # Fallback to member's direct postal code field
        if not postal_code and hasattr(member_doc, "pincode"):
            postal_code = member_doc.pincode

    # Return format expected by JavaScript (list of chapter suggestions)
    matching_chapters = []

    if postal_code:
        chapters_by_postal = get_chapters_by_postal_code(postal_code)
        for chapter in chapters_by_postal:
            matching_chapters.append(
                {
                    "name": chapter.get("name"),
                    "city": chapter.get("region", ""),
                    "state": chapter.get("region", ""),
                    "match_score": 90,  # High score for postal code match
                    "distance": "Unknown",  # Could be calculated if needed
                }
            )

    # If no postal code matches, try region/city matching
    if not matching_chapters:
        all_chapters = frappe.get_all(
            "Chapter", filters={"published": 1}, fields=["name", "region", "postal_codes", "introduction"]
        )

        for chapter in all_chapters:
            score = 0
            if state and chapter.get("region"):
                if state.lower() in chapter.get("region").lower():
                    score += 40
                elif chapter.get("region").lower() in state.lower():
                    score += 30

            if city and chapter.get("region"):
                if city.lower() in chapter.get("region").lower():
                    score += 35
                elif city.lower() in chapter.get("name").lower():
                    score += 45

            if score > 0:
                matching_chapters.append(
                    {
                        "name": chapter.get("name"),
                        "city": chapter.get("region", ""),
                        "state": chapter.get("region", ""),
                        "match_score": score,
                        "distance": "Unknown",
                    }
                )

    # Sort by match score descending
    matching_chapters.sort(key=lambda x: x.get("match_score", 0), reverse=True)

    return matching_chapters


@frappe.whitelist()
def suggest_chapter_for_member(member_name, postal_code=None, state=None, city=None):
    """Legacy function - calls the new suggest_chapters_for_member"""
    return suggest_chapters_for_member(member_name, postal_code, state, city)


def is_chapter_management_enabled():
    """Check if chapter management is enabled in settings"""
    try:
        return frappe.db.get_single_value("Verenigingen Settings", "enable_chapter_management") == 1
    except Exception:
        return True


@frappe.whitelist()
def assign_member_to_chapter(member, chapter, note=None):
    """Assign a member to a chapter"""
    if not member or not chapter:
        frappe.throw(_("Member and Chapter are required"))

    chapter_doc = frappe.get_doc("Chapter", chapter)
    added = chapter_doc.add_member(member)

    # Update chapter tracking fields on member using document instead of direct DB update
    member_doc = frappe.get_doc("Member", member)
    member_doc.chapter_change_reason = note or f"Assigned to {chapter}"
    member_doc.chapter_assigned_by = frappe.session.user

    # Force update chapter display
    member_doc._chapter_assignment_in_progress = True
    member_doc.update_current_chapter_display()

    member_doc.save(ignore_permissions=True)

    if note:
        frappe.get_doc(
            {
                "doctype": "Comment",
                "comment_type": "Info",
                "reference_doctype": "Member",
                "reference_name": member,
                "content": _("Changed chapter to {0}. Note: {1}").format(chapter, note),
            }
        ).insert(ignore_permissions=True)

    return {"success": True, "added_to_members": added}


@frappe.whitelist()
def join_chapter(member_name, chapter_name, introduction=None, website_url=None):
    """Web method for a member to join a chapter via portal"""
    # Use centralized chapter membership manager for consistency
    from verenigingen.utils.chapter_membership_manager import ChapterMembershipManager

    result = ChapterMembershipManager.join_chapter(
        member_id=member_name,
        chapter_name=chapter_name,
        introduction=introduction,
        website_url=website_url,
        user_email=frappe.session.user,
    )

    return {"success": result.get("success", False), "added": result.get("action") == "added"}


@frappe.whitelist()
def leave_chapter(member_name, chapter_name, leave_reason=None):
    """Web method for a member to leave a chapter via portal"""
    # Use centralized chapter membership manager for consistency
    from verenigingen.utils.chapter_membership_manager import ChapterMembershipManager

    result = ChapterMembershipManager.leave_chapter(
        member_id=member_name,
        chapter_name=chapter_name,
        leave_reason=leave_reason,
        user_email=frappe.session.user,
    )

    return {
        "success": result.get("success", False),
        "removed": result.get("action") in ["removed", "disabled"],
    }


@frappe.whitelist()
def assign_member_to_chapter_with_cleanup(member, chapter, note=None):
    """Assign a member to a chapter with automatic cleanup of existing memberships"""
    if not member or not chapter:
        frappe.throw(_("Member and Chapter are required"))

    try:
        cleanup_performed = False

        # 1. Check for existing chapter memberships and end them
        existing_memberships = frappe.get_all(
            "Chapter Member", filters={"member": member, "enabled": 1}, fields=["parent", "name"]
        )

        for membership in existing_memberships:
            if membership.parent != chapter:  # Don't remove from target chapter
                try:
                    # Try to use chapter's remove_member method first
                    old_chapter_doc = frappe.get_doc("Chapter", membership.parent)
                    old_chapter_doc.remove_member(member, leave_reason=f"Reassigned to {chapter}")
                    cleanup_performed = True

                    frappe.logger().info(f"Removed member {member} from chapter {membership.parent}")
                except Exception as e:
                    # If chapter method fails, disable the membership directly
                    try:
                        frappe.db.set_value("Chapter Member", membership.name, "enabled", 0)
                        frappe.db.set_value(
                            "Chapter Member", membership.name, "leave_reason", f"Reassigned to {chapter}"
                        )
                        frappe.db.commit()
                        cleanup_performed = True

                        frappe.logger().info(
                            f"Directly disabled membership {membership.name} for member {member}"
                        )
                    except Exception as e2:
                        frappe.logger().error(
                            f"Error removing member from chapter {membership.parent}: {str(e)} and {str(e2)}"
                        )
            else:
                # Member is already in target chapter, just note this
                frappe.logger().info(f"Member {member} is already in target chapter {chapter}")

        # 2. Check for board memberships and end them
        # Get volunteer linked to this member
        volunteer_name = frappe.db.get_value("Volunteer", {"member": member}, "name")
        board_memberships = []
        if volunteer_name:
            board_memberships = frappe.get_all(
                "Chapter Board Member",
                filters={"volunteer": volunteer_name, "is_active": 1},
                fields=["name", "parent"],
            )

        for board_membership in board_memberships:
            try:
                board_doc = frappe.get_doc("Chapter Board Member", board_membership.name)
                board_doc.is_active = 0
                board_doc.to_date = today()
                board_doc.notes = (board_doc.notes or "") + f"\nEnded due to member reassignment to {chapter}"
                board_doc.save()
                cleanup_performed = True

                frappe.logger().info(f"Ended board membership {board_membership.name} for member {member}")
            except Exception as e:
                frappe.logger().error(f"Error ending board membership {board_membership.name}: {str(e)}")

        # 3. Check if member is already in target chapter
        already_in_target = any(m.parent == chapter for m in existing_memberships)

        if already_in_target and len(existing_memberships) == 1:
            # Member is already in target chapter and it's their only chapter
            result = {"success": True, "added_to_members": False, "cleanup_performed": cleanup_performed}

            if cleanup_performed:
                result["message"] = _("Member was already in {0}. Board roles have been ended.").format(
                    chapter
                )
            else:
                result["message"] = _("Member is already assigned to {0}").format(chapter)
        elif already_in_target and len(existing_memberships) > 1:
            # Member is in target chapter plus others - cleanup was performed
            result = {
                "success": True,
                "added_to_members": False,
                "cleanup_performed": True,  # Force true since we cleaned up other chapters
            }
            result["message"] = _(
                "Member was already in {0}. Other chapter memberships and board roles have been ended."
            ).format(chapter)
        else:
            # Assign to new chapter
            result = assign_member_to_chapter(member, chapter, note)

            if result.get("success"):
                result["cleanup_performed"] = cleanup_performed

                # Add detailed message
                if cleanup_performed:
                    result["message"] = _(
                        "Member successfully assigned to {0}. Previous memberships and board roles have been ended."
                    ).format(chapter)
                else:
                    result["message"] = _("Member successfully assigned to {0}").format(chapter)

        return result

    except Exception as e:
        frappe.logger().error(f"Error in assign_member_to_chapter_with_cleanup: {str(e)}")
        return {"success": False, "message": str(e)}
