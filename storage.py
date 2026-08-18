"""
Encrypted local-disk file storage for uploaded KYC documents/selfie/signature.

All files are encrypted before being written to disk using Fernet (symmetric encryption).
Files are automatically decrypted when read.

NOTE: On Render's free/starter tiers the filesystem is ephemeral - files
written here disappear on redeploy/restart. This is fine to get the flow
working end-to-end, but before going live, swap to Supabase Storage (or S3)
instead of local disk. The function signature is kept deliberately simple so
that swap is a one-file change.
"""

import os
import re
import uuid

from fastapi import UploadFile

from encryption import decrypt_file_contents, encrypt_file_contents

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "static/uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _safe_ext(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    return ext if re.fullmatch(r"\.[a-z0-9]{1,5}", ext) else ""


async def save_upload(file: UploadFile | None) -> str | None:
    """Save uploaded file with encryption. Returns encrypted file path or None."""
    if file is None or not file.filename:
        return None
    ext = _safe_ext(file.filename)
    name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, name)
    contents = await file.read()
    
    # Encrypt file contents before saving
    encrypted_contents = encrypt_file_contents(contents)
    
    with open(path, "wb") as f:
        f.write(encrypted_contents)
    return path


def read_upload(file_path: str) -> bytes | None:
    """Read and decrypt an uploaded file. Returns decrypted bytes or None if file not found."""
    if not file_path:
        return None
    try:
        with open(file_path, "rb") as f:
            encrypted_contents = f.read()
        # Decrypt file contents after reading
        decrypted_contents = decrypt_file_contents(encrypted_contents)
        return decrypted_contents
    except FileNotFoundError:
        return None
    except Exception as e:
        raise RuntimeError(f"Failed to read file {file_path}: {e}")