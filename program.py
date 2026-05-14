import asyncio
import logging
import os
import re
from typing import Dict
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)

from dotenv import load_dotenv

from api.mocker import MockDatabase
from api.schemas import (
    UserCreate, UserRoleSystem, ProjectCreate, ArtifactCreate,
    ScoreCreate, CommentCreate,
)

load_dotenv()

TOKEN = os.getenv("TOKEN")
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
db = MockDatabase()

if 1 not in db.teams:
    db.teams[1] = {"id": 1, "name": "Команда Альфа"}

registered_users: Dict[int, dict] = {}
org_data: Dict[int, dict] = {}

# Состояния
class Registration(StatesGroup):
    waiting_for_email = State()
    waiting_for_code = State()

class OrgStates(StatesGroup):
    waiting_for_criteria = State()
    waiting_for_experts = State()
    waiting_for_link = State()
    waiting_for_link_edit = State()

class TeacherReview(StatesGroup):
    waiting_for_score = State()
    waiting_for_comment = State()
    confirm_review = State()

class StudentSubmission(StatesGroup):
    waiting_for_link = State()
    confirm_submission = State()

class PeerReview(StatesGroup):
    waiting_for_score = State()
    waiting_for_comment = State()
    confirm_review = State()

# ---------------------- Клавиатуры ----------------------
def main_menu_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👔 Организатор")],
            [KeyboardButton(text="👩‍🏫 Преподаватель")],
            [KeyboardButton(text="👨‍🎓 Студент")],
            [KeyboardButton(text="🔄 Сменить роль")]
        ],
        resize_keyboard=True
    )

def org_mode_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="1️⃣ Режим 1"), KeyboardButton(text="2️⃣ Режим 2")],
            [KeyboardButton(text="3️⃣ Режим 3"), KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def student_mode_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="1️⃣ Режим 1")],
            [KeyboardButton(text="2️⃣ Режим 2")],
            [KeyboardButton(text="3️⃣ Режим 3")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def student_mode2_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статус работы")],
            [KeyboardButton(text="👥 Чужие работы")],
            [KeyboardButton(text="📤 Отправить работу")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def cancel_reply_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )

async def safe_edit(callback: CallbackQuery, text: str, kb: InlineKeyboardMarkup = None):
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await callback.answer()

# ---------------------- Регистрация (только email) ----------------------
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    if message.from_user.id in registered_users:
        await message.answer(f"👋 С возвращением, {registered_users[message.from_user.id]['email']}!", reply_markup=main_menu_kb())
        return
    await state.set_state(Registration.waiting_for_email)
    await message.answer(
        "🌟 Добро пожаловать!\nДля регистрации введите ваш email:",
        reply_markup=cancel_reply_kb()
    )

@dp.message(Registration.waiting_for_email, F.text)
async def process_email(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Регистрация отменена.", reply_markup=ReplyKeyboardRemove())
        return
    email = message.text.strip()
    if '@' not in email or '.' not in email:
        await message.answer("❌ Неверный email. Попробуйте снова:", reply_markup=cancel_reply_kb())
        return
    await state.update_data(email=email)
    await state.set_state(Registration.waiting_for_code)
    demo_code = "123"
    await state.update_data(expected_code=demo_code)
    await message.answer(f"✅ Email принят.\n🔐 Введите код подтверждения (демо-код `{demo_code}`):", parse_mode=ParseMode.MARKDOWN, reply_markup=cancel_reply_kb())

@dp.message(Registration.waiting_for_code, F.text)
async def process_code(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Регистрация отменена.", reply_markup=ReplyKeyboardRemove())
        return
    data = await state.get_data()
    if message.text.strip() == data.get('expected_code'):
        email = data['email']
        existing = await db.get_user_by_email(email)
        if existing:
            db_user = existing
        else:
            db_user = await db.create_user(UserCreate(
                name=email.split('@')[0], email=email, code="", role=UserRoleSystem.STUDENT, team_id=1
            ))
        registered_users[message.from_user.id] = {
            'email': email, 'db_id': db_user.id, 'role': None,
            'registered_at': asyncio.get_event_loop().time()
        }
        await state.clear()
        await message.answer("🎉 Регистрация завершена!\nВыберите роль:", reply_markup=main_menu_kb())
    else:
        await message.answer(f"❌ Неверный код. Попробуйте снова (демо-код: {data['expected_code']}):", reply_markup=cancel_reply_kb())

# ---------------------- Главное меню (Reply) ----------------------
@dp.message(F.text.in_(["👔 Организатор", "👩‍🏫 Преподаватель", "👨‍🎓 Студент"]))
async def role_choice(message: Message):
    if message.from_user.id not in registered_users:
        await message.answer("Сначала зарегистрируйтесь: /start")
        return
    role = message.text
    if role == "👔 Организатор":
        registered_users[message.from_user.id]['role'] = 'org'
        await message.answer("👔 Роль: Организатор\nВыберите режим:", reply_markup=org_mode_kb())
    elif role == "👩‍🏫 Преподаватель":
        registered_users[message.from_user.id]['role'] = 'teacher'
        await teacher_panel(message)
    elif role == "👨‍🎓 Студент":
        registered_users[message.from_user.id]['role'] = 'stud'
        await message.answer("👨‍🎓 Роль: Студент\nВыберите режим:", reply_markup=student_mode_kb())

@dp.message(F.text == "🔄 Сменить роль")
async def change_role_reply(message: Message):
    if message.from_user.id in registered_users:
        registered_users[message.from_user.id]['role'] = None
    await message.answer("Выберите роль:", reply_markup=main_menu_kb())

@dp.message(F.text == "🔙 Назад")
async def back_to_main(message: Message):
    user_id = message.from_user.id
    if user_id not in registered_users:
        await message.answer("Главное меню:", reply_markup=main_menu_kb())
        return
    role = registered_users[user_id].get('role')
    if role == 'org':
        await message.answer("Выберите режим:", reply_markup=org_mode_kb())
    elif role == 'stud':
        await message.answer("Выберите режим:", reply_markup=student_mode_kb())
    else:
        await message.answer("Главное меню:", reply_markup=main_menu_kb())

# ---------------------- Организатор (обработка режимов через Reply) ----------------------
@dp.message(F.text.in_(["1️⃣ Режим 1", "2️⃣ Режим 2", "3️⃣ Режим 3"]))
async def mode_router(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in registered_users:
        await message.answer("Сначала зарегистрируйтесь: /start")
        return
    role = registered_users[user_id].get('role')
    if role == 'org':
        await org_mode_router(message, state)
    elif role == 'stud':
        await student_mode_router(message)
    else:
        await message.answer("Неизвестная роль. Выберите роль в главном меню.")

async def org_mode_router(message: Message, state: FSMContext):
    mode_map = {"1️⃣ Режим 1": "org_1", "2️⃣ Режим 2": "org_2", "3️⃣ Режим 3": "org_3"}
    mode = mode_map[message.text]
    await state.clear()
    if mode == "org_2":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Загрузить критерии", callback_data=f"org_criteria_{mode}")],
            [InlineKeyboardButton(text="Результаты", callback_data="org_results")]
        ])
        await message.answer("Режим 2: выберите действие", reply_markup=kb)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Выбрать экспертов", callback_data=f"org_select_experts_{mode}")],
            [InlineKeyboardButton(text="Результаты", callback_data="org_results")]
        ])
        await message.answer(f"Режим {mode[-1]}: выберите действие", reply_markup=kb)

async def student_mode_router(message: Message):
    mode = message.text
    if mode == "1️⃣ Режим 1":
        await student_mode1(message)
    elif mode == "2️⃣ Режим 2":
        await student_mode2(message)
    elif mode == "3️⃣ Режим 3":
        await student_mode3(message)

# ---------------------- Организатор ----------------------
@dp.callback_query(F.data.startswith("org_select_experts_"))
async def select_experts(callback: CallbackQuery, state: FSMContext):
    current_mode = callback.data.replace("org_select_experts_", "")
    if callback.from_user.id not in org_data:
        org_data[callback.from_user.id] = {'mode': current_mode, 'experts': [], 'step': 'waiting_for_experts'}
    else:
        org_data[callback.from_user.id]['mode'] = current_mode
        org_data[callback.from_user.id]['step'] = 'waiting_for_experts'
    await state.update_data(current_mode=current_mode)
    await state.set_state(OrgStates.waiting_for_experts)
    experts_list = org_data[callback.from_user.id]['experts']
    experts_text = ""
    if experts_list:
        experts_text = "\n\nДобавленные эксперты:\n" + "\n".join([f"• {exp['email']}" for exp in experts_list])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Завершить выбор", callback_data="experts_done")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_to_org_mode")]
    ])
    await safe_edit(
        callback,
        f"👥 Выбор экспертов (режим {current_mode.replace('org_', '')})\n\n"
        f"Введите email эксперта, который уже зарегистрирован в боте.\n"
        f"Эксперт будет проверять работы.{experts_text}\n\n📧 Email эксперта:",
        kb
    )

@dp.message(OrgStates.waiting_for_experts, F.text)
async def process_expert_email(message: Message, state: FSMContext):
    email = message.text.strip()
    expert_found = None
    for user_id, user_data in registered_users.items():
        if user_data.get('email', '').lower() == email.lower():
            expert_found = {'id': user_id, 'email': user_data['email']}
            break
    if not expert_found:
        all_users = "\n".join([f"• {data['email']}" for data in registered_users.values()])
        await message.answer(
            f"❌ Пользователь с email '{email}' не найден!\n\nЗарегистрированные пользователи:\n{all_users}\n\nПопробуйте снова:"
        )
        return
    if email.lower() in [exp['email'].lower() for exp in org_data[message.from_user.id]['experts']]:
        await message.answer(f"⚠️ Эксперт {expert_found['email']} уже добавлен!\n\nВведите другого эксперта.")
        return
    org_data[message.from_user.id]['experts'].append(expert_found)
    experts_list = org_data[message.from_user.id]['experts']
    experts_text = "\n".join([f"• {exp['email']}" for exp in experts_list])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Завершить выбор", callback_data="experts_done")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_to_org_mode")]
    ])
    await message.answer(
        f"✅ Эксперт добавлен!\n\n📧 {expert_found['email']}\n\n"
        f"Текущий список экспертов:\n{experts_text}\n\nВведите следующего эксперта или нажмите 'Завершить выбор':",
        reply_markup=kb
    )

@dp.callback_query(F.data == "experts_done")
async def experts_done(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in org_data:
        await callback.answer("Данные не найдены!", show_alert=True)
        return
    experts = org_data[callback.from_user.id]['experts']
    if not experts:
        await callback.answer("❌ Добавьте хотя бы одного эксперта!", show_alert=True)
        return
    current_mode = org_data[callback.from_user.id]['mode']
    if current_mode == "org_3":
        await ask_for_criteria(callback, state, current_mode)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, загрузить критерии", callback_data=f"need_criteria_{current_mode}")],
            [InlineKeyboardButton(text="❌ Нет, загрузить только работы", callback_data=f"no_criteria_{current_mode}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_to_org_mode")]
        ])
        experts_text = "\n".join([f"• {exp['email']}" for exp in experts])
        await safe_edit(callback,
            f"👥 Выбранные эксперты:\n\n{experts_text}\n\n✅ Выбор экспертов завершен!\n\nТребуется ли загрузить критерии оценки?",
            kb)

@dp.callback_query(F.data.startswith("need_criteria_"))
async def need_criteria(callback: CallbackQuery, state: FSMContext):
    current_mode = callback.data.replace("need_criteria_", "")
    await ask_for_criteria(callback, state, current_mode)

@dp.callback_query(F.data.startswith("no_criteria_"))
async def no_criteria(callback: CallbackQuery, state: FSMContext):
    current_mode = callback.data.replace("no_criteria_", "")
    if callback.from_user.id in org_data:
        org_data[callback.from_user.id]['criteria_accepted'] = False
        org_data[callback.from_user.id]['criteria'] = None
    await ask_for_work_link(callback, state, current_mode)

# Загрузка критериев
async def ask_for_criteria(callback: CallbackQuery, state: FSMContext, current_mode: str):
    await state.update_data(current_mode=current_mode)
    await state.set_state(OrgStates.waiting_for_criteria)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_to_org_mode")]])
    await safe_edit(
        callback,
        f"📋 Загрузка критериев (режим {current_mode.replace('org_', '')})\n\n"
        f"Отправьте критерии одним из способов:\n\n"
        f"📝 Текст - просто напишите сообщение\n"
        f"📎 Файл - пришлите файл (.txt, .doc, .docx, .pdf, .xlsx)\n"
        f"🔗 Ссылка - отправьте ссылку на Google/Яндекс Диск\n\n"
        f"Бот сам определит формат отправленных данных",
        kb
    )

@dp.message(OrgStates.waiting_for_criteria, F.text)
@dp.message(OrgStates.waiting_for_criteria, F.document)
async def process_criteria_auto(message: Message, state: FSMContext):
    user_data = await state.get_data()
    current_mode = user_data.get('current_mode')
    criteria_data = {'type': None, 'content': None, 'timestamp': asyncio.get_event_loop().time()}
    if message.document:
        file_ext = message.document.file_name.split('.')[-1].lower() if '.' in message.document.file_name else ''
        allowed = ['txt', 'doc', 'docx', 'pdf', 'xlsx', 'xls', 'rtf']
        if file_ext not in allowed:
            await message.answer(f"❌ Неподдерживаемый формат.\nПоддерживаются: {', '.join(allowed)}")
            return
        criteria_data['type'] = 'file'
        criteria_data['content'] = {'file_name': message.document.file_name, 'file_id': message.document.file_id, 'file_size': message.document.file_size}
        await message.answer(f"✅ Критерии загружены (файл: {message.document.file_name})")
    elif message.text:
        text = message.text.strip()
        if text.startswith(("http://", "https://")):
            criteria_data['type'] = 'link'
            criteria_data['content'] = text
            await message.answer("✅ Критерии загружены (ссылка)")
        else:
            if len(text) < 10:
                await message.answer("❌ Слишком короткое сообщение. Напишите развернутые критерии (минимум 10 символов) или отправьте файл/ссылку.")
                return
            criteria_data['type'] = 'text'
            criteria_data['content'] = text
            await message.answer("✅ Критерии загружены (текст)")
    else:
        await message.answer("❌ Неподдерживаемый формат.")
        return
    if message.from_user.id not in org_data:
        org_data[message.from_user.id] = {}
    org_data[message.from_user.id]['criteria'] = criteria_data
    org_data[message.from_user.id]['mode'] = current_mode
    await preview_criteria_and_ask(message, state, current_mode)

async def preview_criteria_and_ask(message: Message, state: FSMContext, current_mode: str):
    criteria = org_data[message.from_user.id]['criteria']
    if criteria['type'] == 'text':
        preview = f"📝 Текст критериев:\n{criteria['content'][:500]}"
    elif criteria['type'] == 'file':
        preview = f"📎 Файл критериев: {criteria['content']['file_name']}\nРазмер: {criteria['content']['file_size']} байт"
    else:
        preview = f"🔗 Ссылка на критерии:\n{criteria['content']}"
    if current_mode == "org_2":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять и отправить", callback_data=f"accept_criteria_and_finish_{current_mode}")],
            [InlineKeyboardButton(text="🔄 Загрузить заново", callback_data=f"reload_criteria_{current_mode}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_org_mode")]
        ])
        await message.answer(f"📋 Предпросмотр критериев:\n\n{preview}\n\n✅ Всё верно? Нажмите 'Принять и отправить'.", reply_markup=kb)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять критерии", callback_data=f"accept_criteria_{current_mode}")],
            [InlineKeyboardButton(text="🔄 Загрузить заново", callback_data=f"reload_criteria_{current_mode}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_org_mode")]
        ])
        await message.answer(f"📋 Предпросмотр критериев:\n\n{preview}\n\n✅ Принять или загрузить заново?", reply_markup=kb)

@dp.callback_query(F.data.startswith("reload_criteria_"))
async def reload_criteria(callback: CallbackQuery, state: FSMContext):
    current_mode = callback.data.replace("reload_criteria_", "")
    await state.update_data(current_mode=current_mode)
    await state.set_state(OrgStates.waiting_for_criteria)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_org_mode")]])
    await safe_edit(callback, "🔄 Повторная загрузка критериев\n\nОтправьте критерии заново (текст, файл или ссылку):", kb)

@dp.callback_query(F.data.startswith("accept_criteria_") & ~F.data.startswith("accept_criteria_and_finish_"))
async def accept_criteria(callback: CallbackQuery, state: FSMContext):
    current_mode = callback.data.replace("accept_criteria_", "")
    if callback.from_user.id in org_data:
        org_data[callback.from_user.id]['criteria_accepted'] = True
    await ask_for_work_link(callback, state, current_mode)

@dp.callback_query(F.data.startswith("accept_criteria_and_finish_"))
async def accept_criteria_and_finish(callback: CallbackQuery, state: FSMContext):
    current_mode = callback.data.replace("accept_criteria_and_finish_", "")
    if callback.from_user.id in org_data:
        org_data[callback.from_user.id]['criteria_accepted'] = True
    await final_confirmation(callback, state, current_mode)

# Загрузка ссылок на работы
async def ask_for_work_link(callback: CallbackQuery, state: FSMContext, current_mode: str):
    await state.update_data(current_mode=current_mode)
    await state.set_state(OrgStates.waiting_for_link)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_org_mode")]])
    await safe_edit(
        callback,
        f"🔗 Отправка ссылки на работы\n\nРежим: {current_mode.replace('org_', '')}\n\n"
        f"Пожалуйста, отправьте ссылку на Google Диск или Яндекс Диск с работами:\n"
        f"(например: https://drive.google.com/...)\n\n💡 Можно отправить несколько ссылок через пробел или с новой строки",
        kb
    )

@dp.message(OrgStates.waiting_for_link, F.text)
async def process_work_link(message: Message, state: FSMContext):
    link_text = message.text.strip()
    links = re.findall(r'https?://[^\s]+', link_text)
    if not links:
        await message.answer("❌ Не найдено корректных ссылок. Отправьте ссылку(и), начинающиеся с http:// или https://")
        return
    user_data = await state.get_data()
    current_mode = user_data.get("current_mode")
    org_data[message.from_user.id]['links'] = links
    org_data[message.from_user.id]['link_text'] = link_text
    links_preview = "\n".join([f"{i+1}. {link}" for i, link in enumerate(links)])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять ссылки", callback_data=f"accept_links_{current_mode}")],
        [InlineKeyboardButton(text="🔄 Отправить заново", callback_data=f"ask_work_link_{current_mode}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_org_mode")]
    ])
    await message.answer(
        f"🔗 Предпросмотр ссылок:\n\n{links_preview}\n\n✅ Всего ссылок: {len(links)}\n\nПринять или отправить заново?",
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("accept_links_"))
async def accept_links(callback: CallbackQuery, state: FSMContext):
    current_mode = callback.data.replace("accept_links_", "")
    org_data[callback.from_user.id]['links_accepted'] = True
    await final_confirmation(callback, state, current_mode)

@dp.callback_query(F.data.startswith("ask_work_link_"))
async def ask_work_link_again(callback: CallbackQuery, state: FSMContext):
    current_mode = callback.data.replace("ask_work_link_", "")
    await ask_for_work_link(callback, state, current_mode)

async def final_confirmation(callback: CallbackQuery, state: FSMContext, current_mode: str):
    if callback.from_user.id not in org_data:
        await callback.answer("Данные не найдены!", show_alert=True)
        return
    data = org_data[callback.from_user.id]
    experts = data.get('experts', [])
    experts_text = "\n".join([f"• {exp['email']}" for exp in experts]) if experts else "Не выбраны"
    criteria_text = ""
    if 'criteria' in data and data.get('criteria_accepted', False):
        crit = data['criteria']
        if crit['type'] == 'text':
            criteria_text = f"\n📝 Критерии (текст):\n{crit['content'][:300]}"
        elif crit['type'] == 'file':
            criteria_text = f"\n📎 Файл критериев: {crit['content']['file_name']}"
        elif crit['type'] == 'link':
            criteria_text = f"\n🔗 Ссылка на критерии: {crit['content']}"
    else:
        criteria_text = "\n❌ Критерии не загружены"
    links = data.get('links', [])
    links_text = "\n".join([f"{i+1}. {link}" for i, link in enumerate(links)]) if links else "Не указаны"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Окончательно подтвердить", callback_data=f"final_confirm_{current_mode}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_org_mode")]
    ])
    await safe_edit(
        callback,
        f"📎 Финальная проверка перед отправкой\n\n"
        f"📁 Режим: {current_mode.replace('org_', '')}\n\n"
        f"👥 Эксперты:\n{experts_text}\n{criteria_text}\n\n"
        f"🔗 Ссылки на работы ({len(links)} шт.):\n{links_text}\n\n"
        f"✅ Всё верно? Нажмите 'Окончательно подтвердить'.",
        kb
    )

@dp.callback_query(F.data.startswith("final_confirm_"))
async def final_confirm(callback: CallbackQuery, state: FSMContext):
    current_mode = callback.data.replace("final_confirm_", "")
    if callback.from_user.id not in org_data:
        await callback.answer("Данные не найдены!", show_alert=True)
        return
    data = org_data[callback.from_user.id]
    mode_int = int(current_mode.replace("org_", ""))
    project_name = f"Проект от {registered_users[callback.from_user.id]['email']} {asyncio.get_event_loop().time()}"

    participant_ids = [1] if mode_int == 2 else []
    project = await db.create_project(ProjectCreate(
        name=project_name,
        mode=mode_int,
        creator_team_id=1,
        participant_team_ids=participant_ids
    ))
    del org_data[callback.from_user.id]
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад к режимам", callback_data="back_to_org_mode")]])
    await safe_edit(callback,
        f"✅ ВСЕ ДАННЫЕ УСПЕШНО ОТПРАВЛЕНЫ!\n\n"
        f"📎 Режим: {current_mode.replace('org_', '')}\n"
        f"📁 Проект создан с ID {project.id} (заглушка)\n\n"
        f"📨 Уведомления отправлены проверяющим.",
        kb)

# Режим 2 (только критерии)
@dp.callback_query(F.data.startswith("org_criteria_org_2"))
async def handle_criteria_mode2(callback: CallbackQuery, state: FSMContext):
    current_mode = "org_2"
    if callback.from_user.id not in org_data:
        org_data[callback.from_user.id] = {}
    org_data[callback.from_user.id]['mode'] = current_mode
    org_data[callback.from_user.id]['experts'] = []
    await state.update_data(current_mode=current_mode)
    await state.set_state(OrgStates.waiting_for_criteria)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_org_mode")]])
    await safe_edit(
        callback,
        f"📋 Загрузка критериев (режим 2)\n\n"
        f"Отправьте критерии одним из способов:\n\n"
        f"📝 Текст\n📎 Файл\n🔗 Ссылка\n\nБот сам определит формат",
        kb
    )

@dp.callback_query(F.data == "org_results")
async def results(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(callback, "📊 Результаты проверки\n\nЗдесь будут отображаться результаты проверки работ (заглушка)", None)

# Кнопка "Назад" для организатора (из любого inline-меню)
@dp.callback_query(F.data == "back_to_org_mode")
async def back_to_org_mode(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Выберите действие:", reply_markup=None)
    await callback.message.answer("Режим организатора. Выберите режим:", reply_markup=org_mode_kb())
    await callback.answer()

# ---------------------- Преподаватель (заглушка) ----------------------
async def teacher_panel(message: Message):
    await message.answer(
        "👩‍🏫 Роль: Преподаватель (эксперт)\n\n"
        "Это тестовый режим. Вы можете выставить оценку и комментарий (без привязки к реальной работе).",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📝 Выставить оценку и комментарий")], [KeyboardButton(text="🔙 Назад")]],
            resize_keyboard=True
        )
    )

@dp.message(F.text == "📝 Выставить оценку и комментарий")
async def teacher_start_review(message: Message, state: FSMContext):
    await state.set_state(TeacherReview.waiting_for_score)
    await message.answer("Введите оценку (0-100):", reply_markup=cancel_reply_kb())

@dp.message(TeacherReview.waiting_for_score, F.text)
async def teacher_score(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu_kb())
        return
    try:
        score = int(message.text.strip())
        if not (0 <= score <= 100):
            raise ValueError
    except ValueError:
        await message.answer("Оценка должна быть целым числом 0-100.")
        return
    await state.update_data(score=score)
    await state.set_state(TeacherReview.waiting_for_comment)
    await message.answer("Введите комментарий:")

@dp.message(TeacherReview.waiting_for_comment, F.text)
async def teacher_comment(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu_kb())
        return
    comment = message.text.strip()
    await state.update_data(comment=comment)
    data = await state.get_data()
    await state.set_state(TeacherReview.confirm_review)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_teacher_review")],
        [InlineKeyboardButton(text="✏️ Редактировать оценку", callback_data="edit_teacher_score")],
        [InlineKeyboardButton(text="✏️ Редактировать комментарий", callback_data="edit_teacher_comment")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_teacher_review")]
    ])
    await message.answer(f"Проверьте данные:\nОценка: {data['score']}\nКомментарий: {comment}\n\nВсё верно?", reply_markup=kb)

@dp.callback_query(F.data == "edit_teacher_score")
async def edit_teacher_score(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TeacherReview.waiting_for_score)
    await callback.message.answer("Введите новую оценку:")
    await callback.answer()

@dp.callback_query(F.data == "edit_teacher_comment")
async def edit_teacher_comment(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TeacherReview.waiting_for_comment)
    await callback.message.answer("Введите новый комментарий:")
    await callback.answer()

@dp.callback_query(F.data == "cancel_teacher_review")
async def cancel_teacher_review(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Отменено.", reply_markup=main_menu_kb())
    await callback.answer()

@dp.callback_query(F.data == "confirm_teacher_review")
async def confirm_teacher_review(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    score = data['score']
    comment = data['comment']
    await state.clear()
    await callback.message.answer(
        f"✅ Оценка и комментарий отправлены!\n\nОценка: {score}\nКомментарий: {comment}\n(заглушка, реальная работа не привязана)",
        reply_markup=main_menu_kb()
    )
    await callback.answer()

# ---------------------- Студент ----------------------
@dp.message(F.text == "1️⃣ Режим 1")
async def student_mode1(message: Message):
    await message.answer(
        "📊 Результаты проверки (заглушка)\n\nВаша работа: 'Аналитика'\nСтатус: проверена\nОценка: 85/100\nКомментарий: Хорошая работа, но есть замечания по оформлению."
    )

@dp.message(F.text == "2️⃣ Режим 2")
async def student_mode2(message: Message):
    await message.answer("Режим 2: выберите действие", reply_markup=student_mode2_kb())

@dp.message(F.text == "3️⃣ Режим 3")
async def student_mode3(message: Message):
    await message.answer(
        "🏆 Рейтинг студентов (заглушка)\n\n1. Dodo Ptizza – 95 баллов\n2. Dodo Bonya – 88 баллов\n3. ООО Тчисление – 76 баллов\n\n📊 Ваша позиция: 2 место"
    )

@dp.message(F.text == "📊 Статус работы")
async def student_own_status(message: Message):
    await message.answer(
        "📊 Статус вашей работы (заглушка)\n\nПроект: 'Аналитика'\nСтатус: На проверке\nОценка: не оценено\nКомментарии: нет"
    )

@dp.message(F.text == "👥 Чужие работы")
async def student_others_works(message: Message, state: FSMContext):
    await state.set_state(PeerReview.waiting_for_score)
    await message.answer(
        "Вы выбрали просмотр чужих работ (заглушка).\nВведите оценку (0-100) для работы студента:",
        reply_markup=cancel_reply_kb()
    )

@dp.message(PeerReview.waiting_for_score, F.text)
async def peer_score(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=student_mode2_kb())
        return
    try:
        score = int(message.text.strip())
        if not (0 <= score <= 100):
            raise ValueError
    except ValueError:
        await message.answer("Оценка должна быть целым числом 0-100.")
        return
    await state.update_data(peer_score=score)
    await state.set_state(PeerReview.waiting_for_comment)
    await message.answer("Введите комментарий:")

@dp.message(PeerReview.waiting_for_comment, F.text)
async def peer_comment(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=student_mode2_kb())
        return
    comment = message.text.strip()
    await state.update_data(peer_comment=comment)
    data = await state.get_data()
    await state.set_state(PeerReview.confirm_review)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить", callback_data="confirm_peer_review")],
        [InlineKeyboardButton(text="✏️ Изменить оценку", callback_data="edit_peer_score")],
        [InlineKeyboardButton(text="✏️ Изменить комментарий", callback_data="edit_peer_comment")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_peer_review")]
    ])
    await message.answer(f"Проверьте:\nОценка: {data['peer_score']}\nКомментарий: {comment}\n\nОтправить?", reply_markup=kb)

@dp.callback_query(F.data == "edit_peer_score")
async def edit_peer_score(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PeerReview.waiting_for_score)
    await callback.message.answer("Введите новую оценку:")
    await callback.answer()

@dp.callback_query(F.data == "edit_peer_comment")
async def edit_peer_comment(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PeerReview.waiting_for_comment)
    await callback.message.answer("Введите новый комментарий:")
    await callback.answer()

@dp.callback_query(F.data == "cancel_peer_review")
async def cancel_peer_review(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Отменено.", reply_markup=student_mode2_kb())
    await callback.answer()

@dp.callback_query(F.data == "confirm_peer_review")
async def confirm_peer_review(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    score = data['peer_score']
    comment = data['peer_comment']
    await state.clear()
    await callback.message.answer(
        f"✅ Оценка отправлена!\n\nОценка: {score}\nКомментарий: {comment}\n(заглушка, реальная работа не привязана)",
        reply_markup=student_mode2_kb()
    )
    await callback.answer()

@dp.message(F.text == "📤 Отправить работу")
async def student_submit_work(message: Message, state: FSMContext):
    await state.set_state(StudentSubmission.waiting_for_link)
    await message.answer(
        "Отправьте ссылку(и) на Google/Яндекс Диск с вашей работой.\nМожно несколько ссылок через пробел или с новой строки.",
        reply_markup=cancel_reply_kb()
    )

@dp.message(StudentSubmission.waiting_for_link, F.text)
async def process_student_links(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=student_mode2_kb())
        return
    links = re.findall(r'https?://[^\s]+', message.text)
    if not links:
        await message.answer("Не найдено ссылок. Попробуйте снова.")
        return
    await state.update_data(links=links)
    preview = "\n".join([f"{i+1}. {link}" for i, link in enumerate(links)])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_student_submit")],
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit_student_submit")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_student_submit")]
    ])
    await message.answer(f"Предпросмотр ссылок:\n{preview}\n\nВсё верно?", reply_markup=kb)
    await state.set_state(StudentSubmission.confirm_submission)

@dp.callback_query(F.data == "edit_student_submit")
async def edit_student_submit(callback: CallbackQuery, state: FSMContext):
    await state.set_state(StudentSubmission.waiting_for_link)
    await callback.message.answer("Отправьте ссылки заново:")
    await callback.answer()

@dp.callback_query(F.data == "cancel_student_submit")
async def cancel_student_submit(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Отменено.", reply_markup=student_mode2_kb())
    await callback.answer()

@dp.callback_query(F.data == "confirm_student_submit")
async def confirm_student_submit(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    links = data['links']
    user_id = callback.from_user.id
    db_user = await db.get_user(registered_users[user_id]['db_id'])
    project = await db.create_project(ProjectCreate(
        name=f"Работа {db_user.email}",
        mode=1,
        creator_team_id=db_user.team_id,
        participant_team_ids=[]
    ))
    for link in links:
        await db.add_artifact(project.id, ArtifactCreate(url=link, type="link"))
    await state.clear()
    await callback.message.answer("✅ Работа отправлена на проверку!", reply_markup=student_mode2_kb())
    await callback.answer()

# ---------------------- Запуск ----------------------
async def main():
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())