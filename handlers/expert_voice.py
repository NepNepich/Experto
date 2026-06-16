import os
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from services.whisper_service import transcribe_audio
from services.expert import submit_expert_comment

voice_router = Router()

@voice_router.message(F.voice)
async def expert_handle_voice(message: Message, bot: Bot, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "ExpertReview:writing_comment":
        return

    status_msg = await message.reply("🎙 Принято! Расшифровываю...")

    os.makedirs("temp_voices", exist_ok=True)
    file_path = f"temp_voices/{message.voice.file_id}.ogg"
    await bot.download(message.voice, destination=file_path)

    try:
        text = await transcribe_audio(file_path)
        await state.update_data(transcribed_text=text)
        await state.set_state("ExpertReview:confirming_voice")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, отправить", callback_data="voice_approve")],
            [InlineKeyboardButton(text="❌ Перезаписать", callback_data="expert_write_comment")]
        ])
        await status_msg.edit_text(
            f"📝 **Расшифровка:**\n\n_{text}_\n\nСохраняем?",
            reply_markup=kb, parse_mode="Markdown"
        )
    except Exception as e:
        await status_msg.edit_text("❌ Ошибка при расшифровке.")
        logging.error(f"Whisper error: {e}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

@voice_router.callback_query(F.data == "voice_approve")
async def expert_approve_voice(callback: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "ExpertReview:confirming_voice":
        logging.warning(f"voice_approve ignored: state={current_state}")
        await callback.answer("Это действие уже недоступно", show_alert=False)
        return

    data = await state.get_data()
    text = data.get("transcribed_text")
    assignment_id = data.get("assignment_id")

    if not assignment_id:
        await callback.answer("❌ Ошибка: задание не найдено", show_alert=True)
        return

    try:
        result = await submit_expert_comment(
            assignment_id=assignment_id,
            comment_text=text
        )
        await state.update_data(comment_id=result["id"])

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Завершить проверку", callback_data="expert_finalize")],
            [InlineKeyboardButton(text="✏️ Исправить", callback_data="expert_write_comment")]
        ])

        await callback.message.edit_text(
            f"✅ Голосовой комментарий расшифрован и сохранён:\n\n{text[:200]}...",
            reply_markup=kb
        )
        await state.set_state("ExpertReview:confirming_review")
        await callback.answer()
    except ValueError as e:
        await callback.answer(f"❌ {e}", show_alert=True)
    except Exception as e:
        logging.exception("Unexpected error in voice_approve")
        await callback.answer("❌ Произошла ошибка при сохранении комментария", show_alert=True)