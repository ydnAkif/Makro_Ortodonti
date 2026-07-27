from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum as PyEnum
from typing import TYPE_CHECKING

from flask_login import UserMixin
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from .patient import Patient
    from .invoice import Invoice, InvoiceItem


class TreatmentCategory:
    ANA_ISLEMLER = "ana_islemler"
    EKSTRA_ISLEMLER = "ekstra_islemler"
    OTHER = "other"  # Bilinmeyen/sınıflandırılamayan kategoriler için genel geri dönüş değeri.

    ALL = [
        ANA_ISLEMLER,
        EKSTRA_ISLEMLER,
    ]


class PartyType(PyEnum):
    DENTIST = "dentist"
    PATIENT = "patient"
    DENTIST_CUSTOMER = "dentist_customer"
    COMPANY_CUSTOMER = "company_customer"


class InvoiceItemType(PyEnum):
    TREATMENT = "treatment"
    PRODUCT = "product"
    SERVICE = "service"
    LAB = "lab"
    CUSTOM = "custom"


INVOICE_CATEGORY_LABELS = {
    TreatmentCategory.ANA_ISLEMLER: "Ana İşlemler",
    TreatmentCategory.EKSTRA_ISLEMLER: "Ekstra İşlemler",
    TreatmentCategory.OTHER: "Diğer",
    InvoiceItemType.PRODUCT.value: "Ürün",
    InvoiceItemType.SERVICE.value: "Hizmet",
    InvoiceItemType.LAB.value: "Laboratuvar",
    InvoiceItemType.CUSTOM.value: "Özel kalem",
    "mixed": "Karma",
}


def invoice_item_category_key(item: "InvoiceItem") -> str:
    """Return the business-facing category for an invoice line."""
    item_type = item.item_type.value if isinstance(item.item_type, InvoiceItemType) else str(item.item_type)
    if item_type == InvoiceItemType.TREATMENT.value and item.treatment:
        return item.treatment.category or TreatmentCategory.OTHER
    return item_type if item_type in INVOICE_CATEGORY_LABELS else TreatmentCategory.OTHER


class Party(Base, TimestampMixin):
    """Unified entity for all parties: patients, dentist customers, company customers.

    Mimari karar — Single Table Inheritance (STI):
    Party tablosu DENTIST, PATIENT, DENTIST_CUSTOMER ve COMPANY_CUSTOMER türlerini
    aynı tabloda tutar. Bu, mevcut ölçekte (birkaç yüz kayıt) en verimli yaklaşımdır.

    Kolon kullanımı türe göre değişir:
    - DENTIST: name, phone, email, address, tax_id, notes, is_active, previous_balance
    - PATIENT: first_name, last_name, date_of_birth, treatment_status, referred_by_id
    - COMPANY_CUSTOMER: contact_person, contact_phone
    - DENTIST_CUSTOMER: name, phone (doktor müşterisi)

    Patient modeli (`patient.py`) legacy.read-only uyumluluk içindir; yeni klinik
    verileri Party.PATIENT türü ile yönetilir. Invoice.patient_id FK'si mevcut
    verilerle uyumluluk için korunmaktadır.
    """
    __tablename__ = "parties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    party_type: Mapped[str] = mapped_column(
        SQLEnum(PartyType), nullable=False, default=PartyType.DENTIST, index=True
    )
    # Common fields
    name: Mapped[str] = mapped_column(String(200), nullable=False)  # full name or company name
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(50), nullable=True)  # TC Kimlik / Vergi No
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    previous_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    applies_kdv: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    # Patient-specific fields (used when party_type = PATIENT)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(nullable=True)
    treatment_status: Mapped[str] = mapped_column(
        String(30), default="active", nullable=False, index=True
    )

    # Company-specific fields (used when party_type = COMPANY_CUSTOMER)
    contact_person: Mapped[str | None] = mapped_column(String(150), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Doctor link (patients -> referring dentist)
    referred_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("parties.id"), nullable=True, index=True)
    referred_by = relationship("Party", remote_side="Party.id", foreign_keys=[referred_by_id], lazy="selectin")

    # Relationships
    invoices: Mapped[list["Invoice"]] = relationship(
        back_populates="party", lazy="selectin"
    )
    patient: Mapped["Patient"] = relationship(
        back_populates="party", uselist=False, lazy="selectin"
    )
    treatments: Mapped[list["PatientTreatment"]] = relationship(
        back_populates="party", lazy="selectin"
    )
    work_orders: Mapped[list["WorkOrder"]] = relationship(
        back_populates="party", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("name", "phone", "party_type", name="uq_party_identity"),
    )

    @property
    def display_name(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"<Party {self.display_name} ({self.party_type.value})>"


MONEY_SCALE = Decimal("0.01")
RATE_SCALE = Decimal("0.0001")
PERCENT_SCALE = Decimal("0.01")


def money(value: object) -> Decimal:
    """Convert a monetary input without passing through binary floating point."""
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(MONEY_SCALE, rounding=ROUND_HALF_UP)


def rate_decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0.0000")
    return Decimal(str(value)).quantize(RATE_SCALE, rounding=ROUND_HALF_UP)


class Treatment(Base, TimestampMixin):
    """Catalog treatment/appliance price list item."""
    __tablename__ = "treatments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, default=TreatmentCategory.ANA_ISLEMLER
    )
    price_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # NOT: Sütun adı price_eur olsa da bu aslında katalog baz fiyatıdır.
    # currency alanına göre TL, EUR veya USD cinsinden olabilir.
    # Bu isim historical migration uyumluluğu için korunmaktadır.
    # Yeni kodlarda base_price property'ini kullanın.
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="TL")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    @property
    def base_price(self) -> Decimal:
        """Catalog base price (stored in price_eur column)."""
        return self.price_eur

    @base_price.setter
    def base_price(self, value: Decimal) -> None:
        self.price_eur = value

    @property
    def price_formatted(self) -> str:
        """Return formatted price with correct currency symbol."""
        if self.currency == "USD":
            symbol = "$"
        elif self.currency == "EUR":
            symbol = "€"
        else:
            symbol = "₺"
        return f"{symbol}{self.price_eur:.2f}"

    patient_treatments: Mapped[list["PatientTreatment"]] = relationship(
        back_populates="treatment", lazy="selectin"
    )
    invoice_items: Mapped[list["InvoiceItem"]] = relationship(
        back_populates="treatment", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("name", name="uq_treatment_name"),
    )

    def __repr__(self) -> str:
        return f"<Treatment {self.name} {self.price_formatted}>"


class Patient(Base, TimestampMixin, SoftDeleteMixin):
    """Read-only legacy compatibility model; new clinical data belongs to Party.

    Bu model mevcut verilerle geriye dönük uyumluluk için korunmaktadır.
    Yeni hasta kayıtları Party(party_type=PATIENT) olarak oluşturulmalıdır.

    Kullanım alanları:
    - Test fixture'larında (conftest.py)
    - Invoice.patient_id FK referansları (eski faturalar)
    - Gelecekte tamamen kaldırılabilir; migration stratejisi henüz belirlenmemiştir.
    """
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    treatment_status: Mapped[str] = mapped_column(
        String(30), default="active", nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    party_id: Mapped[int | None] = mapped_column(ForeignKey("parties.id"), nullable=True, index=True)

    patient_treatments: Mapped[list["PatientTreatment"]] = relationship(
        back_populates="patient", lazy="selectin"
    )
    invoices: Mapped[list["Invoice"]] = relationship(
        back_populates="patient", lazy="selectin"
    )
    party: Mapped["Party"] = relationship(back_populates="patient", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("first_name", "last_name", "phone", name="uq_patient_identity"),
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def __repr__(self) -> str:
        return f"<Patient {self.full_name}>"


class PatientTreatment(Base, TimestampMixin):
    __tablename__ = "patient_treatments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"), nullable=True, index=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), nullable=False, index=True)
    treatment_id: Mapped[int] = mapped_column(
        ForeignKey("treatments.id"), nullable=False, index=True
    )
    treatment_date: Mapped[date] = mapped_column(nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_override_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    patient: Mapped["Patient"] = relationship(back_populates="patient_treatments")
    party: Mapped["Party"] = relationship(back_populates="treatments")
    treatment: Mapped["Treatment"] = relationship(back_populates="patient_treatments")

    @property
    def effective_price_eur(self) -> Decimal:
        if self.price_override_eur is not None:
            return self.price_override_eur
        return self.treatment.price_eur

    def __repr__(self) -> str:
        return f"<PatientTreatment party={self.party_id} treatment={self.treatment_id}>"


class ExchangeRate(Base, TimestampMixin):
    __tablename__ = "exchange_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rate_date: Mapped[date] = mapped_column(nullable=False, index=True)
    eur_to_try: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    usd_to_try: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="ecb", nullable=False)

    __table_args__ = (
        UniqueConstraint("rate_date", "source", name="uq_exchange_rate_date_source"),
    )

    def __repr__(self) -> str:
        return f"<ExchangeRate {self.rate_date}: 1€ = {self.eur_to_try:.2f}₺, 1$ = {self.usd_to_try or 0:.2f}₺>"


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"), nullable=True, index=True)
    party_id: Mapped[int | None] = mapped_column(ForeignKey("parties.id"), nullable=True, index=True)
    invoice_number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    invoice_date: Mapped[date] = mapped_column(nullable=False, index=True)
    due_date: Mapped[date | None] = mapped_column(nullable=True)
    total_eur: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0.00"))
    total_try: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0.00"))
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    patient: Mapped["Patient"] = relationship(back_populates="invoices")
    party: Mapped["Party"] = relationship(back_populates="invoices")
    items: Mapped[list["InvoiceItem"]] = relationship(
        back_populates="invoice", lazy="selectin", cascade="all, delete-orphan"
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="invoice", lazy="selectin", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("invoice_number", name="uq_invoice_number"),
    )

    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"
    STATUS_OVERDUE = "overdue"
    STATUS_CANCELLED = "cancelled"

    def recalculate_totals(self) -> None:
        self.total_eur = money(sum((item.line_total_eur + item.vat_amount_eur for item in self.items), Decimal("0")))
        self.total_try = money(sum((item.line_total_try + item.vat_amount_try for item in self.items), Decimal("0")))

    @property
    def category_keys(self) -> list[str]:
        return sorted({invoice_item_category_key(item) for item in self.items})

    @property
    def category_key(self) -> str:
        keys = self.category_keys
        if not keys:
            return TreatmentCategory.OTHER
        return keys[0] if len(keys) == 1 else "mixed"

    @property
    def category_label(self) -> str:
        return INVOICE_CATEGORY_LABELS.get(self.category_key, self.category_key)

    def __repr__(self) -> str:
        return f"<Invoice {self.invoice_number} €{self.total_eur:.2f}>"


class InvoiceItem(Base, TimestampMixin):
    __tablename__ = "invoice_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_type: Mapped[str] = mapped_column(
        SQLEnum(InvoiceItemType), nullable=False, default=InvoiceItemType.TREATMENT
    )
    treatment_id: Mapped[int | None] = mapped_column(
        ForeignKey("treatments.id"), nullable=True, index=True
    )
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # for product/service/lab
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    unit_price_try: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0.00"))
    discount_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # percent, amount
    discount_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))

    invoice: Mapped["Invoice"] = relationship(back_populates="items")
    treatment: Mapped["Treatment"] = relationship(back_populates="invoice_items")

    @property
    def line_total_eur(self) -> Decimal:
        base = self.unit_price_eur * self.quantity
        if self.discount_type == "percent":
            return money(base * (Decimal("1") - self.discount_value / Decimal("100")))
        elif self.discount_type == "amount":
            return base - self.discount_value
        return base

    @property
    def line_total_try(self) -> Decimal:
        base = self.unit_price_try * self.quantity
        if self.discount_type == "percent":
            return money(base * (Decimal("1") - self.discount_value / Decimal("100")))
        elif self.discount_type == "amount":
            return base - self.discount_value
        return base

    @property
    def vat_amount_eur(self) -> Decimal:
        return money(self.line_total_eur * (self.vat_rate / Decimal("100")))

    @property
    def vat_amount_try(self) -> Decimal:
        return money(self.line_total_try * (self.vat_rate / Decimal("100")))

    def __repr__(self) -> str:
        return f"<InvoiceItem {self.description} x{self.quantity} ({self.item_type.value})>"


class Settings(Base, TimestampMixin):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    DEFAULTS = {
        "clinic_name": "Makro Ortodonti",
        "clinic_address": "",
        "clinic_phone": "",
        "clinic_email": "",
        "clinic_logo_path": "",
        "tax_id": "",
        "invoice_prefix": "MKR",
        "invoice_next_number": "1",
        "invoice_footer_text": "",
        "default_exchange_rate_source": "ecb",
        "currency_symbol_eur": "€",
        "currency_symbol_try": "₺",
        "whatsapp_session_id": "",
        "whatsapp_phone_number": "",
    }

    def __repr__(self) -> str:
        return f"<Settings {self.key}={self.value}>"


class User(UserMixin, Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="staff", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # SHA-256 hex digest of a bearer token for /api/v1/*, not the token
    # itself — the raw token is shown once at generation time and cannot be
    # recovered from this column (same pattern as GitHub/Stripe API keys).
    api_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)

    ROLE_ADMIN = "admin"
    ROLE_STAFF = "staff"
    VALID_ROLES = [ROLE_ADMIN, ROLE_STAFF]

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role})>"


class WhatsAppSession(Base, TimestampMixin):
    __tablename__ = "whatsapp_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="disconnected", nullable=False)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    qr_code: Mapped[str | None] = mapped_column(Text, nullable=True)

    STATUS_DISCONNECTED = "disconnected"
    STATUS_CONNECTING = "connecting"
    STATUS_CONNECTED = "connected"

    def __repr__(self) -> str:
        return f"<WhatsAppSession {self.session_id} ({self.status})>"


class PaymentMethod(PyEnum):
    CASH = "cash"
    CARD = "card"
    TRANSFER = "transfer"
    CHECK = "check"
    OTHER = "other"


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), nullable=False, index=True)
    payment_date: Mapped[date] = mapped_column(nullable=False, index=True)
    amount_eur: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    amount_try: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    method: Mapped[str] = mapped_column(SQLEnum(PaymentMethod), nullable=False, default=PaymentMethod.CASH)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    invoice: Mapped["Invoice"] = relationship(lazy="selectin")

    def __repr__(self) -> str:
        return f"<Payment {self.invoice_id} €{self.amount_eur:.2f} ₺{self.amount_try:.2f}>"


class WorkOrder(Base, TimestampMixin):
    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), nullable=False, index=True)
    work_date: Mapped[date] = mapped_column(nullable=False, index=True)
    apparatus_type: Mapped[str] = mapped_column(Text, nullable=False)
    extra_addons: Mapped[str | None] = mapped_column(Text, nullable=True)
    patient_name: Mapped[str] = mapped_column(String(200), nullable=False)
    apparatus_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    extra_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    total_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    exchange_rate_applied: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    party: Mapped["Party"] = relationship(lazy="selectin")

    def recalculate_total(self) -> None:
        self.total_price = money(self.apparatus_price + self.extra_price)

    def __repr__(self) -> str:
        return f"<WorkOrder {self.patient_name} ({self.apparatus_type}) ₺{self.total_price:.2f}>"


class Makbuz(Base, TimestampMixin):
    """Doktor bazlı, aylık, kalıcı makbuz kaydı (WorkOrder toplamlarının anlık görüntüsü)."""

    __tablename__ = "makbuzlar"

    STATUS_DRAFT = "draft"
    STATUS_SENT = "sent"
    STATUS_PAID = "paid"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    month: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    work_order_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0.00"))
    vat_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0.00"))
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0.00"))
    grand_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0.00"))

    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_DRAFT, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now().astimezone())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    paid_at: Mapped[date | None] = mapped_column(nullable=True)
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    party: Mapped["Party"] = relationship(lazy="selectin")
    payment_entries: Mapped[list["MakbuzPayment"]] = relationship(
        back_populates="makbuz",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="MakbuzPayment.payment_date.desc(), MakbuzPayment.id.desc()",
    )

    __table_args__ = (
        UniqueConstraint("party_id", "year", "month", name="uq_makbuz_party_period"),
    )

    def recalculate_totals(self) -> None:
        self.vat_amount = money(self.subtotal * self.vat_rate / Decimal("100")) if self.vat_applied else Decimal("0.00")
        self.grand_total = money(self.subtotal + self.vat_amount)

    @property
    def collected_amount(self) -> Decimal:
        if self.payment_entries:
            raw_total = money(sum((entry.amount for entry in self.payment_entries), Decimal("0.00")))
            return min(self.grand_total, raw_total) if self.grand_total > 0 else raw_total
        return min(self.grand_total, money(self.paid_amount or Decimal("0.00"))) if self.grand_total > 0 else money(self.paid_amount or Decimal("0.00"))

    @property
    def outstanding_amount(self) -> Decimal:
        return money(max(self.grand_total - self.collected_amount, Decimal("0.00")))

    @property
    def is_partially_paid(self) -> bool:
        return Decimal("0.00") < self.collected_amount < self.grand_total

    def __repr__(self) -> str:
        return f"<Makbuz {self.party_id} {self.year}-{self.month:02d} ₺{self.grand_total:.2f} ({self.status})>"


class MakbuzPayment(Base, TimestampMixin):
    """A single collection movement allocated to a monthly doctor receipt."""

    __tablename__ = "makbuz_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    makbuz_id: Mapped[int] = mapped_column(ForeignKey("makbuzlar.id"), nullable=False, index=True)
    payment_date: Mapped[date] = mapped_column(nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    method: Mapped[str] = mapped_column(String(30), nullable=False, default=PaymentMethod.CASH.value)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    makbuz: Mapped["Makbuz"] = relationship(back_populates="payment_entries", lazy="selectin")

    def __repr__(self) -> str:
        return f"<MakbuzPayment {self.makbuz_id} ₺{self.amount:.2f} {self.payment_date}>"


class MakbuzSendLog(Base, TimestampMixin):
    """WhatsApp makbuz gönderimlerinin kalıcı geçmişi (batch bazlı, doktor başına bir satır)."""

    __tablename__ = "makbuz_send_logs"

    TRIGGER_MANUAL = "manual"
    TRIGGER_SCHEDULER = "scheduler"
    TRIGGER_REMINDER = "reminder"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    makbuz_id: Mapped[int | None] = mapped_column(ForeignKey("makbuzlar.id"), nullable=True, index=True)
    party_id: Mapped[int | None] = mapped_column(ForeignKey("parties.id"), nullable=True, index=True)

    # Snapshot fields so history stays readable if the doctor/makbuz changes
    doctor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)

    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(20), nullable=False, default=TRIGGER_MANUAL)

    def __repr__(self) -> str:
        return f"<MakbuzSendLog {self.doctor_name} {self.year}-{self.month:02d} {'ok' if self.success else 'fail'}>"


class LoginAttempt(Base, TimestampMixin):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip_address: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    is_successful: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:
        return f"<LoginAttempt {self.username} from {self.ip_address} - {'SUCCESS' if self.is_successful else 'FAIL'} at {self.created_at}>"


class AuditLog(Base):
    """Append-only trace of data mutations; application code never updates rows."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now().astimezone(), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    actor_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    endpoint: Mapped[str | None] = mapped_column(String(150), nullable=True)
    changes_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    actor: Mapped["User | None"] = relationship(lazy="joined")
