import json

from fpdf.enums import MethodReturnValue, XPos, YPos

from app.services.base_pdf import LOGO_PATH, BasePDF
from app.services.validation_service import normalize_optional_text

CURRENCY_SYMBOLS = {"TL": "₺", "EUR": "€", "USD": "$"}



def _item_lines(raw: str | None, bullet: str = "•") -> list[str]:
    """Same source data as _format_items, but one line per item for the PDF table."""
    raw = normalize_optional_text(raw)
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return [f"{bullet} {raw}"]
    if not isinstance(items, list) or not items:
        return [f"{bullet} {raw}"]
    lines = []
    for item in items:
        if isinstance(item, dict):
            symbol = CURRENCY_SYMBOLS.get(item.get("currency", "TL"), "₺")
            lines.append(f"{bullet} {item.get('name', '')}  {symbol}{float(item.get('price', 0)):,.2f}")
        else:
            lines.append(f"{bullet} {item}")
    return lines


from app.constants import MONTH_NAMES


class MakbuzPDF(BasePDF):

    def __init__(self, clinic_name="Makro Ortodonti", clinic_phone="", clinic_email=""):
        super().__init__()
        self.clinic_name = clinic_name
        self.clinic_phone = clinic_phone
        self.clinic_email = clinic_email

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
        self.set_font(self.default_font, "B", 10)
        self.set_text_color(*self.AQUA_DARK)
        self.cell(53, 8, "AYLIK HESAP ÖZETİ", align="R")

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
        self.cell(140, 6, "Bilgilendirme amaçlıdır; resmi fatura veya makbuz değildir.")
        self.cell(46, 6, f"Sayfa {self.page_no()}/{{nb}}", align="R")

    def add_summary(self, makbuz, doctor_name):
        y = self.get_y()
        self.set_fill_color(*self.SURFACE)
        self.set_draw_color(*self.LINE)
        self.rect(12, y, 186, 24, style="DF")

        self.set_xy(18, y + 5)
        self.set_font(self.default_font, "B", 7)
        self.set_text_color(*self.AQUA_DARK)
        self.cell(90, 5, "HESAP ÖZETİ GÖNDERİLEN DOKTOR")
        self.set_xy(18, y + 11)
        self.set_font(self.default_font, "B", 11)
        self.set_text_color(*self.INK)
        self.cell(90, 6, doctor_name[:48])

        period = f"{MONTH_NAMES[makbuz.month]} {makbuz.year}"
        self.set_xy(118, y + 5)
        self.set_font(self.default_font, "", 6.7)
        self.set_text_color(*self.MUTED)
        self.cell(35, 5, "Dönem")
        self.set_font(self.default_font, "B", 6.7)
        self.set_text_color(*self.INK)
        self.cell(33, 5, period, align="R")

        self.set_xy(118, y + 11)
        self.set_font(self.default_font, "", 6.7)
        self.set_text_color(*self.MUTED)
        self.cell(35, 5, "İş emri sayısı")
        self.set_font(self.default_font, "B", 6.7)
        self.set_text_color(*self.INK)
        self.cell(33, 5, str(makbuz.work_order_count), align="R")

        self.set_xy(118, y + 17)
        self.set_font(self.default_font, "", 6.7)
        self.set_text_color(*self.MUTED)
        self.cell(35, 5, "Düzenlenme tarihi")
        self.set_font(self.default_font, "B", 6.7)
        self.set_text_color(*self.INK)
        self.cell(33, 5, makbuz.generated_at.strftime("%d.%m.%Y"), align="R")

        self.set_y(y + 30)

    TABLE_WIDTHS = (20, 36, 64, 22, 22, 22)

    def _table_header(self):
        labels = ("Tarih", "Hasta", "Yapılan İşlemler", "Aparey (₺)", "Ekstra (₺)", "Toplam (₺)")
        self.set_fill_color(*self.INK)
        self.set_text_color(255, 255, 255)
        self.set_font(self.default_font, "B", 7)
        for width, label in zip(self.TABLE_WIDTHS, labels):
            align = "R" if "(₺)" in label else "L"
            self.cell(width, 8, label, border=0, fill=True, align=align)
        self.ln()

    def add_items_table(self, work_orders):
        self.set_font(self.default_font, "B", 9)
        self.set_text_color(*self.AQUA_DARK)
        self.cell(0, 7, "İŞ EMİRLERİ", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self._table_header()
        widths = self.TABLE_WIDTHS
        line_h = 4.2
        for index, wo in enumerate(work_orders):
            detail = "\n".join(_item_lines(wo.apparatus_type) + _item_lines(wo.extra_addons, bullet="+")) or "-"
            self.set_font(self.default_font, "", 7.2)
            detail_lines = self.multi_cell(widths[2] - 3, line_h, detail, dry_run=True, output=MethodReturnValue.LINES)
            name_lines = self.multi_cell(widths[1] - 2, line_h, wo.patient_name, dry_run=True, output=MethodReturnValue.LINES)
            row_h = max(8.0, line_h * max(len(detail_lines), len(name_lines)) + 3.2)

            if self.get_y() + row_h > 262:
                self.add_page()
                self._table_header()
                self.set_font(self.default_font, "", 7.2)

            x0, y0 = self.l_margin, self.get_y()
            self.set_fill_color(*(self.SURFACE if index % 2 == 0 else (255, 255, 255)))
            self.rect(x0, y0, sum(widths), row_h, style="F")
            self.set_text_color(*self.INK)

            self.set_xy(x0, y0 + 1.6)
            self.cell(widths[0], line_h, wo.work_date.strftime("%d.%m.%Y"))
            self.set_xy(x0 + widths[0], y0 + 1.6)
            self.multi_cell(widths[1] - 2, line_h, wo.patient_name, align="L")
            self.set_xy(x0 + widths[0] + widths[1], y0 + 1.6)
            self.multi_cell(widths[2] - 3, line_h, detail, align="L")
            self.set_xy(x0 + widths[0] + widths[1] + widths[2], y0 + 1.6)
            self.cell(widths[3], line_h, f"{wo.apparatus_price:,.2f}", align="R")
            self.cell(widths[4], line_h, f"{wo.extra_price:,.2f}", align="R")
            self.cell(widths[5], line_h, f"{wo.total_price:,.2f}", align="R")

            self.set_draw_color(*self.LINE)
            self.line(x0, y0 + row_h, x0 + sum(widths), y0 + row_h)
            self.set_y(y0 + row_h)

    def add_totals(self, makbuz, statement):
        required_height = 48 + len(statement.previous_periods) * 8
        if self.get_y() + required_height > 266:
            self.add_page()
        self.ln(4)

        self.set_font(self.default_font, "B", 9)
        self.set_text_color(*self.AQUA_DARK)
        self.cell(0, 7, "BAKİYE DÖKÜMÜ", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        x_label = 112
        carried_forward_balance = statement.previous_balance
        if makbuz.party and makbuz.party.previous_balance_outstanding > 0:
            carried_forward_balance += makbuz.party.previous_balance_outstanding

        rows = [("Bu dönem işlem toplamı", f"₺{makbuz.grand_total:,.2f}", False)]
        if carried_forward_balance > 0:
            rows.append(("Devreden borç", f"₺{carried_forward_balance:,.2f}", False))
        if statement.current_collected > 0:
            rows.append(("Bu dönem tahsil edilen", f"-₺{statement.current_collected:,.2f}", False))
            rows.append(("Bu dönem kalan", f"₺{statement.current_outstanding:,.2f}", True))
        for label, value, bold in rows:
            self.set_x(x_label)
            self.set_font(self.default_font, "B" if bold else "", 8)
            self.set_text_color(*self.MUTED if not bold else self.INK)
            self.cell(51, 7, label, align="R")
            self.set_text_color(*self.INK)
            self.cell(35, 7, value, align="R")
            self.ln()

        if statement.previous_periods:
            self.ln(2)
            self.set_fill_color(*self.SKY_PALE)
            self.set_text_color(*self.INK)
            self.set_font(self.default_font, "B", 7.5)
            self.cell(48, 8, "Önceki açık dönem", fill=True)
            self.cell(46, 8, "Dönem toplamı", fill=True, align="R")
            self.cell(46, 8, "Tahsil edilen", fill=True, align="R")
            self.cell(46, 8, "Kalan", fill=True, align="R")
            self.ln()
            for period in statement.previous_periods:
                self.set_font(self.default_font, "", 7.5)
                self.set_text_color(*self.INK)
                self.cell(48, 7, period.period_label)
                self.cell(46, 7, f"₺{period.original_total:,.2f}", align="R")
                self.cell(46, 7, f"-₺{period.collected:,.2f}", align="R")
                self.set_font(self.default_font, "B", 7.5)
                self.cell(46, 7, f"₺{period.outstanding:,.2f}", align="R")
                self.ln()

        self.ln(3)
        self.set_x(112)
        self.set_fill_color(*self.AQUA_DARK)
        self.set_text_color(255, 255, 255)
        self.set_font(self.default_font, "B", 10)
        self.cell(51, 11, "TOPLAM AÇIK BAKİYE", fill=True, align="R")
        self.cell(35, 11, f"₺{statement.total_due:,.2f}", fill=True, align="R")
        self.ln()


def generate_makbuz_pdf(makbuz, work_orders) -> bytes:
    from app.extensions import db
    from app.models.models import Settings
    from app.services.makbuz_account_service import account_statement

    def get_setting(key, default=""):
        value = db.session.execute(
            db.select(Settings.value).where(Settings.key == key)
        ).scalar_one_or_none()
        return value or default

    pdf = MakbuzPDF(
        clinic_name=get_setting("clinic_name", "Makro Ortodonti"),
        clinic_phone=get_setting("clinic_phone"),
        clinic_email=get_setting("clinic_email"),
    )
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.add_summary(makbuz, makbuz.party.name if makbuz.party else "Bilinmeyen doktor")
    pdf.add_items_table(work_orders)
    pdf.add_totals(makbuz, account_statement(makbuz))

    output = pdf.output()
    return bytes(output) if isinstance(output, (bytes, bytearray)) else str(output).encode("latin-1", errors="ignore")
