"""Seed data and migration utilities."""

from __future__ import annotations

import os
import secrets
from datetime import date

import bcrypt
from sqlalchemy.orm import Session

from .models import (
    ExchangeRate,
    Invoice,
    Party,
    PartyType,
    Patient,
    Settings,
    Treatment,
    TreatmentCategory,
    User,
)


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _is_valid_bcrypt_hash(password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        bcrypt.checkpw(b"__probe__", password_hash.encode("utf-8"))
        return True
    except ValueError:
        return False


def _resolve_admin_password() -> tuple[str, bool]:
    env_password = os.environ.get("DEFAULT_ADMIN_PASSWORD", "").strip()
    is_debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    is_testing = os.environ.get("TESTING", "false").lower() == "true" or os.environ.get("PYTEST_CURRENT_TEST") is not None
    
    if env_password:
        if (
            (len(env_password) < 12 or env_password.lower() in ("admin123", "admin", "123456", "password"))
            and not is_debug
            and not is_testing
        ):
            random_pw = secrets.token_urlsafe(12)
            print("\n[CRITICAL SECURITY WARNING] Weak DEFAULT_ADMIN_PASSWORD rejected in production!")
            print(f"Generating a random secure one-time password instead: {random_pw}\n")
            return random_pw, True
        return env_password, False
    return secrets.token_urlsafe(12), True


def _seed_parties(session: Session) -> None:
    """Insert the full dentist party list. Idempotent — skips existing names."""
    sample_parties = [
        Party(party_type=PartyType.DENTIST, name="Abdulkadir Narin", phone="+905337694469"),
        Party(party_type=PartyType.DENTIST, name="Adile Göktaş", phone="+905352779663"),
        Party(party_type=PartyType.DENTIST, name="Ahmet Berkan Aksoy", phone="+905302923132"),
        Party(party_type=PartyType.DENTIST, name="Aklen Anıl", phone="+905058020645"),
        Party(party_type=PartyType.DENTIST, name="Alara Ersoy", phone="+905312628526"),
        Party(party_type=PartyType.DENTIST, name="Alev Sarp", phone="+905327753412"),
        Party(party_type=PartyType.DENTIST, name="Alpay Giray", phone="+905532353187"),
        Party(party_type=PartyType.DENTIST, name="Alperen Başgöl", phone="+905415770573"),
        Party(party_type=PartyType.DENTIST, name="Alper Temuralay", phone="+905352370677"),
        Party(party_type=PartyType.DENTIST, name="Anı Türköz", phone="+905332240853"),
        Party(party_type=PartyType.DENTIST, name="Arzu Arı Demirkaya", phone="+905384882434"),
        Party(party_type=PartyType.DENTIST, name="Arzu Boğatepe", phone="+905537761245"),
        Party(party_type=PartyType.DENTIST, name="Arzu Kahya", phone="+905424277851"),
        Party(party_type=PartyType.DENTIST, name="Aslıhan Yazgülü", phone="+905331998893"),
        Party(party_type=PartyType.DENTIST, name="Aspen Diş Kliniği", phone="+905523246661"),
        Party(party_type=PartyType.DENTIST, name="Atakan Vargün", phone="+905322174293"),
        Party(party_type=PartyType.DENTIST, name="Ayberk Kara", phone="+905374910550"),
        Party(party_type=PartyType.DENTIST, name="Aybüke Ensarioğlu", phone="+905378867733"),
        Party(party_type=PartyType.DENTIST, name="Ayşegül Gürbüz Sancar", phone="+905530029830"),
        Party(party_type=PartyType.DENTIST, name="Banu Gürkan Köseoğlu"),
        Party(party_type=PartyType.DENTIST, name="Banu Mert", phone="+905377197679"),
        Party(party_type=PartyType.DENTIST, name="Baran Öztürk", phone="+905543636929"),
        Party(party_type=PartyType.DENTIST, name="Barış Taştan", phone="+905444818868"),
        Party(party_type=PartyType.DENTIST, name="Başak Altuntaş", phone="+905543732098"),
        Party(party_type=PartyType.DENTIST, name="Begüm Su Kaya", phone="+905426827489"),
        Party(party_type=PartyType.DENTIST, name="Belin Altuntaş", phone="+905313988065"),
        Party(party_type=PartyType.DENTIST, name="Berk Tiryaki", phone="+905325432788"),
        Party(party_type=PartyType.DENTIST, name="Beytullah Gülsoy", phone="+905364107350"),
        Party(party_type=PartyType.DENTIST, name="Bilgehan Kul", phone="+905321596317"),
        Party(party_type=PartyType.DENTIST, name="Boğaç Akkoç", phone="+905345898614"),
        Party(party_type=PartyType.DENTIST, name="Bora Aysan", phone="+905345905638"),
        Party(party_type=PartyType.DENTIST, name="Bora Aysan Dentgrup Maslak", phone="+905418260585"),
        Party(party_type=PartyType.DENTIST, name="Bora Aysan - Dentgroup Göztepe"),
        Party(party_type=PartyType.DENTIST, name="Burcu Ata", phone="+905335220502"),
        Party(party_type=PartyType.DENTIST, name="Burcu Öztopal", phone="+905339239063"),
        Party(party_type=PartyType.DENTIST, name="Burçe Nur Yılmaz Klinik", phone="+905526435434"),
        Party(party_type=PartyType.DENTIST, name="Burçe Yılmaz", phone="+905069049830"),
        Party(party_type=PartyType.DENTIST, name="Buse Tavukçuoğlu", phone="+905425865372"),
        Party(party_type=PartyType.DENTIST, name="Bülent Keskin"),
        Party(party_type=PartyType.DENTIST, name="Büşra Ersoy", phone="+905325922762"),
        Party(party_type=PartyType.DENTIST, name="Canan Doğdu İnovasyon", phone="+905333757723"),
        Party(party_type=PartyType.DENTIST, name="Canberk Acar", phone="+905334472372"),
        Party(party_type=PartyType.DENTIST, name="Cansu Akçeşme", phone="+905069964137"),
        Party(party_type=PartyType.DENTIST, name="Cansu Gedik", phone="+905318327209"),
        Party(party_type=PartyType.DENTIST, name="Cemile Uysal", phone="+905325174352"),
        Party(party_type=PartyType.DENTIST, name="Ceren Alkan", phone="+905523004644"),
        Party(party_type=PartyType.DENTIST, name="Confident-artun U.", phone="+905356272682"),
        Party(party_type=PartyType.DENTIST, name="Çağan Seyhan", phone="+905313029552"),
        Party(party_type=PartyType.DENTIST, name="Çağatay Kavaz", phone="+905423538777"),
        Party(party_type=PartyType.DENTIST, name="Çağla Çelik", phone="+905399551961"),
        Party(party_type=PartyType.DENTIST, name="Damla Karakaya Özdemir", phone="+905367093900"),
        Party(party_type=PartyType.DENTIST, name="Damla Pek Öztürk", phone="+905542034039"),
        Party(party_type=PartyType.DENTIST, name="Damla Şen", phone="+905542527875"),
        Party(party_type=PartyType.DENTIST, name="Defne Prime", phone="+905332453872"),
        Party(party_type=PartyType.DENTIST, name="Demet Ayman", phone="+905322581085"),
        Party(party_type=PartyType.DENTIST, name="Deniz Berk Bekar", phone="+905389499289"),
        Party(party_type=PartyType.DENTIST, name="Deniz Mercan", phone="+905075990363"),
        Party(party_type=PartyType.DENTIST, name="Deniz Mercan Medicana", phone="+905372889284"),
        Party(party_type=PartyType.DENTIST, name="Deniz Özdemir", phone="+905393492669"),
        Party(party_type=PartyType.DENTIST, name="Dentar Yenibosna", phone="+905425474405"),
        Party(party_type=PartyType.DENTIST, name="Dentavega"),
        Party(party_type=PartyType.DENTIST, name="Dentgroup Kids Bahçelievler", phone="+905521587611"),
        Party(party_type=PartyType.DENTIST, name="Dentia-damla Şen", phone="+905388541404"),
        Party(party_type=PartyType.DENTIST, name="Dentolya Dilara Nükhet", phone="+905413789698"),
        Party(party_type=PartyType.DENTIST, name="Dent Ar Beylikdüzü", phone="+905464902140"),
        Party(party_type=PartyType.DENTIST, name="Dent İstanbul", phone="+905534971358"),
        Party(party_type=PartyType.DENTIST, name="Dent İstün"),
        Party(party_type=PartyType.DENTIST, name="Dent İstün-ahmet Çavuşoğlu", phone="+905365616100"),
        Party(party_type=PartyType.DENTIST, name="Dent Kalamış", phone="+905529422808"),
        Party(party_type=PartyType.DENTIST, name="Dicle Tokatlı-okan", phone="+905068447510"),
        Party(party_type=PartyType.DENTIST, name="Dilara Kahraman", phone="+905374347134"),
        Party(party_type=PartyType.DENTIST, name="Dilvin Kendirci", phone="+905318896420"),
        Party(party_type=PartyType.DENTIST, name="Dinamik Diş", phone="+905383707844"),
        Party(party_type=PartyType.DENTIST, name="Dolapdere", phone="+905313040847"),
        Party(party_type=PartyType.DENTIST, name="Duygu Aslan", phone="+905359384994"),
        Party(party_type=PartyType.DENTIST, name="Ebru Demircan Kapıyoldaş", phone="+905330507167"),
        Party(party_type=PartyType.DENTIST, name="Ebru Sarı", phone="+905388710677"),
        Party(party_type=PartyType.DENTIST, name="Eda Sertkaya", phone="+905392209982"),
        Party(party_type=PartyType.DENTIST, name="Elif Aslan", phone="+905412884989"),
        Party(party_type=PartyType.DENTIST, name="Elif Cellek Tiftik", phone="+905053376038"),
        Party(party_type=PartyType.DENTIST, name="Elif Çankaya Uludağ", phone="+905447789305"),
        Party(party_type=PartyType.DENTIST, name="Elif Gündüz", phone="+905324171645"),
        Party(party_type=PartyType.DENTIST, name="Elif Karakullukçu", phone="+905339737655"),
        Party(party_type=PartyType.DENTIST, name="Elif Nur Yoğurtçu", phone="+905466395656"),
        Party(party_type=PartyType.DENTIST, name="Elif Şentürk", phone="+905318141618"),
        Party(party_type=PartyType.DENTIST, name="Elif Tuba Kabak"),
        Party(party_type=PartyType.DENTIST, name="Elit Dental-karagümrük", phone="+905464155958"),
        Party(party_type=PartyType.DENTIST, name="Elvin Eralp", phone="+905364273232"),
        Party(party_type=PartyType.DENTIST, name="Emident", phone="+905331625381"),
        Party(party_type=PartyType.DENTIST, name="Emine Bıyık", phone="+905342088926"),
        Party(party_type=PartyType.DENTIST, name="Emircan-Klinika", phone="+905379813463"),
        Party(party_type=PartyType.DENTIST, name="Emrah Girgin", phone="+905324366740"),
        Party(party_type=PartyType.DENTIST, name="Emrah Girgin-mimaroba", phone="+905052928750"),
        Party(party_type=PartyType.DENTIST, name="Emre Can Ulugöz", phone="+905354654843"),
        Party(party_type=PartyType.DENTIST, name="Erdal Kumkumoğlu", phone="+905436587155"),
        Party(party_type=PartyType.DENTIST, name="Erhan Elgin", phone="+905462770542"),
        Party(party_type=PartyType.DENTIST, name="Erkan Allahverdi", phone="+905356184184"),
        Party(party_type=PartyType.DENTIST, name="Evrim Birkalan", phone="+905431832327"),
        Party(party_type=PartyType.DENTIST, name="Ezgi Koyuncu", phone="+905387403772"),
        Party(party_type=PartyType.DENTIST, name="Ezgi Özkan", phone="+905300957878"),
        Party(party_type=PartyType.DENTIST, name="Fakir Uzdil", phone="+905322071631"),
        Party(party_type=PartyType.DENTIST, name="Faradent", phone="+905078400301"),
        Party(party_type=PartyType.DENTIST, name="Fatma Aslı Konca", phone="+905322188688"),
        Party(party_type=PartyType.DENTIST, name="Ferdi Allaf-centerdent", phone="+905322606533"),
        Party(party_type=PartyType.DENTIST, name="Ferhat Akgül", phone="+905537896161", notes="+"),
        Party(party_type=PartyType.DENTIST, name="Feyzanur Tetik", phone="+905415646253"),
        Party(party_type=PartyType.DENTIST, name="Fırat Budacı", phone="+905324025007"),
        Party(party_type=PartyType.DENTIST, name="Flor Dent", phone="+905380538342"),
        Party(party_type=PartyType.DENTIST, name="Funda Korkmaz", phone="+905323236037"),
        Party(party_type=PartyType.DENTIST, name="Furkan Açıkgözoğlu", phone="+905446533566"),
        Party(party_type=PartyType.DENTIST, name="Furkan Açıkgözoğlu Dentgrup", phone="+905379157822"),
        Party(party_type=PartyType.DENTIST, name="Furkan A.-emsey Klinik", phone="+905389705723"),
        Party(party_type=PartyType.DENTIST, name="Gizem Yoğurucu Değerli", phone="+905399330565"),
        Party(party_type=PartyType.DENTIST, name="Grupdent", phone="+905443766358"),
        Party(party_type=PartyType.DENTIST, name="Gülderen Konak", phone="+905423656728"),
        Party(party_type=PartyType.DENTIST, name="Gülşah Balan", phone="+905445937719"),
        Party(party_type=PartyType.DENTIST, name="Hakan Yılmaz", phone="+905466908812"),
        Party(party_type=PartyType.DENTIST, name="Hakan-ordulu", phone="+905367724899"),
        Party(party_type=PartyType.DENTIST, name="Hatice Orhan", phone="+905052981684"),
        Party(party_type=PartyType.DENTIST, name="Hatice Sural", phone="+905325598810"),
        Party(party_type=PartyType.DENTIST, name="Hatice Taştan", phone="+905534373094"),
        Party(party_type=PartyType.DENTIST, name="Haydar Çimen", phone="+905317047874"),
        Party(party_type=PartyType.DENTIST, name="Hazal Demir Aksoy", phone="+905421391699"),
        Party(party_type=PartyType.DENTIST, name="Helin Çınar", phone="+905343569914"),
        Party(party_type=PartyType.DENTIST, name="Hospitadent M.Köy"),
        Party(party_type=PartyType.DENTIST, name="Hüseyin Batuhan Güven", phone="+905342083437"),
        Party(party_type=PartyType.DENTIST, name="Işıl Evcimik"),
        Party(party_type=PartyType.DENTIST, name="İnfinty", phone="+905354961228"),
        Party(party_type=PartyType.DENTIST, name="İpek Cemre Özkan", phone="+905413038923"),
        Party(party_type=PartyType.DENTIST, name="İrem Lapacı", phone="+905383210909"),
        Party(party_type=PartyType.DENTIST, name="İrem Nur Kıstı", phone="+905348405859"),
        Party(party_type=PartyType.DENTIST, name="İrem Özgen Demirel", phone="+905342150459"),
        Party(party_type=PartyType.DENTIST, name="Kadir Deva Dis", phone="+905442430432"),
        Party(party_type=PartyType.DENTIST, name="Kamuran Özdoğan"),
        Party(party_type=PartyType.DENTIST, name="Kavi Diş Kliniği", phone="+905435132335"),
        Party(party_type=PartyType.DENTIST, name="Kemal Başdüvenci", phone="+905386082930"),
        Party(party_type=PartyType.DENTIST, name="Kemal Bulut Çırpan", phone="+905374626659"),
        Party(party_type=PartyType.DENTIST, name="Kenan Cantekin", phone="+905458808850"),
        Party(party_type=PartyType.DENTIST, name="Klinik No 1"),
        Party(party_type=PartyType.DENTIST, name="Körfezkent Alpay Giray", phone="+905343231877"),
        Party(party_type=PartyType.DENTIST, name="Kübra Olkun", phone="+905327361454"),
        Party(party_type=PartyType.DENTIST, name="Levent Demiray", phone="+905326158088"),
        Party(party_type=PartyType.DENTIST, name="Mehmet Ali Zorbey", phone="+905366124779"),
        Party(party_type=PartyType.DENTIST, name="Mehmet Ulaş"),
        Party(party_type=PartyType.DENTIST, name="Melisa Alkan", phone="+905071715822"),
        Party(party_type=PartyType.DENTIST, name="Melisa Öztürkmen", phone="+905312220522"),
        Party(party_type=PartyType.DENTIST, name="Meltem Veliağagil", phone="+905327462146"),
        Party(party_type=PartyType.DENTIST, name="Mert Cumaoğlu", phone="+905052025646"),
        Party(party_type=PartyType.DENTIST, name="Mert Doğan", phone="+905393331492"),
        Party(party_type=PartyType.DENTIST, name="Mert Osanmaz", phone="+905354310617"),
        Party(party_type=PartyType.DENTIST, name="Merve Durak", phone="+905344139012"),
        Party(party_type=PartyType.DENTIST, name="Muhammed Raşit Nacar", phone="+905010669346"),
        Party(party_type=PartyType.DENTIST, name="Mustafa Karcıoğlu-Namlı Market"),
        Party(party_type=PartyType.DENTIST, name="Nazenin Danışvar"),
        Party(party_type=PartyType.DENTIST, name="Nihal Hamamcı", phone="+905532041247"),
        Party(party_type=PartyType.DENTIST, name="Oğuzhan Kahveci", phone="+905415836148"),
        Party(party_type=PartyType.DENTIST, name="Onul Üner", phone="+905325742598"),
        Party(party_type=PartyType.DENTIST, name="Onur Çetinkaya", phone="+905334376687"),
        Party(party_type=PartyType.DENTIST, name="Orhan Öztoprak", phone="+905306330217"),
        Party(party_type=PartyType.DENTIST, name="Oya Dertop Özkan", phone="+905362495819"),
        Party(party_type=PartyType.DENTIST, name="Özge Deniz"),
        Party(party_type=PartyType.DENTIST, name="Özgür Aydın Ergünay", phone="+905055900578"),
        Party(party_type=PartyType.DENTIST, name="Özlem Aylıkçı", phone="+905067035279"),
        Party(party_type=PartyType.DENTIST, name="Özlem Bayrak", phone="+905323841570"),
        Party(party_type=PartyType.DENTIST, name="Özlem Karaca", phone="+905443948998"),
        Party(party_type=PartyType.DENTIST, name="Özlem Özcan", phone="+905522887648"),
        Party(party_type=PartyType.DENTIST, name="Parla", phone="+905056956352", notes="."),
        Party(party_type=PartyType.DENTIST, name="Pervin Bilginer", phone="+905322613585"),
        Party(party_type=PartyType.DENTIST, name="Pervin-Yavuz İpçi"),
        Party(party_type=PartyType.DENTIST, name="Pınar Karataban", phone="+905325221103"),
        Party(party_type=PartyType.DENTIST, name="Rabia Özer", phone="+905053459237"),
        Party(party_type=PartyType.DENTIST, name="Rabia Varol Boyraz", phone="+905304716330"),
        Party(party_type=PartyType.DENTIST, name="Recep Aydın - Bursa Vita", phone="+905389518656"),
        Party(party_type=PartyType.DENTIST, name="Rodi Mızrak", phone="+905423014824"),
        Party(party_type=PartyType.DENTIST, name="Royaldent", phone="+905333053505"),
        Party(party_type=PartyType.DENTIST, name="Sefa-oğuzhan", notes="+"),
        Party(party_type=PartyType.DENTIST, name="Selim Can Çakır", phone="+905070750103"),
        Party(party_type=PartyType.DENTIST, name="Selin Ölçer", phone="+905384173604"),
        Party(party_type=PartyType.DENTIST, name="Semih Levi", phone="+905323165355"),
        Party(party_type=PartyType.DENTIST, name="Sena Karaaslan", phone="+905077457112"),
        Party(party_type=PartyType.DENTIST, name="Serdar Gözkaya", notes="+"),
        Party(party_type=PartyType.DENTIST, name="Serenay Şekerci", phone="+905385662339"),
        Party(party_type=PartyType.DENTIST, name="Serkan Öztürk", phone="+905452484875"),
        Party(party_type=PartyType.DENTIST, name="Sevcan Akesi", phone="+905357372624"),
        Party(party_type=PartyType.DENTIST, name="Sevgi Başeğmez", phone="+905303896667"),
        Party(party_type=PartyType.DENTIST, name="Sevgi Budancamanak", phone="+905439169520"),
        Party(party_type=PartyType.DENTIST, name="Sevgi Ersoy-hosp.(özel)", phone="+905355073040", notes="FATURA"),
        Party(party_type=PartyType.DENTIST, name="Sevil Gökkurt", phone="+905309295941"),
        Party(party_type=PartyType.DENTIST, name="Sıdıka Demir", phone="+905326630030"),
        Party(party_type=PartyType.DENTIST, name="Sıla Başa", phone="+905076390134"),
        Party(party_type=PartyType.DENTIST, name="Sinan Atıcı", phone="+905327078477"),
        Party(party_type=PartyType.DENTIST, name="Sinem Öztürk", phone="+905069902903"),
        Party(party_type=PartyType.DENTIST, name="Su Ağız Diş", phone="+905550254244"),
        Party(party_type=PartyType.DENTIST, name="Şevval Gür", phone="+905349559477"),
        Party(party_type=PartyType.DENTIST, name="Şeyma Acar", phone="+905330276192"),
        Party(party_type=PartyType.DENTIST, name="Şule Başsimitçi", phone="+905322875850"),
        Party(party_type=PartyType.DENTIST, name="Tarabya Smile", phone="+905521679500"),
        Party(party_type=PartyType.DENTIST, name="Taşkın Özcan"),
        Party(party_type=PartyType.DENTIST, name="Tuğba Özercan", phone="+905077447446"),
        Party(party_type=PartyType.DENTIST, name="Tuğçe Gürbüztürk", phone="+905350116572"),
        Party(party_type=PartyType.DENTIST, name="Tuna", phone="+905438353624"),
        Party(party_type=PartyType.DENTIST, name="Tülin Şakar", phone="+905332400105"),
        Party(party_type=PartyType.DENTIST, name="Uğur Can Kara", phone="+905306922234"),
        Party(party_type=PartyType.DENTIST, name="Uğur Önder Acıbadem"),
        Party(party_type=PartyType.DENTIST, name="Uğur Önder Özel", phone="+905389727354"),
        Party(party_type=PartyType.DENTIST, name="Umut Tör-yeni", phone="+905431965655"),
        Party(party_type=PartyType.DENTIST, name="Vedat Karaduman", phone="+905352139646"),
        Party(party_type=PartyType.DENTIST, name="Velda Sönmez", phone="+905301321709"),
        Party(party_type=PartyType.DENTIST, name="Yağmur Kahraman", phone="+905387148541"),
        Party(party_type=PartyType.DENTIST, name="Yalçın Temtek", phone="+905312007767"),
        Party(party_type=PartyType.DENTIST, name="Yusuf Ceylan", phone="+905337256139"),
        Party(party_type=PartyType.DENTIST, name="Yusuf Demir"),
        Party(party_type=PartyType.DENTIST, name="Yusuf İlhan", phone="+905335775026"),
        Party(party_type=PartyType.DENTIST, name="Zehra Yaşar", phone="+905322261073"),
        Party(party_type=PartyType.DENTIST, name="Zelal Mızrak", phone="+905392650111"),
        Party(party_type=PartyType.DENTIST, name="Zeynep Cengiz", phone="+905302482616"),
        Party(party_type=PartyType.DENTIST, name="Zeynep Sunay Şahin", phone="+905344658363"),
        Party(party_type=PartyType.DENTIST, name="Bilal Akman", phone="+905052934940"),
        Party(party_type=PartyType.DENTIST, name="Cihat Ulusan", phone="+905333864594"),
        Party(party_type=PartyType.DENTIST, name="Emirdental", phone="+905398123595"),
        Party(party_type=PartyType.DENTIST, name="Ersoy", phone="+905349568025"),
        Party(party_type=PartyType.DENTIST, name="Halit Sarıbaş", phone="+905373855241"),
        Party(party_type=PartyType.DENTIST, name="Hamdi Abi", phone="+905344642671"),
        Party(party_type=PartyType.DENTIST, name="Hatice Klinik", phone="+905447212064"),
        Party(party_type=PartyType.DENTIST, name="Kadir Abi", phone="+905394427222"),
        Party(party_type=PartyType.DENTIST, name="Kavrayış Murat", phone="+905338147425"),
        Party(party_type=PartyType.DENTIST, name="Muharrem Aksoy Konya", phone="+905439580206"),
        Party(party_type=PartyType.DENTIST, name="Olcay Abi", phone="+905530081442"),
        Party(party_type=PartyType.DENTIST, name="Salih İskeletçi"),
        Party(party_type=PartyType.DENTIST, name="Sercan Abi", phone="+905556336819"),
        Party(party_type=PartyType.DENTIST, name="Yıldırım Teknisyen"),
        Party(party_type=PartyType.DENTIST, name="Gülcan Danacı"),
        Party(party_type=PartyType.DENTIST, name="Praxiss"),
        Party(party_type=PartyType.DENTIST, name="Deniz Berk Bekar-delta"),
        Party(party_type=PartyType.DENTIST, name="Dikili Klinik Akademi"),
        Party(party_type=PartyType.DENTIST, name="Dent Ar Şirinevler", phone="+905425474405", notes="Not: Telefon numarası dosyada başka bir kayıtla aynı; güncellenecek."),
        Party(party_type=PartyType.DENTIST, name="Pınar Kutay", phone="+905325221103", notes="Not: Telefon numarası dosyada başka bir kayıtla aynı; güncellenecek."),
    ]
    session.add_all(sample_parties)


def seed_sample_data() -> str | None:
    """Seed sample data using Flask-SQLAlchemy session. Must be called inside app context."""
    from app.extensions import db

    generated_password: str | None = None
    has_seed_data = db.session.execute(
        db.select(Treatment).limit(1)
    ).scalar_one_or_none() is not None

    if has_seed_data:
        admin_user = db.session.execute(
            db.select(User).where(User.username == "admin")
        ).scalar_one_or_none()

        if admin_user is None:
            admin_password, is_generated = _resolve_admin_password()
            db.session.add(
                User(
                    username="admin",
                    password_hash=_hash_password(admin_password),
                    full_name="Admin",
                    role=User.ROLE_ADMIN,
                )
            )
            db.session.commit()
            if is_generated:
                generated_password = admin_password
        elif not _is_valid_bcrypt_hash(admin_user.password_hash):
            admin_password, is_generated = _resolve_admin_password()
            admin_user.password_hash = _hash_password(admin_password)
            db.session.commit()
            if is_generated:
                generated_password = admin_password

        has_parties = db.session.execute(
            db.select(Party).limit(1)
        ).scalar_one_or_none() is not None
        if not has_parties:
            _seed_parties(db.session)
            db.session.commit()

        return generated_password

    treatments = [
        Treatment(name="Dijital Planlama (Tek Çene)", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1750.00, currency="TL"),
        Treatment(name="Lingual Ark", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1000.00, currency="TL"),
        Treatment(name="Dijital Plak (Adet)", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1200.00, currency="TL"),
        Treatment(name="Nance", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1100.00, currency="TL"),
        Treatment(name="Şeffaf Plak (Soft, Medium, Hard)", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1600.00, currency="TL"),
        Treatment(name="TPA", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1000.00, currency="TL"),
        Treatment(name="Set-up'lı Sx", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1100.00, currency="TL"),
        Treatment(name="Habit Appliances", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1200.00, currency="TL"),
        Treatment(name="Dijital Model (Adet)", category=TreatmentCategory.ANA_ISLEMLER, price_eur=500.00, currency="TL"),
        Treatment(name="Quad Helix", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1200.00, currency="TL"),
        Treatment(name="Bi Helix", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1200.00, currency="TL"),
        Treatment(name="Lingual Indirect Bonding Tek Çene 7-7", category=TreatmentCategory.ANA_ISLEMLER, price_eur=3500.00, currency="TL"),
        Treatment(name="Lingual Indirect Bonding set-upsız Tek Diş", category=TreatmentCategory.ANA_ISLEMLER, price_eur=300.00, currency="TL"),
        Treatment(name="Rapid Expansion (Hyrax Type) (Vidasız)", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1400.00, currency="TL"),
        Treatment(name="Labial Indirect Bonding Tek Çene", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1600.00, currency="TL"),
        Treatment(name="Rapid Expansion (Mc Namara) (Vidasız)", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1500.00, currency="TL"),
        Treatment(name="Rapid Expansion (Fan Type) (Vidasız)", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1500.00, currency="TL"),
        Treatment(name="Hawley", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1100.00, currency="TL"),
        Treatment(name="Molar Slider", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1500.00, currency="TL"),
        Treatment(name="Wrap Around", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1100.00, currency="TL"),
        Treatment(name="Pendulum Appliance", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1500.00, currency="TL"),
        Treatment(name="Lingual Retainer", category=TreatmentCategory.ANA_ISLEMLER, price_eur=450.00, currency="TL"),
        Treatment(name="Expansion (Transverse)", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1500.00, currency="TL"),
        Treatment(name="Sx Plak", category=TreatmentCategory.ANA_ISLEMLER, price_eur=375.00, currency="TL"),
        Treatment(name="Expansion (3 way Type) (Vidasız)", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1400.00, currency="TL"),
        Treatment(name="Yer Tutucu (Sabit)", category=TreatmentCategory.ANA_ISLEMLER, price_eur=850.00, currency="TL"),
        Treatment(name="Expansion (Fan Type) (Vidasız)", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1400.00, currency="TL"),
        Treatment(name="Yer Tutucu (Hareketli)", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1100.00, currency="TL"),
        Treatment(name="Bite Plate", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1500.00, currency="TL"),
        Treatment(name="Gece Plağı", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1000.00, currency="TL"),
        Treatment(name="Activator (FKO)", category=TreatmentCategory.ANA_ISLEMLER, price_eur=2500.00, currency="TL"),
        Treatment(name="Durasoft Gece Plağı (2.5 mm)", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1600.00, currency="TL"),
        Treatment(name="Bionator (Açık-Kapalı)", category=TreatmentCategory.ANA_ISLEMLER, price_eur=2700.00, currency="TL"),
        Treatment(name="Eklem Splinti", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1750.00, currency="TL"),
        Treatment(name="Frankel (I, II, III, IV)", category=TreatmentCategory.ANA_ISLEMLER, price_eur=3000.00, currency="TL"),
        Treatment(name="Twin Block", category=TreatmentCategory.ANA_ISLEMLER, price_eur=3300.00, currency="TL"),
        Treatment(name="Horlama Apareyi (Akrilik)", category=TreatmentCategory.ANA_ISLEMLER, price_eur=2900.00, currency="TL"),
        Treatment(name="Herbst", category=TreatmentCategory.ANA_ISLEMLER, price_eur=4000.00, currency="TL"),
        Treatment(name="Horlama Apareyi (Plak)", category=TreatmentCategory.ANA_ISLEMLER, price_eur=3600.00, currency="TL"),
        Treatment(name="Horlama Apareyi (SomnoMed)", category=TreatmentCategory.ANA_ISLEMLER, price_eur=5000.00, currency="TL"),
        Treatment(name="Hotz Plate", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1100.00, currency="TL"),
        Treatment(name="Beyazlatma Plağı", category=TreatmentCategory.ANA_ISLEMLER, price_eur=1100.00, currency="TL"),
        Treatment(name="Sporcu Plağı", category=TreatmentCategory.ANA_ISLEMLER, price_eur=2800.00, currency="TL"),
        Treatment(name="PRO Sporcu Plağı", category=TreatmentCategory.ANA_ISLEMLER, price_eur=4000.00, currency="TL"),
        Treatment(name="Bant", category=TreatmentCategory.EKSTRA_ISLEMLER, price_eur=3.00, currency="USD"),
        Treatment(name="Activator Tüpü", category=TreatmentCategory.EKSTRA_ISLEMLER, price_eur=5.00, currency="EUR"),
        Treatment(name="Tüplü Bant", category=TreatmentCategory.EKSTRA_ISLEMLER, price_eur=4.00, currency="USD"),
        Treatment(name="Hyrax Vida", category=TreatmentCategory.EKSTRA_ISLEMLER, price_eur=20.00, currency="EUR"),
        Treatment(name="Lingual Sheat", category=TreatmentCategory.EKSTRA_ISLEMLER, price_eur=4.00, currency="USD"),
        Treatment(name="3 way (Bertoni)", category=TreatmentCategory.EKSTRA_ISLEMLER, price_eur=25.00, currency="EUR"),
        Treatment(name="Ekstra Vida", category=TreatmentCategory.EKSTRA_ISLEMLER, price_eur=4.50, currency="EUR"),
        Treatment(name="Fantype (Hyrax)", category=TreatmentCategory.EKSTRA_ISLEMLER, price_eur=60.00, currency="EUR"),
        Treatment(name="Z Zemberek, Finger Spring Vs.", category=TreatmentCategory.EKSTRA_ISLEMLER, price_eur=100.00, currency="TL"),
        Treatment(name="Oklüzyon Yükseltme", category=TreatmentCategory.EKSTRA_ISLEMLER, price_eur=100.00, currency="TL"),
    ]

    settings_defaults = Settings.DEFAULTS.copy()
    settings_defaults["invoice_next_number"] = "1"

    admin_password, is_generated = _resolve_admin_password()
    admin_user = User(
        username="admin",
        password_hash=_hash_password(admin_password),
        full_name="Admin",
        role=User.ROLE_ADMIN,
    )

    sample_rate = ExchangeRate(
        rate_date=date.today(),
        eur_to_try=37.50,
        source="ecb",
    )

    db.session.add_all(treatments)

    existing_settings = {
        s.key for s in db.session.execute(db.select(Settings)).scalars().all()
    }
    new_settings = [
        Settings(key=k, value=v) for k, v in settings_defaults.items() if k not in existing_settings
    ]
    if new_settings:
        db.session.add_all(new_settings)

    db.session.add(admin_user)

    existing_rate = db.session.execute(
        db.select(ExchangeRate).where(
            ExchangeRate.rate_date == date.today(),
            ExchangeRate.source == "ecb",
        )
    ).scalar_one_or_none()
    if not existing_rate:
        db.session.add(sample_rate)

    _seed_parties(db.session)
    db.session.commit()

    if is_generated:
        generated_password = admin_password
    return generated_password


def migrate_patients_to_parties() -> int:
    """Migrate existing patients to Party records. Must be called inside app context."""
    from app.extensions import db

    migrated = 0
    patients = db.session.execute(
        db.select(Patient).where(Patient.party_id.is_(None))
    ).scalars().all()

    for patient in patients:
        existing = db.session.execute(
            db.select(Party).where(
                Party.party_type == PartyType.PATIENT,
                Party.first_name == patient.first_name,
                Party.last_name == patient.last_name,
                Party.phone == patient.phone,
            )
        ).scalar_one_or_none()

        if existing:
            patient.party_id = existing.id
        else:
            party = Party(
                party_type=PartyType.PATIENT,
                name=f"{patient.first_name} {patient.last_name}",
                first_name=patient.first_name,
                last_name=patient.last_name,
                phone=patient.phone,
                email=patient.email,
                address=patient.address,
                tax_id=getattr(patient, 'tax_id', None),
                notes=patient.notes,
                date_of_birth=patient.date_of_birth,
                treatment_status=patient.treatment_status,
                is_active=patient.is_active,
            )
            db.session.add(party)
            db.session.flush()
            patient.party_id = party.id
        migrated += 1

    if migrated > 0:
        db.session.commit()

    return migrated


def link_invoices_to_parties() -> int:
    """Link existing invoices to parties via their patients. Must be called inside app context."""
    from app.extensions import db

    linked = 0
    invoices = db.session.execute(
        db.select(Invoice).where(Invoice.party_id.is_(None))
    ).scalars().all()

    for invoice in invoices:
        if invoice.patient and invoice.patient.party_id:
            invoice.party_id = invoice.patient.party_id
            linked += 1

    if linked > 0:
        db.session.commit()

    return linked
