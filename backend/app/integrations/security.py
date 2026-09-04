import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.exceptions import CredentialConfigurationError


class CredentialCipher:
    """Authenticated encryption for the complete credential document."""

    def __init__(self, key: str | None) -> None:
        if not key or not key.strip():
            raise CredentialConfigurationError(
                "BRAIN_AGENT_CREDENTIAL_ENCRYPTION_KEY is not configured"
            )
        try:
            self._fernet = Fernet(key.strip().encode("ascii"))
        except (ValueError, TypeError, UnicodeEncodeError) as exc:
            raise CredentialConfigurationError(
                "BRAIN_AGENT_CREDENTIAL_ENCRYPTION_KEY must be a Fernet key"
            ) from exc

    def encrypt(self, credentials: dict[str, Any]) -> str:
        payload = json.dumps(
            credentials, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return self._fernet.encrypt(payload).decode("ascii")

    def decrypt(self, token: str) -> dict[str, Any]:
        try:
            value = json.loads(self._fernet.decrypt(token.encode("ascii")))
        except (InvalidToken, ValueError, TypeError, UnicodeEncodeError) as exc:
            raise CredentialConfigurationError(
                "Stored integration credentials cannot be decrypted"
            ) from exc
        if not isinstance(value, dict):
            raise CredentialConfigurationError("Stored credentials have an invalid shape")
        return value
