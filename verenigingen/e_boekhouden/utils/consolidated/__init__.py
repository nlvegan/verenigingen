"""
E-Boekhouden Consolidated Utilities

This package contains consolidated implementations that replace scattered
functionality throughout the E-Boekhouden module.

Modules:
- party_manager: Consolidated party (customer/supplier) management (964 → 400 lines)
- account_manager: Consolidated account creation and management (790 → 350 lines)
- migration_coordinator: Consolidated migration coordination (823 → 400 lines)

Total reduction: 2,577 → 1,150 lines (55% reduction with improved functionality)
"""

from .account_manager import (
    EBoekhoudenAccountManager,
    create_account_with_smart_typing,
    get_smart_account_type,
)
from .migration_coordinator import (
    EBoekhoudenMigrationCoordinator,
    coordinate_migration,
    validate_migration_prerequisites,
)
from .party_manager import (
    EBoekhoudenPartyManager,
    get_or_create_customer_simple,
    get_or_create_supplier_simple,
)

__all__ = [
    "EBoekhoudenPartyManager",
    "EBoekhoudenAccountManager",
    "EBoekhoudenMigrationCoordinator",
    "get_or_create_customer_simple",
    "get_or_create_supplier_simple",
    "get_smart_account_type",
    "create_account_with_smart_typing",
    "coordinate_migration",
    "validate_migration_prerequisites",
]
