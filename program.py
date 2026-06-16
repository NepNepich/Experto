import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict


from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)
from dotenv import load_dotenv

from api.models import User, SubmissionAssignment
from api.schemas import AcademicRole
from handlers.expert_voice import voice_router
from handlers.peer_voice import peer_voice_router
from database import AsyncSessionLocal
from services.auth import (
    find_user_by_email,
    bind_telegram_account,
    get_user_by_telegram,
    register_new_user
)
from services.expert import (
    get_expert_by_telegram,
    get_expert_active_projects,
    get_next_task_for_expert,
    get_project_criteria,
    submit_criterion_score,
    submit_expert_comment,
    finalize_expert_review,
    get_expert_stats, get_existing_score
)
from services.org import (
    create_project_with_criteria,
    assign_experts_to_project,
    get_organizer_projects,
    get_project_dashboard,
    export_project_results,
    get_all_experts,
    get_all_teams,
    org_bulk_submit_works
)
from services.peer import (
    submit_peer_work, get_peer_review_queue, take_peer_task,
    get_my_peer_tasks, submit_peer_score
)

from services.student import (
    submit_work,
    get_active_projects_for_team,
    get_student_submissions_with_feedback,
    get_active_projects_for_student,
    get_student_by_telegram,
    finalize_student_peer_review, 
    submit_peer_comment
)

load_dotenv()

TOKEN = os.getenv("TOKEN")
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
dp.include_router(voice_router)
dp.include_router(peer_voice_router)
registered_users: Dict[int, dict] = {}
org_data: Dict[int, dict] = {}


# ==================== СОСТОЯНИЯ ====================
class Registration(StatesGroup):
    waiting_for_email = State()
    waiting_for_code = State()
    waiting_for_name = State()


class OrgProjectCreate(StatesGroup):
    waiting_for_name = State()
    waiting_for_mode = State()
    waiting_for_type = State()
    waiting_for_teams = State()
    waiting_for_deadline = State()
    waiting_for_criteria = State()
    confirming_creation = State()


class OrgUploadWorks(StatesGroup):
    selecting_project = State()
    waiting_for_works = State()


class OrgAssignExperts(StatesGroup):
    selecting_project = State()
    selecting_experts = State()
    confirming_assignment = State()


class PeerReview(StatesGroup):
    selecting_project = State()
    viewing_task = State()
    scoring_criterion = State()
    writing_comment = State()


class TeacherReview(StatesGroup):
    waiting_for_score = State()
    waiting_for_comment = State()


class ExpertReview(StatesGroup):
    selecting_project = State()
    viewing_submission = State()
    scoring_criterion = State()
    writing_comment = State()
    confirming_voice = State() 
    confirming_review = State()


class StudentSubmission(StatesGroup):
    waiting_for_link = State()
    confirm_submission = State()


def get_role_value(role) -> str:
    if isinstance(role, str):
        return role
    return role.value if hasattr(role, 'value') else str(role)


# ==================== КЛАВИАТУРЫ ====================
def org_mode_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📦 Мои проекты")],
        [KeyboardButton(text="📥 Загрузить работы")]
    ], resize_keyboard=True)


def student_mode_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="1️⃣ Режим 1")],
        [KeyboardButton(text="2️⃣ Режим 2")]
    ], resize_keyboard=True)


def student_mode2_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Статус работы")],
        [KeyboardButton(text="👥 Чужие работы")],
        [KeyboardButton(text="📤 Отправить работу")]
    ], resize_keyboard=True)


def cancel_reply_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)


async def safe_edit(callback: CallbackQuery, text: str, kb: InlineKeyboardMarkup = None):
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await callback.answer()


async def show_main_menu(message: Message, role: AcademicRole):
    """Показывает меню в зависимости от роли"""
    user_data = registered_users.get(message.from_user.id, {})

    if role == AcademicRole.ORG:
        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="📦 Мои проекты")],
            [KeyboardButton(text="📥 Загрузить работы")]
        ], resize_keyboard=True)
        await message.answer("👔 Панель организатора", reply_markup=kb)
    elif role == AcademicRole.EXPERT:
        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="📋 Взять работу")],
            [KeyboardButton(text="📊 Статистика")]
        ], resize_keyboard=True)
        await message.answer("👩‍🏫 Панель эксперта", reply_markup=kb)
    elif role == AcademicRole.STUDENT:
        await message.answer("👨‍🎓 Панель студента", reply_markup=student_mode_kb())
    else:
        await message.answer("Выберите роль:", reply_markup=main_menu_kb())


# ==================== АВТОРИЗАЦИЯ ====================
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    user = await get_user_by_telegram(tg_id)

    if user:
        registered_users[tg_id] = {
            'email': user.email,
            'db_id': user.id,
            'role': get_role_value(user.academic_role),
            'name': user.name
        }
        await show_main_menu(message, user.academic_role)
        return

    await state.set_state(Registration.waiting_for_email)
    await message.answer("🌟 Добро пожаловать!\nВведите email:", reply_markup=cancel_reply_kb())


@dp.message(Registration.waiting_for_email, F.text)
async def process_email(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=ReplyKeyboardRemove())
        return

    email = message.text.strip()
    if '@' not in email or '.' not in email:
        await message.answer("❌ Неверный email.", reply_markup=cancel_reply_kb())
        return

    existing = await find_user_by_email(email)

    if existing:
        await state.update_data(email=email, user_id=existing.id, is_new=False)
        await state.set_state(Registration.waiting_for_code)
        await message.answer(f"✅ Email найден.\nКод (демо): `123`", parse_mode=ParseMode.MARKDOWN,
                             reply_markup=cancel_reply_kb())
    else:
        await state.update_data(email=email, is_new=True)
        await state.set_state(Registration.waiting_for_name)
        await message.answer("🆕 Email не найден. Введите имя для регистрации:", reply_markup=cancel_reply_kb())


@dp.message(Registration.waiting_for_name, F.text)
async def process_name(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=ReplyKeyboardRemove())
        return

    name = message.text.strip()
    if len(name) < 2:
        await message.answer("❌ Имя слишком короткое.")
        return

    data = await state.get_data()
    success, result = await register_new_user(
        email=data['email'], name=name,
        telegram_id=message.from_user.id,
        telegram_username=message.from_user.username
    )

    if not success:
        await message.answer(f"❌ {result}", reply_markup=ReplyKeyboardRemove())
        await state.clear()
        return

    assert isinstance(result, User)
    new_user = result
    registered_users[message.from_user.id] = {
        'email': new_user.email, 'db_id': new_user.id,
        'role': get_role_value(new_user.academic_role), 'name': new_user.name, 'code': new_user.code
    }

    await state.clear()
    await message.answer(f"🎉 Регистрация завершена!\n🔑 Ваш код: `{new_user.code}`", parse_mode=ParseMode.MARKDOWN)
    await show_main_menu(message, new_user.academic_role)


@dp.message(Registration.waiting_for_code, F.text)
async def process_code(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=ReplyKeyboardRemove())
        return

    data = await state.get_data()
    if message.text.strip() != data.get('expected_code', '123'):
        await message.answer("❌ Неверный код.", reply_markup=cancel_reply_kb())
        return

    success = await bind_telegram_account(
        user_id=data['user_id'],
        telegram_id=message.from_user.id,
        telegram_username=message.from_user.username
    )

    if not success:
        await message.answer("❌ Не удалось привязать аккаунт.", reply_markup=ReplyKeyboardRemove())
        await state.clear()
        return

    user = await get_user_by_telegram(message.from_user.id)
    registered_users[message.from_user.id] = {
        'email': user.email,
        'db_id': user.id,
        'role': get_role_value(user.academic_role),
        'name': user.name
    }

    await state.clear()
    await message.answer(f"🎉 Привет, {user.name}!", reply_markup=ReplyKeyboardRemove())
    await show_main_menu(message, user.academic_role)


# ==================== МЕНЮ И РОУТИНГ ====================
@dp.message(F.text == "🔙 Назад")
async def back_to_main(message: Message):
    user_id = message.from_user.id
    if user_id not in registered_users:
        await message.answer("")
        return
    role = registered_users[user_id].get('role')
    if role == 'org':
        await message.answer("Выберите режим:", reply_markup=org_mode_kb())
    elif role == 'student':
        await message.answer("Выберите режим:", reply_markup=student_mode_kb())



@dp.message(F.text.in_(["1️⃣ Режим 1", "2️⃣ Режим 2"]))
async def mode_router(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in registered_users:
        await message.answer("Сначала зарегистрируйтесь: /start")
        return

    role = registered_users[user_id].get('role')

    if role == 'org':
        await org_mode_router(message, state)
    elif role == 'student':
        await student_mode_router(message)
    elif role == 'expert':
        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="📋 Взять работу")],
            [KeyboardButton(text="📊 Статистика")]
        ], resize_keyboard=True)
        await message.answer("👩‍🏫 Панель эксперта", reply_markup=kb)
    else:
        await message.answer(f"⚠️ Неизвестная роль: '{role}'. Выберите роль в главном меню.")


async def org_mode_router(message: Message, state: FSMContext):
    mode_map = {"1️⃣ Режим 1": "org_1", "2️⃣ Режим 2": "org_2"}
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
        await message.answer("Режим 1: выберите действие", reply_markup=kb)


async def student_mode_router(message: Message):
    if message.text == "1️⃣ Режим 1":
        projects = await get_active_projects_for_student(message.from_user.id)
        if not projects:
            await message.answer("📭 У вас пока нет работ в проектах Режима 1.")
            return

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"📦 {p['name']}", callback_data=f"student_feedback_{p['id']}")]
            for p in projects
        ])
        await message.answer("📋 Выберите проект для просмотра оценок:", reply_markup=kb)

    elif message.text == "2️⃣ Режим 2":
        await message.answer("Режим 2: выберите действие", reply_markup=student_mode2_kb())


# ==================== ОРГАНИЗАТОР ====================

@dp.message(F.text == "📦 Мои проекты")
async def org_show_projects(message: Message):
    projects = await get_organizer_projects(1)  

    if not projects:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать новый проект", callback_data="org_create_project")]
        ])
        await message.answer("📭 У вас пока нет активных проектов.\nСоздайте первый!", reply_markup=kb)
        return

    project_buttons = [
        [InlineKeyboardButton(text=f"📦 {proj['name']} (Mode {proj['mode']})",
                              callback_data=f"org_project_{proj['id']}")]
        for proj in projects
    ]
    project_buttons.append([InlineKeyboardButton(text="➕ Создать проект", callback_data="org_create_project")])

    kb = InlineKeyboardMarkup(inline_keyboard=project_buttons)

    text = "📋 Ваши проекты:\n\n" + "\n".join([
        f"• {proj['name']}\n  📅 Дедлайн: {proj['deadline'].strftime('%d.%m.%Y')}\n  📊 Статус: {proj['status']}"
        for proj in projects
    ])

    await message.answer(text, reply_markup=kb)


@dp.message(F.text == "📥 Загрузить работы")
async def org_start_upload_works(message: Message, state: FSMContext):
    user_data = registered_users.get(message.from_user.id)
    if not user_data or user_data.get('role') != 'org':
        await message.answer("❌ Доступ только для организаторов.")
        return
        
    projects = await get_organizer_projects(user_data['db_id'])
    mode1_projects = [p for p in projects if p.get('mode') == 1]
    
    if not mode1_projects:
        await message.answer("📭 Нет активных проектов Режима 1 для загрузки.")
        return
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📦 {p['name']}", callback_data=f"org_upload_proj_{p['id']}")]
        for p in mode1_projects
    ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="org_cancel")])
    await message.answer("📥 Выберите проект для загрузки работ:", reply_markup=kb)

@dp.callback_query(F.data.startswith("org_upload_proj_"))
async def org_select_upload_project(callback: CallbackQuery, state: FSMContext):
    project_id = int(callback.data.split("_")[-1])
    await state.update_data(upload_project_id=project_id)
    await state.set_state(OrgUploadWorks.waiting_for_works)
    
    teams = await get_all_teams()
    teams_list = "\n".join([f"• `ID {t['id']}` — {t['name']}" for t in teams]) if teams else "Нет команд"
    #ИИ:
    await callback.message.edit_text(
        f"📥 **Загрузка работ для проекта**\n\n"
        f"📋 **Список команд и их ID:**\n{teams_list}\n\n"
        f"📝 **Формат ввода (каждая работа с новой строки):**\n"
        f"`ID_команды: Название работы | Ссылка`\n\n"
        f"💡 **Примеры:**\n"
        f"`1: Финальный проект | https://github.com/repo`\n"
        f"`2: Просто текст описания без ссылки`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="org_cancel")]
        ])
    )
    #
    await callback.answer()

@dp.callback_query(F.data == "org_download_template")
async def org_send_template(callback: CallbackQuery):
    template_text = (
        "1: Команда Alpha | https://github.com/alpha/project\n"
        "2: Команда Beta | https://drive.google.com/file/d/xxx\n"
        "3: Команда Gamma | Просто текстовое описание работы без ссылки"
    )
    from io import BytesIO
    file = BytesIO(template_text.encode('utf-8'))
    file.name = "template_works.txt"
    
    await callback.message.answer_document(
        document=file,
        caption="📄 Шаблон для загрузки работ. Заполните его и отправьте текстом в чат (или скопируйте формат)."
    )
    await callback.answer()

@dp.message(OrgUploadWorks.waiting_for_works, F.text)
async def org_process_works_upload(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=org_mode_kb()) # Убедитесь, что main_menu_kb() импортирована/определена
        return
        
    data = await state.get_data()
    project_id = data.get("upload_project_id")
    user_data = registered_users.get(message.from_user.id)
    organizer_id = user_data.get('db_id') if user_data else None
    
    if not organizer_id or not project_id:
        await message.answer("❌ Ошибка сессии. Начните заново через меню.")
        await state.clear()
        return
        
    lines = [line.strip() for line in message.text.strip().split("\n") if line.strip()]
    if not lines:
        await message.answer("❌ Пустой список. Попробуйте еще раз.")
        return
        
    try:
        result = await org_bulk_submit_works(organizer_id, project_id, lines)
        
        report = "📥 **Результат загрузки:**\n"
        if result["success"]:
            report += "\n".join(result["success"])
        if result["errors"]:
            report += "\n\n⚠️ **Ошибки:**\n" + "\n".join(result["errors"])
            
        report += "\n\n💡 *На все успешно загруженные работы автоматически созданы задания для экспертов проекта.*"
        
        await message.answer(report, parse_mode=ParseMode.MARKDOWN)
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Критическая ошибка: {e}")
        await state.clear()


@dp.callback_query(F.data == "org_create_project")
async def org_start_create_project(callback: CallbackQuery, state: FSMContext):
    await state.set_state(OrgProjectCreate.waiting_for_name)
    await callback.message.edit_text(
        "📦 Создание проекта \n\n"
        "Введите название проекта:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="org_cancel")]
        ])
    )
    await callback.answer()


@dp.message(OrgProjectCreate.waiting_for_name, F.text)
async def org_set_project_name(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=org_mode_kb())
        return

    name = message.text.strip()
    if len(name) < 3:
        await message.answer("❌ Название слишком короткое (мин. 3 символа).")
        return

    await state.update_data(project_name=name)
    await state.set_state(OrgProjectCreate.waiting_for_mode)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Режим 1 (Эксперт)", callback_data="proj_mode_1")],
        [InlineKeyboardButton(text="2️⃣ Режим 2 (P2P)", callback_data="proj_mode_2")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="org_cancel")]
    ])
    await message.answer(
        "🔢 Выберите режим проекта:\n\n"
        "1️⃣ **Экспертный** — работы проверяют назначенные эксперты\n"
        "2️⃣ **P2P** — студенты проверяют работы друг друга",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )


@dp.callback_query(F.data.startswith("proj_mode_"))
async def org_select_mode(callback: CallbackQuery, state: FSMContext):
    mode = int(callback.data.split("_")[-1])
    await state.update_data(project_mode=mode)
    await state.set_state(OrgProjectCreate.waiting_for_type)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔓 Открытый (все команды)", callback_data="proj_type_public")],
        [InlineKeyboardButton(text="🔐 Закрытый (выбор команд)", callback_data="proj_type_private")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="org_cancel")]
    ])

    await callback.message.edit_text(
        f"✅ Выбран **Режим {mode}**\n\n"
        " Выберите тип доступа:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )
    await callback.answer()


@dp.callback_query(F.data == "proj_type_public")
async def org_set_project_type_public(callback: CallbackQuery, state: FSMContext):
    await state.update_data(project_is_public=True)
    await state.set_state(OrgProjectCreate.waiting_for_deadline)
    await callback.message.edit_text(
        "✅ Выбран **открытый проект**\n\n"
        "📅 Введите дедлайн в формате ДД.ММ.ГГГГ ЧЧ:ММ (например, 15.06.2026 23:59):",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="org_cancel")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "proj_type_private")
async def org_set_project_type_private(callback: CallbackQuery, state: FSMContext):
    await state.update_data(project_is_public=False)
    await state.set_state(OrgProjectCreate.waiting_for_teams)

    teams = await get_all_teams()
    if not teams:
        await callback.answer("❌ В системе нет команд. Сначала создайте их.", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"👥 {t['name']}", callback_data=f"proj_team_toggle_{t['id']}")]
        for t in teams[:10]
    ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="✅ Завершить выбор", callback_data="proj_teams_done")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="org_cancel")])

    await callback.message.edit_text(
        "🔐 **Закрытый проект**\n\n"
        "Выберите команды, которые смогут участвовать:\n"
        "(нажимайте на названия для выбора)",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("proj_team_toggle_"))
async def org_toggle_project_team(callback: CallbackQuery, state: FSMContext):
    team_id = int(callback.data.split("_")[-1])
    data = await state.get_data()

    selected = data.get("project_teams", [])

    if team_id in selected:
        selected.remove(team_id)
        await callback.answer(f"❌ Команда убрана")
    else:
        selected.append(team_id)
        await callback.answer(f"✅ Команда добавлена")

    await state.update_data(project_teams=selected)

    teams = await get_all_teams()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{'✅' if t['id'] in selected else '👥'} {t['name']}",
            callback_data=f"proj_team_toggle_{t['id']}"
        )] for t in teams[:10]
    ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="✅ Завершить выбор", callback_data="proj_teams_done")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="org_cancel")])

    await callback.message.edit_text(
        f"🔐 Закрытый проект\n\n"
        f"Выбрано команд: {len(selected)}\n"
        f"(нажимайте для переключения)",
        reply_markup=kb
    )


@dp.callback_query(F.data == "proj_teams_done")
async def org_teams_selection_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("project_teams", [])

    if not selected:
        await callback.answer("❌ Выберите хотя бы одну команду", show_alert=True)
        return

    await state.set_state(OrgProjectCreate.waiting_for_deadline)
    await callback.message.edit_text(
        f"✅ Выбрано команд: {len(selected)}\n\n"
        "📅 Введите дедлайн в формате ДД.ММ.ГГГГ ЧЧ:ММ:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="org_cancel")]
        ])
    )
    await callback.answer()


@dp.message(OrgProjectCreate.waiting_for_deadline, F.text)
async def org_set_project_deadline(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=org_mode_kb())
        return

    try:
        deadline = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
        deadline = deadline.replace(tzinfo=timezone.utc)
        if deadline <= datetime.now(timezone.utc):
            raise ValueError("Дедлайн должен быть в будущем")
    except ValueError as e:
        await message.answer(f"❌ Неверный формат. Пример: 15.06.2026 23:59")
        return

    await state.update_data(project_deadline=deadline)
    await state.set_state(OrgProjectCreate.waiting_for_criteria)  # Теперь всегда идём к критериям
    await message.answer(
        "📏 Введите критерии (по одному в строке).\n"
        "Формат: **Название МаксБалл** (через пробел)\n\n"
        "Примеры:\n"
        "`Архитектура 10`\n"
        "`Код 20`\n"
        "`Презентация 15`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="org_cancel")]
        ])
    )

@dp.callback_query(F.data == "org_skip_criteria")
async def org_skip_criteria(callback: CallbackQuery, state: FSMContext):
    await state.update_data(project_criteria=[])
    await org_confirm_creation(callback.message, state)
    await callback.answer("✅ Критерии пропущены")

@dp.message(OrgProjectCreate.waiting_for_criteria, F.text)
async def org_set_criteria(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=org_mode_kb())
        return

    criteria = []
    lines = message.text.strip().split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        parts = line.split()

        if len(parts) < 2:
            await message.answer(
                f"❌ Ошибка в строке: `{line}`\n"
                f"Убедитесь, что после названия стоит пробел и число.\n"
                f"Пример: `Название 10`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        try:
            score = int(parts[-1])
            name = " ".join(parts[:-1])

            criteria.append({
                "name": name[:127],  
                "max_score": score,
                "sort_order": len(criteria)
            })
        except ValueError:
            await message.answer(
                f"❌ Ошибка в строке: `{line}`\n"
                f"Последнее слово должно быть числом (баллами).",
                parse_mode=ParseMode.MARKDOWN
            )
            return

    if not criteria:
        await message.answer("❌ Не найдено корректных критериев. Попробуйте снова или нажмите 'Пропустить'.")
        return

    await state.update_data(project_criteria=criteria)
    await org_confirm_creation(message, state)


async def org_confirm_creation(message: Message, state: FSMContext):
    data = await state.get_data()
    mode_name = "Эксперт" if data.get("project_mode") == 1 else "P2P"
    project_type = "🔓 Открытый" if data.get("project_is_public", True) else "🔐 Закрытый"
    teams_count = len(data.get("project_teams", []))

    criteria_preview = "\n".join([f"• {c['name']}: {c['max_score']} балл(ов)"
                                  for c in data.get("project_criteria", [])]) or "❌ Без критериев"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Создать", callback_data="org_do_create_project")],
        [InlineKeyboardButton(text="✏️ Изменить", callback_data="org_edit_criteria")]
    ])
    #ИИ
    await message.answer(
        f"📋 Подтвердите создание проекта:\n\n"
        f"📦 Название: {data['project_name']}\n"
        f" Режим: {mode_name}\n"
        f"🔐 Тип: {project_type}" + (f" ({teams_count} команд)" if teams_count else "") + "\n"
                                                                                         f"📅 Дедлайн: {data['project_deadline'].strftime('%d.%m.%Y %H:%M')}\n"
                                                                                         f" Критерии:\n{criteria_preview}",
        reply_markup=kb
    )
    #
    await state.set_state(OrgProjectCreate.confirming_creation)

#ИИ
@dp.callback_query(F.data == "org_do_create_project")
async def org_do_create_project(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    try:
        user_data = registered_users.get(callback.from_user.id)
        if not user_data or user_data.get('role') != 'org':
            await callback.answer("❌ Вы не авторизованы как организатор", show_alert=True)
            return
            
        organizer_id = user_data['db_id']
        participant_teams = None
        if not data.get("project_is_public", True):
            participant_teams = data.get("project_teams", [])
            
        project = await create_project_with_criteria(
            organizer_id=organizer_id,
            name=data["project_name"],
            mode=data.get("project_mode", 1),
            deadline=data["project_deadline"],
            criteria=data.get("project_criteria"),
            participant_team_ids=participant_teams,
            is_public=data.get("project_is_public", True)
        )
        await state.clear()
        
        if project.mode == 1:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👥 Назначить экспертов", callback_data=f"org_assign_experts_{project.id}")],
                [InlineKeyboardButton(text="📥 Загрузить работы", callback_data=f"org_upload_proj_{project.id}")],
                [InlineKeyboardButton(text="📊 Открыть дашборд", callback_data=f"org_project_{project.id}")]
            ])
            text = (
                f"✅ **Проект успешно создан!**\n\n"
                f"📦 {project.name}\n"
                f"🔢 Режим: 1 (Экспертный)\n"
                f"🆔 ID: {project.id}\n"
                f"📅 Дедлайн: {project.deadline.strftime('%d.%m.%Y %H:%M')}\n\n"
                f"💡 **осталось загрузить работы!**\n"
                f"_(При загрузке работ система автоматически создаст задания для выбранных экспертов)_"
            )
        else:
            # Для Режима 2 (P2P) эксперты не нужны
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📥 Загрузить работы", callback_data=f"org_upload_proj_{project.id}")],
                [InlineKeyboardButton(text="📊 Открыть дашборд", callback_data=f"org_project_{project.id}")]
            ])
            text = (
                f"✅ **Проект успешно создан!**\n\n"
                f"📦 {project.name}\n"
                f"🔢 Режим: 2 (P2P)\n"
                f"🆔 ID: {project.id}\n"
                f"📅 Дедлайн: {project.deadline.strftime('%d.%m.%Y %H:%M')}"
            )
            
        await callback.message.edit_text(
            text, 
            parse_mode=ParseMode.MARKDOWN, 
            reply_markup=kb
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        await callback.answer(f"❌ Ошибка при создании: {e}", show_alert=True)
#

@dp.callback_query(F.data.startswith("org_project_"))
async def org_project_dashboard(callback: CallbackQuery):
    project_id = int(callback.data.split("_")[-1])
    dashboard = await get_project_dashboard(project_id)

    if not dashboard:
        await callback.answer("❌ Не удалось загрузить данные", show_alert=True)
        return

    experts_text = "\n".join([
        f"• {e['expert_name']}: {e['checked_count']} проверено"
        for e in dashboard["experts"]
    ]) or "❌ Нет назначенных экспертов"

    criteria_text = "\n".join([
        f"• {c['name']}: макс. {c['max_score']}"
        for c in dashboard["criteria"]
    ]) or "❌ Нет критериев"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Назначить экспертов", callback_data=f"org_assign_experts_{project_id}")],
        [InlineKeyboardButton(text="📥 Экспортировать", callback_data=f"org_export_{project_id}")],
        [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="org_back_to_projects")]
    ])

    text = (
        f"📊 Дашборд: {dashboard['project_id']}\n\n"
        f"📈 Работы:\n"
        f"• Всего: {dashboard['total_submissions']}\n"
        f"• Проверено: {dashboard['checked_submissions']}\n"
        f"• Ожидает: {dashboard['pending_submissions']}\n\n"
        f"👥 Эксперты:\n{experts_text}\n\n"
        f"📏 Критерии:\n{criteria_text}"
    )

    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data == "org_back_to_projects")
async def org_back_to_projects(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "👔 Панель организатора",
        reply_markup=org_mode_kb()
    )
    await callback.message.delete()


@dp.callback_query(F.data.startswith("org_assign_experts_"))
async def org_start_assign_experts(callback: CallbackQuery, state: FSMContext):
    project_id = int(callback.data.split("_")[-1])
    await state.update_data(assign_project_id=project_id)

    experts = await get_all_experts()
    if not experts:
        await callback.answer("❌ В системе нет экспертов. Сначала зарегистрируйте их.", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"👤 {e['name']}", callback_data=f"org_expert_toggle_{e['id']}")]
        for e in experts[:15]  
    ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="✅ Завершить выбор", callback_data="org_experts_confirm")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"org_project_{project_id}")])

    await callback.message.edit_text(
        "👥 Выберите экспертов для назначения:\n"
        "(нажимайте на имена для выбора)",
        reply_markup=kb
    )
    await state.set_state(OrgAssignExperts.selecting_experts)
    await callback.answer()


@dp.callback_query(F.data == "org_cancel")
async def org_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Отменено.", reply_markup=org_mode_kb())
    await callback.answer()

# ==================== ОРГАНИЗАТОР: ЭКСПЕРТЫ ====================

@dp.callback_query(F.data.startswith("org_expert_toggle_"))
async def org_toggle_expert(callback: CallbackQuery, state: FSMContext):
    """Переключение эксперта в списке выбора"""
    expert_id = int(callback.data.split("_")[-1])
    data = await state.get_data()
    selected = data.get("selected_experts", [])

    if expert_id in selected:
        selected.remove(expert_id)
        await callback.answer(f"❌ Эксперт убран из выбора")
    else:
        selected.append(expert_id)
        await callback.answer(f"✅ Эксперт добавлен в выбор")

    await state.update_data(selected_experts=selected)
    experts = await get_all_experts()

    keyboard = []
    for e in experts[:10]:
        emoji = "✅" if e['id'] in selected else "👤"
        keyboard.append([InlineKeyboardButton(
            text=f"{emoji} {e['name']}",
            callback_data=f"org_expert_toggle_{e['id']}"
        )])

    keyboard.append([InlineKeyboardButton(text="✅ Завершить выбор", callback_data="org_experts_confirm")])
    keyboard.append(
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"org_project_{data.get('assign_project_id')}")])

    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)

    await callback.message.edit_text(
        f"👥 Выбрано экспертов: {len(selected)}\n"
        f"(нажимайте на имена для переключения)",
        reply_markup=kb
    )

@dp.callback_query(F.data == "org_experts_confirm")
async def org_confirm_expert_assignment(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    project_id = data.get("assign_project_id")
    selected_ids = data.get("selected_experts", []) 
    
    if not selected_ids:
        await callback.answer("❌ Выберите хотя бы одного эксперта", show_alert=True)
        return
        
    try:
        result = await assign_experts_to_project(project_id, selected_ids)
        all_experts = await get_all_experts()
        selected_experts = [e for e in all_experts if e["id"] in selected_ids]
        #ИИ
        report = (
            f"✅ **Назначение завершено!**\n"
            f"📁 Проект ID: {project_id}\n"
            f"👥 Назначено экспертов: {len(selected_experts)}\n"
            f"📝 Создано заданий: {result['assigned_count']}\n\n"
        )
        for exp in selected_experts:
            report += f"• {exp['name']}\n"
            
        if result['assigned_count'] == 0:
            report += "\n⚠️ *В проекте пока нет работ. Эксперты получат задания автоматически, когда вы загрузите работы.*"
            
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К дашборду проекта", callback_data=f"org_project_{project_id}")]
        ])
        await callback.message.edit_text(report, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
        await state.clear()
    except Exception as e:
        import traceback
        traceback.print_exc()
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
        #

@dp.callback_query(F.data == "org_back_to_dashboard")
async def org_back_to_dashboard(callback: CallbackQuery, state: FSMContext):
    """Возврат к дашборду проекта"""
    data = await state.get_data()
    project_id = data.get("assign_project_id")
    await state.clear()

    if project_id:
        dashboard = await get_project_dashboard(project_id)
        
        experts_text = "\n".join([
            f"• {e['expert_name']}: {e['checked_count']} проверено"
            for e in dashboard["experts"]
        ]) or "❌ Нет назначенных экспертов"

        criteria_text = "\n".join([
            f"• {c['name']}: макс. {c['max_score']}"
            for c in dashboard["criteria"]
        ]) or "❌ Нет критериев"
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Назначить экспертов", callback_data=f"org_assign_experts_{project_id}")],
            [InlineKeyboardButton(text="📥 Экспортировать", callback_data=f"org_export_{project_id}")],
            [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="org_back_to_projects")]
        ])
        
        text = (
            f"📊 Дашборд: {dashboard['project_id']}\n\n"
            f"📈 Работы:\n"
            f"• Всего: {dashboard['total_submissions']}\n"
            f"• Проверено: {dashboard['checked_submissions']}\n"
            f"• Ожидает: {dashboard['pending_submissions']}\n\n"
            f"👥 Эксперты:\n{experts_text}\n\n"
            f"📏 Критерии:\n{criteria_text}"
        )
        
        await callback.message.edit_text(text, reply_markup=kb)
    else:
        await callback.message.edit_text("👔 Панель организатора", reply_markup=org_mode_kb())
    
    await callback.answer()

# ==================== ОРГАНИЗАТОР: ЭКСПОРТ ====================

@dp.callback_query(F.data.startswith("org_export_"))
async def org_export_results(callback: CallbackQuery):
    """Экспорт результатов проекта в текстовый формат"""
    project_id = int(callback.data.split("_")[-1])

    try:
        results = await export_project_results(project_id)

        if not results:
            await callback.answer("ℹ️ Нет данных для экспорта", show_alert=True)
            return

        report = f"📊 Экспорт результатов проекта #{project_id}\n\n"
        report += "=" * 50 + "\n\n"

        for row in results:
            report += f"👥 Команда: {row['team_name']}\n"
            report += f"📝 Работа #{row['submission_id']}\n"
            report += f"📊 Статус: {row['status']}\n"
            if row['mark'] is not None:
                report += f"⭐ Оценка: {row['mark']}\n"
            if row['checked_at']:
                report += f"🕐 Проверено: {row['checked_at']}\n"

            if row['comments']:
                report += "💬 Комментарии:\n"
                for c in row['comments']:
                    report += f"  • {c['text'][:100]}...\n"

            report += "\n" + "-" * 30 + "\n\n"

        for i in range(0, len(report), 4000):  
            await callback.message.answer(report[i:i + 4000])

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Открыть подробные результаты", url="https://jczapadn-rgb.github.io/itogitog/")],
            [InlineKeyboardButton(text="🔙 К дашборду", callback_data=f"org_project_{project_id}")]
        ])
        await callback.message.answer("✅ Экспорт завершён", reply_markup=kb)

    except Exception as e:
        await callback.answer(f"❌ Ошибка экспорта: {e}", show_alert=True)

# ==================== ЭКСПЕРТ ====================

@dp.message(F.text == "📋 Взять работу")
async def expert_choose_project(message: Message, state: FSMContext):
    user = await get_expert_by_telegram(message.from_user.id)
    if not user:
        await message.answer("❌ Вы не авторизованы как эксперт.")
        return

    projects = await get_expert_active_projects(message.from_user.id)
    if not projects:
        await message.answer("🎉 Нет активных проектов для проверки.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📦 {p['name']}", callback_data=f"expert_project_{p['id']}")]
        for p in projects
    ])
    await message.answer("📋 Выберите проект для проверки:", reply_markup=kb)


@dp.callback_query(F.data.startswith("expert_project_"))
async def expert_select_project(callback: CallbackQuery, state: FSMContext):
    project_id = int(callback.data.split("_")[-1])
    await state.update_data(project_id=project_id)
    
    task = await get_next_task_for_expert(callback.from_user.id, project_id)
    if not task:
        await callback.answer("ℹ️ Нет доступных работ в этом проекте", show_alert=True)
        return
    
    await state.update_data(
        assignment_id=task["assignment_id"],
        submission_id=task["submission"].id,
        is_continuation=task.get("is_continuation", False)
    )
    
    criteria = await get_project_criteria(project_id)
    await state.update_data(criteria=criteria)
    
    sub = task["submission"]
    artifacts_text = "\n".join([f"• [{a.type}] {a.url}" for a in sub.artifacts]) if sub.artifacts else "Нет артефактов"
    criteria_text = "\n".join([f"• {c['name']} (макс. {c['max_score']})" for c in criteria])
    
    text = (
        f"📝 Работа #{sub.id} | Проект: {sub.project.name}\n"
        f"📄 Контент:\n{sub.content[:500]}{'...' if len(sub.content) > 500 else ''}\n"
        f"🔗 Артефакты:\n{artifacts_text}\n"
        f"📏 Критерии оценки:\n{criteria_text}"
    )
    
    if task.get("is_continuation"):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Продолжить оценку", callback_data="expert_start_scoring")]
        ])
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Начать оценку", callback_data="expert_start_scoring")]
        ])
        
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data == "expert_start_scoring")
async def expert_start_scoring(callback: CallbackQuery, state: FSMContext):
    user_data = registered_users.get(callback.from_user.id, {})
    db_id = user_data.get('db_id')
    if not db_id:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return
    
    await state.update_data(db_id=db_id)
    
    data = await state.get_data()
    if not data.get("criteria"):
        criteria = await get_project_criteria(data.get("project_id"))
        await state.update_data(criteria=criteria)
    
    await _expert_show_next_criterion_from_state(callback, state)

#ИИ
async def _expert_show_next_criterion_from_state(event, state: FSMContext):
    """Показывает следующий критерий. Если все оценены, показывает кнопки комментария и завершения."""
    data = await state.get_data()
    criteria = data.get("criteria", [])
    
    if not criteria:
        await _safe_answer(event, "❌ Критерии не загружены")
        return
    
    unscored_criteria = [c for c in criteria if not c.get("scored", False)]
    
    if not unscored_criteria:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Добавить комментарий", callback_data="expert_write_comment")],
            [InlineKeyboardButton(text="✅ Завершить проверку", callback_data="expert_finalize")]
        ])
        text = "✅ **Все критерии успешно оценены!**\n\n💡 Теперь вы можете добавить комментарий (по желанию) или сразу завершить проверку."
        await _safe_edit_or_send(event, text, kb)
        return

    c = unscored_criteria[0]
    await state.update_data(current_criterion=c)
    await state.set_state(ExpertReview.scoring_criterion)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Пропустить (0 баллов)", callback_data="expert_skip_criterion")]
    ])
    text = (
        f"⭐ **{c['name']}**\n"
        f"Введите оценку от 0 до {c['max_score']}:\n"
        f"_(или нажмите «Пропустить», чтобы поставить 0)_"
    )
    await _safe_edit_or_send(event, text, kb)
#

@dp.message(ExpertReview.scoring_criterion, F.text)
async def expert_save_score(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=(show_main_menu)) # Убедитесь, что функция импортирована
        return
    
    data = await state.get_data()
    criterion = data.get("current_criterion")
    if not criterion:
        await message.answer("❌ Ошибка: критерий не выбран")
        await state.clear()
        return
    
    try:
        score = int(message.text.strip())
        if not (0 <= score <= criterion["max_score"]):
            raise ValueError
    except (ValueError, TypeError):
        await message.answer(f"❌ Введите число от 0 до {criterion['max_score']}:")
        return
    
    user_data = registered_users.get(message.from_user.id, {})
    db_id = user_data.get('db_id')
    if not db_id:
        await message.answer("❌ Пользователь не найден в БД")
        return
    
    try:
        await submit_criterion_score(
            assignment_id=data["assignment_id"],
            criterion_id=criterion["id"],
            score=score
        )
        
        criteria = data.get("criteria", [])
        for c in criteria:
            if c["id"] == criterion["id"]:
                c["scored"] = True
                c["existing_score"] = score
                break
        await state.update_data(criteria=criteria)
        
        await message.answer(f"✅ Оценка {score}/{criterion['max_score']} сохранена!")
        await asyncio.sleep(0.5)
        
        await _expert_show_next_criterion_from_state(message, state)
    except ValueError as e:
        await message.answer(f"❌ {e}")


async def _expert_show_next_criterion_from_state(event, state: FSMContext):
    """Показывает следующий критерий, полагаясь ТОЛЬКО на состояние (не БД)"""
    data = await state.get_data()
    criteria = data.get("criteria", [])

    if not criteria:
        await _safe_answer(event, "❌ Критерии не загружены")
        return

    for c in criteria:
        if not c.get("scored", False):
            await state.update_data(current_criterion=c)
            await state.set_state(ExpertReview.scoring_criterion)

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Пропустить", callback_data="expert_skip_criterion")]
            ])

            text = (
                f"⭐ **{c['name']}**\n"
                f"Введите оценку от 0 до {c['max_score']}:\n\n"
                f"_(или нажмите «Пропустить»)_"
            )

            await _safe_edit_or_send(event, text, kb)
            return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Комментарий", callback_data="expert_write_comment")],
        [InlineKeyboardButton(text="✅ Завершить", callback_data="expert_finalize")]
    ])

    text = "✅ Все критерии оценены!\n\n💡 Можете добавить комментарий или завершить проверку."
    await _safe_edit_or_send(event, text, kb)


async def _safe_answer(event, text: str):
    if hasattr(event, 'answer') and hasattr(event, 'message'):
        await event.answer(text)
    else:
        await event.answer(text)


async def _safe_edit_or_send(event, text: str, reply_markup=None):
    if hasattr(event, 'message') and hasattr(event.message, 'edit_text'):
        try:
            await event.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        except Exception:
            await event.message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    else:
        await event.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

    if hasattr(event, 'answer') and hasattr(event, 'message'):
        await event.answer()


@dp.callback_query(F.data == "expert_skip_criterion")
async def expert_skip_criterion(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    criterion = data.get("current_criterion")
    assignment_id = data.get("assignment_id")
    
    if not criterion or not assignment_id:
        await callback.answer("❌ Ошибка состояния", show_alert=True)
        return
        
    try:
        await submit_criterion_score(
            assignment_id=assignment_id,
            criterion_id=criterion["id"],
            score=0
        )
        
        criteria = data.get("criteria", [])
        for c in criteria:
            if c["id"] == criterion["id"]:
                c["scored"] = True
                c["existing_score"] = 0
                break
        await state.update_data(criteria=criteria)
        
        await callback.answer("⏭️ Пропущено (оценка 0)")
        await _expert_show_next_criterion_from_state(callback, state)
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)


@dp.callback_query(F.data.startswith("expert_score_"))
async def expert_set_score(callback: CallbackQuery, state: FSMContext):
    score = int(callback.data.split("_")[-1])
    data = await state.get_data()
    criterion = data.get("current_criterion")

    if not criterion:
        await callback.answer("❌ Ошибка: критерий не выбран", show_alert=True)
        return

    try:
        result = await submit_criterion_score(
            assignment_id=data["assignment_id"],
            criterion_id=criterion["id"],
            score=score
        )

        criteria = data.get("criteria", [])
        for c in criteria:
            if c["id"] == criterion["id"]:
                c["scored"] = True
                c["existing_score"] = score
                break
        await state.update_data(criteria=criteria)

        await callback.message.edit_text(
            f"✅ Оценка {score}/{criterion['max_score']} сохранена для \"{criterion['name']}\"")
        await asyncio.sleep(1)
        await expert_start_scoring(callback, state)
    except ValueError as e:
        await callback.answer(f"❌ {e}", show_alert=True)


@dp.callback_query(F.data == "expert_write_comment")
async def expert_write_comment(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ExpertReview.writing_comment)
    await callback.message.edit_text("✍️ Напишите комментарий к работе или запишите голосовое сообщение (или нажмите «Назад» для пропуска):")
    await callback.answer()


@dp.message(ExpertReview.writing_comment, F.text)
async def expert_save_comment(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=student_mode2_kb())
        return

    data = await state.get_data()
    try:
        result = await submit_expert_comment(
            assignment_id=data["assignment_id"],
            comment_text=message.text.strip()
        )
        await state.update_data(comment_id=result["id"])

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Завершить проверку", callback_data="expert_finalize")],
            [InlineKeyboardButton(text="✏️ Исправить", callback_data="expert_write_comment")]
        ])
        await message.answer(f"✅ Комментарий сохранён:\n\n{message.text[:200]}...", reply_markup=kb)
        await state.set_state(ExpertReview.confirming_review)
    except ValueError as e:
        await message.answer(f"❌ {e}")


@dp.callback_query(F.data == "expert_finalize")
async def expert_finalize(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    criteria = data.get("criteria", [])
    if not all(c.get("scored", False) for c in criteria):
        await callback.answer("❌ Оцените все критерии перед завершением", show_alert=True)
        return

    try:
        result = await finalize_expert_review(data["assignment_id"])

        text = f"🎉 Проверка завершена!\n"
        if result["final_mark"]:
            text += f"⭐ Итоговая оценка: {result['final_mark']}\n"

        if result["next_submission_id"]:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📥 Следующая работа",
                                      callback_data=f"expert_next_{result['next_submission_id']}")]
            ])
            text += "\n📥 Следующая работа уже ждёт!"
            await callback.message.edit_text(text, reply_markup=kb)
        else:
            text += "\n✅ Все работы в проекте проверены."
            await callback.message.edit_text(text)

        await state.clear()
    except ValueError as e:
        await callback.answer(f"❌ {e}", show_alert=True)
    except Exception as e:
        logging.error(f"Finalize error: {e}")
        await callback.answer("❌ Ошибка при завершении", show_alert=True)

# ИИ
@dp.callback_query(F.data.startswith("expert_next_"))
async def expert_take_next(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🔄 Загрузка следующей работы...")
    await callback.answer()

    data = await state.get_data()
    project_id = data.get("project_id")
    
    if not project_id:
        projects = await get_expert_active_projects(callback.from_user.id)
        if not projects:
            await callback.message.edit_text("🎉 Нет активных проектов для проверки.")
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"📦 {p['name']}", callback_data=f"expert_project_{p['id']}")]
            for p in projects
        ])
        await callback.message.edit_text("📋 Выберите проект для проверки:", reply_markup=kb)
        return

    task = await get_next_task_for_expert(callback.from_user.id, project_id)
    
    if not task:
        await callback.message.edit_text(
            "🎉 В этом проекте больше нет работ для проверки! Отличная работа.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 К выбору проекта", callback_data="expert_choose_project_menu")] # Убедитесь, что такая кнопка есть в главном меню эксперта, или используйте текст команды
            ])
        )
        await state.clear()
        return

    await state.update_data(
        assignment_id=task["assignment_id"],
        submission_id=task["submission"].id,
        is_continuation=task.get("is_continuation", False),
        project_id=project_id
    )
    
    criteria = await get_project_criteria(project_id)
    await state.update_data(criteria=criteria)
    
    sub = task["submission"]
    artifacts_text = "\n".join([f"• [{a.type}] {a.url}" for a in sub.artifacts]) if sub.artifacts else "Нет артефактов"
    criteria_text = "\n".join([f"• {c['name']} (макс. {c['max_score']})" for c in criteria])
    
    text = (
        f"📝 Работа #{sub.id} | Проект: {sub.project.name}\n"
        f"📄 Контент:\n{sub.content[:500]}{'...' if len(sub.content) > 500 else ''}\n"
        f"🔗 Артефакты:\n{artifacts_text}\n"
        f"📏 Критерии оценки:\n{criteria_text}"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Начать оценку", callback_data="expert_start_scoring")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb)
#

@dp.message(F.text == "📊 Статистика")
async def expert_show_stats(message: Message):
    stats = await get_expert_stats(message.from_user.id)
    if not stats:
        await message.answer("❌ Не удалось загрузить статистику.")
        return

    text = (
        f"📊 Ваша статистика:\n"
        f"• Всего заданий: {stats['total_assigned']}\n"
        f"• Завершено: {stats['completed']}\n"
        f"• В работе: {stats['pending']}"
    )
    await message.answer(text)


# ==================== СТУДЕНТ ====================

@dp.callback_query(F.data.startswith("submit_to_"))
async def process_project_selection(callback: CallbackQuery, state: FSMContext):
    project_id = int(callback.data.split("_")[-1])
    await state.update_data(project_id=project_id)
    await state.set_state(StudentSubmission.waiting_for_link)

    await callback.message.answer("🔗 Отправьте ссылку(и) на работу:", reply_markup=cancel_reply_kb())
    await callback.answer()


@dp.message(StudentSubmission.waiting_for_link, F.text)
async def process_student_links(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=student_mode2_kb())
        return

    links = re.findall(r'https?://[^\s]+', message.text)
    if not links:
        await message.answer("❌ Не найдено ссылок.")
        return

    await state.update_data(links=links)
    preview = "\n".join([f"{i + 1}. {l}" for i, l in enumerate(links)])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_student_submit")],
        [InlineKeyboardButton(text="✏️ Изменить", callback_data="edit_student_submit")]
    ])
    await message.answer(f"🔗 Ссылки:\n{preview}\n\nВсё верно?", reply_markup=kb)
    await state.set_state(StudentSubmission.confirm_submission)


@dp.callback_query(F.data == "edit_student_submit")
async def edit_student_submit(callback: CallbackQuery, state: FSMContext):
    await state.set_state(StudentSubmission.waiting_for_link)
    await callback.message.answer("Отправьте ссылки заново:")
    await callback.answer()


@dp.callback_query(F.data == "confirm_student_submit")
async def confirm_student_submit(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    links = data.get('links', [])
    project_id = data.get('project_id') 

    if not project_id:
        await callback.answer("❌ Ошибка: проект не выбран", show_alert=True)
        return

    try:
        user = await get_user_by_telegram(callback.from_user.id)
        artifacts = [{"url": link, "type": "link"} for link in links]

        submission = await submit_work(
            telegram_id=callback.from_user.id,
            project_id=project_id,
            content=f"Работа от {user.name}",
            artifacts=artifacts
        )

        await state.clear()
        await callback.message.answer(f"✅ Работа отправлена в проект #{project_id}!\n📁 ID работы: {submission.id}",
                                      reply_markup=student_mode2_kb())
    except ValueError as e:
        await callback.message.answer(f"❌ {e}")
    except Exception as e:
        logging.error(f"Submit error: {e}")
        await callback.message.answer("❌ Ошибка отправки. Попробуйте позже.")
    await callback.answer()


# ===================== СТУДЕНТ: ПРОСМОТР ОЦЕНОК =======================
@dp.message(F.text == "📊 Мои результаты")
async def student_show_my_results_menu(message: Message):
    user = await get_student_by_telegram(message.from_user.id)
    if not user or not user.team_id:
        await message.answer("❌ Вы не привязаны к команде.")
        return
        
    projects = await get_active_projects_for_team(user.team_id)
    if not projects:
        await message.answer("📭 У вас нет проектов для просмотра.")
        return
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📦 {p['name']} (Mode {p['mode']})", callback_data=f"student_feedback_{p['id']}")]
        for p in projects
    ])
    await message.answer("📊 Выберите проект для просмотра результатов:", reply_markup=kb)

@dp.callback_query(F.data.startswith("student_feedback_"))
async def student_show_feedback(callback: CallbackQuery, state: FSMContext):
    project_id = int(callback.data.split("_")[-1])
    submissions = await get_student_submissions_with_feedback(callback.from_user.id, project_id=project_id)
    
    if not submissions:
        await callback.answer("ℹ️ Нет данных для отображения", show_alert=True)
        return
        
    sub = submissions[0]
    status_emoji = {"unchecked": "⏳", "checking": "🔍", "checked": "✅"}.get(sub["status"], "❓")
    update_time = datetime.now().strftime("%H:%M:%S")
    
    text = (
        f"📝 Работа #{sub['id']} | Проект: {sub['project_name']}\n"
        f"📅 Отправлена: {sub['created_at']}\n"
        f"📊 Статус: {status_emoji} {sub['status'].replace('_', ' ').title()}\n"
        f"🕐 Обновлено: {update_time}\n"
    )
    
    if sub.get("content"):
        content_preview = sub["content"][:200] + ("..." if len(sub["content"]) > 200 else "")
        text += f"📄 **Работа:** {content_preview}\n"
        
    if sub["status"] == "checked" and sub["mark"] is not None:
        text += f"⭐ Итоговая оценка: **{sub['mark']}**\n"
        
    if sub["criteria"]:
        text += "📏 Оценки по критериям:\n"
        for crit in sub["criteria"]:
            text += f"• {crit['name']}: **{crit['average']}/{crit['max']}**\n"
        text += "\n"
        
    if sub["comments"]:
        text += "💬 Комментарии:\n"
        for c in sub["comments"]:
            text += f"• {c['author']} ({c['created_at']}):\n_{c['text']}_\n"
            
    text += "\n💡 *Для детального просмотра всех графиков, таблиц и полной статистики рекомендуем использовать веб-интерфейс.*"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Открыть подробные результаты", url="https://jczapadn-rgb.github.io/itogitog/")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"student_feedback_{project_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="student_back_to_mode1")]
    ])
    
    try:
        await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    except TelegramBadRequest:
        pass
    await callback.answer()


@dp.callback_query(F.data == "student_back_to_mode1")
async def student_back_to_mode1(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "👨‍🎓 Панель студента",
        reply_markup=student_mode_kb()
    )
    await callback.message.delete()


# ====================== РЕЖИМ 2 (P2P) =====================
@dp.message(F.text == "📤 Отправить работу")
async def student_submit_work_menu(message: Message, state: FSMContext):
    user = await get_student_by_telegram(message.from_user.id)
    if not user or not user.team_id:
        await message.answer("❌ Вы не привязаны к команде.")
        return

    projects = await get_active_projects_for_team(user.team_id)
    mode2_projects = [p for p in projects if p.get("mode") == 2]
    
    if not mode2_projects:
        await message.answer("📭 Нет активных проектов P2P для отправки работ.")
        return
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📦 {p['name']}", callback_data=f"peer_submit_{p['id']}")]
        for p in mode2_projects
    ])
    await message.answer("📤 Выберите проект для отправки работы:", reply_markup=kb)


@dp.callback_query(F.data.startswith("peer_submit_"))
async def peer_select_project(callback: CallbackQuery, state: FSMContext):
    project_id = int(callback.data.split("_")[-1])
    await state.update_data(project_id=project_id)
    await state.set_state(StudentSubmission.waiting_for_link)  # Используем тот же FSM

    await callback.message.answer("🔗 Отправьте ссылку(и) на работу:", reply_markup=cancel_reply_kb())
    await callback.answer()


@dp.message(StudentSubmission.waiting_for_link, F.text)
async def process_peer_links(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=student_mode2_kb())
        return

    links = re.findall(r'https?://[^\s]+', message.text)
    if not links:
        await message.answer("❌ Не найдено ссылок.")
        return

    await state.update_data(links=links)
    preview = "\n".join([f"{i + 1}. {l}" for i, l in enumerate(links)])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_peer_submit")],
        [InlineKeyboardButton(text="️ Изменить", callback_data="edit_peer_submit")]
    ])
    await message.answer(f"🔗 Ссылки:\n{preview}\n\nВсё верно?", reply_markup=kb)
    await state.set_state(StudentSubmission.confirm_submission)


@dp.callback_query(F.data == "edit_peer_submit")
async def edit_peer_submit(callback: CallbackQuery, state: FSMContext):
    await state.set_state(StudentSubmission.waiting_for_link)
    await callback.message.answer("Отправьте ссылки заново:")
    await callback.answer()


@dp.callback_query(F.data == "confirm_peer_submit")
async def confirm_peer_submit(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    links = data.get('links', [])
    project_id = data.get('project_id')

    if not project_id:
        await callback.answer("❌ Ошибка: проект не выбран", show_alert=True)
        return

    try:
        user = await get_student_by_telegram(callback.from_user.id)
        artifacts = [{"url": link, "type": "link"} for link in links]
        submission = await submit_work(
            telegram_id=callback.from_user.id,
            project_id=project_id,
            content=f"Работа от {user.name}",
            artifacts=artifacts
        )
        
        await state.clear()
        await callback.message.answer(
            f"✅ Работа отправлена!\n📁 ID: {submission.id}\n"
            f"💡 Теперь возьмите чужие работы на проверку:",
            reply_markup=student_mode2_kb()
        )
    except ValueError as e:
        await callback.message.answer(f"❌ {e}")
    except Exception as e:
        logging.error(f"Peer submit error: {e}")
        await callback.message.answer("❌ Ошибка отправки.")
    await callback.answer()

@dp.message(F.text == "👥 Чужие работы")
async def peer_show_queue(message: Message, state: FSMContext):
    user = await get_student_by_telegram(message.from_user.id)
    if not user or not user.team_id:
        await message.answer("❌ Вы не привязаны к команде.")
        return
        
    projects = await get_active_projects_for_team(user.team_id) # <-- Было message.from_user.id
    mode2_projects = [p for p in projects if p.get("mode") == 2]
    
    if not mode2_projects:
        await message.answer("📭 Нет активных проектов Режима 2.")
        return
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📦 {p['name']}", callback_data=f"peer_queue_{p['id']}")]
        for p in mode2_projects
    ])
    await message.answer("👥 Выберите проект для проверки работ:", reply_markup=kb)

# ИИ очень помог, долго не могли найти проблему
@dp.callback_query(F.data.startswith("peer_queue_"))
async def peer_select_queue(callback: CallbackQuery, state: FSMContext):
    project_id = int(callback.data.split("_")[-1])
    await state.update_data(project_id=project_id)
    
    my_tasks = await get_my_peer_tasks(callback.from_user.id, project_id)
    if my_tasks:
        text = "📋 Ваши задания на проверку:\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[])
        for t in my_tasks:
            text += f"• Работа #{t['submission'].id} (Команда: {t['submission'].team.name})\n"
            kb.inline_keyboard.append([InlineKeyboardButton(
                text=f"📝 Проверить #{t['submission'].id}",
                callback_data=f"peer_start_review_{t['assignment_id']}"
            )])
        kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="peer_back_mode2")])
        await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()
        return
    
    queue = await get_peer_review_queue(callback.from_user.id, project_id)
    
    if not queue:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"peer_queue_{project_id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="peer_back_mode2")]
        ])
        await callback.message.edit_text(
            "ℹ️ В этом проекте пока нет доступных работ для проверки.\n\n"
            "💡 Возможные причины:\n"
            "• Другие студенты еще не сдали работы\n"
            "• Все работы уже разобраны\n"
            "• Вы находитесь в одной команде с авторами оставшихся работ",
            reply_markup=kb
        )
        await callback.answer()
        return

    text = "📥 Доступные работы:\n(выберите одну, чтобы взять на проверку)\n\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for q in queue:
        text += f"• #{q['id']} | {q['team_name']}\n"
        kb.inline_keyboard.append([InlineKeyboardButton(
            text=f"📥 Взять #{q['id']}", callback_data=f"peer_take_{q['id']}"
        )])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="peer_back_mode2")])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()
#

@dp.callback_query(F.data.startswith("peer_start_review_"))
async def peer_continue_review(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Проверить' из списка 'Мои задания'"""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from api.models import SubmissionAssignment, Submission
    
    assignment_id = int(callback.data.split("_")[-1])
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SubmissionAssignment)
            .where(SubmissionAssignment.id == assignment_id)
            .options(selectinload(SubmissionAssignment.submission).selectinload(Submission.artifacts))
        )
        assign = result.scalar_one_or_none()
        if not assign:
            await callback.answer("❌ Задание не найдено", show_alert=True)
            return
            
        submission_id = assign.submission_id
        project_id = assign.submission.project_id
        sub = assign.submission
        
        await state.update_data(
            assignment_id=assignment_id,
            submission_id=submission_id,
            project_id=project_id
        )
        criteria = await get_project_criteria(project_id)
        await state.update_data(criteria=criteria)

        artifacts_text = "\n".join([f"• [{a.type}] {a.url}" for a in sub.artifacts]) if sub.artifacts else "Нет ссылок/артефактов"
        text = (
            f"📝 **Продолжение проверки работы #{sub.id}**\n\n"
            f"📄 **Контент работы:**\n{sub.content}\n\n"
            f"🔗 **Артефакты/Ссылки:**\n{artifacts_text}\n\n"
            f"👇 *Перейдем к критериям оценки...*"
        )
        await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
        await asyncio.sleep(1.5) # Даем время прочитать
        await _peer_show_next_criterion(callback, state)
        await callback.answer()

@dp.callback_query(F.data.startswith("peer_take_"))
async def peer_take_task(callback: CallbackQuery, state: FSMContext):
    submission_id = int(callback.data.split("_")[-1])
    try:
        task = await take_peer_task(callback.from_user.id, submission_id)
        await state.update_data(
            assignment_id=task["assignment_id"],
            submission_id=task["submission"].id,
            project_id=task["submission"].project_id
        )
        criteria = await get_project_criteria(task["submission"].project_id)
        await state.update_data(criteria=criteria)

        sub = task["submission"]
        artifacts_text = "\n".join([f"• [{a.type}] {a.url}" for a in sub.artifacts]) if sub.artifacts else "Нет ссылок/артефактов"
        text = (
            f"✅ Вы взяли работу #{sub.id} на проверку.\n\n"
            f"📄 **Контент работы:**\n{sub.content}\n\n"
            f"🔗 **Артефакты/Ссылки:**\n{artifacts_text}\n\n"
            f"👇 *Теперь начните оценку по критериям...*"
        )
        await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
        await asyncio.sleep(1.5)
        
        await _peer_show_next_criterion(callback, state)
    except ValueError as e:
        await callback.answer(f"❌ {e}", show_alert=True)


async def peer_start_review_callback(callback: CallbackQuery, state: FSMContext, assignment_id: int):
    """Запускает процесс проверки (показывает критерии)"""
    data = await state.get_data()
    project_id = data.get("project_id")
    criteria = await get_project_criteria(project_id)  

    await state.update_data(assignment_id=assignment_id, criteria=criteria, project_id=project_id)
    await state.set_state(PeerReview.viewing_task)

    crit_text = "\n".join([f"• {c['name']} (макс. {c['max_score']})" for c in criteria])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Начать оценку", callback_data="peer_start_scoring")],
        [InlineKeyboardButton(text="💬 Комментарий", callback_data="peer_write_comment")],
        [InlineKeyboardButton(text="✅ Завершить", callback_data="peer_finalize")]
    ])
    await callback.message.edit_text(f"📝 Начинаем проверку!\n\n📏 Критерии:\n{crit_text}", reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data == "peer_start_scoring")
async def peer_start_scoring(callback: CallbackQuery, state: FSMContext):
    """Хендлер для кнопки 'Начать оценку'"""
    await _peer_show_next_criterion(callback, state)


async def _peer_show_next_criterion(event, state: FSMContext):
    """Универсальная функция показа следующего критерия (для callback и message)"""
    data = await state.get_data()
    criteria = data.get("criteria", [])
    submission_id = data.get("submission_id")
    tg_id = event.from_user.id
    user_data = registered_users.get(tg_id, {})
    db_id = user_data.get('db_id')

    if not criteria or not submission_id or not db_id:
        await _peer_safe_answer(event, "❌ Данные не загружены")
        return

    for c in criteria:
        existing = await get_existing_score(submission_id, c["id"], db_id)
        c["scored"] = existing is not None
        if not c["scored"]:
            await state.update_data(current_criterion=c)
            await state.set_state(PeerReview.scoring_criterion)

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Пропустить", callback_data="peer_skip_criterion")]
            ])
            text = f"⭐ **{c['name']}**\nВведите оценку от 0 до {c['max_score']}:"

            await _peer_safe_edit_or_send(event, text, kb)
            return

    text = "✅ Все критерии оценены!"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Комментарий", callback_data="peer_write_comment")]
    ])
    await _peer_safe_edit_or_send(event, text, kb)


async def _peer_safe_answer(event, text: str):
    """Безопасный ответ для любого типа event"""
    if hasattr(event, 'answer'):
        try:
            await event.answer(text)
        except:
            pass


async def _peer_safe_edit_or_send(event, text: str, reply_markup=None):
    """Редактирует (если callback) или отправляет новое (если message)"""
    try:
        if hasattr(event, 'message') and hasattr(event.message, 'edit_text'):
            await event.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        else:
            await event.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    except Exception:
        try:
            if hasattr(event, 'message'):
                await event.message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
            else:
                await event.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        except:
            pass
    if hasattr(event, 'answer') and hasattr(event, 'message'):
        try:
            await event.answer()
        except:
            pass


@dp.message(PeerReview.scoring_criterion, F.text)
async def peer_save_score(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=student_mode2_kb())
        return

    data = await state.get_data()
    criterion = data.get("current_criterion")
    user_data = registered_users.get(message.from_user.id, {})
    db_id = user_data.get('db_id')

    if not criterion or not db_id:
        await message.answer("❌ Ошибка контекста")
        return

    try:
        score = int(message.text.strip())
        if not (0 <= score <= criterion["max_score"]): raise ValueError
    except ValueError:
        await message.answer(f"❌ Введите число от 0 до {criterion['max_score']}:")
        return

    try:
        await submit_peer_score(data["assignment_id"], criterion["id"], score)

        criteria = data.get("criteria", [])
        for c in criteria:
            if c["id"] == criterion["id"]: c["scored"] = True
        await state.update_data(criteria=criteria)

        await message.answer(f"✅ Оценка {score}/{criterion['max_score']} сохранена!")
        await asyncio.sleep(0.5)

        await _peer_show_next_criterion(message, state)
    except ValueError as e:
        await message.answer(f"❌ {e}")


@dp.callback_query(F.data == "peer_skip_criterion")
async def peer_skip_criterion(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    criterion = data.get("current_criterion")
    assignment_id = data.get("assignment_id")
    
    if not criterion or not assignment_id:
        await callback.answer("❌ Ошибка состояния", show_alert=True)
        return
        
    try:
        await submit_peer_score(assignment_id, criterion["id"], 0)
        
        criteria = data.get("criteria", [])
        for c in criteria:
            if c["id"] == criterion["id"]:
                c["scored"] = True
                c["existing_score"] = 0
                break
        await state.update_data(criteria=criteria)
        
        await callback.answer("⏭️ Пропущено (оценка 0)")
        await _peer_show_next_criterion(callback, state)
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)


@dp.callback_query(F.data == "peer_write_comment")
async def peer_write_comment(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PeerReview.writing_comment)
    await callback.message.edit_text("✍️ Напишите комментарий:")
    await callback.answer()


@dp.message(PeerReview.writing_comment, F.text)
async def peer_save_comment(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=student_mode2_kb()) # Убедитесь, что эта клавиатура существует
        return
    
    data = await state.get_data()
    assignment_id = data.get("assignment_id")
    
    if not assignment_id:
        await message.answer("❌ Ошибка: потеряна привязка к заданию. Начните проверку заново.")
        await state.clear()
        return

    try:
        await submit_peer_comment(assignment_id, message.text.strip())
        await state.update_data(comment_saved=True)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Завершить проверку", callback_data="peer_finalize")],
            [InlineKeyboardButton(text="✏️ Исправить", callback_data="peer_write_comment")]
        ])
        await message.answer("✅ Комментарий сохранён!", reply_markup=kb)
    except Exception as e:
        await message.answer(f"❌ Ошибка сохранения: {e}")


@dp.callback_query(F.data == "peer_finalize")
async def peer_finalize(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    criteria = data.get("criteria", [])
    assignment_id = data.get("assignment_id")
    
    if not assignment_id:
        await callback.answer("❌ Ошибка: задание не найдено", show_alert=True)
        return
    
    if not all(c.get("scored", False) for c in criteria):
        await callback.answer("❌ Оцените все критерии перед завершением!", show_alert=True)
        return
    
    try:
        result = await finalize_student_peer_review(assignment_id)
        
        text = "✅ Проверка успешно завершена!\n"
        if result.get("final_mark") is not None:
            text += f"⭐ Средний балл работы обновлён: **{result['final_mark']}**\n"
        else:
            text += "⭐ Ваш вклад в итоговую оценку учтён.\n"
            
        await callback.message.edit_text(text, parse_mode="Markdown")
        await state.clear()
        
    except ValueError as e:
        await callback.answer(f"❌ {e}", show_alert=True)
    except Exception as e:
        logging.error(f"Peer finalize error: {e}")
        await callback.answer("❌ Ошибка при завершении проверки", show_alert=True)


@dp.callback_query(F.data == "peer_back_mode2")
async def peer_back_mode2(callback: CallbackQuery):
    await callback.message.edit_text("Режим 2: выберите действие", reply_markup=student_mode2_kb())
    await callback.answer()


@dp.message(F.text == "📊 Статус работы")
async def peer_show_status(message: Message):
    await student_show_my_results_menu(message)


# ==================== ЗАПУСК ====================
async def main():
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
