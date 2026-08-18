#!/usr/bin/env python
"""
Quick setup script to generate encryption key and create .env file for VerifyZ.
Run: python setup_encryption.py
"""

import os
from pathlib import Path
from cryptography.fernet import Fernet


def generate_encryption_key():
    """Generate a new Fernet encryption key."""
    key = Fernet.generate_key().decode()
    return key


def create_env_file():
    """Create .env file with encryption key if it doesn't exist."""
    env_path = Path(".env")
    env_example_path = Path(".env.example")
    
    if env_path.exists():
        print(f"✓ {env_path} already exists. Not overwriting.")
        return
    
    # Generate new encryption key
    encryption_key = generate_encryption_key()
    
    # Generate strong default password (can be changed)
    import secrets
    debug_password = secrets.token_urlsafe(16)
    
    # Create .env content
    env_content = f"""# ═════════════════════════════════════════════════════════════════════════════
# VerifyZ Environment Configuration
# ═════════════════════════════════════════════════════════════════════════════
# IMPORTANT: Never commit this file to git (it's in .gitignore)

# Database Connection
DATABASE_URL=postgresql://user:password@host:port/dbname

# Encryption (KEEP THIS SECRET!)
ENCRYPTION_KEY={encryption_key}

# Debug Endpoint Authentication
DEBUG_USERNAME=admin
DEBUG_PASSWORD={debug_password}

# DigiLocker OAuth2 Credentials (from API Setu dashboard)
DIGILOCKER_CLIENT_ID=your_client_id_here
DIGILOCKER_CLIENT_SECRET=your_client_secret_here
DIGILOCKER_REDIRECT_URI=http://localhost:8000/digilocker/callback

# File Upload Directory (encrypted files stored here)
UPLOAD_DIR=static/uploads

# Server Port
PORT=8000
"""
    
    with open(env_path, "w") as f:
        f.write(env_content)
    
    print(f"✅ Created .env file with encryption key")
    print(f"\n📋 Your credentials:")
    print(f"   Debug Username: admin")
    print(f"   Debug Password: {debug_password}")
    print(f"\n⚠️  IMPORTANT:")
    print(f"   • Save your encryption key and password securely!")
    print(f"   • Never commit .env to git")
    print(f"   • Update DATABASE_URL and DigiLocker credentials")
    print(f"   • Test with: curl -u admin:{debug_password} http://localhost:8000/debug/applications")


def main():
    print("🔐 VerifyZ Encryption Setup")
    print("=" * 60)
    
    print("\n1️⃣  Generating encryption key...")
    key = generate_encryption_key()
    print(f"✓ Encryption key generated (length: {len(key)} chars)")
    print(f"   Key: {key}")
    
    print("\n2️⃣  Creating .env file...")
    create_env_file()
    
    print("\n3️⃣  Next steps:")
    print("   1. Update DATABASE_URL in .env with your PostgreSQL connection")
    print("   2. Update DIGILOCKER_* credentials from API Setu dashboard")
    print("   3. Run: pip install -r requirements.txt")
    print("   4. Run: python app.py")
    print("   5. Visit: http://localhost:8000/")
    
    print("\n📖 For detailed setup instructions, see: ENCRYPTION_SETUP.md")


if __name__ == "__main__":
    main()