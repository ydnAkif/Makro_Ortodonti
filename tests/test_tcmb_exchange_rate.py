"""Tests for TCMB exchange rate fallback and WorkOrder structured properties."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from app.models.models import WorkOrder
from app.services.exchange_service import (
    fetch_eur_try_rate,
    fetch_tcmb_rates,
    fetch_usd_try_rate,
)


TCMB_SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="islemkur.xsl"?>
<TCMB_AnlikKurlar Tarih="28.07.2026">
    <Currency CrossOrder="0" Kod="USD" CurrencyCode="USD">
        <Unit>1</Unit>
        <Isim>ABD DOLARI</Isim>
        <CurrencyName>US DOLLAR</CurrencyName>
        <ForexBuying>40.2500</ForexBuying>
        <ForexSelling>40.3200</ForexSelling>
    </Currency>
    <Currency CrossOrder="9" Kod="EUR" CurrencyCode="EUR">
        <Unit>1</Unit>
        <Isim>EURO</Isim>
        <CurrencyName>EURO</CurrencyName>
        <ForexBuying>44.1500</ForexBuying>
        <ForexSelling>44.2300</ForexSelling>
    </Currency>
</TCMB_AnlikKurlar>
"""


def test_fetch_tcmb_rates_parses_xml_correctly():
    mock_resp = MagicMock()
    mock_resp.content = TCMB_SAMPLE_XML.encode("utf-8")
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_resp):
        rates = fetch_tcmb_rates()
        assert rates["EUR"] == Decimal("44.1500")
        assert rates["USD"] == Decimal("40.2500")


def test_fetch_eur_try_rate_uses_tcmb_when_frankfurter_fails():
    mock_tcmb_resp = MagicMock()
    mock_tcmb_resp.content = TCMB_SAMPLE_XML.encode("utf-8")
    mock_tcmb_resp.raise_for_status = MagicMock()

    def mock_requests_get(url, **kwargs):
        if "frankfurter" in url:
            raise RuntimeError("Frankfurter down")
        return mock_tcmb_resp

    with patch("requests.get", side_effect=mock_requests_get):
        rate = fetch_eur_try_rate()
        assert rate == Decimal("44.1500")


def test_fetch_usd_try_rate_uses_tcmb_when_frankfurter_fails():
    mock_tcmb_resp = MagicMock()
    mock_tcmb_resp.content = TCMB_SAMPLE_XML.encode("utf-8")
    mock_tcmb_resp.raise_for_status = MagicMock()

    def mock_requests_get(url, **kwargs):
        if "frankfurter" in url:
            raise RuntimeError("Frankfurter down")
        return mock_tcmb_resp

    with patch("requests.get", side_effect=mock_requests_get):
        rate = fetch_usd_try_rate()
        assert rate == Decimal("40.2500")


def test_work_order_apparatus_and_extra_lists():
    wo_plain = WorkOrder(apparatus_type="Hawley Plak, Monoblok", extra_addons="Zemberek\nVida")
    assert wo_plain.apparatus_list == ["Hawley Plak", "Monoblok"]
    assert wo_plain.extra_addons_list == ["Zemberek", "Vida"]

    wo_json = WorkOrder(apparatus_type='["Hawley", "Expansion"]', extra_addons='["Spring"]')
    assert wo_json.apparatus_list == ["Hawley", "Expansion"]
    assert wo_json.extra_addons_list == ["Spring"]
