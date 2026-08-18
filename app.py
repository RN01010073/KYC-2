import json
import os
import secrets

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

import crud
import digilocker
import storage
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

Base.metadata.create_all(bind=engine)

app = FastAPI(title="VerifyZ")
templates = Jinja2Templates(directory="templates")
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
        def _stub(request: Request):
            return HTMLResponse(
                f"<div style='font-family:sans-serif;padding:60px;text-align:center;"
                f"background:#0A0C10;color:#F0F2F8;min-height:100vh;'>"
                f"<h1>{label}</h1><p>This flow isn't wired up yet.</p>"
                f"<a href='/kyc-select' style='color:#378ADD;'>&larr; Back</a></div>"
            )
        return _stub
    app.add_api_route(path, _make_stub(label), methods=["GET"])


# ────────────────────────────────────────────────────────────────────────
# eKYC submission -> kicks off DigiLocker OAuth
# ────────────────────────────────────────────────────────────────────────

@app.post("/submit-ekyc")
async def submit_ekyc(
    request: Request,
    db: Session = Depends(get_db),
    full_name: str = Form(...),
    dob: str = Form(...),
    nationality: str = Form(...),
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
    perm_country: str = Form(...),
    same_address: str = Form(None),
    curr_address_line1: str = Form(""),
    curr_address_line2: str = Form(""),
    curr_city: str = Form(""),
    curr_state: str = Form(""),
    curr_pin: str = Form(""),
    curr_country: str = Form(""),
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
    income_proof: UploadFile = None,
    selfie: UploadFile = None,
    signature_upload: UploadFile = None,
):
    form_data = dict(
        full_name=full_name, dob=dob, nationality=nationality, gender=gender,
        marital_status=marital_status, mobile=mobile, email=email,
        alternate_contact=alternate_contact,
        perm_address_line1=perm_address_line1, perm_address_line2=perm_address_line2,
        perm_city=perm_city, perm_state=perm_state, perm_pin=perm_pin, perm_country=perm_country,
        same_address=bool(same_address),
        curr_address_line1=curr_address_line1, curr_address_line2=curr_address_line2,
        curr_city=curr_city, curr_state=curr_state, curr_pin=curr_pin, curr_country=curr_country,
        id_type=id_type, id_number=id_number,
        aadhaar_linked_mobile=aadhaar_linked_mobile, dl_expiry_date=dl_expiry_date,
        occupation=occupation, annual_income=annual_income,
        source_of_funds=source_of_funds, pep_status=pep_status,
        account_purpose=account_purpose,
    )

    file_paths = dict(
        id_proof_front_path=await storage.save_upload(id_proof_front),
        id_proof_back_path=await storage.save_upload(id_proof_back),
        address_proof_path=await storage.save_upload(address_proof),
        income_proof_path=await storage.save_upload(income_proof),
        selfie_path=await storage.save_upload(selfie),
        signature_path=await storage.save_upload(signature_upload),
    )

    verifier, challenge = digilocker.generate_pkce_pair()
    state = secrets.token_urlsafe(24)

    crud.create_pending_session(db, state, verifier, form_data, file_paths)

    authorize_url = digilocker.build_authorize_url(state, challenge)
    return RedirectResponse(authorize_url, status_code=303)


# ────────────────────────────────────────────────────────────────────────
# DigiLocker callback -> exchange token, pull eAadhaar, cross-check, save
# ────────────────────────────────────────────────────────────────────────

@app.get("/digilocker/callback")
async def digilocker_callback(request: Request, db: Session = Depends(get_db)):
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
    print(f"🔍 FULL CLAIMS: {claims}")

    dl_name = claims.get("given_name") or claims.get("name")
    dl_dob = claims.get("birthdate")
    dl_gender = claims.get("gender")
    eaadhaar_available = bool(claims.get("masked_aadhaar"))

    ocr_success = bool(claims)
    ocr_name = dl_name
    ocr_dob = dl_dob
    ocr_aadhaar = claims.get("masked_aadhaar")
    ocr_pan = claims.get("pan_number")
    # Claim key is "driving_licence" (note UK spelling, no trailing "s") -
    # only present if the user has actually linked/pulled their DL into
    # DigiLocker; blank otherwise, same as pan_number.
    ocr_dl = claims.get("driving_licence")

    # Aadhaar document access requires separate UIDAI-level approval beyond
    # standard API Setu partner registration - not available at our current
    # tier, so eAadhaar XML fetch is skipped. PAN + DL cover identity
    # verification; address cross-check is not available from DigiLocker.
    ocr_address = None
    form_values = {
        "name": pending.full_name,
        "dob": pending.dob,
        "address": ", ".join(filter(None, [
            pending.perm_address_line1, pending.perm_address_line2,
            pending.perm_city, pending.perm_state, pending.perm_pin,
        ])),
        "id_type": pending.id_type,
        "id_number": pending.id_number,
    }
    ocr_values = {
        "name": ocr_name, "dob": ocr_dob, "address": ocr_address,
        "masked_aadhaar": ocr_aadhaar,
        "pan_number": ocr_pan,
        "driving_licence": ocr_dl,
    }

    checks = digilocker.cross_check(form_values, ocr_values)
    dedup = crud.check_duplicates(db, pending.id_number, pending.mobile, pending.email)
    risk_score, risk_reasons = digilocker.compute_risk(checks, dedup, ocr_success, pending.pep_status)
    status = digilocker.status_from_risk(risk_score)

    application = crud.create_kyc_application(
        db,
        kyc_source="eKYC",
        status=status,
        full_name=pending.full_name, dob=pending.dob, nationality=pending.nationality,
        gender=pending.gender, mobile=pending.mobile, email=pending.email,
        perm_address_line1=pending.perm_address_line1, perm_address_line2=pending.perm_address_line2,
        perm_city=pending.perm_city, perm_state=pending.perm_state,
        perm_pin=pending.perm_pin, perm_country=pending.perm_country,
        id_type=pending.id_type, id_number=pending.id_number,
        aadhaar_linked_mobile=pending.aadhaar_linked_mobile,
        occupation=pending.occupation, annual_income=pending.annual_income,
        source_of_funds=pending.source_of_funds, pep_status=pending.pep_status,
        id_proof_front_path=pending.id_proof_front_path, id_proof_back_path=pending.id_proof_back_path,
        address_proof_path=pending.address_proof_path, income_proof_path=pending.income_proof_path,
        selfie_path=pending.selfie_path, signature_path=pending.signature_path,
        digilocker_access_token=access_token, digilocker_id_token=token_body.get("id_token"),
        digilocker_scope=token_body.get("scope"),
        digilocker_name=dl_name, digilocker_dob=dl_dob, digilocker_gender=dl_gender,
        digilocker_eaadhaar_available=eaadhaar_available,
        ocr_success=ocr_success, ocr_name=ocr_name, ocr_dob=ocr_dob,
        ocr_aadhaar=ocr_aadhaar, ocr_pan=ocr_pan, ocr_dl=ocr_dl, ocr_address=ocr_address,
        name_match=checks["name_match"], dob_match=checks["dob_match"],
        address_match=checks["address_match"], id_number_match=checks["id_number_match"],
        doc_dup=dedup["doc_dup"], mobile_dup=dedup["mobile_dup"], email_dup=dedup["email_dup"],
        risk_score=risk_score, risk_reasons=risk_reasons,
    )

    crud.delete_pending_session(db, pending)

    response = RedirectResponse(f"/results/{application.id}", status_code=303)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


# ────────────────────────────────────────────────────────────────────────
# Results page
# ────────────────────────────────────────────────────────────────────────

@app.get("/results/{app_id}", response_class=HTMLResponse)
def results(app_id: str, request: Request, db: Session = Depends(get_db)):
    application = crud.get_kyc_application(db, app_id)
    if not application:
        return HTMLResponse("<h1>Application not found</h1>", status_code=404)

    context = {
        "user_id": application.id[:8],
        "status": application.status,
        "kyc_source": application.kyc_source,
        "doc_dup": application.doc_dup,
        "mobile_dup": application.mobile_dup,
        "email_dup": application.email_dup,
        "full_name": application.full_name,
        "id_type": application.id_type,
        "id_number": application.id_number,
        "ocr_success": application.ocr_success,
        "form_values": {
            "name": application.full_name,
            "dob": application.dob,
            "address": ", ".join(filter(None, [
                application.perm_address_line1, application.perm_address_line2,
                application.perm_city, application.perm_state, application.perm_pin,
            ])),
            "id_number": application.id_number,
        },
        "ocr_values": {
            "name": application.ocr_name,
            "dob": application.ocr_dob,
            "address": application.ocr_address,
            # Show whichever DigiLocker field actually corresponds to the ID
            # type the applicant selected - never show Aadhaar data under a
            # PAN/DL row (or vice versa).
            "id_number": {
                "aadhaar": application.ocr_aadhaar,
                "pan": application.ocr_pan,
                "dl": application.ocr_dl,
            }.get(application.id_type),
        },
        # True as long as it's an ID type we know how to cross-check at all;
        # the row itself still falls back to "N/A" per-application if
        # DigiLocker just didn't have that document linked for this user.
        "digilocker_verifies_id_number": application.id_type in ("aadhaar", "pan", "dl"),
        "cross_checks": {
            "name_match": application.name_match,
            "dob_match": application.dob_match,
            "address_match": application.address_match,
            "id_number_match": application.id_number_match,
        },
        "ocr_name": application.ocr_name,
        "ocr_dob": application.ocr_dob,
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
            address: {a.perm_address_line1}, {a.perm_city}, {a.perm_state} {a.perm_pin}<br><br>

            <u>DigiLocker token response (raw - DECRYPTED)</u><br>
            digilocker_name: {a.digilocker_name} | digilocker_dob: {a.digilocker_dob} | digilocker_gender: {a.digilocker_gender}<br>
            eaadhaar_available: {a.digilocker_eaadhaar_available}<br>
            scope: {a.digilocker_scope}<br><br>

            <u>Full decoded id_token claims</u><br>
            {"<br>".join(f"{k}: {v}" for k, v in (digilocker.decode_id_token_claims(a.digilocker_id_token).items() if a.digilocker_id_token else {}))}<br><br>

            <u>eAadhaar / OCR extracted data (DECRYPTED)</u><br>
            ocr_success: {a.ocr_success}<br>
            ocr_name: {a.ocr_name} | ocr_dob: {a.ocr_dob}<br>
            ocr_aadhaar: {a.ocr_aadhaar} | ocr_pan: {a.ocr_pan}<br>
            ocr_address: {a.ocr_address}<br><br>

            <u>Cross-check results</u><br>
            name_match: {a.name_match} | dob_match: {a.dob_match} |
            address_match: {a.address_match} | id_number_match: {a.id_number_match}<br><br>

            <u>Risk</u><br>
            score: {a.risk_score} | reasons: {a.risk_reasons}
        </div>
        """)

    html.append("</div>")
    return "".join(html)


if __name__ == "__main__":
    import os

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))