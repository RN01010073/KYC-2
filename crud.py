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
    doc_dup = bool(id_number) and db.query(KYCApplication).filter(KYCApplication.id_number == id_number).first() is not None
    mobile_dup = bool(mobile) and db.query(KYCApplication).filter(KYCApplication.mobile == mobile).first() is not None
    email_dup = bool(email) and db.query(KYCApplication).filter(KYCApplication.email == email).first() is not None
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