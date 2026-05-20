# Базовый URL: http://localhost:8000/
# Swagger (авто документация): http://127.0.0.1:8000/docs#/

# в .gitignore и .env.example примеры того, как в будущем работать с токенами, паролями и прочим, что не дожно идти в общий доступ

# для запуска сервера:
uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# чтобы работать с бд
нужно скачать mysql и настроить его (мини гайд https://www.youtube.com/watch?v=hiS_mWZmmI0) ((если что, спрашивайте у иишки))
можно скачать dbeaver, удобен для просмотра содержимого бд и прочего

# не забудьте также скачать нужные библиотеки:

1. Создать виртуальное окружение (рекомендуется)
python -m venv venv

2. Активировать:
Windows
venv\Scripts\activate

Linux
source venv/bin/activate

3. Установить все зависимости
pip install -r requirements.txt

откройте examples и 