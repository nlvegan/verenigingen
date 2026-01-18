# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Member Payment Services Package.

This package provides payment-related services for member management, extracted
from the PaymentMixin to improve maintainability and testability.

Services (READ focus):
    - PaymentHistoryService: Batched payment history loading (96% query reduction)
    - PaymentCoverageService: Coverage date extraction from schedules/invoices

Related Components (WRITE focus - in utils/):
    - MemberFinancialHistoryManager: Atomic single-entry add/update/remove
    - FinancialHistoryBatchProcessor: Queues updates for 10s batch processing

Architecture Overview:
    READ PATH (display):
        payment_mixin._load_payment_history_batched()
            → PaymentHistoryService.load_payment_history_batched()
                → 3 batch queries (96% reduction from 81 N+1 queries)

    WRITE PATH (updates):
        payment_mixin.add_invoice_to_payment_history()
            → queue_payment_update() [batch processor]
                → MemberFinancialHistoryManager.add_or_update_entry()

Query Optimization:
    Original pattern (N+1): 81 queries for typical member
    Optimized pattern (batch): 3 queries regardless of invoice count

Usage:
    from verenigingen.services.member.payment import get_payment_history_service

    service = get_payment_history_service()
    result = service.load_payment_history_batched(member_doc)
"""

from verenigingen.services.member.payment.payment_coverage_service import (
    PaymentCoverageService,
    get_payment_coverage_service,
)
from verenigingen.services.member.payment.payment_history_service import (
    PaymentHistoryService,
    get_payment_history_service,
)

__all__ = [
    "PaymentHistoryService",
    "get_payment_history_service",
    "PaymentCoverageService",
    "get_payment_coverage_service",
]
