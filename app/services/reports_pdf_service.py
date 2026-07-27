"""Rapor PDF üretimi — doktor bazlı, dönemsel, KDV detaylı."""

from __future__ import annotations

from decimal import Decimal

from fpdf.enums import XPos, YPos
from app.services.base_pdf import BasePDF

from app.constants import MONTH_NAMES


class ReportPDF(BasePDF):

    def __init__(self, clinic_name="Makro Ortodonti", clinic_phone="", clinic_email=""):
        super().__init__()
        self.clinic_name = clinic_name
        self.clinic_phone = clinic_phone
        self.clinic_email = clinic_email

    def header(self):
        from app.services.base_pdf import LOGO_PATH
        try:
            self.image(LOGO_PATH, x=12, y=9.5, w=18, h=18, keep_aspect_ratio=True)
        except Exception:
            self.set_fill_color(*self.AQUA_DARK)
            self.rect(12, 10, 17, 17, style="F")
            self.set_xy(12, 10.5)
            self.set_font(self.default_font, "B", 13)
            self.set_text_color(*self.WHITE)
            self.cell(17, 16, "M", align="C")

        self.set_xy(35, 10)
        self.set_font(self.default_font, "B", 15)
        self.set_text_color(*self.INK)
        self.cell(104, 7, self.clinic_name)
        self.set_xy(35, 18)
        self.set_font(self.default_font, "", 7.5)
        self.set_text_color(*self.MUTED)
        contacts = [v for v in (self.clinic_phone, self.clinic_email) if v]
        self.cell(104, 5, "  |  ".join(contacts) or "Ortodonti ve klinik hizmetleri")
        self.set_draw_color(*self.LINE)
        self.set_line_width(0.35)
        self.line(12, 30, 198, 30)
        self.set_y(35)

    def footer(self):
        self.set_y(-19)
        self.set_draw_color(*self.LINE)
        self.line(12, self.get_y(), 198, self.get_y())
        self.ln(2)
        self.set_font(self.default_font, "", 6.5)
        self.set_text_color(*self.MUTED)
        self.cell(140, 6, "Bu belge elektronik ortamda oluşturulmuştur.")
        self.cell(46, 6, f"Sayfa {self.page_no()}/{{nb}}", align="R")

    def _section_title(self, title: str):
        self.set_font(self.default_font, "B", 9)
        self.set_text_color(*self.AQUA_DARK)
        self.cell(0, 7, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def _label_value_row(self, label: str, value: str, bold: bool = False):
        self.set_font(self.default_font, "B" if bold else "", 7.5)
        self.set_text_color(*self.MUTED if not bold else self.INK)
        self.cell(55, 6, label)
        self.set_text_color(*self.INK)
        self.cell(40, 6, value, align="R")

    def add_report_title(self, title: str, subtitle: str):
        self.set_font(self.default_font, "B", 14)
        self.set_text_color(*self.AQUA_DARK)
        self.cell(0, 8, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font(self.default_font, "", 8)
        self.set_text_color(*self.MUTED)
        self.cell(0, 5, subtitle, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(3)


# ---------------------------------------------------------------------------
# Doctor summary PDF
# ---------------------------------------------------------------------------

def generate_doctor_report_pdf(
    clinic_name: str,
    clinic_phone: str,
    clinic_email: str,
    title: str,
    subtitle: str,
    doctor_name: str,
    period_label: str,
    summary_rows: list[tuple[str, str]],
    work_orders: list[dict] | None = None,
    makbuzlar: list[dict] | None = None,
    aging_rows: list[dict] | None = None,
    vat_summary: list[dict] | None = None,
) -> bytes:
    """Tek doktor için kapsamlı PDF rapor üret."""
    pdf = ReportPDF(clinic_name=clinic_name, clinic_phone=clinic_phone, clinic_email=clinic_email)
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.add_report_title(title, subtitle)

    # Doktor bilgisi
    y = pdf.get_y()
    pdf.set_fill_color(*pdf.SURFACE)
    pdf.set_draw_color(*pdf.LINE)
    pdf.rect(12, y, 186, 18, style="DF")
    pdf.set_xy(18, y + 4)
    pdf.set_font(pdf.default_font, "B", 7)
    pdf.set_text_color(*pdf.AQUA_DARK)
    pdf.cell(90, 5, "DOKTOR")
    pdf.set_xy(18, y + 10)
    pdf.set_font(pdf.default_font, "B", 11)
    pdf.set_text_color(*pdf.INK)
    pdf.cell(90, 6, doctor_name[:55])
    pdf.set_xy(118, y + 4)
    pdf.set_font(pdf.default_font, "", 7)
    pdf.set_text_color(*pdf.MUTED)
    pdf.cell(35, 5, "Dönem")
    pdf.set_font(pdf.default_font, "B", 7)
    pdf.set_text_color(*pdf.INK)
    pdf.cell(33, 5, period_label, align="R")
    pdf.set_xy(118, y + 10)
    pdf.set_font(pdf.default_font, "", 7)
    pdf.set_text_color(*pdf.MUTED)
    pdf.cell(35, 5, "Rapor tarihi")
    pdf.set_font(pdf.default_font, "B", 7)
    pdf.set_text_color(*pdf.INK)
    pdf.cell(33, 5, subtitle[:20], align="R")
    pdf.set_y(y + 24)

    # Özet satırları
    if summary_rows:
        pdf._section_title("ÖZET")
        for label, value in summary_rows:
            pdf._label_value_row(label, value)
        pdf.ln(3)

    # İş emirleri tablosu
    if work_orders:
        pdf._section_title("İŞ EMİRLERİ")
        widths = (20, 35, 60, 22, 22, 22)
        labels = ("Tarih", "Hasta", "İşlem", "Aparey (₺)", "Ekstra (₺)", "Toplam (₺)")
        pdf.set_fill_color(*pdf.INK)
        pdf.set_text_color(*pdf.WHITE)
        pdf.set_font(pdf.default_font, "B", 6.5)
        for w, lbl in zip(widths, labels):
            align = "R" if "(₺)" in lbl else ("C" if lbl == "Adet" else "L")
            pdf.cell(w, 7, lbl, border=0, fill=True, align=align)
        pdf.ln()

        for i, item in enumerate(work_orders):
            wo = item.get("work_order", item)
            if pdf.get_y() > 262:
                pdf.add_page()
                pdf.set_fill_color(*pdf.INK)
                pdf.set_text_color(*pdf.WHITE)
                pdf.set_font(pdf.default_font, "B", 6.5)
                for w, lbl in zip(widths, labels):
                    align = "R" if "(₺)" in lbl else ("C" if lbl == "Adet" else "L")
                    pdf.cell(w, 7, lbl, border=0, fill=True, align=align)
                pdf.ln()

            pdf.set_fill_color(*(pdf.SURFACE if i % 2 == 0 else pdf.WHITE))
            pdf.set_text_color(*pdf.INK)
            pdf.set_font(pdf.default_font, "", 6.5)
            pdf.cell(widths[0], 6, wo.work_date.strftime("%d.%m.%Y"), border="B", fill=True)
            pdf.cell(widths[1], 6, (wo.patient_name or "")[:22], border="B", fill=True)
            detail = (wo.apparatus_type or "")[:40]
            pdf.cell(widths[2], 6, detail, border="B", fill=True)
            pdf.cell(widths[3], 6, f"{wo.apparatus_price:,.2f}", border="B", fill=True, align="R")
            pdf.cell(widths[4], 6, f"{wo.extra_price:,.2f}", border="B", fill=True, align="R")
            pdf.cell(widths[5], 6, f"{wo.total_price:,.2f}", border="B", fill=True, align="R")
            pdf.ln()
        pdf.ln(2)

    # Makbuzlar tablosu
    if makbuzlar:
        pdf._section_title("AYLIK HESAP ÖZETLERİ")
        widths = (35, 22, 30, 30, 30, 30)
        labels = ("Dönem", "Durum", "Toplam (₺)", "Tahsil (₺)", "Kalan (₺)", "Durum")
        pdf.set_fill_color(*pdf.INK)
        pdf.set_text_color(*pdf.WHITE)
        pdf.set_font(pdf.default_font, "B", 6.5)
        for w, lbl in zip(widths, labels):
            pdf.cell(w, 7, lbl, border=0, fill=True, align="C")
        pdf.ln()

        status_map = {"draft": "Taslak", "sent": "Gönderildi", "paid": "Ödendi"}
        for i, item in enumerate(makbuzlar):
            m = item.get("makbuz", item)
            period = f"{MONTH_NAMES[m.month]} {m.year}"
            collected = item.get("collected", m.collected_amount)
            outstanding = item.get("outstanding", m.outstanding_amount)
            pdf.set_fill_color(*(pdf.SURFACE if i % 2 == 0 else pdf.WHITE))
            pdf.set_text_color(*pdf.INK)
            pdf.set_font(pdf.default_font, "", 6.5)
            pdf.cell(widths[0], 6, period, border="B", fill=True)
            pdf.cell(widths[1], 6, status_map.get(m.status, m.status), border="B", fill=True, align="C")
            pdf.cell(widths[2], 6, f"{m.grand_total:,.2f}", border="B", fill=True, align="R")
            pdf.cell(widths[3], 6, f"{collected:,.2f}", border="B", fill=True, align="R")
            pdf.cell(widths[4], 6, f"{outstanding:,.2f}", border="B", fill=True, align="R")
            pdf.cell(widths[5], 6, status_map.get(m.status, m.status), border="B", fill=True, align="C")
            pdf.ln()
        pdf.ln(2)

    # KDV özeti
    if vat_summary:
        pdf._section_title("KDV ÖZETİ")
        widths = (30, 35, 35, 35)
        labels = ("KDV Oranı", "Brüt (₺)", "KDV (₺)", "Net (₺)")
        pdf.set_fill_color(*pdf.INK)
        pdf.set_text_color(*pdf.WHITE)
        pdf.set_font(pdf.default_font, "B", 6.5)
        for w, lbl in zip(widths, labels):
            pdf.cell(w, 7, lbl, border=0, fill=True, align="C")
        pdf.ln()
        for i, v in enumerate(vat_summary):
            pdf.set_fill_color(*(pdf.SURFACE if i % 2 == 0 else pdf.WHITE))
            pdf.set_text_color(*pdf.INK)
            pdf.set_font(pdf.default_font, "", 6.5)
            pdf.cell(widths[0], 6, v.get("label", ""), border="B", fill=True, align="C")
            pdf.cell(widths[1], 6, f"{v.get('gross', 0):,.2f}", border="B", fill=True, align="R")
            pdf.cell(widths[2], 6, f"{v.get('vat_amount', 0):,.2f}", border="B", fill=True, align="R")
            pdf.cell(widths[3], 6, f"{v.get('net', 0):,.2f}", border="B", fill=True, align="R")
            pdf.ln()
        pdf.ln(2)

    # Aging
    if aging_rows:
        pdf._section_title("Vadesine Göre Açık Alacaklar")
        for row in aging_rows:
            label = row.get("label", "")
            count = row.get("count", 0)
            amount = row.get("amount", Decimal("0.00"))
            pdf.set_font(pdf.default_font, "", 7)
            pdf.set_text_color(*pdf.INK)
            pdf.cell(70, 6, f"{label} ({count} aylık özet)")
            pdf.cell(30, 6, f"{amount:,.2f} ₺", align="R")
            pdf.ln()

    output = pdf.output()
    return bytes(output) if isinstance(output, (bytes, bytearray)) else str(output).encode("latin-1", errors="ignore")


# ---------------------------------------------------------------------------
# Period overview PDF
# ---------------------------------------------------------------------------

def generate_period_report_pdf(
    clinic_name: str,
    clinic_phone: str,
    clinic_email: str,
    title: str,
    period_label: str,
    summary_rows: list[tuple[str, str]],
    doctor_rows: list[dict] | None = None,
    aging_rows: list[dict] | None = None,
    vat_summary: list[dict] | None = None,
) -> bytes:
    """Dönemsel genel rapor PDF'i."""
    pdf = ReportPDF(clinic_name=clinic_name, clinic_phone=clinic_phone, clinic_email=clinic_email)
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.add_report_title(title, period_label)

    # Özet
    if summary_rows:
        pdf._section_title("DÖNEM ÖZETİ")
        for label, value in summary_rows:
            pdf._label_value_row(label, value)
        pdf.ln(3)

    # Doktor bazlı tablo
    if doctor_rows:
        pdf._section_title("DOKTOR BAZLI ÖZET")
        widths = (50, 18, 30, 30, 30, 28)
        labels = ("Doktor", "İş Emri", "Toplam (₺)", "Tahsil (₺)", "Kalan (₺)", "Devreden")
        pdf.set_fill_color(*pdf.INK)
        pdf.set_text_color(*pdf.WHITE)
        pdf.set_font(pdf.default_font, "B", 6.5)
        for w, lbl in zip(widths, labels):
            pdf.cell(w, 7, lbl, border=0, fill=True, align="C")
        pdf.ln()

        for i, row in enumerate(doctor_rows):
            if pdf.get_y() > 262:
                pdf.add_page()
            pdf.set_fill_color(*(pdf.SURFACE if i % 2 == 0 else pdf.WHITE))
            pdf.set_text_color(*pdf.INK)
            pdf.set_font(pdf.default_font, "", 6.5)
            pdf.cell(widths[0], 6, row.get("doctor_name", "")[:35], border="B", fill=True)
            pdf.cell(widths[1], 6, str(row.get("work_order_count", 0)), border="B", fill=True, align="C")
            pdf.cell(widths[2], 6, f"{row.get('total_try', 0):,.2f}", border="B", fill=True, align="R")
            pdf.cell(widths[3], 6, f"{row.get('collected_try', 0):,.2f}", border="B", fill=True, align="R")
            pdf.cell(widths[4], 6, f"{row.get('outstanding_try', 0):,.2f}", border="B", fill=True, align="R")
            pdf.cell(widths[5], 6, f"{row.get('previous_debt', 0):,.2f}", border="B", fill=True, align="R")
            pdf.ln()
        pdf.ln(2)

    # KDV özeti
    if vat_summary:
        pdf._section_title("KDV ÖZETİ")
        widths = (30, 35, 35, 35)
        labels = ("KDV Oranı", "Brüt (₺)", "KDV (₺)", "Net (₺)")
        pdf.set_fill_color(*pdf.INK)
        pdf.set_text_color(*pdf.WHITE)
        pdf.set_font(pdf.default_font, "B", 6.5)
        for w, lbl in zip(widths, labels):
            pdf.cell(w, 7, lbl, border=0, fill=True, align="C")
        pdf.ln()
        for i, v in enumerate(vat_summary):
            pdf.set_fill_color(*(pdf.SURFACE if i % 2 == 0 else pdf.WHITE))
            pdf.set_text_color(*pdf.INK)
            pdf.set_font(pdf.default_font, "", 6.5)
            pdf.cell(widths[0], 6, v.get("label", ""), border="B", fill=True, align="C")
            pdf.cell(widths[1], 6, f"{v.get('gross', 0):,.2f}", border="B", fill=True, align="R")
            pdf.cell(widths[2], 6, f"{v.get('vat_amount', 0):,.2f}", border="B", fill=True, align="R")
            pdf.cell(widths[3], 6, f"{v.get('net', 0):,.2f}", border="B", fill=True, align="R")
            pdf.ln()
        pdf.ln(2)

    # Aging
    if aging_rows:
        pdf._section_title("Vadesine Göre Açık Alacaklar")
        widths = (80, 25, 35)
        labels = ("Dönem", "Adet", "Tutar (₺)")
        pdf.set_fill_color(*pdf.INK)
        pdf.set_text_color(*pdf.WHITE)
        pdf.set_font(pdf.default_font, "B", 6.5)
        for w, lbl in zip(widths, labels):
            pdf.cell(w, 7, lbl, border=0, fill=True, align="C")
        pdf.ln()
        for i, row in enumerate(aging_rows):
            pdf.set_fill_color(*(pdf.SURFACE if i % 2 == 0 else pdf.WHITE))
            pdf.set_text_color(*pdf.INK)
            pdf.set_font(pdf.default_font, "", 6.5)
            pdf.cell(widths[0], 6, row.get("label", ""), border="B", fill=True)
            pdf.cell(widths[1], 6, str(row.get("count", 0)), border="B", fill=True, align="C")
            pdf.cell(widths[2], 6, f"{row.get('amount', 0):,.2f}", border="B", fill=True, align="R")
            pdf.ln()

    output = pdf.output()
    return bytes(output) if isinstance(output, (bytes, bytearray)) else str(output).encode("latin-1", errors="ignore")


def generate_work_orders_pdf(
    clinic_name: str,
    clinic_phone: str,
    clinic_email: str,
    period_label: str,
    work_orders: list,
    doctor_count: int,
    period_total: Decimal,
) -> bytes:
    """İş emirleri defteri / listesi PDF çıktısı üret."""
    from app.services.reports_service import _parse_wo_items

    pdf = ReportPDF(clinic_name=clinic_name, clinic_phone=clinic_phone, clinic_email=clinic_email)
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.add_report_title(
        "İŞ EMİRLERİ LİSTESİ",
        f"Dönem: {period_label}  |  {len(work_orders)} İş Emri  |  {doctor_count} Doktor  |  Toplam: ₺{period_total:,.2f}"
    )

    widths = (20, 42, 42, 44, 19, 19)
    labels = ("Tarih", "Doktor", "Hasta", "Aparey / İşlem", "Ekstra", "Toplam (TL)")

    pdf.set_fill_color(*pdf.AQUA_DARK)
    pdf.set_text_color(*pdf.WHITE)
    pdf.set_font(pdf.default_font, "B", 7)

    pdf.cell(widths[0], 7, labels[0], fill=True)
    pdf.cell(widths[1], 7, labels[1], fill=True)
    pdf.cell(widths[2], 7, labels[2], fill=True)
    pdf.cell(widths[3], 7, labels[3], fill=True)
    pdf.cell(widths[4], 7, labels[4], align="R", fill=True)
    pdf.cell(widths[5], 7, labels[5], align="R", fill=True)
    pdf.ln()

    pdf.set_font(pdf.default_font, "", 6.5)
    pdf.set_text_color(*pdf.INK)
    fill = False

    for wo in work_orders:
        pdf.set_fill_color(*(pdf.SURFACE if fill else (255, 255, 255)))
        doctor_name = (wo.party.display_name if wo.party else "-")[:24]
        patient_name = (wo.patient_name or "-")[:24]

        items = _parse_wo_items(wo.apparatus_type)
        if items:
            apparatus_text = ", ".join(str(i.get("name", i) if isinstance(i, dict) else i) for i in items)[:30]
        else:
            apparatus_text = (wo.apparatus_type or "-")[:30]

        pdf.cell(widths[0], 6, wo.work_date.strftime("%d.%m.%Y"), border="B", fill=True)
        pdf.cell(widths[1], 6, doctor_name, border="B", fill=True)
        pdf.cell(widths[2], 6, patient_name, border="B", fill=True)
        pdf.cell(widths[3], 6, apparatus_text, border="B", fill=True)
        pdf.cell(widths[4], 6, f"{wo.extra_price:,.2f}", border="B", align="R", fill=True)
        pdf.cell(widths[5], 6, f"{wo.total_price:,.2f}", border="B", align="R", fill=True)
        pdf.ln()
        fill = not fill

    pdf.ln(2)
    pdf.set_font(pdf.default_font, "B", 7.5)
    pdf.set_fill_color(*pdf.SURFACE)
    pdf.cell(widths[0] + widths[1] + widths[2] + widths[3], 7, f"GENEL TOPLAM ({len(work_orders)} İş Emri)", fill=True)
    pdf.cell(widths[4], 7, "", fill=True)
    pdf.cell(widths[5], 7, f"{period_total:,.2f} TL", align="R", fill=True)

    output = pdf.output()
    return bytes(output) if isinstance(output, (bytes, bytearray)) else str(output).encode("latin-1", errors="ignore")


def generate_makbuz_list_pdf(
    clinic_name: str,
    clinic_phone: str,
    clinic_email: str,
    period_label: str,
    doctors: list,
    grand_total_price: Decimal,
) -> bytes:
    """Aylık hesap özeti listesi PDF çıktısı üret."""
    pdf = ReportPDF(clinic_name=clinic_name, clinic_phone=clinic_phone, clinic_email=clinic_email)
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.add_report_title(
        "AYLIK HESAP ÖZETİ LİSTESİ",
        f"Dönem: {period_label}  |  {len(doctors)} Doktor  |  Toplam Tutar: ₺{grand_total_price:,.2f}"
    )
    pdf.set_fill_color(*pdf.SURFACE)
    pdf.set_text_color(*pdf.MUTED)
    pdf.set_font(pdf.default_font, "", 7)
    pdf.multi_cell(0, 5, "Bilgilendirme amaçlıdır; resmi fatura veya makbuz değildir.", fill=True)
    pdf.ln(3)

    widths = (45, 20, 35, 35, 30)
    labels = ("Doktor", "İş Emri", "Tutar (TL)", "Durum", "KDV Oranı")

    pdf.set_fill_color(*pdf.AQUA_DARK)
    pdf.set_text_color(*pdf.WHITE)
    pdf.set_font(pdf.default_font, "B", 7)

    pdf.cell(widths[0], 7, labels[0], fill=True)
    pdf.cell(widths[1], 7, labels[1], align="C", fill=True)
    pdf.cell(widths[2], 7, labels[2], align="R", fill=True)
    pdf.cell(widths[3], 7, labels[3], align="C", fill=True)
    pdf.cell(widths[4], 7, labels[4], align="C", fill=True)
    pdf.ln()

    pdf.set_font(pdf.default_font, "", 6.5)
    pdf.set_text_color(*pdf.INK)
    fill = False

    for d in doctors:
        pdf.set_fill_color(*(pdf.SURFACE if fill else (255, 255, 255)))
        doc_name = (d["party"].display_name if d.get("party") else "-")[:26]
        m = d.get("makbuz")
        price = m.grand_total if m else d.get("total_price", Decimal("0.00"))

        status_text = "Gönderilmedi"
        if m:
            if m.status == "paid":
                status_text = "Ödendi"
            elif m.status == "sent":
                status_text = "Tahsilat bekliyor"
            elif m.status == "draft":
                status_text = "Taslak"

        vat_text = f"%{m.vat_rate:g}" if m and m.vat_applied else "-"

        pdf.cell(widths[0], 6, doc_name, border="B", fill=True)
        pdf.cell(widths[1], 6, str(d.get("count", 0)), border="B", fill=True, align="C")
        pdf.cell(widths[2], 6, f"{price:,.2f}", border="B", fill=True, align="R")
        pdf.cell(widths[3], 6, status_text, border="B", fill=True, align="C")
        pdf.cell(widths[4], 6, vat_text, border="B", fill=True, align="C")
        pdf.ln()
        fill = not fill

    pdf.ln(2)
    pdf.set_font(pdf.default_font, "B", 7.5)
    pdf.set_fill_color(*pdf.SURFACE)
    pdf.cell(widths[0] + widths[1], 7, f"GENEL TOPLAM ({len(doctors)} Doktor)", fill=True)
    pdf.cell(widths[2], 7, f"{grand_total_price:,.2f} TL", align="R", fill=True)
    pdf.cell(widths[3] + widths[4], 7, "", fill=True)

    output = pdf.output()
    return bytes(output) if isinstance(output, (bytes, bytearray)) else str(output).encode("latin-1", errors="ignore")


def generate_kdv_doctors_pdf(
    clinic_name: str,
    clinic_phone: str,
    clinic_email: str,
    period_label: str,
    kdv_doctors_data: list[dict],
) -> bytes:
    """Generate a clean PDF report listing KDV-paying doctors and their monthly work volume & VAT amounts."""
    pdf = ReportPDF(clinic_name=clinic_name, clinic_phone=clinic_phone, clinic_email=clinic_email)
    pdf.alias_nb_pages()
    pdf.add_page()

    total_net = sum((d["net_total"] for d in kdv_doctors_data), Decimal("0.00"))
    total_vat = sum((d["vat_total"] for d in kdv_doctors_data), Decimal("0.00"))
    total_grand = sum((d["grand_total"] for d in kdv_doctors_data), Decimal("0.00"))

    pdf.add_report_title(
        "KDV UYGULANAN DOKTORLAR - AYLIK RAPOR",
        f"Dönem: {period_label}  |  {len(kdv_doctors_data)} KDV'li Doktor  |  Toplam KDV: ₺{total_vat:,.2f}"
    )

    pdf.set_fill_color(*pdf.SURFACE)
    pdf.set_text_color(*pdf.MUTED)
    pdf.set_font(pdf.default_font, "", 7)
    pdf.multi_cell(
        0,
        5,
        "Bilgilendirme: Bu rapor muhasebe hazırlığı içindir. Aylık hesap özetleri resmi fatura veya makbuz yerine geçmez.",
        fill=True,
    )
    pdf.ln(3)

    widths = (52, 28, 18, 30, 30, 32)
    labels = ("Doktor Adı", "Vergi No", "İş Emri", "Matrah (TL)", "KDV (TL)", "Toplam (TL)")

    pdf.set_fill_color(*pdf.AQUA_DARK)
    pdf.set_text_color(*pdf.WHITE)
    pdf.set_font(pdf.default_font, "B", 7)

    pdf.cell(widths[0], 7, labels[0], fill=True)
    pdf.cell(widths[1], 7, labels[1], align="C", fill=True)
    pdf.cell(widths[2], 7, labels[2], align="R", fill=True)
    pdf.cell(widths[3], 7, labels[3], align="R", fill=True)
    pdf.cell(widths[4], 7, labels[4], align="R", fill=True)
    pdf.cell(widths[5], 7, labels[5], align="C", fill=True)
    pdf.ln()

    pdf.set_font(pdf.default_font, "", 6.5)
    pdf.set_text_color(*pdf.INK)
    fill = False

    for d in kdv_doctors_data:
        pdf.set_fill_color(*(pdf.SURFACE if fill else (255, 255, 255)))
        doc_name = (d["name"])[:32]
        tax_id = (d.get("tax_id") or "-")[:15]
        work_order_count = d.get("work_order_count", 0)
        net = d["net_total"]
        vat = d["vat_total"]
        grand = d["grand_total"]

        pdf.cell(widths[0], 6, doc_name, border="B", fill=True)
        pdf.cell(widths[1], 6, tax_id, border="B", fill=True, align="C")
        pdf.cell(widths[2], 6, str(work_order_count), border="B", fill=True, align="C")
        pdf.cell(widths[3], 6, f"{net:,.2f}", border="B", fill=True, align="R")
        pdf.cell(widths[4], 6, f"{vat:,.2f}", border="B", fill=True, align="R")
        pdf.cell(widths[5], 6, f"{grand:,.2f}", border="B", fill=True, align="R")
        pdf.ln()
        fill = not fill

    pdf.ln(2)
    pdf.set_font(pdf.default_font, "B", 7.5)
    pdf.set_fill_color(*pdf.SURFACE)
    pdf.cell(widths[0] + widths[1] + widths[2], 7, f"GENEL TOPLAM ({len(kdv_doctors_data)} Doktor)", fill=True)
    pdf.cell(widths[3], 7, f"{total_net:,.2f} TL", align="R", fill=True)
    pdf.cell(widths[4], 7, f"{total_vat:,.2f} TL", align="R", fill=True)
    pdf.cell(widths[5], 7, f"{total_grand:,.2f} TL", align="R", fill=True)

    output = pdf.output()
    return bytes(output) if isinstance(output, (bytes, bytearray)) else str(output).encode("latin-1", errors="ignore")
