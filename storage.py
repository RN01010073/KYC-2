"""
Minimal local-disk file storage for uploaded KYC documents/selfie/signature.

NOTE: On Render's free/starter tiers the filesystem is ephemeral - files
written here disappear on redeploy/restart. This is fine to get the flow
working end-to-end, but before going live, swap `save_upload` to write to
Supabase Storage (or S3) instead of local disk. The function signature is
kept deliberately simple so that swap is a one-file change.
"""

import os
import re
import uuid

from fastapi import UploadFile

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "static/uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _safe_ext(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    return ext if re.fullmatch(r"\.[a-z0-9]{1,5}", ext) else ""


async def save_upload(file: UploadFile | None) -> str | None:
    if file is None or not file.filename:
        return None
    ext = _safe_ext(file.filename)
    name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, name)
    contents = await file.read()
    with open(path, "wb") as f:
        f.write(contents)
    return path