import hashlib
import re
import unicodedata
from typing import Tuple

import frappe


def execute():
    """Add address matching optimization fields and indexes"""

    # Step 1: Add computed fields to Member DocType
    add_computed_fields_to_member_doctype()

    # Step 2: Create composite indexes for optimized lookups
    create_address_matching_indexes()

    # Step 3: Populate computed fields for existing members
    populate_computed_fields_for_existing_members()

    # Step 4: Create performance tracking table
    create_performance_tracking_table()

    frappe.db.commit()


def add_computed_fields_to_member_doctype():
    """Add computed fields to Member DocType schema"""

    print("Adding computed fields to Member DocType...")

    # The fields are added via JSON modification, but we ensure columns exist
    fields_to_add = [
        ("address_fingerprint", "VARCHAR(16)"),
        ("normalized_address_line", "VARCHAR(200)"),
        ("normalized_city", "VARCHAR(100)"),
        ("address_last_updated", "DATETIME"),
    ]

    for field_name, field_type in fields_to_add:
        try:
            # Check if column exists
            result = frappe.db.sql(
                f"""
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                    AND TABLE_NAME = 'tabMember'
                    AND COLUMN_NAME = '{field_name}'
            """
            )

            if not result:
                # Add column if it doesn't exist
                frappe.db.sql(
                    f"""
                    ALTER TABLE `tabMember`
                    ADD COLUMN `{field_name}` {field_type}
                """
                )
                print(f"Added column: {field_name}")
            else:
                print(f"Column already exists: {field_name}")

        except Exception as e:
            print(f"Error adding column {field_name}: {e}")


def create_address_matching_indexes():
    """Create composite indexes for O(log N) address matching"""

    print("Creating address matching indexes...")

    indexes_to_create = [
        # Primary fingerprint index for O(1) lookups
        {
            "name": "idx_member_address_fingerprint",
            "table": "tabMember",
            "columns": "address_fingerprint",
            "type": "BTREE",
        },
        # Normalized address composite index for O(log N) fallback
        {
            "name": "idx_member_normalized_address",
            "table": "tabMember",
            "columns": "normalized_address_line, normalized_city",
            "type": "BTREE",
        },
        # Address update timestamp index for cache invalidation
        {
            "name": "idx_member_address_updated",
            "table": "tabMember",
            "columns": "address_last_updated",
            "type": "BTREE",
        },
        # Primary address index for JOIN operations
        {
            "name": "idx_member_primary_address",
            "table": "tabMember",
            "columns": "primary_address",
            "type": "BTREE",
        },
    ]

    for index_def in indexes_to_create:
        try:
            # Check if index exists
            existing_indexes = frappe.db.sql(
                f"""
                SELECT INDEX_NAME
                FROM INFORMATION_SCHEMA.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE()
                    AND TABLE_NAME = '{index_def['table']}'
                    AND INDEX_NAME = '{index_def['name']}'
            """
            )

            if not existing_indexes:
                # Create index
                sql = f"""CREATE INDEX `{index_def['name']}` ON `{index_def['table']}` ({index_def['columns']}) USING {index_def['type']}"""
                frappe.db.sql(sql)
                print(f"Created index: {index_def['name']}")
            else:
                print(f"Index already exists: {index_def['name']}")

        except Exception as e:
            print(f"Error creating index {index_def['name']}: {e}")


def populate_computed_fields_for_existing_members():
    """Populate computed fields for all existing members with addresses"""

    print("Populating computed fields for existing members...")

    # Get all members with primary addresses
    members_with_addresses = frappe.db.sql(
        """
        SELECT m.name, m.primary_address
        FROM `tabMember` m
        WHERE m.primary_address IS NOT NULL
            AND m.primary_address != ''
    """,
        as_dict=True,
    )

    print(f"Found {len(members_with_addresses)} members with addresses to process")

    processed_count = 0
    error_count = 0

    for member_data in members_with_addresses:
        try:
            # Get address details
            address = frappe.db.get_value(
                "Address", member_data.primary_address, ["address_line1", "city"], as_dict=True
            )

            if not address:
                continue

            # Generate computed values
            normalized_line, normalized_city, fingerprint = normalize_address_pair(
                address.address_line1 or "", address.city or ""
            )

            # Handle potential collisions
            fingerprint = resolve_fingerprint_collision(
                fingerprint, normalized_line, normalized_city, member_data.name
            )

            # Update member record
            frappe.db.sql(
                """
                UPDATE `tabMember`
                SET address_fingerprint = %s,
                    normalized_address_line = %s,
                    normalized_city = %s,
                    address_last_updated = %s
                WHERE name = %s
            """,
                (fingerprint, normalized_line, normalized_city, frappe.utils.now(), member_data.name),
            )

            processed_count += 1

            if processed_count % 50 == 0:
                print(f"Processed {processed_count} members...")
                frappe.db.commit()

        except Exception as e:
            error_count += 1
            print(f"Error processing member {member_data.name}: {e}")

    print(f"Completed: {processed_count} processed, {error_count} errors")


def normalize_address_pair(address_line: str, city: str) -> Tuple[str, str, str]:
    """Normalize address pair and generate fingerprint"""

    normalized_line = normalize_address_line(address_line)
    normalized_city = normalize_city(city)
    fingerprint = generate_fingerprint(normalized_line, normalized_city)

    return normalized_line, normalized_city, fingerprint


def normalize_address_line(address_line: str) -> str:
    """Normalize Dutch address line with street variations"""
    if not address_line:
        return ""

    # Unicode normalization (NFD -> NFC)
    normalized = unicodedata.normalize("NFD", address_line)
    normalized = "".join(c for c in normalized if unicodedata.category(c) != "Mn")

    # Convert to lowercase and strip
    normalized = normalized.lower().strip()

    # Remove extra whitespace
    normalized = re.sub(r"\s+", " ", normalized)

    # Dutch street type abbreviations
    street_abbreviations = {
        "straat": ["str", "st"],
        "laan": ["ln"],
        "weg": ["wg"],
        "plein": ["pl"],
        "kade": ["kd"],
        "gracht": ["gr"],
        "park": ["pk"],
        "boulevard": ["blvd", "boul"],
        "avenue": ["av", "ave"],
    }

    # Normalize street type abbreviations
    for full_name, abbreviations in street_abbreviations.items():
        for abbrev in abbreviations:
            # Match abbreviation at word boundaries
            pattern = r"\b" + re.escape(abbrev) + r"\b"
            normalized = re.sub(pattern, full_name, normalized)

    # Normalize common Dutch prefixes
    prefixes = ["de", "het", "van", "der", "den", "ter", "aan"]
    words = normalized.split()
    if len(words) > 1 and words[0] in prefixes:
        # Move prefix to end: "de kerkstraat" -> "kerkstraat de"
        normalized = " ".join(words[1:] + [words[0]])

    return normalized


def normalize_city(city: str) -> str:
    """Normalize Dutch city name"""
    if not city:
        return ""

    # Unicode normalization
    normalized = unicodedata.normalize("NFD", city)
    normalized = "".join(c for c in normalized if unicodedata.category(c) != "Mn")

    # Convert to lowercase, strip, remove extra whitespace
    normalized = normalized.lower().strip()
    normalized = re.sub(r"\s+", " ", normalized)

    return normalized


def generate_fingerprint(normalized_address: str, normalized_city: str) -> str:
    """Generate 8-byte address fingerprint for O(1) matching"""

    # Create composite key
    composite_key = f"{normalized_address}|{normalized_city}"

    # Generate SHA-256 hash and take first 8 bytes (16 hex chars)
    hash_object = hashlib.sha256(composite_key.encode("utf-8"))
    fingerprint = hash_object.hexdigest()[:16]

    return fingerprint


def resolve_fingerprint_collision(
    fingerprint: str, normalized_line: str, normalized_city: str, exclude_member: str
) -> str:
    """Resolve fingerprint collisions by appending counter"""

    # Check if collision exists
    existing_members = frappe.db.sql(
        """
        SELECT name, normalized_address_line, normalized_city
        FROM `tabMember`
        WHERE address_fingerprint = %s
            AND name != %s
        LIMIT 5
    """,
        (fingerprint, exclude_member),
        as_dict=True,
    )

    # Check for actual collision (not just hash match)
    for member in existing_members:
        if member.normalized_address_line != normalized_line or member.normalized_city != normalized_city:
            # Collision detected, resolve it
            base_fingerprint = fingerprint
            counter = 1

            while counter <= 255:
                candidate_fingerprint = f"{base_fingerprint[:-2]}{counter:02x}"

                # Check if this candidate is available
                existing_candidate = frappe.db.get_value(
                    "Member", {"address_fingerprint": candidate_fingerprint}, "name"
                )

                if not existing_candidate:
                    return candidate_fingerprint

                counter += 1

            # Fallback to timestamp-based resolution
            import time

            timestamp_hash = hashlib.md5(str(time.time()).encode()).hexdigest()[:2]
            return f"{base_fingerprint[:-2]}{timestamp_hash}"

    return fingerprint


def create_performance_tracking_table():
    """Create table for tracking address matching performance metrics"""

    print("Creating performance tracking table...")

    try:
        frappe.db.sql(
            """
            CREATE TABLE IF NOT EXISTS `tabAddress Matching Metrics` (
                `name` VARCHAR(140) NOT NULL PRIMARY KEY,
                `creation` DATETIME NOT NULL,
                `modified` DATETIME NOT NULL,
                `modified_by` VARCHAR(140),
                `owner` VARCHAR(140),
                `docstatus` INT(1) NOT NULL DEFAULT 0,
                `tier` VARCHAR(20) NOT NULL,
                `duration_ms` DECIMAL(10,2) NOT NULL,
                `result_count` INT NOT NULL,
                `cache_hit` TINYINT(1) DEFAULT 0,
                `timestamp` DATETIME NOT NULL,
                INDEX `idx_metrics_timestamp` (`timestamp`),
                INDEX `idx_metrics_tier` (`tier`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
        )
        print("Performance tracking table created successfully")
    except Exception as e:
        print(f"Error creating performance tracking table: {e}")
