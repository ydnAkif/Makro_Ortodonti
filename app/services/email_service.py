import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from flask import current_app

from app.extensions import db
from app.models.models import Settings


def get_smtp_config() -> dict:
    config = {}
    for key, default in [
        ("smtp_server", "smtp.gmail.com"),
        ("smtp_port", "587"),
        ("smtp_username", ""),
        ("smtp_password", ""),
    ]:
        val = db.session.execute(
            db.select(Settings.value).where(Settings.key == key)
        ).scalar_one_or_none()
        
        if key == "smtp_password" and val:
            from app.services.security_service import decrypt_value
            val = decrypt_value(val)
            
        config[key] = val or default
    return config


def send_invoice_email(invoice) -> tuple[bool, str]:
    # Support both party and legacy patient invoices
    recipient_email = None
    recipient_name = None
    if invoice.party and invoice.party.email:
        recipient_email = invoice.party.email
        recipient_name = invoice.party.display_name
    elif invoice.patient and invoice.patient.email:
        recipient_email = invoice.patient.email
        recipient_name = invoice.patient.full_name

    if not recipient_email:
        return False, "Müşterinin e-posta adresi bulunmuyor."

    try:
        smtp_config = get_smtp_config()
        if not smtp_config["smtp_username"] or not smtp_config["smtp_password"]:
            return False, "SMTP ayarları yapılandırılmamış."

        from app.services.pdf_service import generate_invoice_pdf
        pdf_bytes = generate_invoice_pdf(invoice)

        msg = MIMEMultipart()
        msg["From"] = smtp_config["smtp_username"]
        msg["To"] = recipient_email
        msg["Subject"] = f"Fatura - {invoice.invoice_number}"

        body = f"""Sayın {recipient_name},

{invoice.invoice_date.strftime('%d.%m.%Y')} tarihli {invoice.invoice_number} numaralı faturanız ekte gönderilmiştir.

Toplam Tutar: ₺{invoice.total_try:,.2f} (€{invoice.total_eur:,.2f})
{"Son Ödeme Tarihi: " + invoice.due_date.strftime('%d.%m.%Y') if invoice.due_date else ""}

Ödeme durumunuzla ilgili sorularınız için bizimle iletişime geçebilirsiniz.

Saygılarımızla,
Makro Ortodonti"""

        msg.attach(MIMEText(body, "plain", "utf-8"))

        pdf_attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
        pdf_attachment.add_header(
            "Content-Disposition",
            "attachment",
            filename=f"fatura_{invoice.invoice_number}.pdf",
        )
        msg.attach(pdf_attachment)

        server = smtplib.SMTP(smtp_config["smtp_server"], int(smtp_config["smtp_port"]))
        server.starttls()
        server.login(smtp_config["smtp_username"], smtp_config["smtp_password"])
        server.send_message(msg)
        server.quit()

        return True, "E-posta başarıyla gönderildi."

    except ValueError:
        return False, "SMTP şifresi çözülemedi. Ayarlar ekranından şifreyi yeniden kaydedin."
    except Exception as exc:
        current_app.logger.exception("Fatura e-postası gönderilemedi")
        return False, f"E-posta gönderilemedi: {exc}"
