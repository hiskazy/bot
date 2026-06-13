import os
import sqlite3
import requests
import re
import time
import json
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
offset = 0
users = {}
client_states = {}
editing_states = {}

MASTER_ADMIN_ID = 1897413803
BOT_USERNAME = "LeadFlowHQ_bot"
CRYPTOBOT_TOKEN = os.getenv("CRYPTOBOT_TOKEN")

PRICES = {
    "month": 490,
    "3months": 1290,
    "year": 4450
}

SUBSCRIPTION_DAYS = {
    "month": 30,
    "3months": 90,
    "year": 365
}

TRIAL_DAYS = 14

# Отключаем прокси
for var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'NO_PROXY', 'no_proxy']:
    os.environ.pop(var, None)
os.environ['NO_PROXY'] = '*'

# СОЗДАНИЕ БАЗЫ ДАННЫХ
conn = sqlite3.connect("saas.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS businesses(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER UNIQUE,
    business_name TEXT,
    business_slug TEXT UNIQUE,
    address TEXT,
    phone TEXT,
    working_start INTEGER DEFAULT 9,
    working_end INTEGER DEFAULT 21,
    is_active BOOLEAN DEFAULT 1,
    subscription_end DATE,
    is_trial BOOLEAN DEFAULT 1,
    notification_sent_3d BOOLEAN DEFAULT 0,
    expired_notification_sent BOOLEAN DEFAULT 0
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS admins(
    user_id INTEGER PRIMARY KEY,
    business_id INTEGER,
    added_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS services(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER,
    service_name TEXT,
    duration INTEGER,
    price INTEGER
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS bookings(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER,
    client_id INTEGER,
    client_name TEXT,
    client_phone TEXT,
    service_name TEXT,
    booking_date TEXT,
    booking_time TEXT,
    status TEXT DEFAULT 'pending',
    reminder_sent BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS payments(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    business_id INTEGER,
    payment_id TEXT UNIQUE,
    amount INTEGER,
    plan TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# Добавляем недостающие колонки
try:
    cur.execute("ALTER TABLE bookings ADD COLUMN status TEXT DEFAULT 'pending'")
except: pass
try:
    cur.execute("ALTER TABLE bookings ADD COLUMN reminder_sent BOOLEAN DEFAULT 0")
except: pass
try:
    cur.execute("ALTER TABLE bookings ADD COLUMN client_id INTEGER")
except: pass
try:
    cur.execute("ALTER TABLE businesses ADD COLUMN notification_sent_3d BOOLEAN DEFAULT 0")
except: pass
try:
    cur.execute("ALTER TABLE businesses ADD COLUMN expired_notification_sent BOOLEAN DEFAULT 0")
except: pass
try:
    cur.execute("ALTER TABLE businesses ADD COLUMN working_start INTEGER DEFAULT 9")
except: pass
try:
    cur.execute("ALTER TABLE businesses ADD COLUMN working_end INTEGER DEFAULT 21")
except: pass
try:
    cur.execute("ALTER TABLE admins ADD COLUMN added_by INTEGER")
except: pass
try:
    cur.execute("ALTER TABLE admins ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
except: pass

conn.commit()
conn.close()


def send(chat_id, text):
    try:
        requests.post(f"{BASE_URL}/sendMessage", data={"chat_id": chat_id, "text": text}, proxies={})
    except Exception as e:
        print(f"Ошибка отправки: {e}")


def send_inline_keyboard(chat_id, text, buttons):
    reply_markup = {"inline_keyboard": buttons}
    try:
        requests.post(f"{BASE_URL}/sendMessage",
                      data={"chat_id": chat_id, "text": text, "reply_markup": json.dumps(reply_markup)},
                      proxies={})
    except Exception as e:
        print(f"Ошибка отправки: {e}")


def send_admin_notification(admin_id, booking_info):
    msg = f"📅 Новая запись!\n\n"
    msg += f"👤 Имя: {booking_info['client_name']}\n"
    msg += f"📞 Телефон: {booking_info['client_phone']}\n"
    msg += f"💇 Услуга: {booking_info['service_name']}\n"
    msg += f"📅 Дата: {booking_info['booking_date']}\n"
    msg += f"⏰ Время: {booking_info['booking_time']}\n"
    msg += f"🆔 ID записи: {booking_info['booking_id']}\n\n"
    msg += f"Статус: ожидает подтверждения"

    buttons = [
        [{"text": "✅ Подтвердить", "callback_data": f"confirm_{booking_info['booking_id']}"}],
        [{"text": "❌ Отменить", "callback_data": f"reject_{booking_info['booking_id']}"}]
    ]
    send_inline_keyboard(admin_id, msg, buttons)


def check_reminders():
    while True:
        try:
            conn = sqlite3.connect("saas.db")
            cur = conn.cursor()
            cur.execute("""
                SELECT id, client_id, client_name, service_name, booking_date, booking_time
                FROM bookings 
                WHERE status = 'confirmed' 
                AND (reminder_sent IS NULL OR reminder_sent = 0)
                AND datetime(booking_date || ' ' || booking_time) BETWEEN datetime('now') AND datetime('now', '+1 hour')
            """)
            reminders = cur.fetchall()
            for reminder in reminders:
                if reminder[1]:
                    send(reminder[1], f"🔔 Напоминание!\n\nУ вас запись через час:\n💇 {reminder[3]}\n📅 {reminder[4]} {reminder[5]}")
                cur.execute("UPDATE bookings SET reminder_sent=1 WHERE id=?", (reminder[0],))
                conn.commit()
            conn.close()
        except Exception as e:
            print(f"Ошибка проверки напоминаний: {e}")
        time.sleep(60)


def check_subscription_expiry():
    while True:
        try:
            now = datetime.now()
            three_days_later = now + timedelta(days=3)
            conn = sqlite3.connect("saas.db")
            cur = conn.cursor()
            cur.execute("""
                SELECT owner_id, business_name, subscription_end 
                FROM businesses 
                WHERE subscription_end <= ? AND subscription_end > ? AND (notification_sent_3d IS NULL OR notification_sent_3d = 0)
            """, (three_days_later.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")))
            expiring = cur.fetchall()
            for business in expiring:
                send(business[0], f"⚠️ Ваша подписка истекает через 3 дня!\n\nБизнес: {business[1]}\nДата окончания: {business[2]}\n\nДля продления используйте /subscription")
                cur.execute("UPDATE businesses SET notification_sent_3d=1 WHERE owner_id=?", (business[0],))
                conn.commit()
            cur.execute("""
                SELECT owner_id, business_name, subscription_end 
                FROM businesses 
                WHERE subscription_end < ? AND (expired_notification_sent IS NULL OR expired_notification_sent = 0)
            """, (now.strftime("%Y-%m-%d"),))
            expired = cur.fetchall()
            for business in expired:
                send(business[0], f"❌ Ваша подписка истекла!\n\nБизнес: {business[1]}\nДата окончания: {business[2]}\n\nДля продления используйте /subscription")
                cur.execute("UPDATE businesses SET expired_notification_sent=1 WHERE owner_id=?", (business[0],))
                conn.commit()
            conn.close()
        except Exception as e:
            print(f"Ошибка проверки подписок: {e}")
        time.sleep(3600)


def is_admin(user_id):
    if user_id == MASTER_ADMIN_ID:
        return True
    conn = sqlite3.connect("saas.db")
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
    result = cur.fetchone()
    conn.close()
    return result is not None


def get_admin_business(user_id):
    conn = sqlite3.connect("saas.db")
    cur = conn.cursor()
    cur.execute("""
        SELECT id, business_name, subscription_end, is_trial, working_start, working_end
        FROM businesses WHERE owner_id=?
    """, (user_id,))
    result = cur.fetchone()
    conn.close()
    return result


def get_booking_stats(business_id, period):
    conn = sqlite3.connect("saas.db")
    cur = conn.cursor()
    now = datetime.now()
    if period == "day":
        start_date = now.strftime("%Y-%m-%d")
        cur.execute("SELECT COUNT(*), SUM(s.price), b.status FROM bookings b JOIN services s ON b.service_name = s.service_name AND b.business_id = s.business_id WHERE b.business_id = ? AND b.booking_date = ? GROUP BY b.status", (business_id, start_date))
    elif period == "week":
        week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        cur.execute("SELECT COUNT(*), SUM(s.price), b.status FROM bookings b JOIN services s ON b.service_name = s.service_name AND b.business_id = s.business_id WHERE b.business_id = ? AND b.booking_date >= ? GROUP BY b.status", (business_id, week_ago))
    else:
        month_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        cur.execute("SELECT COUNT(*), SUM(s.price), b.status FROM bookings b JOIN services s ON b.service_name = s.service_name AND b.business_id = s.business_id WHERE b.business_id = ? AND b.booking_date >= ? GROUP BY b.status", (business_id, month_ago))
    results = cur.fetchall()
    conn.close()
    return results


def get_subscription_status(user_id):
    business = get_admin_business(user_id)
    if not business:
        return "нет бизнеса"
    subscription_end_str = business[2]
    is_trial = business[3]
    if not subscription_end_str:
        return "нет подписки"
    subscription_end = datetime.strptime(subscription_end_str, "%Y-%m-%d")
    now = datetime.now()
    if subscription_end < now:
        return "истекла"
    days_left = (subscription_end - now).days
    if is_trial:
        return f"пробный период, осталось {days_left} дн."
    else:
        return f"активна до {subscription_end.strftime('%d.%m.%Y')}"


def is_valid_booking_time(business_id, date_str, time_str):
    booking_datetime = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    if booking_datetime < datetime.now():
        return False, "Дата и время не могут быть в прошлом"
    conn = sqlite3.connect("saas.db")
    cur = conn.cursor()
    cur.execute("SELECT working_start, working_end FROM businesses WHERE id=?", (business_id,))
    result = cur.fetchone()
    conn.close()
    if result:
        working_start, working_end = result
        hour = int(time_str.split(":")[0])
        if hour < working_start or hour >= working_end:
            return False, f"Барбершоп работает с {working_start}:00 до {working_end}:00"
    return True, "OK"


def create_payment_link(user_id, business_id, amount_rub, plan, days):
    try:
        url = "https://pay.crypt.bot/api/createInvoice"
        headers = {"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN, "Content-Type": "application/json"}
        data = {"amount": str(amount_rub), "currency_type": "fiat", "fiat": "RUB", "accepted_assets": "USDT,BTC,TON", "description": f"Подписка на бот на {days} дней", "paid_btn_name": "openBot", "paid_btn_url": f"https://t.me/{BOT_USERNAME}", "payload": f"user_{user_id}_business_{business_id}_plan_{plan}", "expires_in": 3600}
        response = requests.post(url, headers=headers, json=data, proxies={})
        result = response.json()
        if result.get("ok"):
            return result["result"]["bot_invoice_url"]
        else:
            print(f"Ошибка Crypto Bot: {result}")
            return None
    except Exception as e:
        print(f"Ошибка создания платежа: {e}")
        return None


def check_payment_status(payload):
    try:
        url = "https://pay.crypt.bot/api/getInvoices"
        headers = {"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN, "Content-Type": "application/json"}
        params = {"payload": payload}
        response = requests.get(url, headers=headers, params=params, proxies={})
        result = response.json()
        if result.get("ok") and result.get("result"):
            for invoice in result["result"]["items"]:
                if invoice.get("status") == "paid":
                    return True, invoice
        return False, None
    except Exception as e:
        print(f"Ошибка проверки платежа: {e}")
        return False, None


def activate_subscription(business_id, days):
    conn = sqlite3.connect("saas.db")
    cur = conn.cursor()
    cur.execute("SELECT subscription_end FROM businesses WHERE id=?", (business_id,))
    result = cur.fetchone()
    now = datetime.now()
    if result and result[0]:
        current_end = datetime.strptime(result[0], "%Y-%m-%d")
        if current_end > now:
            new_end = current_end + timedelta(days=days)
        else:
            new_end = now + timedelta(days=days)
    else:
        new_end = now + timedelta(days=days)
    new_end_str = new_end.strftime("%Y-%m-%d")
    cur.execute("UPDATE businesses SET subscription_end=?, is_trial=0, notification_sent_3d=0, expired_notification_sent=0 WHERE id=?", (new_end_str, business_id))
    conn.commit()
    conn.close()
    return new_end_str


def generate_unique_slug(business_name, user_id):
    base_slug = re.sub(r'[^a-z0-9]', '-', business_name.lower())
    base_slug = re.sub(r'-+', '-', base_slug).strip('-')
    slug = f"{base_slug}-{user_id % 10000}"
    conn = sqlite3.connect("saas.db")
    cur = conn.cursor()
    counter = 1
    while True:
        cur.execute("SELECT id FROM businesses WHERE business_slug=?", (slug,))
        if not cur.fetchone():
            break
        slug = f"{base_slug}-{user_id % 10000}-{counter}"
        counter += 1
    conn.close()
    return slug


reminder_thread = threading.Thread(target=check_reminders, daemon=True)
reminder_thread.start()
subscription_thread = threading.Thread(target=check_subscription_expiry, daemon=True)
subscription_thread.start()

print(f"Бот запущен. Режим: polling")

# Удаляем вебхук перед запуском polling
try:
    requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", proxies={})
    print("Вебхук удалён")
except:
    pass

while True:
    try:
        response = requests.get(f"{BASE_URL}/getUpdates", params={"offset": offset, "timeout": 30}, proxies={})
        data = response.json()

        for update in data.get("result", []):
            offset = update["update_id"] + 1

            if "callback_query" in update:
                callback = update["callback_query"]
                chat_id = callback["message"]["chat"]["id"]
                user_id = callback["from"]["id"]
                data_callback = callback["data"]
                
                requests.post(f"{BASE_URL}/answerCallbackQuery", data={"callback_query_id": callback["id"]}, proxies={})
                
                if data_callback.startswith("confirm_"):
                    booking_id = int(data_callback.split("_")[1])
                    conn = sqlite3.connect("saas.db")
                    cur = conn.cursor()
                    cur.execute("UPDATE bookings SET status='confirmed' WHERE id=?", (booking_id,))
                    conn.commit()
                    cur.execute("SELECT client_id FROM bookings WHERE id=?", (booking_id,))
                    row = cur.fetchone()
                    conn.close()
                    send(chat_id, f"✅ Запись #{booking_id} подтверждена!")
                    if row and row[0]:
                        send(row[0], f"✅ Ваша запись подтверждена! Ждем вас.")
                    continue
                
                elif data_callback.startswith("reject_"):
                    booking_id = int(data_callback.split("_")[1])
                    conn = sqlite3.connect("saas.db")
                    cur = conn.cursor()
                    cur.execute("UPDATE bookings SET status='rejected' WHERE id=?", (booking_id,))
                    conn.commit()
                    cur.execute("SELECT client_id FROM bookings WHERE id=?", (booking_id,))
                    row = cur.fetchone()
                    conn.close()
                    send(chat_id, f"❌ Запись #{booking_id} отменена!")
                    if row and row[0]:
                        send(row[0], f"❌ Ваша запись отменена. Пожалуйста, свяжитесь с барбершопом.")
                    continue
                
                elif data_callback.startswith("cancel_"):
                    booking_id = int(data_callback.split("_")[1])
                    conn = sqlite3.connect("saas.db")
                    cur = conn.cursor()
                    cur.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
                    conn.commit()
                    conn.close()
                    send(chat_id, f"✅ Запись #{booking_id} отменена!")
                    continue
                
                elif data_callback.startswith("edit_service_"):
                    service_id = int(data_callback.split("_")[2])
                    editing_states[user_id] = {"step": "edit_field", "service_id": service_id}
                    buttons = [
                        [{"text": "Изменить название", "callback_data": f"edit_name_{service_id}"}],
                        [{"text": "Изменить длительность", "callback_data": f"edit_duration_{service_id}"}],
                        [{"text": "Изменить цену", "callback_data": f"edit_price_{service_id}"}],
                        [{"text": "Назад", "callback_data": "back_to_services"}]
                    ]
                    send_inline_keyboard(chat_id, "Что хотите изменить?", buttons)
                    continue
                
                elif data_callback.startswith("edit_name_"):
                    service_id = int(data_callback.split("_")[2])
                    editing_states[user_id] = {"step": "edit_name", "service_id": service_id}
                    send(chat_id, "Введите новое название услуги:")
                    continue
                
                elif data_callback.startswith("edit_duration_"):
                    service_id = int(data_callback.split("_")[2])
                    editing_states[user_id] = {"step": "edit_duration", "service_id": service_id}
                    send(chat_id, "Введите новую длительность в минутах:")
                    continue
                
                elif data_callback.startswith("edit_price_"):
                    service_id = int(data_callback.split("_")[2])
                    editing_states[user_id] = {"step": "edit_price", "service_id": service_id}
                    send(chat_id, "Введите новую цену в рублях:")
                    continue
                
                elif data_callback.startswith("delete_service_"):
                    service_id = int(data_callback.split("_")[2])
                    conn = sqlite3.connect("saas.db")
                    cur = conn.cursor()
                    cur.execute("DELETE FROM services WHERE id=?", (service_id,))
                    conn.commit()
                    conn.close()
                    send(chat_id, f"✅ Услуга удалена!")
                    continue
                
                elif data_callback == "edit_work_hours":
                    editing_states[user_id] = {"step": "edit_start"}
                    send(chat_id, "Введите время начала работы (в часах от 0 до 23):\nПример: 9")
                    continue
                
                elif data_callback == "stats_day":
                    business = get_admin_business(user_id)
                    if business:
                        stats = get_booking_stats(business[0], "day")
                        msg = f"📊 Статистика за сегодня:\n\n"
                        total = 0
                        total_sum = 0
                        for stat in stats:
                            status_name = "подтверждены" if stat[2] == "confirmed" else "ожидают" if stat[2] == "pending" else "отменены"
                            msg += f"{status_name}: {stat[0]} шт., {stat[1] if stat[1] else 0} руб.\n"
                            total += stat[0] if stat[0] else 0
                            total_sum += stat[1] if stat[1] else 0
                        msg += f"\nВсего записей: {total}\nОбщая сумма: {total_sum} руб."
                        send(chat_id, msg)
                    continue
                
                elif data_callback == "stats_week":
                    business = get_admin_business(user_id)
                    if business:
                        stats = get_booking_stats(business[0], "week")
                        msg = f"📊 Статистика за неделю:\n\n"
                        total = 0
                        total_sum = 0
                        for stat in stats:
                            status_name = "подтверждены" if stat[2] == "confirmed" else "ожидают" if stat[2] == "pending" else "отменены"
                            msg += f"{status_name}: {stat[0]} шт., {stat[1] if stat[1] else 0} руб.\n"
                            total += stat[0] if stat[0] else 0
                            total_sum += stat[1] if stat[1] else 0
                        msg += f"\nВсего записей: {total}\nОбщая сумма: {total_sum} руб."
                        send(chat_id, msg)
                    continue
                
                elif data_callback == "stats_month":
                    business = get_admin_business(user_id)
                    if business:
                        stats = get_booking_stats(business[0], "month")
                        msg = f"📊 Статистика за месяц:\n\n"
                        total = 0
                        total_sum = 0
                        for stat in stats:
                            status_name = "подтверждены" if stat[2] == "confirmed" else "ожидают" if stat[2] == "pending" else "отменены"
                            msg += f"{status_name}: {stat[0]} шт., {stat[1] if stat[1] else 0} руб.\n"
                            total += stat[0] if stat[0] else 0
                            total_sum += stat[1] if stat[1] else 0
                        msg += f"\nВсего записей: {total}\nОбщая сумма: {total_sum} руб."
                        send(chat_id, msg)
                    continue
                
                elif data_callback == "back_to_services":
                    business = get_admin_business(user_id)
                    if business:
                        conn = sqlite3.connect("saas.db")
                        cur = conn.cursor()
                        cur.execute("SELECT id, service_name, duration, price FROM services WHERE business_id=?", (business[0],))
                        services = cur.fetchall()
                        conn.close()
                        if services:
                            msg = "📋 Ваши услуги:\n\n"
                            for s in services:
                                msg += f"✂️ {s[1]} - {s[3]} руб. ({s[2]} мин)\n"
                            buttons = []
                            for s in services:
                                buttons.append([{"text": f"✏️ {s[1]}", "callback_data": f"edit_service_{s[0]}"}])
                                buttons.append([{"text": f"🗑 Удалить {s[1]}", "callback_data": f"delete_service_{s[0]}"}])
                            buttons.append([{"text": "📊 Статистика", "callback_data": "stats_menu"}])
                            buttons.append([{"text": "⏰ Часы работы", "callback_data": "edit_work_hours"}])
                            send_inline_keyboard(chat_id, msg, buttons)
                        else:
                            send(chat_id, "У вас нет услуг. Добавьте через /addservice")
                    continue
                
                elif data_callback == "stats_menu":
                    buttons = [
                        [{"text": "За сегодня", "callback_data": "stats_day"}],
                        [{"text": "За неделю", "callback_data": "stats_week"}],
                        [{"text": "За месяц", "callback_data": "stats_month"}],
                        [{"text": "Назад", "callback_data": "back_to_services"}]
                    ]
                    send_inline_keyboard(chat_id, "📊 Выберите период для статистики:", buttons)
                    continue
                
                elif data_callback == "buy_subscription":
                    buttons = [
                        [{"text": f"💰 1 месяц — {PRICES['month']} ₽", "callback_data": "pay_month"}],
                        [{"text": f"💰 3 месяца — {PRICES['3months']} ₽", "callback_data": "pay_3months"}],
                        [{"text": f"💰 12 месяцев — {PRICES['year']} ₽", "callback_data": "pay_year"}]
                    ]
                    send_inline_keyboard(chat_id, "Выберите тариф:", buttons)
                    continue
                
                elif data_callback in ["pay_month", "pay_3months", "pay_year"]:
                    if data_callback == "pay_month":
                        amount = PRICES["month"]
                        days = SUBSCRIPTION_DAYS["month"]
                        plan = "month"
                    elif data_callback == "pay_3months":
                        amount = PRICES["3months"]
                        days = SUBSCRIPTION_DAYS["3months"]
                        plan = "3months"
                    else:
                        amount = PRICES["year"]
                        days = SUBSCRIPTION_DAYS["year"]
                        plan = "year"
                    
                    business = get_admin_business(user_id)
                    if not business:
                        send(chat_id, "❌ Сначала зарегистрируйте бизнес через /register")
                        continue
                    
                    business_id = business[0]
                    payment_url = create_payment_link(user_id, business_id, amount, plan, days)
                    
                    if payment_url:
                        send(chat_id, f"💳 Оплата подписки\n\nСумма: {amount} ₽\nПериод: {days} дней\n\n🔗 [Нажмите для оплаты]({payment_url})\n\nСпособы оплаты:\n• Банковская карта\n• СБП\n• Криптовалюта\n\n✅ После оплаты нажмите «Проверить оплату»")
                        buttons = [[{"text": "🔄 Проверить оплату", "callback_data": f"check_payment_{business_id}_{plan}_{user_id}"}]]
                        send_inline_keyboard(chat_id, "Ожидаем оплату...", buttons)
                    else:
                        send(chat_id, "❌ Ошибка при создании платежа.")
                    continue
                
                elif data_callback.startswith("check_payment_"):
                    parts = data_callback.split("_")
                    business_id = int(parts[2])
                    plan = parts[3]
                    admin_user_id = int(parts[4])
                    
                    send(chat_id, "⏳ Проверяем статус платежа...")
                    payload = f"user_{admin_user_id}_business_{business_id}_plan_{plan}"
                    paid, invoice = check_payment_status(payload)
                    
                    if paid:
                        if plan == "month":
                            days = SUBSCRIPTION_DAYS["month"]
                        elif plan == "3months":
                            days = SUBSCRIPTION_DAYS["3months"]
                        else:
                            days = SUBSCRIPTION_DAYS["year"]
                        new_end = activate_subscription(business_id, days)
                        send(chat_id, f"✅ Подписка успешно активирована!\n\n📅 Действует до: {new_end}")
                    else:
                        send(chat_id, "⏳ Платёж ещё не подтверждён.\n\nЕсли вы уже оплатили, подождите 1-2 минуты.")
                    continue

            if "message" not in update:
                continue

            message = update["message"]
            chat_id = message["chat"]["id"]
            user_id = message["from"]["id"]
            text = message.get("text", "")

            print(f"Сообщение от {user_id}: {text}")

            # ADD ADMIN - ТОЛЬКО ДЛЯ ГЛАВНОГО АДМИНА
            if text == "/addadmin" and user_id == MASTER_ADMIN_ID:
                users[user_id] = {"step": "add_admin"}
                send(chat_id, "✉️ Введите Telegram ID пользователя, которого хотите сделать администратором.\n\nℹ️ Чтобы узнать ID, попросите его отправить команду /id.")
                continue

            # ADMINS - ТОЛЬКО ДЛЯ ГЛАВНОГО АДМИНА
            if text == "/admins" and user_id == MASTER_ADMIN_ID:
                conn = sqlite3.connect("saas.db")
                cur = conn.cursor()
                cur.execute("SELECT user_id, business_id, added_by, created_at FROM admins ORDER BY created_at DESC")
                admins_list = cur.fetchall()
                conn.close()
                if not admins_list:
                    send(chat_id, "👥 Список администраторов пуст.")
                else:
                    msg = "👥 **Список администраторов:**\n\n"
                    for admin in admins_list:
                        added_by = "главный админ" if admin[2] == MASTER_ADMIN_ID else f"администратором {admin[2]}"
                        msg += f"🆔 `{admin[0]}`\n   📍 Бизнес ID: {admin[1]}\n   👤 Добавлен: {added_by}\n   📅 {admin[3]}\n\n"
                    send(chat_id, msg)
                continue

            if text == "/cancel_booking":
                conn = sqlite3.connect("saas.db")
                cur = conn.cursor()
                cur.execute("SELECT id, service_name, booking_date, booking_time, status FROM bookings WHERE client_id=? AND status='pending'", (user_id,))
                bookings = cur.fetchall()
                conn.close()
                if not bookings:
                    send(chat_id, "❌ У вас нет активных записей для отмены.")
                    continue
                msg = "Выберите запись для отмены:\n\n"
                buttons = []
                for booking in bookings:
                    msg += f"🆔 {booking[0]}: {booking[1]} - {booking[2]} {booking[3]}\n"
                    buttons.append([{"text": f"Отменить #{booking[0]}", "callback_data": f"cancel_{booking[0]}"}])
                buttons.append([{"text": "Назад", "callback_data": "back"}])
                send_inline_keyboard(chat_id, msg, buttons)
                continue

            if text == "/editservice" and is_admin(user_id):
                business = get_admin_business(user_id)
                if business:
                    conn = sqlite3.connect("saas.db")
                    cur = conn.cursor()
                    cur.execute("SELECT id, service_name, duration, price FROM services WHERE business_id=?", (business[0],))
                    services = cur.fetchall()
                    conn.close()
                    if services:
                        msg = "Выберите услугу для редактирования:\n\n"
                        buttons = []
                        for s in services:
                            msg += f"✂️ {s[1]} - {s[3]} руб. ({s[2]} мин)\n"
                            buttons.append([{"text": f"✏️ {s[1]}", "callback_data": f"edit_service_{s[0]}"}])
                        buttons.append([{"text": "Назад", "callback_data": "back"}])
                        send_inline_keyboard(chat_id, msg, buttons)
                    else:
                        send(chat_id, "У вас нет услуг. Добавьте через /addservice")
                continue

            if text == "/deleteservice" and is_admin(user_id):
                business = get_admin_business(user_id)
                if business:
                    conn = sqlite3.connect("saas.db")
                    cur = conn.cursor()
                    cur.execute("SELECT id, service_name FROM services WHERE business_id=?", (business[0],))
                    services = cur.fetchall()
                    conn.close()
                    if services:
                        msg = "Выберите услугу для удаления:\n\n"
                        buttons = []
                        for s in services:
                            buttons.append([{"text": f"🗑 {s[1]}", "callback_data": f"delete_service_{s[0]}"}])
                        buttons.append([{"text": "Назад", "callback_data": "back"}])
                        send_inline_keyboard(chat_id, msg, buttons)
                    else:
                        send(chat_id, "У вас нет услуг для удаления.")
                continue

            if text == "/stats" and is_admin(user_id):
                buttons = [
                    [{"text": "За сегодня", "callback_data": "stats_day"}],
                    [{"text": "За неделю", "callback_data": "stats_week"}],
                    [{"text": "За месяц", "callback_data": "stats_month"}]
                ]
                send_inline_keyboard(chat_id, "📊 Выберите период для статистики:", buttons)
                continue

            if text == "/workhours" and is_admin(user_id):
                editing_states[user_id] = {"step": "edit_start"}
                send(chat_id, "Введите время начала работы (в часах от 0 до 23):\nПример: 9")
                continue

            if text == "/start":
                start_param = None
                if len(text.split()) > 1:
                    start_param = text.split()[1]

                if start_param:
                    conn = sqlite3.connect("saas.db")
                    cur = conn.cursor()
                    cur.execute("SELECT id, business_name FROM businesses WHERE business_slug=?", (start_param,))
                    business = cur.fetchone()
                    conn.close()
                    if business:
                        business_id, business_name = business
                        client_states[user_id] = {"step": "name", "business_id": business_id, "business_name": business_name}
                        send(chat_id, f"Добро пожаловать в {business_name}!\n\nВведите ваше имя:")
                        continue
                    else:
                        send(chat_id, "❌ Барбершоп не найден")
                        continue

                if is_admin(user_id):
                    status = get_subscription_status(user_id)
                    business = get_admin_business(user_id)
                    menu = "🤖 Админ-панель\n\n"
                    menu += f"📊 Статус подписки: {status}\n\n"
                    menu += "Команды:\n"
                    menu += "/register - зарегистрировать барбершоп\n"
                    menu += "/mybusiness - мой барбершоп\n"
                    menu += "/addservice - добавить услугу\n"
                    menu += "/services - мои услуги\n"
                    menu += "/editservice - редактировать услуги\n"
                    menu += "/deleteservice - удалить услугу\n"
                    menu += "/bookings - записи клиентов\n"
                    menu += "/stats - статистика\n"
                    menu += "/workhours - часы работы\n"
                    menu += "/getlink - получить ссылку\n"
                    menu += "/subscription - управление подпиской"
                    if user_id == MASTER_ADMIN_ID:
                        menu += "\n\n👑 Команды главного админа:\n"
                        menu += "/addadmin - добавить администратора\n"
                        menu += "/admins - список администраторов"
                    if "истекла" in status or "нет подписки" in status:
                        buttons = [[{"text": "💳 Купить подписку", "callback_data": "buy_subscription"}]]
                        send_inline_keyboard(chat_id, menu, buttons)
                    else:
                        send(chat_id, menu)
                else:
                    conn = sqlite3.connect("saas.db")
                    cur = conn.cursor()
                    cur.execute("SELECT id, business_name FROM businesses WHERE is_active=1")
                    businesses = cur.fetchall()
                    conn.close()
                    if not businesses:
                        send(chat_id, "❌ Нет доступных барбершопов.")
                        continue
                    msg = "📋 Доступные барбершопы:\n\n"
                    for i, biz in enumerate(businesses, 1):
                        msg += f"{i}. {biz[1]}\n"
                    msg += "\nВведите номер барбершопа:"
                    client_states[user_id] = {"step": "select_business", "businesses": businesses}
                    send(chat_id, msg)
                continue

            if text == "/subscription" and is_admin(user_id):
                status = get_subscription_status(user_id)
                business = get_admin_business(user_id)
                if business and "истекла" not in status and "нет" not in status and business[2]:
                    end_date = business[2]
                    days_left = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.now()).days
                    msg = f"💳 Управление подпиской\n\n"
                    msg += f"📊 Статус: {status}\n"
                    msg += f"📅 Действует до: {end_date}\n"
                    msg += f"⏰ Осталось дней: {days_left}\n\n"
                    msg += "Хотите продлить? Нажмите на кнопку ниже."
                else:
                    msg = f"💳 Управление подпиской\n\n"
                    msg += f"📊 Статус: {status}\n\n"
                    msg += "Подписка не активна. Нажмите на кнопку ниже для оплаты."
                buttons = [[{"text": "💳 Купить/Продлить подписку", "callback_data": "buy_subscription"}]]
                send_inline_keyboard(chat_id, msg, buttons)
                continue

            if text == "/register" and is_admin(user_id):
                conn = sqlite3.connect("saas.db")
                cur = conn.cursor()
                cur.execute("SELECT id FROM businesses WHERE owner_id=?", (user_id,))
                existing = cur.fetchone()
                conn.close()
                if existing:
                    send(chat_id, "❌ У вас уже зарегистрирован барбершоп.")
                    continue
                users[user_id] = {"step": "business_name"}
                send(chat_id, "Введите название барбершопа:")
                continue

            if text == "/mybusiness" and is_admin(user_id):
                business = get_admin_business(user_id)
                if business:
                    conn = sqlite3.connect("saas.db")
                    cur = conn.cursor()
                    cur.execute("SELECT address, phone, working_start, working_end FROM businesses WHERE id=?", (business[0],))
                    info = cur.fetchone()
                    conn.close()
                    send(chat_id, f"🏪 {business[1]}\n📍 {info[0]}\n📞 {info[1]}\n⏰ Работаем: {info[2]}:00 - {info[3]}:00")
                else:
                    send(chat_id, "❌ Барбершоп не зарегистрирован.")
                continue

            if text == "/addservice" and is_admin(user_id):
                business = get_admin_business(user_id)
                if not business:
                    send(chat_id, "❌ Сначала зарегистрируйте барбершоп через /register")
                    continue
                if business[2]:
                    end_date = datetime.strptime(business[2], "%Y-%m-%d")
                    if end_date < datetime.now():
                        send(chat_id, "❌ Ваша подписка истекла. Продлите её через /subscription")
                        continue
                users[user_id] = {"step": "service_name", "business_id": business[0]}
                send(chat_id, "Введите название услуги:")
                continue

            if text == "/services" and is_admin(user_id):
                business = get_admin_business(user_id)
                if business:
                    conn = sqlite3.connect("saas.db")
                    cur = conn.cursor()
                    cur.execute("SELECT service_name, duration, price FROM services WHERE business_id=?", (business[0],))
                    services = cur.fetchall()
                    conn.close()
                    if services:
                        msg = "📋 Ваши услуги:\n\n"
                        for s in services:
                            msg += f"✂️ {s[0]} - {s[2]} руб. ({s[1]} мин)\n"
                        send(chat_id, msg)
                    else:
                        send(chat_id, "У вас нет услуг. Добавьте через /addservice")
                continue

            if text == "/bookings" and is_admin(user_id):
                business = get_admin_business(user_id)
                if business:
                    conn = sqlite3.connect("saas.db")
                    cur = conn.cursor()
                    cur.execute("SELECT id, client_name, client_phone, service_name, booking_date, booking_time, status FROM bookings WHERE business_id=? ORDER BY booking_date DESC", (business[0],))
                    bookings = cur.fetchall()
                    conn.close()
                    if bookings:
                        msg = "📅 Записи клиентов:\n\n"
                        for b in bookings:
                            status_emoji = "✅" if b[6] == "confirmed" else "⏳" if b[6] == "pending" else "❌"
                            msg += f"{status_emoji} #{b[0]}: {b[1]} ({b[2]})\n💇 {b[3]}\n📅 {b[4]} {b[5]}\n\n"
                        send(chat_id, msg)
                    else:
                        send(chat_id, "Нет записей")
                continue

            if text == "/getlink" and is_admin(user_id):
                business = get_admin_business(user_id)
                if business:
                    conn = sqlite3.connect("saas.db")
                    cur = conn.cursor()
                    cur.execute("SELECT business_slug FROM businesses WHERE owner_id=?", (user_id,))
                    slug = cur.fetchone()
                    conn.close()
                    if slug and slug[0]:
                        link = f"https://t.me/{BOT_USERNAME}?start={slug[0]}"
                        send(chat_id, f"🔗 Ваша ссылка для клиентов:\n\n{link}\n\nОтправьте её клиентам!")
                    else:
                        send(chat_id, "❌ Ошибка: не удалось получить ссылку")
                continue

            # Обработка добавления администратора
            if user_id == MASTER_ADMIN_ID and user_id in users and users[user_id].get("step") == "add_admin":
                try:
                    new_admin_id = int(text)
                    business = get_admin_business(new_admin_id)
                    if not business:
                        send(chat_id, f"❌ Пользователь `{new_admin_id}` не зарегистрировал барбершоп. Сначала попросите его пройти регистрацию через /register")
                        del users[user_id]
                        continue
                    conn = sqlite3.connect("saas.db")
                    cur = conn.cursor()
                    cur.execute("INSERT OR REPLACE INTO admins (user_id, business_id, added_by) VALUES (?, ?, ?)", (new_admin_id, business[0], user_id))
                    conn.commit()
                    conn.close()
                    send(chat_id, f"✅ Пользователь `{new_admin_id}` добавлен как администратор.")
                    send(new_admin_id, f"🎉 Вас добавили как администратора бота! Используйте /start для входа в админ-панель.")
                    del users[user_id]
                except ValueError:
                    send(chat_id, "❌ Неверный формат ID. Введите только цифры.")
                except Exception as e:
                    send(chat_id, f"❌ Ошибка: {e}")
                    del users[user_id]
                continue

            # Обработка состояний для регистрации бизнеса и добавления услуг
            if user_id in users:
                state = users[user_id]

                if state.get("step") == "business_name":
                    state["business_name"] = text
                    state["step"] = "address"
                    send(chat_id, "Введите адрес барбершопа:")
                    continue

                if state.get("step") == "address":
                    state["address"] = text
                    state["step"] = "phone"
                    send(chat_id, "Введите телефон барбершопа:")
                    continue

                if state.get("step") == "phone":
                    slug = generate_unique_slug(state["business_name"], user_id)
                    trial_end = (datetime.now() + timedelta(days=TRIAL_DAYS)).strftime("%Y-%m-%d")
                    try:
                        conn = sqlite3.connect("saas.db")
                        cur = conn.cursor()
                        cur.execute("INSERT INTO businesses (owner_id, business_name, business_slug, address, phone, subscription_end, is_trial, working_start, working_end) VALUES (?,?,?,?,?,?,1,9,21)", (user_id, state["business_name"], slug, state["address"], text, trial_end))
                        business_id = cur.lastrowid
                        cur.execute("INSERT OR REPLACE INTO admins (user_id, business_id, added_by) VALUES (?,?,?)", (user_id, business_id, MASTER_ADMIN_ID))
                        conn.commit()
                        conn.close()
                        link = f"https://t.me/{BOT_USERNAME}?start={slug}"
                        send(chat_id, f"✅ Барбершоп успешно зарегистрирован!\n\n🏪 {state['business_name']}\n📍 {state['address']}\n📞 {text}\n\n🎁 Пробный период: {TRIAL_DAYS} дней бесплатно!\n📅 Подписка активна до: {trial_end}\n\n🔗 Ваша ссылка:\n{link}\n\n📋 Теперь добавьте услуги через /addservice")
                        del users[user_id]
                    except Exception as e:
                        send(chat_id, f"❌ Ошибка: {e}")
                        del users[user_id]
                    continue

                if state.get("step") == "service_name":
                    state["service_name"] = text
                    state["step"] = "duration"
                    send(chat_id, "Введите длительность в минутах:")
                    continue

                if state.get("step") == "duration":
                    if text.isdigit():
                        state["duration"] = int(text)
                        state["step"] = "price"
                        send(chat_id, "Введите стоимость в рублях:")
                    else:
                        send(chat_id, "❌ Введите число")
                    continue

                if state.get("step") == "price":
                    if text.isdigit():
                        try:
                            conn = sqlite3.connect("saas.db")
                            cur = conn.cursor()
                            cur.execute("INSERT INTO services (business_id, service_name, duration, price) VALUES (?,?,?,?)", (state["business_id"], state["service_name"], state["duration"], int(text)))
                            conn.commit()
                            conn.close()
                            send(chat_id, f"✅ Услуга '{state['service_name']}' добавлена!")
                            del users[user_id]
                        except Exception as e:
                            send(chat_id, f"❌ Ошибка: {e}")
                            del users[user_id]
                    else:
                        send(chat_id, "❌ Введите число")
                    continue

            # Обработка редактирования времени работы
            if user_id in editing_states and editing_states[user_id].get("step") == "edit_start":
                if text.isdigit():
                    hour = int(text)
                    if 0 <= hour <= 23:
                        editing_states[user_id]["start"] = hour
                        editing_states[user_id]["step"] = "edit_end"
                        send(chat_id, f"Время начала: {hour}:00\n\nВведите время окончания работы (в часах от 0 до 23):")
                    else:
                        send(chat_id, "❌ Введите число от 0 до 23")
                else:
                    send(chat_id, "❌ Введите число")
                continue

            if user_id in editing_states and editing_states[user_id].get("step") == "edit_end":
                if text.isdigit():
                    hour = int(text)
                    if 0 <= hour <= 23:
                        business = get_admin_business(user_id)
                        if business:
                            start_hour = editing_states[user_id]["start"]
                            conn = sqlite3.connect("saas.db")
                            cur = conn.cursor()
                            cur.execute("UPDATE businesses SET working_start=?, working_end=? WHERE id=?", (start_hour, hour, business[0]))
                            conn.commit()
                            conn.close()
                            send(chat_id, f"✅ Часы работы обновлены: {start_hour}:00 - {hour}:00")
                        del editing_states[user_id]
                    else:
                        send(chat_id, "❌ Введите число от 0 до 23")
                else:
                    send(chat_id, "❌ Введите число")
                continue

            # Обработка редактирования услуги
            if user_id in editing_states:
                state = editing_states[user_id]

                if state.get("step") == "edit_name":
                    conn = sqlite3.connect("saas.db")
                    cur = conn.cursor()
                    cur.execute("UPDATE services SET service_name=? WHERE id=?", (text, state["service_id"]))
                    conn.commit()
                    conn.close()
                    send(chat_id, f"✅ Название услуги изменено на: {text}")
                    del editing_states[user_id]
                    continue

                if state.get("step") == "edit_duration":
                    if text.isdigit():
                        conn = sqlite3.connect("saas.db")
                        cur = conn.cursor()
                        cur.execute("UPDATE services SET duration=? WHERE id=?", (int(text), state["service_id"]))
                        conn.commit()
                        conn.close()
                        send(chat_id, f"✅ Длительность изменена на: {text} минут")
                        del editing_states[user_id]
                    else:
                        send(chat_id, "❌ Введите число")
                    continue

                if state.get("step") == "edit_price":
                    if text.isdigit():
                        conn = sqlite3.connect("saas.db")
                        cur = conn.cursor()
                        cur.execute("UPDATE services SET price=? WHERE id=?", (int(text), state["service_id"]))
                        conn.commit()
                        conn.close()
                        send(chat_id, f"✅ Цена изменена на: {text} руб.")
                        del editing_states[user_id]
                    else:
                        send(chat_id, "❌ Введите число")
                    continue

            # Обработка состояний клиента
            if user_id in client_states:
                state = client_states[user_id]

                if state.get("step") == "select_business":
                    if text.isdigit():
                        idx = int(text) - 1
                        if 0 <= idx < len(state["businesses"]):
                            biz = state["businesses"][idx]
                            state["business_id"] = biz[0]
                            state["business_name"] = biz[1]
                            state["step"] = "name"
                            send(chat_id, f"✅ Вы выбрали {biz[1]}\n\nВведите ваше имя:")
                        else:
                            send(chat_id, f"❌ Введите число от 1 до {len(state['businesses'])}")
                    else:
                        send(chat_id, "❌ Введите номер барбершопа")
                    continue

                if state.get("step") == "name":
                    if text.strip():
                        state["client_name"] = text.strip()
                        state["step"] = "phone"
                        send(chat_id, "Введите ваш номер телефона:")
                    else:
                        send(chat_id, "❌ Имя не может быть пустым")
                    continue

                if state.get("step") == "phone":
                    if text.strip():
                        state["client_phone"] = text.strip()
                        conn = sqlite3.connect("saas.db")
                        cur = conn.cursor()
                        cur.execute("SELECT id, service_name, duration, price FROM services WHERE business_id=?", (state["business_id"],))
                        services = cur.fetchall()
                        conn.close()
                        if not services:
                            send(chat_id, "❌ В этом барбершопе пока нет услуг")
                            del client_states[user_id]
                            continue
                        state["services"] = services
                        state["step"] = "service"
                        msg = "📋 Выберите услугу:\n\n"
                        for i, s in enumerate(services, 1):
                            msg += f"{i}. {s[1]} - {s[3]} руб. ({s[2]} мин)\n"
                        msg += "\nВведите номер услуги:"
                        send(chat_id, msg)
                    else:
                        send(chat_id, "❌ Телефон не может быть пустым")
                    continue

                if state.get("step") == "service":
                    if text.isdigit():
                        idx = int(text) - 1
                        if 0 <= idx < len(state["services"]):
                            state["service_name"] = state["services"][idx][1]
                            state["step"] = "date"
                            send(chat_id, "Введите дату в формате ГГГГ-ММ-ДД:\nПример: 2024-12-31")
                        else:
                            send(chat_id, f"❌ Введите число от 1 до {len(state['services'])}")
                    else:
                        send(chat_id, "❌ Введите номер услуги")
                    continue

                if state.get("step") == "date":
                    if re.match(r'^\d{4}-\d{2}-\d{2}$', text):
                        if datetime.strptime(text, "%Y-%m-%d") < datetime.now().replace(hour=0, minute=0, second=0):
                            send(chat_id, "❌ Нельзя записаться на прошедшую дату.")
                            continue
                        state["booking_date"] = text
                        state["step"] = "time"
                        send(chat_id, "Введите время в формате ЧЧ:ММ:\nПример: 14:30")
                    else:
                        send(chat_id, "❌ Неверный формат. Используйте ГГГГ-ММ-ДД")
                    continue

                if state.get("step") == "time":
                    if re.match(r'^\d{2}:\d{2}$', text):
                        is_valid, error_msg = is_valid_booking_time(state["business_id"], state["booking_date"], text)
                        if not is_valid:
                            send(chat_id, f"❌ {error_msg}")
                            continue
                        state["booking_time"] = text
                        try:
                            conn = sqlite3.connect("saas.db")
                            cur = conn.cursor()
                            cur.execute("INSERT INTO bookings (business_id, client_id, client_name, client_phone, service_name, booking_date, booking_time, status) VALUES (?,?,?,?,?,?,?,?)", (state["business_id"], user_id, state["client_name"], state["client_phone"], state["service_name"], state["booking_date"], state["booking_time"], "pending"))
                            booking_id = cur.lastrowid
                            conn.commit()
                            cur.execute("SELECT owner_id FROM businesses WHERE id=?", (state["business_id"],))
                            admin_id = cur.fetchone()[0]
                            conn.close()
                            send(chat_id, f"✅ Вы успешно записаны!\n\n👤 Имя: {state['client_name']}\n📞 Телефон: {state['client_phone']}\n✂️ Барбершоп: {state['business_name']}\n💇 Услуга: {state['service_name']}\n📅 Дата: {state['booking_date']}\n⏰ Время: {state['booking_time']}\n\nСтатус: ожидает подтверждения")
                            booking_info = {'booking_id': booking_id, 'client_name': state['client_name'], 'client_phone': state['client_phone'], 'service_name': state['service_name'], 'booking_date': state['booking_date'], 'booking_time': state['booking_time']}
                            send_admin_notification(admin_id, booking_info)
                            del client_states[user_id]
                        except Exception as e:
                            send(chat_id, f"❌ Ошибка: {e}")
                            del client_states[user_id]
                    else:
                        send(chat_id, "❌ Неверный формат. Используйте ЧЧ:ММ")
                    continue

    except Exception as e:
        print(f"Ошибка в основном цикле: {e}")
        time.sleep(5)

