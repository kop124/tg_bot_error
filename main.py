import logging
import re
import os
import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from google.cloud import vision
from google.oauth2 import service_account
import gspread

# ==========================================
# 👇 ВАШІ НАЛАШТУВАННЯ 👇
TELEGRAM_TOKEN = '8507460914:AAH01YVPH1Z6NE7HpsBF5bFKg_Rdvuh3egc'
GOOGLE_CREDENTIALS_FILE = 'service_account.json'
SPREADSHEET_NAME = 'Interlocks_Log' 
SHEET_NAME = 'Sheet1'
# ==========================================

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
    print(f"❌ КРИТИЧНА ПОМИЛКА: Файл '{GOOGLE_CREDENTIALS_FILE}' не знайдено!")
    exit()

try:
    gc = gspread.service_account(filename=GOOGLE_CREDENTIALS_FILE)
    sh = gc.open(SPREADSHEET_NAME)
    worksheet = sh.worksheet(SHEET_NAME)
    vision_client = vision.ImageAnnotatorClient.from_service_account_json(GOOGLE_CREDENTIALS_FILE)
    print("✅ Google API підключено успішно.")
except Exception as e:
    print(f"❌ Помилка підключення до Google: {e}")

# --- ЛОГІКА ОЧИЩЕННЯ (FINAL VERSION) ---
def parse_medical_interface(full_text):
    data = {'name': 'Не розпізнано', 'description': 'Не розпізнано'}
    
    # 1. NAME (Тільки перший рядок після слова Name)
    name_match = re.search(r"Name\s*\n+([^\n]+)", full_text, re.IGNORECASE)
    if name_match:
        raw_name = name_match.group(1).strip()
        if "description" in raw_name.lower():
             raw_name = raw_name.lower().split("description")[0].strip()
        data['name'] = raw_name

    # 2. DESCRIPTION
    desc_match = re.search(r"Description\s*\n*(.*?)\s*Action", full_text, re.IGNORECASE | re.DOTALL)
    
    if desc_match:
        dirty_text = desc_match.group(1)
        
        # КРОК А: Шукаємо "Якір" (код помилки 000-)
        code_match = re.search(r"(\d{3}-.*)", dirty_text, re.DOTALL)
        if code_match:
            cleaner_text = code_match.group(1)
        else:
            cleaner_text = dirty_text

        # КРОК Б: Прибираємо переноси рядків
        cleaner_text = cleaner_text.replace('\n', ' ')
        
        # КРОК В: Видаляємо конкретне сміття (слова-паразити)
        garbage_phrases = [
            "Not Assigned", "DYN. OUT", "Terminates", "Override", "OK",
            "deg", "rst. en", "rly off", "YN.", "UT", "YN "
        ]
        
        for garbage in garbage_phrases:
            # Видаляємо без врахування регістру
            pattern = re.compile(re.escape(garbage), re.IGNORECASE)
            cleaner_text = pattern.sub("", cleaner_text)

        # КРОК Г: "Хвостовий фільтр"
        # Часто в кінці залишаються цифри або короткі літери (типу "151 1" або "MU 2")
        # Цей Regex каже: "Видалити з кінця рядка будь-яку послідовність цифр та коротких слів (до 3 літер)"
        cleaner_text = re.sub(r'(\s+\d+|\s+[A-Za-z.]{1,3})+\s*$', '', cleaner_text)
        
        # Фінальна чистка пробілів
        data['description'] = " ".join(cleaner_text.split())

    return data

# --- ОБРОБКА ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.message.from_user.first_name
    print(f"\n📸 Отримано фото від {user_name}")
    status_msg = await update.message.reply_text("⏳ ...")

    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()

        image = vision.Image(content=bytes(photo_bytes))
        response = vision_client.text_detection(image=image)
        
        if not response.text_annotations:
            await status_msg.edit_text("❌ Текст не знайдено.")
            return

        full_text = response.text_annotations[0].description
        
        print(f"\n--- СИРИЙ ТЕКСТ (в один рядок) ---\n{repr(full_text)}\n----------------------------------\n")
        
        parsed = parse_medical_interface(full_text)
        
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # ЗАПИС В ТАБЛИЦЮ (Тільки 3 колонки: Дата, Ім'я, Опис)
        worksheet.append_row([
            current_time,
            parsed['name'],
            parsed['description']
        ])
        
        await status_msg.edit_text(
            f"✅ **Збережено!**\n\n"
            f"🔹 **Name:** `{parsed['name']}`\n"
            f"🔸 **Desc:** {parsed['description']}",
            parse_mode='Markdown'
        )
        print(f"✅ Name: {parsed['name']}")
        print(f"✅ Desc: {parsed['description'][:50]}...")

    except Exception as e:
        print(f"❌ ПОМИЛКА: {e}")
        await status_msg.edit_text(f"⚠️ Помилка: {e}")

if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
    print("🤖 Бот запущено. Clean Version.")
    application.run_polling()