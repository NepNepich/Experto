import requests
import sys

BASE_URL = "http://localhost:8000"
STUDENT_EMAIL = "alice@test.com"  # Email студента из seed.py (в команде)

def handle_error(resp, step_name):
    """Вспомогательная функция для красивого вывода ошибок"""
    try:
        detail = resp.json()
    except:
        detail = resp.text[:300]
    print(f"❌ Ошибка на шаге '{step_name}': {resp.status_code}")
    print(f"📄 Ответ сервера: {detail}")
    sys.exit(1)

print("🔐 Авторизация студента (без Telegram ID)...")
# 👇 Используем /auth/web вместо /auth/bot — telegram_id не нужен для MVP
auth = requests.post(f"{BASE_URL}/auth/web", json={"email": STUDENT_EMAIL})
if auth.status_code != 200:
    handle_error(auth, "auth")
user_id = auth.json()["user_id"]
print(f"✅ Студент вошёл (user_id={user_id})")

# 2. Активные проекты (фильтруем только Режим 2 для P2P)
print("📦 Загрузка активных проектов (Режим 2 / P2P)...")
projects_resp = requests.get(f"{BASE_URL}/projects/active")
if projects_resp.status_code != 200:
    handle_error(projects_resp, "get_active_projects")
projects = projects_resp.json()

# Фильтруем: студенту для рецензий нужны только проекты с mode=2
mode2_projects = [p for p in projects if p.get("mode") == 2]
if not mode2_projects:
    print("⚠️ Нет активных проектов Режима 2. Создайте проект с mode=2 и дедлайном в будущем.")
    exit()

pid = mode2_projects[0]["id"]
print(f"🎯 Выбран проект: {mode2_projects[0]['name']} (id={pid}, deadline={mode2_projects[0]['deadline']})")

# 3. Взять работу на проверку (P2P-рецензирование)
print("📥 Поиск работы для рецензии...")
task_resp = requests.get(f"{BASE_URL}/assignments/project/{pid}/next", params={"reviewer_id": user_id})

if task_resp.status_code == 404:
    print("ℹ️ Все работы в этом проекте уже проверены или выданы другим рецензентам.")
    # Показываем историю для контекста
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
print(f"✅ Взял работу #{sub_id} для рецензии (assignment_id={assign_id})")

# 4. Просмотр работы + артефактов
print("👁️  Загружаю контент работы...")
review_resp = requests.get(f"{BASE_URL}/submissions/{sub_id}/review", params={"reviewer_id": user_id})
if review_resp.status_code != 200:
    handle_error(review_resp, "get_review")
review = review_resp.json()

project_id = review['submission']['project_id']
print(f"📄 Работа из проекта #{project_id}")

artifacts = review.get("artifacts", [])
print(f"🔗 Артефактов: {len(artifacts)}")
for art in artifacts:
    print(f"   - {art['type']}: {art['url']}")

# 5. Написать комментарий (черновик)
print("💬 Пишу комментарий...")
comment_resp = requests.post(f"{BASE_URL}/scoring/comments", json={
    "submission_id": sub_id,
    "author_id": user_id,
    "comment": "Интересная идея! Но в коде есть опечатки, рекомендую проверить перед сдачей."
})
# 201 = создано, 409 = уже есть (нормально при повторном запуске)
if comment_resp.status_code not in (201, 409):
    handle_error(comment_resp, "create_comment")
print("✅ Комментарий сохранён")

# 6. (Опционально) Правка комментария до отправки
print("✏️  Обновляю комментарий...")
comment_id = comment_resp.json()["id"]
patch_resp = requests.patch(f"{BASE_URL}/scoring/comments/{comment_id}", json={
    "comment": "Интересная идея! Но в коде есть опечатки, рекомендую проверить перед сдачей. Также добавьте больше тестов."
})
if patch_resp.status_code != 200:
    handle_error(patch_resp, "update_comment")
print("✅ Комментарий обновлён")

# 7. Финализация: отправить рецензию
print("🚀 Отправляю рецензию...")
final_resp = requests.post(f"{BASE_URL}/assignments/{assign_id}/finalize")
if final_resp.status_code != 200:
    handle_error(final_resp, "finalize")

final = final_resp.json()
print(f"🎉 Рецензия отправлена!")
next_id = final.get("next_submission_id")
if next_id:
    print(f"📥 Следующая работа уже ждёт: #{next_id}")
else:
    print("✅ Все доступные работы для рецензии в проекте проверены.")

# 8. (Опционально) Показать статистику
print("\n📊 Статистика студента-рецензента:")
history_resp = requests.get(f"{BASE_URL}/assignments/history", params={"reviewer_id": user_id, "project_id": pid})
if history_resp.status_code == 200:
    history = history_resp.json()
    print(f"   Проверено работ в проекте: {len(history)}")