import os
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from services.student import submit_peer_comment
from services.whisper_service import transcribe_audio

peer_voice_router = Router()
logger = logging.getLogger(__name__)

@peer_voice_router.message(F.voice)
async def peer_handle_voice(message: Message, bot, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "PeerReview:writing_comment":
        logger.warning(f"Голосовое получено в неверном состоянии: {current_state}")
        return

    status_msg = await message.reply("🎙 Принято! Расшифровываю голосовой комментарий...")
    os.makedirs("temp_voices", exist_ok=True)
    file_path = f"temp_voices/{message.voice.file_id}.ogg"

    try:
        await bot.download(message.voice, destination=file_path)
        text = await transcribe_audio(file_path)
        
        if not text or not text.strip():
            raise ValueError("Расшифровка пуста или не удалась")

        await state.update_data(transcribed_text=text.strip())
        await state.set_state("PeerReview:writing_comment")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, отправить", callback_data="peer_voice_approve")],
            [InlineKeyboardButton(text="❌ Перезаписать", callback_data="peer_write_comment")]
        ])
        
        await status_msg.edit_text(
            f"📝 **Расшифровка:**\n\n_{text.strip()}_\n\nСохраняем?",
            reply_markup=kb, 
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Whisper error (peer): {e}")
        await status_msg.edit_text("❌ Ошибка при расшифровке. Попробуйте отправить текст или запишите чётче.")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@peer_voice_router.callback_query(F.data == "peer_voice_approve")
async def peer_approve_voice(callback: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "PeerReview:writing_comment":
        await callback.answer("Это действие уже недоступно", show_alert=False)
        return
        
    data = await state.get_data()
    text = data.get("transcribed_text")
    assignment_id = data.get("assignment_id")

    if not assignment_id or not text:
        await callback.answer("❌ Ошибка: данные потеряны", show_alert=True)
        return

    try:
        result = await submit_peer_comment(
            assignment_id=assignment_id,
            comment_text=text
        )
        
        await state.update_data(comment_id=result["id"], comment_saved=True)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Завершить проверку", callback_data="peer_finalize")],
            [InlineKeyboardButton(text="✏️ Исправить", callback_data="peer_write_comment")]
        ])

        await callback.message.edit_text(
            f"✅ Голосовой комментарий расшифрован и сохранён:\n\n_{text[:200]}{'...' if len(text)>200 else ''}_",
            reply_markup=kb, parse_mode="Markdown"
        )
        await callback.answer()
        
    except ValueError as e:
        await callback.answer(f"❌ {e}", show_alert=True)
    except Exception as e:
        logger.exception("Unexpected error in peer_voice_approve")
        await callback.answer("❌ Ошибка при сохранении", show_alert=True)