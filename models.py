import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from database import Base


def _uuid():
    return str(uuid.uuid4())


class PendingKYCSession(Base):
    """
    Holds the submitted eKYC form data + PKCE verifier for the duration of
    the DigiLocker OAuth redirect round-trip. The user's browser only ever
    carries an opaque `state` value - all the real data lives here, server
    side, so concurrent users never collide and nothing sensitive sits in
    a cookie or query string.

    Deliberately NOT the final record - once the callback completes
    successfully, we copy the relevant fields into KYCApplication and this
    row can be left to expire (or cleaned up by a cron/cleanup job later).
    """
    __tablename__ = "pending_kyc_sessions"

    id = Column(String, primary_key=True, default=_uuid)
    state = Column(String, unique=True, index=True, nullable=False)
    code_verifier = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # kyc_source distinguishes which flow this pending session belongs to,
    # e.g. "eKYC" (individual) - keeps room to reuse this table for vendor
    # flows later without a schema change.
    kyc_source = Column(String, default="eKYC")

    # ── Form fields captured on /submit-ekyc, before DigiLocker redirect ──
    full_name = Column(String)
    dob = Column(String)
    nationality = Column(String)
    gender = Column(String)
    marital_status = Column(String)

    mobile = Column(String)
    email = Column(String)
    alternate_contact = Column(String)

    perm_address_line1 = Column(String)
    perm_address_line2 = Column(String)
    perm_city = Column(String)
    perm_state = Column(String)
    perm_pin = Column(String)
    perm_country = Column(String)

    same_address = Column(Boolean, default=True)
    curr_address_line1 = Column(String)
    curr_address_line2 = Column(String)
    curr_city = Column(String)
    curr_state = Column(String)
    curr_pin = Column(String)
    curr_country = Column(String)

    id_type = Column(String)
    id_number = Column(String)
    aadhaar_linked_mobile = Column(String)
    dl_expiry_date = Column(String)

    occupation = Column(String)
    annual_income = Column(String)
    source_of_funds = Column(String)
    pep_status = Column(String)
    account_purpose = Column(Text)

    # Paths to uploaded files on disk (see storage.py) - not the files
    # themselves; keeps the DB row small.
    id_proof_front_path = Column(String)
    id_proof_back_path = Column(String)
    address_proof_path = Column(String)
    income_proof_path = Column(String)
    selfie_path = Column(String)
    signature_path = Column(String)


class KYCApplication(Base):
    """
    Final, completed KYC record - created once the DigiLocker callback has
    run successfully and the identity cross-check + risk score have been
    computed. This is what /results/{id} renders via results.html.
    """
    __tablename__ = "kyc_applications"

    id = Column(String, primary_key=True, default=_uuid)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    kyc_source = Column(String, default="eKYC")  # "eKYC" / "Offline KYC" / "Vendor eKYC" / etc.
    status = Column(String, default="review")     # "approved" / "review" / "rejected"

    # ── As submitted on the form ──
    full_name = Column(String)
    dob = Column(String)
    nationality = Column(String)
    gender = Column(String)
    mobile = Column(String, index=True)
    email = Column(String, index=True)

    perm_address_line1 = Column(String)
    perm_address_line2 = Column(String)
    perm_city = Column(String)
    perm_state = Column(String)
    perm_pin = Column(String)
    perm_country = Column(String)

    id_type = Column(String)
    id_number = Column(String, index=True)
    aadhaar_linked_mobile = Column(String)

    occupation = Column(String)
    annual_income = Column(String)
    source_of_funds = Column(String)
    pep_status = Column(String)

    # File paths carried over from the pending session
    id_proof_front_path = Column(String)
    id_proof_back_path = Column(String)
    address_proof_path = Column(String)
    income_proof_path = Column(String)
    selfie_path = Column(String)
    signature_path = Column(String)

    # ── DigiLocker OAuth result (raw) ──
    digilocker_access_token = Column(Text)  # short-lived; fine to keep only until processed
    digilocker_id_token = Column(Text)
    digilocker_scope = Column(String)
    digilocker_name = Column(String)
    digilocker_dob = Column(String)
    digilocker_gender = Column(String)
    digilocker_eaadhaar_available = Column(Boolean, default=False)
    digilocker_doc_uri = Column(String)  # reference if/when a specific issued doc is pulled

    # ── Data extracted from DigiLocker / eAadhaar (what results.html calls "ocr_*") ──
    ocr_success = Column(Boolean, default=False)
    ocr_name = Column(String)
    ocr_dob = Column(String)
    ocr_aadhaar = Column(String)  # masked - see digilocker.py
    ocr_pan = Column(String)
    ocr_dl = Column(String)  # from id_token's "driving_licence" claim
    ocr_address = Column(Text)

    # ── Cross-check results (form vs DigiLocker data) ──
    name_match = Column(Boolean, nullable=True)
    dob_match = Column(Boolean, nullable=True)
    address_match = Column(Boolean, nullable=True)
    id_number_match = Column(Boolean, nullable=True)

    # ── Dedup flags ──
    doc_dup = Column(Boolean, default=False)
    mobile_dup = Column(Boolean, default=False)
    email_dup = Column(Boolean, default=False)

    # ── Risk ──
    risk_score = Column(Integer, default=0)
    risk_reasons = Column(Text)  # JSON-encoded list of strings