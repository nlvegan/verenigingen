# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto API Handlers

This module contains the API endpoints for Ponto integration,
including webhook handlers.
"""

from verenigingen.verenigingen_payments.ponto.api.webhook import handle_ponto_webhook

__all__ = [
    "handle_ponto_webhook",
]
