"""
Member management API endpoints with optimized performance and error handling
"""

from typing import Any, Dict, List, Optional

import frappe

from verenigingen.utils.constants import Roles
from verenigingen.utils.error_handling import (
    PermissionError,
    ValidationError,
    handle_api_error,
    log_error,
    validate_required_fields,
)
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.performance_utils import QueryOptimizer, performance_monitor

# Import comprehensive security framework
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)
from verenigingen.utils.security.enhanced_validation import validate_with_schema


@frappe.whitelist()
@critical_api(operation_type=OperationType.MEMBER_DATA)
@validate_with_schema("member_data")
@handle_api_error
@performance_monitor(threshold_ms=500)
def assign_member_to_chapter(member_name: str, chapter_name: str) -> OperationResult[Dict[str, Any]]:
    """Assign a member to a specific chapter using centralized manager"""
    # Validate inputs using standardized validation
    validate_required_fields(
        {"member_name": member_name, "chapter_name": chapter_name}, ["member_name", "chapter_name"]
    )

    # Check permissions
    if not can_assign_member_to_chapter(member_name, chapter_name):
        raise PermissionError("You don't have permission to assign members to this chapter")

    # Use centralized chapter membership manager for proper history tracking
    from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager

    result = ChapterMembershipManager.assign_member_to_chapter(
        member_id=member_name,
        chapter_name=chapter_name,
        reason="Assigned via admin interface",
        assigned_by=frappe.session.user,
    )

    # Adapt result format for backward compatibility
    if result.get("success"):
        return OperationResult.ok(
            {"new_chapter": chapter_name},
            message=f"Member {member_name} has been assigned to {chapter_name}",
        )

    # Re-assigning a member who is already in the target chapter is an
    # idempotent no-op, not a hard error. The membership manager signals this
    # via action == "already_exists"; surface it as success so callers can
    # safely retry an assignment.
    if result.get("action") == "already_exists":
        return OperationResult.ok(
            {"new_chapter": chapter_name},
            message=result.get("message")
            or frappe._("Member is already assigned to {0}").format(chapter_name),
        )

    # Convert any other error result to ValidationError. The manager may report
    # the failure under "error" or, for non-exception outcomes, under "message".
    error_msg = result.get("error") or result.get("message") or "Unknown error occurred"
    raise ValidationError(error_msg)


@performance_monitor(threshold_ms=200)
def can_assign_member_to_chapter(member_name, chapter_name):
    """Check if current user can assign a member to a specific chapter - optimized version"""
    user = frappe.session.user

    # System managers and Association/Membership managers can assign anyone
    if any(role in frappe.get_roles(user) for role in Roles.ADMIN_ROLES):
        return True

    # Get user's member record
    user_member = frappe.db.get_value("Member", {"user": user}, "name")
    if not user_member:
        return False

    # Optimized permission check using single query with JOINs
    try:
        # Single query to check all board positions and roles
        board_permissions = frappe.db.sql(
            """
            SELECT cr.permissions_level
            FROM `tabChapter Board Member` cbm
            JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            JOIN `tabChapter Role` cr ON cbm.chapter_role = cr.name
            WHERE v.member = %s
            AND cbm.parent = %s
            AND cbm.is_active = 1
            AND cr.permissions_level IN ('Admin', 'Membership')
        """,
            [user_member, chapter_name],
            as_dict=True,
        )

        if board_permissions:
            return True

        # Check national board access with optimized query
        settings = frappe.get_single("Verenigingen Settings")
        if hasattr(settings, "national_board_chapter") and settings.national_board_chapter:
            national_permissions = frappe.db.sql(
                """
                SELECT cr.permissions_level
                FROM `tabChapter Board Member` cbm
                JOIN `tabVolunteer` v ON cbm.volunteer = v.name
                JOIN `tabChapter Role` cr ON cbm.chapter_role = cr.name
                WHERE v.member = %s
                AND cbm.parent = %s
                AND cbm.is_active = 1
                AND cr.permissions_level IN ('Admin', 'Membership')
            """,
                [user_member, settings.national_board_chapter],
                as_dict=True,
            )

            if national_permissions:
                return True

        return False

    except Exception as e:
        log_error(
            e,
            context={"user": user, "member_name": member_name, "chapter_name": chapter_name},
            module="verenigingen.api.member_management",
        )
        return False

    return False


@frappe.whitelist()
@handle_api_error
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def get_members_without_chapter(**kwargs) -> OperationResult[Dict[str, Any]]:
    """Get list of members without chapter assignment"""
    try:
        # Check permissions
        if not can_view_members_without_chapter():
            return OperationResult.fail("You don't have permission to view this data")

        # Get members who are not in any Chapter Member records
        members_with_chapters = frappe.get_all(
            "Chapter Member", filters={"enabled": 1}, fields=["member"], distinct=True
        )

        excluded_members = [m.member for m in members_with_chapters]

        # Get members without chapter
        member_filters = {}
        if excluded_members:
            member_filters["name"] = ["not in", excluded_members]

        # Pagination support
        limit = frappe.utils.cint(kwargs.get("limit", 100))
        offset = frappe.utils.cint(kwargs.get("offset", 0))
        if limit > 1000:
            limit = 1000  # Max limit for performance

        members = frappe.get_all(
            "Member",
            filters=member_filters,
            fields=["name", "full_name", "email", "status", "creation"],
            order_by="creation desc",
            limit=limit,
            start=offset,
        )

        return OperationResult.ok({"members": members, "count": len(members)})

    except Exception as e:
        frappe.log_error(f"Error getting members without chapter: {str(e)}", "Members Without Chapter Error")
        return OperationResult.fail(f"Failed to get members: {str(e)}")


def can_view_members_without_chapter():
    """Check if current user can view members without chapter"""
    user = frappe.session.user

    # System managers and Association/Membership managers can view
    if any(role in frappe.get_roles(user) for role in Roles.ADMIN_ROLES):
        return True

    # Chapter board members with admin/membership permissions can view
    user_member = frappe.db.get_value("Member", {"user": user}, "name")
    if not user_member:
        return False

    try:
        volunteer_records = frappe.get_all("Volunteer", filters={"member": user_member}, fields=["name"])

        for volunteer_record in volunteer_records:
            board_positions = frappe.get_all(
                "Chapter Board Member",
                filters={"volunteer": volunteer_record.name, "is_active": 1},
                fields=["chapter_role"],
            )

            for position in board_positions:
                try:
                    role_doc = frappe.get_doc("Chapter Role", position.chapter_role)
                    if role_doc.permissions_level in ["Admin", "Membership"]:
                        return True
                except Exception:
                    continue
    except Exception:
        pass

    return False


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def bulk_assign_members_to_chapters(assignments) -> OperationResult[Dict[str, Any]]:
    """Bulk assign multiple members to chapters

    Args:
        assignments: List of dicts with member_name and chapter_name
    """
    try:
        if not assignments:
            return OperationResult.fail("No assignments provided")

        results = []
        success_count = 0
        error_count = 0

        for assignment in assignments:
            member_name = assignment.get("member_name")
            chapter_name = assignment.get("chapter_name")

            result = assign_member_to_chapter(member_name, chapter_name)
            # Handle OperationResult from assign_member_to_chapter
            result_dict = (
                result.to_dict(scrub_sensitive=True) if isinstance(result, OperationResult) else result
            )
            results.append({"member_name": member_name, "chapter_name": chapter_name, "result": result_dict})

            if isinstance(result, OperationResult):
                if result.success:
                    success_count += 1
                else:
                    error_count += 1
            elif result.get("success"):
                success_count += 1
            else:
                error_count += 1

        return OperationResult.ok(
            {
                "results": results,
                "success_count": success_count,
                "error_count": error_count,
            },
            message=f"Processed {len(assignments)} assignments: {success_count} successful, {error_count} failed",
        )

    except Exception as e:
        frappe.log_error(f"Error in bulk assignment: {str(e)}", "Bulk Assignment Error")
        return OperationResult.fail(f"Failed to process bulk assignments: {str(e)}")


def _sanitize_member_filters(filters):
    """Validate and sanitize member list filters.

    Accepts a dict or JSON string. Applies a whitelist of allowed filter keys
    to prevent unauthorized field access. Returns a sanitized filter dict.
    """
    if not isinstance(filters, dict):
        try:
            from verenigingen.utils.validation.api_validators import parse_json_filters

            filters = parse_json_filters(filters) or {}
        except Exception as e:
            frappe.log_error(f"Invalid filters JSON: {filters} - Error: {str(e)}", "Member List API")
            filters = {}

    if isinstance(filters, dict):
        allowed_filters = {"status", "member_since", "current_membership_type"}
        return {k: v for k, v in filters.items() if k in allowed_filters}

    return {}


def _enrich_members_with_chapters(members, chapter_relationships, chapter_info):
    """Enrich each member dict with chapter data from pre-fetched maps.

    Returns list of member dicts with added 'chapters' and 'primary_chapter' keys.
    """
    enriched_members = []
    for member in members:
        member_name = member["name"]

        member_chapters = []
        if member_name in chapter_relationships:
            for rel in chapter_relationships[member_name]:
                chapter_name = rel.get("parent")
                if chapter_name and chapter_name in chapter_info:
                    chapter_data = chapter_info[chapter_name]
                    member_chapters.append(
                        {
                            "chapter_name": chapter_name,
                            "region": chapter_data["region"],
                            "status": rel.get("status", "Active"),
                            "join_date": rel.get("chapter_join_date"),
                        }
                    )

        member["chapters"] = member_chapters
        member["primary_chapter"] = member_chapters[0] if member_chapters else None
        enriched_members.append(member)

    return enriched_members


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
@performance_monitor(threshold_ms=1000)
def get_members_with_chapter_info(
    filters: dict | str | None = None, limit=50
) -> OperationResult[Dict[str, Any]]:
    """
    Get member list with chapter relationships using optimized queries (N+1 prevention)

    Security-first approach: permission filtering happens before data fetching

    Args:
        filters: Optional dict with status, chapter_name, etc.
        limit: Maximum members to return (default 50)

    Returns:
        OperationResult with members list and metadata
    """
    if limit is None or limit > 500:
        limit = 50  # Security: prevent large data dumps

    base_filters = {"docstatus": ["<", 2]}
    if filters:
        base_filters.update(_sanitize_member_filters(filters))

    members = frappe.get_all(
        "Member",
        filters=base_filters,
        fields=["name", "full_name", "email", "status", "member_since", "current_membership_type", "age"],
        limit=limit,
        order_by="full_name asc",
    )

    if not members:
        return OperationResult.ok({"members": [], "total_count": 0})

    member_names = [m["name"] for m in members]

    # Batch get chapter relationships (single query - prevents N+1)
    chapter_relationships = QueryOptimizer.bulk_get_linked_docs(
        doctype="Chapter Member",
        parent_field="member",
        parent_names=member_names,
        fields=["member", "parent", "enabled", "chapter_join_date", "status"],
        filters={"enabled": 1},
    )

    # Batch get chapter info (single query)
    all_chapter_names = set()
    for relationships in chapter_relationships.values():
        for rel in relationships:
            if rel.get("parent"):
                all_chapter_names.add(rel["parent"])

    chapter_info = {}
    if all_chapter_names:
        chapters = frappe.get_all(
            "Chapter", filters={"name": ["in", list(all_chapter_names)]}, fields=["name", "region"]
        )
        chapter_info = {ch["name"]: ch for ch in chapters}

    enriched_members = _enrich_members_with_chapters(members, chapter_relationships, chapter_info)

    return OperationResult.ok(
        {
            "members": enriched_members,
            "total_count": len(enriched_members),
            "query_optimization": {
                "queries_used": 3,
                "n_plus_1_prevented": True,
                "members_processed": len(members),
            },
        }
    )


def add_member_to_chapter_roster(member_name, new_chapter):
    """Add member to chapter's member roster using centralized manager"""
    try:
        if new_chapter:
            # Use centralized chapter membership manager for proper history tracking
            from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager

            result = ChapterMembershipManager.assign_member_to_chapter(
                member_id=member_name,
                chapter_name=new_chapter,
                reason="Administrative assignment",
                assigned_by=frappe.session.user,
            )

            if not result.get("success"):
                frappe.log_error(
                    f"Failed to add member {member_name} to chapter {new_chapter}: {result.get('error')}",
                    "Chapter Roster Update Error",
                )

    except Exception as e:
        frappe.log_error(f"Error updating chapter roster: {str(e)}", "Chapter Roster Update Error")


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_mt940_import_url() -> OperationResult[str]:
    """Get URL for MT940 import page"""
    return OperationResult.ok("/mt940_import")


def _resolve_mt940_bank_account(bank_account, company, mt940_content):
    """Resolve bank account and company from explicit params, IBAN extraction, or defaults.

    Returns (bank_account, company, error) where error is an OperationResult
    to return early if resolution fails, or None on success.
    """
    # Get company from bank account if not provided
    if bank_account and not company:
        company = frappe.db.get_value("Bank Account", bank_account, "company")

    if not company:
        companies = frappe.get_all("Company", limit=1)
        if companies:
            company = companies[0].name

    # Auto-detect bank account via IBAN if not provided
    if not bank_account:
        statement_iban = extract_iban_from_mt940_content(mt940_content)
        if statement_iban:
            bank_account = find_bank_account_by_iban_improved(statement_iban, company)
            if not bank_account:
                return (
                    None,
                    company,
                    OperationResult.fail(
                        f"No Bank Account found with IBAN {statement_iban}",
                        extracted_iban=statement_iban,
                    ),
                )
        else:
            return (
                None,
                company,
                OperationResult.fail("Could not extract IBAN from MT940 file and no bank account specified"),
            )

    if not frappe.db.exists("Bank Account", bank_account):
        return None, company, OperationResult.fail(f"Bank Account {bank_account} does not exist")

    return bank_account, company, None


def _process_mt940_statements(transaction_list, bank_account, company):
    """Iterate MT940 statements, extract/deduplicate transactions, and create bank transactions.

    Returns (created_count, skipped_count, errors).
    """
    created = 0
    skipped = 0
    errors = []
    processed_signatures = set()

    for statement in transaction_list:
        if hasattr(statement, "transactions") and statement.transactions:
            statement_transactions = statement.transactions
        else:
            statement_transactions = [statement]

        for transaction in statement_transactions:
            try:
                transaction_data = extract_transaction_data_improved(transaction)

                if not transaction_data:
                    skipped += 1
                    errors.append("Failed to extract transaction data")
                    continue

                # Deduplicate within this import run (MT940 library may emit duplicates)
                signature = (
                    str(transaction_data["date"]),
                    str(transaction_data["amount"]),
                    str(transaction_data.get("reference", "")),
                    str(transaction_data.get("description", ""))[:50],
                )
                if signature in processed_signatures:
                    continue
                processed_signatures.add(signature)

                creation_result = create_bank_transaction_improved(transaction_data, bank_account, company)
                if creation_result == "created":
                    created += 1
                elif creation_result == "exists":
                    skipped += 1
                else:
                    skipped += 1
                    errors.append(f"Failed to create transaction: {creation_result}")

            except Exception as e:
                skipped += 1
                errors.append(f"Transaction error: {str(e)}")
                frappe.logger().error(f"Error processing MT940 transaction: {str(e)}")

    return created, skipped, errors


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def import_mt940_improved(file_content, bank_account=None, company=None) -> OperationResult[Dict[str, Any]]:
    """Improved MT940 import with better transaction handling"""
    try:
        import base64
        import os
        import tempfile

        mt940_content = base64.b64decode(file_content).decode("utf-8")

        bank_account, company, error = _resolve_mt940_bank_account(bank_account, company, mt940_content)
        if error:
            return error

        try:
            import mt940
        except ImportError:
            return OperationResult.fail(
                "MT940 library not available. Please install with: pip install mt-940"
            )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".sta", delete=False) as temp_file:
            temp_file.write(mt940_content)
            temp_file_path = temp_file.name

        try:
            transaction_list = list(mt940.parse(temp_file_path))

            if not transaction_list:
                return OperationResult.fail("No statements found in MT940 file")

            created, skipped, errors = _process_mt940_statements(transaction_list, bank_account, company)

            return OperationResult.ok(
                {
                    "transactions_created": created,
                    "transactions_skipped": skipped,
                    "bank_account": bank_account,
                    "errors": errors[:5],
                    "debug_info": {
                        "total_statements": len(transaction_list),
                        "total_transactions_processed": created + skipped,
                        "first_few_errors": errors[:3],
                    },
                },
                message=f"Import completed: {created} transactions created, {skipped} skipped",
            )

        except Exception as e:
            return OperationResult.fail(f"Failed to parse MT940 file: {str(e)}")
        finally:
            try:
                os.unlink(temp_file_path)
            except Exception:
                pass

    except Exception as e:
        return OperationResult.fail(f"Import failed: {str(e)}")


def extract_iban_from_mt940_content(mt940_content):
    """Extract IBAN from MT940 content"""
    import re

    # Look for :25: tag which contains account identification
    match = re.search(r":25:([A-Z]{2}[0-9]{2}[A-Z0-9]{1,30})", mt940_content)
    if match:
        return match.group(1)

    # Alternative: look for any IBAN pattern
    iban_match = re.search(r"([A-Z]{2}[0-9]{2}[A-Z0-9]{15,30})", mt940_content)
    if iban_match:
        return iban_match.group(1)

    return None


def find_bank_account_by_iban_improved(iban, company=None):
    """Find bank account by IBAN"""
    # First try with company filter if provided
    if company:
        filters = {"bank_account_no": iban, "company": company}
        bank_account = frappe.db.get_value("Bank Account", filters, "name")

        if not bank_account:
            filters = {"iban": iban, "company": company}
            bank_account = frappe.db.get_value("Bank Account", filters, "name")

        if bank_account:
            return bank_account

    # Fallback: search without company filter
    bank_account = frappe.db.get_value("Bank Account", {"bank_account_no": iban}, "name")

    if not bank_account:
        bank_account = frappe.db.get_value("Bank Account", {"iban": iban}, "name")

    return bank_account


def _parse_mt940_amount(data):
    """Parse amount and currency from MT940 data dictionary.

    Handles amount strings like "-898.54 EUR" or "1234.56".
    Returns (amount, currency) where amount may be None if parsing fails.
    """
    import re

    amount = None
    currency = "EUR"

    if "amount" in data and data["amount"]:
        amount_str = str(data["amount"]).strip()

        # Extract trailing currency code (e.g. "EUR")
        currency_match = re.search(r"([A-Z]{3})$", amount_str)
        if currency_match:
            currency = currency_match.group(1)
            amount_str = amount_str.replace(currency, "").strip()

        try:
            amount = float(amount_str)
        except Exception:
            numeric_match = re.search(r"([+-]?\d+\.?\d*)", amount_str)
            if numeric_match:
                amount = float(numeric_match.group(1))

    # Prefer explicit currency field if present
    if "currency" in data and data["currency"]:
        currency = data["currency"]

    return amount, currency


def _build_transaction_description(sepa_data, data, reference):
    """Assemble transaction description from SEPA and raw MT940 fields.

    Prefers clean SEPA remittance_info/payment_purpose over raw tagged text.
    Normalizes whitespace and returns a cleaned description string.
    """
    import re

    description_parts = []
    has_sepa_description = False

    if sepa_data.get("remittance_info"):
        description_parts.append(sepa_data["remittance_info"])
        has_sepa_description = True
    elif sepa_data.get("payment_purpose"):
        description_parts.append(sepa_data["payment_purpose"])
        has_sepa_description = True

    # Only include raw fields if no clean SEPA description was extracted
    if not has_sepa_description:
        if data.get("extra_details"):
            description_parts.append(data["extra_details"])
        if data.get("transaction_details"):
            description_parts.append(data["transaction_details"])

    if data.get("funds_code"):
        description_parts.append(f"Funds: {data['funds_code']}")
    if data.get("transaction_reference") and data["transaction_reference"] != reference:
        description_parts.append(f"Ref: {data['transaction_reference']}")

    description = " | ".join(filter(None, description_parts)) or "MT940 Transaction"

    # Normalize: remove line breaks and collapse whitespace
    description = re.sub(r"[\r\n]+", "", description)
    description = re.sub(r"\s+", " ", description).strip()

    return description


def extract_transaction_data_improved(transaction):
    """Extract transaction data from MT940 transaction object"""
    try:
        from frappe.utils import getdate

        from verenigingen.utils.sepa_parser import parse_sepa_structured_data

        data = transaction.data if hasattr(transaction, "data") else {}

        # Parse date
        transaction_date = None
        if "date" in data and data["date"]:
            try:
                transaction_date = getdate(data["date"])
            except Exception:
                pass

        # Parse amount and currency
        amount, currency = _parse_mt940_amount(data)

        if not transaction_date or amount is None:
            return None

        # Combine text fields for SEPA parsing
        raw_text_for_sepa = " ".join(
            filter(
                None,
                [
                    data.get("extra_details", ""),
                    data.get("transaction_details", ""),
                    data.get("purpose", ""),
                ],
            )
        )
        sepa_data = parse_sepa_structured_data(raw_text_for_sepa)

        # Determine counterparty info - prefer SEPA parsed data over raw fields
        counterparty_name = sepa_data.get("counterparty_name") or data.get("customer_reference", "")
        counterparty_account = sepa_data.get("counterparty_account") or data.get("counterparty_account", "")

        if counterparty_name and counterparty_name.upper() == "NONREF":
            counterparty_name = ""

        reference = sepa_data.get("end_to_end_ref") or data.get("transaction_reference", "")

        transaction_data = {
            "date": transaction_date,
            "amount": amount,
            "currency": currency,
            "description": "",
            "reference": reference,
            "bank_reference": data.get("bank_reference", ""),
            "counterparty_name": counterparty_name,
            "counterparty_account": counterparty_account,
            "extra_details": data.get("extra_details", ""),
            "mandate_ref": sepa_data.get("mandate_ref", ""),
            "creditor_ref": sepa_data.get("creditor_ref", ""),
            "remittance_info": sepa_data.get("remittance_info", ""),
            "payment_purpose": sepa_data.get("payment_purpose", ""),
        }

        transaction_data["description"] = _build_transaction_description(sepa_data, data, reference)

        return transaction_data

    except Exception as e:
        frappe.logger().error(f"Error extracting transaction data: {str(e)}")
        return None


def create_bank_transaction_improved(transaction_data, bank_account, company):
    """
    Create ERPNext Bank Transaction from extracted data.

    Uses centralized BankTransactionCreator for consistent creation logic.
    """
    try:
        import hashlib

        from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
            get_bank_transaction_creator,
        )

        # Validate required data
        if not transaction_data.get("date") or transaction_data.get("amount") is None:
            return "missing_required_data"

        # Validate bank account exists
        if not frappe.db.exists("Bank Account", bank_account):
            return f"bank_account_not_found: {bank_account}"

        # Generate unique transaction ID with more specific components
        id_components = [
            str(transaction_data["date"]),
            str(transaction_data["amount"]),
            str(transaction_data.get("description") or "")[:100],
            str(transaction_data.get("counterparty_name") or ""),
            str(transaction_data.get("counterparty_account") or ""),
            str(transaction_data.get("reference") or ""),
            str(transaction_data.get("bank_reference") or ""),
            bank_account,
        ]

        hash_input = "|".join(id_components)
        transaction_id = hashlib.sha256(hash_input.encode()).hexdigest()[:16]

        # Check if transaction already exists (idempotency)
        if frappe.db.exists(
            "Bank Transaction", {"transaction_id": transaction_id, "bank_account": bank_account}
        ):
            return "exists"

        # Prepare transaction data for BankTransactionCreator
        # Map counterparty fields to bank_party fields
        creator_data = {
            "date": transaction_data["date"],
            "amount": transaction_data["amount"],
            "currency": transaction_data.get("currency", "EUR"),
            "description": transaction_data["description"],
            "reference_number": transaction_data.get("reference", ""),
            "transaction_id": transaction_id,
            "bank_party_name": transaction_data.get("counterparty_name"),
            "bank_party_iban": transaction_data.get("counterparty_account"),
        }

        # Create Bank Transaction using centralized service
        creator = get_bank_transaction_creator()
        bank_transaction_name = creator.create_from_dict(
            transaction_data=creator_data,
            bank_account=bank_account,
            company=company,
            source_type="Member Payment Import",
        )

        if bank_transaction_name:
            frappe.logger().info(f"Created Bank Transaction from member payment: {bank_transaction_name}")
            return "created"
        else:
            frappe.logger().error("Failed to create Bank Transaction from member payment")
            return "error: Failed to create Bank Transaction"

    except Exception as e:
        error_msg = str(e)
        frappe.logger().error(f"Error creating bank transaction: {error_msg}")
        return f"error: {error_msg}"


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
@handle_api_error
@performance_monitor(threshold_ms=1000)
def get_chapter_member_emails(chapter_name: str) -> OperationResult[Dict[str, Any]]:
    """
    Get email addresses of all members in a specific chapter.

    Args:
        chapter_name (str): Name of the chapter

    Returns:
        OperationResult: List of member emails and metadata
    """
    # Validate input
    validate_required_fields({"chapter_name": chapter_name}, ["chapter_name"])

    # Check permissions - user must be able to approve members or be admin
    if not can_approve_members():
        raise PermissionError("You do not have permission to access member email lists")

    # Validate chapter exists
    if not frappe.db.exists("Chapter", chapter_name):
        raise ValidationError(f"Chapter '{chapter_name}' does not exist")

    # Get chapter members through Chapter Member relationship
    chapter_members = frappe.get_all(
        "Chapter Member",
        filters={
            "parent": chapter_name,
            "enabled": 1,
            "status": ["in", ["Active", "Pending"]],
        },
        fields=["member"],
    )

    # Get member details for active chapter members
    member_names = [cm.member for cm in chapter_members]
    members = frappe.get_all(
        "Member",
        filters={
            "name": ["in", member_names],
            "membership_status": ["in", ["Active", "Pending"]],
            "email": ["is", "set"],  # Only members with email addresses
        },
        fields=["name", "full_name", "email", "membership_status", "member_since"],
        order_by="full_name",
    )

    # Filter out invalid emails and prepare email list
    valid_emails = []
    member_details = []

    for member in members:
        if member.email and "@" in member.email:
            valid_emails.append(member.email)
            member_details.append(
                {
                    "name": member.name,
                    "full_name": member.full_name,
                    "email": member.email,
                    "status": member.membership_status,
                    "member_since": member.member_since,
                }
            )

    # Get chapter information
    chapter = frappe.get_doc("Chapter", chapter_name)

    return OperationResult.ok(
        {
            "chapter": {"name": chapter_name, "chapter_name": chapter.name, "region": chapter.region},
            "emails": valid_emails,
            "members": member_details,
            "total_members": len(member_details),
            "email_list": ", ".join(valid_emails),  # Convenient for copy-paste
        }
    )


def can_approve_members():
    """Check if current user can approve members (has required roles)"""
    user_roles = frappe.get_roles(frappe.session.user)
    required_roles = [Roles.SYSTEM_MANAGER, Roles.VERENIGINGEN_ADMIN, Roles.CHAPTER_ADMIN, "Board Member"]

    return any(role in user_roles for role in required_roles)
