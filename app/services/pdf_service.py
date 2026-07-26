from fpdf.enums import XPos, YPos
from app.services.base_pdf import LOGO_PATH, BasePDF


class InvoicePDF(BasePDF):

    def __init__(
        self,
        clinic_name="Makro Ortodonti",
        clinic_address="",
        clinic_phone="",
        clinic_email="",
        clinic_tax_id="",
        footer_text="",
    ):
        super().__init__()
        self.clinic_name = clinic_name
        self.clinic_address = clinic_address
        self.clinic_phone = clinic_phone
        self.clinic_email = clinic_email
        self.clinic_tax_id = clinic_tax_id
        self.footer_text = footer_text

    def header(self):
        try:
            self.image(LOGO_PATH, x=12, y=9.5, w=18, h=18, keep_aspect_ratio=True)
        except Exception:
            self.set_fill_color(*self.AQUA_DARK)
            self.rect(12, 10, 17, 17, style="F")
            self.set_xy(12, 10.5)
            self.set_font(self.default_font, "B", 13)
            self.set_text_color(255, 255, 255)
            self.cell(17, 16, "M", align="C")

        self.set_xy(35, 10)
        self.set_font(self.default_font, "B", 15)
        self.set_text_color(*self.INK)
        self.cell(104, 7, self.clinic_name)
        self.set_xy(35, 18)
        self.set_font(self.default_font, "", 7.5)
        self.set_text_color(*self.MUTED)
        contacts = [value for value in (self.clinic_phone, self.clinic_email) if value]
        self.cell(104, 5, "  |  ".join(contacts) or "Ortodonti ve klinik hizmetleri")

        self.set_xy(145, 10)
        self.set_font(self.default_font, "B", 16)
        self.set_text_color(*self.AQUA_DARK)
        self.cell(53, 8, "FATURA", align="R")
        self.set_xy(145, 19)
        self.set_font(self.default_font, "", 7)
        self.set_text_color(*self.MUTED)
        self.cell(53, 5, "EUR / TRY", align="R")

        self.set_draw_color(*self.LINE)
        self.set_line_width(.35)
        self.line(12, 32, 198, 32)
        self.set_y(38)

    def footer(self):
        self.set_y(-19)
        self.set_draw_color(*self.LINE)
        self.line(12, self.get_y(), 198, self.get_y())
        self.ln(2)
        self.set_font(self.default_font, "", 6.5)
        self.set_text_color(*self.MUTED)
        if self.footer_text:
            self.cell(140, 6, self.footer_text[:105])
        else:
            self.cell(140, 6, "Bu belge elektronik ortamda oluşturulmuştur.")
        self.cell(46, 6, f"Sayfa {self.page_no()}/{{nb}}", align="R")

    def _card(self, x, y, w, h, fill=None):
        fill = fill or self.SURFACE
        self.set_fill_color(*fill)
        self.set_draw_color(*self.LINE)
        self.rect(x, y, w, h, style="DF")

    def add_summary(self, invoice, customer, rate_date):
        y = self.get_y()
        self._card(12, y, 112, 43)
        self._card(128, y, 70, 43, self.AQUA_PALE)

        self.set_xy(18, y + 6)
        self.set_font(self.default_font, "B", 7)
        self.set_text_color(*self.AQUA_DARK)
        self.cell(95, 5, "FATURA EDİLEN")
        self.set_xy(18, y + 12)
        self.set_font(self.default_font, "B", 11)
        self.set_text_color(*self.INK)
        self.cell(95, 6, customer["name"][:48])
        self.set_font(self.default_font, "", 7.5)
        self.set_text_color(*self.MUTED)
        info = [customer.get("phone"), customer.get("email"), customer.get("tax_id")]
        line_y = y + 21
        for value in [value for value in info if value][:3]:
            self.set_xy(18, line_y)
            self.cell(95, 5, str(value)[:65])
            line_y += 5

        status_labels = {
            "pending": "Bekliyor", "paid": "Ödendi", "overdue": "Gecikmiş", "cancelled": "İptal",
        }
        self.set_xy(134, y + 6)
        self.set_font(self.default_font, "B", 10)
        self.set_text_color(*self.INK)
        self.cell(58, 6, invoice.invoice_number, align="R")
        rows = [
            ("Fatura tarihi", invoice.invoice_date.strftime("%d.%m.%Y")),
            ("Son ödeme", invoice.due_date.strftime("%d.%m.%Y") if invoice.due_date else "-"),
            ("Kategori", invoice.category_label),
            ("Durum", status_labels.get(invoice.status, invoice.status)),
        ]
        row_y = y + 15
        for label, value in rows:
            self.set_xy(134, row_y)
            self.set_font(self.default_font, "", 6.7)
            self.set_text_color(*self.MUTED)
            self.cell(25, 5, label)
            self.set_font(self.default_font, "B", 6.7)
            self.set_text_color(*self.INK)
            self.cell(33, 5, str(value)[:22], align="R")
            row_y += 6

        self.set_y(y + 48)
        self.set_fill_color(*self.SKY_PALE)
        self.set_draw_color(188, 224, 232)
        self.rect(12, self.get_y(), 186, 15, style="DF")
        self.set_xy(18, self.get_y() + 3)
        self.set_font(self.default_font, "B", 8.5)
        self.set_text_color(*self.INK)
        self.cell(110, 8, f"Fatura tarihi kuru: 1 EUR = {invoice.exchange_rate:,.4f} TRY")
        self.set_font(self.default_font, "", 7)
        self.set_text_color(*self.MUTED)
        date_text = rate_date.strftime("%d.%m.%Y") if rate_date else invoice.invoice_date.strftime("%d.%m.%Y")
        self.cell(64, 8, f"Kur tarihi: {date_text}", align="R")
        self.set_y(self.get_y() + 19)

    def _table_header(self):
        widths = (68, 31, 12, 27, 18, 30)
        labels = ("Kalem", "Kategori", "Adet", "Birim EUR", "KDV", "Toplam TRY")
        self.set_fill_color(*self.INK)
        self.set_text_color(255, 255, 255)
        self.set_font(self.default_font, "B", 7)
        for width, label in zip(widths, labels):
            align = "R" if label in ("Birim EUR", "KDV", "Toplam TRY") else ("C" if label == "Adet" else "L")
            self.cell(width, 8, label, border=0, fill=True, align=align)
        self.ln()

    def add_items_table(self, items, category_labels):
        self.set_font(self.default_font, "B", 9)
        self.set_text_color(*self.AQUA_DARK)
        self.cell(0, 7, "FATURA KALEMLERİ", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self._table_header()
        widths = (68, 31, 12, 27, 18, 30)
        for index, item in enumerate(items):
            if self.get_y() > 255:
                self.add_page()
                self._table_header()
            category_key = item.treatment.category if item.treatment else item.item_type.value
            category = category_labels.get(category_key, category_key)
            self.set_fill_color(*(self.SURFACE if index % 2 == 0 else (255, 255, 255)))
            self.set_text_color(*self.INK)
            self.set_font(self.default_font, "", 7.2)
            values = (
                item.description[:45], category[:20], str(item.quantity),
                f"{item.unit_price_eur:,.2f}", f"%{item.vat_rate:,.1f}", f"{item.line_total_try + item.vat_amount_try:,.2f}",
            )
            for width, value in zip(widths, values):
                align = "R" if width in (27, 18, 30) else ("C" if width == 12 else "L")
                self.cell(width, 8, value, border="B", fill=True, align=align)
            self.ln()

    def add_totals(self, invoice):
        if self.get_y() > 225:
            self.add_page()
        subtotal_eur = sum(item.line_total_eur for item in invoice.items)
        vat_eur = sum(item.vat_amount_eur for item in invoice.items)
        self.ln(4)
        x_label, x_value = 126, 163
        rows = (
            ("Ara toplam", f"€{subtotal_eur:,.2f}", False),
            ("KDV toplamı", f"€{vat_eur:,.2f}", False),
            ("Toplam EUR", f"€{invoice.total_eur:,.2f}", True),
        )
        for label, value, bold in rows:
            self.set_xy(x_label, self.get_y())
            self.set_font(self.default_font, "B" if bold else "", 8)
            self.set_text_color(*self.MUTED if not bold else self.INK)
            self.cell(37, 7, label, align="R")
            self.set_text_color(*self.INK)
            self.cell(35, 7, value, align="R")
            self.ln()

        self.set_x(126)
        self.set_fill_color(*self.AQUA_DARK)
        self.set_text_color(255, 255, 255)
        self.set_font(self.default_font, "B", 10)
        self.cell(37, 11, "TOPLAM TRY", fill=True, align="R")
        self.cell(35, 11, f"₺{invoice.total_try:,.2f}", fill=True, align="R")
        self.ln()

    def add_notes(self, notes):
        if not notes:
            return
        if self.get_y() > 242:
            self.add_page()
        self.ln(6)
        self.set_font(self.default_font, "B", 7)
        self.set_text_color(*self.AQUA_DARK)
        self.cell(0, 5, "NOTLAR", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font(self.default_font, "", 7.5)
        self.set_text_color(*self.MUTED)
        self.set_fill_color(*self.SURFACE)
        self.multi_cell(0, 5, notes, fill=True, padding=3)


def get_customer_info(invoice):
    customer = invoice.party or invoice.patient
    if not customer:
        return {"name": "Bilinmeyen müşteri"}
    return {
        "name": getattr(customer, "display_name", None) or getattr(customer, "full_name", "Bilinmeyen müşteri"),
        "phone": customer.phone,
        "email": customer.email,
        "address": customer.address,
        "tax_id": getattr(customer, "tax_id", None),
    }


def generate_invoice_pdf(invoice) -> bytes:
    from app.extensions import db
    from app.models.models import ExchangeRate, INVOICE_CATEGORY_LABELS, Settings

    def get_setting(key, default=""):
        value = db.session.execute(
            db.select(Settings.value).where(Settings.key == key)
        ).scalar_one_or_none()
        return value or default

    rate_record = db.session.execute(
        db.select(ExchangeRate)
        .where(ExchangeRate.rate_date <= invoice.invoice_date)
        .order_by(ExchangeRate.rate_date.desc())
        .limit(1)
    ).scalar_one_or_none()

    pdf = InvoicePDF(
        clinic_name=get_setting("clinic_name", "Makro Ortodonti"),
        clinic_address=get_setting("clinic_address"),
        clinic_phone=get_setting("clinic_phone"),
        clinic_email=get_setting("clinic_email"),
        clinic_tax_id=get_setting("tax_id"),
        footer_text=get_setting("invoice_footer_text"),
    )
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.add_summary(invoice, get_customer_info(invoice), rate_record.rate_date if rate_record else None)
    pdf.add_items_table(invoice.items, INVOICE_CATEGORY_LABELS)
    pdf.add_totals(invoice)
    pdf.add_notes(invoice.notes)

    output = pdf.output()
    return bytes(output) if isinstance(output, (bytes, bytearray)) else str(output).encode("latin-1", errors="ignore")
