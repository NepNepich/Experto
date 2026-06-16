import requests

BASE_URL = "http://localhost:8000"
TEST_EMAIL = "alice@test.com"

print("🔍 Авторизация студента...")
login_resp = requests.post(f"{BASE_URL}/auth/web", json={"email": TEST_EMAIL})
login_resp.raise_for_status()  # ⚠️ Остановит скрипт при 4xx/5xx
user_id = login_resp.json()["user_id"]
print(f"✅ Вошёл как student (user_id={user_id})")

# === РЕЖИМ 1 ===
print("\n📚 Загрузка работ (Режим 1)...")
params_m1 = {"mode": 1} 
resp_m1 = requests.get(f"{BASE_URL}/submissions/student/{user_id}/list", params=params_m1)
resp_m1.raise_for_status()
list_m1 = resp_m1.json()
print(f"📦 Найдено работ: {len(list_m1)}")

if list_m1:
    sub_id_m1 = list_m1[0]["id"]
    print(f"🔍 Первая работа: {list_m1[0]['project_name']} (status={list_m1[0]['status']})")

    # 👇 Добавь логирование запроса
    detail_url = f"{BASE_URL}/submissions/{sub_id_m1}/detail/mode1?user_id={user_id}"
    print(f"📡 Запрос: GET {detail_url}")
    
    detail_m1_resp = requests.get(detail_url)
    if detail_m1_resp.status_code != 200:
        print(f"❌ Ошибка сервера: {detail_m1_resp.status_code}")
        print(f"📄 Ответ: {detail_m1_resp.text[:500]}")  # Первые 500 символов
        # Не вызывай raise_for_status(), чтобы увидеть ответ
    else:
        detail_m1 = detail_m1_resp.json()
        print(f"📊 Итоговая оценка: {detail_m1.get('total_mark')}")
        print(f"💬 Комментарий эксперта: {detail_m1.get('expert_comment') or 'Нет комментария'}")

# === РЕЖИМ 2 (P2P) ===
print("\n🤝 Загрузка работ (Режим 2 P2P)...")
params_m2 = {"mode": 2}
resp_m2 = requests.get(f"{BASE_URL}/submissions/student/{user_id}/list", params=params_m2)
resp_m2.raise_for_status()
list_m2 = resp_m2.json()
print(f"📦 Найдено работ: {len(list_m2)}")

if list_m2:
    sub_id_m2 = list_m2[0]["id"]
    print(f"🔍 Первая работа: {list_m2[0]['project_name']} (комментариев: {list_m2[0]['comment_count']})")

    detail_m2_resp = requests.get(f"{BASE_URL}/submissions/{sub_id_m2}/detail/mode2", params={"user_id": user_id})
    detail_m2_resp.raise_for_status()
    detail_m2 = detail_m2_resp.json()
    print(f"💬 Отзывы студентов:")
    for c in detail_m2.get("comments", []):
        print(f"  - {c['author_name']} ({c['created_at']}): {c['comment'][:50]}...")