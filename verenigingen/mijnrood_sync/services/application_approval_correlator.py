"""
MijnRood Application Approval Correlator

When MijnRood approves a membership applicant it deletes the source row from
admin_membership_application and creates a new row in admin_member with a
different primary key. The polling service sees these as two independent
events ("Deleted" on the application table, "New" on the member table).

This correlator runs after all tables have been polled in a single sync run
and collapses confident pairs into a single "Approved" event. The two raw
events are marked Ignored with a cross-reference note.

Pairing strategy (in order):
  1. mollie_customer_id match — strongest signal, tolerates field drift
  2. Email match — requires last-name agreement, vetoed by Mollie mismatch

Unmatched Deletions are left alone (likely rejections). Ambiguous matches
(>1 candidate on either side) are also left alone.
"""

import json
from typing import Optional

import frappe
from frappe import _
from frappe.utils import now_datetime

from verenigingen.mijnrood_sync.services.polling_service import compute_change_tags
from verenigingen.services.infrastructure.base_service import StatefulService


class ApplicationApprovalCorrelator(StatefulService):
    """Collapses admin_membership_application Deleted + admin_member New event
    pairs created in the same sync run into a single Approved event."""

    def __init__(self):
        super().__init__(service_name="ApplicationApprovalCorrelator")

    def correlate(self, sync_run_id: str) -> int:
        """Entry point. Returns the number of pairs collapsed."""
        deletions, creations = self._load_candidates(sync_run_id)
        if not deletions or not creations:
            return 0

        pairs_collapsed = 0

        # Pass 1 — Mollie-ID match
        mollie_index = {}
        for c in creations:
            c_mollie = self._field(c["new_data"], "mollie_customer_id")
            if c_mollie:
                mollie_index.setdefault(c_mollie, []).append(c)

        remaining_deletions = []
        paired_creation_names = set()
        for d in deletions:
            d_mollie = self._field(d["old_data"], "mollie_customer_id")
            if not d_mollie:
                remaining_deletions.append(d)
                continue
            candidates = [c for c in mollie_index.get(d_mollie, []) if c["name"] not in paired_creation_names]
            if len(candidates) == 1:
                c = candidates[0]
                self._collapse_pair(d, c, sync_run_id)
                paired_creation_names.add(c["name"])
                pairs_collapsed += 1
            else:
                # 0 or >1 — leave for Pass 2 (0) or skip (>1 logged)
                if len(candidates) > 1:
                    self.logger.warning(
                        "Ambiguous Mollie match for deletion %s (id=%s): %d candidates",
                        d["name"],
                        d_mollie,
                        len(candidates),
                    )
                else:
                    remaining_deletions.append(d)

        # Pass 2 — Email + last-name match (fallback)
        email_index = {}
        for c in creations:
            if c["name"] in paired_creation_names:
                continue
            c_email = self._field(c["new_data"], "email")
            if c_email:
                email_index.setdefault(c_email.lower(), []).append(c)

        for d in remaining_deletions:
            d_email = self._field(d["old_data"], "email")
            if not d_email:
                continue
            candidates = [
                c for c in email_index.get(d_email.lower(), []) if c["name"] not in paired_creation_names
            ]
            if len(candidates) != 1:
                if len(candidates) > 1:
                    self.logger.warning(
                        "Ambiguous email match for deletion %s (email=%s): %d candidates",
                        d["name"],
                        d_email,
                        len(candidates),
                    )
                continue

            c = candidates[0]
            if not self._passes_confidence_check(d, c):
                continue

            self._collapse_pair(d, c, sync_run_id)
            paired_creation_names.add(c["name"])
            pairs_collapsed += 1

        return pairs_collapsed

    # ─── Candidate loading ────────────────────────────────────────────

    def _load_candidates(self, sync_run_id: str) -> tuple[list[dict], list[dict]]:
        """Load Pending Deleted admin_membership_application events and
        Pending New admin_member events for this sync run."""
        fields = [
            "name",
            "event_type",
            "mijnrood_table",
            "mijnrood_row_id",
            "status",
            "linked_member",
            "old_data",
            "new_data",
        ]
        deletions = frappe.get_all(
            "MijnRood Sync Event",
            filters={
                "sync_run_id": sync_run_id,
                "event_type": "Deleted",
                "mijnrood_table": "admin_membership_application",
                "status": "Pending",
            },
            fields=fields,
        )
        creations = frappe.get_all(
            "MijnRood Sync Event",
            filters={
                "sync_run_id": sync_run_id,
                "event_type": "New",
                "mijnrood_table": "admin_member",
                "status": "Pending",
            },
            fields=fields,
        )
        return deletions, creations

    # ─── Pair collapsing ──────────────────────────────────────────────

    def _collapse_pair(self, deletion: dict, creation: dict, sync_run_id: str) -> None:
        """Emit the Approved event and mark both raw events Ignored."""
        approved_name = self._emit_approved_event(deletion, creation, sync_run_id)
        note = _("Superseded by {0}").format(approved_name)
        self._mark_ignored(deletion["name"], note)
        self._mark_ignored(creation["name"], note)

    def _emit_approved_event(self, deletion: dict, creation: dict, sync_run_id: str) -> str:
        """Create and insert the synthesized Approved event. Returns its name."""
        old_data = json.loads(deletion["old_data"]) if deletion["old_data"] else {}
        new_data = json.loads(creation["new_data"]) if creation["new_data"] else {}

        summary = self._build_summary(old_data, new_data)

        event = frappe.new_doc("MijnRood Sync Event")
        event.event_type = "Approved"
        event.mijnrood_table = "admin_member"
        event.mijnrood_row_id = creation["mijnrood_row_id"]
        event.status = "Pending"
        event.linked_member = creation.get("linked_member") or deletion.get("linked_member")
        event.old_data = json.dumps(old_data)
        event.new_data = json.dumps(new_data)
        event.change_summary = summary
        event.change_tags = compute_change_tags("Approved", "admin_member", None)
        event.detected_at = now_datetime()
        event.sync_run_id = sync_run_id
        # Security: System-internal synthesized event creation, runs in scheduler/background context
        event.insert(ignore_permissions=True)
        return event.name

    def _mark_ignored(self, event_name: str, note: str) -> None:
        """Mark a raw event as Ignored with a cross-reference note."""
        frappe.db.set_value(
            "MijnRood Sync Event",
            event_name,
            {"status": "Ignored", "review_notes": note},
            update_modified=False,
        )

    def _passes_confidence_check(self, deletion: dict, creation: dict) -> bool:
        """Confirm an email-based pair via last-name agreement and veto rules."""
        d_last = (self._field(deletion["old_data"], "last_name") or "").lower()
        c_last = (self._field(creation["new_data"], "last_name") or "").lower()
        if d_last != c_last:
            self.logger.info(
                "Last-name mismatch blocks pair %s ↔ %s: %r vs %r",
                deletion["name"],
                creation["name"],
                d_last,
                c_last,
            )
            return False

        d_mollie = self._field(deletion["old_data"], "mollie_customer_id")
        c_mollie = self._field(creation["new_data"], "mollie_customer_id")
        if d_mollie and c_mollie and d_mollie != c_mollie:
            self.logger.info(
                "Mollie-ID mismatch vetoes pair %s ↔ %s: %s vs %s",
                deletion["name"],
                creation["name"],
                d_mollie,
                c_mollie,
            )
            return False

        d_dob = self._field(deletion["old_data"], "date_of_birth")
        c_dob = self._field(creation["new_data"], "date_of_birth")
        if d_dob and c_dob and d_dob != c_dob:
            self.logger.info(
                "DOB mismatch blocks pair %s ↔ %s: %s vs %s",
                deletion["name"],
                creation["name"],
                d_dob,
                c_dob,
            )
            return False

        return True

    def _build_summary(self, old_data: dict, new_data: dict) -> str:
        """Human-readable summary for the synthesized Approved event."""
        name_parts = [
            (new_data.get(k) or old_data.get(k) or "").strip()
            for k in ("first_name", "middle_name", "last_name")
        ]
        full_name = " ".join(p for p in name_parts if p) or "unknown"
        return _("Application approved: {0} (app #{1} → member #{2})").format(
            full_name,
            old_data.get("id", "?"),
            new_data.get("id", "?"),
        )

    @staticmethod
    def _field(raw_json: Optional[str], key: str) -> Optional[str]:
        """Safely extract a field from a JSON string column."""
        if not raw_json:
            return None
        try:
            data = json.loads(raw_json)
        except (TypeError, ValueError):
            return None
        val = data.get(key)
        if val is None or val == "":
            return None
        return str(val).strip()


# Module-level singleton
_correlator_instance: Optional[ApplicationApprovalCorrelator] = None


def get_correlator() -> ApplicationApprovalCorrelator:
    """Singleton accessor for the correlator."""
    global _correlator_instance
    if _correlator_instance is None:
        _correlator_instance = ApplicationApprovalCorrelator()
    return _correlator_instance
