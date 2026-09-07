import json

from sqlalchemy.orm import Session

from models import KYCApplication, PendingKYCSession


def create_pending_session(db: Session, state: str, code_verifier: str, form_data: dict, file_paths: dict) -> PendingKYCSession:
    row = PendingKYCSession(
        state=state,
        code_verifier=code_verifier,
        **form_data,
        **file_paths,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_pending_session_by_state(db: Session, state: str) -> PendingKYCSession | None:
    return db.query(PendingKYCSession).filter(PendingKYCSession.state == state).first()


def delete_pending_session(db: Session, row: PendingKYCSession) -> None:
    db.delete(row)
    db.commit()


def check_duplicates(db: Session, id_number: str | None, mobile: str | None, email: str | None) -> dict:
    """
    Check for duplicate identity or contact numbers across all applications.
    Since columns use Fernet non-deterministic encryption, we compare decrypted values.
    """
    if not (id_number or mobile or email):
        return {"doc_dup": False, "mobile_dup": False, "email_dup": False}

    all_apps = db.query(KYCApplication).all()
    doc_dup = bool(id_number) and any(app.id_number == id_number for app in all_apps)
    mobile_dup = bool(mobile) and any(app.mobile == mobile for app in all_apps)
    email_dup = bool(email) and any(app.email == email for app in all_apps)
    return {"doc_dup": doc_dup, "mobile_dup": mobile_dup, "email_dup": email_dup}


def create_kyc_application(db: Session, **fields) -> KYCApplication:
    if isinstance(fields.get("risk_reasons"), list):
        fields["risk_reasons"] = json.dumps(fields["risk_reasons"])
    row = KYCApplication(**fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_kyc_application(db: Session, app_id: str) -> KYCApplication | None:
    return db.query(KYCApplication).filter(KYCApplication.id == app_id).first()


def get_all_kyc_applications(db: Session):
    return db.query(KYCApplication).order_by(KYCApplication.created_at.desc()).all()