# Base History Manager - shared boilerplate for history tracking managers
#
# Eliminates ~400 LOC of duplicated existence checks, recursion guards,
# safe saves, and error handling across history managers.

from typing import Callable, Optional

import frappe
from frappe.exceptions import QueryDeadlockError, QueryTimeoutError
from frappe.model.document import Document

from verenigingen.utils.history_manager_utils import (
    HistoryOperationResult,
    ensure_doc_exists,
    log_history_error,
    recursion_guard,
    safe_child_table_update,
)
from verenigingen.utils.transaction_errors import is_statement_timeout


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
    ) -> HistoryOperationResult:
        """Execute *callback(doc)* with existence check, recursion guard, and safe save.

        Returns HistoryOperationResult (truthy when successful, so existing callers
        that check ``if result:`` or ``if not result:`` continue to work).

        Callback protocol – return value determines post-callback behaviour:
            None  → save via safe_child_table_update, return its HistoryOperationResult
            True  → skip save (already handled / idempotent), return success
            False → skip save (validation failure), return failure
        """
        try:
            if not ensure_doc_exists(cls.PARENT_DOCTYPE, doc_name, operation_name):
                return HistoryOperationResult(
                    success=False,
                    message=f"{cls.PARENT_DOCTYPE} {doc_name} does not exist",
                    errors=[f"{cls.PARENT_DOCTYPE} {doc_name} not found"],
                )

            # Lock the parent row BEFORE loading it, because everything below is a
            # read-modify-write: the callback mutates the child table on this
            # in-memory copy and safe_child_table_update writes it back. Without the
            # lock two writers both read, both compute, and the second write wins --
            # and update_child_table does not touch the parent row, so nothing else
            # in this path takes that lock on our behalf.
            #
            # donor_history is why this is not theoretical: MemberFinancialHistoryManager
            # locks the Donor row (#424) while DonationHistoryManager took nothing, and
            # an unlocked writer does not queue behind a locked one. #436.
            #
            # PARENT_DOCTYPE is Donor / Member / Volunteer for the three subclasses --
            # none of them Single, all series-named -- so neither of get_value's two
            # silently-lockless shapes (a Single, or a name equal to its doctype)
            # applies here.
            #
            # CANONICAL LOCK ORDER: Donor -> Member -> Volunteer.
            # A caller that ends up taking two of these three in one transaction MUST
            # take them in that order, or it deadlocks against a caller that takes them
            # the other way round. It is alphabetical purely so that it is memorable.
            #
            # Three paths take more than one kind: Chapter._handle_document_changes,
            # TerminationExecutionService.execute_system_updates, and
            # api.termination_api.execute_safe_termination. All three are pinned by
            # tests/unit/test_history_lock_order.py, which measures the acquisitions
            # rather than reading them; that module's docstring also records how the
            # list of three was derived, and why no static search of this can be
            # exhaustive. Add a path there before adding one here.
            frappe.db.get_value(cls.PARENT_DOCTYPE, doc_name, "name", for_update=True)

            doc = frappe.get_doc(cls.PARENT_DOCTYPE, doc_name)

            with recursion_guard(doc, cls.RECURSION_FLAG) as should_proceed:
                if not should_proceed:
                    return HistoryOperationResult(success=True, message="skipped (recursion guard)")

                result = callback(doc)

                if result is True:
                    return HistoryOperationResult(success=True, message="skipped (callback)")
                if result is False:
                    return HistoryOperationResult(
                        success=False,
                        message="validation failure",
                        errors=[f"Callback returned False for {operation_name}"],
                    )

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

                return save_result

        except (QueryDeadlockError, QueryTimeoutError):
            # Contention on the lock above is NOT an ordinary "history update failed".
            # Before that lock existed this branch was unreachable, and the handler
            # below would fold it into HistoryOperationResult(success=False) -- which
            # the eleven call sites in chapter/managers/member_manager.py discard
            # entirely, so a Chapter save would commit the membership change with no
            # history row and report nothing.
            #
            # 1213 (deadlock) has already rolled the transaction back, so carrying on
            # would let every later iteration "succeed" against a discarded
            # transaction -- the shape bulk_invoice_generation_service documents at
            # its own commit. 1205 (lock wait) does not roll back, but the write did
            # not happen, and the caller is the only frame that can decide whether to
            # retry or abort. Let both reach it.
            #
            # Imported by name rather than reached through `frappe.`: an except clause
            # that resolves its classes through a patchable namespace raises
            # "catching classes that do not inherit from BaseException" under any test
            # that mocks frappe -- test_base_history_manager.py does exactly that.
            raise

        except Exception as e:
            if is_statement_timeout(e):
                # MariaDB 1969 ("max_statement_time exceeded") is exactly as
                # non-resumable as the 1213/1205 pair above -- the statement was
                # killed mid-flight -- but frappe's dispatch does not wrap it into a
                # typed exception the way it does for those two, so it cannot be
                # caught by the except clause above and falls through to here by
                # default. Folding it into an ordinary HistoryOperationResult would
                # be the exact swallow this method exists to prevent for 1213/1205.
                # See transaction_errors.is_statement_timeout and #1352.
                raise

            log_history_error(
                title=error_title,
                message=f"Error in {operation_name} for {cls.PARENT_DOCTYPE} {doc_name}: {str(e)}",
                include_traceback=True,
            )
            return HistoryOperationResult(
                success=False,
                message=f"Exception in {operation_name}",
                errors=[str(e)],
            )
