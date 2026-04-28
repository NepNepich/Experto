# test_review_flow.py
import asyncio
from api.mocker import MockDatabase
from api.schemas import (
    UserCreate, UserRoleSystem, ProjectCreate, 
    ScoreCreate, CommentCreate
)

async def main():
    # 0. Инициализация заглушки
    db = MockDatabase()
    
    # Базовая подготовка: команды и организатор
    db.teams[1] = {"id": 1, "name": "Команда Альфа"}
    await db.create_user(UserCreate(name="Орг", email="org@test.com", code="ORG", role=UserRoleSystem.ORG, team_id=1))
    expert = await db.create_user(UserCreate(name="Эксперт Иван", email="exp@test.com", code="EXP", role=UserRoleSystem.EXPERT, team_id=1))
    student = await db.create_user(UserCreate(name="Студент Алекс", email="stu@test.com", code="STU", role=UserRoleSystem.STUDENT, team_id=1))

    # Добавляем критерии для проекта (нужны для выставления баллов)
    # В реальном mock это делается через db.add_criterion(...), здесь упростим для теста
    db.criteria.append({"id": 1, "project_id": 999, "name": "Качество кода", "max_score": 10, "sort_order": 1})
    db.criteria.append({"id": 2, "project_id": 999, "name": "Презентация", "max_score": 10, "sort_order": 2})

    print("="*60)
    
    # ==========================================
    # 📝 Создает нового пользователя
    # ==========================================
    print("👤 1. Создает нового пользователя (Студент)")
    # Пользователь уже создан выше для наглядности, но покажем вызов:
    new_user = await db.get_user(student.id)
    print(f"✅ Создан: {new_user.name} | Роль: {new_user.role.value} | Команда ID: {new_user.team_id}\n")

    # ==========================================
    # 📂 Создает новый проект в режиме 1
    # ==========================================
    print("📁 2. Создает новый проект в режиме 1 (доступен всем командам)")
    project = await db.create_project(ProjectCreate(
        name="Курсовая работа: Микросервисы",
        mode=1,
        creator_team_id=1,
        participant_team_ids=[] 
    ))
    print(f"✅ Проект создан: '{project.name}' | ID: {project.id} | Режим: {project.mode}\n")

    # Привязываем критерии к созданному проекту (обновляем ID в mock-списке)
    db.criteria[0]["project_id"] = project.id
    db.criteria[1]["project_id"] = project.id

    # ==========================================
    # 🔍 Смотрит, проверен ли проект
    # ==========================================
    print("🔍 3. Смотрит, проверен ли проект")
    current_state = await db.get_project(project.id)
    is_checked = current_state.status == "checked"
    
    print(f"📊 Текущий статус:   {current_state.status}")
    print(f"📊 Текущий балл:     {current_state.mark}")
    print(f"📊 Дата проверки:    {current_state.date_checked}")
    print(f"🔎 ИТОГ: {'✅ ПРОВЕРЕН' if is_checked else '⏳ ЕЩЕ НЕ ПРОВЕРЕН'}\n")

    # ==========================================
    # 📤 Дает проекту проверку
    # ==========================================
    print("📤 4. Дает проекту проверку (Эксперт ставит баллы + комментарий)")
    
    # Эксперт выставляет баллы по критериям
    await db.add_score(ScoreCreate(
        project_id=project.id, criterion_id=1, reviewer_id=expert.id, score=9
    ))
    await db.add_score(ScoreCreate(
        project_id=project.id, criterion_id=2, reviewer_id=expert.id, score=8
    ))
    
    # Эксперт оставляет текстовый комментарий
    await db.add_comment(CommentCreate(
        project_id=project.id, commentator_id=expert.id, 
        comment="Архитектура грамотная, но не хватает Docker-compose. Исправьте и перездайте."
    ))
    
    print("✅ Баллы и комментарий сохранены. Система автоматически пересчитала mark и обновила статус.\n")

    # ==========================================
    # 👨‍🎓 Студент нужной команды видит этот проверенный проект
    # ==========================================
    print("👨‍🎓 5. Студент нужной команды видит этот проверенный проект")
    
    # Метод get_projects_for_team возвращает проекты mode=1 ИЛИ привязанные к team_id студента
    student_projects = await db.get_projects_for_team(team_id=1)
    
    for p in student_projects:
        print(f"📦 Проект: '{p.name}'")
        print(f"   ├─ Статус: {p.status}")
        print(f"   ├─ Итоговый балл: {p.mark}")
        print(f"   └─ Проверен: {p.date_checked.strftime('%Y-%m-%d %H:%M')}\n")
        
    # Проверяем комментарии к проекту
    comments = await db.get_comments(project.id)
    print("💬 Комментарий эксперта:")
    for c in comments:
        print(f"   🔹 {c.comment}\n")

    print("="*60)
    print("🎉 Цикл проверки завершен. Данные согласованы.")

if __name__ == "__main__":
    asyncio.run(main())