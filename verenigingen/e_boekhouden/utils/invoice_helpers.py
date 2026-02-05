# Helper functions for enhanced invoice creation from E-Boekhouden data
import frappe
from frappe.utils import add_days, flt, getdate, now

# Re-exports from canonical locations for backward compatibility
# New code should import directly from the consolidated modules
from .consolidated.date_utils import ensure_fiscal_year_exists  # noqa: F401
from .consolidated.ledger_utils import resolve_ledger_code  # noqa: F401
from .field_mapping import (
    ACCOUNT_TYPE_MAP,
    BTW_CODE_MAP,
    DEFAULT_ITEM_GROUPS,
    DEFAULT_PAYMENT_TERMS,
    INVOICE_FIELD_MAP,
    ITEM_GROUP_KEYWORDS,
    LINE_ITEM_FIELD_MAP,
    PRICE_CATEGORY_RANGES,
    UOM_MAP,
)


def get_or_create_payment_terms(days):
    """Get or create payment terms template with enhanced Dutch business logic"""
    if not days or days <= 0:
        days = 30  # Default to 30 days

    # Check for standard Dutch payment terms
    if days in DEFAULT_PAYMENT_TERMS:
        template_name = DEFAULT_PAYMENT_TERMS[days]
    else:
        template_name = f"Netto {days} dagen"

    # Check if template already exists
    if frappe.db.exists("Payment Terms Template", template_name):
        return template_name

    # Create new payment terms template
    try:
        template = frappe.new_doc("Payment Terms Template")
        template.template_name = template_name

        # Standard single payment term
        template.append(
            "terms",
            {
                "due_date_based_on": "Day(s) after invoice date",
                "credit_days": int(days),
                "invoice_portion": 100.0,
                "description": f"Full payment due {days} days after invoice date",
            },
        )

        # Add common Dutch payment descriptions
        descriptions = {
            7: "Betaling binnen 7 dagen",
            14: "Betaling binnen 14 dagen",
            21: "Betaling binnen 21 dagen",
            30: "Betaling binnen 30 dagen",
            45: "Betaling binnen 45 dagen",
            60: "Betaling binnen 60 dagen",
        }

        if days in descriptions:
            template.terms[0].description = descriptions[days]

        template.insert()

        return template.name

    except Exception as e:
        # If creation fails, return a default
        frappe.log_error(f"Failed to create payment terms for {days} days: {str(e)}")
        return "Net 30"  # ERPNext default


def process_line_items(invoice, regels, invoice_type, cost_center, debug_info):
    """Process e-boekhouden line items with proper VAT handling"""
    if not regels:
        debug_info.append("No line items (Regels) found, creating fallback item")
        return False

    debug_info.append(f"Processing {len(regels)} line items")

    for regel in regels:
        # Handle both Dutch (SOAP) and English (REST) field names
        description = regel.get("description") or regel.get("Omschrijving", "Service")
        # Clean up description for ERPNext compatibility
        if description and description.strip():
            # Remove newlines and normalize whitespace
            description = " ".join(description.split())
            # Limit length to ERPNext's 140 character limit for item names
            if len(description) > 140:
                description = description[:137] + "..."
        else:
            description = "Service Item"  # Fallback for empty descriptions

        unit = regel.get("unit") or regel.get("Eenheid", "Nos")
        btw_code = regel.get("vatCode") or regel.get("BTWCode")
        # CRITICAL: ledgerId is E-Boekhouden's internal ID, must resolve to ledger_code
        raw_account_code = regel.get("ledgerId") or regel.get("GrootboekNummer")
        account_code = resolve_ledger_code(raw_account_code, debug_info)
        # Handle quantity and amount properly
        # E-Boekhouden stores: amount field (can be positive or negative)
        # ERPNext expects: rate (always positive) × quantity (sign determines debit/credit)
        raw_quantity = regel.get("quantity") or regel.get("Aantal")
        raw_amount = flt(regel.get("amount") or regel.get("Prijs", 0))

        # CRITICAL: Determine quantity sign based on amount sign
        # Positive amount = debit (positive qty), Negative amount = credit (negative qty)
        if getattr(invoice, "is_return", False):
            # Credit note: quantities must be negative (ERPNext requirement)
            # Amounts have been converted to positive by preprocessing
            # So we set qty based on the provided quantity or default to -1
            quantity = flt(raw_quantity) if raw_quantity else -1
            rate = abs(raw_amount)
            debug_info.append(
                f"Credit note item: rate={rate}, qty={quantity} (ERPNext is_return requirement)"
            )
        else:
            # Normal invoice or mixed invoice
            # Use amount sign to determine quantity sign
            if raw_amount < 0:
                # Negative amount = credit line item (qty = -1)
                quantity = -1 if not raw_quantity else -abs(flt(raw_quantity))
                rate = abs(raw_amount)
                debug_info.append(f"Credit line item: amount={raw_amount} → rate={rate}, qty={quantity}")
            else:
                # Positive amount = debit line item (qty = +1)
                quantity = 1 if not raw_quantity else abs(flt(raw_quantity))
                rate = abs(raw_amount)
                debug_info.append(f"Debit line item: amount={raw_amount} → rate={rate}, qty={quantity}")

        # Use rate instead of price (which was the old variable name)
        price = rate

        # Get or create item using proper Item Mapping DocType integration
        from verenigingen.e_boekhouden.utils.eboekhouden_improved_item_naming import (
            get_or_create_item_improved,
        )

        # Use the company from the invoice being processed, not defaults
        company = invoice.company

        item_code = get_or_create_item_improved(
            account_code=account_code,
            company=company,
            transaction_type="Sales" if invoice_type == "sales" else "Purchase",
            description=description,
            btw_code=btw_code,
            price=price,
            unit=unit,
        )

        # Map GL account (try both English and Dutch field names)
        # CRITICAL: NEVER allow fallbacks - they cause data corruption with fake account codes
        gl_account = map_grootboek_to_erpnext_account(
            account_code, invoice_type, company, debug_info, allow_fallback=False
        )

        # CRITICAL: Fail early if no account found - prevents ERPNext from using Item Defaults
        # which might contain invalid or cross-company account references
        if not gl_account:
            error_msg = (
                f"No account mapping found for account code {account_code} ({invoice_type} transaction). "
                f"Please create a ledger mapping or ERPNext account with this code."
            )
            debug_info.append(f"ERROR: {error_msg}")
            frappe.throw(error_msg, title="Account Mapping Required")

        # For standardized items (Event-Ticket, Bank-Costs), use clean item details instead of ugly transaction description
        if item_code in ["Event-Ticket", "Bank-Costs"]:
            # Get clean details from the actual Item master
            item_doc = frappe.get_doc("Item", item_code)
            clean_item_name = item_doc.item_name
            clean_description = item_doc.description
            debug_info.append(
                f"Using clean {item_code} item details: name='{clean_item_name}', description='{clean_description}'"
            )
        else:
            # Use original transaction description for other items
            clean_item_name = description[:140]
            clean_description = description

        line_item = {
            "item_code": item_code,
            "item_name": clean_item_name,
            "description": clean_description,
            "qty": quantity,
            "uom": map_unit_of_measure(unit),
            "rate": price,
            "cost_center": cost_center,
        }

        # For Purchase Invoices, ensure item_name stays as description, not item code
        if invoice_type == "purchase":
            # ERPNext may override item_name with Item.item_name during save
            # Force it to use the mutation description instead
            line_item["item_name"] = description

        # Set appropriate account
        if invoice_type == "sales":
            line_item["income_account"] = gl_account
        else:
            line_item["expense_account"] = gl_account

        # Cost center if available
        if regel.get("KostenplaatsId"):
            line_item["cost_center"] = get_cost_center(regel.get("KostenplaatsId"))

        invoice.append("items", line_item)
        debug_info.append(
            f"Added line item: {regel.get('Omschrijving', 'Unknown')} - {line_item['qty']} x {line_item['rate']}"
        )

    return True


def add_tax_lines(invoice, regels, invoice_type, debug_info):
    """Add tax lines based on BTW codes with enhanced calculations"""
    if not regels:
        debug_info.append("No line items (Regels) for tax calculation")
        return

    # Group by BTW code and calculate taxable amounts
    btw_summary = {}
    total_net_amount = 0

    for regel in regels:
        # Handle both Dutch (SOAP) and English (REST) field names
        btw_code = (regel.get("vatCode") or regel.get("BTWCode", "")).upper()
        description = regel.get("description") or regel.get("Omschrijving", "Unknown")
        # Handle quantity properly - preserve negative values for credit notes
        raw_line_qty = regel.get("quantity") or regel.get("Aantal", 1)
        line_qty = flt(raw_line_qty) if isinstance(raw_line_qty, (int, float)) else flt(raw_line_qty)
        line_price = flt(regel.get("amount") or regel.get("Prijs", 0))

        # Handle quantities and prices for tax calculation with correction line item support
        line_qty = abs(line_qty)  # Quantities should always be positive

        # For prices: preserve negatives for correction entries (same logic as process_line_items)
        # Don't convert negative amounts to positive - they represent corrections/discounts
        if line_price < 0:
            debug_info.append(f"Tax calculation preserving negative amount {line_price} as correction")

        line_total = line_qty * line_price
        total_net_amount += line_total

        debug_info.append(
            f"Line item: {description} - {line_qty} x {line_price} = {line_total} (BTW: {btw_code})"
        )

        if btw_code and btw_code not in ["GEEN", "VRIJ", ""]:
            if btw_code not in btw_summary:
                btw_info = BTW_CODE_MAP.get(btw_code, {})
                if not btw_info:
                    debug_info.append(f"WARNING: Unknown BTW code: {btw_code}")
                    continue

                btw_summary[btw_code] = {
                    "taxable_amount": 0,
                    "rate": btw_info.get("rate", 0),
                    "description": btw_info.get("description", f"BTW {btw_code}"),
                    "account_name": btw_info.get("account_name"),
                    "type": btw_info.get("type"),
                }

            btw_summary[btw_code]["taxable_amount"] += line_total

    debug_info.append(f"Total net amount: {total_net_amount}")
    debug_info.append(f"BTW codes found: {list(btw_summary.keys())}")

    # Create tax lines
    total_tax_amount = 0

    for btw_code, data in btw_summary.items():
        if data["rate"] > 0 and data["taxable_amount"] > 0:
            tax_amount = round(data["taxable_amount"] * data["rate"] / 100, 2)
            total_tax_amount += tax_amount

            tax_account = get_tax_account(btw_code, invoice_type, invoice.company, debug_info)

            if tax_account:
                # Create proper tax line for ERPNext
                tax_line = {
                    "charge_type": "Actual",
                    "account_head": tax_account,
                    "tax_amount": tax_amount,
                    "description": f"{data['description']} ({data['rate']}%)",
                    "rate": 0,  # Using actual amount instead of percentage
                    "base_tax_amount": tax_amount,
                    "base_tax_amount_after_discount_amount": tax_amount,
                    "tax_amount_after_discount_amount": tax_amount,
                }

                # Add cost center if available
                if hasattr(invoice, "cost_center") and invoice.cost_center:
                    tax_line["cost_center"] = invoice.cost_center

                invoice.append("taxes", tax_line)
                debug_info.append(
                    f"Added tax line: {data['description']} - Taxable: €{data['taxable_amount']}, Tax: €{tax_amount}"
                )
            else:
                debug_info.append(f"WARNING: No tax account found for BTW code: {btw_code}")
        elif data["rate"] == 0:
            debug_info.append(f"Zero-rate tax code: {btw_code} - {data['description']}")

    debug_info.append(f"Total tax amount: €{total_tax_amount}")

    # Validate total amounts
    if total_tax_amount > 0:
        calculated_total = total_net_amount + total_tax_amount
        debug_info.append(f"Calculated total (net + tax): €{calculated_total}")

    return {"net_amount": total_net_amount, "tax_amount": total_tax_amount}


def get_or_create_item_from_description(
    description, unit="Nos", debug_info=None, btw_code=None, account_code=None, price=None
):
    """Smart item creation based on description with enhanced categorization"""
    if debug_info is None:
        debug_info = []

    # Check for existing item by description
    existing = frappe.db.get_value("Item", {"description": description}, "name")
    if existing:
        debug_info.append(f"Found existing item: {existing}")
        return existing

    # Generate item code
    item_code = generate_item_code(description)

    # Check if item code already exists
    if frappe.db.exists("Item", item_code):
        debug_info.append(f"Item code already exists: {item_code}")
        return item_code

    # Determine item group using enhanced logic
    item_group = determine_item_group(description, btw_code, account_code, price)
    debug_info.append(
        f"Determined item group: {item_group} (BTW: {btw_code}, Account: {account_code}, Price: {price})"
    )

    # Create new item
    item = frappe.new_doc("Item")
    item.item_code = item_code
    item.item_name = description[:140]  # Limit length
    item.description = description
    item.item_group = item_group

    # Smart UOM assignment
    mapped_uom = map_unit_of_measure(unit)
    if mapped_uom == "Nos" and unit in ["Nos", None, ""]:
        # If no specific unit given, suggest based on item group
        from .uom_manager import UOMManager

        suggested_uom = UOMManager.get_uom_for_category(item_group)
        item.stock_uom = suggested_uom
        debug_info.append(f"Suggested UOM based on category: {suggested_uom}")
    else:
        item.stock_uom = mapped_uom

    # Smart stock item determination based on group
    if item_group in ["Products", "Office Supplies"]:
        item.is_stock_item = 1
        item.maintain_stock = 1
        item.valuation_method = "FIFO"
        item.has_batch_no = 0
        item.has_serial_no = 0
        debug_info.append("Configured as stock item")
    else:
        item.is_stock_item = 0
        item.maintain_stock = 0

    item.is_sales_item = 1
    item.is_purchase_item = 1

    # Add Dutch description and metadata
    if hasattr(item, "custom_dutch_description"):
        item.custom_dutch_description = description

    # Add price categorization for future reference
    if price and hasattr(item, "custom_price_category"):
        if 0 < flt(price) <= PRICE_CATEGORY_RANGES["consumable"][1]:
            item.custom_price_category = "Consumable"
        elif flt(price) <= PRICE_CATEGORY_RANGES["equipment"][1]:
            item.custom_price_category = "Equipment"
        else:
            item.custom_price_category = "Investment"

    # Additional metadata
    item.eboekhouden_import = 1

    item.insert()
    debug_info.append(f"Created new item: {item.item_code} in group {item.item_group}")
    return item.name


def generate_item_code(description):
    """Generate a clean item code from description"""
    # Take first 30 characters, clean up
    clean_desc = "".join(c for c in description if c.isalnum() or c in " -_").strip()
    clean_desc = clean_desc.replace(" ", "-").upper()[:30]

    # Use description alone without E-Boekhouden prefix
    return clean_desc


def determine_item_group(description, btw_code=None, account_code=None, price=None):
    """Enhanced item group determination using multiple signals"""
    from .field_mapping import ACCOUNT_CODE_ITEM_HINTS, PRICE_CATEGORY_RANGES, VAT_CATEGORY_HINTS

    description_lower = description.lower()

    # Priority 1: Check description keywords (most specific)
    for group, keywords in ITEM_GROUP_KEYWORDS.items():
        if any(keyword in description_lower for keyword in keywords):
            return DEFAULT_ITEM_GROUPS.get(group, "Services")

    # Priority 2: Use VAT code hints if available
    if btw_code and btw_code in VAT_CATEGORY_HINTS:
        group = VAT_CATEGORY_HINTS[btw_code]
        return DEFAULT_ITEM_GROUPS.get(group, "Services")

    # Priority 3: Use account code hints if available
    if account_code:
        try:
            account_num = int(str(account_code).split("-")[0].strip())
            for (start, end), group in ACCOUNT_CODE_ITEM_HINTS.items():
                if start <= account_num <= end:
                    return DEFAULT_ITEM_GROUPS.get(group, "Services")
        except (ValueError, IndexError):
            pass

    # Priority 4: Use price range hints
    if price:
        price_float = flt(price)
        if 0 < price_float <= PRICE_CATEGORY_RANGES["consumable"][1]:
            return "Office Supplies"
        elif price_float > PRICE_CATEGORY_RANGES["equipment"][0]:
            return "Products"

    # Default fallback
    return DEFAULT_ITEM_GROUPS.get("default", "Services")


def map_unit_of_measure(unit):
    """Map Dutch units to ERPNext UOMs using enhanced UOM manager"""
    from .uom_manager import map_unit_of_measure as uom_map

    return uom_map(unit)


def auto_create_ledger_mapping(ledger_id, transaction_type, company, debug_info):
    """
    Auto-create missing ledger mapping by fetching from eBoekhouden API
    and creating both ERPNext Account and Ledger Mapping if needed.

    Args:
        ledger_id: eBoekhouden ledger ID
        transaction_type: 'sales' or 'purchase'
        company: Company name
        debug_info: List to append debug messages

    Returns:
        str: ERPNext account name if successful, None otherwise
    """
    try:
        import requests

        from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import EBoekhoudenRESTClient

        debug_info.append(f"Attempting to fetch ledger {ledger_id} from eBoekhouden API")

        # Get eBoekhouden settings
        settings = frappe.get_single("E-Boekhouden Settings")
        if not settings.api_token:
            debug_info.append("E-Boekhouden API not configured")
            return None

        client = EBoekhoudenRESTClient(settings)

        # Fetch ledger details from API
        try:
            # Get session token
            session_token = client._get_session_token()
            if not session_token:
                debug_info.append("Failed to get session token")
                return None

            headers = {"Authorization": session_token, "Accept": "application/json"}
            ledger_url = f"{client.base_url}/v1/ledger/{ledger_id}"

            response = requests.get(ledger_url, headers=headers, timeout=30)

            if response.status_code != 200:
                debug_info.append(f"API error fetching ledger {ledger_id}: HTTP {response.status_code}")
                return None

            ledger_data = response.json()
            ledger_code = ledger_data.get("code") or ledger_data.get("Code")
            ledger_name = (
                ledger_data.get("description")
                or ledger_data.get("Description")
                or ledger_data.get("Omschrijving")
                or f"Ledger {ledger_code}"
            )
            ledger_category = (
                ledger_data.get("category") or ledger_data.get("Category") or ledger_data.get("Categorie")
            )

            if not ledger_code:
                debug_info.append(f"No ledger code found in API response for {ledger_id}")
                return None

            debug_info.append(
                f"Fetched ledger details: code={ledger_code}, name={ledger_name}, category={ledger_category}"
            )

        except Exception as e:
            debug_info.append(f"Error fetching ledger from API: {str(e)}")
            return None

        # Check if ERPNext Account already exists with this code
        # MODIFIED 2025-11-11: When multiple accounts exist with same grootboek_nummer,
        # prefer Expense Account type for cost-related accounts to avoid using Contra-Revenue variants
        # MODIFIED 2025-01-23: Also search by account_number and name pattern for accounts
        # created via Chart of Accounts import or manually (which don't have eboekhouden_grootboek_nummer)
        existing_accounts = frappe.db.get_all(
            "Account",
            filters={"company": company, "eboekhouden_grootboek_nummer": ledger_code},
            fields=["name", "account_type", "account_name"],
            order_by="creation",
        )

        # If not found by eboekhouden_grootboek_nummer, try account_number
        if not existing_accounts:
            existing_accounts = frappe.db.get_all(
                "Account",
                filters={"company": company, "account_number": ledger_code},
                fields=["name", "account_type", "account_name"],
                order_by="creation",
            )
            if existing_accounts:
                debug_info.append(
                    f"Found account by account_number instead of eboekhouden_grootboek_nummer: {ledger_code}"
                )

        # If still not found, try by name pattern (e.g., "4645 - % - NVV")
        if not existing_accounts:
            company_abbr = frappe.db.get_value("Company", company, "abbr")
            if company_abbr:
                name_pattern = f"{ledger_code} - % - {company_abbr}"
                existing_accounts = frappe.db.get_all(
                    "Account",
                    filters={"company": company, "name": ["like", name_pattern], "disabled": 0},
                    fields=["name", "account_type", "account_name"],
                    order_by="creation",
                )
                if existing_accounts:
                    debug_info.append(f"Found account by name pattern '{name_pattern}': {existing_accounts}")

        existing_account = None
        if existing_accounts:
            # If multiple accounts exist, prefer Expense Account for cost-related ledgers
            ledger_name_lower = (ledger_name or "").lower()
            is_cost_ledger = any(
                keyword in ledger_name_lower
                for keyword in ["bankkosten", "bank cost", "kosten", "cost", "expense"]
            )

            if is_cost_ledger and len(existing_accounts) > 1:
                # Prefer Expense Account type, NEVER use Contra-Revenue accounts
                for acc in existing_accounts:
                    # Skip any Contra-Revenue accounts
                    if "Contra-Revenue" in acc.account_name or "Contra-Revenue" in acc.name:
                        debug_info.append(f"Skipping Contra-Revenue account: {acc.name}")
                        continue
                    if acc.account_type == "Expense Account":
                        existing_account = acc
                        debug_info.append(
                            f"Multiple accounts found for {ledger_code}, selected Expense Account: {acc.name}"
                        )
                        break

            # REMOVED FALLBACK: Do not fall back to first account if it's Contra-Revenue
            if not existing_account and len(existing_accounts) == 1:
                # Only use single account if it's not Contra-Revenue
                acc = existing_accounts[0]
                if "Contra-Revenue" not in acc.account_name and "Contra-Revenue" not in acc.name:
                    existing_account = acc
                else:
                    debug_info.append(f"Only account found is Contra-Revenue, will not use it: {acc.name}")

        # REMOVED 2025-11-11: All contra-account logic stripped out

        if not existing_account:
            # Need to create ERPNext Account - determine account type from ledger code/category
            account_type, parent_account = _determine_account_type_for_transaction(
                ledger_code, ledger_name, ledger_category, transaction_type, company, debug_info
            )

            if not account_type or not parent_account:
                debug_info.append(f"Could not determine account type for ledger {ledger_code}")
                return None

            # Create ERPNext Account
            try:
                account_doc = frappe.new_doc("Account")
                account_doc.account_name = f"{ledger_code} - {ledger_name[:50]}"  # Limit name length
                account_doc.company = company
                account_doc.account_type = account_type
                account_doc.parent_account = parent_account
                account_doc.eboekhouden_grootboek_nummer = ledger_code
                # Security: Automated ledger mapping during eBoekhouden API sync - system context
                # Audit: All creations are logged in debug_info and E-Boekhouden Ledger Mapping records
                account_doc.insert(ignore_permissions=True)
                account_name = account_doc.name

                debug_info.append(f"Created ERPNext Account: {account_name} (type: {account_type})")

            except Exception as e:
                error_str = str(e)
                debug_info.append(f"Error creating ERPNext Account: {error_str}")

                # If duplicate key error, try to find the existing account by name
                if "Duplicate entry" in error_str or "IntegrityError" in error_str:
                    debug_info.append(
                        f"Account creation failed due to duplicate - searching for existing account by name"
                    )
                    company_abbr = frappe.db.get_value("Company", company, "abbr")
                    if company_abbr:
                        # Try exact name match first
                        expected_name = f"{ledger_code} - {ledger_name[:50]} - {company_abbr}"
                        existing_by_name = frappe.db.get_value(
                            "Account",
                            {"name": expected_name, "company": company},
                            ["name", "account_type"],
                            as_dict=True,
                        )
                        if existing_by_name:
                            account_name = existing_by_name.name
                            debug_info.append(f"Found existing account by exact name: {account_name}")
                            # Update eboekhouden_grootboek_nummer if not set
                            current_grootboek = frappe.db.get_value(
                                "Account", account_name, "eboekhouden_grootboek_nummer"
                            )
                            if not current_grootboek:
                                frappe.db.set_value(
                                    "Account", account_name, "eboekhouden_grootboek_nummer", ledger_code
                                )
                                debug_info.append(f"Updated eboekhouden_grootboek_nummer to {ledger_code}")
                        else:
                            # Try pattern match
                            pattern = f"{ledger_code} - % - {company_abbr}"
                            existing_by_pattern = frappe.db.get_value(
                                "Account",
                                {"name": ["like", pattern], "company": company},
                                ["name", "account_type"],
                                as_dict=True,
                            )
                            if existing_by_pattern:
                                account_name = existing_by_pattern.name
                                debug_info.append(f"Found existing account by pattern: {account_name}")
                                # Update eboekhouden_grootboek_nummer if not set
                                current_grootboek = frappe.db.get_value(
                                    "Account", account_name, "eboekhouden_grootboek_nummer"
                                )
                                if not current_grootboek:
                                    frappe.db.set_value(
                                        "Account", account_name, "eboekhouden_grootboek_nummer", ledger_code
                                    )
                                    debug_info.append(
                                        f"Updated eboekhouden_grootboek_nummer to {ledger_code}"
                                    )
                            else:
                                debug_info.append(
                                    f"Could not find existing account by name pattern: {pattern}"
                                )
                                frappe.log_error(
                                    title=f"Auto-Create Account Failed - {ledger_code}",
                                    message=f"Account creation failed for ledger {ledger_id} ({ledger_code}) and could not find existing account.\n\nError: {error_str}\n\n{frappe.get_traceback()}",
                                )
                                return None
                else:
                    frappe.log_error(
                        title=f"Auto-Create Account Failed - {ledger_code}",
                        message=f"Error creating account for ledger {ledger_id} ({ledger_code})\n\n{error_str}\n\n{frappe.get_traceback()}",
                    )
                    return None
        else:
            # Use existing account
            account_name = existing_account.name
            debug_info.append(
                f"Using existing account: {account_name} (type: {existing_account.account_type})"
            )

        # Create ledger mapping (if it doesn't already exist)
        try:
            # Check if mapping already exists using the document name (which is set to ledger_id)
            # Note: E-Boekhouden Ledger Mapping uses autoname: field:ledger_id, so name == ledger_id
            existing_mapping = frappe.db.exists("E-Boekhouden Ledger Mapping", str(ledger_id))

            if existing_mapping:
                debug_info.append(
                    f"Ledger mapping already exists: {ledger_id} ({ledger_code}) -> {account_name}"
                )
                return account_name

            # Create new mapping
            mapping = frappe.new_doc("E-Boekhouden Ledger Mapping")
            mapping.ledger_id = str(ledger_id)
            mapping.ledger_code = ledger_code
            mapping.ledger_name = ledger_name
            mapping.erpnext_account = account_name
            # Security: Automated ledger mapping during eBoekhouden API sync - system context
            # Audit: Ledger mapping records serve as audit trail for auto-created accounts
            mapping.insert(ignore_permissions=True)

            debug_info.append(f"Created ledger mapping: {ledger_id} ({ledger_code}) -> {account_name}")
            return account_name

        except Exception as e:
            error_msg = f"Error creating ledger mapping: {str(e)}"
            debug_info.append(error_msg)
            frappe.log_error(
                title=f"Auto-Create Ledger Mapping Failed - {ledger_id}",
                message=f"Error creating mapping for ledger {ledger_id} ({ledger_code}) -> {account_name}\n\n{error_msg}\n\n{frappe.get_traceback()}",
            )
            return None

    except Exception as e:
        debug_info.append(f"Unexpected error in auto_create_ledger_mapping: {str(e)}")
        return None


def _determine_account_type_for_transaction(
    ledger_code, ledger_name, ledger_category, transaction_type, company, debug_info
):
    """
    Determine appropriate ERPNext account type and parent account for a transaction.

    Args:
        ledger_code: eBoekhouden account code
        ledger_name: eBoekhouden account name
        ledger_category: eBoekhouden category (FIN, VER, OMS, KOS, etc.)
        transaction_type: 'sales' or 'purchase'
        company: Company name
        debug_info: Debug info list

    Returns:
        tuple: (account_type, parent_account) or (None, None) if cannot determine
    """
    # DISABLED 2025-11-11: Bank cost contra-account logic causing issues with regular bank costs
    # # Check if this is a cost account (bank fees, transaction costs, etc.) being used in a sales invoice
    # # These should be treated as "contra-revenue" (deductions from income) not expenses
    # ledger_name_lower = (ledger_name or "").lower()
    # is_cost_account = any(
    #     keyword in ledger_name_lower
    #     for keyword in ["bankkosten", "bank cost", "transactiekosten", "payment fee", "processing fee"]
    # )

    # Priority 1: Use transaction type as primary signal
    if transaction_type == "sales":
        # Sales invoices need income accounts (including contra-revenue accounts like bank fees)
        account_type = "Income Account"

        # DISABLED 2025-11-11: Bank cost contra-account logic causing issues with regular bank costs
        # # For cost accounts in sales invoices, use "Kortingen en Kostenposten" or similar parent
        # if is_cost_account:
        #     # Try to find a "Kortingen" (Discounts) or similar parent account
        #     parent_account = frappe.db.get_value(
        #         "Account",
        #         {
        #             "company": company,
        #             "account_type": "Income Account",
        #             "is_group": 1,
        #             "account_name": ["like", "%Korting%"],
        #         },
        #         "name",
        #     )
        #     if not parent_account:
        #         # Fallback to main Income group (Opbrengsten or Omzet)
        #         for keyword in ["%Opbrengsten%", "%Omzet%", "%Revenue%", "%Income%"]:
        #             parent_account = frappe.db.get_value(
        #                 "Account",
        #                 {"company": company, "is_group": 1, "account_name": ["like", keyword]},
        #                 "name",
        #             )
        #             if parent_account:
        #                 break
        #     debug_info.append(
        #         f"Sales transaction with cost item: using Income Account (contra-revenue) under {parent_account}"
        #     )
        # else:
        # Regular income account - search for common Dutch/English names
        for keyword in ["%Opbrengsten%", "%Omzet%", "%Revenue%", "%Income%"]:
            parent_account = frappe.db.get_value(
                "Account",
                {"company": company, "is_group": 1, "account_name": ["like", keyword]},
                "name",
            )
            if parent_account:
                break
        debug_info.append(f"Sales transaction: using Income Account under {parent_account}")

        if not parent_account:
            # Last resort fallback
            parent_account = frappe.db.get_value(
                "Account",
                {
                    "company": company,
                    "is_group": 1,
                    "account_name": ["like", "%8%"],  # Dutch chart usually starts with 8
                },
                "name",
            )
            debug_info.append(f"Fallback: using income group: {parent_account}")

    else:  # purchase
        # Purchase invoices need expense accounts
        account_type = "Expense Account"
        # Find appropriate parent - look for "Kosten" or "Expense" account
        parent_account = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "account_type": "Expense Account",
                "is_group": 1,
                "account_name": ["like", "%Kosten%"],
            },
            "name",
        )
        if not parent_account:
            # Fallback to any Expense Account group
            parent_account = frappe.db.get_value(
                "Account",
                {
                    "company": company,
                    "account_type": "Expense Account",
                    "is_group": 1,
                },
                "name",
            )
        debug_info.append(f"Purchase transaction: using Expense Account under {parent_account}")

    if not parent_account:
        debug_info.append(f"ERROR: No parent account found for {account_type}")
        return None, None

    return account_type, parent_account


def map_grootboek_to_erpnext_account(
    grootboek_nummer, transaction_type, company, debug_info=None, allow_fallback=False
):
    """
    Map eBoekhouden GL account to ERPNext account using modern mapping system

    Args:
        grootboek_nummer: E-Boekhouden account number
        transaction_type: 'sales' or 'purchase'
        company: Company name for account lookup
        debug_info: List to append debug messages to
        allow_fallback: If False, raises error instead of using fallback accounts
    """
    if debug_info is None:
        debug_info = []

    if not grootboek_nummer:
        if not allow_fallback:
            error_msg = f"Missing grootboek_nummer for {transaction_type} transaction. Proper account mapping required."
            debug_info.append(f"ERROR: {error_msg}")
            frappe.throw(error_msg, title="Account Mapping Required")
        return get_default_account(transaction_type)

    # Check if ERPNext account already exists with this grootboek code
    company_abbr = frappe.db.get_value("Company", company, "abbr")

    # Try direct account lookup first (accounts created by Chart of Accounts import)
    potential_account_names = [
        f"{grootboek_nummer} - {company_abbr}",  # Standard format
        f"{grootboek_nummer} - % - {company_abbr}",  # With description wildcard
    ]

    for pattern in potential_account_names:
        account = frappe.db.get_value(
            "Account", {"name": ["like", pattern], "company": company, "disabled": 0}, "name"
        )
        if account:
            debug_info.append(f"Found direct account match: {grootboek_nummer} -> {account}")
            return account

    # Use E-Boekhouden Ledger Mapping system (the actual table with data)
    try:
        # Look up the account mapping in the correct table
        mapping = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping",
            {"ledger_id": str(grootboek_nummer)},
            ["erpnext_account", "ledger_code", "ledger_name"],
            as_dict=True,
        )

        if mapping and mapping.get("erpnext_account"):
            debug_info.append(
                f"Found ledger mapping: {grootboek_nummer} ({mapping.get('ledger_name')}) -> {mapping['erpnext_account']}"
            )
            return mapping["erpnext_account"]

        # No mapping found in ledger mapping table - try to auto-create
        debug_info.append(f"No ledger mapping found for {grootboek_nummer}, attempting auto-creation")
        auto_created_account = auto_create_ledger_mapping(
            grootboek_nummer, transaction_type, company, debug_info
        )
        if auto_created_account:
            return auto_created_account

        # Auto-creation failed
        debug_info.append(f"Auto-creation failed for ledger {grootboek_nummer}")
        return None

    except Exception as e:
        debug_info.append(f"Ledger mapping lookup error: {str(e)}")
        return None

    # No mapping found - use fallback account only if allowed
    if not allow_fallback:
        error_msg = f"No account mapping found for E-Boekhouden account {grootboek_nummer}. Configure proper account mapping in E-Boekhouden Account Map."
        debug_info.append(f"ERROR: {error_msg}")
        frappe.throw(error_msg, title="Account Mapping Required")

    debug_info.append(
        f"WARNING: No account mapping found for E-Boekhouden account {grootboek_nummer}, using fallback"
    )
    fallback_account = get_default_account(transaction_type)
    debug_info.append(f"Using fallback account: {fallback_account}")
    return fallback_account


def get_default_account(transaction_type):
    """
    CRITICAL: This function should NEVER be used in production.
    Account mapping must be properly configured for all E-Boekhouden GL codes.

    This function now REJECTS imports instead of creating fake accounts.
    """
    # Get the company for error reporting (currently unused but kept for future error handling)
    # company = (
    #     frappe.defaults.get_user_default("Company")
    #     or frappe.db.get_single_value("Global Defaults", "default_company")
    #     or frappe.db.get_value("Company", {}, "name")
    # )

    # Log critical error and reject the import
    error_msg = (
        f"ACCOUNT MAPPING REQUIRED: No account mapping found for {transaction_type} transaction. "
        f"Configure proper account mapping in E-Boekhouden Account Map before importing. "
        f"Automatic fallback account creation has been disabled to prevent data corruption."
    )

    frappe.logger().error(f"DATA INTEGRITY PROTECTION: {error_msg}")

    # Throw error to stop the import - no more fake accounts
    frappe.throw(error_msg, title="Account Mapping Required", exc=frappe.ValidationError)


def get_tax_account(btw_code, invoice_type, company, debug_info=None):
    """Get appropriate tax account for BTW code using existing accounts"""
    if debug_info is None:
        debug_info = []

    btw_info = BTW_CODE_MAP.get(btw_code, {})
    if not btw_info or not btw_info.get("account_name"):
        debug_info.append(f"No tax account mapping for BTW code: {btw_code}")
        return None

    # Try primary account mapping
    account_name = btw_info.get("account_name")
    if account_name and frappe.db.exists("Account", account_name):
        debug_info.append(f"Using primary tax account: {account_name}")
        return account_name

    # Try fallback account
    fallback_account = btw_info.get("account_fallback")
    if fallback_account and frappe.db.exists("Account", fallback_account):
        debug_info.append(f"Using fallback tax account: {fallback_account}")
        return fallback_account

    # Final fallback based on invoice type
    if invoice_type == "sales":
        final_fallback = "1500 - BTW af te dragen 21% - NVV"
    else:
        final_fallback = "1530 - BTW te vorderen - NVV"

    if frappe.db.exists("Account", final_fallback):
        debug_info.append(f"Using final fallback tax account: {final_fallback}")
        return final_fallback

    debug_info.append(f"No suitable tax account found for BTW code: {btw_code}")
    return None


def get_cost_center(cost_center_id, company=None):
    """Get cost center by ID with proper company context"""
    if not company:
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

    if not company:
        frappe.throw("No company configured for cost center lookup", title="Company Required")

    # Try to get company's default cost center
    default_cost_center = frappe.db.get_value("Company", company, "cost_center")
    if default_cost_center:
        return default_cost_center

    # Try to find "Main" cost center for this company
    main_cost_center = frappe.db.get_value(
        "Cost Center", {"company": company, "cost_center_name": "Main", "is_group": 0}, "name"
    )
    if main_cost_center:
        return main_cost_center

    # Get any cost center for this company
    any_cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")
    if any_cost_center:
        return any_cost_center

    frappe.throw(
        f"No cost center found for company {company}. Please create a cost center first.",
        title="Cost Center Required",
    )


def fetch_relation_details(relation_id):
    """Fetch relation details from e-boekhouden API"""
    # This would require API call to get relation details
    # For now, return None to use provisional creation
    return None


def create_customer_from_relation(relation_details, debug_info):
    """
    Create customer with proper details from relation data.

    Uses centralized BankTransactionParser for party creation to ensure
    consistent matching and creation logic across the codebase.
    """
    from verenigingen.e_boekhouden.utils.bank_transaction_parser import BankTransactionParser

    parser = BankTransactionParser()

    # Use actual name if available
    customer_name = relation_details.get("name", f"E-Boekhouden {relation_details['id']}")

    party_name, created = parser.find_or_create_party(
        party_name=customer_name,
        party_type="Customer",
        iban=None,
    )

    if created:
        # Set additional fields from relation data
        try:
            updates = {"eboekhouden_relation_code": str(relation_details["id"])}
            if relation_details.get("email"):
                updates["email_id"] = relation_details["email"]
            frappe.db.set_value("Customer", party_name, updates)
        except Exception:
            pass  # Fields might not exist

        debug_info.append(f"Created customer from relation data: {party_name}")
    else:
        debug_info.append(f"Found existing customer: {party_name}")

    return party_name


def create_single_line_fallback(invoice, mutation_detail, cost_center, debug_info):
    """Create a single line item fallback when no detailed line items are available"""
    mutation_id = mutation_detail.get("id")
    description = mutation_detail.get("description", f"eBoekhouden Import {mutation_id}")
    amount = flt(mutation_detail.get("amount", 0))
    ledger_id = mutation_detail.get("ledgerId")

    # For credit notes, use absolute amount (mutation_detail should already be converted)
    amount = abs(amount)

    debug_info.append(f"Creating single line fallback item with amount: {amount}")

    # Determine if this is sales or purchase based on document type
    transaction_type = "sales" if invoice.doctype == "Sales Invoice" else "purchase"

    # Use consolidated modules for line creation
    from verenigingen.e_boekhouden.utils.consolidated.invoice_line_utils import (
        create_invoice_line_for_tegenrekening,
    )
    from verenigingen.e_boekhouden.utils.consolidated.ledger_utils import get_ledger_code_from_id

    # Convert ledger_id to ledger_code for proper account mapping
    ledger_code = get_ledger_code_from_id(ledger_id, debug_info)

    line_dict = create_invoice_line_for_tegenrekening(
        tegenrekening_code=ledger_code,
        amount=abs(amount),
        description=description,
        transaction_type=transaction_type,
    )

    # Get or create item using intelligent creation
    from verenigingen.e_boekhouden.utils.eboekhouden_improved_item_naming import get_or_create_item_improved

    # Get the actual account code from the Account record instead of parsing names
    account_code = ""
    account_name = line_dict.get("income_account" if transaction_type == "sales" else "expense_account", "")

    if account_name:
        # Query the actual account record to get the proper account code
        account_code = frappe.db.get_value(
            "Account", account_name, ["eboekhouden_grootboek_nummer", "account_number"], as_dict=True
        )
        if account_code:
            # Prefer eboekhouden_grootboek_nummer, fallback to account_number
            account_code = (
                account_code.get("eboekhouden_grootboek_nummer") or account_code.get("account_number") or ""
            )

    item_code = get_or_create_item_improved(
        account_code=account_code,
        company=invoice.company,
        transaction_type="Sales" if transaction_type == "sales" else "Purchase",
        description=line_dict["description"],
    )

    # For standardized items (Event-Ticket, Bank-Costs), use clean item details instead of ugly transaction description
    if item_code in ["Event-Ticket", "Bank-Costs"]:
        # Get clean details from the actual Item master
        item_doc = frappe.get_doc("Item", item_code)
        clean_item_name = item_doc.item_name
        clean_description = item_doc.description
        debug_info.append(
            f"Fallback: Using clean {item_code} item details: name='{clean_item_name}', description='{clean_description}'"
        )
    else:
        # Use original transaction description for other items
        clean_item_name = line_dict["description"]
        clean_description = line_dict["description"]

    line_item = {
        "item_code": item_code,
        "item_name": clean_item_name,
        "description": clean_description,
        "qty": line_dict["qty"],
        "rate": line_dict["rate"],
        "amount": line_dict["amount"],
        "cost_center": cost_center,
    }

    # For Purchase Invoices, ensure item_name stays as description
    if transaction_type == "purchase":
        line_item["item_name"] = line_dict["description"]

    # Set appropriate account
    if transaction_type == "sales":
        line_item["income_account"] = line_dict["income_account"]
    else:
        line_item["expense_account"] = line_dict["expense_account"]

    invoice.append("items", line_item)
    debug_info.append(f"Added fallback line item: {line_dict['description']} - {line_dict['amount']}")
