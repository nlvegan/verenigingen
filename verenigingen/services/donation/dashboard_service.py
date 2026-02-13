"""
Donation Dashboard Service

Handles all data fetching and aggregation for the donation dashboard page.
Extracted from the donation_dashboard.py template controller to follow
service-oriented architecture.

All methods are read-only queries — no transaction management needed.
"""

from typing import Any, Dict, List, Optional

import frappe
from frappe.utils import add_days, flt, getdate, today

from verenigingen.services.infrastructure.base_service import StatelessService


class DonationDashboardService(StatelessService):
    """Service for fetching and assembling donation dashboard data.

    Inherits from StatelessService — read-only queries, no state management.
    """

    def __init__(self):
        super().__init__(service_name="DonationDashboardService")

    def get_dashboard_context(self) -> Dict[str, Any]:
        """Return complete dashboard data dict for the template context."""
        settings = frappe.get_single("Verenigingen Settings")
        current_year = getdate(today()).year
        year_start = f"{current_year}-01-01"
        year_end = f"{current_year}-12-31"
        min_amount = settings.anbi_minimum_reportable_amount

        result = {
            "anbi_minimum_reportable_amount": min_amount,
        }
        result.update(self._get_year_to_date_stats(year_start, year_end))
        result.update(self._get_periodic_agreement_stats())
        result.update(self._get_donor_stats())
        result.update(self._get_reportable_donations(year_start, year_end, min_amount))
        result["recent_donations"] = self._get_recent_donations()
        result["expiring_agreements"] = self._get_expiring_agreements()
        result["donation_trend_chart"] = self._get_monthly_trend_chart(current_year)
        result["agreement_distribution"] = self._get_agreement_distribution()

        return result

    def _get_year_to_date_stats(self, year_start: str, year_end: str) -> Dict[str, Any]:
        total_donations = frappe.db.sql(
            """
            SELECT
                SUM(amount) as total_amount,
                COUNT(*) as count
            FROM `tabDonation`
            WHERE paid = 1
            AND docstatus = 1
            AND donation_date BETWEEN %s AND %s
        """,
            (year_start, year_end),
            as_dict=1,
        )[0]

        return {
            "total_donations_amount": flt(total_donations.get("total_amount", 0), 2),
            "total_donations_count": total_donations.get("count", 0),
        }

    def _get_periodic_agreement_stats(self) -> Dict[str, Any]:
        periodic_stats = frappe.db.sql(
            """
            SELECT
                COUNT(CASE WHEN status = 'Active' AND anbi_eligible = 1 THEN 1 END) as active_anbi_count,
                COUNT(CASE WHEN status = 'Active' AND (anbi_eligible = 0 OR anbi_eligible IS NULL) THEN 1 END) as active_pledge_count,
                SUM(CASE WHEN status = 'Active' THEN annual_amount ELSE 0 END) as total_annual_amount,
                COUNT(CASE WHEN status = 'Active' AND end_date <= %s THEN 1 END) as expiring_soon_count
            FROM `tabPeriodic Donation Agreement`
            WHERE docstatus = 1
        """,
            (add_days(today(), 90),),
            as_dict=1,
        )[0]

        return {
            "active_anbi_agreements": periodic_stats.get("active_anbi_count", 0),
            "active_pledge_agreements": periodic_stats.get("active_pledge_count", 0),
            "total_annual_commitment": flt(periodic_stats.get("total_annual_amount", 0), 2),
            "expiring_soon_count": periodic_stats.get("expiring_soon_count", 0),
        }

    def _get_donor_stats(self) -> Dict[str, Any]:
        donor_stats = frappe.db.sql(
            """
            SELECT
                COUNT(DISTINCT donor.name) as unique_donors,
                COUNT(DISTINCT CASE WHEN donor.donor_type = 'Individual' THEN donor.name END) as individual_donors,
                COUNT(DISTINCT CASE WHEN donor.donor_type = 'Organization' THEN donor.name END) as organization_donors,
                COUNT(DISTINCT CASE WHEN donor.anbi_consent = 1 THEN donor.name END) as donors_with_consent
            FROM `tabDonor` donor
            WHERE donor.name IN (
                SELECT DISTINCT d.donor FROM `tabDonation` d
                WHERE d.paid = 1 AND d.docstatus = 1
            )
        """,
            as_dict=1,
        )[0]

        unique_donors = donor_stats.get("unique_donors", 0)
        donors_with_consent = donor_stats.get("donors_with_consent", 0)
        consent_percentage = flt((donors_with_consent / unique_donors * 100) if unique_donors > 0 else 0, 1)

        return {
            "unique_donors": unique_donors,
            "individual_donors": donor_stats.get("individual_donors", 0),
            "organization_donors": donor_stats.get("organization_donors", 0),
            "donors_with_consent": donors_with_consent,
            "consent_percentage": consent_percentage,
        }

    def _get_reportable_donations(self, year_start: str, year_end: str, min_amount: float) -> Dict[str, Any]:
        reportable_donations = frappe.db.sql(
            """
            SELECT
                COUNT(*) as count,
                SUM(amount) as total_amount
            FROM `tabDonation`
            WHERE paid = 1
            AND docstatus = 1
            AND donation_date BETWEEN %s AND %s
            AND (belastingdienst_reportable = 1 OR amount >= %s)
        """,
            (year_start, year_end, min_amount),
            as_dict=1,
        )[0]

        return {
            "reportable_donations_count": reportable_donations.get("count", 0),
            "reportable_donations_amount": flt(reportable_donations.get("total_amount", 0), 2),
        }

    def _get_recent_donations(self) -> List[Dict[str, Any]]:
        return frappe.db.sql(
            """
            SELECT
                d.name,
                d.donor,
                donor.donor_name,
                d.amount,
                d.donation_date,
                d.periodic_donation_agreement,
                pda.agreement_number,
                pda.anbi_eligible
            FROM `tabDonation` d
            LEFT JOIN `tabDonor` donor ON d.donor = donor.name
            LEFT JOIN `tabPeriodic Donation Agreement` pda ON d.periodic_donation_agreement = pda.name
            WHERE d.paid = 1
            AND d.docstatus = 1
            ORDER BY d.donation_date DESC
            LIMIT 10
        """,
            as_dict=1,
        )

    def _get_expiring_agreements(self) -> List[Dict[str, Any]]:
        return frappe.db.sql(
            """
            SELECT
                name,
                agreement_number,
                donor_name,
                end_date,
                annual_amount,
                anbi_eligible,
                DATEDIFF(end_date, %s) as days_remaining
            FROM `tabPeriodic Donation Agreement`
            WHERE status = 'Active'
            AND docstatus = 1
            AND end_date <= %s
            ORDER BY end_date ASC
            LIMIT 10
        """,
            (today(), add_days(today(), 90)),
            as_dict=1,
        )

    def _get_monthly_trend_chart(self, current_year: int) -> Dict[str, Any]:
        monthly_trend = frappe.db.sql(
            """
            SELECT
                MONTH(donation_date) as month,
                SUM(amount) as total_amount,
                COUNT(*) as count
            FROM `tabDonation`
            WHERE paid = 1
            AND docstatus = 1
            AND YEAR(donation_date) = %s
            GROUP BY MONTH(donation_date)
            ORDER BY MONTH(donation_date)
        """,
            (current_year,),
            as_dict=1,
        )

        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        chart_labels = []
        chart_values = []

        for i in range(1, 13):
            month_data = next((m for m in monthly_trend if m.month == i), None)
            chart_labels.append(months[i - 1])
            chart_values.append(float(month_data.total_amount) if month_data else 0)

        return {
            "labels": chart_labels,
            "datasets": [{"name": "Donations", "values": chart_values}],
        }

    def _get_agreement_distribution(self) -> Dict[str, Any]:
        agreement_distribution = frappe.db.sql(
            """
            SELECT
                CASE
                    WHEN anbi_eligible = 1 THEN 'ANBI Agreements'
                    ELSE 'Donation Pledges'
                END as type,
                COUNT(*) as count
            FROM `tabPeriodic Donation Agreement`
            WHERE status = 'Active'
            AND docstatus = 1
            GROUP BY anbi_eligible
        """,
            as_dict=1,
        )

        return {
            "labels": [d.type for d in agreement_distribution],
            "datasets": [{"name": "Agreements", "values": [d.count for d in agreement_distribution]}],
        }


# Module-level singleton accessor
_service_instance: Optional[DonationDashboardService] = None


def get_donation_dashboard_service() -> DonationDashboardService:
    """Get or create the DonationDashboardService singleton.

    Returns:
        DonationDashboardService: The service instance
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = DonationDashboardService()
    return _service_instance
