import asyncio
from faster_whisper import WhisperModel

# Загружаем модель один раз при запуске
model = WhisperModel("base", device="cpu", compute_type="int8")

def _transcribe_sync(file_path: str) -> str:
    # Эта функция принимает РОВНО 1 аргумент — путь к файлу
    segments, info = model.transcribe(file_path, beam_size=5, language="ru")
    return " ".join([segment.text for segment in segments])

async def transcribe_audio(file_path: str) -> str:
    # Отправляем синхронную функцию в отдельный поток, чтобы бот не вис
    return await asyncio.to_thread(_transcribe_sync, file_path)