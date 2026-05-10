#!/usr/bin/env python3
"""
✈️ UçuşAI Bot — Groq AI + Google Flights Scraping
Tamamen ücretsiz: Groq API + Google Flights (scraping) + Telegram
"""

import logging
import os
import json
import re
import asyncio
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
from groq import Groq
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ─── API Keys ────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8656362471:AAGAZF5AfRhwmGoNNSrPEUcYs0MxdIC6pXo")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY",       "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")

# ─── Groq İstemcisi ──────────────────────────────────────────────────────────
groq_client = Groq(api_key=GROQ_API_KEY)
GROQ_MODEL  = "llama-3.3-70b-versatile"

# ─── Sohbet Geçmişi ─────────────────────────────────────────────────────────
conversation_history: dict = {}

# ─── Prompt ──────────────────────────────────────────────────────────────────

PARSE_PROMPT = """Aşağıdaki kullanıcı mesajını analiz et ve SADECE JSON formatında yanıt ver.

Bugünün tarihi: {today}
Kullanıcı mesajı: "{message}"

Şehir → IATA kodu:
istanbul=IST, ankara=ESB, izmir=ADB, antalya=AYT, trabzon=TZX, bodrum=BJV,
dalaman=DLM, gaziantep=GZT, kayseri=ASR, samsun=SZF, van=VAN, erzurum=ERZ,
diyarbakir=DIY, diyarbakır=DIY, konya=KYA, hatay=HTY, malatya=MLX, adana=ADA, bursa=YEI,
londra=LHR, paris=CDG, frankfurt=FRA, amsterdam=AMS, dubai=DXB,
new york=JFK, barcelona=BCN, barselona=BCN, roma=FCO, munih=MUC, berlin=BER,
madrid=MAD, viyana=VIE, bruksel=BRU, zurich=ZRH, stockholm=ARN,
kopenhag=CPH, oslo=OSL, tokyo=NRT, bangkok=BKK, singapur=SIN,
moskova=SVO, pekin=PEK, hong kong=HKG, sydney=SYD, toronto=YYZ

Tarih hesaplama (bugün: {today}):
- "gelecek N gün" veya "N gün içinde" → bugünden N gün sonrasına
- "bu ay" → BUGÜNDEN bu ayın son gününe (ayın başı geçmişte olsa bile bugünden başla)
- "gelecek ay" → gelecek ayın 1'inden son gününe
- "N ay içinde" → bugünden N×30 gün sonrasına
- ay adı (mayıs/haziran/temmuz vb.) → o ayın BUGÜN veya sonrasından son gününe (geçmişse gelecek yıl)
- "gelecek hafta" → bugünden 7 gün sonrasına
- ÖNEMLİ: date_from her zaman bugün ({today}) veya daha ileri bir tarih olmalı, asla geçmiş tarih verme!

KARAR KURALLARI:
- Uçuş / bilet / uçak fiyatı sorusuysa → intent = "search"
- Vize / pasaport / seyahat belgesi / giriş koşulu sorusuysa → intent = "travel_info"
- "nasıl kullanırım" / "ne yapabilirsin" / "yardım" gibi bot kullanım sorusuysa → intent = "guide"
- "merhaba", "selam", "hey", "iyi günler", "günaydın", "iyi akşamlar" gibi selamlama mesajlarıysa → intent = "greeting"
- Uçuş veya seyahatle ilgisiz konuysa → intent = "off_topic"
- Şehir veya tarih anlaşılamıyorsa → intent = "missing"

GİDİŞ-DÖNÜŞ TESPİTİ:
- Mesajda "gidiş dönüş", "gidiş-dönüş", "gidis donus", "rt", "round trip" geçiyorsa → round_trip: true
- Geçmiyorsa → round_trip: false (varsayılan tek yön)

SADECE şu formatlardan birini döndür, başka hiçbir şey yazma:

Uçuş araması (tek yön):
{{"intent":"search","origin":"IST","destination":"ADB","date_from":"2025-06-01","date_to":"2025-06-30","round_trip":false,"user_message":"İstanbul → İzmir Haziran ayı tek yön aranıyor..."}}

Uçuş araması (gidiş-dönüş):
{{"intent":"search","origin":"IST","destination":"ADB","date_from":"2025-06-01","date_to":"2025-06-30","round_trip":true,"user_message":"İstanbul → İzmir Haziran ayı gidiş-dönüş aranıyor..."}}

Seyahat bilgisi:
{{"intent":"travel_info","chat_reply":"Kısa Türkçe bilgi buraya"}}

Kullanım rehberi:
{{"intent":"guide","chat_reply":"Botu açıklayan kısa Türkçe metin"}}

Eksik bilgi:
{{"intent":"missing","chat_reply":"Eksik bilgiyi soran Türkçe mesaj"}}

Kapsam dışı:
{{"intent":"off_topic"}}

Selamlama:
{{"intent":"greeting"}}

Tarih formatı: YYYY-MM-DD
"""

CHAT_SYSTEM = """Sen UçuşAI adında Türkçe konuşan sıcak bir uçak bileti asistanısın.
Sadece uçuşlar, bilet fiyatları, vize ve seyahat kuralları hakkında yardım edersin.
Kısa, samimi ve emoji kullanan bir dille cevap ver."""

# ─── Groq: Niyet Anlama ───────────────────────────────────────────────────────

async def groq_parse_intent(user_message: str, today: datetime) -> dict:
    prompt = PARSE_PROMPT.format(
        today=today.strftime("%d/%m/%Y"),
        message=user_message
    )
    try:
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": "Sadece JSON döndür, başka hiçbir şey yazma."},
                {"role": "user",   "content": prompt}
            ],
            temperature=0.1,
            max_tokens=300,
        )
        raw = response.choices[0].message.content.strip()
        logger.info(f"Groq ham yanıt: {raw[:300]}")

        raw = re.sub(r"```json\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)
        raw = raw.strip()

        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            raw = match.group(0)

        result = json.loads(raw)

        if "intent" not in result:
            raise ValueError("intent alanı eksik")

        logger.info(f"Intent: {result.get('intent')} | origin: {result.get('origin')} | dest: {result.get('destination')}")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse hatası: {e} | Ham: {raw[:300]}")
        return {
            "intent": "missing",
            "chat_reply": "Anlayamadım. Örnek: _İstanbul'dan Ankara'ya gelecek 30 gün içinde en ucuz bilet_ ✈️"
        }
    except Exception as e:
        logger.error(f"Groq genel hata: {e}")
        return {
            "intent": "missing",
            "chat_reply": "Bir sorun oluştu, tekrar dener misiniz? 🙏"
        }


# ─── Google Flights Scraper ───────────────────────────────────────────────────

def build_skyscanner_links(origin: str, destination: str, date_from: str, date_to: str, round_trip: bool = False) -> list:
    start      = datetime.strptime(date_from, "%Y-%m-%d")
    end        = datetime.strptime(date_to,   "%Y-%m-%d")
    today      = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # Başlangıç tarihi geçmişte ise bugünden başla
    if start < today:
        start = today

    # Bitiş tarihi de geçmişte ise boş döndür
    if end < today:
        return []

    total_days = (end - start).days + 1
    step       = 1 if total_days <= 7 else (2 if total_days <= 30 else 5)

    links = []
    current = start
    while current <= end:
        date_sk = current.strftime("%y%m%d")

        if round_trip:
            return_dt = current + timedelta(days=7)
            return_sk = return_dt.strftime("%y%m%d")
            sk_url = (
                f"https://www.skyscanner.com.tr/transport/flights/"
                f"{origin.lower()}/{destination.lower()}/{date_sk}/{return_sk}/"
                f"?adultsv2=1&currency=TRY&locale=tr-TR&market=TR"
            )
        else:
            sk_url = (
                f"https://www.skyscanner.com.tr/transport/flights/"
                f"{origin.lower()}/{destination.lower()}/{date_sk}/"
                f"?adultsv2=1&currency=TRY&locale=tr-TR&market=TR"
            )

        links.append({
            "date":      current.strftime("%d.%m.%Y"),
            "weekday":   ["Pzt","Sal","Çar","Per","Cum","Cmt","Paz"][current.weekday()],
            "link":      sk_url,
            "date_str":  current.strftime("%Y-%m-%d"),
            "is_cheap":  current.weekday() in [1, 2, 6],
            "round_trip": round_trip,
        })
        current += timedelta(days=step)

    return links


async def search_date_range(origin: str, destination: str, date_from: str, date_to: str, round_trip: bool = False) -> list:
    return build_skyscanner_links(origin, destination, date_from, date_to, round_trip)


# ─── Sonuç Formatlama ─────────────────────────────────────────────────────────

async def format_results_async(flights: list, origin: str, destination: str, label: str, round_trip: bool = False) -> str:
    if not flights:
        return (
            f"😔 {origin} → {destination} için uygun tarih bulunamadı.\n\n"
            f"⚠️ Belirttiğiniz tarih aralığı geçmiş olabilir.\n"
            f"Lütfen gelecek bir tarih aralığı girin.\n\n"
            f"Örnek: _İstanbul'dan Ankara'ya gelecek 30 gün_"
        )

    start_sk = datetime.strptime(flights[0]['date_str'], "%Y-%m-%d").strftime("%y%m%d")
    sk_genel = (
        f"https://www.skyscanner.com.tr/transport/flights/"
        f"{origin.lower()}/{destination.lower()}/{start_sk}/"
        f"?adultsv2=1&currency=TRY&locale=tr-TR&market=TR"
    )

    yon        = "↔️ Gidiş-Dönüş" if round_trip else "→ Tek Yön"
    donus_notu = " (dönüş 7 gün sonrası)" if round_trip else ""

    text = (
        f"✈️ {origin} → {destination} | {yon}\n"
        f"📅 {label}{donus_notu}\n"
        f"{'─'*28}\n\n"
        f"🟢 = Ucuz olması beklenen gün (Sal/Çar/Paz)\n"
        f"🔵 = Normal gün\n\n"
    )

    for f in flights:
        emoji     = "🟢" if f["is_cheap"] else "🔵"
        cheap_tag = " ⭐" if f["is_cheap"] else ""
        text += (
            f"{emoji} {f['date']} {f['weekday']}{cheap_tag}\n"
            f"🔗 {f['link']}\n\n"
        )

    text += (
        f"{'─'*28}\n"
        f"📊 Genel arama:\n"
        f"{sk_genel}\n\n"
        f"💡 Ucuz bilet tüyoları:\n"
        f"🟢 Sal-Çar-Paz genellikle daha ucuz\n"
        f"⏰ 6-8 hafta önceden almak avantajlı\n"
        f"🌙 Gece yarısı uçuşlar daha uygun\n\n"
        f"💬 Gidiş-dönüş için: 'gidiş dönüş' ekleyin\n"
        f"🔄 /sifirla — Yeni arama"
    )
    return text


# ─── Animasyon ───────────────────────────────────────────────────────────────

async def animate_thinking(message, stop_event: asyncio.Event):
    dots = ["", ".", "..", "..."]
    i = 0
    while not stop_event.is_set():
        try:
            await message.edit_text(f"🔍 Kontrol ediyorum{dots[i % 4]}")
        except Exception:
            pass
        i += 1
        await asyncio.sleep(0.7)


# ─── Telegram Handlers ────────────────────────────────────────────────────────

HOSGELDIN_METNI = (
    "✈️ *UcuzYolcu Bot'a Hoş Geldiniz!*\n\n"
    "Merhaba! Ben yapay zeka destekli uçak bileti asistanınızım.\n"
    "Size en uygun uçuş günlerini bulmak için buradayım! 🆓\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "🤖 *Nasıl Çalışır?*\n\n"
    "1️⃣ Kalkış ve varış şehrinizi yazın\n"
    "2️⃣ Tarih aralığını belirtin\n"
    "3️⃣ Ben size en ucuz günleri ve\n"
    "    Skyscanner linklerini getiririm!\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "📌 *Örnek Kullanım:*\n\n"
    "✈️ _Trabzon'dan İstanbul'a bu ay en ucuz bilet_\n"
    "✈️ _İstanbul'dan Londra'ya gelecek 2 ay içinde_\n"
    "✈️ _Ankara'dan İzmir'e temmuz ayında hangi gün ucuz?_\n"
    "✈️ _İstanbul'dan Dubai'ye gidiş dönüş bu ay_\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "🌍 *Seyahat Bilgisi de Sorabilirsiniz:*\n\n"
    "• _İngiltere için vize gerekiyor mu?_\n"
    "• _Dubai'ye pasaportla giriş yapılır mı?_\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "💬 Komut gerekmez, *normal Türkçe* yazın!\n\n"
    "/yardim — Detaylı kullanım rehberi\n"
    "/sifirla — Sohbeti sıfırla"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conversation_history.pop(chat_id, None)
    await update.message.reply_text(HOSGELDIN_METNI, parse_mode="Markdown")


async def yardim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *UCUZYOLCU BOT — KULLANIM REHBERİ*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✅ *Şehir Adı Yazın:*\n"
        "İstanbul, Ankara, İzmir, Trabzon, Antalya,\n"
        "Londra, Paris, Dubai, Berlin, Amsterdam...\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✅ *Tarih Aralığı Örnekleri:*\n"
        "• _gelecek 30 gün_\n"
        "• _bu ay / gelecek ay_\n"
        "• _temmuz ayında_\n"
        "• _önümüzdeki 2 ay_\n"
        "• _15 Temmuz - 31 Temmuz_\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✅ *Tam Örnek Sorgular:*\n"
        "• _Trabzon'dan İstanbul'a en ucuz bu ay_\n"
        "• _İstanbul'dan Londra'ya gelecek 60 gün_\n"
        "• _Ankara'dan İzmir'e ağustos ayı en ucuz gün_\n"
        "• _İstanbul'dan Dubai'ye gidiş dönüş haziran_\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✅ *Seyahat Kuralları:*\n"
        "• _İngiltere için vize gerekiyor mu?_\n"
        "• _Dubai'ye pasaportla giriş yapılır mı?_\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 Yeşil günler → Ucuz olması beklenen günler\n"
        "🔵 Mavi günler → Normal günler\n"
        "🏆 En ucuz tahmin → Groq AI analizi\n\n"
        "🔄 /sifirla — Sohbeti sıfırla"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def sifirla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conversation_history.pop(chat_id, None)
    await update.message.reply_text(
        "🔄 Sohbet sıfırlandı!\n\n"
        "Yeni bir arama yapmak için şehir ve tarih yazın.\n"
        "Örnek: _Trabzon'dan İstanbul'a bu ay_ ✈️",
        parse_mode="Markdown"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text.strip()
    chat_id   = update.effective_chat.id
    today     = datetime.now()

    # ── Animasyon başlat ─────────────────────────────────────────────
    thinking   = await update.message.reply_text("🔍 Kontrol ediyorum...")
    stop_event = asyncio.Event()
    asyncio.create_task(animate_thinking(thinking, stop_event))

    try:
        parsed = await groq_parse_intent(user_text, today)
        intent = parsed.get("intent", "missing")
    finally:
        stop_event.set()
        await asyncio.sleep(0.8)
        try:
            await thinking.delete()
        except Exception:
            pass

    # ── Selamlama ─────────────────────────────────────────────────────
    if intent == "greeting":
        chat_id = update.effective_chat.id
        conversation_history.pop(chat_id, None)
        await update.message.reply_text(HOSGELDIN_METNI, parse_mode="Markdown")
        return

    # ── Kapsam dışı ──────────────────────────────────────────────────
    if intent == "off_topic":
        await update.message.reply_text(
            "✈️ Ben sadece *uçuşlar ve seyahat kuralları* hakkında bilgi veriyorum.\n\n"
            "Şunları sorabilirsiniz:\n"
            "• Uçuş fiyatı araması\n"
            "• Vize ve seyahat gereksinimleri\n"
            "• Bagaj ve havayolu politikaları\n\n"
            "Nasıl kullanacağınızı öğrenmek için /yardim yazın. 😊",
            parse_mode="Markdown"
        )
        return

    # ── Seyahat bilgisi ───────────────────────────────────────────────
    if intent == "travel_info":
        reply = parsed.get("chat_reply", "Bu konuda bilgi bulunamadı.")
        await update.message.reply_text(
            f"{reply}\n\n"
            "⚠️ _Seyahat öncesi resmi kaynaklardan teyit etmenizi öneririm._",
            parse_mode="Markdown"
        )
        return

    # ── Kullanım rehberi ─────────────────────────────────────────────
    if intent == "guide":
        guide_text = parsed.get("chat_reply") or (
            "Merhaba! UçuşAI Bot'u şöyle kullanabilirsin:\n\n"
            "✈️ Uçuş aramak için normal Türkçe yaz:\n"
            "• _İstanbul'dan Ankara'ya bu ay en ucuz bilet?_\n"
            "• _Trabzon'dan İstanbul'a temmuz ayında hangi gün ucuz?_\n\n"
            "🌍 Seyahat kuralları için:\n"
            "• _İngiltere için vize gerekiyor mu?_\n\n"
            "Daha fazlası için /yardim yaz! 😊"
        )
        await update.message.reply_text(guide_text, parse_mode="Markdown")
        return

    # ── Eksik bilgi ───────────────────────────────────────────────────
    if intent == "missing":
        await update.message.reply_text(
            parsed.get("chat_reply", "Biraz daha bilgi verir misiniz?")
        )
        return

    # ── Uçuş araması ─────────────────────────────────────────────────
    origin      = parsed.get("origin", "").upper()
    destination = parsed.get("destination", "").upper()
    date_from   = parsed.get("date_from", "")
    date_to     = parsed.get("date_to", "")
    round_trip  = parsed.get("round_trip", False)

    if not all([origin, destination, date_from, date_to]):
        await update.message.reply_text(
            "🤔 Şehir veya tarih bilgisini anlayamadım.\n\n"
            "Örnek: _İstanbul'dan Ankara'ya gelecek 30 gün içinde en ucuz bilet_",
            parse_mode="Markdown"
        )
        return

    # Uçuş tarama animasyonu
    scanning  = await update.message.reply_text("🔍 Kontrol ediyorum...")
    stop_scan = asyncio.Event()
    asyncio.create_task(animate_thinking(scanning, stop_scan))

    try:
        flights = await search_date_range(origin, destination, date_from, date_to, round_trip)
    finally:
        stop_scan.set()
        await asyncio.sleep(0.8)
        try:
            await scanning.delete()
        except Exception:
            pass

    label  = f"{date_from} – {date_to}"
    result = await format_results_async(flights, origin, destination, label, round_trip)
    await update.message.reply_text(
        result, parse_mode="Markdown", disable_web_page_preview=True
    )


# ─── Ana Fonksiyon ────────────────────────────────────────────────────────────

def main():
    missing = []
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "TELEGRAM_TOKENINIZI_BURAYA_YAZIN":
        missing.append("TELEGRAM_BOT_TOKEN")
    if not GROQ_API_KEY or GROQ_API_KEY == "GROQ_KEYINIZI_BURAYA_YAZIN":
        missing.append("GROQ_API_KEY")

    if missing:
        for m in missing:
            logger.error(f"❌ Eksik: {m} — lütfen dosya içine veya export ile tanımlayın.")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("yardim",  yardim))
    app.add_handler(CommandHandler("sifirla", sifirla))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("✈️ UcuzYolcu Bot başlatılıyor...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
