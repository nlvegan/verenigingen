# Copyright (c) 2025, R.S.P. and contributors
# For license information, please see license.txt

"""
Account Hierarchy Service

Provides functionality for reorganizing ERPNext account hierarchy based on
eBoekhouden group type mappings. Handles both account type classification
and taxonomical grouping (parent-child relationships).
"""

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, critical_api


def derive_group_code(account_number):
    """Derive the group code from an account number.

    NOTE: This function is DEPRECATED for e-Boekhouden group matching.
    E-Boekhouden uses semantic group codes (001-055) that don't correspond
    to account number prefixes. Use match_account_to_group() instead.

    Args:
        account_number: The account number string

    Returns:
        str: The 3-digit group code, or None if cannot be derived
    """
    if not account_number:
        return None

    account_number = str(account_number).strip()
    numeric_only = "".join(c for c in account_number if c.isdigit())

    if not numeric_only:
        return None

    if len(numeric_only) < 3:
        return numeric_only.zfill(3)

    return numeric_only[:3]


# Keyword mappings for e-Boekhouden groups
# Maps group names to keywords that identify accounts belonging to that group
# Keywords are matched against account names (case-insensitive)
# Longer keywords are preferred over shorter ones to avoid false matches
#
# IMPORTANT: Some account names contain ambiguous terms (e.g., "inventaris" appears
# in both Asset accounts AND Expense accounts like "Afschrijving Inventaris").
# We handle this by:
# 1. Using more specific keywords where possible
# 2. Using EXCLUDE_PATTERNS to skip certain matches
# 3. Preferring longer (more specific) keyword matches

GROUP_KEYWORDS = {
    # Balance sheet groups - Assets
    # NOTE: Be careful with these - "inventaris", "apparatuur" also appear in expense account names
    "Materiële vaste activa": [
        "cum. afschrijving",  # Contra-assets - most specific, check first
        "kantoorinventaris",
    ],
    "Liquide middelen": [
        "bank",
        " kas ",
        "kasgeld",
        "giro",
        "spaar",
        "rekening courant",
        "deposito",
        "paypal",
        "mollie",
        "ideal",
        "ing bank",
        "abn amro",
        "rabobank",
        "triodos",
        "asn bank",
        "betaalrekening",
        "spaarrekening",
    ],
    "Voorraden": ["voorraad", "magazijn", "handelsgoederen"],
    "Vorderingen": [
        "debiteuren",
        "vordering",
        "te ontvangen",
        "vooruitbetaalde",
        "nog te factureren",
    ],
    # Balance sheet groups - Equity & Liabilities
    "Eigen Vermogen": [
        "eigen vermogen",
        "algemene reserve",
        "bestemmingsreserve",
        "kapitaal",
        "resultaat voorgaand",
        "beginvermogen",
        "stichtingskapitaal",
    ],
    "Schulden": [
        "crediteuren",
        "schuld aan",
        "te betalen kosten",
        "vooruit ontvangen",
        "btw af te dragen",
        "btw te betalen",
        "loonheffing te betalen",
        "belasting te betalen",
        "nog te betalen",
    ],
    # P&L expense groups
    "Personeelskosten": [
        "lonen en salaris",
        "salaris",
        "personeel",
        "medewerk",
        "sociale lasten",
        "vakantiegeld",
        "pensioen",
        "vacatiegeld",
        "reiskosten medewerk",
        "opleidingskosten",
        "werving",
    ],
    "Promotiekosten": [
        "promotie",
        "marketing",
        "reclame",
        "advertentie",
        "campagne",
        "pr-kosten",
        "communicatiekosten",
        "huisstijl",
        "branding",
    ],
    "Algemene kosten": [
        "algemene kosten",
        "bankkosten",
        "onvoorziene kosten",
        "huur locatie",
        "netwerk",
        "conferentie",
    ],
    "Verzekeringen": ["verzekering", "wa-verzekering", "aansprakelijkheid"],
    "Kantoorkosten": [
        "kantoor:",
        "telefoon",
        "porto",
        "drukwerk",
        "kantoormateriaal",
        "kantoorbenodigdheden",
        "postbus",
        "opslagbox",
    ],
    "Ledenadministratie": [
        "ledenservice",
        "lidmaatschap",
        "ledenadmin",
        "ledenbinding",
        "ledenwerving",
    ],
    "Programma's": ["programma "],  # Space after to avoid partial matches
    "Evenementen": [
        "evenement",
        "festival",
        "beurs",
        "congres",
        "alv ",
        "bijeenkomst",
        "potluck",
    ],
    "Afschrijvingen": [
        "afschrijving ",  # Space after - matches "Afschrijving Inventaris" etc.
        "afschrijvingskosten",
        "amortisatie",
        "waardevermindering",
    ],
    "Administratiekosten": [
        "administratiekosten",
        "boekhouding",
        "accountant",
        "audit",
        "jaarrekening",
        "salarisadministratie",
        "notaris",
        "juridisch",
    ],
    "ICT-Kosten": [
        "ict-",
        "ict ",
        "software",
        "hosting",
        "domein",
        "website",
        "webserver",
        "licentie",
        "cloud",
        "saas",
        "hardware",
    ],
    "Bestuur": [
        "bestuurskosten",
        "directiekosten",
        "raad van toezicht",
        "vergaderkosten bestuur",
        "presentjes - bestuur",
    ],
    "Overige kosten": ["overige bedrijfskosten"],
    # P&L income groups
    # NOTE: These keywords should be specific to income accounts
    # Many expense keywords appear in income account names with ": inkomsten" suffix
    "Opbrengsten": [
        "opbrengst",
        "omzet",
        "inkomsten",
        "verkoop",
        "donaties:",
        "subsidie",
        "sponsoring",
        "legaat",
        "erfenis",
        "contributie leden",  # Income from member contributions
        "advertenties in",  # Revenue from ads in magazine
        "advertenties v",  # Revenue from ads in vegan cookbook/festival
        "donaties",  # Receiving donations (not expense)
        "giften",  # Receiving gifts
        ": inkomsten",  # Pattern like "Promotie: inkomsten"
        "bijdrage",  # Contributions/income
    ],
}

# Patterns that should EXCLUDE an account from matching certain groups
# Format: {group_name: [patterns that disqualify an account from this group]}
#
# CRITICAL: Many Dutch keywords appear in both income and expense contexts:
# - "contributie" can be expense (paying) or income (receiving)
# - "advertentie" can be expense (paying for ads) or income (selling ad space)
# - "promotie" can be expense (costs) or income (revenue)
# - "donatie" can be expense (giving) or income (receiving)
#
# We use income-signaling patterns to exclude accounts from expense groups
INCOME_SIGNALS = [
    "inkomsten",
    "opbrengsten",
    "ontvangen",
    "omzet",
    "verkoop",
    "donaties",
    "giften",
    "subsidie",
    "sponsoring",
    "bijdrage",
]

EXCLUDE_PATTERNS = {
    # Don't match expense accounts to Asset groups
    "Materiële vaste activa": ["afschrijving ", "kosten", "huur"],
    "Liquide middelen": ["kosten", "vergoeding"],
    "Voorraden": ["afschrijving", "kosten"],
    # Don't match liability reserves to Expense
    "Personeelskosten": ["reservering", "te betalen"],
    "Schulden": ["kosten", "lasten"],
    # Don't match expense items to Income
    "Opbrengsten": ["kosten", "uitgaven"],
    # Don't match income accounts to Expense groups (income signals)
    "Promotiekosten": INCOME_SIGNALS,
    "Ledenadministratie": INCOME_SIGNALS,
    "Algemene kosten": INCOME_SIGNALS,
    "Evenementen": INCOME_SIGNALS,
    "Programma's": INCOME_SIGNALS,
    # Don't match contra-asset accounts to Expense
    # "Cum. Afschrijving X" = accumulated depreciation (contra-asset, stays in Asset)
    # "Afschrijving X" = depreciation expense (Expense)
    "Afschrijvingen": ["cum."],
}


def _get_keywords_for_group(group_name):
    """Get keywords for a group, with fallback to group name words.

    If explicit keywords are defined in GROUP_KEYWORDS, use those.
    Otherwise, extract meaningful words from the group name itself.

    This makes the system more generalizable - groups like "Programma Educatie"
    will match accounts containing "educatie" even without explicit configuration.

    Args:
        group_name: The group name to get keywords for

    Returns:
        list: Keywords to match against account names
    """
    # Check for explicit keywords first
    if group_name in GROUP_KEYWORDS:
        return GROUP_KEYWORDS[group_name]

    # Fallback: extract words from group name (excluding common filler words)
    # These words are too generic or appear in many account names unrelated to the group
    FILLER_WORDS = {
        "programma",
        "programma's",
        "kosten",
        "overige",
        "algemene",
        "en",
        "van",
        "de",
        "het",
        "een",
        "voor",
        "met",
        "naar",
        "je",
        "kan",
        "kun",
        "zonder",
        "niet",  # Common Dutch words
        "interne",
        "externe",  # Too generic
        "vegan",  # Useless for a vegan org - everything is vegan
    }

    words = group_name.lower().split()
    keywords = []
    for word in words:
        # Skip short words (< 4 chars) and filler words for derived keywords
        # Use stricter length requirement than explicit keywords
        if len(word) >= 4 and word not in FILLER_WORDS:
            keywords.append(word)

    # Also try the full name (minus "Programma " prefix if present)
    # But only if it's reasonably specific (> 4 chars)
    if group_name.lower().startswith("programma "):
        suffix = group_name[10:].strip()  # Everything after "Programma "
        if suffix and len(suffix) >= 5:
            keywords.append(suffix.lower())

    return keywords


def match_account_to_group(account_name, group_mappings):
    """Match an account to a group based on account name keywords.

    E-Boekhouden uses semantic group classifications (Personeelskosten,
    Promotiekosten, etc.) that are matched by keywords in account names,
    NOT by account number prefixes.

    The matching algorithm:
    1. Checks each group's keywords against the account name
    2. Falls back to using words from group_name if no explicit keywords
    3. Applies EXCLUDE_PATTERNS to filter out false positives
    4. Applies INCOME_SIGNALS to exclude income accounts from Expense groups
    5. Prefers longer (more specific) keyword matches

    Args:
        account_name: The account name to match
        group_mappings: Dict of {group_code: {"group_name": str, "root_type": str, ...}}

    Returns:
        tuple: (group_code, group_name, match_reason) or (None, None, None) if no match
    """
    if not account_name:
        return None, None, None

    account_name_lower = account_name.lower()

    # Check if this account has income signals (should not match Expense groups)
    has_income_signal = any(sig.lower() in account_name_lower for sig in INCOME_SIGNALS)

    # Collect all potential matches with scores
    matches = []

    for group_code, mapping in group_mappings.items():
        group_name = mapping.get("group_name", "")
        root_type = mapping.get("root_type", "")
        if not group_name:
            continue

        # Apply INCOME_SIGNALS exclusion to ALL Expense groups
        # This prevents income accounts from being matched to expense groups
        if has_income_signal and root_type == "Expense":
            continue

        # Check if this account should be excluded from this group (explicit patterns)
        exclude_patterns = EXCLUDE_PATTERNS.get(group_name, [])
        is_excluded = any(excl.lower() in account_name_lower for excl in exclude_patterns)
        if is_excluded:
            continue

        # Get keywords for this group (explicit or derived from name)
        keywords = _get_keywords_for_group(group_name)

        # Check for keyword matches
        for keyword in keywords:
            if keyword.lower() in account_name_lower:
                # Score by keyword length (longer = more specific = better)
                score = len(keyword)
                # Bonus score for explicit keywords (from GROUP_KEYWORDS)
                if group_name in GROUP_KEYWORDS:
                    score += 5
                matches.append((score, group_code, group_name, keyword))

    if not matches:
        return None, None, None

    # Return the best match (highest score)
    matches.sort(reverse=True, key=lambda x: x[0])
    best = matches[0]
    return (best[1], best[2], f"Matched keyword '{best[3]}'")


def get_group_type_mappings_dict(settings=None):
    """Get group type mappings as a dict from settings.

    Args:
        settings: E-Boekhouden Settings doc. If None, will fetch from database.

    Returns:
        dict: {group_code: {"group_name": str, "root_type": str, "account_type": str}}
    """
    if settings is None:
        settings = frappe.get_single("E-Boekhouden Settings")

    mappings = {}
    for row in settings.get("group_type_mappings", []):
        if row.group_code and row.group_name and row.root_type:
            mappings[row.group_code] = {
                "group_name": row.group_name,
                "root_type": row.root_type,
                "account_type": row.account_type or "",
            }
    return mappings


def find_or_create_group_account(
    group_code, group_name, root_type, company, dry_run=False, created_groups=None, groups_created=None
):
    """Find or create a group account for the given group code.

    Args:
        group_code: The group code (e.g., "001")
        group_name: The group name (e.g., "Vaste activa")
        root_type: The root type (Asset, Liability, etc.)
        company: The company name
        dry_run: If True, don't actually create
        created_groups: Dict to track already created groups (cache)
        groups_created: List to append created group info

    Returns:
        The account name of the group account, or None if not found/created.
    """
    if created_groups is None:
        created_groups = {}
    if groups_created is None:
        groups_created = []

    # Check cache first
    cache_key = f"{group_code}_{root_type}"
    if cache_key in created_groups:
        return created_groups[cache_key]

    # Check if group account already exists
    existing_group = frappe.db.get_value(
        "Account",
        {"account_name": group_name, "company": company, "is_group": 1, "root_type": root_type},
        "name",
    )

    if existing_group:
        created_groups[cache_key] = existing_group
        return existing_group

    # Find the root account to be parent
    # Use SQL query because ORM doesn't handle NULL parent_account well
    root_parent = frappe.db.sql(
        """
        SELECT name FROM `tabAccount`
        WHERE company = %s AND root_type = %s AND is_group = 1
        AND (parent_account IS NULL OR parent_account = '')
        LIMIT 1
        """,
        (company, root_type),
        as_dict=False,
    )
    root_parent = root_parent[0][0] if root_parent else None

    if not root_parent:
        return None

    if dry_run:
        # In dry run, return a placeholder name
        placeholder_name = f"{group_name} - {company}"
        created_groups[cache_key] = placeholder_name
        groups_created.append(
            {
                "group_code": group_code,
                "group_name": group_name,
                "root_type": root_type,
                "parent": root_parent,
                "status": "would_create",
            }
        )
        return placeholder_name

    # Actually create the group account
    try:
        group_account = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": group_name,
                "company": company,
                "root_type": root_type,
                "is_group": 1,
                "parent_account": root_parent,
                "disabled": 0,
            }
        )
        # Security: Account hierarchy setup - protected by @critical_api at entry points
        group_account.insert(ignore_permissions=True)

        created_groups[cache_key] = group_account.name
        groups_created.append(
            {
                "group_code": group_code,
                "group_name": group_name,
                "root_type": root_type,
                "parent": root_parent,
                "account_id": group_account.name,
                "status": "created",
            }
        )

        return group_account.name

    except Exception as e:
        frappe.logger().error(f"Error creating group account {group_code}: {e}")
        return None


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def reorganize_account_hierarchy(dry_run=True):
    """Reorganize existing accounts into proper group hierarchy based on group_type_mappings.

    For each account:
    1. Matches account name to a group using keyword matching
    2. Looks up the group mapping to get group_name and root_type
    3. Finds or creates the group parent account
    4. Moves the account under the correct parent if needed

    Args:
        dry_run: If True, returns preview of changes without applying them.
                 If False, actually updates the account hierarchy.

    Returns:
        dict: {
            "success": True/False,
            "dry_run": bool,
            "total_accounts": int,
            "would_move" or "moved": int,
            "groups_created": int,
            "skipped": int,
            "changes": [...],
            "groups": [...]
        }
    """
    try:
        # Convert string "true"/"false" to boolean (from JS)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() != "false"

        settings = frappe.get_single("E-Boekhouden Settings")

        if not settings.default_company:
            return {"success": False, "error": "Default company not configured in E-Boekhouden Settings"}

        company = settings.default_company

        # Get the group type mappings (need root_type for hierarchy)
        group_type_mappings = get_group_type_mappings_dict(settings)

        if not group_type_mappings:
            return {
                "success": False,
                "error": "No group type mappings configured. Please configure mappings first using 'Parse & Suggest Types'.",
            }

        # Get all non-group accounts (with or without account numbers)
        accounts = frappe.get_all(
            "Account",
            filters={
                "company": company,
                "is_group": 0,
            },
            fields=["name", "account_name", "account_number", "parent_account", "root_type"],
        )

        changes = []
        groups_created = []
        moved_count = 0
        skipped_count = 0

        # Track created groups to avoid duplicates
        created_groups = {}

        for account in accounts:
            # Use keyword matching to find the appropriate group
            group_code, group_name, match_reason = match_account_to_group(
                account.account_name, group_type_mappings
            )

            if not group_code:
                skipped_count += 1
                changes.append(
                    {
                        "account": account.account_number or account.name,
                        "account_name": account.account_name,
                        "group_code": None,
                        "status": "skipped",
                        "reason": "No matching group found for account name",
                    }
                )
                continue

            mapping = group_type_mappings[group_code]
            group_root_type = mapping["root_type"]

            # Skip if the matched group would change the account's root_type
            # Hierarchy reorganization should only organize within the same root_type
            if account.root_type and account.root_type != group_root_type:
                skipped_count += 1
                changes.append(
                    {
                        "account": account.account_number or account.name,
                        "account_name": account.account_name,
                        "group_code": group_code,
                        "status": "skipped",
                        "reason": f"Would change root_type from {account.root_type} to {group_root_type}",
                    }
                )
                continue

            # Find or create the group parent account
            group_account_name = find_or_create_group_account(
                group_code=group_code,
                group_name=group_name,
                root_type=group_root_type,
                company=company,
                dry_run=dry_run,
                created_groups=created_groups,
                groups_created=groups_created,
            )

            if not group_account_name:
                skipped_count += 1
                changes.append(
                    {
                        "account": account.account_number,
                        "account_name": account.account_name,
                        "group_code": group_code,
                        "status": "skipped",
                        "reason": f"Could not find/create group account for {group_code}",
                    }
                )
                continue

            # Check if account is already under the correct parent
            if account.parent_account == group_account_name:
                skipped_count += 1
                continue

            change_record = {
                "account": account.account_number,
                "account_name": account.account_name,
                "group_code": group_code,
                "old_parent": account.parent_account,
                "new_parent": group_account_name,
                "new_parent_name": group_name,
            }

            if dry_run:
                change_record["status"] = "would_move"
                moved_count += 1
            else:
                # Actually move the account
                try:
                    frappe.db.set_value(
                        "Account",
                        account.name,
                        "parent_account",
                        group_account_name,
                        update_modified=False,
                    )
                    change_record["status"] = "moved"
                    moved_count += 1
                except Exception as e:
                    change_record["status"] = "error"
                    change_record["error"] = str(e)
                    skipped_count += 1

            changes.append(change_record)

        if not dry_run:
            # Rebuild the account tree to fix lft/rgt values
            frappe.db.commit()
            try:
                from frappe.utils.nestedset import rebuild_tree

                rebuild_tree("Account", "parent_account")
            except Exception as e:
                frappe.logger().warning(f"Could not rebuild account tree: {e}")

        result_key = "would_move" if dry_run else "moved"

        return {
            "success": True,
            "dry_run": dry_run,
            "total_accounts": len(accounts),
            result_key: moved_count,
            "groups_created": len(groups_created),
            "skipped": skipped_count,
            "changes": changes,
            "groups": groups_created,
            "mappings_used": len(group_type_mappings),
        }

    except Exception as e:
        frappe.log_error(f"Error reorganizing account hierarchy: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def reclassify_accounts_by_group_mappings(dry_run=True):
    """Re-classify existing ERPNext accounts based on configured group type mappings.

    Uses keyword matching to find the appropriate group for each account,
    then applies the configured group_type_mappings to update account_type and root_type.

    Args:
        dry_run: If True, returns preview of changes without applying them.
                 If False, actually updates the accounts.

    Returns:
        dict with success status and changes made/previewed.
    """
    try:
        # Convert string "true"/"false" to boolean (from JS)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() != "false"

        settings = frappe.get_single("E-Boekhouden Settings")

        if not settings.default_company:
            return {"success": False, "error": "Default company not configured in E-Boekhouden Settings"}

        # Get the group type mappings
        group_type_mappings = get_group_type_mappings_dict(settings)

        if not group_type_mappings:
            return {
                "success": False,
                "error": "No group type mappings configured. Please configure mappings first using 'Parse & Suggest Types'.",
            }

        # Get all non-group accounts
        accounts = frappe.get_all(
            "Account",
            filters={
                "company": settings.default_company,
                "is_group": 0,
            },
            fields=["name", "account_name", "account_number", "account_type", "root_type"],
        )

        changes = []
        updated_count = 0
        skipped_count = 0

        for account in accounts:
            # Use keyword matching to find the appropriate group
            group_code, group_name, match_reason = match_account_to_group(
                account.account_name, group_type_mappings
            )

            if not group_code:
                skipped_count += 1
                changes.append(
                    {
                        "account": account.account_number or account.name,
                        "account_name": account.account_name,
                        "group_code": None,
                        "old_root_type": account.root_type,
                        "old_account_type": account.account_type,
                        "new_root_type": None,
                        "new_account_type": None,
                        "status": "skipped",
                        "reason": "No matching group found for account name",
                    }
                )
                continue

            mapping = group_type_mappings[group_code]
            new_root_type = mapping.get("root_type")
            new_account_type = mapping.get("account_type", "")

            # Skip if this would change the root_type - only reclassify within same root
            if account.root_type and account.root_type != new_root_type:
                skipped_count += 1
                changes.append(
                    {
                        "account": account.account_number or account.name,
                        "account_name": account.account_name,
                        "group_code": group_code,
                        "old_root_type": account.root_type,
                        "new_root_type": new_root_type,
                        "status": "skipped",
                        "reason": f"Would change root_type from {account.root_type} to {new_root_type}",
                    }
                )
                continue

            # Check if anything would change
            if account.root_type == new_root_type and account.account_type == new_account_type:
                skipped_count += 1
                continue

            change_record = {
                "account": account.account_number or account.name,
                "account_name": account.account_name,
                "group_code": group_code,
                "group_name": group_name,
                "match_reason": match_reason,
                "old_root_type": account.root_type,
                "old_account_type": account.account_type,
                "new_root_type": new_root_type,
                "new_account_type": new_account_type,
            }

            if dry_run:
                change_record["status"] = "would_update"
                updated_count += 1
            else:
                # Actually update the account
                try:
                    frappe.db.set_value(
                        "Account",
                        account.name,
                        {
                            "root_type": new_root_type,
                            "account_type": new_account_type,
                        },
                        update_modified=False,
                    )
                    change_record["status"] = "updated"
                    updated_count += 1
                except Exception as e:
                    change_record["status"] = "error"
                    change_record["error"] = str(e)
                    skipped_count += 1

            changes.append(change_record)

        if not dry_run:
            frappe.db.commit()

        result_key = "would_update" if dry_run else "updated"

        return {
            "success": True,
            "dry_run": dry_run,
            "total_accounts": len(accounts),
            result_key: updated_count,
            "skipped": skipped_count,
            "changes": changes,
            "mappings_used": len(group_type_mappings),
        }

    except Exception as e:
        frappe.log_error(f"Error reclassifying accounts: {str(e)}")
        return {"success": False, "error": str(e)}
