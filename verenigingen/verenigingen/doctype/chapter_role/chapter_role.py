# verenigingen/verenigingen/doctype/chapter_role/chapter_role.py
import frappe
from frappe import _
from frappe.model.document import Document


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

    def after_save(self):
        """Update chapter heads if this is a chair role"""
        # Check if this is a chair role and was modified
        if self.is_chair and self.is_active and self.has_value_changed("is_chair"):
            # Find chapters using this role and update their heads
            try:
                from verenigingen.verenigingen.doctype.chapter_role.chapter_role import (
                    update_chapters_with_role,
                )

                update_chapters_with_role(self.name)
            except Exception as e:
                frappe.log_error(
                    message=f"Error updating chapters from ChapterRole.after_save: {str(e)}",
                    title="ChapterRole after_save Error",
                )


@frappe.whitelist()
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
        "Verenigingen Chapter Board Member",
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
                chapter.save(ignore_permissions=True)
                chapters_updated += 1

                # Log the change
                frappe.get_doc(
                    {
                        "doctype": "Comment",
                        "comment_type": "Info",
                        "reference_doctype": "Chapter",
                        "reference_name": chapter.name,
                        "content": _("Chapter Head changed from {0} to {1} due to chair role update").format(
                            original_head or "None", chapter.chapter_head or "None"
                        ),
                    }
                ).insert(ignore_permissions=True)

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
