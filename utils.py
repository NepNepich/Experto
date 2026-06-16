import secrets
import string

def generate_user_code(prefix: str = "USR", length: int = 8) -> str:
    """Генерирует уникальный код вида USR-7A3F9B2E"""
    alphabet = string.ascii_uppercase + string.digits
    random_part = ''.join(secrets.choice(alphabet) for _ in range(length))
    return f"{prefix}-{random_part}"