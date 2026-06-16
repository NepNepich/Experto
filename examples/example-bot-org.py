import requests
from datetime import datetime, timezone, timedelta

BASE_URL = "http://localhost:8000"
ORG_EMAIL = "org1@test.com"  # Email организатора из seed.py

def api_request(method, url, **kwargs):
    """Универсальная обёртка для запросов с обработкой ошибок"""
    try:
        resp = requests.request(method, url, timeout=10, **kwargs)
        if resp.status_code >= 400:
            print(f"❌ Ошибка {resp.status_code}: {resp.text[:200]}")
            return None
        return resp
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error: {e}")
        return None

print("🔐 Авторизация организатора...")
auth_resp = api_request("POST", f"{BASE_URL}/auth/web", json={"email": ORG_EMAIL})
if not auth_resp:
    exit(1)

auth_data = auth_resp.json()
organizer_id = auth_data.get("user_id")
if not organizer_id:
    print(f"❌ Не удалось получить user_id. Ответ: {auth_data}")
    exit(1)
print(f"✅ Организатор вошёл (user_id={organizer_id})")

# === 1. Выдать права эксперта ===
print("\n🎓 Назначаю экспертов...")
emails = ["exp1@test.com", "exp2@test.com"]  # Emails из seed.py
resp = api_request(
    "PATCH",
    f"{BASE_URL}/users/bulk/academic-role?organizer_id={organizer_id}",
    json={"emails": emails, "new_role": "expert"}
)
if resp and resp.status_code == 200:
    result = resp.json()
    print(f"✅ Обновлено: {result.get('updated_count', 0)} пользователей")
else:
    print(f"⚠️ Предупреждение: роли не обновлены (возможно, пользователи уже эксперты)")

# === 2. Создать проект (Режим 1) ===
print("\n📦 Создаю проект (Режим 1)...")
project_data = {
    "name": "AI Hackathon 2024",
    "mode": 1,
    "deadline": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
    # ✅ Критерии: project_id НЕ указывается — сервер подставит его автоматически
    "criteria": [
        {"name": "Архитектура", "max_score": 10, "sort_order": 1},
        {"name": "Код", "max_score": 10, "sort_order": 2},
        {"name": "Презентация", "max_score": 5, "sort_order": 3}
    ]
}
resp = api_request("POST", f"{BASE_URL}/projects/with-criteria", json=project_data)

if resp and resp.status_code == 201:
    project = resp.json()
    pid = project.get("id")
    print(f"✅ Проект создан: {project.get('name')} (ID: {pid})")
    
    # === 3. Проверка: список активных проектов ===
    print("\n🔍 Проверяю список активных проектов...")
    active = api_request("GET", f"{BASE_URL}/projects/active")
    if active and active.status_code == 200:
        active_list = active.json()
        my_proj = [p for p in active_list if p.get("id") == pid]
        if my_proj:
            print(f"✅ Проект виден в списке активных: {my_proj[0]['name']}")
        else:
            print("⚠️ Проект не найден в активных (возможно, дедлайн в прошлом?)")
    
    # === 4. Дашборд проекта ===
    print(f"\n📊 Загружаю дашборд проекта {pid}...")
    dash_resp = api_request("GET", f"{BASE_URL}/projects/{pid}/dashboard")
    if dash_resp and dash_resp.status_code == 200:
        dash = dash_resp.json()
        print(f"📈 Прогресс: {dash.get('checked_submissions', 0)}/{dash.get('total_submissions', 0)} проверено")
        print(f"👥 Экспертов в работе: {len(dash.get('experts', []))}")
    
    # === 5. Экспорт данных ===
    print(f"\n📥 Выгружаю таблицу для проекта {pid}...")
    export_resp = api_request("GET", f"{BASE_URL}/projects/{pid}/export")
    if export_resp and export_resp.status_code == 200:
        export_data = export_resp.json()
        print(f"✅ Выгружено {len(export_data)} записей")
        if export_data:
            first = export_data[0]
            print(f"📋 Пример строки: Команда #{first.get('team_id')} | Балл: {first.get('total_score')}")
else:
    print(f"❌ Ошибка создания проекта")
    if resp:
        print(f"📄 Ответ сервера: {resp.text[:300]}")

print("\n🎉 Скрипт завершён!")