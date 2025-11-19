"""
Custom Exception Classes for Verenigingen
Inspired by ERPNext's validation error patterns
"""

import frappe


class InvalidDuesRateError(frappe.ValidationError):
    """Raised when dues rate validation fails"""

    pass


class MembershipTypeMismatchError(frappe.ValidationError):
    """Raised when membership type consistency validation fails"""

    pass


class InvalidStatusTransitionError(frappe.ValidationError):
    """Raised when an invalid status transition is attempted"""

    pass


class BillingFrequencyConflictError(frappe.ValidationError):
    """Raised when billing frequency conflicts are detected"""

    pass


class DuplicateScheduleError(frappe.ValidationError):
    """Raised when attempting to create duplicate dues schedules"""

    pass


class ScheduleGenerationError(frappe.ValidationError):
    """Raised when invoice generation fails validation"""

    pass
