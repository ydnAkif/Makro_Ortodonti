import os

from fpdf import FPDF

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "fonts")
FONT_PATH = os.path.join(FONT_DIR, "DejaVuSans.ttf")
FONT_PATH_BOLD = os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")
LOGO_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "images", "brand-mark.svg")


class BasePDF(FPDF):
    INK = (16, 46, 58)
    MUTED = (88, 113, 123)
    AQUA = (32, 166, 162)
    AQUA_DARK = (24, 140, 138)
    AQUA_PALE = (230, 247, 245)
    SKY_PALE = (235, 247, 250)
    LINE = (220, 232, 233)
    SURFACE = (247, 250, 250)
    DANGER = (207, 91, 98)
    WHITE = (255, 255, 255)

    def __init__(self):
        super().__init__()
        self.default_font = "Helvetica"
        if os.path.exists(FONT_PATH):
            try:
                self.add_font("DejaVu", "", FONT_PATH)
                if os.path.exists(FONT_PATH_BOLD):
                    self.add_font("DejaVu", "B", FONT_PATH_BOLD)
                self.default_font = "DejaVu"
            except Exception:
                self.default_font = "Helvetica"
        self.set_margins(12, 15, 12)
        self.set_auto_page_break(auto=True, margin=24)

    def _safe_text(self, text):
        value = "" if text is None else str(text)
        if self.default_font == "DejaVu":
            return value
        replacements = {
            "₺": "TRY ", "€": "EUR ", "ı": "i", "İ": "I", "ş": "s",
            "Ş": "S", "ğ": "g", "Ğ": "G", "ü": "u", "Ü": "U",
            "ö": "o", "Ö": "O", "ç": "c", "Ç": "C",
        }
        for source, target in replacements.items():
            value = value.replace(source, target)
        return value.encode("cp1252", errors="replace").decode("cp1252")

    def draw_header_banner(self, clinic_name: str, contacts_text: str, document_title: str, subtitle: str = ""):
        """Draw shared header with logo, clinic identity, document title, and divider line."""
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
        self.cell(104, 7, clinic_name)
        self.set_xy(35, 18)
        self.set_font(self.default_font, "", 7.5)
        self.set_text_color(*self.MUTED)
        self.cell(104, 5, contacts_text or "Ortodonti ve klinik hizmetleri")

        self.set_xy(145, 10)
        self.set_font(self.default_font, "B", 16)
        self.set_text_color(*self.AQUA_DARK)
        self.cell(53, 8, document_title, align="R")
        if subtitle:
            self.set_xy(145, 19)
            self.set_font(self.default_font, "", 7)
            self.set_text_color(*self.MUTED)
            self.cell(53, 5, subtitle, align="R")

        self.set_draw_color(*self.LINE)
        self.set_line_width(.35)
        self.line(12, 32, 198, 32)
        self.set_y(38)

    def draw_footer_bar(self, footer_text: str = ""):
        """Draw shared footer bar with optional footer text and page numbers."""
        self.set_y(-19)
        self.set_draw_color(*self.LINE)
        self.set_line_width(.35)
        self.line(12, self.get_y(), 198, self.get_y())
        self.set_y(-16)
        self.set_font(self.default_font, "", 7.5)
        self.set_text_color(*self.MUTED)
        if footer_text:
            self.cell(120, 5, footer_text)
            self.cell(66, 5, f"Sayfa {self.page_no()}", align="R")
        else:
            self.cell(186, 5, f"Sayfa {self.page_no()}", align="R")

