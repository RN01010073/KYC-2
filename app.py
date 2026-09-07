import json
import os
import secrets
import traceback
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import text
from sqlalchemy.orm import Session

import crud
import digilocker
import storage
import verification_engine
from database import Base, engine, get_db

# Admin credentials for debug endpoint (from environment variables)
DEBUG_USERNAME = os.environ.get("DEBUG_USERNAME", "admin")
DEBUG_PASSWORD = os.environ.get("DEBUG_PASSWORD")

if not DEBUG_PASSWORD:
    raise RuntimeError(
        "DEBUG_PASSWORD is not set. Set it as an environment variable "
        "(Render: Environment tab; local: .env file). Never hardcode it in source."
    )

security = HTTPBasic()

# Create base tables
try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"Base.metadata.create_all notice: {e}")


def ensure_schema():
    """
    Exhaustive schema synchronisation: ensures EVERY column defined in models.py
    exists in Supabase/PostgreSQL. Safe to run on every startup — uses
    ADD COLUMN IF NOT EXISTS so existing columns are never touched.
    Uses AUTOCOMMIT isolation to avoid leaving transactions in an aborted state.
    """
    # (table_name, column_name, postgres_type_with_optional_default)
    ALL_COLS = [
        # ── pending_kyc_sessions ─────────────────────────────────────────
        ("pending_kyc_sessions", "kyc_source",                  "VARCHAR DEFAULT 'eKYC'"),
        ("pending_kyc_sessions", "full_name",                   "TEXT"),
        ("pending_kyc_sessions", "dob",                         "TEXT"),
        ("pending_kyc_sessions", "nationality",                 "VARCHAR DEFAULT 'Indian'"),
        ("pending_kyc_sessions", "gender",                      "VARCHAR"),
        ("pending_kyc_sessions", "mobile",                      "TEXT"),
        ("pending_kyc_sessions", "email",                       "TEXT"),
        ("pending_kyc_sessions", "marital_status",              "VARCHAR"),
        ("pending_kyc_sessions", "alternate_contact",           "TEXT"),
        # Permanent address
        ("pending_kyc_sessions", "perm_address_line1",          "TEXT"),
        ("pending_kyc_sessions", "perm_address_line2",          "TEXT"),
        ("pending_kyc_sessions", "perm_city",                   "VARCHAR"),
        ("pending_kyc_sessions", "perm_state",                  "VARCHAR"),
        ("pending_kyc_sessions", "perm_pin",                    "TEXT"),
        ("pending_kyc_sessions", "perm_country",                "VARCHAR DEFAULT 'India'"),
        # Current address
        ("pending_kyc_sessions", "same_address",                "BOOLEAN DEFAULT TRUE"),
        ("pending_kyc_sessions", "curr_address_line1",          "TEXT"),
        ("pending_kyc_sessions", "curr_address_line2",          "TEXT"),
        ("pending_kyc_sessions", "curr_city",                   "VARCHAR"),
        ("pending_kyc_sessions", "curr_state",                  "VARCHAR"),
        ("pending_kyc_sessions", "curr_pin",                    "TEXT"),
        ("pending_kyc_sessions", "curr_country",                "VARCHAR DEFAULT 'India'"),
        # ID
        ("pending_kyc_sessions", "id_type",                     "VARCHAR"),
        ("pending_kyc_sessions", "id_number",                   "TEXT"),
        ("pending_kyc_sessions", "aadhaar_linked_mobile",       "TEXT"),
        ("pending_kyc_sessions", "dl_expiry_date",              "VARCHAR"),
        # AML
        ("pending_kyc_sessions", "occupation",                  "VARCHAR"),
        ("pending_kyc_sessions", "annual_income",               "TEXT"),
        ("pending_kyc_sessions", "source_of_funds",             "VARCHAR"),
        ("pending_kyc_sessions", "pep_status",                  "VARCHAR DEFAULT 'No'"),
        ("pending_kyc_sessions", "account_purpose",             "TEXT"),
        # Files
        ("pending_kyc_sessions", "id_proof_front_path",         "VARCHAR"),
        ("pending_kyc_sessions", "id_proof_back_path",          "VARCHAR"),
        ("pending_kyc_sessions", "address_proof_path",          "VARCHAR"),
        ("pending_kyc_sessions", "current_address_proof_path",  "VARCHAR"),
        ("pending_kyc_sessions", "income_proof_path",           "VARCHAR"),
        ("pending_kyc_sessions", "selfie_path",                 "VARCHAR"),
        ("pending_kyc_sessions", "signature_path",              "VARCHAR"),

        # ── kyc_applications ─────────────────────────────────────────────
        ("kyc_applications", "kyc_source",                  "VARCHAR DEFAULT 'eKYC'"),
        ("kyc_applications", "status",                      "VARCHAR DEFAULT 'review'"),
        # Applicant profile
        ("kyc_applications", "full_name",                   "TEXT"),
        ("kyc_applications", "dob",                         "TEXT"),
        ("kyc_applications", "nationality",                 "VARCHAR DEFAULT 'Indian'"),
        ("kyc_applications", "gender",                      "VARCHAR"),
        ("kyc_applications", "mobile",                      "TEXT"),
        ("kyc_applications", "email",                       "TEXT"),
        # Permanent address
        ("kyc_applications", "perm_address_line1",          "TEXT"),
        ("kyc_applications", "perm_address_line2",          "TEXT"),
        ("kyc_applications", "perm_city",                   "VARCHAR"),
        ("kyc_applications", "perm_state",                  "VARCHAR"),
        ("kyc_applications", "perm_pin",                    "TEXT"),
        ("kyc_applications", "perm_country",                "VARCHAR DEFAULT 'India'"),
        # Current address
        ("kyc_applications", "same_address",                "BOOLEAN DEFAULT TRUE"),
        ("kyc_applications", "curr_address_line1",          "TEXT"),
        ("kyc_applications", "curr_address_line2",          "TEXT"),
        ("kyc_applications", "curr_city",                   "VARCHAR"),
        ("kyc_applications", "curr_state",                  "VARCHAR"),
        ("kyc_applications", "curr_pin",                    "TEXT"),
        ("kyc_applications", "curr_country",                "VARCHAR DEFAULT 'India'"),
        # ID
        ("kyc_applications", "id_type",                     "VARCHAR"),
        ("kyc_applications", "id_number",                   "TEXT"),
        # AML
        ("kyc_applications", "occupation",                  "VARCHAR"),
        ("kyc_applications", "annual_income",               "TEXT"),
        ("kyc_applications", "source_of_funds",             "VARCHAR"),
        ("kyc_applications", "pep_status",                  "VARCHAR DEFAULT 'No'"),
        # Files
        ("kyc_applications", "id_proof_front_path",         "VARCHAR"),
        ("kyc_applications", "id_proof_back_path",          "VARCHAR"),
        ("kyc_applications", "address_proof_path",          "VARCHAR"),
        ("kyc_applications", "current_address_proof_path",  "VARCHAR"),
        ("kyc_applications", "income_proof_path",           "VARCHAR"),
        ("kyc_applications", "selfie_path",                 "VARCHAR"),
        ("kyc_applications", "signature_path",              "VARCHAR"),
        # Legacy
        ("kyc_applications", "aadhaar_linked_mobile",       "TEXT"),
        ("kyc_applications", "digilocker_access_token",     "TEXT"),
        ("kyc_applications", "digilocker_id_token",         "TEXT"),
        # DigiLocker response
        ("kyc_applications", "digilocker_scope",            "VARCHAR"),
        ("kyc_applications", "digilocker_name",             "TEXT"),
        ("kyc_applications", "digilocker_dob",              "TEXT"),
        ("kyc_applications", "digilocker_gender",           "VARCHAR"),
        ("kyc_applications", "digilocker_eaadhaar_available", "BOOLEAN DEFAULT FALSE"),
        ("kyc_applications", "digilocker_doc_uri",          "VARCHAR"),
        ("kyc_applications", "digilocker_photo_b64",        "TEXT"),
        # OCR extracted data
        ("kyc_applications", "ocr_success",                 "BOOLEAN DEFAULT FALSE"),
        ("kyc_applications", "ocr_name",                    "TEXT"),
        ("kyc_applications", "ocr_dob",                     "TEXT"),
        ("kyc_applications", "ocr_aadhaar",                 "TEXT"),
        ("kyc_applications", "ocr_pan",                     "TEXT"),
        ("kyc_applications", "ocr_dl",                      "TEXT"),
        ("kyc_applications", "ocr_address",                 "TEXT"),
        # Cross-check results
        ("kyc_applications", "name_match",                  "BOOLEAN"),
        ("kyc_applications", "name_match_score",            "INTEGER DEFAULT 0"),
        ("kyc_applications", "dob_match",                   "BOOLEAN"),
        ("kyc_applications", "id_number_match",             "BOOLEAN"),
        ("kyc_applications", "address_match",               "BOOLEAN"),
        ("kyc_applications", "perm_address_match",          "BOOLEAN"),
        ("kyc_applications", "curr_address_match",          "BOOLEAN"),
        ("kyc_applications", "utility_bill_date",           "VARCHAR"),
        ("kyc_applications", "bill_recency_valid",          "BOOLEAN"),
        # Biometrics
        ("kyc_applications", "face_matched",                "BOOLEAN"),
        ("kyc_applications", "face_match_score",            "INTEGER DEFAULT 0"),
        # Deduplication
        ("kyc_applications", "doc_dup",                     "BOOLEAN DEFAULT FALSE"),
        ("kyc_applications", "mobile_dup",                  "BOOLEAN DEFAULT FALSE"),
        ("kyc_applications", "email_dup",                   "BOOLEAN DEFAULT FALSE"),
        # Risk
        ("kyc_applications", "risk_score",                  "INTEGER DEFAULT 0"),
        ("kyc_applications", "risk_reasons",                "TEXT"),
    ]

    added, skipped = 0, 0
    for tbl, col, col_type in ALL_COLS:
        try:
            with engine.connect() as conn:
                conn.execution_options(isolation_level="AUTOCOMMIT")
                conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col} {col_type};"))
                added += 1
        except Exception as e:
            print(f"  ensure_schema notice [{tbl}.{col}]: {e}")
            skipped += 1
    print(f"ensure_schema complete: {added} columns verified, {skipped} skipped.")


# Run schema synchronization safely
ensure_schema()

app = FastAPI(title="VerifyZ")
templates = Jinja2Templates(directory="templates")


def format_to_ddmmyyyy(d_str: str | None) -> str:
    """Format any date representation to DD-MM-YYYY (e.g. 2002-04-13 or 13042002 -> 13-04-2002)."""
    if not d_str:
        return "-"
    try:
        norm = digilocker._normalize_date(str(d_str).strip())
        if norm and len(norm) == 10 and norm.count("-") == 2:
            parts = norm.split("-")
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
    except Exception:
        pass
    return str(d_str)


templates.env.filters["format_dob"] = format_to_ddmmyyyy
app.mount("/static", StaticFiles(directory="static"), name="static")


# ────────────────────────────────────────────────────────────────────────
# Static-ish pages
# ────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/kyc-select", response_class=HTMLResponse)
def kyc_select(request: Request):
    return templates.TemplateResponse(request, "kyc_select.html", {})


@app.get("/ekyc", response_class=HTMLResponse)
def ekyc_form(request: Request):
    return templates.TemplateResponse(request, "ekyc_form.html", {})


for path, label in [
    ("/offline-kyc", "Offline KYC"),
    ("/vendor-ekyc", "Vendor eKYC"),
    ("/vendor-offline-kyc", "Offline Vendor KYC"),
]:
    def _make_stub(label):
        def stub_endpoint(request: Request):
            return templates.TemplateResponse(
                request, "stub.html", {"title": label, "section": label}
            )
        return stub_endpoint

    app.get(path, response_class=HTMLResponse)(_make_stub(label))


# ────────────────────────────────────────────────────────────────────────
# Decrypted File Serving Endpoint
# ────────────────────────────────────────────────────────────────────────

@app.get("/view-file/{filename}")
def view_uploaded_file(filename: str):
    """
    Securely decodes and serves uploaded applicant documents, selfies,
    and signatures (which are encrypted on disk with Fernet).
    """
    safe_name = os.path.basename(filename)
    file_path = os.path.join(storage.UPLOAD_DIR, safe_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    data = storage.read_upload(file_path)
    if not data:
        raise HTTPException(status_code=404, detail="Could not read file")

    ext = os.path.splitext(safe_name)[1].lower()
    media_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }
    media_type = media_map.get(ext, "application/octet-stream")
    return Response(content=data, media_type=media_type)


# ────────────────────────────────────────────────────────────────────────
# eKYC Form Submission -> Save to pending session -> Redirect to DigiLocker
# ────────────────────────────────────────────────────────────────────────

@app.post("/submit-ekyc")
async def submit_ekyc(
    request: Request,
    db: Session = Depends(get_db),
    full_name: str = Form(...),
    dob: str = Form(...),
    nationality: str = Form("Indian"),
    gender: str = Form(...),
    marital_status: str = Form(""),
    mobile: str = Form(...),
    email: str = Form(...),
    alternate_contact: str = Form(""),
    perm_address_line1: str = Form(...),
    perm_address_line2: str = Form(""),
    perm_city: str = Form(...),
    perm_state: str = Form(...),
    perm_pin: str = Form(...),
    perm_country: str = Form("India"),
    same_address: str = Form(None),
    curr_address_line1: str = Form(""),
    curr_address_line2: str = Form(""),
    curr_city: str = Form(""),
    curr_state: str = Form(""),
    curr_pin: str = Form(""),
    curr_country: str = Form("India"),
    id_type: str = Form(...),
    id_number: str = Form(...),
    aadhaar_linked_mobile: str = Form(""),
    dl_expiry_date: str = Form(""),
    occupation: str = Form(...),
    annual_income: str = Form(...),
    source_of_funds: str = Form(...),
    pep_status: str = Form(...),
    account_purpose: str = Form(""),
    id_proof_front: UploadFile = None,
    id_proof_back: UploadFile = None,
    address_proof: UploadFile = None,
    current_address_proof: UploadFile = None,
    income_proof: UploadFile = None,
    selfie: UploadFile = None,
    signature_upload: UploadFile = None,
    signature_data: str = Form(""),
):
    try:
        same_addr_bool = bool(same_address)

        # Save signature (either canvas drawing or file upload)
        signature_path = None
        if signature_upload and signature_upload.filename:
            signature_path = await storage.save_upload(signature_upload)
        elif signature_data:
            signature_path = storage.save_base64_upload(signature_data)

        form_data = dict(
            full_name=full_name,
            dob=dob,
            nationality=nationality,
            gender=gender,
            marital_status=marital_status,
            mobile=mobile,
            email=email,
            alternate_contact=alternate_contact,
            perm_address_line1=perm_address_line1,
            perm_address_line2=perm_address_line2,
            perm_city=perm_city,
            perm_state=perm_state,
            perm_pin=perm_pin,
            perm_country=perm_country,
            same_address=same_addr_bool,
            curr_address_line1=curr_address_line1 if not same_addr_bool else perm_address_line1,
            curr_address_line2=curr_address_line2 if not same_addr_bool else perm_address_line2,
            curr_city=curr_city if not same_addr_bool else perm_city,
            curr_state=curr_state if not same_addr_bool else perm_state,
            curr_pin=curr_pin if not same_addr_bool else perm_pin,
            curr_country=curr_country if not same_addr_bool else perm_country,
            id_type=id_type,
            id_number=id_number,
            aadhaar_linked_mobile=aadhaar_linked_mobile,
            dl_expiry_date=dl_expiry_date,
            occupation=occupation,
            annual_income=annual_income,
            source_of_funds=source_of_funds,
            pep_status=pep_status,
            account_purpose=account_purpose,
        )

        file_paths = dict(
            id_proof_front_path=await storage.save_upload(id_proof_front),
            id_proof_back_path=await storage.save_upload(id_proof_back),
            address_proof_path=await storage.save_upload(address_proof),
            current_address_proof_path=await storage.save_upload(current_address_proof),
            income_proof_path=await storage.save_upload(income_proof),
            selfie_path=await storage.save_upload(selfie),
            signature_path=signature_path,
        )

        verifier, challenge = digilocker.generate_pkce_pair()
        state = secrets.token_urlsafe(24)

        crud.create_pending_session(db, state, verifier, form_data, file_paths)

        authorize_url = digilocker.build_authorize_url(state, challenge)
        return RedirectResponse(authorize_url, status_code=303)
    except Exception as e:
        traceback.print_exc()
        return HTMLResponse(
            f"""
            <div style="font-family:sans-serif; max-width:600px; margin:40px auto; padding:24px; background:#161A22; color:#F0F2F8; border-radius:12px; border:1px solid #E24B4A;">
                <h2 style="color:#E24B4A; margin-top:0;">Submission Error</h2>
                <p style="color:#8A8FA8;">We could not initiate verification session:</p>
                <div style="background:#0A0C10; padding:14px; border-radius:8px; font-family:monospace; font-size:13px; color:#EF9F27; white-space:pre-wrap;">
                    {str(e)}
                </div>
                <div style="margin-top:20px;">
                    <a href="/ekyc" style="display:inline-block; padding:10px 20px; background:#378ADD; color:#fff; text-decoration:none; border-radius:6px;">← Back to Form</a>
                </div>
            </div>
            """,
            status_code=500
        )


# ────────────────────────────────────────────────────────────────────────
# DigiLocker Callback -> Exchange Token, Verify Biometrics & Address
# ────────────────────────────────────────────────────────────────────────

@app.get("/digilocker/callback")
async def digilocker_callback(request: Request, db: Session = Depends(get_db)):
    try:
        params = dict(request.query_params)
        code = params.get("code")
        state = params.get("state")

        if not code or not state:
            return HTMLResponse(f"<pre>Missing code/state from DigiLocker: {params}</pre>", status_code=400)

        pending = crud.get_pending_session_by_state(db, state)
        if not pending:
            return HTMLResponse("<pre>No matching pending session for this state (expired or already used).</pre>", status_code=400)

        token_body = await digilocker.exchange_code_for_token(code, pending.code_verifier)

        access_token = token_body.get("access_token")
        id_token = token_body.get("id_token")
        claims = digilocker.decode_id_token_claims(id_token) if id_token else {}
        print(f"🔍 DigiLocker Claims: {claims}")

        # Fetch official DigiLocker user profile & government photo
        user_info = {}
        if access_token:
            user_info = await digilocker.fetch_user_info(access_token) or {}

        user_photo_b64 = user_info.get("picture")

        # Fetch official address: Check user_info -> eAadhaar XML -> Driving Licence MoRTH XML
        ocr_address = user_info.get("address")

        if not ocr_address and user_info.get("eaadhaar") == "Y" and access_token:
            try:
                xml_text = await digilocker.fetch_eaadhaar_xml(access_token)
                if xml_text:
                    eaadhaar_data = digilocker.parse_eaadhaar_xml(xml_text)
                    ocr_address = eaadhaar_data.get("address")
            except Exception as e:
                print(f"⚠️ eAadhaar XML fetch note: {e}")

        if not ocr_address and access_token:
            try:
                dl_data = await digilocker.fetch_dl_address(access_token)
                if dl_data and dl_data.get("address"):
                    ocr_address = dl_data["address"]
            except Exception as e:
                print(f"⚠️ DL address fetch note: {e}")

        dl_name = user_info.get("name") or claims.get("given_name") or claims.get("name")
        dl_dob = user_info.get("dob") or claims.get("birthdate")
        dl_gender = user_info.get("gender") or claims.get("gender")
        eaadhaar_available = bool(claims.get("masked_aadhaar"))

        ocr_success = bool(claims or user_info)
        ocr_name = dl_name
        ocr_dob = dl_dob
        ocr_aadhaar = claims.get("masked_aadhaar")
        ocr_pan = claims.get("pan_number")
        ocr_dl = claims.get("driving_licence")

        # ────────────────────────────────────────────────────────────────
        # Run Automated Verification Engine
        # ────────────────────────────────────────────────────────────────

        # 1. Name Match (Fuzzy Token-Sort)
        try:
            name_check = verification_engine.match_names(pending.full_name, dl_name)
        except Exception as e:
            print(f"Name match note: {e}")
            name_check = {"matched": False, "score": 0, "reason": str(e)}

        # 2. Biometric Face Match (Live Selfie vs DigiLocker Photo)
        try:
            face_check = verification_engine.verify_face(pending.selfie_path, user_photo_b64)
        except Exception as e:
            print(f"Face verify note: {e}")
            face_check = {"matched": False, "score": 0, "reason": str(e)}

        # 3. Permanent Address Verification (DL XML or PaddleOCR fallback)
        try:
            form_perm = {
                "perm_address_line1": pending.perm_address_line1,
                "perm_city": pending.perm_city,
                "perm_state": pending.perm_state,
                "perm_pin": pending.perm_pin,
            }
            perm_check = verification_engine.verify_permanent_address(
                form_perm, ocr_address, pending.address_proof_path
            )
        except Exception as e:
            print(f"Perm address verify note: {e}")
            perm_check = {"matched": False, "score": 0, "source": "None", "verified_address": None, "reason": str(e)}

        # 4. Current Address Verification (Same as perm OR Utility Bill PaddleOCR)
        try:
            form_curr = {
                "curr_address_line1": pending.curr_address_line1,
                "curr_city": pending.curr_city,
                "curr_state": pending.curr_state,
                "curr_pin": pending.curr_pin,
            }
            curr_check = verification_engine.verify_current_address(
                form_curr,
                pending.current_address_proof_path,
                pending.same_address,
                perm_check.get("matched", False)
            )
        except Exception as e:
            print(f"Curr address verify note: {e}")
            curr_check = {"matched": False, "score": 0, "source": "None", "reason": str(e)}

        # 5. DOB & ID Cross-Checks
        dob_match = None
        if pending.dob and ocr_dob:
            dob_match = digilocker._normalize_date(pending.dob) == digilocker._normalize_date(ocr_dob)

        id_number_match = None
        id_type = (pending.id_type or "").lower()
        if id_type == "aadhaar" and pending.id_number and ocr_aadhaar:
            form_last4 = "".join(filter(str.isdigit, pending.id_number))[-4:]
            ocr_last4 = str(ocr_aadhaar)[-4:]
            id_number_match = form_last4 == ocr_last4
        elif id_type == "pan" and pending.id_number and ocr_pan:
            id_number_match = digilocker._normalize_id(pending.id_number) == digilocker._normalize_id(ocr_pan)
        elif id_type == "dl" and pending.id_number and ocr_dl:
            id_number_match = digilocker._normalize_id(pending.id_number) == digilocker._normalize_id(ocr_dl)

        # 6. Deduplication Check
        dedup = crud.check_duplicates(db, pending.id_number, pending.mobile, pending.email)

        # 7. Weighted Risk Computation & Final Decision
        risk_score, risk_reasons, status = verification_engine.compute_risk_v2(
            name_matched=name_check["matched"],
            name_score=name_check["score"],
            dob_matched=bool(dob_match),
            face_matched=face_check["matched"],
            face_score=face_check["score"],
            perm_addr_matched=perm_check["matched"],
            curr_addr_matched=curr_check["matched"],
            pep_status=pending.pep_status,
            doc_dup=dedup["doc_dup"],
            mobile_dup=dedup["mobile_dup"],
            email_dup=dedup["email_dup"],
        )

        # Create final application record
        application = crud.create_kyc_application(
            db,
            kyc_source="eKYC",
            status=status,
            full_name=pending.full_name,
            dob=pending.dob,
            nationality=pending.nationality,
            gender=pending.gender,
            mobile=pending.mobile,
            email=pending.email,
            perm_address_line1=pending.perm_address_line1,
            perm_address_line2=pending.perm_address_line2,
            perm_city=pending.perm_city,
            perm_state=pending.perm_state,
            perm_pin=pending.perm_pin,
            perm_country=pending.perm_country,
            same_address=pending.same_address,
            curr_address_line1=pending.curr_address_line1,
            curr_address_line2=pending.curr_address_line2,
            curr_city=pending.curr_city,
            curr_state=pending.curr_state,
            curr_pin=pending.curr_pin,
            curr_country=pending.curr_country,
            id_type=pending.id_type,
            id_number=pending.id_number,
            occupation=pending.occupation,
            annual_income=pending.annual_income,
            source_of_funds=pending.source_of_funds,
            pep_status=pending.pep_status,
            id_proof_front_path=pending.id_proof_front_path,
            id_proof_back_path=pending.id_proof_back_path,
            address_proof_path=pending.address_proof_path,
            current_address_proof_path=pending.current_address_proof_path,
            selfie_path=pending.selfie_path,
            signature_path=pending.signature_path,
            digilocker_scope=token_body.get("scope"),
            digilocker_name=dl_name,
            digilocker_dob=dl_dob,
            digilocker_gender=dl_gender,
            digilocker_eaadhaar_available=eaadhaar_available,
            digilocker_photo_b64=user_photo_b64,
            ocr_success=ocr_success,
            ocr_name=ocr_name,
            ocr_dob=ocr_dob,
            ocr_aadhaar=ocr_aadhaar,
            ocr_pan=ocr_pan,
            ocr_dl=ocr_dl,
            ocr_address=ocr_address or perm_check.get("verified_address"),
            name_match=name_check["matched"],
            name_match_score=name_check["score"],
            dob_match=dob_match,
            id_number_match=id_number_match,
            address_match=perm_check["matched"],
            perm_address_match=perm_check["matched"],
            curr_address_match=curr_check["matched"],
            utility_bill_date=curr_check.get("bill_date"),
            bill_recency_valid=curr_check.get("recency_valid"),
            face_matched=face_check["matched"],
            face_match_score=face_check["score"],
            doc_dup=dedup["doc_dup"],
            mobile_dup=dedup["mobile_dup"],
            email_dup=dedup["email_dup"],
            risk_score=risk_score,
            risk_reasons=risk_reasons,
        )

        # Clean up pending temporary session
        crud.delete_pending_session(db, pending)

        response = RedirectResponse(f"/results/{application.id}", status_code=303)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response
    except Exception as e:
        traceback.print_exc()
        return HTMLResponse(
            f"""
            <div style="font-family:sans-serif; max-width:600px; margin:40px auto; padding:24px; background:#161A22; color:#F0F2F8; border-radius:12px; border:1px solid #E24B4A;">
                <h2 style="color:#E24B4A; margin-top:0;">DigiLocker Verification Notice</h2>
                <p style="color:#8A8FA8;">An error occurred during identity verification callback:</p>
                <div style="background:#0A0C10; padding:14px; border-radius:8px; font-family:monospace; font-size:13px; color:#EF9F27; white-space:pre-wrap;">
                    {str(e)}
                </div>
                <div style="margin-top:20px;">
                    <a href="/ekyc" style="display:inline-block; padding:10px 20px; background:#378ADD; color:#fff; text-decoration:none; border-radius:6px;">← Back to eKYC Form</a>
                </div>
            </div>
            """,
            status_code=500
        )


# ────────────────────────────────────────────────────────────────────────
# Results page
# ────────────────────────────────────────────────────────────────────────

@app.get("/results/{app_id}", response_class=HTMLResponse)
def results(app_id: str, request: Request, db: Session = Depends(get_db)):
    try:
        application = crud.get_kyc_application(db, app_id)
        if not application:
            return HTMLResponse("<h1>Application not found</h1>", status_code=404)

        selfie_url = f"/view-file/{os.path.basename(application.selfie_path)}" if application.selfie_path else None
        signature_url = f"/view-file/{os.path.basename(application.signature_path)}" if application.signature_path else None

        context = {
            "user_id": application.id[:8],
            "application_id": application.id,
            "status": application.status,
            "kyc_source": application.kyc_source,
            "doc_dup": application.doc_dup,
            "mobile_dup": application.mobile_dup,
            "email_dup": application.email_dup,
            "full_name": application.full_name,
            "id_type": application.id_type,
            "id_number": application.id_number,
            "ocr_success": application.ocr_success,
            "same_address": application.same_address,
            "selfie_url": selfie_url,
            "signature_url": signature_url,
            "digilocker_photo_b64": application.digilocker_photo_b64,
            "face_matched": application.face_matched,
            "face_match_score": application.face_match_score or 0,
            "perm_address_match": application.perm_address_match,
            "curr_address_match": application.curr_address_match,
            "utility_bill_date": application.utility_bill_date,
            "bill_recency_valid": application.bill_recency_valid,
            "form_values": {
                "name": application.full_name,
                "dob": format_to_ddmmyyyy(application.dob),
                "address": ", ".join(filter(None, [
                    application.perm_address_line1, application.perm_address_line2,
                    application.perm_city, application.perm_state, application.perm_pin,
                ])),
                "curr_address": ", ".join(filter(None, [
                    application.curr_address_line1, application.curr_address_line2,
                    application.curr_city, application.curr_state, application.curr_pin,
                ])),
                "id_number": application.id_number,
            },
            "ocr_values": {
                "name": application.ocr_name,
                "dob": format_to_ddmmyyyy(application.ocr_dob),
                "address": application.ocr_address,
                "id_number": {
                    "aadhaar": application.ocr_aadhaar,
                    "pan": application.ocr_pan,
                    "dl": application.ocr_dl,
                }.get(application.id_type),
            },
            "digilocker_verifies_id_number": application.id_type in ("aadhaar", "pan", "dl"),
            "cross_checks": {
                "name_match": application.name_match,
                "name_match_score": application.name_match_score,
                "dob_match": application.dob_match,
                "address_match": application.address_match,
                "id_number_match": application.id_number_match,
                "face_matched": application.face_matched,
                "face_match_score": application.face_match_score,
                "perm_address_match": application.perm_address_match,
                "curr_address_match": application.curr_address_match,
            },
            "ocr_name": application.ocr_name,
            "ocr_dob": format_to_ddmmyyyy(application.ocr_dob),
            "ocr_aadhaar": application.ocr_aadhaar,
            "ocr_pan": application.ocr_pan,
            "ocr_dl": application.ocr_dl,
            "ocr_address": application.ocr_address,
            "risk_score": application.risk_score,
            "risk_reasons": json.loads(application.risk_reasons) if application.risk_reasons else [],
        }
        return templates.TemplateResponse(
            request, "results.html", context,
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache"},
        )
    except Exception as e:
        traceback.print_exc()
        return HTMLResponse(f"<h3>Error loading results: {e}</h3>", status_code=500)


# ────────────────────────────────────────────────────────────────────────
# Admin/Debug endpoint (protected with basic auth)
# ────────────────────────────────────────────────────────────────────────

def verify_admin_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify admin username and password for debug endpoints."""
    if credentials.username != DEBUG_USERNAME or credentials.password != DEBUG_PASSWORD:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@app.get("/debug/applications", response_class=HTMLResponse)
def debug_applications(
    admin: str = Depends(verify_admin_credentials),
    db: Session = Depends(get_db),
):
    """Display all KYC applications (admin only, password protected)."""
    applications = crud.get_all_kyc_applications(db)

    html = ["<div style='font-family:monospace; background:#0A0C10; color:#F0F2F8; padding:20px;'>"]
    html.append(f"<h1>⚠️ ADMIN DEBUG: All KYC Applications ({len(applications)})</h1>")
    html.append("<p style='color:#FF6B6B;'>This is encrypted data. Decryption happens automatically on display.</p>")

    if not applications:
        html.append("<p>No applications yet.</p>")

    for a in applications:
        html.append(f"""
        <div style='border:1px solid #378ADD; padding:16px; margin-bottom:16px; border-radius:8px;'>
            <strong>{a.id}</strong> — {a.created_at} — <strong>{a.status.upper()}</strong> ({a.kyc_source})<br><br>

            <u>Form data (as submitted - DECRYPTED)</u><br>
            name: {a.full_name} | dob: {a.dob} | mobile: {a.mobile} | email: {a.email}<br>
            id_type: {a.id_type} | id_number: {a.id_number}<br>
            permanent address: {a.perm_address_line1}, {a.perm_city}, {a.perm_state} {a.perm_pin}<br>
            current address: {a.curr_address_line1}, {a.curr_city}, {a.curr_state} {a.curr_pin}<br><br>

            <u>Biometrics & Verification</u><br>
            face_matched: {a.face_matched} ({a.face_match_score}%)<br>
            perm_address_match: {a.perm_address_match} | curr_address_match: {a.curr_address_match}<br>
            utility_bill_date: {a.utility_bill_date} (recent: {a.bill_recency_valid})<br><br>

            <u>DigiLocker record (DECRYPTED)</u><br>
            digilocker_name: {a.digilocker_name} | digilocker_dob: {a.digilocker_dob} | digilocker_gender: {a.digilocker_gender}<br>
            ocr_address: {a.ocr_address}<br><br>

            <u>Risk Assessment</u><br>
            score: {a.risk_score} | reasons: {a.risk_reasons}
        </div>
        """)

    html.append("</div>")
    return "".join(html)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))