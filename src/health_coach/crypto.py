"""Encryption at rest for OAuth tokens (Fernet, key from HC_TOKEN_KEY)."""

from cryptography.fernet import Fernet, InvalidToken

from health_coach.config import Settings, get_settings


class TokenKeyError(RuntimeError):
    pass


def _fernet(settings: Settings | None = None) -> Fernet:
    settings = settings or get_settings()
    if settings.token_key is None:
        raise TokenKeyError(
            "HC_TOKEN_KEY is not set; create one with `python -c 'from cryptography.fernet "
            "import Fernet; print(Fernet.generate_key().decode())'`"
        )
    return Fernet(settings.token_key.get_secret_value().encode())


def encrypt(value: str, settings: Settings | None = None) -> bytes:
    return _fernet(settings).encrypt(value.encode())


def decrypt(value: bytes, settings: Settings | None = None) -> str:
    try:
        return _fernet(settings).decrypt(value).decode()
    except InvalidToken as exc:
        raise TokenKeyError("stored token cannot be decrypted with HC_TOKEN_KEY") from exc
