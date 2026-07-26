"""Türkçe duyarlı arama testleri: tr_fold, rota aramaları ve içe aktarma dedupe'u."""

from __future__ import annotations

import io

from openpyxl import Workbook

from app.extensions import db
from app.models.models import Party, PartyType, Treatment
from app.services.search_service import tr_collation_key, tr_fold, tr_order
from app.services.validation_service import format_tr_phone, normalize_display_name

from conftest import login


class TestTrFold:
    def test_turkish_letters_fold_to_ascii(self):
        assert tr_fold("Şahin İŞCAN") == "sahin iscan"
        assert tr_fold("Pınar") == "pinar"
        assert tr_fold("IĞDIR ÇÖĞÜŞ") == "igdir cogus"
        assert tr_fold("Büşra Öztopal") == "busra oztopal"

    def test_ascii_unchanged(self):
        assert tr_fold("Dr. Smith") == "dr. smith"

    def test_none_and_empty(self):
        assert tr_fold(None) == ""
        assert tr_fold("") == ""


class TestNormalizeDisplayName:
    def test_uses_turkish_title_case(self):
        assert normalize_display_name("  DR. İBRAHİM   IŞIK  ") == "Dr. İbrahim Işık"
        assert normalize_display_name("ayşe-nur o'CONNOR") == "Ayşe-Nur O'Connor"

    def test_preserves_short_organization_abbreviations(self):
        assert normalize_display_name("ABC SAĞLIK A.Ş.") == "ABC Sağlık A.Ş."


class TestFormatTrPhone:
    def test_formats_common_turkish_phone_variants(self):
        expected = "+90 533 769 44 69"
        assert format_tr_phone("+905337694469") == expected
        assert format_tr_phone("0533 769 44 69") == expected
        assert format_tr_phone("5337694469") == expected

    def test_preserves_non_turkish_or_incomplete_values(self):
        assert format_tr_phone("444 0 123") == "444 0 123"


def _seed_dentist(app, name, phone=None):
    with app.app_context():
        party = Party(party_type=PartyType.DENTIST, name=name, phone=phone)
        db.session.add(party)
        db.session.commit()
        return party.id


class TestTurkishCollationKey:
    def test_c_before_c_cedilla(self):
        assert tr_collation_key("Canan") < tr_collation_key("Çağla")
        assert tr_collation_key("Cem") < tr_collation_key("Çınar")

    def test_dotless_i_before_dotted_i(self):
        # Türk alfabesi: ... h, ı, i, j ... → ı, i'den önce gelir
        assert tr_collation_key("Irmak") < tr_collation_key("İpek")
        assert tr_collation_key("Ilgın") < tr_collation_key("İbrahim")

    def test_other_turkish_letters_follow_base(self):
        assert tr_collation_key("Oya") < tr_collation_key("Ömer")
        assert tr_collation_key("Sevil") < tr_collation_key("Şeyma")
        assert tr_collation_key("Ufuk") < tr_collation_key("Ümit")
        assert tr_collation_key("gokhan") < tr_collation_key("ğ")

    def test_none_and_empty(self):
        assert tr_collation_key(None) == ""
        assert tr_collation_key("") == ""


class TestTurkishOrdering:
    def test_db_order_matches_turkish_alphabet(self, app):
        names = [
            "Büşra", "Canan", "Çağla", "Çınar", "Irmak", "İpek", "Oya",
            "Ömer", "Sevil", "Şule", "Ufuk", "Ümit", "Yusuf", "Zümrüt",
        ]
        with app.app_context():
            for n in names:
                db.session.add(Party(party_type=PartyType.DENTIST, name=n))
            db.session.commit()

            ordered = [
                n for n in db.session.execute(
                    db.select(Party.name)
                    .where(Party.party_type == PartyType.DENTIST)
                    .order_by(tr_order(Party.name))
                ).scalars().all()
                if n in names
            ]

        # DB order must match true Turkish alphabetical order.
        assert ordered == sorted(names, key=tr_collation_key)
        # Concrete rules the user called out:
        assert ordered.index("Canan") < ordered.index("Çağla")  # ç, c'den sonra
        assert ordered.index("Irmak") < ordered.index("İpek")   # ı, i'den önce
        assert ordered[-1] == "Zümrüt"

    def test_list_page_orders_turkish_names_correctly(self, client, app):
        login(client, "admin", "admin-pass")
        with app.app_context():
            for n in ["Zümrüt", "Ahmet", "Çağla", "Canan"]:
                db.session.add(Party(party_type=PartyType.DENTIST, name=n))
            db.session.commit()
        html = client.get("/parties/").get_data(as_text=True)
        # True Turkish order: Ahmet < Canan < Çağla < Zümrüt
        assert (
            html.index("Ahmet")
            < html.index("Canan")
            < html.index("Çağla")
            < html.index("Zümrüt")
        )


class TestPartySearch:
    def test_ascii_query_finds_turkish_name(self, client, app):
        login(client, "admin", "admin-pass")
        _seed_dentist(app, "Şahin İşcan")
        response = client.get("/parties/?search=sahin")
        assert "Şahin İşcan".encode() in response.data

    def test_uppercase_turkish_query(self, client, app):
        login(client, "admin", "admin-pass")
        _seed_dentist(app, "Pınar Kutay")
        for q in ("PINAR", "pınar", "pinar", "kutay"):
            response = client.get(f"/parties/?search={q}")
            assert "Pınar Kutay".encode() in response.data, q

    def test_turkish_query_finds_ascii_name(self, client, app):
        login(client, "admin", "admin-pass")
        _seed_dentist(app, "Pinar Duz")  # ASCII kayıtlı isim
        response = client.get("/parties/?search=pınar")
        assert b"Pinar Duz" in response.data

    def test_phone_search_ignores_spaces(self, client, app):
        login(client, "admin", "admin-pass")
        _seed_dentist(app, "Dr. Telefon", phone="+90 536 361 93 78")
        response = client.get("/parties/?search=5363619378")
        assert b"Dr. Telefon" in response.data

    def test_no_match_returns_empty(self, client, app):
        login(client, "admin", "admin-pass")
        _seed_dentist(app, "Şahin İşcan")
        response = client.get("/parties/?search=olmayanisim")
        assert "Şahin İşcan".encode() not in response.data

    def test_partial_returns_only_results_fragment(self, client, app):
        """Canlı arama sadece sonuç tablosunu ister: tam sayfa (layout, arama
        formu) dönmemeli ki JS onu olduğu gibi tabloya yerleştirebilsin."""
        login(client, "admin", "admin-pass")
        _seed_dentist(app, "Şahin İşcan")

        full = client.get("/parties/").get_data(as_text=True)
        partial = client.get("/parties/?partial=1").get_data(as_text=True)

        assert "Şahin İşcan" in partial
        assert "<html" not in partial  # layout yok
        assert "js-live-search" not in partial  # arama formu tekrarlanmıyor
        assert "js-live-search" in full
        assert 'id="parties-results"' in full

    def test_partial_search_filters_and_keeps_pagination_clean(self, client, app):
        login(client, "admin", "admin-pass")
        with app.app_context():
            for i in range(30):
                db.session.add(Party(party_type=PartyType.DENTIST, name=f"Ahmet {i:02d}"))
            db.session.add(Party(party_type=PartyType.DENTIST, name="Ömer Özkan"))
            db.session.commit()

        partial = client.get("/parties/?search=omer&partial=1").get_data(as_text=True)
        assert "Ömer Özkan" in partial
        assert "Ahmet 00" not in partial

        # Sayfalama bağlantıları partial parametresini taşımamalı; aksi halde
        # tıklandığında tam sayfa yerine parça açılır.
        paged = client.get("/parties/?partial=1").get_data(as_text=True)
        assert "partial=1" not in paged

    def test_search_finds_name_that_lives_on_a_later_page(self, client, app):
        """25/sayfa listede 'Ö' ile başlayan isim son sayfalarda olsa bile
        arama tüm veritabanını tarayıp bulmalı (istemci-sayfa filtresi değil)."""
        login(client, "admin", "admin-pass")
        with app.app_context():
            # 30 doctor whose names sort before "Ö..." so the Ö one is on page 2+
            for i in range(30):
                db.session.add(Party(
                    party_type=PartyType.DENTIST, name=f"Ahmet {i:02d}"
                ))
            db.session.add(Party(party_type=PartyType.DENTIST, name="Ömer Özkan"))
            db.session.commit()

        # Default first page must NOT contain the Ö name (it paginates later)
        first_page = client.get("/parties/").get_data(as_text=True)
        assert "Ömer Özkan" not in first_page
        # Server-side search finds it regardless of page
        found = client.get("/parties/?search=omer").get_data(as_text=True)
        assert "Ömer Özkan" in found


class TestOtherSearches:
    def test_payments_doctor_search_turkish(self, client, app):
        login(client, "admin", "admin-pass")
        _seed_dentist(app, "Gülşah Çördük")
        response = client.get("/payments/?search=gulsah")
        assert "Gülşah Çördük".encode() in response.data

    def test_treatments_search_turkish(self, client, app):
        login(client, "admin", "admin-pass")
        with app.app_context():
            db.session.add(Treatment(name="Ölçü Alımı", category="ana_islemler", price_eur=10))
            db.session.commit()
        response = client.get("/treatments/?search=olcu")
        assert "Ölçü Alımı".encode() in response.data


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["Ad Soyad", "Telefon", "E-posta", "Adres", "Vergi No", "Not"])
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


class TestImportDedupe:
    def test_same_phone_different_names_both_created(self, client, app):
        """Aynı telefonu paylaşan farklı isimler (iki şubeli klinik) yutulmamalı."""
        login(client, "admin", "admin-pass")
        data = {"file": (_xlsx([
            ["Dentar Yenibosna", "+905425474405", None, None, None, None],
            ["Dent Ar Şirinevler", "+905425474405", None, None, None, None],
        ]), "d.xlsx")}
        response = client.post(
            "/parties/import", data=data, content_type="multipart/form-data", follow_redirects=True
        )
        assert "2 yeni" in response.get_data(as_text=True)
        with app.app_context():
            names = db.session.execute(
                db.select(Party.name).where(Party.phone == "+905425474405")
            ).scalars().all()
            assert sorted(names) == ["Dent Ar Şirinevler", "Dentar Yenibosna"]

    def test_turkish_case_name_match_updates(self, client, app):
        """'ŞAHİN işcan' gibi farklı büyük/küçük yazım mevcut kaydı güncellemeli."""
        login(client, "admin", "admin-pass")
        _seed_dentist(app, "Şahin İşcan", phone="+905551110001")

        data = {"file": (_xlsx([["ŞAHİN İŞCAN", "+905559998877", None, None, None, None]]), "d.xlsx")}
        response = client.post(
            "/parties/import", data=data, content_type="multipart/form-data", follow_redirects=True
        )
        assert "1 güncellendi" in response.get_data(as_text=True)
        with app.app_context():
            rows = db.session.execute(
                db.select(Party).where(Party.phone == "+905559998877")
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].name == "Şahin İşcan"
