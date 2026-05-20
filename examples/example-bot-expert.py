import requests
import sys

BASE_URL = "http://localhost:8000"
EXPERT_EMAIL = "exp2@test.com"  # Email эксперта из seed.py

def handle_error(resp, step_name):
    """Вспомогательная функция для красивого вывода ошибок"""
    try:
        detail = resp.json()
    except:
        detail = resp.text[:300]
    print(f"❌ Ошибка на шаге '{step_name}': {resp.status_code}")
    print(f"📄 Ответ сервера: {detail}")
    sys.exit(1)

print("🔐 Авторизация эксперта (без Telegram ID)...")
# 👇 Используем /auth/web вместо /auth/bot — telegram_id не нужен
auth = requests.post(f"{BASE_URL}/auth/web", json={"email": EXPERT_EMAIL})
if auth.status_code != 200:
    handle_error(auth, "auth")
user_id = auth.json()["user_id"]
print(f"✅ Эксперт вошёл (user_id={user_id})")

# 2. Активные проекты (фильтруем только Режим 1 для эксперта)
print("📦 Загрузка активных проектов (Режим 1)...")
projects_resp = requests.get(f"{BASE_URL}/projects/active")
if projects_resp.status_code != 200:
    handle_error(projects_resp, "get_active_projects")
projects = projects_resp.json()

# Фильтруем: эксперту нужны только проекты с mode=1
mode1_projects = [p for p in projects if p.get("mode") == 1]
if not mode1_projects:
    print("⚠️ Нет активных проектов Режима 1. Создайте проект с mode=1 и дедлайном в будущем.")
    exit()

pid = mode1_projects[0]["id"]
print(f"🎯 Выбран проект: {mode1_projects[0]['name']} (id={pid}, deadline={mode1_projects[0]['deadline']})")

# 3. Загрузка критериев
print("📏 Загрузка критериев...")
criteria_resp = requests.get(f"{BASE_URL}/scoring/criteria/project/{pid}")
if criteria_resp.status_code != 200:
    handle_error(criteria_resp, "get_criteria")
criteria = criteria_resp.json()

if not criteria:
    print("⚠️ У проекта нет критериев. Добавьте их через организатора.")
    exit()
print(f"✅ Найдено критериев: {len(criteria)}")

# 4. Взять новую работу (или продолжить существующую)
print("📥 Поиск доступной работы...")
task_resp = requests.get(f"{BASE_URL}/assignments/project/{pid}/next", params={"reviewer_id": user_id})

if task_resp.status_code == 404:
    print("ℹ️ Все работы в этом проекте уже проверены или выданы другим экспертам.")
    # Показываем историю проверок для контекста
    history_resp = requests.get(f"{BASE_URL}/assignments/history", params={"reviewer_id": user_id, "project_id": pid})
    if history_resp.status_code == 200:
        history = history_resp.json()
        if history:
            print(f"📚 Вы уже проверили работ: {len(history)}")
    exit()

if task_resp.status_code != 200:
    handle_error(task_resp, "get_next_task")

task = task_resp.json()
sub_id = task["submission"]["id"]
assign_id = task["assignment_id"]
print(f"✅ Взял работу #{sub_id} (assignment_id={assign_id})")

# 5. Выставить оценки (черновик)
print("✍️  Выставляю оценки...")
for c in criteria:
    score_data = {
        "submission_id": sub_id,
        "criterion_id": c["id"],
        "expert_id": user_id,
        "score": max(1, c["max_score"] - 1)  # Ставим на 1 балл меньше максимума для теста
    }
    score_resp = requests.post(f"{BASE_URL}/scoring/scores", json=score_data)
    # 201 = создано, 409 = уже существует (нормально при повторном запуске)
    if score_resp.status_code not in (201, 409):
        print(f"⚠️ Предупреждение по оценке: {score_resp.json()}")
print("✅ Оценки сохранены/обновлены")

# 6. Добавить комментарий
print("💬 Добавляю комментарий...")
comment_resp = requests.post(f"{BASE_URL}/scoring/comments", json={
    "submission_id": sub_id,
    "author_id": user_id,
    "comment": "Сильный бэкенд, фронт требует доработки. Рекомендую добавить больше тестов."
})
if comment_resp.status_code not in (201, 409):  # 409 может быть, если комментарий уже есть
    handle_error(comment_resp, "create_comment")
print("✅ Комментарий сохранён")

# 7. Финализация: отправить работу
print("🚀 Финализация проверки...")
final_resp = requests.post(f"{BASE_URL}/assignments/{assign_id}/finalize")
if final_resp.status_code != 200:
    handle_error(final_resp, "finalize")

final = final_resp.json()
print(f"🎉 Работа отправлена!")
next_id = final.get("next_submission_id")
if next_id:
    print(f"📥 Следующая работа уже ждёт: #{next_id}")
else:
    print("✅ Все доступные работы в проекте проверены.")

# 8. (Опционально) Показать статистику
print("\n📊 Статистика эксперта:")
history_resp = requests.get(f"{BASE_URL}/assignments/history", params={"reviewer_id": user_id, "project_id": pid})
if history_resp.status_code == 200:
    history = history_resp.json()
    print(f"   Проверено работ в проекте: {len(history)}")