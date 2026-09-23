# verenigingen/verenigingen/doctype/chapter_role/chapter_role.py
import frappe
from frappe import _
from frappe.model.document import Document

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


class ChapterRole(Document):
    def validate(self):
        """Validate chapter role settings"""
        self.validate_chair_role()

    def validate_chair_role(self):
        """Validate chair role settings"""
        if self.is_chair and self.is_active:
            # Check for other chair roles
            other_chair_roles = frappe.get_all(
                "Chapter Role",
                filters={"is_chair": 1, "is_active": 1, "name": ["!=", self.name]},
                fields=["name", "role_name"],
            )

            if other_chair_roles:
                # Just log a message - we allow multiple chair roles but warn the user
                frappe.msgprint(
                    _(
                        "There are other roles also marked as Chair: {0}. Having multiple chair roles may cause confusion."
                    ).format(", ".join([r.role_name for r in other_chair_roles])),
                    indicator="orange",
                    alert=True,
                )

    def on_update(self):
        """Update chapter heads if this is a chair role.

        on_update covers inserts as well (run_post_save_methods runs it for a new
        draft), so this must NOT also be registered on after_insert — has_value_changed
        returns True for a new doc, so a dual registration would run the full
        update_chapters_with_role() path twice per newly created chair role.

        NOTE: this used to live in an `after_save()` method, which Frappe never calls
        server-side — Document.run_method() is never invoked with that name — so
        flipping a role to chair never updated the chapters using it. (`after_save` IS
        a real client-side form event; see chapter_role.js.)

        update_chapters_with_role() carries @high_security_api (HIGH). HIGH access
        is granted only through an assigned Role Profile
        (AuthorizationPolicy.PROFILE_ONLY_LEVELS) -- never through a bare role -- but
        this DocType's own permissions (chapter_role.json) grant write/create to the
        BARE roles "System Manager" and "Verenigingen Administrator". So a user
        holding one of those roles without the matching Role Profile can save this
        document (the DocType permission passes) while update_chapters_with_role()
        raises PermissionError internally -- decorators in this app run on internal
        calls too, the same mechanism DirectDebitBatch.on_submit hit (#1224). The
        previous code swallowed that PermissionError -- and every other exception --
        in a bare `except Exception`, so the save silently succeeded while the
        chapter_head propagation silently failed with no trace a user would ever see
        (#1229).

        Like on_submit(), the save must not depend on the propagation succeeding: an
        admin who cannot clear the HIGH gate still gets their Chapter Role change
        saved, but is told -- via msgprint AND an Error Log entry -- that the
        chapter_head propagation did not run, instead of never finding out. The
        permission check runs BEFORE calling update_chapters_with_role(), not a
        broad except after the fact, so a real failure inside it (a bug, not an
        authorisation denial) still propagates instead of being conflated with "no
        permission" (#1224 review commit 6a83f355f) -- and if the check itself
        errors, update_chapters_with_role() is never reached, so the propagation is
        never silently claimed to have run.
        """
        # Check if this is a chair role and was modified
        if not (self.is_chair and self.is_active and self.has_value_changed("is_chair")):
            return

        from verenigingen.utils.security.api_security_framework import can_clear_security_level
        from verenigingen.verenigingen.doctype.chapter_role.chapter_role import (
            update_chapters_with_role,
        )

        if can_clear_security_level(update_chapters_with_role):
            update_chapters_with_role(self.name)
            return

        frappe.msgprint(
            _(
                "Chapters using this role were NOT updated: {0} does not have "
                "permission for this administrative operation (HIGH security level). "
                "A user with the matching Role Profile must save this role again to "
                "apply the change to chapters."
            ).format(frappe.session.user),
            indicator="orange",
            alert=True,
        )
        frappe.log_error(
            title="Chapter Role Update Deferred",
            message=(
                f"Chapter Role {self.name} saved by {frappe.session.user}, who cannot "
                "clear the HIGH security level update_chapters_with_role() requires. "
                "Chapters using this role were not updated with the new chapter_head."
            ),
        )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def update_chapters_with_role(role):
    """
    Update all chapters that have board members with this role
    This is used to update the chapter_head field when a role is marked as chair
    """
    if not frappe.db.exists("Chapter Role", role):
        frappe.throw(_("Invalid Chapter Role"))

    # Get the role document
    role_doc = frappe.get_doc("Chapter Role", role)

    # Find chapters that have board members with this role
    chapter_board_members = frappe.get_all(
        "Chapter Board Member",
        filters={"chapter_role": role, "is_active": 1},
        fields=["parent"],
        distinct=True,
    )

    chapters_found = 0
    chapters_updated = 0

    for cbm in chapter_board_members:
        try:
            chapters_found += 1
            chapter = frappe.get_doc("Chapter", cbm.parent)
            original_head = chapter.chapter_head

            # Call the update method
            chapter.update_chapter_head()

            # If chapter_head changed, save the doc
            if chapter.chapter_head != original_head:
                # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                from verenigingen.utils.secure_operations import secure_document_operation

                # Secure chapter head update with explicit permission validation
                chapter_result = secure_document_operation(
                    operation="save",
                    doc=chapter,
                    justification=f"Chapter head update for {chapter.name} due to chair role change",
                    required_permissions=["Chapter:write"],
                )

                if not chapter_result.success:
                    frappe.logger().error(
                        f"Failed to update chapter head for {chapter.name}: {'; '.join(chapter_result.errors)}"
                    )
                    # Continue processing other chapters even if one fails
                else:
                    chapters_updated += 1

                    # Log the change - create audit trail comment
                    comment_doc = frappe.get_doc(
                        {
                            "doctype": "Comment",
                            "comment_type": "Info",
                            "reference_doctype": "Chapter",
                            "reference_name": chapter.name,
                            "content": _(
                                "Chapter Head changed from {0} to {1} due to chair role update"
                            ).format(original_head or "None", chapter.chapter_head or "None"),
                        }
                    )

                    # Secure comment creation with explicit permission validation
                    comment_result = secure_document_operation(
                        operation="insert",
                        doc=comment_doc,
                        justification=f"Governance audit trail for chapter head change in {chapter.name}",
                        required_permissions=["Comment:create"],
                    )

                    if not comment_result.success:
                        frappe.logger().error(
                            f"Failed to create audit trail comment: {'; '.join(comment_result.errors)}"
                        )
                        # Don't block the operation if audit trail fails

        except Exception as e:
            frappe.log_error(
                message=f"Error updating chapter {cbm.parent} with role {role}: {str(e)}",
                title="Chapter Head Update Error",
            )

    return {
        "chapters_found": chapters_found,
        "chapters_updated": chapters_updated,
        "role": role,
        "is_chair": role_doc.is_chair,
    }
