"""Service layer for Party (Dentist/Customer) and WorkOrder domain logic."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from app.extensions import db
from app.models.models import Makbuz, Party, PartyType, TreatmentCategory, WorkOrder
from app.services.search_service import tr_fold, tr_order
from app.services.validation_service import (
    normalize_display_name,
    normalize_optional_text,
    parse_date,
    parse_float,
)


class PartyService:

    @staticmethod
    def is_period_locked(party_id: int, year: int, month: int) -> bool:
        """Return True if the given period has a non-draft makbuz (sent or paid)."""
        return db.session.execute(
            db.select(Makbuz).where(
                Makbuz.party_id == party_id,
                Makbuz.year == year,
                Makbuz.month == month,
                Makbuz.status != Makbuz.STATUS_DRAFT,
            )
        ).scalar_one_or_none() is not None

    @staticmethod
    def get_party_or_404(party_id: int) -> Party:
        return db.get_or_404(Party, party_id)

    @staticmethod
    def get_work_order_or_404(wo_id: int) -> WorkOrder:
        return db.get_or_404(WorkOrder, wo_id)

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

        db.session.commit()
        return party

    @classmethod
    def delete_party(cls, party_id: int) -> bool:
        party = cls.get_party_or_404(party_id)
        db.session.delete(party)
        db.session.commit()
        return True

    @classmethod
    def create_work_order(cls, party_id: int, form_data: Dict[str, Any]) -> WorkOrder:
        party = cls.get_party_or_404(party_id)
        work_date = parse_date(form_data.get("work_date", ""))
        if not work_date:
            raise ValueError("Geçersiz tarih.")

        if cls.is_period_locked(party_id, work_date.year, work_date.month):
            raise PermissionError("Bu döneme ait makbuz kesinleştirildiği/ödendiği için iş emri eklenemez.")

        apparatus_price = Decimal(str(parse_float(form_data.get("apparatus_price", "0")) or 0))
        extra_price = Decimal(str(parse_float(form_data.get("extra_price", "0")) or 0))
        rate_val = parse_float(form_data.get("exchange_rate_applied", ""))
        exchange_rate_applied = Decimal(str(rate_val)) if rate_val else None

        wo = WorkOrder(
            party_id=party_id,
            work_date=work_date,
            apparatus_type=str(form_data.get("apparatus_type", "")).strip(),
            extra_addons=normalize_optional_text(form_data.get("extra_addons", "")),
            patient_name=normalize_display_name(form_data.get("patient_name", "")),
            apparatus_price=apparatus_price,
            extra_price=extra_price,
            total_price=apparatus_price + extra_price,
            exchange_rate_applied=exchange_rate_applied,
            notes=normalize_optional_text(form_data.get("notes", "")),
        )
        db.session.add(wo)
        db.session.flush()

        from app.services.makbuz_service import generate_makbuz
        try:
            generate_makbuz(party_id, work_date.year, work_date.month, vat_applied=False, vat_rate=Decimal("0"))
        except ValueError:
            pass

        db.session.commit()
        return wo

    @classmethod
    def update_work_order(cls, party_id: int, wo_id: int, form_data: Dict[str, Any]) -> WorkOrder:
        party = cls.get_party_or_404(party_id)
        wo = cls.get_work_order_or_404(wo_id)

        work_date = parse_date(form_data.get("work_date", ""))
        if not work_date:
            raise ValueError("Geçersiz tarih.")

        if work_date != wo.work_date:
            if cls.is_period_locked(party_id, work_date.year, work_date.month):
                raise PermissionError("Hedef döneme ait makbuz kesinleştirildiği için iş emri bu tarihe taşınamaz.")
        if cls.is_period_locked(party_id, wo.work_date.year, wo.work_date.month):
            raise PermissionError("Bu döneme ait makbuz kesinleştirildiği/ödendiği için iş emri düzenlenemez.")

        apparatus_price = Decimal(str(parse_float(form_data.get("apparatus_price", "0")) or 0))
        extra_price = Decimal(str(parse_float(form_data.get("extra_price", "0")) or 0))
        rate_val = parse_float(form_data.get("exchange_rate_applied", ""))
        exchange_rate_applied = Decimal(str(rate_val)) if rate_val else None

        wo.work_date = work_date
        wo.apparatus_type = str(form_data.get("apparatus_type", "")).strip()
        wo.extra_addons = normalize_optional_text(form_data.get("extra_addons", ""))
        wo.patient_name = normalize_display_name(form_data.get("patient_name", ""))
        wo.apparatus_price = apparatus_price
        wo.extra_price = extra_price
        wo.total_price = apparatus_price + extra_price
        wo.exchange_rate_applied = exchange_rate_applied
        wo.notes = normalize_optional_text(form_data.get("notes", ""))

        db.session.commit()
        return wo

    @classmethod
    def delete_work_order(cls, party_id: int, wo_id: int) -> bool:
        wo = cls.get_work_order_or_404(wo_id)
        if cls.is_period_locked(party_id, wo.work_date.year, wo.work_date.month):
            raise PermissionError("Bu döneme ait makbuz kesinleştirildiği/ödendiği için iş emri silinemez.")

        db.session.delete(wo)
        db.session.commit()
        return True
