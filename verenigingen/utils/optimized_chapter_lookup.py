# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Optimized Chapter Lookup Utilities

This module provides high-performance chapter lookup functionality to eliminate
N+1 query problems in reports and bulk operations. It implements caching and
batch processing to dramatically improve performance when matching postal codes
to chapters for large numbers of members.

Key optimizations:
- Cached chapter management feature status check
- Pre-built postal code mapping for fast lookups
- Batch processing to avoid repeated database queries
- Memory-efficient pattern matching

Performance improvements:
- Reduces N×M queries to 1-2 queries for batch operations
- Caches feature flags and chapter data for repeated use
- Eliminates redundant Chapter document loads
"""

import re
from typing import Dict, List, Optional, Tuple

import frappe
from frappe.utils import cint


class OptimizedChapterLookup:
    """High-performance chapter lookup with caching and batch processing"""

    def __init__(self):
        self._chapter_management_enabled = None
        self._chapter_postal_mapping = None
        self._last_cache_update = None
        self._cache_ttl = 300  # 5 minutes cache TTL

    def is_chapter_management_enabled(self) -> bool:
        """Cached check for chapter management feature status"""
        if self._chapter_management_enabled is None:
            try:
                settings = frappe.get_single("Verenigingen Settings")
                self._chapter_management_enabled = cint(getattr(settings, "enable_chapter_management", 0))
            except Exception:
                frappe.log_error("Failed to check chapter management setting")
                self._chapter_management_enabled = False

        return self._chapter_management_enabled

    def invalidate_cache(self):
        """Force cache refresh on next lookup"""
        self._chapter_management_enabled = None
        self._chapter_postal_mapping = None
        self._last_cache_update = None

    def _needs_cache_refresh(self) -> bool:
        """Check if cache needs refresh based on TTL"""
        if self._last_cache_update is None:
            return True

        import time

        return (time.time() - self._last_cache_update) > self._cache_ttl

    def _build_postal_mapping(self) -> Dict[str, List[Dict]]:
        """Build optimized postal code to chapter mapping"""
        if not self.is_chapter_management_enabled():
            return {}

        # Get all published chapters with postal codes in one query
        chapters = frappe.get_all(
            "Chapter", filters={"published": 1}, fields=["name", "region", "postal_codes"]
        )

        mapping = {}

        for chapter in chapters:
            if not chapter.get("postal_codes"):
                continue

            try:
                # Parse postal code patterns without loading full Chapter doc
                patterns = self._parse_postal_code_patterns(chapter.postal_codes)

                for pattern in patterns:
                    # Create mapping entries for efficient lookup
                    pattern_key = pattern.strip().replace(" ", "").upper()

                    if pattern_key not in mapping:
                        mapping[pattern_key] = []

                    mapping[pattern_key].append(
                        {"name": chapter.name, "region": chapter.region, "pattern": pattern}
                    )

            except Exception as e:
                frappe.log_error(f"Error parsing postal codes for chapter {chapter.name}: {str(e)}")
                continue

        return mapping

    def _parse_postal_code_patterns(self, postal_codes_text: str) -> List[str]:
        """Parse postal code patterns from text field"""
        if not postal_codes_text:
            return []

        # Split by common delimiters and clean up
        patterns = []
        for line in postal_codes_text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):  # Skip comments
                continue

            # Split by comma for multiple patterns on one line
            for pattern in line.split(","):
                pattern = pattern.strip()
                if pattern:
                    patterns.append(pattern)

        return patterns

    def _test_postal_code_match(self, postal_code: str, pattern: str) -> bool:
        """Test if postal code matches pattern (simplified version)"""
        if not postal_code or not pattern:
            return False

        # Normalize both
        postal_code = postal_code.strip().replace(" ", "").upper()
        pattern = pattern.strip().replace(" ", "").upper()

        # Exact match
        if postal_code == pattern:
            return True

        # Range match (e.g., "1000-1999")
        if "-" in pattern:
            try:
                start, end = pattern.split("-", 1)
                # Sanitize - remove trailing asterisks
                start = start.strip().rstrip("*")
                end = end.strip().rstrip("*")
                start_num = int(start)
                end_num = int(end)
                postal_num = int(postal_code[: len(start)])
                return start_num <= postal_num <= end_num
            except (ValueError, IndexError):
                pass

        # Prefix match (e.g., "10*" or "10")
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return postal_code.startswith(prefix)
        else:
            # Default prefix match for numeric patterns
            # Sanitize pattern by removing trailing asterisks
            clean_pattern = pattern.rstrip("*")
            return postal_code.startswith(clean_pattern)

    def get_chapter_postal_mapping(self) -> Dict[str, List[Dict]]:
        """Get cached postal code mapping, refreshing if needed"""
        if self._chapter_postal_mapping is None or self._needs_cache_refresh():
            self._chapter_postal_mapping = self._build_postal_mapping()
            import time

            self._last_cache_update = time.time()

        return self._chapter_postal_mapping

    def find_chapters_for_postal_code(self, postal_code: str) -> List[Dict]:
        """Find all chapters matching a postal code (optimized)"""
        if not postal_code or not self.is_chapter_management_enabled():
            return []

        postal_code = postal_code.strip().replace(" ", "").upper()
        mapping = self.get_chapter_postal_mapping()

        matching_chapters = []

        # Check all patterns in mapping
        for pattern_key, chapter_list in mapping.items():
            for chapter_info in chapter_list:
                if self._test_postal_code_match(postal_code, chapter_info["pattern"]):
                    # Avoid duplicates
                    if not any(c["name"] == chapter_info["name"] for c in matching_chapters):
                        matching_chapters.append(
                            {"name": chapter_info["name"], "region": chapter_info["region"]}
                        )

        return matching_chapters

    def find_best_chapter_for_postal_code(self, postal_code: str) -> Optional[str]:
        """Find the best matching chapter for a postal code"""
        chapters = self.find_chapters_for_postal_code(postal_code)

        if not chapters:
            return None

        # Return first match (could be enhanced with priority logic)
        return chapters[0]["name"]

    def batch_find_chapters_for_members(
        self, member_postal_codes: List[Tuple[str, str]]
    ) -> Dict[str, Optional[str]]:
        """
        Batch find chapters for multiple members

        Args:
            member_postal_codes: List of (member_name, postal_code) tuples

        Returns:
            Dict mapping member_name to best_chapter_name (or None)
        """
        if not self.is_chapter_management_enabled():
            return {member_name: None for member_name, _ in member_postal_codes}

        results = {}

        for member_name, postal_code in member_postal_codes:
            if not postal_code:
                results[member_name] = None
                continue

            best_chapter = self.find_best_chapter_for_postal_code(postal_code)
            results[member_name] = best_chapter

        return results


# Global instance for reuse
_lookup_instance = None


def get_lookup_instance() -> OptimizedChapterLookup:
    """Get singleton instance of optimized chapter lookup"""
    global _lookup_instance
    if _lookup_instance is None:
        _lookup_instance = OptimizedChapterLookup()
    return _lookup_instance


def find_chapter_by_postal_code_optimized(postal_code: str) -> Dict:
    """
    Optimized replacement for member_utils.find_chapter_by_postal_code

    Returns same format as original function for compatibility
    """
    lookup = get_lookup_instance()

    if not lookup.is_chapter_management_enabled():
        return {"success": False, "message": "Chapter management is disabled"}

    if not postal_code:
        return {"success": False, "message": "Postal code is required"}

    matching_chapters = lookup.find_chapters_for_postal_code(postal_code)

    return {"success": True, "matching_chapters": matching_chapters}


def batch_suggest_chapters_for_members(
    members_with_postal_codes: List[Tuple[str, str]],
) -> Dict[str, Optional[str]]:
    """
    Batch suggest chapters for multiple members efficiently

    Args:
        members_with_postal_codes: List of (member_name, postal_code) tuples

    Returns:
        Dict mapping member_name to suggested_chapter_name (or None)
    """
    lookup = get_lookup_instance()
    return lookup.batch_find_chapters_for_members(members_with_postal_codes)


def invalidate_chapter_lookup_cache(doc=None, method=None):
    """Invalidate the chapter lookup cache (call when chapters are modified)"""
    lookup = get_lookup_instance()
    lookup.invalidate_cache()
