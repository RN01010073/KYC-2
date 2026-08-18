# Encryption & Security Setup Guide

This document describes the encryption implementation in VerifyZ, how to set it up, and how it protects your data.

## Overview

VerifyZ now implements **field-level** and **file-level encryption** using Fernet (symmetric encryption) from the `cryptography` library. This ensures that:

- **PII data** (names, DOBs, addresses, mobile numbers, emails, ID numbers) is encrypted at rest in the database
- **OAuth tokens** (DigiLocker access tokens and ID tokens) are encrypted at rest
- **Uploaded files** (ID proofs, selfies, address proofs) are encrypted on disk
- **Debug endpoint** (`/debug/applications`) requires password authentication

---

## Setup Instructions

### 1. Generate an Encryption Key

First, generate a secure encryption key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

This will output something like:
```
eHpzdVhF5XVQvLpYUZvWVfMp3_pX5VRx1234567890=
```

### 2. Update Your `.env` File

Add the encryption key and debug credentials to your `.env` file:

```env
# Encryption
ENCRYPTION_KEY=eHpzdVhF5XVQvLpYUZvWVfMp3_pX5VRx1234567890=

# Debug endpoint authentication
DEBUG_USERNAME=admin
DEBUG_PASSWORD=your_super_strong_password_here
```

**IMPORTANT:**
- Never commit `.env` to version control (it's in `.gitignore`)
- Keep the encryption key secret and back it up securely
- Use a strong password for `DEBUG_PASSWORD` (minimum 16 characters recommended)

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

The `cryptography` library has been added to `requirements.txt`.

### 4. Database Migration (Existing Data)

If you have existing unencrypted data:

**Option A: Start Fresh** (Recommended for development)
```bash
# Drop and recreate the database
# Data will be encrypted on new inserts
```

**Option B: Migrate Existing Data**
```python
# Python script to re-encrypt existing data
from database import SessionLocal
from models import PendingKYCSession, KYCApplication
from encryption import encrypt_value, decrypt_value

db = SessionLocal()

# For existing unencrypted data, the system will handle it gracefully:
# - When reading encrypted columns, if decryption fails, the original value is returned
# - New writes will be encrypted
```

---

## How Encryption Works

### Field-Level Encryption

**Encrypted Columns in `PendingKYCSession`:**
- `full_name`, `dob`, `mobile`, `email`, `alternate_contact`
- Address fields: `perm_address_line1`, `perm_address_line2`, `perm_pin`, `curr_address_line1`, `curr_address_line2`, `curr_pin`
- Identity data: `id_number`, `aadhaar_linked_mobile`
- Financial info: `annual_income`

**Encrypted Columns in `KYCApplication`:**
- All form data fields (as above)
- DigiLocker tokens: `digilocker_access_token`, `digilocker_id_token`
- DigiLocker extracted data: `digilocker_name`, `digilocker_dob`
- OCR data: `ocr_name`, `ocr_dob`, `ocr_aadhaar`, `ocr_pan`, `ocr_dl`, `ocr_address`

**How it works:**
1. When you write: SQLAlchemy calls `EncryptedString.process_bind_param()` → data is encrypted → stored in DB as encrypted bytes
2. When you read: SQLAlchemy calls `EncryptedString.process_result_value()` → data is decrypted → returned as plaintext to Python code

**Backward Compatibility:**
- If decryption fails (e.g., corrupted data), the encrypted value is returned as-is
- This allows gradual migration from unencrypted to encrypted data

### File-Level Encryption

**How it works:**
1. When uploading: `storage.save_upload()` → reads file → encrypts contents → writes encrypted bytes to disk
2. When retrieving: `storage.read_upload()` → reads encrypted bytes → decrypts → returns plaintext bytes

**Location:** `static/uploads/` (configurable via `UPLOAD_DIR` env var)

All uploaded files (ID proofs, selfies, address proofs, income proofs, signatures) are encrypted before being saved to disk.

### Token Encryption

DigiLocker OAuth tokens are stored encrypted in the database:
- `digilocker_access_token`: Short-lived token used to fetch eAadhaar XML
- `digilocker_id_token`: JWT containing identity claims (automatically decrypted when needed)

---

## Admin Debug Endpoint

### Access

The `/debug/applications` endpoint displays all KYC applications with fully decrypted data.

**Protection:** HTTP Basic Authentication

```bash
# Access via curl:
curl -u admin:your_super_strong_password_here http://localhost:8000/debug/applications

# Access via browser:
# Visit http://localhost:8000/debug/applications
# Enter username: admin
# Enter password: your_super_strong_password_here
```

**Features:**
- Shows all KYC applications in a formatted table
- Displays decrypted PII, tokens, and OCR data
- Shows full decoded DigiLocker ID token claims
- Requires correct username + password
- Returns 401 Unauthorized if credentials are wrong

### Security Notes

- The endpoint displays sensitive data, so credentials must be strong
- Consider disabling in production (comment out the route) or using a VPN
- Credentials are transmitted in Basic Auth (use HTTPS in production)
- Add logging/auditing if needed for compliance

---

## Security Best Practices

### ✅ What's Protected

- PII data at rest in the database
- OAuth tokens that could be used to access user data
- Uploaded documents on disk
- Admin debug endpoint with password protection

### ⚠️ What's NOT Protected (yet)

- **Data in transit**: Always use HTTPS in production (set `HTTPS_ONLY` env var)
- **Database backups**: Encrypt backups separately (handled by your DB provider)
- **Encryption key**: Never commit it; rotate keys periodically if possible
- **Admin password**: Use a strong, unique password; store securely
- **Application logs**: Be careful not to log sensitive data

### 🔐 Recommendations

1. **Production HTTPS:** Redirect HTTP to HTTPS
   ```python
   # Add to app.py if in production
   from fastapi.middleware.trustedhost import TrustedHostMiddleware
   app.add_middleware(TrustedHostMiddleware, allowed_hosts=["yourdomain.com"])
   ```

2. **Key Rotation:** Periodically generate a new encryption key
   - Decrypt all data with old key
   - Re-encrypt with new key
   - Update `ENCRYPTION_KEY` env var

3. **Audit Logging:** Log access to debug endpoint
   ```python
   # In app.py, log authenticated requests to /debug/applications
   ```

4. **Database Backups:** Use your database provider's encryption (Supabase, AWS RDS, etc.)

5. **File Storage:** Consider migrating to encrypted cloud storage (Supabase Storage, AWS S3 with KMS)

---

## Troubleshooting

### "ENCRYPTION_KEY is not set" Error

**Problem:** The application won't start.

**Solution:**
1. Generate a key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
2. Add to `.env`: `ENCRYPTION_KEY=<your_key>`
3. Restart the application

### Encrypted Values Can't Be Decrypted

**Problem:** Error like "InvalidToken" when reading data.

**Cause:** 
- Data was encrypted with a different key
- Data is corrupted
- Database contains mixed encrypted/unencrypted values

**Solution:**
1. Check that `ENCRYPTION_KEY` in `.env` is correct
2. If it's wrong, update it to the correct key
3. If the key is lost, you'll need to restore from backup
4. The system has fallback logic: if decryption fails, it returns the encrypted value as-is

### Access Denied to /debug/applications

**Problem:** Getting 401 Unauthorized.

**Cause:** 
- Wrong username or password
- Credentials not set in `.env`

**Solution:**
1. Check `DEBUG_USERNAME` and `DEBUG_PASSWORD` in `.env`
2. Ensure they're correctly set
3. Try with curl: `curl -u admin:password http://localhost:8000/debug/applications`

### Files Not Being Encrypted

**Problem:** Uploaded files appear to be plaintext.

**Cause:**
- Files were uploaded before encryption was implemented
- Encryption key wasn't set during upload

**Solution:**
1. Check that `ENCRYPTION_KEY` is set and consistent
2. New file uploads will be encrypted
3. Consider re-uploading or using a script to encrypt existing files

---

## Testing Encryption Locally

### Test Field Encryption

```python
from encryption import encrypt_value, decrypt_value

# Encrypt
plaintext = "John Doe"
encrypted = encrypt_value(plaintext)
print(f"Encrypted: {encrypted}")

# Decrypt
decrypted = decrypt_value(encrypted)
print(f"Decrypted: {decrypted}")
assert decrypted == plaintext
```

### Test File Encryption

```python
from encryption import encrypt_file_contents, decrypt_file_contents

# Encrypt
original = b"This is a secret document"
encrypted = encrypt_file_contents(original)
print(f"Encrypted: {encrypted[:20]}...")

# Decrypt
decrypted = decrypt_file_contents(encrypted)
print(f"Decrypted: {decrypted}")
assert decrypted == original
```

### Test Debug Endpoint

```bash
# Wrong credentials
curl -u admin:wrongpass http://localhost:8000/debug/applications
# Returns: 401 Unauthorized

# Correct credentials
curl -u admin:your_super_strong_password_here http://localhost:8000/debug/applications
# Returns: HTML page with all KYC applications
```

---

## Performance Considerations

Encryption/decryption adds a small computational overhead:

- **Fernet encryption:** ~1-2ms per 1KB of data
- **Database queries:** Minimal impact (encryption happens at SQLAlchemy layer)
- **File uploads/downloads:** Noticeable for large files (>10MB), but still acceptable

For production with high traffic, consider:
1. **Caching:** Cache decrypted data briefly (with TTL) to avoid re-decrypting on repeated reads
2. **Async processing:** Process encryption/decryption in background tasks for large files
3. **Hardware acceleration:** Use hardware-accelerated encryption if available

---

## Support & Questions

For issues with encryption:
1. Check the troubleshooting section above
2. Review the `.env` file setup
3. Ensure `cryptography` library is installed: `pip install cryptography`
4. Check application logs for error messages

---

**Last Updated:** 2026-08-14