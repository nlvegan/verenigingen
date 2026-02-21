"""
Role Profile to Module Profile Mappings

Single source of truth for role profile and module profile associations.
Used by both the role profile calculator and deployment scripts.

Author: Verenigingen Development Team
Last Updated: 2025-10-10
"""

from verenigingen.utils.constants import Roles

# Role to Module Profile mapping
# Maps role profiles to actual module profiles defined in fixtures/module_profile.json
ROLE_MODULE_MAPPING = {
    "Verenigingen Member": "Verenigingen Member",
    "Verenigingen Volunteer": "Verenigingen Volunteer",
    "Verenigingen Team Leader": "Verenigingen Volunteer",
    "Verenigingen Chapter Board Member": "Verenigingen Chapter Board Member",
    "Verenigingen Treasurer": "Verenigingen Treasurer",
    "Verenigingen Communications Officer": "Verenigingen Volunteer",
    "Verenigingen Event Coordinator": "Verenigingen Volunteer",
    Roles.VERENIGINGEN_STAFF: "Verenigingen National Board Member",
    "Verenigingen Finance Manager": "Verenigingen Treasurer",
    "Verenigingen System Administrator": None,  # Full access
    "Verenigingen Auditor": "Verenigingen Auditor",
    "Verenigingen Guest": "Verenigingen Member",
    "Verenigingen Kascommissie": "Verenigingen Auditor",
    "Verenigingen National Board Member": "Verenigingen National Board Member",
}
