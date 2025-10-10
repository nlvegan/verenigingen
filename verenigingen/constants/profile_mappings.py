"""
Role Profile to Module Profile Mappings

Single source of truth for role profile and module profile associations.
Used by both the role profile calculator and deployment scripts.

Author: Verenigingen Development Team
Last Updated: 2025-10-10
"""

# Role to Module Profile mapping
ROLE_MODULE_MAPPING = {
    "Verenigingen Member": "Verenigingen Basic Access",
    "Verenigingen Volunteer": "Verenigingen Volunteer Access",
    "Verenigingen Team Leader": "Verenigingen Team Management Access",
    "Verenigingen Chapter Board Member": "Verenigingen Volunteer Access",
    "Verenigingen Treasurer": "Verenigingen Financial Access",
    "Verenigingen Chapter Administrator": "Verenigingen Management Access",
    "Verenigingen Communications Officer": "Verenigingen Communications Access",
    "Verenigingen Event Coordinator": "Verenigingen Volunteer Access",
    "Verenigingen Staff": "Verenigingen Management Access",
    "Verenigingen Finance Manager": "Verenigingen Finance Management Access",
    "Verenigingen System Administrator": None,  # Full access
    "Verenigingen Auditor": "Verenigingen Audit Access",
    "Verenigingen Guest": "Verenigingen Guest Access",
    "Verenigingen Kascommissie": "Verenigingen Financial Access",
    "Verenigingen National Board Member": "Verenigingen Management Access",
}
