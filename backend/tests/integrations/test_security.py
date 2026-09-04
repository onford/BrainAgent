import pytest

from app.core.exceptions import CredentialConfigurationError
from app.integrations.security import CredentialCipher


TEST_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


def test_credentials_round_trip_with_authenticated_encryption() -> None:
    cipher = CredentialCipher(TEST_KEY)
    credentials = {"token": "github-secret", "email": "user@example.org"}

    encrypted = cipher.encrypt(credentials)

    assert "github-secret" not in encrypted
    assert "user@example.org" not in encrypted
    assert cipher.decrypt(encrypted) == credentials


def test_missing_or_wrong_key_fails_safely() -> None:
    with pytest.raises(CredentialConfigurationError):
        CredentialCipher(None)
    with pytest.raises(CredentialConfigurationError):
        CredentialCipher("not-a-fernet-key")
