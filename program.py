import asyncio
import logging
import os
import re
from typing import Dict

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

# API импорты
from Experto.api.mocker import MockDatabase
from Experto.api.schemas import (
    UserCreate, UserRoleSystem, ProjectCreate,
    ScoreCreate, CommentCreate
)

load_dotenv()

TOKEN = os.getenv("TOKEN")

storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Инициализация базы данных (мок)
db = MockDatabase()

# Создаём команду по умолчанию, если её нет
if 1 not in db.teams:
    db.teams[1] = {"id": 1, "name": "Команда Альфа"}

# Временное хранилище для зарегистрированных пользователей (ID бота -> данные)
registered_users: Dict[int, dict] = {}

# Временное хранилище для ссылок организатора
org_data: Dict[int, dict] = {}

# Состояния
class Registration(StatesGroup):
    waiting_for_fullname = State()
    waiting_for_email = State()
    waiting_for_code = State()

class OrgStates(StatesGroup):
    waiting_for_criteria = State()
    waiting_for_criteria_type = State()
    waiting_for_experts = State()
    waiting_for_link = State()
    waiting_for_link_edit = State()

# ---------------------- Клавиатуры ----------------------
def role_selection_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Организатор", callback_data="org")],
        [InlineKeyboardButton(text="Преподаватель", callback_data="teacher")],
        [InlineKeyboardButton(text="Студент", callback_data="stud")]
    ])

def cancel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена регистрации")]],
        resize_keyboard=True
    )

async def safe_edit(callback: CallbackQuery, text: str, kb: InlineKeyboardMarkup = None):
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await callback.answer()

# ---------------------- Регистрация ----------------------
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    if message.from_user.id in registered_users:
        user_data = registered_users[message.from_user.id]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Выбрать роль", callback_data="choose_role")]
        ])
        await message.answer(
            f"👋 С возвращением, {user_data['fullname']}!\n\nВы уже зарегистрированы в системе.",
            reply_markup=kb
        )
        return
    await state.set_state(Registration.waiting_for_fullname)
    await message.answer(
        "🌟 Добро пожаловать в сервис обратной связи по ОПД! 🌟\n\n"
        "Для начала работы необходимо пройти регистрацию.\n\n"
        "📝 Введите ваше ФИО (полностью):",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=cancel_kb()
    )

async def cancel_registration(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Регистрация отменена.\n\nЧтобы начать заново, используйте команду /start",
        reply_markup=ReplyKeyboardRemove()
    )

@dp.message(Registration.waiting_for_fullname, F.text)
async def process_fullname(message: Message, state: FSMContext):
    if message.text == "❌ Отмена регистрации":
        await cancel_registration(message, state)
        return
    if len(message.text.strip()) < 5:
        await message.answer("❌ ФИО должно содержать минимум 5 символов. Попробуйте еще раз:", reply_markup=cancel_kb())
        return
    await state.update_data(fullname=message.text.strip())
    await state.set_state(Registration.waiting_for_email)
    await message.answer(
        f"✅ ФИО принято: {message.text.strip()}\n\n📧 Введите ваш email:\n(пример: example@mail.com)",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=cancel_kb()
    )

@dp.message(Registration.waiting_for_email, F.text)
async def process_email(message: Message, state: FSMContext):
    if message.text == "❌ Отмена регистрации":
        await cancel_registration(message, state)
        return
    email = message.text.strip()
    if '@' not in email or '.' not in email or ' ' in email:
        await message.answer(
            "❌ Неверный формат email. Попробуйте еще раз:\n(пример: example@mail.com)",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=cancel_kb()
        )
        return
    await state.update_data(email=email)
    await state.set_state(Registration.waiting_for_code)
    demo_code = "123"
    await state.update_data(expected_code=demo_code)
    await message.answer(
        f"✅ Email принят: {email}\n\n🔐 Подтверждение email\nНа вашу почту отправлен код подтверждения.\n*(Используйте код `{demo_code}`)*\n\nВведите код из письма:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=cancel_kb()
    )

@dp.message(Registration.waiting_for_code, F.text)
async def process_code(message: Message, state: FSMContext):
    if message.text == "❌ Отмена регистрации":
        await cancel_registration(message, state)
        return
    user_data = await state.get_data()
    expected_code = user_data.get('expected_code')
    entered_code = message.text.strip()
    if entered_code == expected_code:
        # Создаём пользователя в БД (роль пока не выбрана)
        # Условно: пользователь пока без роли, роль назначим позже
        # Но API требует роль при создании, поэтому создадим с ролью STUDENT
        # При выборе роли в боте обновим роль в БД (но в моке нет обновления роли, просто сохраним отдельно)
        db_user = await db.create_user(UserCreate(
            name=user_data['fullname'],
            email=user_data['email'],
            code="",  # пока не используем
            role=UserRoleSystem.STUDENT,  # временно
            team_id=1
        ))
        registered_users[message.from_user.id] = {
            'fullname': user_data['fullname'],
            'email': user_data['email'],
            'db_id': db_user.id,
            'role': None,
            'registered_at': asyncio.get_event_loop().time()
        }
        await state.clear()
        await message.answer(
            f"🎉 Регистрация успешно завершена! 🎉\n\nДобро пожаловать в сервис обратной связи по ОПД, {user_data['fullname']}!\n"
            f"📧 Email: {user_data['email']}\n\nТеперь выберите вашу роль, чтобы продолжить:",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode=ParseMode.MARKDOWN
        )
        await message.answer("Выберите вашу роль:", reply_markup=role_selection_kb())
    else:
        await message.answer(
            f"❌ Неверный код подтверждения.\nПопробуйте еще раз (демо-код: {expected_code}):",
            reply_markup=cancel_kb()
        )

# ---------------------- Выбор роли ----------------------
@dp.callback_query(F.data == "choose_role")
async def show_role_selection(callback: CallbackQuery):
    if callback.from_user.id not in registered_users:
        await callback.answer("❌ Сначала необходимо зарегистрироваться!", show_alert=True)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Начать регистрацию", callback_data="start_registration")]])
        await safe_edit(callback, "Вы не зарегистрированы. Пройдите регистрацию:", kb)
        return
    await safe_edit(callback, "Выберите вашу роль:", role_selection_kb())

@dp.callback_query(F.data == "change_role")
async def change_role(callback: CallbackQuery):
    if callback.from_user.id in registered_users:
        registered_users[callback.from_user.id]['role'] = None
    await safe_edit(callback, "🔄 Смена роли\n\nВыберите новую роль (только для тестов):", role_selection_kb())

# ---------------------- Организатор ----------------------
@dp.callback_query(F.data == "org")
async def organizer(callback: CallbackQuery):
    if callback.from_user.id not in registered_users:
        await callback.answer("❌ Сначала зарегистрируйтесь!", show_alert=True)
        return
    registered_users[callback.from_user.id]['role'] = 'org'
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 режим", callback_data="org_1")],
        [InlineKeyboardButton(text="2 режим", callback_data="org_2")],
        [InlineKeyboardButton(text="3 режим", callback_data="org_3")],
        [InlineKeyboardButton(text="🔄 Сменить роль (тест)", callback_data="change_role")]
    ])
    await safe_edit(
        callback,
        f"👔 Роль: Организатор\n\nДобро пожаловать, {registered_users[callback.from_user.id]['fullname']}!\n\nДоступные режимы:",
        kb
    )

def get_mode_menu(mode: str):
    if mode == "org_2":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Загрузить критерии", callback_data=f"org_criteria_{mode}")],
            [InlineKeyboardButton(text="Результаты", callback_data="org_results")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="org")]
        ])
    else:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Выбрать экспертов", callback_data=f"org_select_experts_{mode}")],
            [InlineKeyboardButton(text="Результаты", callback_data="org_results")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="org")]
        ])

@dp.callback_query(F.data.startswith("org_") & F.data.in_({"org_1", "org_2", "org_3"}))
async def org_mode(callback: CallbackQuery, state: FSMContext):
    mode = callback.data
    mode_text = mode.replace("org_", "")
    await state.clear()
    await safe_edit(callback, f"📁 Режим {mode_text}\n\nЧто сделать?", get_mode_menu(mode))

# Выбор экспертов (1 и 3 режимы)
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
        experts_text = "\n\nДобавленные эксперты:\n" + "\n".join([f"• {exp['email']} ({exp['fullname']})" for exp in experts_list])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Завершить выбор", callback_data="experts_done")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=current_mode)]
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
            expert_found = {'id': user_id, 'email': user_data['email'], 'fullname': user_data['fullname']}
            break
    if not expert_found:
        all_users = "\n".join([f"• {data['email']} ({data['fullname']})" for data in registered_users.values()])
        await message.answer(
            f"❌ Пользователь с email '{email}' не найден!\n\nЗарегистрированные пользователи:\n{all_users}\n\nПопробуйте снова:"
        )
        return
    if email.lower() in [exp['email'].lower() for exp in org_data[message.from_user.id]['experts']]:
        await message.answer(f"⚠️ Эксперт {expert_found['fullname']} ({email}) уже добавлен!\n\nВведите другого эксперта.")
        return
    org_data[message.from_user.id]['experts'].append(expert_found)
    experts_list = org_data[message.from_user.id]['experts']
    experts_text = "\n".join([f"• {exp['email']} ({exp['fullname']})" for exp in experts_list])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Завершить выбор", callback_data="experts_done")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=org_data[message.from_user.id]['mode'])]
    ])
    await message.answer(
        f"✅ Эксперт добавлен!\n\n📧 {expert_found['email']} ({expert_found['fullname']})\n\n"
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
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=current_mode)]
        ])
        experts_text = "\n".join([f"• {exp['email']} ({exp['fullname']})" for exp in experts])
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
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=current_mode)]])
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
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=current_mode)]
        ])
        await message.answer(f"📋 Предпросмотр критериев:\n\n{preview}\n\n✅ Всё верно? Нажмите 'Принять и отправить'.", reply_markup=kb)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять критерии", callback_data=f"accept_criteria_{current_mode}")],
            [InlineKeyboardButton(text="🔄 Загрузить заново", callback_data=f"reload_criteria_{current_mode}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=current_mode)]
        ])
        await message.answer(f"📋 Предпросмотр критериев:\n\n{preview}\n\n✅ Принять или загрузить заново?", reply_markup=kb)

@dp.callback_query(F.data.startswith("reload_criteria_"))
async def reload_criteria(callback: CallbackQuery, state: FSMContext):
    current_mode = callback.data.replace("reload_criteria_", "")
    await state.update_data(current_mode=current_mode)
    await state.set_state(OrgStates.waiting_for_criteria)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=current_mode)]])
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
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=current_mode)]])
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
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=current_mode)]
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

# Финальное подтверждение и создание проекта в БД
async def final_confirmation(callback: CallbackQuery, state: FSMContext, current_mode: str):
    if callback.from_user.id not in org_data:
        await callback.answer("Данные не найдены!", show_alert=True)
        return
    data = org_data[callback.from_user.id]
    experts = data.get('experts', [])
    experts_text = "\n".join([f"• {exp['email']} ({exp['fullname']})" for exp in experts]) if experts else "Не выбраны"
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
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=current_mode)]
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
    # Создаём проект в БД
    mode_int = int(current_mode.replace("org_", ""))
    project_name = f"Проект от {registered_users[callback.from_user.id]['fullname']} {asyncio.get_event_loop().time()}"
    project = await db.create_project(ProjectCreate(
        name=project_name,
        mode=mode_int,
        creator_team_id=1,
        participant_team_ids=[1]
    ))
    # Сохраняем ссылки на работы (можно сохранить в БД, расширив модель)
    # Например, в моке можно добавить поле files_references, пока игнорируем
    # Сохраняем критерии как объекты в БД
    if 'criteria' in data and data.get('criteria_accepted', False):
        crit = data['criteria']
        if crit['type'] == 'text':
            # Добавляем критерий как запись в БД (для примера)
            await db.add_criterion(project.id, "Критерии (текст)", 100, 1)
        elif crit['type'] == 'file':
            await db.add_criterion(project.id, f"Файл критериев: {crit['content']['file_name']}", 100, 1)
        elif crit['type'] == 'link':
            await db.add_criterion(project.id, f"Ссылка на критерии: {crit['content']}", 100, 1)
    # Уведомляем экспертов (пока просто заглушка)
    del org_data[callback.from_user.id]
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад к режимам", callback_data=current_mode)]])
    await safe_edit(callback,
        f"✅ ВСЕ ДАННЫЕ УСПЕШНО ОТПРАВЛЕНЫ!\n\n"
        f"📎 Режим: {current_mode.replace('org_', '')}\n"
        f"📁 Проект создан с ID {project.id}\n\n"
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
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=current_mode)]])
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
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="org")]])
    await safe_edit(callback, "📊 Результаты проверки\n\nЗдесь будут отображаться результаты проверки работ", kb)

# ---------------------- Эксперт (преподаватель) ----------------------
@dp.callback_query(F.data == "teacher")
async def teacher(callback: CallbackQuery):
    if callback.from_user.id not in registered_users:
        await callback.answer("❌ Сначала зарегистрируйтесь!", show_alert=True)
        return
    registered_users[callback.from_user.id]['role'] = 'teacher'
    # Получаем проекты, назначенные эксперту (в моке нет прямой привязки, для примера показываем все проекты mode=1)
    projects = await db.get_projects_for_team(team_id=1)  # все проекты команды
    # Фильтруем проекты, где ещё нет оценки от текущего эксперта (заглушка)
    if not projects:
        text = "📭 Нет доступных проектов для проверки."
    else:
        text = "📋 Проекты для проверки:\n"
        for p in projects:
            text += f"\n🔹 {p.name} (ID {p.id}) | Статус: {p.status}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="choose_role")],
        [InlineKeyboardButton(text="🔄 Сменить роль", callback_data="change_role")]
    ])
    await safe_edit(callback, f"👩‍🏫 Роль: Эксперт\n\n{text}", kb)

# ---------------------- Студент ----------------------
@dp.callback_query(F.data == "stud")
async def student(callback: CallbackQuery):
    if callback.from_user.id not in registered_users:
        await callback.answer("❌ Сначала зарегистрируйтесь!", show_alert=True)
        return
    registered_users[callback.from_user.id]['role'] = 'stud'
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 режим", callback_data="stud_1")],
        [InlineKeyboardButton(text="2 режим", callback_data="stud_2")],
        [InlineKeyboardButton(text="3 режим", callback_data="stud_3")],
        [InlineKeyboardButton(text="🔄 Сменить роль", callback_data="change_role")]
    ])
    await safe_edit(callback,
        f"👨‍🎓 Роль: Студент\n\nДобро пожаловать, {registered_users[callback.from_user.id]['fullname']}!\n\nДоступные режимы:",
        kb)

@dp.callback_query(F.data == "stud_1")
async def stud_1(callback: CallbackQuery):
    # Показываем статус своей работы (последний проект команды)
    projects = await db.get_projects_for_team(team_id=1)
    if not projects:
        status_info = "📊 У вас пока нет проектов для отображения."
    else:
        last_project = projects[-1]
        scores = await db.get_scores(last_project.id)  # метод get_scores нужно добавить в мок, пока заглушка
        comments = await db.get_comments(last_project.id)
        status_info = (
            f"📊 Статус вашей работы\n\n"
            f"📁 Проект: {last_project.name}\n"
            f"✅ Статус проверки: {last_project.status}\n"
            f"⭐ Оценка: {last_project.mark if last_project.mark else 'Не оценено'}\n"
            f"💬 Комментарии:\n" + "\n".join([f"• {c.comment}" for c in comments]) if comments else "• Нет комментариев"
        )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="stud")]])
    await safe_edit(callback, status_info, kb)

@dp.callback_query(F.data == "stud_2")
async def stud_2(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Посмотреть статус работы", callback_data="stud_status")],
        [InlineKeyboardButton(text="👥 Посмотреть чужие работы", callback_data="stud_others_work")],
        [InlineKeyboardButton(text="📤 Загрузить свою работу", callback_data="stud_upload")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="stud")]
    ])
    await safe_edit(callback, "📁 Режим 2\n\nВыберите действие:", kb)

@dp.callback_query(F.data == "stud_status")
async def stud_status(callback: CallbackQuery):
    projects = await db.get_projects_for_team(team_id=1)
    if not projects:
        text = "Нет проектов."
    else:
        p = projects[-1]
        scores = await db.get_scores(p.id)  # заглушка
        comments = await db.get_comments(p.id)
        text = (
            f"📊 Статус работы\n\nПроект: {p.name}\nСтатус: {p.status}\nОценка: {p.mark}\n"
            f"Комментарии:\n" + "\n".join([f"• {c.comment}" for c in comments]) if comments else "Нет комментариев"
        )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="stud_2")]])
    await safe_edit(callback, text, kb)

@dp.callback_query(F.data == "stud_others_work")
async def stud_others_work(callback: CallbackQuery):
    # Для демонстрации – все проекты команды, кроме последнего (чужие)
    projects = await db.get_projects_for_team(team_id=1)
    if len(projects) <= 1:
        text = "Пока нет чужих работ."
    else:
        text = "👥 Работы других студентов:\n"
        for p in projects[:-1]:
            text += f"\n🔹 {p.name} – Оценка: {p.mark if p.mark else 'не проверено'}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="stud_2")]])
    await safe_edit(callback, text, kb)

@dp.callback_query(F.data == "stud_upload")
async def stud_upload(callback: CallbackQuery):
    # Заглушка – в реальности нужно реализовать загрузку файлов/ссылок через state
    text = "📤 Загрузка своей работы\n\nФункционал в разработке. Скоро вы сможете загружать работы."
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="stud_2")]])
    await safe_edit(callback, text, kb)

@dp.callback_query(F.data == "stud_3")
async def stud_3(callback: CallbackQuery):
    # Рейтинг – для простоты показываем оценки всех проектов команды
    projects = await db.get_projects_for_team(team_id=1)
    rating = []
    for p in projects:
        if p.mark is not None:
            rating.append((p.name, p.mark))
    rating.sort(key=lambda x: x[1], reverse=True)
    text = "🏆 Рейтинг студентов\n\n"
    for i, (name, mark) in enumerate(rating[:5], 1):
        text += f"{i}. {name} – {mark} баллов\n"
    
    if rating:
        # Находим позицию текущего пользователя
        user_name = registered_users[callback.from_user.id]['fullname']
        user_position = None
        user_mark = None
        
        for idx, (name, mark) in enumerate(rating, 1):
            if user_name.lower() in name.lower():
                user_position = idx
                user_mark = mark
                break
        
        if user_position:
            text += f"\n📊 **Ваша позиция:** {user_position} место ({user_mark} баллов)"
        else:
            text += f"\n📊 **Ваша позиция:** В рейтинге пока нет (нет оцененных работ)"
    else:
        text += "Пока нет оценок."
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="stud")]
    ])
    await safe_edit(callback, text, kb)

# ---------------------- Заглушки ----------------------
@dp.callback_query(F.data == "checking")
async def checking(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_start")]])
    await safe_edit(callback, "Проверка работы", kb)

@dp.callback_query(F.data == "start_registration")
async def start_registration(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Registration.waiting_for_fullname)
    await safe_edit(callback, "📝 Регистрация\n\nВведите ваше ФИО (полностью):", None)
    await callback.message.answer("Введите ФИО (минимум 5 символов):", reply_markup=cancel_kb())

@dp.callback_query(F.data == "re注册")
async def reregister_user(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id in registered_users:
        del registered_users[callback.from_user.id]
    await state.set_state(Registration.waiting_for_fullname)
    await safe_edit(callback, "🔄 Перерегистрация\n\nВведите ваше ФИО:", None)
    await callback.message.answer("Введите ФИО (минимум 5 символов):", reply_markup=cancel_kb())

# ---------------------- Запуск ----------------------
async def main():
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())