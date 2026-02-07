# Base History Manager - shared boilerplate for history tracking managers
#
# Eliminates ~400 LOC of duplicated existence checks, recursion guards,
# safe saves, and error handling from AssignmentHistoryManager and
# ChapterMembershipHistoryManager.

from typing import Callable, Optional

import frappe
from frappe.model.document import Document

from verenigingen.utils.history_manager_utils import (
    ensure_doc_exists,
    log_history_error,
    recursion_guard,
    safe_child_table_update,
)


class BaseHistoryManager:
    """Base class for history managers that share existence-check / guard / save boilerplate.

    Subclasses must set:
        PARENT_DOCTYPE  – e.g. "Volunteer", "Member"
        CHILD_TABLE     – e.g. "assignment_history", "chapter_membership_history"
        PERMISSION      – e.g. "Volunteer:write", "Member:write"
        RECURSION_FLAG  – e.g. "_updating_assignment_history"
    """

    PARENT_DOCTYPE: str = ""
    CHILD_TABLE: str = ""
    PERMISSION: str = ""
    RECURSION_FLAG: str = ""

    @classmethod
    def _with_doc(
        cls,
        doc_name: str,
        operation_name: str,
        callback: Callable[[Document], Optional[bool]],
        error_title: str = "History Manager Error",
    ) -> bool:
        """Execute *callback(doc)* with existence check, recursion guard, and safe save.

        Callback protocol – return value determines post-callback behaviour:
            None  → save via safe_child_table_update, return True on success
            True  → skip save (already handled / idempotent), return True
            False → skip save (validation failure), return False
        """
        try:
            if not ensure_doc_exists(cls.PARENT_DOCTYPE, doc_name, operation_name):
                return False

            doc = frappe.get_doc(cls.PARENT_DOCTYPE, doc_name)

            with recursion_guard(doc, cls.RECURSION_FLAG) as should_proceed:
                if not should_proceed:
                    return True

                result = callback(doc)

                if result is True:
                    return True
                if result is False:
                    return False

                # result is None → save
                save_result = safe_child_table_update(
                    doc=doc,
                    child_table_name=cls.CHILD_TABLE,
                    justification=f"{operation_name} for {cls.PARENT_DOCTYPE} {doc_name}",
                    doctype_permission=cls.PERMISSION,
                    auto_cleanup=True,
                )

                if not save_result.success:
                    log_history_error(
                        title=error_title,
                        message=(
                            f"Failed to {operation_name} for {cls.PARENT_DOCTYPE} "
                            f"{doc_name}: {'; '.join(save_result.errors)}"
                        ),
                    )
                    return False

                return True

        except Exception as e:
            log_history_error(
                title=error_title,
                message=f"Error in {operation_name} for {cls.PARENT_DOCTYPE} {doc_name}: {str(e)}",
                include_traceback=True,
            )
            return False
