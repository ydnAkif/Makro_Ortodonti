"""Muhasebe raporlama servisi — TRY merkezli, kapsamlı finansal analiz."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from flask import has_app_context
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models.models import (
    ExchangeRate,
    Invoice,
    InvoiceItem,
    Makbuz,
    Party,
    PartyType,
    Payment,
    TreatmentCategory,
    WorkOrder,
    money,
)
from app.services.exchange_service import get_rate_for_date

from app.constants import MONTH_NAMES

logger = logging.getLogger(__name__)

VAT_RATES = [
    (Decimal("0"), "%0 (Muaf)"),
    (Decimal("1"), "%1"),
    (Decimal("10"), "%10"),
    (Decimal("20"), "%20"),
]


def _resolve_rate(work_date: date, applied: Decimal | None) -> Decimal:
    """Return the effective EUR→TRY rate for a work order.

    Falls back to 1:1 only when no rate can be found at all (no rate
    recorded on the work order and no ExchangeRate row on or before its
    date). That fallback silently understates TRY figures reported as EUR,
    so it's logged loudly rather than swallowed — this should never
    actually fire once the exchange-rate cron/auto-fetch is running.
    """
    rate = applied if applied and applied > 0 else None
    if not rate:
        obj = get_rate_for_date(work_date)
        rate = obj.eur_to_try if obj else None
    if rate and rate > 0:
        return rate
    logger.warning(
        "Kur bulunamadı, %s tarihli iş emri için 1:1 varsayılan kur kullanılıyor "
        "— rapor tutarları yanlış olabilir.",
        work_date,
    )
    return Decimal("1")


def _parse_wo_items(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        items = json.loads(raw)
        if isinstance(items, list):
            return [i for i in items if isinstance(i, dict)]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _wo_to_try(wo: WorkOrder) -> Decimal:
    """WorkOrder toplamını TL'ye çevir."""
    return money(wo.total_price)


def _wo_to_eur(wo: WorkOrder) -> Decimal:
    """WorkOrder toplamını EUR'ya çevir."""
    rate = _resolve_rate(wo.work_date, wo.exchange_rate_applied)
    return money(wo.total_price / rate)


# ---------------------------------------------------------------------------
# Period resolution
# ---------------------------------------------------------------------------

def resolve_period(today: date, period: str, start_str: str, end_str: str) -> tuple[date, date, str]:
    from app.services.validation_service import parse_date

    explicit_start = parse_date(start_str)
    explicit_end = parse_date(end_str)

    if period == "custom" and (explicit_start or explicit_end):
        start = explicit_start or today.replace(month=1, day=1)
        end = explicit_end or today
        period = "custom"
    elif period == "last_30":
        start, end = today - timedelta(days=29), today
    elif period == "this_year":
        start, end = today.replace(month=1, day=1), today
    elif period == "last_year":
        start = today.replace(year=today.year - 1, month=1, day=1)
        end = today.replace(year=today.year - 1, month=12, day=31)
    elif period == "daily":
        start = end = today
    elif period == "monthly":
        start, end = today.replace(day=1), today
    else:
        period = "this_month"
        start, end = today.replace(day=1), today

    if start > end:
        start, end = end, start
    return start, end, period


# ---------------------------------------------------------------------------
# Dataclasses for report results
# ---------------------------------------------------------------------------

@dataclass
class DoctorSummary:
    party_id: int
    doctor_name: str
    work_order_count: int = 0
    total_try: Decimal = Decimal("0.00")
    total_eur: Decimal = Decimal("0.00")
    makbuz_count: int = 0
    makbuz_total_try: Decimal = Decimal("0.00")
    collected_try: Decimal = Decimal("0.00")
    outstanding_try: Decimal = Decimal("0.00")
    previous_debt: Decimal = Decimal("0.00")


@dataclass
class PeriodOverview:
    start_date: date
    end_date: date
    issued_try: Decimal = Decimal("0.00")
    collected_try: Decimal = Decimal("0.00")
    outstanding_try: Decimal = Decimal("0.00")
    overdue_try: Decimal = Decimal("0.00")
    receivable_count: int = 0
    collection_ratio: Decimal = Decimal("0")
    work_order_count: int = 0
    makbuz_count: int = 0
    payment_count: int = 0


@dataclass
class AgingBucket:
    label: str
    count: int = 0
    amount: Decimal = Decimal("0.00")


@dataclass
class TreatmentStat:
    name: str
    category: str
    count: int = 0
    amount_try: Decimal = Decimal("0.00")


@dataclass
class CategoryStat:
    category: str
    count: int = 0
    amount_try: Decimal = Decimal("0.00")


@dataclass
class VATSummary:
    rate: Decimal
    label: str
    gross: Decimal = Decimal("0.00")
    vat_amount: Decimal = Decimal("0.00")
    net: Decimal = Decimal("0.00")


@dataclass
class DailyRow:
    date: date
    label: str
    issued_try: Decimal = Decimal("0.00")
    collected_try: Decimal = Decimal("0.00")
    work_order_count: int = 0


@dataclass
class DoctorDetailReport:
    doctor: DoctorSummary
    work_orders: list[dict] = field(default_factory=list)
    makbuzlar: list[dict] = field(default_factory=list)
    aging: list[AgingBucket] = field(default_factory=list)
    total_outstanding: Decimal = Decimal("0.00")
    previous_debt: Decimal = Decimal("0.00")


# ---------------------------------------------------------------------------
# Core report builders
# ---------------------------------------------------------------------------

def build_period_overview(
    start_date: date,
    end_date: date,
    invoices: list[Invoice],
    payments: list[Payment],
    work_orders: list[WorkOrder],
    makbuzlar: list[Makbuz],
    all_makbuzlar: list[Makbuz],
    receivable_invoices: list[Invoice] | None = None,
) -> PeriodOverview:
    """Dönem genel bakış — faturalandırma, tahsilat, açık bakiye."""
    overview = PeriodOverview(start_date=start_date, end_date=end_date)

    # --- İş emirleri (TRY) ---
    for wo in work_orders:
        overview.issued_try += money(wo.total_price)
    overview.work_order_count = len(work_orders)

    # --- Legacy invoices (in-period) ---
    for inv in invoices:
        overview.issued_try += money(inv.total_try)
    for pmt in payments:
        overview.collected_try += money(pmt.amount_try)
    overview.payment_count += len(payments)

    # --- Makbuzlar (in-period) ---
    for m in makbuzlar:
        if m.affects_balance:
            overview.makbuz_count += 1
            overview.issued_try += money(m.grand_total)

    # --- Tahsilat (makbuz payment_entries in-period) ---
    for m in all_makbuzlar:
        if m.payment_entries:
            for entry in m.payment_entries:
                if start_date <= entry.payment_date <= end_date:
                    overview.collected_try += money(entry.amount)
                    overview.payment_count += 1
        elif m.paid_at and m.paid_amount:
            if start_date <= m.paid_at <= end_date:
                overview.collected_try += money(m.paid_amount)
                overview.payment_count += 1

    # --- Açık bakiye: TÜM dönemlerden kalan borç (sadece makbuzlar) ---
    for m in all_makbuzlar:
        m_date = date(m.year, m.month, 1)
        if m_date > end_date:
            continue
        if not m.affects_balance:
            continue
        remaining = m.outstanding_amount
        if remaining > Decimal("0.01"):
            overview.outstanding_try += remaining
            overview.receivable_count += 1

    # Legacy invoices kalan bakiye
    if receivable_invoices is None:
        receivable_invoices = []
    for inv in receivable_invoices:
        paid_try = sum(
            pmt.amount_try for pmt in inv.payments if pmt.payment_date <= end_date
        )
        remaining = max(inv.total_try - paid_try, Decimal("0.00"))
        if remaining > Decimal("0.01"):
            overview.outstanding_try += remaining
            overview.receivable_count += 1

    if overview.issued_try > 0:
        overview.collection_ratio = (overview.collected_try / overview.issued_try * 100).quantize(Decimal("0.1"))
    return overview


def build_doctor_summaries(
    start_date: date,
    end_date: date,
    work_orders: list[WorkOrder],
    all_makbuzlar: list[Makbuz],
) -> list[DoctorSummary]:
    """Doktor bazlı özet rapor."""
    doctors: dict[int, DoctorSummary] = {}

    def _get(pid: int, name: str) -> DoctorSummary:
        if pid not in doctors:
            doctors[pid] = DoctorSummary(party_id=pid, doctor_name=name)
        return doctors[pid]

    for wo in work_orders:
        d = _get(wo.party_id, wo.party.name if wo.party else "Bilinmeyen")
        d.work_order_count += 1
        d.total_try += money(wo.total_price)
        d.total_eur += _wo_to_eur(wo)

    for m in all_makbuzlar:
        m_date = date(m.year, m.month, 1)
        if m.month == 12:
            m_end = date(m.year + 1, 1, 1) - timedelta(days=1)
        else:
            m_end = date(m.year, m.month + 1, 1) - timedelta(days=1)

        if m_date > end_date or m_end < start_date:
            continue
        if not m.affects_balance:
            continue

        d = _get(m.party_id, m.party.name if m.party else "Bilinmeyen")
        d.makbuz_count += 1
        d.makbuz_total_try += money(m.grand_total)
        d.collected_try += money(m.collected_amount)
        d.outstanding_try += money(m.outstanding_amount)

    # Devreden borçlar (dönem öncesi)
    for m in all_makbuzlar:
        m_date = date(m.year, m.month, 1)
        if m_date >= start_date:
            continue
        if not m.affects_balance:
            continue
        outstanding = m.outstanding_amount
        if outstanding > 0:
            d = _get(m.party_id, m.party.name if m.party else "Bilinmeyen")
            d.previous_debt += outstanding

    # Önceden devreden borçlar (party.previous_balance)
    if has_app_context():
        all_parties = db.session.execute(db.select(Party).where(Party.party_type == PartyType.DENTIST)).scalars().all()
        for p in all_parties:
            prev = p.previous_balance_outstanding
            if prev > 0:
                d = _get(p.id, p.name)
                d.previous_debt += prev
                d.outstanding_try += prev

    return sorted(doctors.values(), key=lambda d: (d.outstanding_try, d.total_try), reverse=True)


def build_aging_buckets(
    end_date: date,
    all_makbuzlar: list[Makbuz],
    receivable_invoices: list[Invoice] | None = None,
) -> list[AgingBucket]:
    """Vadesine göre açık alacaklar — makbuzlar, faturalar ve devreden borçlar."""
    buckets = [
        AgingBucket(label="Vadesi henüz gelmedi"),
        AgingBucket(label="1–30 gün gecikmiş"),
        AgingBucket(label="31–60 gün gecikmiş"),
        AgingBucket(label="61–90 gün gecikmiş"),
        AgingBucket(label="91+ gün gecikmiş"),
    ]

    def _bucket_idx(due: date) -> int:
        age_days = (end_date - due).days
        if age_days <= 0:
            return 0
        elif age_days <= 30:
            return 1
        elif age_days <= 60:
            return 2
        elif age_days <= 90:
            return 3
        return 4

    for m in all_makbuzlar:
        if not m.affects_balance:
            continue
        remaining = m.outstanding_amount
        if remaining <= Decimal("0.01"):
            continue

        if m.month == 12:
            due = date(m.year + 1, 1, 15)
        else:
            due = date(m.year, m.month + 1, 15)

        idx = _bucket_idx(due)
        buckets[idx].count += 1
        buckets[idx].amount += remaining

    # Legacy invoices aging
    if receivable_invoices:
        for inv in receivable_invoices:
            paid_try = sum(
                pmt.amount_try for pmt in inv.payments if pmt.payment_date <= end_date
            )
            remaining = max(inv.total_try - paid_try, Decimal("0.00"))
            if remaining <= Decimal("0.01"):
                continue
            due_reference = inv.due_date or inv.invoice_date
            idx = _bucket_idx(due_reference)
            buckets[idx].count += 1
            buckets[idx].amount += remaining

    # Önceden devreden borçlar (party.previous_balance) -> 91+ gün gecikmiş
    if has_app_context():
        all_parties = db.session.execute(db.select(Party).where(Party.party_type == PartyType.DENTIST)).scalars().all()
        for p in all_parties:
            prev = p.previous_balance_outstanding
            if prev > 0:
                buckets[4].count += 1
                buckets[4].amount += prev

    return buckets


def build_treatment_stats(work_orders: list[WorkOrder]) -> list[TreatmentStat]:
    """İşlem bazlı üretim istatistikleri (TRY)."""
    totals: dict[str, TreatmentStat] = {}

    for wo in work_orders:
        for raw_items, cat in [
            (wo.apparatus_type, TreatmentCategory.ANA_ISLEMLER),
            (wo.extra_addons, TreatmentCategory.EKSTRA_ISLEMLER),
        ]:
            items = _parse_wo_items(raw_items)
            if not items:
                continue
            for item in items:
                name = item.get("name", "Diğer")
                key = f"{cat}:{name}"
                if key not in totals:
                    totals[key] = TreatmentStat(name=name, category=cat)
                totals[key].count += 1
                price = Decimal(str(item.get("price") or 0))
                totals[key].amount_try += money(price)

    return sorted(totals.values(), key=lambda s: s.amount_try, reverse=True)[:20]


def build_category_stats(work_orders: list[WorkOrder]) -> list[CategoryStat]:
    """Kategori bazlı dağılım."""
    totals: dict[str, CategoryStat] = {}
    for wo in work_orders:
        for raw_items, cat in [
            (wo.apparatus_type, TreatmentCategory.ANA_ISLEMLER),
            (wo.extra_addons, TreatmentCategory.EKSTRA_ISLEMLER),
        ]:
            items = _parse_wo_items(raw_items)
            if not items:
                continue
            if cat not in totals:
                totals[cat] = CategoryStat(category=cat)
            totals[cat].count += len(items)
            for item in items:
                totals[cat].amount_try += money(Decimal(str(item.get("price") or 0)))
    return sorted(totals.values(), key=lambda s: s.amount_try, reverse=True)


def build_vat_summary(makbuzlar: list[Makbuz]) -> list[VATSummary]:
    """KDV özeti — orana göre kırılım."""
    summaries: dict[Decimal, VATSummary] = {}
    for m in makbuzlar:
        if not m.affects_balance:
            continue
        rate = m.vat_rate if m.vat_applied else Decimal("0")
        if rate not in summaries:
            label = dict(VAT_RATES).get(rate, f"%{rate}")
            summaries[rate] = VATSummary(rate=rate, label=label)
        summaries[rate].gross += money(m.subtotal)
        summaries[rate].vat_amount += money(m.vat_amount)
        summaries[rate].net += money(m.subtotal)
    return sorted(summaries.values(), key=lambda s: s.rate)


def build_daily_rows(
    start_date: date,
    end_date: date,
    work_orders: list[WorkOrder],
    all_makbuzlar: list[Makbuz],
) -> list[DailyRow]:
    """Günlük hareket dökümü."""
    day_span = (end_date - start_date).days + 1
    if day_span > 366:
        return []

    rows: dict[date, DailyRow] = {}
    for d_offset in range(day_span):
        d = start_date + timedelta(days=d_offset)
        rows[d] = DailyRow(date=d, label=d.strftime("%d.%m.%Y"))

    for wo in work_orders:
        if wo.work_date in rows:
            rows[wo.work_date].issued_try += money(wo.total_price)
            rows[wo.work_date].work_order_count += 1

    for m in all_makbuzlar:
        if m.payment_entries:
            for entry in m.payment_entries:
                if entry.payment_date in rows:
                    rows[entry.payment_date].collected_try += money(entry.amount)
        elif m.paid_at and m.paid_amount:
            if m.paid_at in rows:
                rows[m.paid_at].collected_try += money(m.paid_amount)

    return [rows[d] for d in sorted(rows)]


def build_monthly_trend(
    start_date: date,
    end_date: date,
    work_orders: list[WorkOrder],
    all_makbuzlar: list[Makbuz],
) -> list[dict]:
    """Aylık trend — faturalanan ve tahsil edilen."""
    day_span = (end_date - start_date).days + 1
    use_months = day_span > 100

    values: dict[tuple[int, int] | date, dict[str, Decimal]] = defaultdict(
        lambda: {"issued": Decimal("0.00"), "collected": Decimal("0.00")}
    )

    def key_for(d: date):
        if use_months:
            return d.year, d.month
        return d - timedelta(days=d.weekday())

    for wo in work_orders:
        values[key_for(wo.work_date)]["issued"] += money(wo.total_price)

    for m in all_makbuzlar:
        m_date = date(m.year, m.month, 1)
        m_end = date(m.year + 1, 1, 1) - timedelta(days=1) if m.month == 12 else date(m.year, m.month + 1, 1) - timedelta(days=1)
        if m_date <= end_date and m_end >= start_date and m.affects_balance:
            k = key_for(m_date)
            values[k]["issued"] += money(m.grand_total)

        if m.payment_entries:
            for entry in m.payment_entries:
                if start_date <= entry.payment_date <= end_date:
                    k = key_for(entry.payment_date)
                    values[k]["collected"] += money(entry.amount)
        elif m.paid_at and m.paid_amount and start_date <= m.paid_at <= end_date:
            k = key_for(m.paid_at)
            values[k]["collected"] += money(m.paid_amount)

    rows = []
    for key in sorted(values):
        if isinstance(key, tuple):
            label = f"{MONTH_NAMES[key[1]]} {key[0]}"
        else:
            label = key.strftime("%d.%m")
        rows.append({"label": label, **values[key]})
    return rows[-24:]


def build_doctor_detail(
    party_id: int,
    start_date: date,
    end_date: date,
    all_makbuzlar: list[Makbuz],
    work_orders: list[WorkOrder],
) -> DoctorDetailReport:
    """Tek doktor detaylı rapor — iş emirleri, makbuzlar, aging."""
    party = db.session.get(Party, party_id)
    if not party:
        return DoctorDetailReport(
            doctor=DoctorSummary(party_id=party_id, doctor_name="Bilinmeyen")
        )

    doctor = DoctorSummary(party_id=party_id, doctor_name=party.name)

    # İş emirleri
    wo_list = []
    for wo in work_orders:
        if wo.party_id != party_id:
            continue
        doctor.work_order_count += 1
        wo_try = money(wo.total_price)
        doctor.total_try += wo_try
        doctor.total_eur += _wo_to_eur(wo)
        wo_list.append({
            "work_order": wo,
            "total_try": wo_try,
            "total_eur": _wo_to_eur(wo),
        })

    # Makbuzlar
    makbuz_list = []
    for m in all_makbuzlar:
        if m.party_id != party_id:
            continue
        m_date = date(m.year, m.month, 1)
        if m.month == 12:
            m_end = date(m.year + 1, 1, 1) - timedelta(days=1)
        else:
            m_end = date(m.year, m.month + 1, 1) - timedelta(days=1)
        if m_date > end_date or m_end < start_date:
            continue
        if not m.affects_balance:
            continue
        doctor.makbuz_count += 1
        doctor.makbuz_total_try += money(m.grand_total)
        doctor.collected_try += money(m.collected_amount)
        doctor.outstanding_try += money(m.outstanding_amount)
        makbuz_list.append({
            "makbuz": m,
            "collected": m.collected_amount,
            "outstanding": m.outstanding_amount,
        })

    # Devreden borç
    for m in all_makbuzlar:
        if m.party_id != party_id:
            continue
        m_date = date(m.year, m.month, 1)
        if m_date >= start_date:
            continue
        if not m.affects_balance:
            continue
        outstanding = m.outstanding_amount
        if outstanding > 0:
            doctor.previous_debt += outstanding

    doctor.previous_debt += party.previous_balance_outstanding

    # Aging
    aging = build_aging_buckets(end_date, [m for m in all_makbuzlar if m.party_id == party_id])
    total_outstanding = sum((b.amount for b in aging), Decimal("0.00"))

    return DoctorDetailReport(
        doctor=doctor,
        work_orders=wo_list,
        makbuzlar=makbuz_list,
        aging=aging,
        total_outstanding=total_outstanding,
        previous_debt=doctor.previous_debt,
    )


# ---------------------------------------------------------------------------
# Master data fetcher
# ---------------------------------------------------------------------------

def fetch_report_data(start_date: date, end_date: date) -> dict[str, Any]:
    """Tüm rapor verilerini tek seferde çek — N+1 sorgu yok."""
    # Legacy invoices
    invoices = db.session.execute(
        db.select(Invoice)
        .options(selectinload(Invoice.items).selectinload(InvoiceItem.treatment))
        .where(
            Invoice.invoice_date.between(start_date, end_date),
            Invoice.is_deleted.is_(False),
            Invoice.status != Invoice.STATUS_CANCELLED,
        )
    ).scalars().all()

    payments = db.session.execute(
        db.select(Payment)
        .join(Invoice, Payment.invoice_id == Invoice.id)
        .where(
            Payment.payment_date.between(start_date, end_date),
            Invoice.is_deleted.is_(False),
            Invoice.status != Invoice.STATUS_CANCELLED,
        )
    ).scalars().all()

    # Work orders in period
    work_orders = db.session.execute(
        db.select(WorkOrder)
        .where(WorkOrder.work_date.between(start_date, end_date))
        .order_by(WorkOrder.work_date)
    ).scalars().all()

    # All makbuzlar (for aging / cross-period)
    all_makbuzlar = db.session.execute(
        db.select(Makbuz)
        .options(selectinload(Makbuz.party), selectinload(Makbuz.payment_entries))
        .order_by(Makbuz.year, Makbuz.month)
    ).scalars().all()

    # Makbuzlar in period
    makbuzlar = []
    for m in all_makbuzlar:
        m_date = date(m.year, m.month, 1)
        m_end = date(m.year + 1, 1, 1) - timedelta(days=1) if m.month == 12 else date(m.year, m.month + 1, 1) - timedelta(days=1)
        if m_date <= end_date and m_end >= start_date:
            makbuzlar.append(m)

    current_rate = db.session.execute(
        db.select(ExchangeRate)
        .where(ExchangeRate.rate_date <= end_date)
        .order_by(ExchangeRate.rate_date.desc())
        .limit(1)
    ).scalar_one_or_none()

    # All receivable invoices (for aging — entire history)
    receivable_invoices = db.session.execute(
        db.select(Invoice)
        .options(selectinload(Invoice.payments))
        .where(
            Invoice.invoice_date <= end_date,
            Invoice.is_deleted.is_(False),
            Invoice.status != Invoice.STATUS_CANCELLED,
        )
    ).scalars().all()

    return {
        "invoices": invoices,
        "payments": payments,
        "work_orders": work_orders,
        "all_makbuzlar": all_makbuzlar,
        "makbuzlar": makbuzlar,
        "current_rate": current_rate,
        "receivable_invoices": receivable_invoices,
    }
