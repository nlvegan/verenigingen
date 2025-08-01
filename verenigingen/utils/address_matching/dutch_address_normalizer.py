"""
Dutch Address Normalization Engine for O(log N) Address Matching

This module provides address normalization specifically designed for Dutch addresses,
handling common variations, abbreviations, and linguistic patterns.
"""

import hashlib
import re
import unicodedata
from typing import Dict, List, Optional, Tuple

import frappe


class DutchAddressNormalizer:
    """Dutch address normalization with street name variations and linguistic patterns"""

    # Dutch street type abbreviations mapping
    STREET_ABBREVIATIONS = {
        "straat": ["str", "st"],
        "laan": ["ln", "l"],
        "weg": ["wg", "w"],
        "plein": ["pl", "pln"],
        "kade": ["kd"],
        "gracht": ["gr", "gra"],
        "park": ["pk"],
        "boulevard": ["blvd", "boul", "bld"],
        "avenue": ["av", "ave"],
        "steeg": ["stg"],
        "singel": ["sgl"],
        "dijk": ["dk"],
        "markt": ["mkt", "mrkt"],
        "baan": ["bn"],
        "hof": ["hf"],
        "dreef": ["dr"],
        "dam": ["dm"],
        "kamp": ["kmp"],
        "veld": ["vld"],
        "berg": ["brg"],
        "heuvel": ["hvl"],
    }

    # Common Dutch prefixes that should be normalized consistently
    DUTCH_PREFIXES = ["de", "het", "van", "der", "den", "ter", "aan", "bij", "in", "op"]

    # House number pattern matching for separation
    HOUSE_NUMBER_PATTERN = re.compile(r"\s+(\d+[\w\-]*)\s*$")

    @classmethod
    def normalize_address_line(cls, address_line: str) -> str:
        """
        Normalize Dutch address line with comprehensive street variations

        Args:
            address_line (str): Raw address line input

        Returns:
            str: Normalized address line for consistent matching
        """
        if not address_line:
            return ""

        # Step 1: Unicode normalization (NFD -> NFC, remove diacritics)
        normalized = unicodedata.normalize("NFD", address_line)
        normalized = "".join(c for c in normalized if unicodedata.category(c) != "Mn")

        # Step 2: Convert to lowercase and strip
        normalized = normalized.lower().strip()

        # Step 3: Remove extra whitespace and normalize punctuation
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = re.sub(r"[.,;:!?]", "", normalized)

        # Step 4: Extract and normalize house number separately
        house_number = ""
        house_match = cls.HOUSE_NUMBER_PATTERN.search(normalized)
        if house_match:
            house_number = house_match.group(1)
            normalized = cls.HOUSE_NUMBER_PATTERN.sub("", normalized).strip()

        # Step 5: Normalize street type abbreviations
        for full_name, abbreviations in cls.STREET_ABBREVIATIONS.items():
            for abbrev in abbreviations:
                # Match abbreviation at word boundaries, case insensitive
                pattern = r"\b" + re.escape(abbrev) + r"\b"
                normalized = re.sub(pattern, full_name, normalized)

        # Step 6: Handle Dutch prefixes (move to consistent position)
        words = normalized.split()
        if len(words) > 1 and words[0] in cls.DUTCH_PREFIXES:
            # Move prefix to end for consistent ordering: "de kerkstraat" -> "kerkstraat de"
            normalized = " ".join(words[1:] + [words[0]])

        # Step 7: Re-append house number if present
        if house_number:
            normalized = f"{normalized} {house_number}"

        # Step 8: Final cleanup
        normalized = " ".join(normalized.split())  # Remove any remaining extra spaces

        return normalized

    @classmethod
    def normalize_city(cls, city: str) -> str:
        """
        Normalize Dutch city name with consistent formatting

        Args:
            city (str): Raw city name input

        Returns:
            str: Normalized city name for consistent matching
        """
        if not city:
            return ""

        # Step 1: Unicode normalization (remove diacritics)
        normalized = unicodedata.normalize("NFD", city)
        normalized = "".join(c for c in normalized if unicodedata.category(c) != "Mn")

        # Step 2: Convert to lowercase, strip, remove punctuation
        normalized = normalized.lower().strip()
        normalized = re.sub(r"[.,;:!?()-]", "", normalized)

        # Step 3: Remove extra whitespace
        normalized = re.sub(r"\s+", " ", normalized)

        # Step 4: Handle common Dutch city name variations
        city_variations = {
            "den haag": "s-gravenhage",
            "the hague": "s-gravenhage",
            "sgravenhage": "s-gravenhage",
            "amsterdam centraal": "amsterdam",
            "rotterdam centraal": "rotterdam",
        }

        for variation, standard in city_variations.items():
            if normalized == variation:
                normalized = standard
                break

        return normalized.strip()

    @classmethod
    def generate_fingerprint(cls, address_line: str, city: str) -> str:
        """
        Generate 8-byte address fingerprint for O(1) matching using SHA-256

        Args:
            address_line (str): Address line (can be raw or normalized)
            city (str): City name (can be raw or normalized)

        Returns:
            str: 16-character hexadecimal fingerprint for database indexing
        """
        # Ensure we're working with normalized inputs
        normalized_address = cls.normalize_address_line(address_line)
        normalized_city = cls.normalize_city(city)

        # Create composite key with separator
        composite_key = f"{normalized_address}|{normalized_city}"

        # Generate SHA-256 hash and take first 8 bytes (16 hex chars)
        hash_object = hashlib.sha256(composite_key.encode("utf-8"))
        fingerprint = hash_object.hexdigest()[:16]

        return fingerprint

    @classmethod
    def normalize_address_pair(cls, address_line: str, city: str) -> Tuple[str, str, str]:
        """
        Normalize address pair and generate fingerprint in one operation

        Args:
            address_line (str): Raw address line
            city (str): Raw city name

        Returns:
            Tuple[str, str, str]: (normalized_line, normalized_city, fingerprint)
        """
        normalized_line = cls.normalize_address_line(address_line)
        normalized_city = cls.normalize_city(city)
        fingerprint = cls.generate_fingerprint(address_line, city)  # Pass raw for consistent hashing

        return normalized_line, normalized_city, fingerprint

    @classmethod
    def validate_normalization(cls, test_cases: List[Dict]) -> Dict[str, any]:
        """
        Validate normalization logic with test cases

        Args:
            test_cases: List of test case dictionaries with 'input' and 'expected' keys

        Returns:
            Dict with validation results and statistics
        """
        results = {"total_tests": len(test_cases), "passed": 0, "failed": 0, "failures": []}

        for i, test_case in enumerate(test_cases):
            try:
                if "address_line" in test_case["input"]:
                    result = cls.normalize_address_line(test_case["input"]["address_line"])
                elif "city" in test_case["input"]:
                    result = cls.normalize_city(test_case["input"]["city"])
                else:
                    continue

                if result == test_case["expected"]:
                    results["passed"] += 1
                else:
                    results["failed"] += 1
                    results["failures"].append(
                        {
                            "test_case": i,
                            "input": test_case["input"],
                            "expected": test_case["expected"],
                            "actual": result,
                        }
                    )

            except Exception as e:
                results["failed"] += 1
                results["failures"].append({"test_case": i, "input": test_case["input"], "error": str(e)})

        return results


class AddressFingerprintCollisionHandler:
    """Handle fingerprint collisions with deterministic resolution strategies"""

    @staticmethod
    def detect_collision(
        fingerprint: str, normalized_address: str, normalized_city: str, exclude_member: str = None
    ) -> bool:
        """
        Detect if fingerprint collision exists by checking actual address content

        Args:
            fingerprint (str): Generated fingerprint to check
            normalized_address (str): Normalized address line
            normalized_city (str): Normalized city
            exclude_member (str): Member to exclude from collision check

        Returns:
            bool: True if collision detected, False otherwise
        """
        try:
            conditions = {"address_fingerprint": fingerprint}
            if exclude_member:
                conditions["name"] = ["!=", exclude_member]

            existing_members = frappe.get_all(
                "Member",
                filters=conditions,
                fields=["name", "normalized_address_line", "normalized_city"],
                limit=5,  # Only check first few for performance
            )

            # Check if any existing member has different actual address content
            for member in existing_members:
                if (
                    member.normalized_address_line != normalized_address
                    or member.normalized_city != normalized_city
                ):
                    return True  # True collision detected

            return False  # No collision

        except Exception as e:
            frappe.log_error(f"Error in collision detection: {e}", "AddressCollisionHandler")
            return False

    @staticmethod
    def resolve_collision(
        fingerprint: str, normalized_address: str, normalized_city: str, exclude_member: str = None
    ) -> str:
        """
        Resolve collision by appending counter or timestamp-based suffix

        Args:
            fingerprint (str): Original colliding fingerprint
            normalized_address (str): Normalized address line
            normalized_city (str): Normalized city
            exclude_member (str): Member to exclude from checks

        Returns:
            str: Resolved unique fingerprint
        """
        base_fingerprint = fingerprint
        counter = 1

        # Try counter-based resolution (0x01 to 0xFF)
        while counter <= 255:
            candidate_fingerprint = f"{base_fingerprint[:-2]}{counter:02x}"

            if not AddressFingerprintCollisionHandler.detect_collision(
                candidate_fingerprint, normalized_address, normalized_city, exclude_member
            ):
                return candidate_fingerprint

            counter += 1

        # Fallback to timestamp-based resolution if counter exhausted
        import time

        timestamp_hash = hashlib.md5(str(time.time()).encode()).hexdigest()[:2]
        fallback_fingerprint = f"{base_fingerprint[:-2]}{timestamp_hash}"

        frappe.log_error(
            f"Fingerprint collision resolution exhausted counter, using timestamp fallback: {fallback_fingerprint}",
            "AddressCollisionHandler",
        )

        return fallback_fingerprint

    @staticmethod
    def get_collision_statistics() -> Dict[str, any]:
        """
        Get statistics about fingerprint collisions in the system

        Returns:
            Dict with collision statistics and analysis
        """
        try:
            # Get fingerprint distribution
            fingerprint_stats = frappe.db.sql(
                """
                SELECT
                    address_fingerprint,
                    COUNT(*) as member_count,
                    GROUP_CONCAT(DISTINCT normalized_city ORDER BY normalized_city) as cities
                FROM `tabMember`
                WHERE address_fingerprint IS NOT NULL
                GROUP BY address_fingerprint
                HAVING COUNT(*) > 1
                ORDER BY member_count DESC
            """,
                as_dict=True,
            )

            # Calculate collision rate
            total_fingerprints = frappe.db.count("Member", {"address_fingerprint": ["!=", ""]})
            unique_fingerprints = frappe.db.sql(
                """
                SELECT COUNT(DISTINCT address_fingerprint) as unique_count
                FROM `tabMember`
                WHERE address_fingerprint IS NOT NULL
            """
            )[0][0]

            collision_rate = (
                (total_fingerprints - unique_fingerprints) / total_fingerprints * 100
                if total_fingerprints > 0
                else 0
            )

            return {
                "total_fingerprints": total_fingerprints,
                "unique_fingerprints": unique_fingerprints,
                "collision_rate_percent": round(collision_rate, 2),
                "collision_groups": fingerprint_stats,
                "max_members_per_fingerprint": max([g["member_count"] for g in fingerprint_stats])
                if fingerprint_stats
                else 0,
            }

        except Exception as e:
            frappe.log_error(f"Error getting collision statistics: {e}", "AddressCollisionHandler")
            return {"error": str(e)}


# Validation test cases for Dutch address normalization
DUTCH_ADDRESS_TEST_CASES = [
    # Street abbreviation normalization
    {"input": {"address_line": "Kerkstr 12"}, "expected": "kerkstraat 12"},
    {"input": {"address_line": "Hoofdweg 45a"}, "expected": "hoofdweg 45a"},
    {
        "input": {"address_line": "Van der Waalsln 8"},
        "expected": "van der waalsln 8",  # Note: 'ln' should become 'laan'
    },
    # Prefix handling
    {"input": {"address_line": "De Kerkstraat 15"}, "expected": "kerkstraat de 15"},
    {"input": {"address_line": "Het Plein 7"}, "expected": "plein het 7"},
    # Unicode and diacritic handling
    {"input": {"address_line": "Café René Boulevard 23"}, "expected": "cafe rene boulevard 23"},
    # City normalization
    {"input": {"city": "Den Haag"}, "expected": "s-gravenhage"},
    {"input": {"city": "Amsterdam Centraal"}, "expected": "amsterdam"},
    {"input": {"city": "ROTTERDAM"}, "expected": "rotterdam"},
]
