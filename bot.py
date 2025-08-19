import os
import json
import datetime
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# Конфигурация
# =========================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

# =========================
# Загружаем вопросы
# =========================
try:
    with open("questions.json", "r", encoding="utf-8") as f:
        questions = json.load(f)
    print(f"✅ Загружено {len(questions)} вопросов")
except FileNotFoundError:
    print("❌ Ошибка: файл questions.json не найден!")
    # Создаем тестовые вопросы чтобы бот мог работать
    questions = [
        {
            "id": 1,
            "category": "HTML",
            "task": "Проверьте наличие doctype",
            "code": "<!DOCTYPE html>"
        },
        {
            "id": 2,
            "category": "HTML", 
            "task": "Проверьте валидность тегов",
            "code": "<div><p>Текст</div>"
        }
    ]
except json.JSONDecodeError as e:
    print(f"❌ Ошибка в формате questions.json: {e}")
    questions = []

# =========================
# /start
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not questions:
        await update.message.reply_text("❌ Ошибка: вопросы не загружены!")
        return
        
    categories = sorted({q["category"] for q in questions})
    keyboard = [[InlineKeyboardButton(cat, callback_data=f"cat_{cat}")] for cat in categories]
    await update.message.reply_text("Выберите категорию:", reply_markup=InlineKeyboardMarkup(keyboard))

# =========================
# Выбор категории
# =========================
async def on_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.split("_")[1]
    items = [q for q in questions if q["category"] == category]
    
    if not items:
        await query.edit_message_text("❌ В этой категории нет вопросов!")
        return
        
    context.user_data["current"] = {"items": items, "index": 0}
    await show_question(query, items[0])

# =========================
# Показ вопроса
# =========================
async def show_question(query, q):
    text = f"📋 Вопрос: {q['task']}"
    if q.get("code"):
        text += f"\n\n💻 Код:\n<code>{q['code']}</code>"
    
    keyboard = [[
        InlineKeyboardButton("✅ Да", callback_data=f"ans_yes_{q['id']}"),
        InlineKeyboardButton("❌ Нет", callback_data=f"ans_no_{q['id']}"),
        InlineKeyboardButton("🟡 Частично", callback_data=f"ans_part_{q['id']}")
    ]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

# =========================
# Ответ на вопрос (кнопки)
# =========================
async def on_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 3:
        await query.edit_message_text("❌ Ошибка в данных")
        return
        
    ans = parts[1]
    qid = parts[2]
    
    try:
        qid = int(qid)
        q = next(x for x in questions if x["id"] == qid)
    except (ValueError, StopIteration):
        await query.edit_message_text("❌ Вопрос не найден!")
        return
        
    user_id = update.effective_user.id

    if ans in ("no", "part"):
        context.user_data["pending"] = {
            "question": q,
            "answer": "Нет" if ans == "no" else "Частично",
            "user_id": user_id
        }
        await query.edit_message_text(
            f"Вы выбрали «{'Нет' if ans == 'no' else 'Частично'}». \n"
            "📝 Введите комментарий:"
        )
        return

    await send_to_webhook(user_id, q, "Да", "")
    await go_next_question(query, context)

# =========================
# Приём комментария
# =========================
async def on_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "pending" not in context.user_data:
        await update.message.reply_text("❌ Нет ожидающих комментариев. Используйте /start")
        return

    pending = context.user_data.pop("pending")
    q = pending["question"]
    user_id = pending["user_id"]
    comment_text = update.message.text.strip()
    
    if not comment_text:
        await update.message.reply_text("❌ Комментарий не может быть пустым:")
        context.user_data["pending"] = pending
        return
        
    await send_to_webhook(user_id, q, pending["answer"], comment_text)
    await update.message.reply_text("✅ Комментарий сохранён")
    await go_next_question(update.message, context)

# =========================
# Переход к следующему вопросу
# =========================
async def go_next_question(message_or_query, context):
    if "current" not in context.user_data:
        if hasattr(message_or_query, "reply_text"):
            await message_or_query.reply_text("❌ Сессия завершена. Используйте /start")
        return
        
    current = context.user_data["current"]
    items = current.get("items", [])
    idx = current.get("index", 0) + 1
    context.user_data["current"]["index"] = idx

    if idx < len(items):
        next_q = items[idx]
        if hasattr(message_or_query, "edit_message_text"):
            await show_question(message_or_query, next_q)
        else:
            text = f"📋 Вопрос: {next_q['task']}"
            if next_q.get("code"):
                text += f"\n\n💻 Код:\n<code>{next_q['code']}</code>"
                
            keyboard = [[
                InlineKeyboardButton("✅ Да", callback_data=f"ans_yes_{next_q['id']}"),
                InlineKeyboardButton("❌ Нет", callback_data=f"ans_no_{next_q['id']}"),
                InlineKeyboardButton("🟡 Частично", callback_data=f"ans_part_{next_q['id']}")
            ]]
            await message_or_query.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    else:
        if hasattr(message_or_query, "reply_text"):
            await message_or_query.reply_text("🎉 Чек-лист завершён! Спасибо!")
        else:
            await message_or_query.edit_message_text("🎉 Чек-лист завершён! Спасибо!")
        context.user_data.pop("current", None)

# =========================
# Отправка в Google Apps Script
# =========================
async def send_to_webhook(user_id, q, answer, comment):
    if not WEBHOOK_URL:
        print("❌ WEBHOOK_URL не установлен, пропускаем отправку")
        return
        
    payload = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "user_id": str(user_id),
        "category": q["category"],
        "task": q["task"],
        "answer": answer,
        "code": q.get("code", ""),
        "comment": comment
    }
    try:
        response = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        print(f"✅ Данные отправлены: {response.status_code}")
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")

# =========================
# Команда /cancel
# =========================
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "pending" in context.user_data:
        context.user_data.pop("pending")
    if "current" in context.user_data:
        context.user_data.pop("current")
    await update.message.reply_text("❌ Операция отменена. /start - начать заново")

# =========================
# Команда /status
# =========================
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🤖 Бот работает! Вопросов: {len(questions)}")

# =========================
# Обработка ошибок
# =========================
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"❌ Ошибка: {context.error}")
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text("❌ Произошла ошибка. /start - начать заново")
    except:
        pass

# =========================
# Основной запуск
# =========================
def main():
    if not TELEGRAM_TOKEN:
        print("❌ Ошибка: TELEGRAM_TOKEN не установлен!")
        return
        
    print("🤖 Запуск бота...")
    print(f"📊 Вопросов: {len(questions)}")
    print(f"🌐 WEBHOOK_URL: {'Установлен' if WEBHOOK_URL else 'Не установлен'}")
    
    try:
        app = Application.builder().token(TELEGRAM_TOKEN).build()
        
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("cancel", cancel))
        app.add_handler(CommandHandler("status", status))
        app.add_handler(CallbackQueryHandler(on_category, pattern="^cat_"))
        app.add_handler(CallbackQueryHandler(on_answer, pattern="^ans_"))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_comment))
        app.add_error_handler(error_handler)

        print("✅ Бот запущен в режиме polling")
        app.run_polling()
        
    except Exception as e:
        print(f"❌ Критическая ошибка запуска: {e}")

if __name__ == "__main__":
    main()
