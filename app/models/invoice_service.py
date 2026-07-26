"""Backward-compatibility shim — real module moved to app.services.invoice_service."""
from app.services.invoice_service import *  # noqa: F401,F403
from app.services.invoice_service import InvoiceService  # noqa: F401
