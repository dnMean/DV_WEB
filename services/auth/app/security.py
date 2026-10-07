import bcrypt

from app.config import get_settings


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=get_settings().BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode(), salt).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False
