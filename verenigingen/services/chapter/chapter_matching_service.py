# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
ChapterMatchingService - Chapter suggestion and matching for members

This service handles chapter matching and suggestion algorithms based on
geographic location, postal codes, and member address data.

Extracted from chapter.py:
- get_chapters_by_postal_code() - Lines 934-953 (20 LOC)
- suggest_chapters_for_member() - Lines 958-1029 (72 LOC)
- suggest_chapter_for_member() - Lines 1034-1036 (3 LOC, legacy wrapper)
- is_chapter_management_enabled() - Lines 1039-1044 (6 LOC)
Total extraction: ~101 LOC

Architecture:
- Static methods for stateless operations
- Scoring algorithm for chapter matching
- Postal code-based matching
- Region/city-based fallback matching
- Member address data integration

Dependencies:
- frappe.db for chapter queries
- Chapter.matches_postal_code() method
- Member address data
- Verenigingen Settings for feature flag
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class ChapterMatchingService(StatelessService):
    """
    Service for chapter matching and suggestion algorithms.

    This service handles:
    - Finding chapters by postal code
    - Suggesting chapters for members based on location
    - Scoring algorithms for match quality
    - Member address data resolution
    """

    # ========================================================================
    # SCORING CONSTANTS
    # ========================================================================

    SCORE_POSTAL_CODE_MATCH = 90
    SCORE_STATE_IN_REGION = 40
    SCORE_REGION_IN_STATE = 30
    SCORE_CITY_IN_REGION = 35
    SCORE_CITY_IN_NAME = 45

    def __init__(self) -> None:
        """Initialize the chapter matching service."""
        super().__init__(service_name="ChapterMatchingService")

    # ========================================================================
    # PUBLIC MATCHING METHODS
    # ========================================================================

    def get_chapters_by_postal_code(self, postal_code: str) -> List[Dict[str, Any]]:
        """Get chapters that match a postal code.

        Args:
            postal_code: Postal code to search for

        Returns:
            List of chapter dicts with name, region, postal_codes, introduction

        Examples:
            >>> ChapterMatchingService.get_chapters_by_postal_code("1234AB")
            [{"name": "Amsterdam", "region": "Noord-Holland", ...}]
        """
        if not postal_code:
            return []

        # Get all published chapters
        chapters = frappe.get_all(
            "Chapter", filters={"published": 1}, fields=["name", "region", "postal_codes", "introduction"]
        )

        matching_chapters = []

        # Check each chapter for postal code match
        for chapter in chapters:
            if not chapter.get("postal_codes"):
                continue

            # Use chapter's postal code matching logic
            chapter_doc = frappe.get_doc("Chapter", chapter.name)
            if chapter_doc.matches_postal_code(postal_code):
                matching_chapters.append(chapter)

        return matching_chapters

    def suggest_chapters_for_member(
        self,
        member: str,
        postal_code: Optional[str] = None,
        state: Optional[str] = None,
        city: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Suggest appropriate chapters for a member based on location.

        This method:
        1. Tries postal code matching first (highest score)
        2. Falls back to region/city matching
        3. Returns sorted list by match score

        Args:
            member: Member ID or name
            postal_code: Optional postal code (will fetch from member if not provided)
            state: Optional state/region
            city: Optional city

        Returns:
            List of chapter suggestions with:
                - name: Chapter name
                - city: Chapter region
                - state: Chapter region
                - match_score: Score (0-100)
                - distance: Distance info (currently "Unknown")

        Examples:
            >>> ChapterMatchingService.suggest_chapters_for_member("MEMBER-001")
            [{"name": "Amsterdam", "match_score": 90, ...}]
        """
        # Check if chapter management is enabled
        if not self._is_chapter_management_enabled():
            return []

        # Resolve location data from member if not provided
        if not postal_code and not state and not city:
            postal_code, state, city = self._get_member_location(member)

        matching_chapters = []

        # Strategy 1: Postal code matching (high confidence)
        if postal_code:
            chapters_by_postal = self.get_chapters_by_postal_code(postal_code)
            for chapter in chapters_by_postal:
                matching_chapters.append(
                    {
                        "name": chapter.get("name"),
                        "city": chapter.get("region", ""),
                        "state": chapter.get("region", ""),
                        "match_score": self.SCORE_POSTAL_CODE_MATCH,
                        "distance": "Unknown",
                    }
                )

        # Strategy 2: Region/city matching (fallback)
        if not matching_chapters:
            matching_chapters = self._find_chapters_by_region(state, city)

        # Sort by match score descending
        matching_chapters.sort(key=lambda x: x.get("match_score", 0), reverse=True)

        return matching_chapters

    # ========================================================================
    # HELPER METHODS (Private)
    # ========================================================================

    def _is_chapter_management_enabled(self) -> bool:
        """Check if chapter management is enabled in settings.

        Returns:
            True if enabled, defaults to True on error
        """
        try:
            return frappe.db.get_single_value("Verenigingen Settings", "enable_chapter_management") == 1
        except Exception:
            return True  # Fail open

    def _get_member_location(self, member: str) -> tuple:
        """Get location data from member's address.

        Args:
            member: Member ID

        Returns:
            Tuple of (postal_code, state, city)
        """
        postal_code = None
        state = None
        city = None

        try:
            member_doc = frappe.get_doc("Member", member)

            # Try primary address first
            if member_doc.primary_address:
                try:
                    address_doc = frappe.get_doc("Address", member_doc.primary_address)
                    postal_code = address_doc.pincode
                    state = address_doc.state
                    city = address_doc.city
                except Exception as e:
                    self.logger.error(f"Error fetching address for member {member}: {str(e)}")

            # Fallback to member's direct postal code field
            if not postal_code and hasattr(member_doc, "pincode"):
                postal_code = member_doc.pincode

        except Exception as e:
            self.logger.error(f"Error getting member location: {str(e)}")

        return postal_code, state, city

    def _find_chapters_by_region(self, state: Optional[str], city: Optional[str]) -> List[Dict[str, Any]]:
        """Find chapters by region/city matching with scoring.

        Args:
            state: State/region to match
            city: City to match

        Returns:
            List of chapter matches with scores
        """
        all_chapters = frappe.get_all(
            "Chapter", filters={"published": 1}, fields=["name", "region", "postal_codes", "introduction"]
        )

        matching_chapters = []

        for chapter in all_chapters:
            score = self._calculate_region_match_score(chapter=chapter, state=state, city=city)

            if score > 0:
                matching_chapters.append(
                    {
                        "name": chapter.get("name"),
                        "city": chapter.get("region", ""),
                        "state": chapter.get("region", ""),
                        "match_score": score,
                        "distance": "Unknown",
                    }
                )

        return matching_chapters

    def _calculate_region_match_score(
        self, chapter: Dict[str, Any], state: Optional[str], city: Optional[str]
    ) -> int:
        """Calculate match score based on region/city matching.

        Scoring rules:
        - State in chapter region: +40
        - Chapter region in state: +30
        - City in chapter region: +35
        - City in chapter name: +45

        Args:
            chapter: Chapter dict with name and region
            state: State to match
            city: City to match

        Returns:
            Match score (0-100)
        """
        score = 0

        # State matching
        if state and chapter.get("region"):
            state_lower = state.lower()
            region_lower = chapter.get("region").lower()

            if state_lower in region_lower:
                score += self.SCORE_STATE_IN_REGION
            elif region_lower in state_lower:
                score += self.SCORE_REGION_IN_STATE

        # City matching
        if city and chapter.get("region"):
            city_lower = city.lower()
            region_lower = chapter.get("region").lower()
            name_lower = chapter.get("name").lower()

            if city_lower in region_lower:
                score += self.SCORE_CITY_IN_REGION
            elif city_lower in name_lower:
                score += self.SCORE_CITY_IN_NAME

        return score
