"""Invoice number generation and management utilities."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional, List, Dict, Any

from sqlalchemy import Integer, cast, select, update

from app.models.models import (
    ExchangeRate, Invoice, InvoiceItem, InvoiceItemType,
    PatientTreatment, Settings, Treatment, Party, money,
)


def _normalize_item(item_data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize one invoice item before any database mutation."""
    normalized = dict(item_data)

    description = str(item_data.get("description", "")).strip()
    if not description:
        raise ValueError("Kalem açıklaması boş olamaz.")
    if len(description) > 300:
        raise ValueError("Kalem açıklaması 300 karakteri aşamaz.")

    quantity = item_data.get("quantity", 1)
    try:
        quantity = int(quantity)
    except (TypeError, ValueError) as exc:
        raise ValueError("Miktar tam sayı olmalıdır.") from exc
    if quantity <= 0:
        raise ValueError(f"Miktar sıfırdan büyük olmalıdır (girilen: {quantity}).")

    try:
        unit_price = money(item_data.get("unit_price_eur"))
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise ValueError("Birim fiyat sayısal olmalıdır.") from exc
    if not unit_price.is_finite() or unit_price < 0:
        raise ValueError(f"Birim fiyat negatif olamaz (girilen: {unit_price}).")

    try:
        vat_rate = money(item_data.get("vat_rate", 0))
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise ValueError("KDV oranı sayısal olmalıdır.") from exc
    if not vat_rate.is_finite() or not Decimal("0") <= vat_rate <= Decimal("100"):
        raise ValueError(f"KDV oranı 0 ile 100 arasında olmalıdır (girilen: {vat_rate}).")

    discount_type = item_data.get("discount_type") or None
    if discount_type not in {None, "percent", "amount"}:
        raise ValueError("İskonto tipi percent veya amount olmalıdır.")
    try:
        discount_value = money(item_data.get("discount_value", 0) or 0)
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise ValueError("İskonto değeri sayısal olmalıdır.") from exc
    if not discount_value.is_finite() or discount_value < 0:
        raise ValueError(f"İskonto değeri negatif olamaz (girilen: {discount_value}).")
    if discount_type == "percent" and discount_value > Decimal("100"):
        raise ValueError(f"Yüzde iskonto 100'ü aşamaz (girilen: {discount_value}).")
    if discount_type == "amount" and discount_value > unit_price * quantity:
        raise ValueError(
            f"Tutar iskontosu ({discount_value:.2f} €) satır tutarını "
            f"({unit_price * quantity:.2f} €) aşamaz."
        )

    item_type_value = str(item_data.get("item_type", "treatment")).lower()
    try:
        item_type = InvoiceItemType(item_type_value)
    except ValueError as exc:
        raise ValueError(f"Geçersiz fatura kalemi tipi: {item_type_value}.") from exc

    normalized.update(
        description=description,
        quantity=quantity,
        unit_price_eur=unit_price,
        vat_rate=vat_rate,
        discount_type=discount_type,
        discount_value=discount_value,
        item_type=item_type,
    )
    return normalized


class InvoiceService:

    @staticmethod
    def generate_invoice_number(session, invoice_date: Optional[date] = None) -> str:
        prefix = (
            session.execute(
                select(Settings.value).where(Settings.key == "invoice_prefix")
            ).scalar_one_or_none()
            or "MKR"
        )
        # Increment and return in one database statement. SQLite serializes this
        # write and PostgreSQL applies a row lock, so concurrent workers cannot
        # observe and reuse the same counter value.
        incremented = session.execute(
            update(Settings)
            .where(Settings.key == "invoice_next_number")
            .values(value=cast(Settings.value, Integer) + 1)
            .returning(Settings.value)
        ).scalar_one_or_none()
        if incremented is None:
            # A correctly migrated database always has this row. Keeping the
            # failure explicit prevents silently issuing duplicate numbers.
            raise RuntimeError("invoice_next_number ayarı bulunamadı.")

        next_num = int(incremented) - 1
        year = (invoice_date or date.today()).year
        invoice_number = f"{prefix}-{year}-{next_num:04d}"
        session.flush()

        return invoice_number

    @staticmethod
    def get_exchange_rate(session, target_date: Optional[date] = None) -> float:
        target_date = target_date or date.today()
        rate = session.execute(
            select(ExchangeRate)
            .where(ExchangeRate.rate_date <= target_date)
            .order_by(ExchangeRate.rate_date.desc())
            .limit(1)
        ).scalar_one_or_none()
        if rate is None:
            raise ValueError(
                f"No exchange rate found for date {target_date}. "
                "Please add an exchange rate first."
            )
        return rate.eur_to_try

    @staticmethod
    def create_invoice(
        session,
        party_id: int,
        items: List[Dict[str, Any]],
        invoice_date: Optional[date] = None,
        due_date: Optional[date] = None,
        notes: Optional[str] = None,
    ) -> Invoice:
        """
        Create an invoice with flexible items.
        
        items: List of dicts with keys:
            - item_type: InvoiceItemType (treatment, product, service, lab, custom)
            - treatment_id: int (required if item_type == treatment)
            - reference_id: int (for product/service/lab reference)
            - description: str
            - quantity: int (default 1)
            - unit_price_eur: float
            - vat_rate: float (default 0)
            - discount_type: str (percent/amount, optional)
            - discount_value: float (default 0)
        """
        if not items:
            raise ValueError("Fatura en az bir kalem içermelidir.")

        party = session.get(Party, party_id)
        if party is None:
            raise ValueError(f"Müşteri bulunamadı (id={party_id}).")

        normalized_items = [_normalize_item(item_data) for item_data in items]
        for item_data in normalized_items:
            if item_data["item_type"] == InvoiceItemType.TREATMENT:
                treatment_id = item_data.get("treatment_id")
                treatment = session.get(Treatment, treatment_id) if treatment_id else None
                if treatment is None:
                    raise ValueError("Tedavi kalemi için geçerli bir tedavi seçilmelidir.")

        invoice_date = invoice_date or date.today()
        rate = InvoiceService.get_exchange_rate(session, invoice_date)
        invoice_number = InvoiceService.generate_invoice_number(session, invoice_date)

        invoice = Invoice(
            party_id=party_id,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            due_date=due_date,
            exchange_rate=rate,
            notes=notes,
        )
        session.add(invoice)
        session.flush()

        for item_data in normalized_items:
            item_type = item_data["item_type"]
            unit_eur = item_data["unit_price_eur"]
            unit_try = money(unit_eur * rate)
            
            item = InvoiceItem(
                invoice_id=invoice.id,
                item_type=item_type,
                treatment_id=item_data.get("treatment_id"),
                reference_id=item_data.get("reference_id"),
                description=item_data["description"],
                quantity=item_data.get("quantity", 1),
                unit_price_eur=unit_eur,
                unit_price_try=unit_try,
                vat_rate=item_data.get("vat_rate", 0.0),
                discount_type=item_data.get("discount_type"),
                discount_value=item_data.get("discount_value", 0.0),
            )
            session.add(item)

        session.flush()
        invoice.recalculate_totals()
        session.commit()

        return invoice

    @staticmethod
    def create_invoice_from_treatments(
        session,
        party_id: int,
        treatment_ids: list[int],
        invoice_date: Optional[date] = None,
        due_date: Optional[date] = None,
        notes: Optional[str] = None,
    ) -> Invoice:
        """Legacy method for backward compatibility - create invoice from patient treatments."""
        invoice_date = invoice_date or date.today()
        rate = InvoiceService.get_exchange_rate(session, invoice_date)
        invoice_number = InvoiceService.generate_invoice_number(session, invoice_date)

        invoice = Invoice(
            party_id=party_id,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            due_date=due_date,
            exchange_rate=rate,
            notes=notes,
        )
        session.add(invoice)
        session.flush()

        for tid in treatment_ids:
            pt = session.get(PatientTreatment, tid)
            if pt is None:
                raise ValueError(f"PatientTreatment {tid} not found")
            treatment = pt.treatment
            unit_eur = pt.effective_price_eur
            unit_try = money(unit_eur * rate)

            item = InvoiceItem(
                invoice_id=invoice.id,
                item_type=InvoiceItemType.TREATMENT,
                treatment_id=treatment.id,
                description=treatment.name,
                quantity=1,
                unit_price_eur=unit_eur,
                unit_price_try=unit_try,
            )
            session.add(item)

        session.flush()
        invoice.recalculate_totals()
        session.commit()

        return invoice
