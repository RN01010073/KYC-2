"""
Field-level and file-level encryption utilities for PII and sensitive data.

Uses Fernet (symmetric encryption) from the cryptography library.
Encryption key is read from environment variable ENCRYPTION_KEY.

To generate a key:
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    print(key)  # Add this to .env as ENCRYPTION_KEY
"""

import os
from cryptography.fernet import Fernet, InvalidToken

# Load encryption key from environment
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY")

if not ENCRYPTION_KEY:
    raise RuntimeError(
        "ENCRYPTION_KEY is not set. Generate one with:\n"
        "  python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n"
        "Then add it to your .env file as: ENCRYPTION_KEY=<the-key>"
    )

cipher = Fernet(ENCRYPTION_KEY.encode() if isinstance(ENCRYPTION_KEY, str) else ENCRYPTION_KEY)


def encrypt_value(value: str | None) -> str | None:
    """Encrypt a string value. Returns None if input is None or empty."""
    if not value:
        return None
    try:
        encrypted = cipher.encrypt(value.encode())
        return encrypted.decode()
    except Exception as e:
        raise RuntimeError(f"Encryption failed: {e}")


def decrypt_value(encrypted_value: str | None) -> str | None:
    """Decrypt an encrypted string value. Returns None if input is None or empty."""
    if not encrypted_value:
        return None
    try:
        decrypted = cipher.decrypt(encrypted_value.encode())
        return decrypted.decode()
    except InvalidToken:
        # If decryption fails, return the value as-is (for backward compatibility
        # during migration from unencrypted to encrypted data)
        return encrypted_value
    except Exception as e:
        raise RuntimeError(f"Decryption failed: {e}")


def encrypt_file_contents(contents: bytes) -> bytes:
    """Encrypt file contents (bytes). Returns encrypted bytes."""
    try:
        encrypted = cipher.encrypt(contents)
        return encrypted
    except Exception as e:
        raise RuntimeError(f"File encryption failed: {e}")


def decrypt_file_contents(encrypted_contents: bytes) -> bytes:
    """Decrypt file contents (bytes). Returns decrypted bytes."""
    try:
        decrypted = cipher.decrypt(encrypted_contents)
        return decrypted
    except InvalidToken:
        # If decryption fails, return contents as-is (for backward compatibility)
        return encrypted_contents
    except Exception as e:
        raise RuntimeError(f"File decryption failed: {e}")