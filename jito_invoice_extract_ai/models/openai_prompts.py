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


class BankAccountExtraction(BaseModel):
    """Bank account details found on the invoice."""
    iban: Optional[str] = Field(
        default=None,
        description="Full IBAN number (e.g., 'LT123456789012345678'). "
                    "Remove spaces but keep all characters.",
    )
    bic_swift: Optional[str] = Field(
        default=None,
        description="BIC/SWIFT code (e.g., 'REVOLT21').",
    )
    bank_name: Optional[str] = Field(
        default=None,
        description="Name of the bank.",
    )
    account_holder: Optional[str] = Field(
        default=None,
        description="Account holder name, only if different from the vendor name.",
    )


class VendorExtraction(BaseModel):
    """Full vendor/supplier details extracted from the invoice."""
    name: Optional[str] = Field(
        default=None,
        description="Full legal name of the vendor/supplier company.",
    )
    vat: Optional[str] = Field(
        default=None,
        description="VAT/Tax ID number with country prefix (e.g., 'LT100001234', 'DE123456789').",
    )
    street: Optional[str] = Field(
        default=None,
        description="Street address line 1.",
    )
    street2: Optional[str] = Field(
        default=None,
        description="Street address line 2 (apartment, suite, floor, etc.).",
    )
    city: Optional[str] = Field(
        default=None,
        description="City name.",
    )
    zip_code: Optional[str] = Field(
        default=None,
        description="Postal/ZIP code.",
    )
    state: Optional[str] = Field(
        default=None,
        description="State, province, or region name.",
    )
    country: Optional[str] = Field(
        default=None,
        description="Country as ISO 3166-1 alpha-2 code (e.g., 'LT', 'DE', 'US'). "
                    "If the code is not obvious, use the full country name.",
    )
    email: Optional[str] = Field(
        default=None,
        description="Vendor email address.",
    )
    phone: Optional[str] = Field(
        default=None,
        description="Vendor phone number (landline). Include country code if shown.",
    )
    mobile: Optional[str] = Field(
        default=None,
        description="Vendor mobile number, only if listed separately from phone.",
    )
    website: Optional[str] = Field(
        default=None,
        description="Vendor website URL.",
    )
    bank_accounts: List[BankAccountExtraction] = Field(
        default_factory=list,
        description="Bank account details found on the invoice (IBAN, BIC, bank name).",
    )


class InvoiceExtraction(BaseModel):
    """Structured data extracted from an invoice/bill PDF."""
    vendor: Optional[VendorExtraction] = Field(
        default=None,
        description="Full vendor/supplier details including address, contact info, and bank accounts.",
    )
    invoice_number: Optional[str] = Field(
        default=None,
        description="The vendor's invoice/bill number (e.g., 'INV-2024-0042', 'FA-00123', '#1057'). "
                    "This is the document identifier assigned by the vendor, NOT the vendor name, "
                    "NOT the customer name, NOT a description of services. "
                    "Look for labels like 'Invoice No', 'Invoice #', 'Bill Number', 'Document Number'. "
                    "Return null if no clear invoice number is found.",
    )
    invoice_date: Optional[str] = Field(
        default=None,
        description="Invoice issue date in YYYY-MM-DD format. "
                    "Look for 'Invoice Date', 'Date', 'Issue Date', etc.",
    )
    due_date: Optional[str] = Field(
        default=None,
        description="Payment due date in YYYY-MM-DD format. "
                    "Look for 'Due Date', 'Payment Due', 'Pay by', etc. "
                    "If payment terms are specified (e.g., 'Net 30'), calculate from invoice_date.",
    )
    currency: Optional[str] = Field(
        default=None,
        description="ISO 4217 currency code (e.g., 'EUR', 'USD').",
    )
    payment_reference: Optional[str] = Field(
        default=None,
        description="Payment reference for bank transfer — a code the vendor asks you to include "
                    "when making payment (e.g., structured communication, payment code, reference number). "
                    "This is NOT the invoice number. Look for labels like 'Payment Reference', "
                    "'Communication', 'Reference for payment', 'Verwendungszweck'. "
                    "If no explicit payment reference is found, generate one as: "
                    "'<vendor_name> - <invoice_number>' (e.g., 'Acme Corp - INV-2024-0042'). "
                    "Never return null — always provide a meaningful reference.",
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

General rules:
- Return null for any field you cannot find or confidently determine.
- Dates must be in YYYY-MM-DD format.
- Currency must be an ISO 4217 code (EUR, USD, GBP, etc.).

Dates:
- invoice_date: The date the invoice was issued. Look for labels like "Invoice Date", "Date",
  "Issue Date", "Sąskaitos data", "Datum", "Rechnungsdatum".
- due_date: The date by which payment must be made. Look for labels like "Due Date",
  "Payment Due", "Apmokėti iki", "Fälligkeitsdatum", "Date d'échéance".
  If the invoice specifies payment terms (e.g., "Net 30", "14 days"), calculate the due date
  from the invoice date. Always try to extract or derive a due date.

Invoice number & payment reference:
- invoice_number is the DOCUMENT IDENTIFIER assigned by the vendor (e.g., INV-2024-0042, #1057).
  It is NOT the vendor name, NOT the customer/buyer name, NOT a service description.
  Look for labels: "Invoice No", "Invoice #", "Bill Number", "Nr.", "Sąskaitos Nr.".
  Return null if you cannot find a clear invoice number.
- payment_reference is a code for bank transfers. If the invoice specifies one explicitly,
  use it. Otherwise, generate: "<vendor_name> - <invoice_number>" as a meaningful reference.
  Never return null for payment_reference.

Vendor details:
- Extract the full vendor/supplier company name, address, and contact information.
- VAT numbers should include the country prefix (e.g., LT100001234, DE123456789).
- Country should be an ISO 3166-1 alpha-2 code (e.g., LT, DE, US, GB) when possible.
- Extract email, phone, mobile, and website if shown on the invoice.
- If the vendor has multiple phone numbers, put the landline in phone and mobile number in mobile.

Bank account details:
- Extract all bank accounts shown on the invoice (there may be multiple).
- IBAN should be the full number without spaces.
- BIC/SWIFT code if shown.
- Bank name if shown.

Invoice lines:
- Extract each distinct product/service line.
- unit_price should be the price per unit BEFORE tax.
- tax_percent should be the tax rate as a number (e.g., 21.0 for 21% VAT).
- If the invoice shows only totals without individual lines, create a single line with the subtotal.
- Be precise with numbers — do not round amounts.
"""
