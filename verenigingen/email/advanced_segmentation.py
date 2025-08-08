#!/usr/bin/env python3
"""
Advanced Email Segmentation System
Phase 3 Implementation - Advanced Member Segmentation

This module provides advanced segmentation capabilities for targeted email campaigns
based on member behavior, demographics, engagement, and custom criteria.
"""

import json
from datetime import date, datetime
from typing import Dict, List, Optional, Set

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now_datetime


class AdvancedSegmentationManager:
    """Manager for advanced member segmentation and targeting"""

    def __init__(self):
        self.built_in_segments = self._get_built_in_segments()

    def _get_built_in_segments(self) -> Dict:
        """Define built-in segmentation options"""
        return {
            # Engagement-based segments
            "highly_engaged": {
                "name": "Highly Engaged Members",
                "description": "Members with high email engagement (>75% score)",
                "category": "Engagement",
                "query_type": "engagement",
                "criteria": {"engagement_score": {"operator": ">=", "value": 75}},
            },
            "low_engagement": {
                "name": "Low Engagement Members",
                "description": "Members with low email engagement (<25% score)",
                "category": "Engagement",
                "query_type": "engagement",
                "criteria": {"engagement_score": {"operator": "<", "value": 25}},
            },
            "new_members": {
                "name": "New Members (Last 30 Days)",
                "description": "Members who joined in the last 30 days",
                "category": "Membership",
                "query_type": "date_range",
                "criteria": {"creation": {"operator": ">=", "value": "30_days_ago"}},
            },
            "long_term_members": {
                "name": "Long-term Members (>2 Years)",
                "description": "Members who have been active for more than 2 years",
                "category": "Membership",
                "query_type": "date_range",
                "criteria": {"creation": {"operator": "<=", "value": "2_years_ago"}},
            },
            "volunteers_only": {
                "name": "Active Volunteers",
                "description": "Members who are currently active volunteers",
                "category": "Role",
                "query_type": "volunteer_status",
                "criteria": {"volunteer_status": {"operator": "=", "value": "Active"}},
            },
            "board_members_only": {
                "name": "Board Members",
                "description": "Current chapter and organization board members",
                "category": "Role",
                "query_type": "board_member",
                "criteria": {"board_member": {"operator": "=", "value": True}},
            },
            "donors": {
                "name": "Donors",
                "description": "Members who have made donations",
                "category": "Financial",
                "query_type": "donation_history",
                "criteria": {"has_donated": {"operator": "=", "value": True}},
            },
            "non_donors": {
                "name": "Non-Donors",
                "description": "Members who have never made donations",
                "category": "Financial",
                "query_type": "donation_history",
                "criteria": {"has_donated": {"operator": "=", "value": False}},
            },
            # Demographic segments
            "young_members": {
                "name": "Young Members (Under 35)",
                "description": "Members under 35 years old",
                "category": "Demographics",
                "query_type": "age_range",
                "criteria": {"age": {"operator": "<", "value": 35}},
            },
            "senior_members": {
                "name": "Senior Members (55+)",
                "description": "Members 55 years and older",
                "category": "Demographics",
                "query_type": "age_range",
                "criteria": {"age": {"operator": ">=", "value": 55}},
            },
            # Geographic segments
            "urban_members": {
                "name": "Urban Members",
                "description": "Members in urban postal code areas",
                "category": "Geographic",
                "query_type": "postal_code_type",
                "criteria": {"area_type": {"operator": "=", "value": "urban"}},
            },
            # Behavioral segments
            "event_attendees": {
                "name": "Recent Event Attendees",
                "description": "Members who attended events in the last 90 days",
                "category": "Behavior",
                "query_type": "event_attendance",
                "criteria": {"attended_recently": {"operator": "=", "value": True}},
            },
            "inactive_members": {
                "name": "Inactive Members",
                "description": "Members with no recent activity (6+ months)",
                "category": "Behavior",
                "query_type": "activity_level",
                "criteria": {"last_activity": {"operator": "<=", "value": "6_months_ago"}},
            },
        }

    def get_segment_recipients(
        self, segment_id: str, chapter_name: str = None, additional_filters: Dict = None
    ) -> Dict:
        """
        Get recipients for a specific segment

        Args:
            segment_id: Segment identifier
            chapter_name: Chapter name filter (optional)
            additional_filters: Additional filtering criteria

        Returns:
            Dict with recipients and metadata
        """
        try:
            if segment_id in self.built_in_segments:
                return self._get_built_in_segment_recipients(segment_id, chapter_name, additional_filters)
            else:
                # Check for custom segment
                return self._get_custom_segment_recipients(segment_id, chapter_name, additional_filters)

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _get_built_in_segment_recipients(
        self, segment_id: str, chapter_name: str = None, additional_filters: Dict = None
    ) -> Dict:
        """Get recipients for built-in segments"""
        segment_def = self.built_in_segments[segment_id]
        query_type = segment_def["query_type"]
        criteria = segment_def["criteria"]

        base_conditions = [
            "m.status = 'Active'",
            "m.email IS NOT NULL",
            "m.email != ''",
            "(m.opt_out_optional_emails IS NULL OR m.opt_out_optional_emails = 0)",
        ]

        values = {}

        # Add chapter filter if specified
        if chapter_name:
            base_conditions.append(
                """
                EXISTS (
                    SELECT 1 FROM `tabChapter Member` cm
                    WHERE cm.member = m.name
                    AND cm.parent = %(chapter)s
                    AND cm.enabled = 1
                )
            """
            )
            values["chapter"] = chapter_name

        # Build query based on segment type
        if query_type == "engagement":
            # This would require engagement scores to be calculated
            # For now, return basic query with placeholder
            recipients = frappe.db.sql(
                f"""
                SELECT DISTINCT m.email, m.name, m.first_name, m.last_name
                FROM `tabMember` m
                WHERE {" AND ".join(base_conditions)}
                ORDER BY m.first_name, m.last_name
            """,
                values,
                as_dict=True,
            )

        elif query_type == "date_range":
            date_value = criteria[list(criteria.keys())[0]]["value"]
            if date_value == "30_days_ago":
                base_conditions.append("m.creation >= DATE_SUB(NOW(), INTERVAL 30 DAY)")
            elif date_value == "2_years_ago":
                base_conditions.append("m.creation <= DATE_SUB(NOW(), INTERVAL 2 YEAR)")

            recipients = frappe.db.sql(
                f"""
                SELECT DISTINCT m.email, m.name, m.first_name, m.last_name, m.creation
                FROM `tabMember` m
                WHERE {" AND ".join(base_conditions)}
                ORDER BY m.creation DESC
            """,
                values,
                as_dict=True,
            )

        elif query_type == "volunteer_status":
            base_conditions.append(
                """
                EXISTS (
                    SELECT 1 FROM `tabVolunteer` v
                    WHERE v.member = m.name
                    AND v.status = 'Active'
                )
            """
            )

            recipients = frappe.db.sql(
                f"""
                SELECT DISTINCT m.email, m.name, m.first_name, m.last_name,
                       v.volunteer_name
                FROM `tabMember` m
                INNER JOIN `tabVolunteer` v ON v.member = m.name
                WHERE {" AND ".join(base_conditions)}
                ORDER BY m.first_name, m.last_name
            """,
                values,
                as_dict=True,
            )

        elif query_type == "board_member":
            base_conditions.append(
                """
                EXISTS (
                    SELECT 1 FROM `tabChapter Board Member` cbm
                    INNER JOIN `tabVolunteer` v ON cbm.volunteer = v.name
                    WHERE v.member = m.name
                    AND cbm.is_active = 1
                    AND (cbm.to_date IS NULL OR cbm.to_date >= CURDATE())
                )
            """
            )

            recipients = frappe.db.sql(
                f"""
                SELECT DISTINCT m.email, m.name, m.first_name, m.last_name,
                       cbm.chapter_role, cbm.parent as chapter
                FROM `tabMember` m
                INNER JOIN `tabVolunteer` v ON v.member = m.name
                INNER JOIN `tabChapter Board Member` cbm ON cbm.volunteer = v.name
                WHERE {" AND ".join(base_conditions)}
                ORDER BY m.first_name, m.last_name
            """,
                values,
                as_dict=True,
            )

        elif query_type == "donation_history":
            has_donated = criteria["has_donated"]["value"]
            if has_donated:
                base_conditions.append(
                    """
                    EXISTS (
                        SELECT 1 FROM `tabDonation` d
                        WHERE d.donor = m.name
                        AND d.docstatus = 1
                    )
                """
                )
            else:
                base_conditions.append(
                    """
                    NOT EXISTS (
                        SELECT 1 FROM `tabDonation` d
                        WHERE d.donor = m.name
                        AND d.docstatus = 1
                    )
                """
                )

            recipients = frappe.db.sql(
                f"""
                SELECT DISTINCT m.email, m.name, m.first_name, m.last_name
                FROM `tabMember` m
                WHERE {" AND ".join(base_conditions)}
                ORDER BY m.first_name, m.last_name
            """,
                values,
                as_dict=True,
            )

        elif query_type == "age_range":
            age_operator = criteria["age"]["operator"]
            age_value = criteria["age"]["value"]

            # Calculate birth date range
            if age_operator == "<":
                base_conditions.append(f"m.birth_date > DATE_SUB(CURDATE(), INTERVAL {age_value} YEAR)")
            elif age_operator == ">=":
                base_conditions.append(f"m.birth_date <= DATE_SUB(CURDATE(), INTERVAL {age_value} YEAR)")

            recipients = frappe.db.sql(
                f"""
                SELECT DISTINCT m.email, m.name, m.first_name, m.last_name, m.birth_date,
                       FLOOR(DATEDIFF(CURDATE(), m.birth_date) / 365.25) as age
                FROM `tabMember` m
                WHERE {" AND ".join(base_conditions)}
                    AND m.birth_date IS NOT NULL
                ORDER BY m.birth_date DESC
            """,
                values,
                as_dict=True,
            )

        else:
            # Default fallback - all active members
            recipients = frappe.db.sql(
                f"""
                SELECT DISTINCT m.email, m.name, m.first_name, m.last_name
                FROM `tabMember` m
                WHERE {" AND ".join(base_conditions)}
                ORDER BY m.first_name, m.last_name
            """,
                values,
                as_dict=True,
            )

        return {
            "success": True,
            "segment_id": segment_id,
            "segment_name": segment_def["name"],
            "recipients": recipients,
            "recipients_count": len(recipients),
            "query_type": query_type,
            "chapter_filter": chapter_name,
        }

    def _get_custom_segment_recipients(
        self, segment_id: str, chapter_name: str = None, additional_filters: Dict = None
    ) -> Dict:
        """Get recipients for custom segments (placeholder for future implementation)"""
        return {"success": False, "error": "Custom segments not yet implemented"}

    def create_segment_combination(
        self,
        segment_ids: List[str],
        operation: str = "intersection",  # intersection, union, exclusion
        chapter_name: str = None,
    ) -> Dict:
        """
        Create a combination of multiple segments

        Args:
            segment_ids: List of segment IDs to combine
            operation: How to combine segments (intersection/union/exclusion)
            chapter_name: Chapter filter

        Returns:
            Combined segment recipients
        """
        try:
            if not segment_ids:
                return {"success": False, "error": "No segments specified"}

            # Get recipients for each segment
            segment_results = []
            for segment_id in segment_ids:
                result = self.get_segment_recipients(segment_id, chapter_name)
                if result["success"]:
                    recipient_emails = {r["email"] for r in result["recipients"]}
                    segment_results.append(
                        {
                            "id": segment_id,
                            "name": result["segment_name"],
                            "emails": recipient_emails,
                            "recipients": result["recipients"],
                        }
                    )
                else:
                    return {
                        "success": False,
                        "error": f"Failed to get segment {segment_id}: {result.get('error')}",
                    }

            if not segment_results:
                return {"success": False, "error": "No valid segments found"}

            # Combine segments based on operation
            if operation == "intersection":
                # Members who are in ALL segments
                combined_emails = segment_results[0]["emails"]
                for segment in segment_results[1:]:
                    combined_emails = combined_emails.intersection(segment["emails"])

            elif operation == "union":
                # Members who are in ANY segment
                combined_emails = set()
                for segment in segment_results:
                    combined_emails = combined_emails.union(segment["emails"])

            elif operation == "exclusion":
                # Members in first segment but NOT in others
                if len(segment_results) < 2:
                    return {"success": False, "error": "Exclusion requires at least 2 segments"}

                combined_emails = segment_results[0]["emails"]
                for segment in segment_results[1:]:
                    combined_emails = combined_emails - segment["emails"]

            else:
                return {
                    "success": False,
                    "error": "Invalid operation. Use: intersection, union, or exclusion",
                }

            # Get full recipient details for combined emails
            combined_recipients = []
            for segment in segment_results:
                for recipient in segment["recipients"]:
                    if recipient["email"] in combined_emails:
                        combined_recipients.append(recipient)
                        combined_emails.discard(recipient["email"])  # Avoid duplicates

            return {
                "success": True,
                "operation": operation,
                "source_segments": [{"id": s["id"], "name": s["name"]} for s in segment_results],
                "recipients": combined_recipients,
                "recipients_count": len(combined_recipients),
                "chapter_filter": chapter_name,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def analyze_segment_overlap(self, segment_ids: List[str], chapter_name: str = None) -> Dict:
        """
        Analyze overlap between multiple segments

        Args:
            segment_ids: List of segment IDs to analyze
            chapter_name: Chapter filter

        Returns:
            Overlap analysis
        """
        try:
            if len(segment_ids) < 2:
                return {"success": False, "error": "Need at least 2 segments for overlap analysis"}

            # Get recipients for each segment
            segments = {}
            for segment_id in segment_ids:
                result = self.get_segment_recipients(segment_id, chapter_name)
                if result["success"]:
                    segments[segment_id] = {
                        "name": result["segment_name"],
                        "emails": {r["email"] for r in result["recipients"]},
                        "count": result["recipients_count"],
                    }

            if len(segments) < 2:
                return {"success": False, "error": "Could not load enough valid segments"}

            # Calculate pairwise overlaps
            overlap_matrix = {}
            for seg1_id, seg1_data in segments.items():
                overlap_matrix[seg1_id] = {}
                for seg2_id, seg2_data in segments.items():
                    if seg1_id == seg2_id:
                        overlap_matrix[seg1_id][seg2_id] = {"count": seg1_data["count"], "percentage": 100.0}
                    else:
                        intersection = seg1_data["emails"].intersection(seg2_data["emails"])
                        overlap_count = len(intersection)
                        overlap_percentage = (
                            (overlap_count / seg1_data["count"] * 100) if seg1_data["count"] > 0 else 0
                        )

                        overlap_matrix[seg1_id][seg2_id] = {
                            "count": overlap_count,
                            "percentage": round(overlap_percentage, 1),
                        }

            # Find unique members (only in one segment)
            all_emails = set()
            for seg_data in segments.values():
                all_emails = all_emails.union(seg_data["emails"])

            unique_members = {}
            for seg_id, seg_data in segments.items():
                other_emails = set()
                for other_id, other_data in segments.items():
                    if other_id != seg_id:
                        other_emails = other_emails.union(other_data["emails"])

                unique_to_segment = seg_data["emails"] - other_emails
                unique_members[seg_id] = {
                    "count": len(unique_to_segment),
                    "percentage": (
                        round(len(unique_to_segment) / seg_data["count"] * 100, 1)
                        if seg_data["count"] > 0
                        else 0
                    ),
                }

            return {
                "success": True,
                "segments": {
                    seg_id: {"name": seg_data["name"], "count": seg_data["count"]}
                    for seg_id, seg_data in segments.items()
                },
                "overlap_matrix": overlap_matrix,
                "unique_members": unique_members,
                "total_unique_members": len(all_emails),
                "chapter_filter": chapter_name,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_segment_suggestions(self, chapter_name: str = None) -> Dict:
        """
        Get segment suggestions based on chapter data

        Args:
            chapter_name: Chapter name filter

        Returns:
            Suggested segments
        """
        try:
            suggestions = []

            # Analyze chapter member distribution
            if chapter_name:
                chapter_stats = frappe.db.sql(
                    """
                    SELECT
                        COUNT(*) as total_members,
                        COUNT(CASE WHEN m.creation >= DATE_SUB(NOW(), INTERVAL 30 DAY) THEN 1 END) as new_members,
                        COUNT(CASE WHEN EXISTS (SELECT 1 FROM `tabVolunteer` v WHERE v.member = m.name AND v.status = 'Active') THEN 1 END) as volunteers,
                        COUNT(CASE WHEN m.birth_date IS NOT NULL AND m.birth_date > DATE_SUB(CURDATE(), INTERVAL 35 YEAR) THEN 1 END) as young_members,
                        COUNT(CASE WHEN EXISTS (SELECT 1 FROM `tabDonation` d WHERE d.donor = m.name AND d.docstatus = 1) THEN 1 END) as donors
                    FROM `tabMember` m
                    INNER JOIN `tabChapter Member` cm ON cm.member = m.name
                    WHERE cm.parent = %(chapter)s
                        AND cm.enabled = 1
                        AND m.status = 'Active'
                        AND (m.opt_out_optional_emails IS NULL OR m.opt_out_optional_emails = 0)
                """,
                    {"chapter": chapter_name},
                    as_dict=True,
                )[0]
            else:
                chapter_stats = frappe.db.sql(
                    """
                    SELECT
                        COUNT(*) as total_members,
                        COUNT(CASE WHEN m.creation >= DATE_SUB(NOW(), INTERVAL 30 DAY) THEN 1 END) as new_members,
                        COUNT(CASE WHEN EXISTS (SELECT 1 FROM `tabVolunteer` v WHERE v.member = m.name AND v.status = 'Active') THEN 1 END) as volunteers,
                        COUNT(CASE WHEN m.birth_date IS NOT NULL AND m.birth_date > DATE_SUB(CURDATE(), INTERVAL 35 YEAR) THEN 1 END) as young_members,
                        COUNT(CASE WHEN EXISTS (SELECT 1 FROM `tabDonation` d WHERE d.donor = m.name AND d.docstatus = 1) THEN 1 END) as donors
                    FROM `tabMember` m
                    WHERE m.status = 'Active'
                        AND (m.opt_out_optional_emails IS NULL OR m.opt_out_optional_emails = 0)
                """,
                    as_dict=True,
                )[0]

            total = chapter_stats["total_members"] or 0

            # Suggest segments based on significant populations
            if chapter_stats["new_members"] > total * 0.1:  # >10% new members
                suggestions.append(
                    {
                        "segment_id": "new_members",
                        "name": "New Members (Last 30 Days)",
                        "reason": f"{chapter_stats['new_members']} new members ({round(chapter_stats['new_members'] / total * 100, 1)}%)",
                        "priority": "high",
                    }
                )

            if chapter_stats["volunteers"] > total * 0.15:  # >15% volunteers
                suggestions.append(
                    {
                        "segment_id": "volunteers_only",
                        "name": "Active Volunteers",
                        "reason": f"{chapter_stats['volunteers']} volunteers ({round(chapter_stats['volunteers'] / total * 100, 1)}%)",
                        "priority": "medium",
                    }
                )

            if chapter_stats["young_members"] > total * 0.2:  # >20% young members
                suggestions.append(
                    {
                        "segment_id": "young_members",
                        "name": "Young Members (Under 35)",
                        "reason": f"{chapter_stats['young_members']} young members ({round(chapter_stats['young_members'] / total * 100, 1)}%)",
                        "priority": "medium",
                    }
                )

            if chapter_stats["donors"] < total * 0.3:  # <30% donors - target non-donors
                suggestions.append(
                    {
                        "segment_id": "non_donors",
                        "name": "Non-Donors",
                        "reason": f"{total - chapter_stats['donors']} non-donors ({round((total - chapter_stats['donors']) / total * 100, 1)}%) - fundraising opportunity",
                        "priority": "high",
                    }
                )

            # Always suggest engagement-based segments
            suggestions.extend(
                [
                    {
                        "segment_id": "highly_engaged",
                        "name": "Highly Engaged Members",
                        "reason": "Target your most engaged members for important announcements",
                        "priority": "medium",
                    },
                    {
                        "segment_id": "low_engagement",
                        "name": "Low Engagement Members",
                        "reason": "Re-engage members with lower email activity",
                        "priority": "low",
                    },
                ]
            )

            return {
                "success": True,
                "chapter_name": chapter_name,
                "chapter_stats": chapter_stats,
                "suggestions": suggestions,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


# API Functions
@frappe.whitelist()
def get_available_segments(chapter_name: str = None) -> Dict:
    """Get available segmentation options"""
    manager = AdvancedSegmentationManager()

    segments = []
    for segment_id, segment_data in manager.built_in_segments.items():
        segments.append(
            {
                "id": segment_id,
                "name": segment_data["name"],
                "description": segment_data["description"],
                "category": segment_data["category"],
            }
        )

    return {"success": True, "segments": segments, "categories": list(set(s["category"] for s in segments))}


@frappe.whitelist()
def get_segment_recipients(segment_id: str, chapter_name: str = None, preview_only: bool = False) -> Dict:
    """
    Get recipients for a segment

    Args:
        segment_id: Segment identifier
        chapter_name: Chapter name filter
        preview_only: If True, only return count and sample

    Returns:
        Segment recipients
    """
    # Check permissions
    if chapter_name and not frappe.has_permission("Chapter", "read", doc=chapter_name):
        frappe.throw(_("You don't have permission to view this chapter's segments"))

    manager = AdvancedSegmentationManager()
    result = manager.get_segment_recipients(segment_id, chapter_name)

    if result["success"] and preview_only:
        # Return only preview data
        recipients = result["recipients"]
        return {
            "success": True,
            "segment_id": segment_id,
            "segment_name": result["segment_name"],
            "recipients_count": result["recipients_count"],
            "sample_recipients": recipients[:5],  # First 5 as sample
            "query_type": result["query_type"],
        }

    return result


@frappe.whitelist()
def create_segment_combination(
    segment_ids: str, operation: str = "intersection", chapter_name: str = None
) -> Dict:
    """
    Create combined segment

    Args:
        segment_ids: JSON array of segment IDs
        operation: Combination operation
        chapter_name: Chapter filter

    Returns:
        Combined segment result
    """
    try:
        segment_ids = json.loads(segment_ids) if isinstance(segment_ids, str) else segment_ids

        # Check permissions
        if chapter_name and not frappe.has_permission("Chapter", "read", doc=chapter_name):
            frappe.throw(_("You don't have permission to view this chapter's segments"))

        manager = AdvancedSegmentationManager()
        return manager.create_segment_combination(segment_ids, operation, chapter_name)

    except json.JSONDecodeError:
        return {"success": False, "error": "Invalid segment_ids JSON"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def analyze_segment_overlap(segment_ids: str, chapter_name: str = None) -> Dict:
    """
    Analyze overlap between segments

    Args:
        segment_ids: JSON array of segment IDs
        chapter_name: Chapter filter

    Returns:
        Overlap analysis
    """
    try:
        segment_ids = json.loads(segment_ids) if isinstance(segment_ids, str) else segment_ids

        # Check permissions
        if chapter_name and not frappe.has_permission("Chapter", "read", doc=chapter_name):
            frappe.throw(_("You don't have permission to view this chapter's segments"))

        manager = AdvancedSegmentationManager()
        return manager.analyze_segment_overlap(segment_ids, chapter_name)

    except json.JSONDecodeError:
        return {"success": False, "error": "Invalid segment_ids JSON"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_segment_suggestions(chapter_name: str = None) -> Dict:
    """Get segment suggestions for a chapter"""
    # Check permissions
    if chapter_name and not frappe.has_permission("Chapter", "read", doc=chapter_name):
        frappe.throw(_("You don't have permission to view this chapter's data"))

    manager = AdvancedSegmentationManager()
    return manager.get_segment_suggestions(chapter_name)
