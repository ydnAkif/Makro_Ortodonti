"""WhatsApp service using Neonize for free message sending.

Threading model: ``NewClient.connect()`` is a blocking call, so the client
runs in a single background daemon thread per process. Event handlers (QR,
PairStatus, Connected, ...) are invoked from Neonize's own threads and only
touch the DB through ``_update_session_row``, which pushes a Flask app
context. Send methods are safe to call from Flask request threads; they are
serialized through ``_send_lock``.

Deployment: exactly one process may own the WhatsApp client — the session
store (data/whatsapp_session.db) cannot be shared. Run gunicorn with a
single worker (``--workers 1``). As a safety net, client startup takes an
exclusive flock on data/whatsapp.worker.lock; extra workers skip the client
and their sends fail with a clear message instead of corrupting the session.
"""

import logging
import os
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Optional

from flask import has_app_context

from app.extensions import db
from app.models.models import WhatsAppSession

logger = logging.getLogger(__name__)


class WhatsAppService:
    _app = None  # Flask app, for DB access from Neonize's callback threads
    _client = None
    _thread = None  # daemon thread blocked inside client.connect()
    _connected = False
    _qr_code: Optional[str] = None  # current QR payload while pairing
    _pair_code: Optional[str] = None  # current pair code while pairing
    _state_lock = threading.RLock()
    _send_lock = threading.Lock()
    _pair_wait_seconds = 30.0  # how long PairPhone waits for pairing mode
    _process_lock_handle = None  # flock handle marking this process as owner
    _session_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data",
    )

    # ------------------------------------------------------------------ setup

    @classmethod
    def session_db_path(cls) -> str:
        return os.path.join(cls._session_dir, "whatsapp_session.db")

    @classmethod
    def init_app(cls, app) -> None:
        """Store the app and auto-reconnect if a paired session exists."""
        cls._app = app
        if app.testing or not app.config.get("WHATSAPP_AUTO_CONNECT", True):
            return
        # Under the werkzeug reloader only the child process serves requests.
        if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
            return
        if os.path.exists(cls.session_db_path()):
            # NewClient loads a native library; don't delay app startup.
            threading.Thread(
                target=cls.start, name="whatsapp-autoconnect", daemon=True
            ).start()

    @classmethod
    def get_client(cls):
        with cls._state_lock:
            if cls._client is None:
                try:
                    from neonize.client import NewClient

                    os.makedirs(cls._session_dir, exist_ok=True)
                    cls._client = NewClient(cls.session_db_path())
                except Exception as e:
                    logger.error("WhatsApp client creation error: %s", e)
                    return None
            return cls._client

    @classmethod
    def _acquire_process_lock(cls) -> bool:
        """Only one process may own the Neonize client (see module docstring)."""
        if cls._process_lock_handle is not None:
            return True

        os.makedirs(cls._session_dir, exist_ok=True)
        lock_path = os.path.join(cls._session_dir, "whatsapp.worker.lock")
        handle = open(lock_path, "w")

        try:
            try:
                import fcntl
            except ImportError:
                fcntl = None

            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                try:
                    import msvcrt
                except ImportError:
                    cls._process_lock_handle = handle
                    return True
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except (OSError, AttributeError):
            try:
                handle.close()
            except Exception:
                pass
            return False

        cls._process_lock_handle = handle
        return True

    # ------------------------------------------------------- connection flow

    @classmethod
    def start(cls) -> bool:
        """Start the background client thread. Returns False if another
        process owns the client or the client cannot be created."""
        with cls._state_lock:
            if cls._thread is not None and cls._thread.is_alive():
                return True
            if not cls._acquire_process_lock():
                logger.warning(
                    "WhatsApp istemcisi başka bir worker tarafından kullanılıyor; "
                    "bu worker'da başlatılmadı. Gunicorn'u tek worker ile çalıştırın."
                )
                return False
            client = cls.get_client()
            if client is None:
                return False
            cls._client = client
            cls._register_handlers(client)
            cls._thread = threading.Thread(
                target=cls._run, args=(client,), name="whatsapp-client", daemon=True
            )
            cls._thread.start()
            return True

    @classmethod
    def _register_handlers(cls, client) -> None:
        from neonize.events import (
            ConnectedEv,
            DisconnectedEv,
            LoggedOutEv,
            PairStatusEv,
        )

        client.event.qr(cls._on_qr)
        client.event(ConnectedEv)(cls._on_connected)
        client.event(PairStatusEv)(cls._on_pair_status)
        client.event(DisconnectedEv)(cls._on_disconnected)
        client.event(LoggedOutEv)(cls._on_logged_out)

    @classmethod
    def _run(cls, client) -> None:
        try:
            client.connect()  # blocks until stop() / logout
        except Exception as e:
            logger.error("WhatsApp bağlantı hatası: %s", e)
        finally:
            with cls._state_lock:
                cls._connected = False
                cls._qr_code = None
                cls._pair_code = None
                if cls._client is client:
                    cls._client = None
                    cls._thread = None
            cls._update_session_row(
                status=WhatsAppSession.STATUS_DISCONNECTED,
                disconnected_at=datetime.now(timezone.utc).replace(tzinfo=None),
                qr_code=None,
            )

    # -------------------------------------------------------- event handlers
    # Called from Neonize's threads: never raise, DB only via helper.

    @classmethod
    def _on_qr(cls, client, data_qr: bytes) -> None:
        qr = data_qr.decode("utf-8", "replace")
        with cls._state_lock:
            cls._qr_code = qr
            cls._connected = False
        cls._update_session_row(
            status=WhatsAppSession.STATUS_CONNECTING, qr_code=qr
        )

    @classmethod
    def _on_pair_status(cls, client, event) -> None:
        phone = None
        try:
            phone = event.ID.User or None
        except Exception:
            pass
        with cls._state_lock:
            cls._qr_code = None
            cls._pair_code = None
        if phone:
            cls._update_session_row(phone_number=phone, qr_code=None)

    @classmethod
    def _on_connected(cls, client, event) -> None:
        with cls._state_lock:
            cls._connected = True
            cls._qr_code = None
            cls._pair_code = None
        fields = {
            "status": WhatsAppSession.STATUS_CONNECTED,
            "connected_at": datetime.now(timezone.utc).replace(tzinfo=None),
            "qr_code": None,
        }
        try:
            me = getattr(client, "me", None)
            if me is not None and me.JID.User:
                fields["phone_number"] = me.JID.User
        except Exception:
            pass
        cls._update_session_row(**fields)
        logger.info("WhatsApp bağlandı.")

    @classmethod
    def _on_disconnected(cls, client, event) -> None:
        # Transient drop; whatsmeow reconnects on its own. Block sends until
        # the next Connected event.
        with cls._state_lock:
            cls._connected = False
        logger.warning("WhatsApp bağlantısı koptu, yeniden bağlanılıyor.")

    @classmethod
    def _on_logged_out(cls, client, event) -> None:
        # The phone unlinked this device; a new QR scan is required.
        with cls._state_lock:
            cls._connected = False
            cls._qr_code = None
            cls._pair_code = None
        cls._update_session_row(
            status=WhatsAppSession.STATUS_DISCONNECTED,
            disconnected_at=datetime.now(timezone.utc).replace(tzinfo=None),
            qr_code=None,
        )
        logger.warning("WhatsApp oturumu telefondan kapatıldı; yeniden QR taraması gerekiyor.")

    @classmethod
    def _update_session_row(cls, **fields) -> None:
        def _apply():
            try:
                session = db.session.execute(
                    db.select(WhatsAppSession).where(
                        WhatsAppSession.session_id == "default"
                    )
                ).scalar_one_or_none()
                if session is None:
                    session = WhatsAppSession(session_id="default")
                    db.session.add(session)
                for key, value in fields.items():
                    setattr(session, key, value)
                db.session.commit()
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                raise

        try:
            if cls._app is not None:
                with cls._app.app_context():
                    _apply()
            else:
                _apply()
        except Exception:
            logger.exception("WhatsApp oturum kaydı güncellenemedi")

    # ------------------------------------------------------------ public API

    @classmethod
    def connect(cls, phone_number: Optional[str] = None) -> dict:
        """Start the connection flow. Returns immediately; the UI polls
        /whatsapp/status for the QR code / pair code / connected state."""
        try:
            cls._update_session_row(status=WhatsAppSession.STATUS_CONNECTING)
            if not cls.start():
                return {
                    "success": False,
                    "message": (
                        "WhatsApp istemcisi başlatılamadı. İstemci başka bir "
                        "worker'da çalışıyor olabilir (tek worker gerekli)."
                    ),
                }
            if phone_number:
                clean = (
                    phone_number.replace("+", "").replace(" ", "").replace("-", "")
                )
                threading.Thread(
                    target=cls._request_pair_code,
                    args=(clean,),
                    name="whatsapp-paircode",
                    daemon=True,
                ).start()
                return {
                    "success": True,
                    "message": "Eşleştirme kodu isteniyor, lütfen bekleyin.",
                }
            return {
                "success": True,
                "message": "QR kod oluşturuluyor. Lütfen WhatsApp'tan QR kodu tarayın.",
            }
        except Exception as e:
            return {"success": False, "message": f"Hata: {str(e)}"}

    @classmethod
    def _request_pair_code(cls, phone: str) -> None:
        # PairPhone needs the socket up; wait until the first QR arrives
        # (pairing mode) or we are already connected.
        deadline = time.monotonic() + cls._pair_wait_seconds
        while time.monotonic() < deadline:
            with cls._state_lock:
                if cls._connected:
                    return
                if cls._qr_code is not None:
                    break
            time.sleep(0.5)
        client = cls._client
        if client is None:
            return
        try:
            code = client.PairPhone(phone, show_push_notification=True)
            with cls._state_lock:
                cls._pair_code = code
            cls._update_session_row(phone_number=phone)
        except Exception as e:
            logger.error("Pair code alınamadı: %s", e)

    @classmethod
    def disconnect(cls) -> dict:
        try:
            with cls._state_lock:
                client = cls._client
                cls._connected = False
                cls._qr_code = None
                cls._pair_code = None
            if client is not None:
                try:
                    client.stop()  # unblocks connect(); _run() cleans up
                except Exception as e:
                    logger.warning("WhatsApp istemcisi durdurulamadı: %s", e)
            cls._update_session_row(
                status=WhatsAppSession.STATUS_DISCONNECTED,
                disconnected_at=datetime.now(timezone.utc).replace(tzinfo=None),
                qr_code=None,
            )
            return {"success": True, "message": "WhatsApp bağlantısı kesildi."}
        except Exception as e:
            return {"success": False, "message": f"Hata: {str(e)}"}

    @classmethod
    def quick_state(cls) -> str:
        """Cheap in-memory state for UI badges; never touches the DB."""
        with cls._state_lock:
            if cls._connected:
                return "connected"
            if cls._thread is not None and cls._thread.is_alive():
                return "connecting"
            return "disconnected"

    @classmethod
    def get_status(cls) -> dict:
        with cls._state_lock:
            connected = cls._connected
            qr = cls._qr_code
            pair_code = cls._pair_code
            connecting = (
                not connected
                and cls._thread is not None
                and cls._thread.is_alive()
            )

        session = None
        try:
            session = db.session.execute(
                db.select(WhatsAppSession).where(
                    WhatsAppSession.session_id == "default"
                )
            ).scalar_one_or_none()
        except Exception:
            logger.debug("WhatsApp oturum kaydı okunamadı", exc_info=True)

        if connected:
            status = WhatsAppSession.STATUS_CONNECTED
        elif connecting:
            status = WhatsAppSession.STATUS_CONNECTING
        else:
            status = session.status if session else WhatsAppSession.STATUS_DISCONNECTED

        qr_image = None
        if qr:
            try:
                import segno

                qr_image = segno.make_qr(qr).png_data_uri(scale=5)
            except Exception:
                logger.debug("QR görseli üretilemedi", exc_info=True)

        return {
            "connected": connected,
            "connecting": connecting,
            "status": status,
            "phone_number": session.phone_number if session else None,
            "connected_at": session.connected_at if session else None,
            "qr": qr,
            "qr_image": qr_image,
            "pair_code": pair_code,
        }

    # -------------------------------------------------------------- sending

    @classmethod
    def _build_jid(cls, phone_number: str):
        from neonize.utils.jid import build_jid

        clean_phone = phone_number.replace("+", "").replace(" ", "").replace("-", "")
        return build_jid(clean_phone)

    @classmethod
    def send_message(cls, phone_number: str, message: str) -> dict:
        """Send a text message to a phone number."""
        try:
            if not cls._connected:
                return {"success": False, "message": "WhatsApp bağlı değil."}
            client = cls.get_client()
            if client is None:
                return {"success": False, "message": "WhatsApp istemcisi mevcut değil."}

            with cls._send_lock:
                client.send_message(cls._build_jid(phone_number), message)
            return {"success": True, "message": f"Mesaj gönderildi: {phone_number}"}

        except Exception as e:
            return {"success": False, "message": f"Gönderim hatası: {str(e)}"}

    @classmethod
    def send_document(cls, phone_number: str, file_bytes: bytes, filename: str, caption: str = "") -> dict:
        """Send a document (e.g. PDF) to a phone number."""
        try:
            if not cls._connected:
                return {"success": False, "message": "WhatsApp bağlı değil."}
            client = cls.get_client()
            if client is None:
                return {"success": False, "message": "WhatsApp istemcisi mevcut değil."}

            with cls._send_lock:
                client.send_document(
                    cls._build_jid(phone_number),
                    file_bytes,
                    caption=caption,
                    filename=filename,
                    mimetype="application/pdf",
                )
            return {"success": True, "message": f"Belge gönderildi: {phone_number}"}

        except Exception as e:
            return {"success": False, "message": f"Belge gönderim hatası: {str(e)}"}

    @classmethod
    def send_makbuz_message(cls, makbuz, pdf_bytes: bytes) -> dict:
        """Send a monthly doctor receipt (özet metin + PDF) via WhatsApp."""
        party = makbuz.party
        if not party or not party.phone:
            return {"success": False, "message": "Doktorun telefon numarası bulunmuyor."}

        month_names = [
            "", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
            "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
        ]
        period = f"{month_names[makbuz.month]} {makbuz.year}"

        from app.services.makbuz_account_service import account_statement

        def _safe_decimal(val) -> Decimal:
            if isinstance(val, Decimal):
                return val
            if isinstance(val, (int, float)):
                return Decimal(str(val))
            if isinstance(val, str):
                try:
                    return Decimal(val)
                except Exception:
                    return Decimal("0.00")
            return Decimal("0.00")

        if has_app_context():
            statement = account_statement(makbuz)
        else:
            current_total = _safe_decimal(getattr(makbuz, 'grand_total', 0))
            subtotal_val = _safe_decimal(getattr(makbuz, 'subtotal', 0))
            vat_val = _safe_decimal(getattr(makbuz, 'vat_amount', 0))
            statement = SimpleNamespace(
                previous_periods=[],
                previous_balance=Decimal("0.00"),
                party_previous_balance=Decimal("0.00"),
                carried_over_balance=Decimal("0.00"),
                current_work_subtotal=subtotal_val,
                current_vat_amount=vat_val,
                current_month_total=current_total,
                current_collected=Decimal("0.00"),
                current_outstanding=current_total,
                total_due=current_total,
            )

        vat_rate_val = _safe_decimal(getattr(makbuz, 'vat_rate', 0))
        vat_amount_val = _safe_decimal(getattr(makbuz, 'vat_amount', 0))
        vat_text = f"• Bu Ayın KDV'si (%{vat_rate_val:g}): ₺{vat_amount_val:,.2f}\n" if makbuz.vat_applied else ""
        carried_text = f"• Devreden Borç: ₺{statement.carried_over_balance:,.2f}\n" if statement.carried_over_balance > 0 else ""
        prev_periods_text = ""
        if statement.previous_periods:
            lines = ["Önceki dönemlerden kalanlar:"]
            for open_period in statement.previous_periods:
                lines.append(
                    f"{open_period.period_label}: ₺{open_period.original_total:,.2f} hesap özeti"
                    f" - ₺{open_period.collected:,.2f} tahsilat"
                    f" = ₺{open_period.outstanding:,.2f} kalan"
                )
            prev_periods_text = "\n".join(lines) + "\n"

        message = f"""Sayın Dr. {party.name},

{period} dönemi hesap özetiniz:

• Bu Ayki İşler (KDV Hariç): ₺{makbuz.subtotal:,.2f}
{vat_text}• Bu Ay Toplamı: ₺{makbuz.grand_total:,.2f}
{carried_text}{prev_periods_text}------------------------------
• TOPLAM ÖDENECEK BAKİYE: ₺{statement.total_due:,.2f}

Bu bilgilendirme bilgilendirme amaçlıdır. Ayrıntılı hesap dökümü ekte yer almaktadır.

Saygılarımızla,
Makro Ortodonti"""

        text_result = cls.send_message(party.phone, message)
        if not text_result["success"]:
            return text_result

        filename = f"hesap_ozeti_{makbuz.year}_{makbuz.month:02d}_{party.id}.pdf"
        return cls.send_document(party.phone, pdf_bytes, filename=filename, caption=f"{period} Hesap Özeti")

    @classmethod
    def send_invoice_message(cls, invoice) -> dict:
        """Legacy helper for sending invoice notification message."""
        phone = invoice.party.phone if (invoice.party and invoice.party.phone) else (invoice.patient.phone if (invoice.patient and invoice.patient.phone) else None)
        if not phone:
            return {"success": False, "message": "Telefon numarası bulunamadı."}
        name = invoice.party.display_name if invoice.party else (invoice.patient.full_name if invoice.patient else "")
        due_str = f"\nSon Ödeme: {invoice.due_date.strftime('%d.%m.%Y')}" if getattr(invoice, 'due_date', None) else ""
        msg = f"Sayın {name},\n{invoice.invoice_number} numaralı faturanız ({invoice.invoice_date.strftime('%d.%m.%Y')}) tutarı: ₺{invoice.total_try:,.2f}{due_str}."
        return cls.send_message(phone, msg)

    @classmethod
    def send_reminder(cls, recipient, text: str) -> dict:
        """Legacy helper for sending reminder message."""
        phone = getattr(recipient, "phone", None)
        if not phone:
            return {"success": False, "message": "Telefon numarası bulunamadı."}
        return cls.send_message(phone, text)
