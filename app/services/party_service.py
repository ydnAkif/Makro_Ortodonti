"""Service layer for Party (Dentist/Customer) and WorkOrder domain logic."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict

from flask import abort

from app.constants import VAT_RATE
from app.extensions import db
from app.models.models import Makbuz, Party, PartyType, RATE_SCALE, WorkOrder, money
from app.services.validation_service import (
    normalize_display_name,
    normalize_optional_text,
    parse_date,
    parse_decimal,
)


class PartyService:

    @staticmethod
    def is_period_locked(party_id: int, year: int, month: int) -> bool:
        """Tahsilat hareketi bulunan dönemler finansal tutarlılık için kilitlidir."""
        summary = db.session.execute(
            db.select(Makbuz).where(
                Makbuz.party_id == party_id,
                Makbuz.year == year,
                Makbuz.month == month,
            )
        ).scalar_one_or_none()
        return bool(summary and (summary.payment_entries or summary.collected_amount > 0))

    @staticmethod
    def _refresh_period_summary(party: Party, year: int, month: int) -> None:
        """Varsa dönem özetini güncel iş emirleri ve doktor KDV tercihiyle yenile."""
        existing = db.session.execute(
            db.select(Makbuz).where(
                Makbuz.party_id == party.id,
                Makbuz.year == year,
                Makbuz.month == month,
            )
        ).scalar_one_or_none()
        if not existing:
            return

        from app.services.makbuz_service import generate_makbuz

        generate_makbuz(
            party.id,
            year,
            month,
            vat_applied=bool(party.applies_kdv),
            vat_rate=VAT_RATE if party.applies_kdv else Decimal("0.00"),
        )

    @staticmethod
    def get_party_or_404(party_id: int) -> Party:
        return db.get_or_404(Party, party_id)

    @staticmethod
    def get_work_order_or_404(party_id: int, wo_id: int) -> WorkOrder:
        """Fetch a work order and enforce it belongs to party_id.

        Without this check, a caller who supplies a valid wo_id that
        belongs to a *different* party bypasses that other party's
        period-lock check (the lock lookups below all key off the URL's
        party_id, not the work order's real owner).
        """
        wo = db.get_or_404(WorkOrder, wo_id)
        if wo.party_id != party_id:
            abort(404)
        return wo

    @classmethod
    def create_party(cls, form_data: Dict[str, Any]) -> Party:
        name = normalize_display_name(form_data.get("name", ""))
        if not name:
            raise ValueError("İsim alanı gereklidir.")

        party_type_str = form_data.get("party_type", PartyType.DENTIST.value)
        try:
            party_type = PartyType(party_type_str)
        except ValueError:
            party_type = PartyType.DENTIST

        party = Party(
            name=name,
            party_type=party_type,
            phone=normalize_optional_text(form_data.get("phone", "")),
            email=normalize_optional_text(form_data.get("email", "")),
            address=normalize_optional_text(form_data.get("address", "")),
            notes=normalize_optional_text(form_data.get("notes", "")),
            is_active=form_data.get("is_active") == "on" or form_data.get("is_active") is True,
            applies_kdv=form_data.get("applies_kdv") == "on" or form_data.get("applies_kdv") is True,
        )
        db.session.add(party)
        db.session.commit()
        return party

    @classmethod
    def update_party(cls, party_id: int, form_data: Dict[str, Any]) -> Party:
        party = cls.get_party_or_404(party_id)
        name = normalize_display_name(form_data.get("name", ""))
        if not name:
            raise ValueError("İsim alanı gereklidir.")

        party.name = name
        party.phone = normalize_optional_text(form_data.get("phone", ""))
        party.email = normalize_optional_text(form_data.get("email", ""))
        party.address = normalize_optional_text(form_data.get("address", ""))
        party.notes = normalize_optional_text(form_data.get("notes", ""))
        party.is_active = form_data.get("is_active") == "on" or form_data.get("is_active") is True
        party.applies_kdv = form_data.get("applies_kdv") == "on" or form_data.get("applies_kdv") is True

        db.session.commit()
        return party

    @classmethod
    def delete_party(cls, party_id: int) -> bool:
        party = cls.get_party_or_404(party_id)
        db.session.delete(party)
        db.session.commit()
        return True

    @staticmethod
    def _parse_work_order_money(form_data: Dict[str, Any]) -> tuple[Decimal, Decimal, Decimal | None]:
        """Parse apparatus/extra prices and the applied exchange rate.

        Uses parse_decimal (not parse_float) so entered values never make a
        string->float->Decimal round trip through binary floating point, and
        rejects negative prices — nothing upstream of this validated that.
        """
        apparatus_price = parse_decimal(form_data.get("apparatus_price", "0")) or Decimal("0.00")
        extra_price = parse_decimal(form_data.get("extra_price", "0")) or Decimal("0.00")
        if apparatus_price < 0 or extra_price < 0:
            raise ValueError("Aparey ve ekstra tutarları negatif olamaz.")

        rate = parse_decimal(form_data.get("exchange_rate_applied", ""), scale=str(RATE_SCALE))
        exchange_rate_applied = rate if rate and rate > 0 else None

        return apparatus_price, extra_price, exchange_rate_applied

    @classmethod
    def create_work_order(cls, party_id: int, form_data: Dict[str, Any]) -> WorkOrder:
        cls.get_party_or_404(party_id)
        work_date = parse_date(form_data.get("work_date", ""))
        if not work_date:
            raise ValueError("Geçersiz tarih.")

        apparatus_price, extra_price, exchange_rate_applied = cls._parse_work_order_money(form_data)

        wo = WorkOrder(
            party_id=party_id,
            work_date=work_date,
            apparatus_type=str(form_data.get("apparatus_type", "")).strip(),
            extra_addons=normalize_optional_text(form_data.get("extra_addons", "")),
            patient_name=normalize_display_name(form_data.get("patient_name", "")),
            apparatus_price=apparatus_price,
            extra_price=extra_price,
            total_price=money(apparatus_price + extra_price),
            exchange_rate_applied=exchange_rate_applied,
            notes=normalize_optional_text(form_data.get("notes", "")),
        )
        db.session.add(wo)
        db.session.flush()

        from app.services.makbuz_service import generate_makbuz
        party = cls.get_party_or_404(party_id)
        generate_makbuz(
            party_id,
            work_date.year,
            work_date.month,
            vat_applied=bool(party.applies_kdv),
            vat_rate=VAT_RATE if party.applies_kdv else Decimal("0.00"),
        )

        db.session.commit()
        return wo

    @classmethod
    def update_work_order(cls, party_id: int, wo_id: int, form_data: Dict[str, Any]) -> WorkOrder:
        cls.get_party_or_404(party_id)
        wo = cls.get_work_order_or_404(party_id, wo_id)

        work_date = parse_date(form_data.get("work_date", ""))
        if not work_date:
            raise ValueError("Geçersiz tarih.")

        if work_date != wo.work_date:
            if cls.is_period_locked(party_id, work_date.year, work_date.month):
                raise PermissionError("Hedef dönemde tahsilat hareketi bulunduğu için iş emri bu tarihe taşınamaz.")
        if cls.is_period_locked(party_id, wo.work_date.year, wo.work_date.month):
            raise PermissionError("Bu dönemde tahsilat hareketi bulunduğu için iş emri düzenlenemez. Önce tahsilat kaydını geri alın.")

        apparatus_price, extra_price, exchange_rate_applied = cls._parse_work_order_money(form_data)

        old_year, old_month = wo.work_date.year, wo.work_date.month
        wo.work_date = work_date
        wo.apparatus_type = str(form_data.get("apparatus_type", "")).strip()
        wo.extra_addons = normalize_optional_text(form_data.get("extra_addons", ""))
        wo.patient_name = normalize_display_name(form_data.get("patient_name", ""))
        wo.apparatus_price = apparatus_price
        wo.extra_price = extra_price
        wo.total_price = money(apparatus_price + extra_price)
        wo.exchange_rate_applied = exchange_rate_applied
        wo.notes = normalize_optional_text(form_data.get("notes", ""))

        db.session.flush()
        party = cls.get_party_or_404(party_id)
        cls._refresh_period_summary(party, old_year, old_month)
        if (work_date.year, work_date.month) != (old_year, old_month):
            cls._refresh_period_summary(party, work_date.year, work_date.month)
        db.session.commit()
        return wo

    @classmethod
    def delete_work_order(cls, party_id: int, wo_id: int) -> bool:
        wo = cls.get_work_order_or_404(party_id, wo_id)
        if cls.is_period_locked(party_id, wo.work_date.year, wo.work_date.month):
            raise PermissionError("Bu dönemde tahsilat hareketi bulunduğu için iş emri silinemez. Önce tahsilat kaydını geri alın.")

        year, month = wo.work_date.year, wo.work_date.month
        db.session.delete(wo)
        db.session.flush()
        party = cls.get_party_or_404(party_id)
        cls._refresh_period_summary(party, year, month)
        db.session.commit()
        return True
