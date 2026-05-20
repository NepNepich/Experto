--команды
INSERT INTO
    teams (name)
VALUES ('Команда А'),
    ('Команда Б'),
    ('Соло-разработчики');

--юзеры
INSERT INTO
    users (
        name,
        email,
        code,
        role,
        team_id
    )
VALUES (
        'Иван Организатор',
        'org@urfu.ru',
        'ORG-111',
        'org',
        NULL
    ),
    (
        'Анна Студент',
        'beta@urfu.ru',
        'STU-222',
        'student',
        1
    ),
    (
        'Таня Студент',
        'student@urfu.ru',
        'STU-333',
        'student',
        2
    );

-- Проекты
INSERT INTO
    projects (name, artifact, mode, team_id)
VALUES (
        'Мобильное приложение',
        'https://gitlab.com/app-v1',
        1,
        1
    ),
    (
        'Веб-дашборд аналитики',
        'https://gitlab.com/web-v2',
        1,
        2
    );

-- связи проектов и ролей (проект 1, роли разраба и дизайнера)
INSERT INTO
    project_roles (project_id, role_id)
VALUES (1, 2),
    (1, 5);

--комменты
INSERT INTO
    project_comments (
        project_id,
        commentator_id,
        comment
    )
VALUES (
        1,
        2,
        'Отличная архитектура, но нужно добавить обработку ошибок в API и логирование.'
    );

--критерии
INSERT INTO
    project_criteria (
        project_id,
        name,
        max_score,
        sort_order
    )
VALUES (1, 'Качество кода', 10, 1),
    (1, 'UI/UX дизайн', 10, 2),
    (1, 'Стабильность', 5, 3);

INSERT INTO
    project_criteria (
        project_id,
        name,
        max_score,
        sort_order
    )
VALUES (2, 'Архитектура', 10, 1),
    (2, 'Документация', 5, 2),
    (2, 'Презентация', 5, 3);

--оценки по критериям
INSERT INTO
    project_criterion_scores (
        project_id,
        criterion_id,
        expert_id,
        score
    )
VALUES (1, 1, 2, 8),
    (1, 2, 2, 9),
    (1, 3, 2, 4);