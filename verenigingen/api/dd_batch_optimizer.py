"""
SEPA Direct Debit Batch Optimization System
Automatically creates optimally-sized batches for efficient processing
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, now_datetime

from verenigingen.utils.security.api_security_framework import critical_api, high_security_api, standard_api
from verenigingen.utils.security.authorization import (
    SEPAOperation,
    SEPAPermissionLevel,
    require_sepa_permission,
)

# Configuration constants
DEFAULT_CONFIG = {
    "max_amount_per_batch": 4000,  # Stay below €5000 high-risk threshold
    "max_invoices_per_batch": 20,  # Optimal processing size
    "min_invoices_per_batch": 3,  # Avoid tiny batches
    "max_batches_per_day": 5,  # Bank processing limits
    "preferred_batch_size": 15,  # Sweet spot for efficiency
    "risk_distribution_target": {  # Target risk distribution
        "High": 0.1,  # Max 10% high-risk batches
        "Medium": 0.3,  # Max 30% medium-risk batches
        "Low": 0.6,  # Prefer 60% low-risk batches
    },
}


@critical_api()
@require_sepa_permission(SEPAPermissionLevel.CREATE, SEPAOperation.BATCH_CREATE)
@frappe.whitelist()
def create_optimal_batches(target_date=None, config=None):
    """
    Create optimally-sized SEPA Direct Debit batches automatically

    Args:
        target_date: Date for batch processing (default: tomorrow)
        config: Custom configuration overrides

    Returns:
        Dict with batch creation results
    """
    if not target_date:
        target_date = add_days(getdate(), 1)  # Default to tomorrow

    if isinstance(target_date, str):
        target_date = getdate(target_date)

    # Merge custom config with defaults
    batch_config = DEFAULT_CONFIG.copy()
    if config:
        batch_config.update(config)

    frappe.logger().info(f"Starting optimal batch creation for {target_date}")

    try:
        # Step 1: Get all eligible invoices
        eligible_invoices = get_eligible_invoices_for_batching()

        if not eligible_invoices:
            return {
                "success": True,
                "message": "No eligible invoices found for batching",
                "batches_created": 0,
                "total_invoices": 0,
            }

        # Step 2: Analyze and categorize invoices
        invoice_analysis = analyze_invoices_for_optimization(eligible_invoices)

        # Step 3: Create optimal batch combinations
        batch_groups = create_optimal_batch_groups(invoice_analysis, batch_config)

        # Step 4: Create actual DD batch documents
        created_batches = []
        for group_index, batch_group in enumerate(batch_groups):
            batch_doc = create_dd_batch_document(batch_group, target_date, group_index + 1, batch_config)
            created_batches.append(batch_doc)

        # Step 5: Generate optimization report
        optimization_report = generate_optimization_report(eligible_invoices, created_batches, batch_config)

        frappe.logger().info(f"Created {len(created_batches)} optimized batches")

        return {
            "success": True,
            "message": f"Created {len(created_batches)} optimized batches with {len(eligible_invoices)} invoices",
            "batches_created": len(created_batches),
            "batch_names": [batch.name for batch in created_batches],
            "total_invoices": len(eligible_invoices),
            "optimization_report": optimization_report,
        }

    except Exception as e:
        frappe.log_error(f"Error in optimal batch creation: {str(e)}", "DD Batch Optimization Error")
        return {"success": False, "error": str(e), "batches_created": 0}


def get_eligible_invoices_for_batching():
    """
    Get all invoices eligible for SEPA Direct Debit batching
    ⚠️ CRITICAL: Includes member status validation to prevent billing terminated members
    """

    # Get unpaid invoices with SEPA mandates and ACTIVE MEMBER STATUS
    # Join through customer relationship since Member.customer links to Sales Invoice.customer
    invoices = frappe.db.sql(
        """
        SELECT
            si.name as invoice,
            si.customer,
            si.grand_total as amount,
            si.currency,
            si.posting_date,
            m.name as membership,
            mem.name as member,
            mem.full_name as member_name,
            mem.iban,
            mem.payment_method,
            sm.mandate_id as mandate_reference,
            mem.member_since,
            mem.status as member_status,
            m.status as membership_status,
            'Normal' as priority
        FROM
            `tabMember` mem
        JOIN `tabMembership` m ON m.member = mem.name
        JOIN `tabSales Invoice` si ON si.customer = mem.customer
        LEFT JOIN `tabSEPA Mandate` sm ON sm.member = mem.name AND sm.status = 'Active'
        WHERE
            si.docstatus = 1
            AND si.status IN ('Unpaid', 'Overdue')
            AND si.outstanding_amount > 0
            AND mem.payment_method = 'SEPA Direct Debit'
            AND mem.iban IS NOT NULL
            AND mem.iban != ''
            AND mem.customer IS NOT NULL
            AND sm.mandate_id IS NOT NULL
            -- ⚠️ CRITICAL VALIDATION: Exclude terminated/inactive members
            AND mem.status NOT IN ('Terminated', 'Expelled', 'Deceased', 'Suspended', 'Quit')
            AND m.status = 'Active'
            -- Exclude invoices already in batches
            AND si.name NOT IN (
                SELECT DISTINCT ddi.invoice
                FROM `tabDirect Debit Batch Invoice` ddi
                JOIN `tabDirect Debit Batch` ddb ON ddi.parent = ddb.name
                WHERE ddb.docstatus != 2
            )
        ORDER BY
            si.posting_date ASC,
            si.grand_total DESC
    """,
        as_dict=True,
    )

    # Additional validation for edge cases
    validated_invoices = []
    excluded_count = 0

    for invoice in invoices:
        # Double-check member eligibility for billing
        if validate_member_eligibility_for_billing(invoice):
            validated_invoices.append(invoice)
        else:
            excluded_count += 1
            frappe.logger().warning(
                f"Excluded invoice {invoice['invoice']} for member {invoice['member']} "
                f"due to member status validation failure"
            )

    frappe.logger().info(
        f"Found {len(validated_invoices)} eligible invoices for batching "
        f"({excluded_count} excluded due to member status)"
    )
    return validated_invoices


def validate_member_eligibility_for_billing(invoice_data):
    """
    ⚠️ CRITICAL VALIDATION: Check if member is eligible for billing
    This function MUST be called before creating any invoice or DD batch entry
    """
    member_name = invoice_data.get("member")
    if not member_name:
        return False

    try:
        # Check member status
        member_status = invoice_data.get("member_status")
        if member_status in ["Terminated", "Expelled", "Deceased", "Suspended", "Quit"]:
            frappe.log_error(
                f"Attempted to bill terminated member: {member_name} (status: {member_status})",
                "Member Status Validation",
            )
            return False

        # Check membership status
        membership_status = invoice_data.get("membership_status")
        if membership_status != "Active":
            frappe.log_error(
                f"Attempted to bill member with inactive membership: {member_name} (membership status: {membership_status})",
                "Membership Status Validation",
            )
            return False

        # Check if member has valid SEPA mandate
        if invoice_data.get("payment_method") == "SEPA Direct Debit":
            mandate_exists = frappe.db.exists(
                "SEPA Mandate", {"member": member_name, "status": "Active", "is_active": 1}
            )
            if not mandate_exists:
                frappe.log_error(
                    f"Member {member_name} has no active SEPA mandate", "SEPA Mandate Validation"
                )
                return False

        return True

    except Exception as e:
        frappe.log_error(
            f"Error validating member eligibility for {member_name}: {str(e)}",
            "Member Eligibility Validation Error",
        )
        return False


@high_security_api()
@require_sepa_permission(SEPAPermissionLevel.VALIDATE, SEPAOperation.INVOICE_VALIDATE)
@frappe.whitelist()
def validate_all_pending_invoices():
    """
    Emergency function to validate all pending invoices for member status issues
    Returns report of issues found
    """
    results = {
        "total_checked": 0,
        "issues_found": 0,
        "terminated_members": [],
        "inactive_memberships": [],
        "missing_mandates": [],
        "validation_errors": [],
    }

    try:
        # Get all unpaid membership invoices
        pending_invoices = frappe.db.sql(
            """
            SELECT
                si.name as invoice,
                si.customer,
                si.outstanding_amount,
                mem.name as member,
                mem.full_name as member_name,
                mem.status as member_status,
                m.status as membership_status,
                mem.payment_method
            FROM
                `tabSales Invoice` si
            JOIN `tabMembership` m ON si.membership = m.name
            JOIN `tabMember` mem ON m.member = mem.name
            WHERE
                si.docstatus = 1
                AND si.status IN ('Unpaid', 'Overdue')
                AND si.outstanding_amount > 0
        """,
            as_dict=True,
        )

        results["total_checked"] = len(pending_invoices)

        for invoice in pending_invoices:
            # Check for terminated members
            if invoice["member_status"] in ["Terminated", "Expelled", "Deceased", "Suspended", "Quit"]:
                results["terminated_members"].append(
                    {
                        "invoice": invoice["invoice"],
                        "member": invoice["member"],
                        "member_name": invoice["member_name"],
                        "status": invoice["member_status"],
                        "amount": invoice["outstanding_amount"],
                    }
                )
                results["issues_found"] += 1

            # Check for inactive memberships
            elif invoice["membership_status"] != "Active":
                results["inactive_memberships"].append(
                    {
                        "invoice": invoice["invoice"],
                        "member": invoice["member"],
                        "member_name": invoice["member_name"],
                        "membership_status": invoice["membership_status"],
                        "amount": invoice["outstanding_amount"],
                    }
                )
                results["issues_found"] += 1

            # Check for missing SEPA mandates
            elif invoice["payment_method"] == "SEPA Direct Debit":
                mandate_exists = frappe.db.exists(
                    "SEPA Mandate", {"member": invoice["member"], "status": "Active", "is_active": 1}
                )
                if not mandate_exists:
                    results["missing_mandates"].append(
                        {
                            "invoice": invoice["invoice"],
                            "member": invoice["member"],
                            "member_name": invoice["member_name"],
                            "amount": invoice["outstanding_amount"],
                        }
                    )
                    results["issues_found"] += 1

    except Exception as e:
        results["validation_errors"].append(str(e))

    return results


def analyze_invoices_for_optimization(invoices):
    """Analyze invoices to determine optimal grouping strategy"""

    analysis = {
        "total_invoices": len(invoices),
        "total_amount": sum(flt(inv["amount"]) for inv in invoices),
        "by_amount": defaultdict(list),
        "by_customer": defaultdict(list),
        "by_priority": defaultdict(list),
        "by_age": defaultdict(list),
        "risk_factors": [],
    }

    # Categorize by amount (for risk assessment)
    for invoice in invoices:
        amount = flt(invoice["amount"])

        if amount > 100:
            analysis["by_amount"]["high"].append(invoice)
        elif amount > 25:
            analysis["by_amount"]["medium"].append(invoice)
        else:
            analysis["by_amount"]["low"].append(invoice)

        # Group by customer for consolidation opportunities
        analysis["by_customer"][invoice["customer"]].append(invoice)

        # Group by priority
        analysis["by_priority"][invoice.get("priority", "Normal")].append(invoice)

        # Group by age (overdue vs current)
        invoice_age = (getdate() - getdate(invoice["posting_date"])).days
        if invoice_age > 30:
            analysis["by_age"]["overdue"].append(invoice)
        else:
            analysis["by_age"]["current"].append(invoice)

    # Identify risk factors
    if analysis["total_amount"] > 20000:
        analysis["risk_factors"].append("High total volume")

    if len([c for c, invs in analysis["by_customer"].items() if len(invs) > 5]) > 3:
        analysis["risk_factors"].append("Many high-volume customers")

    frappe.logger().info(f"Invoice analysis: {analysis['total_amount']}€ across {len(invoices)} invoices")
    return analysis


def create_optimal_batch_groups(analysis, config):
    """Create optimal groupings of invoices for batching"""

    all_invoices = []
    for category in analysis["by_amount"].values():
        all_invoices.extend(category)

    batch_groups = []
    remaining_invoices = all_invoices.copy()

    # Strategy 1: Prioritize high-priority invoices first
    if analysis["by_priority"].get("High"):
        priority_batches = create_priority_batches(analysis["by_priority"]["High"], config)
        batch_groups.extend(priority_batches)
        # Remove processed invoices
        processed_invoices = set()
        for batch in priority_batches:
            processed_invoices.update(inv["invoice"] for inv in batch)
        remaining_invoices = [inv for inv in remaining_invoices if inv["invoice"] not in processed_invoices]

    # Strategy 2: Create customer-consolidated batches
    customer_batches = create_customer_consolidated_batches(remaining_invoices, config)
    batch_groups.extend(customer_batches)

    # Remove processed invoices
    processed_invoices = set()
    for batch in customer_batches:
        processed_invoices.update(inv["invoice"] for inv in batch)
    remaining_invoices = [inv for inv in remaining_invoices if inv["invoice"] not in processed_invoices]

    # Strategy 3: Create amount-optimized batches for remaining invoices
    amount_batches = create_amount_optimized_batches(remaining_invoices, config)
    batch_groups.extend(amount_batches)

    frappe.logger().info(f"Created {len(batch_groups)} optimal batch groups")
    return batch_groups


def create_priority_batches(priority_invoices, config):
    """Create batches for high-priority invoices"""
    batches = []
    current_batch = []
    current_amount = 0

    for invoice in sorted(priority_invoices, key=lambda x: flt(x["amount"]), reverse=True):
        invoice_amount = flt(invoice["amount"])

        # Check if adding this invoice would exceed limits
        if (
            len(current_batch) >= config["max_invoices_per_batch"]
            or current_amount + invoice_amount > config["max_amount_per_batch"]
        ):
            if len(current_batch) >= config["min_invoices_per_batch"]:
                batches.append(current_batch)
            current_batch = []
            current_amount = 0

        current_batch.append(invoice)
        current_amount += invoice_amount

    # Add final batch if it meets minimum requirements
    if len(current_batch) >= config["min_invoices_per_batch"]:
        batches.append(current_batch)

    return batches


def create_customer_consolidated_batches(invoices, config):
    """Create batches that consolidate invoices by customer when beneficial"""
    batches = []
    customer_groups = defaultdict(list)

    # Group by customer
    for invoice in invoices:
        customer_groups[invoice["customer"]].append(invoice)

    # Process customers with multiple invoices first
    multi_invoice_customers = {k: v for k, v in customer_groups.items() if len(v) > 1}
    # single_invoice_customers = {k: v for k, v in customer_groups.items() if len(v) == 1}  # Unused

    current_batch = []
    current_amount = 0
    processed_customers = set()

    # Process multi-invoice customers
    for customer, customer_invoices in multi_invoice_customers.items():
        customer_total = sum(flt(inv["amount"]) for inv in customer_invoices)

        # If customer's invoices alone make a good batch
        if (
            len(customer_invoices) >= config["min_invoices_per_batch"]
            and customer_total <= config["max_amount_per_batch"]
        ):
            batches.append(customer_invoices)
            processed_customers.add(customer)
        else:
            # Try to fit customer invoices in current batch
            if (
                len(current_batch) + len(customer_invoices) <= config["max_invoices_per_batch"]
                and current_amount + customer_total <= config["max_amount_per_batch"]
            ):
                current_batch.extend(customer_invoices)
                current_amount += customer_total
                processed_customers.add(customer)

    # Add current batch if it's substantial
    if len(current_batch) >= config["min_invoices_per_batch"]:
        batches.append(current_batch)

    # Process remaining invoices
    remaining_invoices = []
    for customer, customer_invoices in customer_groups.items():
        if customer not in processed_customers:
            remaining_invoices.extend(customer_invoices)

    # Create additional batches from remaining invoices
    if remaining_invoices:
        additional_batches = create_amount_optimized_batches(remaining_invoices, config)
        batches.extend(additional_batches)

    return batches


def create_amount_optimized_batches(invoices, config):
    """Create batches optimized for amount distribution and risk"""
    batches = []

    # Sort invoices by amount (mix high and low for balanced risk)
    sorted_invoices = sorted(invoices, key=lambda x: flt(x["amount"]), reverse=True)

    current_batch = []
    current_amount = 0

    for invoice in sorted_invoices:
        invoice_amount = flt(invoice["amount"])

        # Check batch limits
        if (
            len(current_batch) >= config["max_invoices_per_batch"]
            or current_amount + invoice_amount > config["max_amount_per_batch"]
        ):
            if len(current_batch) >= config["min_invoices_per_batch"]:
                batches.append(current_batch)
            current_batch = []
            current_amount = 0

        current_batch.append(invoice)
        current_amount += invoice_amount

        # Create batch if we hit the preferred size
        if len(current_batch) >= config["preferred_batch_size"]:
            batches.append(current_batch)
            current_batch = []
            current_amount = 0

    # Add final batch if it meets requirements
    if len(current_batch) >= config["min_invoices_per_batch"]:
        batches.append(current_batch)

    return batches


def create_dd_batch_document(batch_invoices, target_date, batch_number, config):
    """Create actual SEPA Direct Debit Batch document with mandate usage tracking"""

    total_amount = sum(flt(inv["amount"]) for inv in batch_invoices)

    # Determine batch type based on individual mandate usage
    batch_type = determine_batch_type(batch_invoices)

    # Create batch document
    batch_doc = frappe.get_doc(
        {
            "doctype": "Direct Debit Batch",  # Use correct doctype name
            "batch_date": target_date,
            "batch_description": f"Auto-optimized batch #{batch_number} - {target_date}",
            "batch_type": batch_type,
            "currency": "EUR",  # Default to EUR
            "total_amount": total_amount,
            "entry_count": len(batch_invoices),
            "status": "Draft",
        }
    )

    # Set flag for automated processing (affects validation behavior)
    batch_doc._automated_processing = True

    # Import mandate usage functions
    from verenigingen.verenigingen.doctype.sepa_mandate_usage.sepa_mandate_usage import (
        create_mandate_usage_record,
        get_mandate_sequence_type,
    )

    # Add invoices to batch and create mandate usage records
    for invoice in batch_invoices:
        # Get mandate for this member
        mandate_name = frappe.db.get_value(
            "SEPA Mandate", {"member": invoice.get("member"), "status": "Active"}, "name"
        )

        # Determine individual sequence type for this invoice
        sequence_info = (
            get_mandate_sequence_type(mandate_name, invoice.get("invoice"))
            if mandate_name
            else {"sequence_type": "FRST", "reason": "No mandate found, defaulting to FRST"}
        )

        batch_doc.append(
            "invoices",
            {
                "invoice": invoice["invoice"],
                "membership": invoice["membership"],
                "member": invoice["member"],
                "member_name": invoice["member_name"],
                "amount": invoice["amount"],
                "currency": invoice["currency"],
                "iban": invoice["iban"],
                "mandate_reference": invoice["mandate_reference"],
                "status": "Pending",
                "sequence_type": sequence_info["sequence_type"],  # Add individual sequence type
            },
        )

        # Create mandate usage record for tracking
        if mandate_name:
            try:
                create_mandate_usage_record(
                    mandate_name=mandate_name,
                    reference_doctype="Sales Invoice",
                    reference_name=invoice["invoice"],
                    amount=invoice["amount"],
                    sequence_type=sequence_info["sequence_type"],
                )
            except Exception as e:
                frappe.log_error(
                    f"Failed to create mandate usage record for {mandate_name}: {str(e)}",
                    "Mandate Usage Creation Error",
                )

    # Save and validate
    batch_doc.insert()

    # Add batch reference to mandate usage records
    try:
        frappe.db.sql(
            """
            UPDATE `tabSEPA Mandate Usage`
            SET batch_reference = %s
            WHERE reference_doctype = 'Sales Invoice'
            AND reference_name IN %s
        """,
            (batch_doc.name, tuple(inv["invoice"] for inv in batch_invoices)),
        )
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"Failed to update batch references: {str(e)}", "Batch Reference Update Error")

    frappe.logger().info(
        f"Created batch {batch_doc.name} with {len(batch_invoices)} invoices (€{total_amount}), type: {batch_type}"
    )
    return batch_doc


def determine_batch_type(batch_invoices):
    """Determine appropriate SEPA batch type based on individual mandate usage"""

    # Import here to avoid circular imports
    from verenigingen.verenigingen.doctype.sepa_mandate_usage.sepa_mandate_usage import (
        get_mandate_sequence_type,
    )

    # Check individual mandate usage for each invoice
    sequence_types = set()

    for invoice in batch_invoices:
        # Get the mandate for this member
        mandate_name = frappe.db.get_value(
            "SEPA Mandate", {"member": invoice.get("member"), "status": "Active"}, "name"
        )

        if mandate_name:
            # Determine sequence type for this specific mandate
            sequence_info = get_mandate_sequence_type(mandate_name, invoice.get("invoice"))
            sequence_types.add(sequence_info["sequence_type"])

    # If batch contains any FRST payments, the entire batch is FRST
    # This is important for SEPA pre-notification timing requirements
    if "FRST" in sequence_types:
        return "FRST"

    # Default to recurring if all are RCUR or no sequence types found
    return "RCUR"


def generate_optimization_report(original_invoices, created_batches, config):
    """Generate report on optimization results"""

    total_original_amount = sum(flt(inv["amount"]) for inv in original_invoices)
    total_batched_amount = sum(flt(batch.total_amount) for batch in created_batches)

    # Calculate efficiency metrics
    avg_batch_size = len(original_invoices) / len(created_batches) if created_batches else 0
    avg_batch_amount = total_batched_amount / len(created_batches) if created_batches else 0

    # Risk assessment
    high_risk_batches = sum(
        1 for batch in created_batches if flt(batch.total_amount) > 4000 or batch.entry_count > 25
    )

    risk_distribution = {
        "high_risk_batches": high_risk_batches,
        "medium_risk_batches": len([b for b in created_batches if 2000 < flt(b.total_amount) <= 4000]),
        "low_risk_batches": len([b for b in created_batches if flt(b.total_amount) <= 2000]),
    }

    # Efficiency score (0-100)
    efficiency_score = calculate_efficiency_score(
        avg_batch_size, config["preferred_batch_size"], risk_distribution, len(created_batches)
    )

    report = {
        "summary": {
            "total_invoices_processed": len(original_invoices),
            "total_amount_processed": total_original_amount,
            "batches_created": len(created_batches),
            "average_batch_size": round(avg_batch_size, 1),
            "average_batch_amount": round(avg_batch_amount, 2),
            "efficiency_score": efficiency_score,
        },
        "risk_analysis": risk_distribution,
        "batch_details": [
            {
                "name": batch.name,
                "invoice_count": batch.entry_count,
                "total_amount": flt(batch.total_amount),
                "batch_type": batch.batch_type,
                "risk_level": "High"
                if flt(batch.total_amount) > 4000 or batch.entry_count > 25
                else "Medium"
                if flt(batch.total_amount) > 2000
                else "Low",
            }
            for batch in created_batches
        ],
        "optimization_config": config,
        "generated_at": now_datetime(),
    }

    return report


def calculate_efficiency_score(avg_batch_size, target_size, risk_dist, batch_count):
    """Calculate optimization efficiency score (0-100)"""

    # Size efficiency (40% weight)
    size_efficiency = max(0, 100 - abs(avg_batch_size - target_size) * 5)

    # Risk distribution efficiency (30% weight)
    risk_efficiency = 100 - (risk_dist["high_risk_batches"] * 20)  # Penalize high-risk batches

    # Batch count efficiency (30% weight) - prefer fewer, larger batches
    count_efficiency = max(0, 100 - batch_count * 5)

    total_score = size_efficiency * 0.4 + risk_efficiency * 0.3 + count_efficiency * 0.3
    return min(100, max(0, round(total_score)))


@standard_api()
@require_sepa_permission(SEPAPermissionLevel.READ, SEPAOperation.BATCH_VALIDATE)
@frappe.whitelist()
def get_batching_preview(config=None):
    """Preview what batches would be created without actually creating them"""

    batch_config = DEFAULT_CONFIG.copy()
    if config:
        batch_config.update(config)

    # Get eligible invoices
    eligible_invoices = get_eligible_invoices_for_batching()

    if not eligible_invoices:
        return {"success": True, "message": "No eligible invoices found", "preview": []}

    # Analyze and create preview
    invoice_analysis = analyze_invoices_for_optimization(eligible_invoices)
    batch_groups = create_optimal_batch_groups(invoice_analysis, batch_config)

    preview = []
    for i, group in enumerate(batch_groups):
        group_total = sum(flt(inv["amount"]) for inv in group)
        preview.append(
            {
                "batch_number": i + 1,
                "invoice_count": len(group),
                "total_amount": group_total,
                "risk_level": "High"
                if group_total > 4000 or len(group) > 25
                else "Medium"
                if group_total > 2000
                else "Low",
                "customers": list(set(inv["customer"] for inv in group)),
                "sample_invoices": [inv["invoice"] for inv in group[:3]],  # Show first 3
            }
        )

    return {
        "success": True,
        "eligible_invoices": len(eligible_invoices),
        "total_amount": sum(flt(inv["amount"]) for inv in eligible_invoices),
        "preview": preview,
        "config_used": batch_config,
    }


@critical_api()
@require_sepa_permission(SEPAPermissionLevel.ADMIN, SEPAOperation.BATCH_CREATE)
@frappe.whitelist()
def update_batch_optimization_config(new_config):
    """Update batch optimization configuration"""

    # Validate configuration
    required_fields = ["max_amount_per_batch", "max_invoices_per_batch", "min_invoices_per_batch"]
    for field in required_fields:
        if field not in new_config:
            frappe.throw(_(f"Missing required configuration field: {field}"))

    # Save to Verenigingen Settings or custom doctype
    settings = frappe.get_single("Verenigingen Settings")
    settings.batch_optimization_config = frappe.as_json(new_config)
    settings.save()

    return {"success": True, "message": "Batch optimization configuration updated", "config": new_config}
