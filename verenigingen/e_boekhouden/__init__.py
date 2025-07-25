"""
E-Boekhouden Integration Module

A dedicated module for Dutch accounting system integration with ERPNext.
This module provides comprehensive migration, synchronization, and mapping
capabilities for E-Boekhouden data into the Frappe/ERPNext framework.

Features:
- Complete chart of accounts import and mapping
- Transaction migration (invoices, payments, journal entries)
- Opening balance import with party assignment
- Real-time synchronization capabilities
- Dutch tax compliance and VAT handling
- Comprehensive error handling and logging

This follows ERPNext's modular architecture pattern where specialized
integrations are organized into dedicated modules.
"""

__version__ = "1.0.0"
