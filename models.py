import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, TypeDecorator

from database import Base
from encryption import decrypt_value, encrypt_value


class EncryptedString(TypeDecorator):
    """
    SQLAlchemy type decorator for encrypted string columns.
    Automatically encrypts on insert/update and decrypts on retrieval.
    """
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        """Encrypt data before writing to database."""
        if value is not None:
            return encrypt_value(value)
        return value

    def process_result_value(self, value, dialect):
        """Decrypt data after reading from database."""
        if value is not None:
            return decrypt_value(value)
        return value


def _uuid():
    return str(uuid.uuid4())


class PendingKYCSession(Base):
    """
    Holds submitted eKYC form data + PKCE verifier for the duration of
    the DigiLocker OAuth redirect round-trip. The user's browser only
    carries an opaque `state` token - sensitive data lives safely on server.
    """
    __tablename__ = "pending_kyc_sessions"

    id = Column(String, primary_key=True, default=_uuid)
    state = Column(String, unique=True, index=True, nullable=False)
    code_verifier = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    kyc_source = Column(String, default="eKYC")

    # Form fields captured on /submit-ekyc before DigiLocker redirect
    full_name = Column(EncryptedString)
    dob = Column(EncryptedString)
    nationality = Column(String, default="Indian")
    gender = Column(String)

    mobile = Column(EncryptedString)
    email = Column(EncryptedString)

    # Permanent Address
    perm_address_line1 = Column(EncryptedString)
    perm_address_line2 = Column(EncryptedString)
    perm_city = Column(String)
    perm_state = Column(String)
    perm_pin = Column(EncryptedString)
    perm_country = Column(String, default="India")

    # Current Address
    same_address = Column(Boolean, default=True)
    curr_address_line1 = Column(EncryptedString)
    curr_address_line2 = Column(EncryptedString)
    curr_city = Column(String)
    curr_state = Column(String)
    curr_pin = Column(EncryptedString)
    curr_country = Column(String, default="India")

    id_type = Column(String)
    id_number = Column(EncryptedString)

    # AML / Profile fields
    occupation = Column(String)
    annual_income = Column(EncryptedString)
    source_of_funds = Column(String)
    pep_status = Column(String, default="No")

    # Legacy optional fields (preserved for Supabase schema compatibility)
    marital_status = Column(String, nullable=True)
    alternate_contact = Column(EncryptedString, nullable=True)
    aadhaar_linked_mobile = Column(EncryptedString, nullable=True)
    dl_expiry_date = Column(String, nullable=True)
    account_purpose = Column(Text, nullable=True)
    income_proof_path = Column(String, nullable=True)

    # File paths on disk
    id_proof_front_path = Column(String)
    id_proof_back_path = Column(String)
    address_proof_path = Column(String)           # Permanent address proof (e.g. Aadhaar back)
    current_address_proof_path = Column(String)   # Utility bill / bank statement if different
    selfie_path = Column(String)                  # Live webcam selfie
    signature_path = Column(String)               # Digital signature capture


class KYCApplication(Base):
    """
    Final, completed KYC record created once DigiLocker callback has
    completed and biometric face match + address cross-checks are computed.
    Rendered on /results/{id}.
    """
    __tablename__ = "kyc_applications"

    id = Column(String, primary_key=True, default=_uuid)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    kyc_source = Column(String, default="eKYC")
    status = Column(String, default="review")     # "approved" / "review" / "rejected"

    # Applicant profile
    full_name = Column(EncryptedString)
    dob = Column(EncryptedString)
    nationality = Column(String, default="Indian")
    gender = Column(String)
    mobile = Column(EncryptedString, index=False)
    email = Column(EncryptedString, index=False)

    # Permanent Address
    perm_address_line1 = Column(EncryptedString)
    perm_address_line2 = Column(EncryptedString)
    perm_city = Column(String)
    perm_state = Column(String)
    perm_pin = Column(EncryptedString)
    perm_country = Column(String, default="India")

    # Current Address
    same_address = Column(Boolean, default=True)
    curr_address_line1 = Column(EncryptedString)
    curr_address_line2 = Column(EncryptedString)
    curr_city = Column(String)
    curr_state = Column(String)
    curr_pin = Column(EncryptedString)
    curr_country = Column(String, default="India")

    id_type = Column(String)
    id_number = Column(EncryptedString, index=False)

    occupation = Column(String)
    annual_income = Column(EncryptedString)
    source_of_funds = Column(String)
    pep_status = Column(String, default="No")

    # File paths carried over
    id_proof_front_path = Column(String)
    id_proof_back_path = Column(String)
    address_proof_path = Column(String)
    current_address_proof_path = Column(String)
    income_proof_path = Column(String, nullable=True)
    selfie_path = Column(String)
    signature_path = Column(String)

    # Legacy optional fields
    aadhaar_linked_mobile = Column(EncryptedString, nullable=True)
    digilocker_access_token = Column(EncryptedString, nullable=True)
    digilocker_id_token = Column(EncryptedString, nullable=True)

    # DigiLocker response & Biometrics
    digilocker_scope = Column(String)
    digilocker_name = Column(EncryptedString)
    digilocker_dob = Column(EncryptedString)
    digilocker_gender = Column(String)
    digilocker_eaadhaar_available = Column(Boolean, default=False)
    digilocker_doc_uri = Column(String)
    digilocker_photo_b64 = Column(EncryptedString)  # Official government photo

    # Data extracted from DigiLocker / MoRTH / Surya OCR
    ocr_success = Column(Boolean, default=False)
    ocr_name = Column(EncryptedString)
    ocr_dob = Column(EncryptedString)
    ocr_aadhaar = Column(EncryptedString)
    ocr_pan = Column(EncryptedString)
    ocr_dl = Column(EncryptedString)
    ocr_address = Column(EncryptedString)

    # Cross-check results
    name_match = Column(Boolean, nullable=True)
    name_match_score = Column(Integer, default=0)
    dob_match = Column(Boolean, nullable=True)
    id_number_match = Column(Boolean, nullable=True)

    # Address checks
    address_match = Column(Boolean, nullable=True)
    perm_address_match = Column(Boolean, nullable=True)
    curr_address_match = Column(Boolean, nullable=True)
    utility_bill_date = Column(String)
    bill_recency_valid = Column(Boolean, nullable=True)

    # Biometric Face Matching
    face_matched = Column(Boolean, nullable=True)
    face_match_score = Column(Integer, default=0)

    # Deduplication flags
    doc_dup = Column(Boolean, default=False)
    mobile_dup = Column(Boolean, default=False)
    email_dup = Column(Boolean, default=False)

    # Final Risk Assessment
    risk_score = Column(Integer, default=0)
    risk_reasons = Column(Text)