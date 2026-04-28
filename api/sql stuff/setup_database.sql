CREATE DATABASE IF NOT EXISTS experto_database CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE experto_database;

CREATE TABLE teams (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(127) NOT NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE user_roles (
    id TINYINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(63) NOT NULL UNIQUE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(127) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    code VARCHAR(255) NOT NULL UNIQUE,
    telegram_id BIGINT UNIQUE,
    role ENUM('org', 'expert', 'student') NOT NULL DEFAULT 'student',
    team_id INT DEFAULT NULL,
    CONSTRAINT fk_users_team FOREIGN KEY (team_id) REFERENCES teams (id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE projects (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL,
    mode TINYINT UNSIGNED NOT NULL,
    team_id INT NOT NULL,
    date_created DATETIME DEFAULT CURRENT_TIMESTAMP,
    date_checked DATETIME DEFAULT NULL,
    mark TINYINT UNSIGNED DEFAULT NULL,
    status ENUM(
        'submitted', -- Отправлено
        'assigned', -- Назначено проверяющему
        'checked' -- Финал
    ) DEFAULT 'submitted',
    CONSTRAINT fk_projects_team FOREIGN KEY (team_id) REFERENCES teams (id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE project_comments (
    id INT PRIMARY KEY AUTO_INCREMENT,
    project_id INT NOT NULL,
    commentator_id INT NOT NULL,
    comment TEXT NOT NULL,
    CONSTRAINT fk_comments_project FOREIGN KEY (project_id) REFERENCES projects (id),
    CONSTRAINT fk_comments_user FOREIGN KEY (commentator_id) REFERENCES users (id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE project_roles (
    project_id INT NOT NULL,
    role_id TINYINT UNSIGNED NOT NULL,
    PRIMARY KEY (project_id, role_id),
    CONSTRAINT fk_pr_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
    CONSTRAINT fk_pr_role FOREIGN KEY (role_id) REFERENCES user_roles (id) ON DELETE RESTRICT
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE project_criteria (
    id INT PRIMARY KEY AUTO_INCREMENT,
    project_id INT NOT NULL,
    name VARCHAR(127) NOT NULL,
    max_score TINYINT UNSIGNED NOT NULL,
    sort_order TINYINT UNSIGNED DEFAULT 0,
    UNIQUE KEY uk_project_criteria_name (project_id, name),
    CONSTRAINT fk_pc_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE project_criterion_scores (
    project_id INT NOT NULL,
    criterion_id INT NOT NULL,
    expert_id INT NOT NULL,
    score TINYINT UNSIGNED NOT NULL,
    PRIMARY KEY (
        project_id,
        criterion_id,
        expert_id
    ),
    CONSTRAINT fk_pcs_criterion FOREIGN KEY (criterion_id) REFERENCES project_criteria (id) ON DELETE CASCADE,
    CONSTRAINT fk_pcs_expert FOREIGN KEY (expert_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE project_artifacts (
    id INT PRIMARY KEY AUTO_INCREMENT,
    project_id INT NOT NULL,
    url VARCHAR(511) NOT NULL,
    type ENUM('link', 'file', 'text') DEFAULT 'link',
    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE project_reviewers (
    id INT PRIMARY KEY AUTO_INCREMENT,
    project_id INT NOT NULL,
    reviewer_id INT NOT NULL,
    role ENUM('expert', 'student') DEFAULT 'expert',
    status ENUM('pending', 'active', 'done') DEFAULT 'pending',
    assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
    FOREIGN KEY (reviewer_id) REFERENCES users (id) ON DELETE CASCADE,
    UNIQUE KEY unique_reviewer_project (project_id, reviewer_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE project_teams (
    project_id INT NOT NULL,
    team_id INT NOT NULL,
    PRIMARY KEY (project_id, team_id),
    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
    FOREIGN KEY (team_id) REFERENCES teams (id) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

INSERT INTO
    user_roles (name)
VALUES ('Team Lead'),
    ('Developer'),
    ('Analytic'),
    ('Game Designer'),
    ('Designer');