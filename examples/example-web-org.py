import requests
import csv
from datetime import datetime

BASE_URL = "http://localhost:8000"
TEST_EMAIL = "org2@test.com"

print("🔍 Пытаюсь войти в систему...")
# 1. Авторизация
login_resp = requests.post(f"{BASE_URL}/auth/web", json={"email": TEST_EMAIL})

if login_resp.status_code != 200:
    print(f"❌ Ошибка входа: {login_resp.status_code}")
    print(f"📄 Ответ сервера: {login_resp.json()}")
    print("💡 Совет: сначала создай пользователя через POST /users/")
    exit(1)

login = login_resp.json()
user_id = login["user_id"]
print(f"✅ Организатор вошёл (user_id={user_id}, роль={login['academic_role']})")

# 2. Список миникарточек
print("📦 Загружаю список проектов...")
projects_resp = requests.get(f"{BASE_URL}/projects/", params={"skip": 0, "limit": 16})
projects_resp.raise_for_status()
projects = projects_resp.json()

if not projects:
    print("⚠️ Проектов в базе нет. Создай их через POST /projects/")
    exit(0)

project = projects[1]
pid = project["id"]
print(f"🎯 Работаем с проектом: {project['name']} (id={pid})")

# 3. Дашборд (прогресс)
dash = requests.get(f"{BASE_URL}/projects/{pid}/dashboard").json()
print(f"📊 Прогресс: {dash['checked_submissions']}/{dash['total_submissions']} проверено")

# 4. Статус проекта
status_resp = requests.get(f"{BASE_URL}/projects/{pid}").json()
print(f"🟢 Статус: {status_resp['status']} | Дедлайн: {status_resp['deadline']}")

# 5. Выгрузка таблицы в CSV
export_data = requests.get(f"{BASE_URL}/projects/{pid}/export").json()
csv_filename = f"project_{pid}_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

with open(csv_filename, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["team_id", "team_name", "total_score", "comment", "expert_name", "check_date"])
    writer.writeheader()
    writer.writerows(export_data)

print(f"📥 Таблица выгружена: {csv_filename} ({len(export_data)} строк)")