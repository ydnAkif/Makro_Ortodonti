from pathlib import Path
import json

import pytest


AXE_SOURCE = Path(__file__).parents[2] / "app/static/vendor/axe.min.js"


def test_turkish_font_families_are_loaded(page, live_server_url):
    page.goto(f"{live_server_url}/login")
    page.wait_for_function("document.fonts.status === 'loaded'")

    result = page.evaluate("""() => {
        const heading = document.querySelector('.login-form h2');
        const body = document.querySelector('.login-form > p');
        const loadedFamilies = [...document.fonts]
            .filter(face => face.status === 'loaded')
            .map(face => face.family.replaceAll('"', ''));
        return {
            headingFamily: getComputedStyle(heading).fontFamily,
            bodyFamily: getComputedStyle(body).fontFamily,
            familjenLoaded: loadedFamilies.includes('Familjen Grotesk'),
            manropeLoaded: loadedFamilies.includes('Manrope'),
        };
    }""")

    assert result["headingFamily"].startswith('"Familjen Grotesk"')
    assert result["bodyFamily"].startswith('Manrope') or result["bodyFamily"].startswith('"Manrope"')
    assert result["familjenLoaded"] is True
    assert result["manropeLoaded"] is True


@pytest.mark.parametrize("viewport", [{"width": 400, "height": 765}, {"width": 1280, "height": 900}])
def test_authenticated_shell_has_no_serious_accessibility_violations(authenticated_page, viewport):
    page = authenticated_page
    page.set_viewport_size(viewport)
    page.reload()
    page.add_script_tag(content=AXE_SOURCE.read_text())
    result = page.evaluate("async () => await axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa']}})")
    serious = [v for v in result["violations"] if v["impact"] in {"serious", "critical"}]
    assert serious == [], json.dumps(serious, ensure_ascii=False, indent=2)


def test_primary_navigation_and_security_headers(authenticated_page, live_server_url):
    page = authenticated_page
    response = page.goto(f"{live_server_url}/parties/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"].startswith("default-src 'self'")
    assert response.headers["x-request-id"]
    assert page.get_by_role("heading", name="Doktorlar", exact=True).is_visible()


def test_dentist_work_order_and_makbuz_payment_critical_flow(authenticated_page, live_server_url):
    page = authenticated_page

    page.goto(f"{live_server_url}/parties/add")
    page.locator("#name").fill("Dr. Tarayıcı Hekimi")
    page.locator("#phone").fill("5554443322")
    page.get_by_role("button", name="Kaydet").click()
    page.wait_for_url(f"{live_server_url}/parties/*")
    party_id = page.url.rstrip("/").split("/")[-1]

    page.goto(f"{live_server_url}/parties/{party_id}/work-orders/add")
    page.locator("#patient_name").fill("E2E Hasta")
    page.locator("#apparatus_price").fill("100")
    page.get_by_role("button", name="Kaydet").click()
    page.wait_for_url(f"{live_server_url}/parties/{party_id}*")

    page.goto(f"{live_server_url}/makbuzlar/{party_id}")
    page.wait_for_selector('a[href*="/pdf"]')
    pdf_href = page.locator('a[href*="/pdf"]').first.get_attribute("href")
    makbuz_id = pdf_href.split("/makbuzlar/")[-1].split("/")[0]

    page.goto(f"{live_server_url}/payments/{makbuz_id}/mark-paid")
    page.get_by_role("button", name="Kaydet").click()
    page.wait_for_url(f"{live_server_url}/payments/?tab=paid")
    assert page.get_by_text("₺100.00").first.is_visible()


def test_turkish_search_in_browser_filters(authenticated_page, live_server_url):
    """ASCII yazım ('pinar', 'sahin') Türkçe isimleri hem sunucu aramasında
    hem istemci tarafı filtrelerde bulmalı."""
    page = authenticated_page

    # Sunucu tarafı: diş hekimi listesi araması
    page.goto(f"{live_server_url}/parties/?search=pinar")
    assert page.get_by_text("Dr. Pınar Şahin").first.is_visible()

    # İstemci tarafı: WhatsApp toplu mesaj kişi filtresi
    page.goto(f"{live_server_url}/whatsapp/")
    page.locator("details.disclosure-panel > summary").click()
    filter_input = page.locator("#bulk-patient-filter")
    filter_input.fill("sahin")
    pinar_row = page.locator("#bulk-patient-list .form-check", has_text="Dr. Pınar Şahin")
    other_row = page.locator("#bulk-patient-list .form-check", has_text="Dr. E2E Hekim")
    assert pinar_row.is_visible()
    assert other_row.is_hidden()


def test_parties_live_search_without_page_reload(authenticated_page, live_server_url):
    """Arama kutusuna yazınca sonuçlar sayfa YENİLENMEDEN güncellenmeli;
    tüm veritabanında Türkçe-duyarlı arama yapılmalı ('pinar' → 'Pınar')."""
    page = authenticated_page
    page.goto(f"{live_server_url}/parties/")

    # Sayfanın yeniden yüklenip yüklenmediğini anlamak için bir işaret bırak.
    page.evaluate("window.__notReloaded = true")

    page.locator("input.js-live-search").fill("pinar")

    # Sonuçlar yerinde güncellenir
    page.wait_for_function(
        "() => document.querySelectorAll('#parties-results tbody tr').length === 1",
        timeout=5000,
    )
    assert page.get_by_text("Dr. Pınar Şahin").first.is_visible()

    # Sayfa yenilenmedi: işaret hâlâ duruyor ve odak kutuda kaldı
    assert page.evaluate("window.__notReloaded") is True
    assert page.evaluate("document.activeElement.name") == "search"
    # Adres çubuğu aramayla senkron (yenile/yer imi çalışsın)
    assert "search=pinar" in page.url
