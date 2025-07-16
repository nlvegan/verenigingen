"""
Member management API endpoints with optimized performance and error handling
"""
import frappe

from verenigingen.utils.error_handling import (
    PermissionError,
    ValidationError,
    handle_api_error,
    log_error,
    validate_required_fields,
)
from verenigingen.utils.migration.migration_performance import BatchProcessor
from verenigingen.utils.performance_utils import QueryOptimizer, performance_monitor


@frappe.whitelist()
@handle_api_error
@performance_monitor(threshold_ms=500)
def assign_member_to_chapter(member_name, chapter_name):
    """Assign a member to a specific chapter using centralized manager"""
    # Validate inputs using standardized validation
    validate_required_fields(
        {"member_name": member_name, "chapter_name": chapter_name}, ["member_name", "chapter_name"]
    )

    # Check permissions
    if not can_assign_member_to_chapter(member_name, chapter_name):
        raise PermissionError("You don't have permission to assign members to this chapter")

    # Use centralized chapter membership manager for proper history tracking
    from verenigingen.utils.chapter_membership_manager import ChapterMembershipManager

    result = ChapterMembershipManager.assign_member_to_chapter(
        member_id=member_name,
        chapter_name=chapter_name,
        reason="Assigned via admin interface",
        assigned_by=frappe.session.user,
    )

    # Adapt result format for backward compatibility
    if result.get("success"):
        return {
            "success": True,
            "message": f"Member {member_name} has been assigned to {chapter_name}",
            "new_chapter": chapter_name,
        }
    else:
        # Convert any error result to ValidationError
        error_msg = result.get("error", "Unknown error occurred")
        raise ValidationError(error_msg)


@performance_monitor(threshold_ms=200)
def can_assign_member_to_chapter(member_name, chapter_name):
    """Check if current user can assign a member to a specific chapter - optimized version"""
    user = frappe.session.user

    # System managers and Association/Membership managers can assign anyone
    admin_roles = ["System Manager", "Verenigingen Administrator", "Verenigingen Manager"]
    if any(role in frappe.get_roles(user) for role in admin_roles):
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


@handle_api_error
@frappe.whitelist()
def get_members_without_chapter(**kwargs):
    """Get list of members without chapter assignment"""
    try:
        # Check permissions
        if not can_view_members_without_chapter():
            return {"success": False, "error": "You don't have permission to view this data"}

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

        return {"success": True, "members": members, "count": len(members)}

    except Exception as e:
        frappe.log_error(f"Error getting members without chapter: {str(e)}", "Members Without Chapter Error")
        return {"success": False, "error": f"Failed to get members: {str(e)}"}


def can_view_members_without_chapter():
    """Check if current user can view members without chapter"""
    user = frappe.session.user

    # System managers and Association/Membership managers can view
    admin_roles = ["System Manager", "Verenigingen Administrator", "Verenigingen Manager"]
    if any(role in frappe.get_roles(user) for role in admin_roles):
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
def bulk_assign_members_to_chapters(assignments):
    """Bulk assign multiple members to chapters

    Args:
        assignments: List of dicts with member_name and chapter_name
    """
    try:
        if not assignments:
            return {"success": False, "error": "No assignments provided"}

        results = []
        success_count = 0
        error_count = 0

        for assignment in assignments:
            member_name = assignment.get("member_name")
            chapter_name = assignment.get("chapter_name")

            result = assign_member_to_chapter(member_name, chapter_name)
            results.append({"member_name": member_name, "chapter_name": chapter_name, "result": result})

            if result.get("success"):
                success_count += 1
            else:
                error_count += 1

        return {
            "success": True,
            "message": f"Processed {len(assignments)} assignments: {success_count} successful, {error_count} failed",
            "results": results,
            "success_count": success_count,
            "error_count": error_count,
        }

    except Exception as e:
        frappe.log_error(f"Error in bulk assignment: {str(e)}", "Bulk Assignment Error")
        return {"success": False, "error": f"Failed to process bulk assignments: {str(e)}"}


def add_member_to_chapter_roster(member_name, new_chapter):
    """Add member to chapter's member roster using centralized manager"""
    try:
        if new_chapter:
            # Use centralized chapter membership manager for proper history tracking
            from verenigingen.utils.chapter_membership_manager import ChapterMembershipManager

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
def debug_address_members(member_id):
    """Debug method to test address members functionality"""
    try:
        member = frappe.get_doc("Member", member_id)

        result = {
            "member_id": member.name,
            "member_name": f"{member.first_name} {member.last_name}",
            "primary_address": member.primary_address,
            "address_members_html": None,
            "address_members_html_length": 0,
            "other_members_count": 0,
            "other_members_list": [],
            "current_field_value": member.get("other_members_at_address"),
        }

        # Test the HTML generation
        html_result = member.get_address_members_html()
        result["address_members_html"] = html_result
        result["address_members_html_length"] = len(html_result) if html_result else 0

        # Test the underlying method
        other_members = member.get_other_members_at_address()
        result["other_members_count"] = len(other_members) if other_members else 0
        result["other_members_list"] = other_members if other_members else []

        return result

    except Exception as e:
        return {"error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def manually_populate_address_members(member_id):
    """Manually populate the address members field to test UI"""
    try:
        member = frappe.get_doc("Member", member_id)

        # Generate the HTML content
        html_content = member.get_address_members_html()

        # Set the field value directly
        member.other_members_at_address = html_content
        member.save(ignore_permissions=True)

        return {
            "success": True,
            "message": f"Field populated for {member_id}",
            "html_length": len(html_content) if html_content else 0,
            "field_value": member.other_members_at_address,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def clear_address_members_field(member_id):
    """Clear the address members field to test automatic population"""
    try:
        member = frappe.get_doc("Member", member_id)
        member.other_members_at_address = None
        member.save(ignore_permissions=True)

        return {"success": True, "message": f"Field cleared for {member_id}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_simple_field_population(member_id):
    """Test setting a simple value to verify field visibility"""
    try:
        member = frappe.get_doc("Member", member_id)

        # Set a simple test value
        test_html = '<div style="background: red; color: white; padding: 10px;">TEST: This field is working! If you can see this, the field is visible.</div>'
        member.other_members_at_address = test_html
        member.save(ignore_permissions=True)

        return {"success": True, "message": f"Test content set for {member_id}", "test_html": test_html}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@handle_api_error
def get_address_members_html_api(member_id):
    """Dedicated API method to get address members HTML - completely separate from document methods"""
    try:
        member = frappe.get_doc("Member", member_id)

        if not member.primary_address:
            return {
                "success": True,
                "html": '<div class="text-muted"><i class="fa fa-home"></i> No address selected</div>',
            }

        # Get the address document
        try:
            address_doc = frappe.get_doc("Address", member.primary_address)
        except Exception:
            return {
                "success": True,
                "html": '<div class="text-muted"><i class="fa fa-exclamation-triangle"></i> Address not found</div>',
            }

        # Find other members at the same physical address
        if not address_doc.address_line1 or not address_doc.city:
            return {
                "success": True,
                "html": '<div class="text-muted"><i class="fa fa-info-circle"></i> Incomplete address information</div>',
            }

        # Normalize the address components for matching
        normalized_address_line = address_doc.address_line1.lower().strip()
        normalized_city = address_doc.city.lower().strip()

        # Find all addresses with matching physical location (optimized query)
        matching_addresses = frappe.get_all(
            "Address",
            fields=["name", "address_line1", "city"],
            filters={
                "address_line1": address_doc.address_line1,  # Exact match instead of LIKE
                "city": address_doc.city,
            },
        )

        same_location_addresses = []
        for addr in matching_addresses:
            if addr.address_line1 and addr.city:
                addr_line_normalized = addr.address_line1.lower().strip()
                addr_city_normalized = addr.city.lower().strip()

                # Match if address line AND city are the same (case-insensitive)
                if (
                    addr_line_normalized == normalized_address_line
                    and addr_city_normalized == normalized_city
                ):
                    same_location_addresses.append(addr.name)

        if not same_location_addresses:
            return {
                "success": True,
                "html": '<div class="text-muted"><i class="fa fa-info-circle"></i> No other members found at this address</div>',
            }

        # Find members using any of the matching addresses, excluding current member
        other_members = frappe.get_all(
            "Member",
            filters={
                "primary_address": ["in", same_location_addresses],
                "name": ["!=", member.name],
                "status": ["in", ["Active", "Pending", "Suspended"]],
            },
            fields=["name", "full_name", "email", "status", "member_since", "birth_date"],
        )

        if not other_members:
            return {
                "success": True,
                "html": '<div class="text-muted"><i class="fa fa-info-circle"></i> No other members found at this address</div>',
            }

        # Generate HTML
        html_content = f'<div class="address-members-display"><h6>Other Members at This Address ({len(other_members)} found):</h6>'

        for other in other_members:
            # Guess relationship
            guess_relationship_simple(member, other)

            # Get age group
            get_age_group_simple(other.get("birth_date"))

            # Get status color
            get_status_color_simple(other.get("status", "Unknown"))

            html_content += f"""
            <div class="member-card" style="border: 1px solid #ddd; padding: 8px; margin: 4px 0; border-radius: 4px; background: #f8f9fa;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <div style="flex-grow: 1;">
                        <strong>{other.get("full_name", "Unknown")}</strong>
                        <span class="text-muted">({other.get("name", "Unknown ID")})</span>
                        <br><small class="text-muted">
                            <i class="fa fa-users"></i> {relationship} |
                            <i class="fa fa-birthday-cake"></i> {age_group} |
                            <i class="fa fa-circle text-{status_color}"></i> {other.get("status", "Unknown")}
                        </small>
                        <br><small class="text-muted">
                            <i class="fa fa-envelope"></i> {other.get("email", "Unknown")}
                        </small>
                    </div>
                    <div style="margin-left: 12px;">
                        <button type="button" class="btn btn-xs btn-default view-member-btn"
                                data-member="{other.get("name", "")}"
                                style="font-size: 11px; padding: 4px 8px;">
                            <i class="fa fa-external-link" style="margin-right: 4px;"></i>View
                        </button>
                    </div>
                </div>
            </div>
            """
        html_content += "</div>"

        return {"success": True, "html": html_content}

    except Exception as e:
        frappe.log_error(f"Error in get_address_members_html_api for {member_id}: {str(e)}")
        return {
            "success": False,
            "html": f'<div class="text-danger"><i class="fa fa-exclamation-triangle"></i> Error loading member information: {str(e)}</div>',
        }


def guess_relationship_simple(member1, member2_data):
    """Simple relationship guessing"""
    # Extract last names
    member1_last = member1.last_name.lower() if member1.last_name else ""
    member2_name = member2_data.get("full_name", "")
    member2_last = member2_name.split()[-1].lower() if member2_name else ""

    # Same last name suggests family
    if member1_last and member2_last and member1_last == member2_last:
        return "Family Member"
    else:
        return "Household Member"


def get_age_group_simple(birth_date):
    """Simple age group calculation"""
    if not birth_date:
        return "Unknown"

    try:
        from frappe.utils import date_diff, today

        age = date_diff(today(), birth_date) / 365.25

        if age < 18:
            return "Minor"
        elif age < 30:
            return "Young Adult"
        elif age < 50:
            return "Adult"
        elif age < 65:
            return "Middle-aged"
        else:
            return "Senior"
    except Exception:
        return "Unknown"


def get_status_color_simple(status):
    """Simple status color mapping"""
    status_colors = {
        "Active": "success",
        "Pending": "warning",
        "Suspended": "danger",
        "Terminated": "secondary",
    }
    return status_colors.get(status, "secondary")


@frappe.whitelist()
def get_mt940_import_url():
    """Get URL for MT940 import page"""
    return "/mt940_import"


@frappe.whitelist()
def test_mt940_extraction(file_content, bank_account=None):
    """Test the extraction function on first transaction"""
    try:
        import base64
        import tempfile

        # Decode content
        mt940_content = base64.b64decode(file_content).decode("utf-8")

        # Try to import mt940 library
        try:
            import mt940
        except ImportError:
            return {"success": False, "error": "MT940 library not available"}

        # Parse without calling the extraction function first to isolate the issue
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sta", delete=False) as temp_file:
            temp_file.write(mt940_content)
            temp_file_path = temp_file.name

        try:
            transactions = mt940.parse(temp_file_path)
            transaction_list = list(transactions)

            if not transaction_list:
                return {"success": False, "error": "No statements found"}

            first_statement = transaction_list[0]
            if not hasattr(first_statement, "transactions") or not first_statement.transactions:
                return {"success": False, "error": "No transactions in first statement"}

            first_transaction = first_statement.transactions[0]

            # Get raw data safely
            raw_data = {
                "date": str(first_transaction.data.get("date", "None")),
                "amount": str(first_transaction.data.get("amount", "None")),
                "currency": str(first_transaction.data.get("currency", "None")),
            }

            # Now test extraction
            try:
                extracted = extract_transaction_data_improved(first_transaction)
                return {"success": True, "raw_data": raw_data, "extracted": extracted}
            except Exception as extract_error:
                return {
                    "success": True,
                    "raw_data": raw_data,
                    "extracted": None,
                    "extraction_error": str(extract_error),
                }

        finally:
            import os

            try:
                os.unlink(temp_file_path)
            except Exception:
                pass

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def debug_mt940_import_improved(file_content, bank_account=None):
    """Debug version of MT940 import with improved transaction parsing"""
    try:
        import base64
        import tempfile

        # Decode file content
        mt940_content = base64.b64decode(file_content).decode("utf-8")

        debug_info = {
            "step": "1_file_decoded",
            "content_length": len(mt940_content),
            "content_preview": mt940_content[:500] + "..." if len(mt940_content) > 500 else mt940_content,
        }

        # Try to parse with mt940 library
        try:
            import mt940

            debug_info["step"] = "2_mt940_library_found"
        except ImportError:
            debug_info["error"] = "MT940 library not installed"
            return debug_info

        # Write to temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sta", delete=False) as temp_file:
            temp_file.write(mt940_content)
            temp_file_path = temp_file.name

        debug_info["step"] = "3_temp_file_created"

        try:
            # Parse the MT940 file
            transactions = mt940.parse(temp_file_path)
            transaction_list = list(transactions)

            debug_info["step"] = "4_file_parsed"
            debug_info["statements_found"] = len(transaction_list)

            if transaction_list:
                first_statement = transaction_list[0]
                debug_info["first_statement"] = {
                    "has_data": hasattr(first_statement, "data"),
                    "has_transactions": hasattr(first_statement, "transactions"),
                    "transaction_count": len(first_statement.transactions)
                    if hasattr(first_statement, "transactions")
                    else 0,
                }

                if hasattr(first_statement, "transactions") and first_statement.transactions:
                    first_transaction = first_statement.transactions[0]

                    # Simple inspection without calling extraction (to avoid hanging)
                    transaction_inspection = {
                        "has_date_attr": hasattr(first_transaction, "date"),
                        "has_amount_attr": hasattr(first_transaction, "amount"),
                        "has_data": hasattr(first_transaction, "data"),
                        "date_str": str(getattr(first_transaction, "date", "None")),
                        "amount_str": str(getattr(first_transaction, "amount", "None")),
                        "data_keys": list(first_transaction.data.keys())
                        if hasattr(first_transaction, "data")
                        else [],
                    }

                    # Try to get data values safely
                    if hasattr(first_transaction, "data"):
                        transaction_inspection["data_date"] = str(first_transaction.data.get("date", "None"))
                        transaction_inspection["data_amount"] = str(
                            first_transaction.data.get("amount", "None")
                        )

                    debug_info["first_transaction"] = transaction_inspection
                    debug_info["step"] = "5_transaction_inspected"

        except Exception as e:
            debug_info["parse_error"] = str(e)
            debug_info["step"] = "4_parse_failed"

        # Clean up temp file
        import os

        try:
            os.unlink(temp_file_path)
        except Exception:
            pass

        return debug_info

    except Exception as e:
        return {"error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def debug_mt940_import(file_content, bank_account=None):
    """Debug version of MT940 import to see what's happening"""
    try:
        import base64
        import tempfile

        # Decode file content
        mt940_content = base64.b64decode(file_content).decode("utf-8")

        debug_info = {
            "step": "1_file_decoded",
            "content_length": len(mt940_content),
            "content_preview": mt940_content[:500] + "..." if len(mt940_content) > 500 else mt940_content,
        }

        # Try to parse with mt940 library
        try:
            import mt940

            debug_info["step"] = "2_mt940_library_found"
        except ImportError:
            debug_info["error"] = "MT940 library not installed"
            return debug_info

        # Write to temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sta", delete=False) as temp_file:
            temp_file.write(mt940_content)
            temp_file_path = temp_file.name

        debug_info["step"] = "3_temp_file_created"
        debug_info["temp_file"] = temp_file_path

        try:
            # Parse the MT940 file
            transactions = mt940.parse(temp_file_path)
            transaction_list = list(transactions)

            debug_info["step"] = "4_file_parsed"
            debug_info["statements_found"] = len(transaction_list)

            if transaction_list:
                first_statement = transaction_list[0]
                debug_info["first_statement"] = {
                    "has_data": hasattr(first_statement, "data"),
                    "has_transactions": hasattr(first_statement, "transactions"),
                    "data_keys": list(first_statement.data.keys())
                    if hasattr(first_statement, "data")
                    else [],
                    "transaction_count": len(first_statement.transactions)
                    if hasattr(first_statement, "transactions")
                    else 0,
                }

                if hasattr(first_statement, "transactions") and first_statement.transactions:
                    first_transaction = first_statement.transactions[0]
                    debug_info["first_transaction"] = {
                        "date": str(first_transaction.date)
                        if hasattr(first_transaction, "date")
                        else "No date",
                        "amount": str(first_transaction.amount)
                        if hasattr(first_transaction, "amount")
                        else "No amount",
                        "has_data": hasattr(first_transaction, "data"),
                        "data_keys": list(first_transaction.data.keys())
                        if hasattr(first_transaction, "data")
                        else [],
                    }

        except Exception as e:
            debug_info["parse_error"] = str(e)
            debug_info["step"] = "4_parse_failed"

        # Clean up temp file
        import os

        try:
            os.unlink(temp_file_path)
        except Exception:
            pass

        return debug_info

    except Exception as e:
        return {"error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def debug_bank_account_search(iban):
    """Debug bank account search by IBAN"""
    try:
        # Get all bank accounts
        all_accounts = frappe.get_all(
            "Bank Account",
            fields=["name", "account_name", "bank_account_no", "iban", "company"],
            limit_page_length=None,
        )

        # Search by bank_account_no
        accounts_by_no = frappe.get_all(
            "Bank Account",
            filters={"bank_account_no": iban},
            fields=["name", "account_name", "bank_account_no", "iban", "company"],
        )

        # Search by iban field
        accounts_by_iban = frappe.get_all(
            "Bank Account",
            filters={"iban": iban},
            fields=["name", "account_name", "bank_account_no", "iban", "company"],
        )

        return {
            "search_iban": iban,
            "total_accounts": len(all_accounts),
            "all_accounts": all_accounts,
            "found_by_bank_account_no": accounts_by_no,
            "found_by_iban_field": accounts_by_iban,
        }

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def debug_duplicate_detection(file_content_b64, bank_account, company=None):
    """Debug the duplicate detection logic specifically"""
    try:
        import base64
        import hashlib

        # Decode and parse file
        mt940_content = base64.b64decode(file_content_b64).decode("utf-8")
        from mt940 import parse

        statements = parse(mt940_content)

        debug_info = {
            "total_transactions": 0,
            "sample_transactions": [],
            "duplicate_analysis": [],
            "existing_transaction_ids": [],
            "hash_analysis": {},
        }

        # Get existing transaction IDs for this bank account
        existing_transactions = frappe.db.sql(
            """
            SELECT transaction_id, date, deposit, withdrawal, description
            FROM `tabBank Transaction`
            WHERE bank_account = %s
            ORDER BY date DESC
            LIMIT 50
        """,
            [bank_account],
            as_dict=True,
        )

        debug_info["existing_transaction_ids"] = [
            f"{t.transaction_id}: {t.date} - {t.description[:30]}..." for t in existing_transactions
        ]

        # Analyze first few transactions - use same logic as working import
        transaction_count = 0
        for statement in statements:
            # Debug the statement structure first
            debug_info["statement_structure"] = {
                "statement_data_keys": list(statement.data.keys())
                if hasattr(statement, "data")
                else "No data attribute",
                "statement_attributes": [attr for attr in dir(statement) if not attr.startswith("_")],
                "has_transactions_attr": hasattr(statement, "transactions"),
                "transactions_type": str(type(statement.transactions))
                if hasattr(statement, "transactions")
                else "No transactions attr",
            }

            # Use same transaction access pattern as working import
            if hasattr(statement, "transactions") and statement.transactions:
                statement_transactions = statement.transactions
                debug_info["statement_structure"]["transactions_location"] = "statement.transactions"
            else:
                # Alternative: statement IS the transaction
                statement_transactions = [statement]
                debug_info["statement_structure"]["transactions_location"] = "statement as single transaction"

            for transaction in statement_transactions:
                transaction_count += 1

                # Extract data using same logic as import
                transaction_data = extract_transaction_data_improved(transaction)
                if not transaction_data:
                    continue

                # Generate ID using same improved logic as create function
                id_components = [
                    str(transaction_data["date"]),
                    str(transaction_data["amount"]),
                    str(transaction_data.get("description") or "")[:100],  # Use more of description
                    str(transaction_data.get("counterparty_name") or ""),
                    str(transaction_data.get("counterparty_account") or ""),
                    str(transaction_data.get("reference") or ""),
                    str(transaction_data.get("bank_reference") or ""),
                    bank_account,  # Include bank account in hash to prevent cross-account collisions
                ]

                # Create a more robust hash using all components
                hash_input = "|".join(id_components)  # Use separator to prevent concatenation issues
                transaction_id = hashlib.sha256(hash_input.encode()).hexdigest()[:16]

                # Check if exists
                exists = frappe.db.exists(
                    "Bank Transaction", {"transaction_id": transaction_id, "bank_account": bank_account}
                )

                # Check for hash collisions
                if transaction_id in debug_info["hash_analysis"]:
                    debug_info["hash_analysis"][transaction_id]["count"] += 1
                    debug_info["hash_analysis"][transaction_id]["collisions"].append(
                        {
                            "transaction_number": transaction_count,
                            "date": str(transaction_data["date"]),
                            "amount": transaction_data["amount"],
                            "description": transaction_data["description"][:50],
                        }
                    )
                else:
                    debug_info["hash_analysis"][transaction_id] = {
                        "count": 1,
                        "hash_input": hash_input[:200],
                        "collisions": [],
                    }

                # Add to sample (first 10 transactions)
                if len(debug_info["sample_transactions"]) < 10:
                    debug_info["sample_transactions"].append(
                        {
                            "transaction_number": transaction_count,
                            "date": str(transaction_data["date"]),
                            "amount": transaction_data["amount"],
                            "description": transaction_data["description"][:50],
                            "reference": transaction_data.get("reference", ""),
                            "bank_reference": transaction_data.get("bank_reference", ""),
                            "generated_id": transaction_id,
                            "hash_input": hash_input[:100],
                            "id_components": id_components,
                            "exists_in_db": bool(exists),
                            "raw_transaction_data": str(transaction.data)[:200],
                        }
                    )

                # Analyze duplicates
                if exists:
                    existing_record = frappe.db.get_value(
                        "Bank Transaction",
                        {"transaction_id": transaction_id, "bank_account": bank_account},
                        ["date", "deposit", "withdrawal", "description"],
                        as_dict=True,
                    )

                    debug_info["duplicate_analysis"].append(
                        {
                            "new_transaction": {
                                "date": str(transaction_data["date"]),
                                "amount": transaction_data["amount"],
                                "description": transaction_data["description"][:50],
                            },
                            "existing_transaction": existing_record,
                            "transaction_id": transaction_id,
                        }
                    )

                    # Stop after finding 5 duplicates
                    if len(debug_info["duplicate_analysis"]) >= 5:
                        break

        debug_info["total_transactions"] = transaction_count

        # Analyze hash collisions
        collision_summary = {}
        for hash_id, data in debug_info["hash_analysis"].items():
            if data["count"] > 1:
                collision_summary[hash_id] = {
                    "collision_count": data["count"],
                    "hash_input": data["hash_input"],
                    "colliding_transactions": data["collisions"],
                }

        debug_info["collision_summary"] = collision_summary
        debug_info["total_collisions"] = len(collision_summary)

        return debug_info

    except Exception as e:
        return {"error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def debug_mt940_import_detailed(file_content, bank_account=None, company=None):
    """Debug version that shows exactly what's happening during import"""
    try:
        import base64
        import tempfile

        # Decode file content
        mt940_content = base64.b64decode(file_content).decode("utf-8")

        debug_results = {"step": "1_decoded", "content_length": len(mt940_content)}

        # Get company from bank account if not provided
        if bank_account and not company:
            company = frappe.db.get_value("Bank Account", bank_account, "company")
            debug_results["company_from_bank_account"] = company

        # Ensure we have a company
        if not company:
            # Get default company
            companies = frappe.get_all("Company", limit=1)
            if companies:
                company = companies[0].name
                debug_results["default_company_used"] = company

        # Auto-detect bank account if not provided
        if not bank_account:
            statement_iban = extract_iban_from_mt940_content(mt940_content)
            debug_results["extracted_iban"] = statement_iban

            if statement_iban:
                bank_account = find_bank_account_by_iban_improved(statement_iban, company)
                debug_results["found_bank_account"] = bank_account

                # Add detailed search debug
                debug_search = debug_bank_account_search(statement_iban)
                debug_results["iban_search_debug"] = debug_search

                if not bank_account:
                    debug_results["error"] = f"No Bank Account found with IBAN {statement_iban}"
                    return debug_results
            else:
                debug_results[
                    "error"
                ] = "Could not extract IBAN from MT940 file and no bank account specified"
                return debug_results

        debug_results["final_bank_account"] = bank_account
        debug_results["final_company"] = company

        # Validate bank account exists
        if not frappe.db.exists("Bank Account", bank_account):
            debug_results["error"] = f"Bank Account {bank_account} does not exist"
            return debug_results

        # Import mt940 library
        try:
            import mt940

            debug_results["step"] = "2_library_imported"
        except ImportError:
            debug_results["error"] = "MT940 library not available"
            return debug_results

        # Write to temp file and parse
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sta", delete=False) as temp_file:
            temp_file.write(mt940_content)
            temp_file_path = temp_file.name

        try:
            transactions = mt940.parse(temp_file_path)
            transaction_list = list(transactions)

            debug_results["step"] = "3_parsed"
            debug_results["statements_found"] = len(transaction_list)

            if not transaction_list:
                debug_results["error"] = "No statements found in MT940 file"
                return debug_results

            # Test first transaction only
            first_statement = transaction_list[0]
            if hasattr(first_statement, "transactions") and first_statement.transactions:
                first_transaction = first_statement.transactions[0]

                # Extract and test creation
                transaction_data = extract_transaction_data_improved(first_transaction)
                debug_results["extraction_result"] = transaction_data

                if transaction_data:
                    creation_result = create_bank_transaction_improved(
                        transaction_data, bank_account, company
                    )
                    debug_results["creation_result"] = creation_result
                else:
                    debug_results["creation_result"] = "extraction_failed"

            debug_results["step"] = "4_complete"
            return debug_results

        finally:
            # Clean up temp file
            import os

            try:
                os.unlink(temp_file_path)
            except Exception:
                pass

    except Exception as e:
        return {"error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def import_mt940_improved(file_content, bank_account=None, company=None):
    """Improved MT940 import with better transaction handling"""
    try:
        import base64
        import tempfile

        # Decode file content
        mt940_content = base64.b64decode(file_content).decode("utf-8")

        # Get company from bank account if not provided
        if bank_account and not company:
            company = frappe.db.get_value("Bank Account", bank_account, "company")

        # Ensure we have a company
        if not company:
            # Get default company
            companies = frappe.get_all("Company", limit=1)
            if companies:
                company = companies[0].name

        # Auto-detect bank account if not provided
        if not bank_account:
            statement_iban = extract_iban_from_mt940_content(mt940_content)
            if statement_iban:
                bank_account = find_bank_account_by_iban_improved(statement_iban, company)
                if not bank_account:
                    return {
                        "success": False,
                        "message": f"No Bank Account found with IBAN {statement_iban}",
                        "extracted_iban": statement_iban,
                    }
            else:
                return {
                    "success": False,
                    "message": "Could not extract IBAN from MT940 file and no bank account specified",
                }

        # Validate bank account exists
        if not frappe.db.exists("Bank Account", bank_account):
            return {"success": False, "message": f"Bank Account {bank_account} does not exist"}

        # Import mt940 library
        try:
            import mt940
        except ImportError:
            return {
                "success": False,
                "message": "MT940 library not available. Please install with: pip install mt-940",
            }

        # Write to temp file and parse
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sta", delete=False) as temp_file:
            temp_file.write(mt940_content)
            temp_file_path = temp_file.name

        try:
            transactions = mt940.parse(temp_file_path)
            transaction_list = list(transactions)

            if not transaction_list:
                return {"success": False, "message": "No statements found in MT940 file"}

            transactions_created = 0
            transactions_skipped = 0
            errors = []

            # Fix for MT940 library bug: library may return duplicate statements
            # Use only the first statement to avoid processing duplicates
            processed_transaction_ids = set()

            for statement in transaction_list:
                # Handle different statement structures
                statement_transactions = []

                if hasattr(statement, "transactions") and statement.transactions:
                    # Standard structure: statement has transactions list
                    statement_transactions = statement.transactions
                else:
                    # Alternative: statement IS the transaction
                    statement_transactions = [statement]

                for transaction in statement_transactions:
                    try:
                        # Extract transaction data properly
                        transaction_data = extract_transaction_data_improved(transaction)

                        if transaction_data:
                            # Create a unique identifier for this transaction to avoid MT940 library duplicates
                            transaction_signature = (
                                str(transaction_data["date"]),
                                str(transaction_data["amount"]),
                                str(transaction_data.get("reference", "")),
                                str(transaction_data.get("description", ""))[:50],
                            )

                            # Skip if we've already processed this exact transaction
                            if transaction_signature in processed_transaction_ids:
                                continue

                            processed_transaction_ids.add(transaction_signature)

                            creation_result = create_bank_transaction_improved(
                                transaction_data, bank_account, company
                            )
                            if creation_result == "created":
                                transactions_created += 1
                            elif creation_result == "exists":
                                transactions_skipped += 1
                            else:
                                transactions_skipped += 1
                                errors.append(f"Failed to create transaction: {creation_result}")
                        else:
                            transactions_skipped += 1
                            errors.append("Failed to extract transaction data")

                    except Exception as e:
                        transactions_skipped += 1
                        errors.append(f"Transaction error: {str(e)}")
                        frappe.logger().error(f"Error processing MT940 transaction: {str(e)}")

            # Clean up temp file
            import os

            try:
                os.unlink(temp_file_path)
            except Exception:
                pass

            return {
                "success": True,
                "message": f"Import completed: {transactions_created} transactions created, {transactions_skipped} skipped",
                "transactions_created": transactions_created,
                "transactions_skipped": transactions_skipped,
                "bank_account": bank_account,
                "errors": errors[:5],  # Only show first 5 errors
                "debug_info": {
                    "total_statements": len(transaction_list),
                    "total_transactions_processed": transactions_created + transactions_skipped,
                    "first_few_errors": errors[:3],
                },
            }

        except Exception as e:
            return {"success": False, "message": f"Failed to parse MT940 file: {str(e)}"}

    except Exception as e:
        return {"success": False, "message": f"Import failed: {str(e)}"}


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


def extract_transaction_data_improved(transaction):
    """Extract transaction data from MT940 transaction object"""
    try:
        import re

        from frappe.utils import getdate

        # Get transaction data - all data is in the data dictionary
        data = transaction.data if hasattr(transaction, "data") else {}

        # Extract date from data dictionary
        transaction_date = None
        if "date" in data and data["date"]:
            try:
                transaction_date = getdate(data["date"])
            except Exception:
                pass

        # Extract amount from data dictionary
        # Amount comes as string like "-898.54 EUR" or "1234.56 EUR"
        amount = None
        currency = "EUR"

        if "amount" in data and data["amount"]:
            amount_str = str(data["amount"]).strip()

            # Parse amount string like "-898.54 EUR" or "1234.56"
            # Remove currency and extract numeric value
            currency_match = re.search(r"([A-Z]{3})$", amount_str)
            if currency_match:
                currency = currency_match.group(1)
                amount_str = amount_str.replace(currency, "").strip()

            # Extract numeric value
            try:
                amount = float(amount_str)
            except Exception:
                # Try to extract just the numeric part
                numeric_match = re.search(r"([+-]?\d+\.?\d*)", amount_str)
                if numeric_match:
                    amount = float(numeric_match.group(1))

        # Also try currency from separate field
        if "currency" in data and data["currency"]:
            currency = data["currency"]

        # Skip if essential data is missing
        if not transaction_date or amount is None:
            return None

        # Build transaction data
        transaction_data = {
            "date": transaction_date,
            "amount": amount,
            "currency": currency,
            "description": "",
            "reference": data.get("transaction_reference", ""),
            "bank_reference": data.get("bank_reference", ""),
            "counterparty_name": data.get("customer_reference", ""),
            "counterparty_account": data.get("counterparty_account", ""),
            "extra_details": data.get("extra_details", ""),
        }

        # Build description from available fields
        description_parts = []
        if data.get("extra_details"):
            description_parts.append(data["extra_details"])
        if data.get("transaction_details"):
            description_parts.append(data["transaction_details"])
        # Add funds code and transaction reference for more context
        if data.get("funds_code"):
            description_parts.append(f"Funds: {data['funds_code']}")
        if data.get("transaction_reference"):
            description_parts.append(f"Ref: {data['transaction_reference']}")

        transaction_data["description"] = " | ".join(filter(None, description_parts)) or "MT940 Transaction"

        return transaction_data

    except Exception as e:
        frappe.logger().error(f"Error extracting transaction data: {str(e)}")
        return None


def create_bank_transaction_improved(transaction_data, bank_account, company):
    """Create ERPNext Bank Transaction from extracted data"""
    try:
        import hashlib

        # Validate required data
        if not transaction_data.get("date") or transaction_data.get("amount") is None:
            return "missing_required_data"

        # Generate unique transaction ID with more specific components
        id_components = [
            str(transaction_data["date"]),
            str(transaction_data["amount"]),
            str(transaction_data.get("description") or "")[:100],  # Use more of description
            str(transaction_data.get("counterparty_name") or ""),
            str(transaction_data.get("counterparty_account") or ""),
            str(transaction_data.get("reference") or ""),
            str(transaction_data.get("bank_reference") or ""),
            bank_account,  # Include bank account in hash to prevent cross-account collisions
        ]

        # Create a more robust hash using all components
        hash_input = "|".join(id_components)  # Use separator to prevent concatenation issues
        transaction_id = hashlib.sha256(hash_input.encode()).hexdigest()[:16]

        # Check if transaction already exists
        if frappe.db.exists(
            "Bank Transaction", {"transaction_id": transaction_id, "bank_account": bank_account}
        ):
            return "exists"

        # Validate bank account exists
        if not frappe.db.exists("Bank Account", bank_account):
            return f"bank_account_not_found: {bank_account}"

        # Create new Bank Transaction
        bt = frappe.new_doc("Bank Transaction")
        bt.date = transaction_data["date"]
        bt.bank_account = bank_account
        bt.company = company
        bt.currency = transaction_data.get("currency", "EUR")

        # Handle amount and direction
        amount = transaction_data["amount"]
        if amount >= 0:
            bt.deposit = amount
            bt.withdrawal = 0
        else:
            bt.deposit = 0
            bt.withdrawal = abs(amount)

        bt.description = transaction_data["description"]
        bt.reference_number = transaction_data.get("reference", "")
        bt.transaction_id = transaction_id

        # Set counterparty information
        if transaction_data.get("counterparty_name"):
            bt.bank_party_name = transaction_data["counterparty_name"]
        if transaction_data.get("counterparty_account"):
            bt.bank_party_iban = transaction_data["counterparty_account"]

        # Insert transaction
        bt.insert()
        bt.submit()

        return "created"

    except Exception as e:
        error_msg = str(e)
        frappe.logger().error(f"Error creating bank transaction: {error_msg}")
        return f"error: {error_msg}"
