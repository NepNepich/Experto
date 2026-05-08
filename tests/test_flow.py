# tests/test_flow.py
import pytest
from main import app
from database import get_db
from api.mocker import MockDatabase
# 🔹 Глобальный контекст для обмена ID между тестами
_ctx = {}

@pytest.fixture(autouse=True)
def init_mock_db(mock_db):
    """Заранее создаёт команду с ID=1 для тестов"""
    mock_db.teams[1] = {"id": 1, "name": "Test Team"}
    _ctx["team_id"] = 1  # Глобально используем ID=1
    yield
    # Очистка после теста
    mock_db.teams.clear()
    mock_db.users.clear()
    mock_db.projects.clear()
    mock_db._counters = {k: 0 for k in mock_db._counters}
    _ctx.clear()

def test_create_team(client):
    """1. Создаем команду"""
    response = client.post("/api/v1/teams", json={"name": "Test Team"})
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Team"
    assert "id" in data
    _ctx["team_id"] = data["id"]  # 👈 Сохраняем в глобальный контекст

def test_create_user(client):
    """2. Регистрируем пользователя"""
    response = client.post("/api/v1/users", json={
        "name": "Test User",
        "email": "test@example.com",
        "code": "CODE123",
        "telegram_id": 999,
        "role": "expert",
        "team_id": _ctx["team_id"]  # 👈 Берём из контекста
    })
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test@example.com"
    _ctx["user_id"] = data["id"]

def test_create_project_mode_1(client):
    """3. Создаем проект в режиме 1"""
    response = client.post("/api/v1/projects", json={
        "name": "Project Alpha",
        "mode": 1,
        "creator_team_id": 1,
        "participant_team_ids": []
    })
    assert response.status_code == 201, f"Ошибка: {response.json()}"
    data = response.json()
    assert data["name"] == "Project Alpha"
    _ctx["project_id"] = data["id"]

def test_score_updates_mark_and_status(client, mock_db):
    """4. Интеграционный тест оценки"""
    # Подготовка данных, если ещё не созданы
    if "team_id" not in _ctx:
        test_create_team(client)
    if "user_id" not in _ctx:
        test_create_user(client)
    if "project_id" not in _ctx:
        test_create_project_mode_1(client)
    
    # Добавляем критерий в мок
    current_mock = app.dependency_overrides[get_db]()
    current_mock.criteria.append({
        "id": 1, 
        "project_id": _ctx["project_id"], 
        "name": "Code Quality", 
        "max_score": 10, 
        "sort_order": 1
    })

    # Ставим оценку
    score_response = client.post(f"/api/v1/projects/{_ctx['project_id']}/scores", json={
        "project_id": _ctx["project_id"],
        "criterion_id": 1,
        "reviewer_id": _ctx["user_id"],
        "score": 9
    })
    assert score_response.status_code == 200, f"Ошибка: {score_response.json()}"

    # Проверяем результат
    check_response = client.get(f"/api/v1/projects/{_ctx['project_id']}")
    project_data = check_response.json()
    
    assert project_data["status"] == "checked"
    assert project_data["mark"] == 9

def test_add_comment(client):
    """5. Добавляем комментарий"""
    # Убеждаемся, что данные есть
    if "project_id" not in _ctx:
        test_create_project_mode_1(client)
    if "user_id" not in _ctx:
        test_create_user(client)
        
    response = client.post(f"/api/v1/projects/{_ctx['project_id']}/comments", json={
        "project_id": _ctx["project_id"],
        "commentator_id": _ctx["user_id"],
        "comment": "Отличная работа!"
    })
    assert response.status_code == 200, f"Ошибка: {response.json()}"
    
    comments = client.get(f"/api/v1/projects/{_ctx['project_id']}/comments").json()
    assert len(comments) >= 1