"""
Services module - Centralized business services for Verenigingen.

This module contains extracted service classes that handle specific business logic
that was previously embedded in DocType classes. Services provide better separation
of concerns and reusability.

Available Services:
    - member_id_service: Member and application ID generation
    - customer_service: ERPNext Customer creation and management
    - member_status_service: Member status and lifecycle management
"""
