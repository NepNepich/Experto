CREATE DATABASE experto_database CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE experto_database;

CREATE TABLE teams (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(127) NOT NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(127) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    code VARCHAR(255) NOT NULL UNIQUE,
    telegram_id BIGINT UNIQUE,
    academic_role ENUM('org', 'expert', 'student') NOT NULL DEFAULT 'student',
    team_role ENUM(
        'team_lead',
        'developer',
        'analytic',
        'game_designer',
        'designer'
    ) DEFAULT NULL,
    team_id INT DEFAULT NULL,
    CONSTRAINT fk_users_team FOREIGN KEY (team_id) REFERENCES teams (id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE projects (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL,
    mode TINYINT UNSIGNED NOT NULL,
    date_created DATETIME DEFAULT CURRENT_TIMESTAMP,
    deadline DATETIME NOT NULL,
    status ENUM(
        'submitted',
        'assigned',
        'checked'
    ) DEFAULT 'submitted'
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

CREATE TABLE project_teams (
    project_id INT NOT NULL,
    team_id INT NOT NULL,
    PRIMARY KEY (project_id, team_id),
    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
    FOREIGN KEY (team_id) REFERENCES teams (id) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE submissions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    project_id INT NOT NULL,
    team_id INT NOT NULL,
    content TEXT NOT NULL,
    mark TINYINT UNSIGNED DEFAULT NULL, -- Итоговый балл (заполняется ТОЛЬКО в Режиме 1)
    status ENUM(
        'unchecked',
        'checking',
        'checked'
    ) DEFAULT 'unchecked',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    checked_at DATETIME DEFAULT NULL,
    UNIQUE KEY uk_project_team (project_id, team_id),
    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
    FOREIGN KEY (team_id) REFERENCES teams (id) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE submission_artifacts (
    id INT PRIMARY KEY AUTO_INCREMENT,
    submission_id INT NOT NULL,
    url VARCHAR(511) NOT NULL,
    type ENUM('link', 'file', 'text') DEFAULT 'link',
    FOREIGN KEY (submission_id) REFERENCES submissions (id) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE submission_comments (
    id INT PRIMARY KEY AUTO_INCREMENT,
    submission_id INT NOT NULL,
    author_id INT NOT NULL,
    comment TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (submission_id) REFERENCES submissions (id) ON DELETE CASCADE,
    FOREIGN KEY (author_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

-- В Режимн 2 эта таблица игнорируется, баллы не выставляются
CREATE TABLE submission_criterion_scores (
    submission_id INT NOT NULL,
    criterion_id INT NOT NULL,
    expert_id INT NOT NULL,
    score TINYINT UNSIGNED NOT NULL,
    PRIMARY KEY (
        submission_id,
        criterion_id,
        expert_id
    ),
    FOREIGN KEY (submission_id) REFERENCES submissions (id) ON DELETE CASCADE,
    FOREIGN KEY (criterion_id) REFERENCES project_criteria (id) ON DELETE CASCADE,
    FOREIGN KEY (expert_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

CREATE TABLE submission_assignments (
    id INT PRIMARY KEY AUTO_INCREMENT,
    submission_id INT NOT NULL,
    reviewer_id INT NOT NULL,
    status ENUM('pending', 'done') DEFAULT 'pending',
    assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME DEFAULT NULL,
    UNIQUE KEY uk_sub_reviewer (submission_id, reviewer_id),
    FOREIGN KEY (submission_id) REFERENCES submissions (id) ON DELETE CASCADE,
    FOREIGN KEY (reviewer_id) REFERENCES users (id) ON DELETE CASCADE,
    INDEX idx_reviewer_pending (reviewer_id, status)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;