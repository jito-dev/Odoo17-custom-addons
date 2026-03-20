from typing import List, Optional

from pydantic import BaseModel, Field


class InvoiceLineExtraction(BaseModel):
    """Structured data for a single invoice line."""
    description: str = Field(
        description="Description or name of the product/service."
    )
    quantity: float = Field(
        default=1.0,
        description="Quantity of items. Default 1.0 if not specified.",
    )
    unit_price: float = Field(
        description="Price per unit (excluding tax).",
    )
    tax_percent: Optional[float] = Field(
        default=None,
        description="Tax rate as a percentage (e.g., 20.0 for 20%). "
                    "Null if no tax or not determinable.",
    )


class InvoiceExtraction(BaseModel):
    """Structured data extracted from an invoice/bill PDF."""
    vendor_name: Optional[str] = Field(
        default=None,
        description="Full legal name of the vendor/supplier.",
    )
    vendor_vat: Optional[str] = Field(
        default=None,
        description="Vendor's VAT/Tax ID number (e.g., 'LT100001234').",
    )
    invoice_number: Optional[str] = Field(
        default=None,
        description="Invoice number or reference from the vendor.",
    )
    invoice_date: Optional[str] = Field(
        default=None,
        description="Invoice issue date in YYYY-MM-DD format.",
    )
    due_date: Optional[str] = Field(
        default=None,
        description="Payment due date in YYYY-MM-DD format.",
    )
    currency: Optional[str] = Field(
        default=None,
        description="ISO 4217 currency code (e.g., 'EUR', 'USD').",
    )
    payment_reference: Optional[str] = Field(
        default=None,
        description="Payment reference or structured communication.",
    )
    total_amount: Optional[float] = Field(
        default=None,
        description="Total invoice amount including tax.",
    )
    subtotal_amount: Optional[float] = Field(
        default=None,
        description="Subtotal amount before tax.",
    )
    total_tax_amount: Optional[float] = Field(
        default=None,
        description="Total tax amount.",
    )
    lines: List[InvoiceLineExtraction] = Field(
        default_factory=list,
        description="List of invoice line items.",
    )


INVOICE_EXTRACTION_PROMPT = """You are an expert invoice data extraction assistant.
Analyze the uploaded invoice/bill document and extract all available data into the structured format.

Rules:
- Return null for any field you cannot find or confidently determine.
- Dates must be in YYYY-MM-DD format.
- Currency must be an ISO 4217 code (EUR, USD, GBP, etc.).
- VAT numbers should include the country prefix (e.g., LT100001234, DE123456789).
- For line items, extract each distinct product/service line.
- unit_price should be the price per unit BEFORE tax.
- tax_percent should be the tax rate as a number (e.g., 21.0 for 21% VAT).
- If the invoice shows only totals without individual lines, create a single line with the subtotal.
- Be precise with numbers — do not round amounts.
"""
