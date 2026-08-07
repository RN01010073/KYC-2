import re

# ─────────────────────────────────────────────────────────────────────────────
# Individual KYC risk (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_risk(validation_result: dict, is_duplicate: bool) -> dict:
    risk_score = 0
    reasons = []

    if validation_result.get("status") == "failed":
        risk_score += 50
        reasons.append("Validation failed")

    if is_duplicate:
        risk_score += 40
        reasons.append("Duplicate document detected")

    if risk_score < 30:
        status = "Approved"
    elif risk_score < 70:
        status = "Review"
    else:
        status = "Rejected"

    return {"risk_score": risk_score, "status": status, "reasons": reasons}


# ─────────────────────────────────────────────────────────────────────────────
# Vendor KYC risk scoring
# ─────────────────────────────────────────────────────────────────────────────

# ── Format validators used internally ────────────────────────────────────────

def _is_valid_gstin(gstin: str) -> bool:
    """
    GSTIN format: 2-digit state code + 10-char PAN + 1 entity number + Z + 1 checksum
    Pattern: \d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}Z[A-Z\d]{1}
    """
    if not gstin:
        return False
    pattern = r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}Z[A-Z\d]{1}$"
    return bool(re.match(pattern, gstin.strip().upper()))


def _is_valid_pan(pan: str) -> bool:
    if not pan:
        return False
    return bool(re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", pan.strip().upper()))


def _is_valid_ifsc(ifsc: str) -> bool:
    if not ifsc:
        return False
    return bool(re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", ifsc.strip().upper()))


def _is_valid_aadhaar(aadhaar: str) -> bool:
    if not aadhaar:
        return False
    digits = re.sub(r"\s", "", aadhaar)
    return len(digits) == 12 and digits.isdigit()


# ── Main vendor risk function ─────────────────────────────────────────────────

def calculate_vendor_risk(
    form_data: dict,
    validation_result: dict,
    is_duplicate: bool,
    duplicate_match_type: str = None,
    ocr_cheque_data: dict = None,
    bank_details_match: bool = False,
    source: str = "ekyc",
) -> dict:
    """
    Calculates risk score for a vendor KYC submission.

    Parameters
    ----------
    form_data           : all submitted form fields as a flat dict
    validation_result   : output from validate_vendor_kyc()
    is_duplicate        : whether GSTIN or PAN already exists in DB
    duplicate_match_type: 'GSTIN' | 'PAN' | None
    ocr_cheque_data     : dict from process_cancelled_cheque()
    bank_details_match  : True if OCR-extracted bank data matches declared data
    source              : 'ekyc' | 'offline'

    Returns
    -------
    dict with keys: risk_score (int), status (str), reasons (list[str])
    """
    risk_score = 0
    reasons    = []

    # ── 1. Validation failures (weight: up to 40) ─────────────────────────────
    if validation_result.get("status") == "failed":
        errors = validation_result.get("errors", [])
        # Each validation error adds points
        critical   = [e for e in errors if any(k in e for k in ["GSTIN", "PAN", "Aadhaar"])]
        non_critical = [e for e in errors if e not in critical]

        risk_score += min(len(critical) * 15, 30)
        risk_score += min(len(non_critical) * 5, 10)

        for e in errors:
            reasons.append(f"Validation: {e}")

    # ── 2. Duplicate detection (weight: 35–45) ────────────────────────────────
    if is_duplicate:
        if duplicate_match_type == "GSTIN":
            risk_score += 45
            reasons.append("Duplicate GSTIN detected in system")
        elif duplicate_match_type == "PAN":
            risk_score += 35
            reasons.append("Duplicate business PAN detected in system")
        else:
            risk_score += 30
            reasons.append("Possible duplicate vendor record")

    # ── 3. GSTIN format check (weight: 20) ───────────────────────────────────
    gstin = form_data.get("gstin", "")
    if gstin and not _is_valid_gstin(gstin):
        risk_score += 20
        reasons.append("Invalid GSTIN format")

    # ── 4. PAN format checks (weight: 10 each) ───────────────────────────────
    biz_pan = form_data.get("business_pan", "")
    if biz_pan and not _is_valid_pan(biz_pan):
        risk_score += 10
        reasons.append("Invalid business PAN format")

    sig_pan = form_data.get("signatory_pan", "")
    if sig_pan and not _is_valid_pan(sig_pan):
        risk_score += 10
        reasons.append("Invalid signatory PAN format")

    # ── 5. PAN–GSTIN state code consistency (weight: 15) ─────────────────────
    # GSTIN char 3–12 (0-indexed 2:12) should match entity PAN
    if gstin and len(gstin) >= 12 and biz_pan and len(biz_pan) == 10:
        gstin_pan_segment = gstin[2:12].upper()
        if gstin_pan_segment != biz_pan.upper():
            risk_score += 15
            reasons.append("PAN embedded in GSTIN does not match business PAN")

    # ── 6. Aadhaar format check (weight: 10) ─────────────────────────────────
    aadhaar_raw = form_data.get("sig1_aadhaar") or form_data.get("signatory_aadhaar", "")
    if aadhaar_raw and not _is_valid_aadhaar(aadhaar_raw):
        risk_score += 10
        reasons.append("Invalid Aadhaar format")

    # ── 7. Bank / cheque OCR mismatch (weight: 20) ───────────────────────────
    if ocr_cheque_data:
        ocr_available = any([
            ocr_cheque_data.get("account_number"),
            ocr_cheque_data.get("ifsc"),
        ])
        if ocr_available and not bank_details_match:
            risk_score += 20
            reasons.append("Bank account details mismatch between form and cheque OCR")
        elif not ocr_available:
            # OCR ran but extracted nothing — cheque may be unclear
            risk_score += 10
            reasons.append("Cheque OCR could not extract bank details")

    # ── 8. IFSC format check (weight: 10) ────────────────────────────────────
    declared_ifsc = form_data.get("ifsc_code", "")
    if declared_ifsc and not _is_valid_ifsc(declared_ifsc):
        risk_score += 10
        reasons.append("Invalid IFSC code format")

    # ── 9. Offline source penalty (weight: 5) ────────────────────────────────
    # Offline submissions have less real-time verification
    if source == "offline":
        risk_score += 5
        reasons.append("Offline submission — pending manual document review")

    # ── 10. Missing critical fields (weight: 5 each) ─────────────────────────
    critical_fields = {
        "business_name": "Business name missing",
        "gstin":         "GSTIN not provided",
        "business_pan":  "Business PAN not provided",
    }
    for field, msg in critical_fields.items():
        if not form_data.get(field, "").strip():
            risk_score += 5
            reasons.append(msg)

    # ── Cap score at 100 ──────────────────────────────────────────────────────
    risk_score = min(risk_score, 100)

    # ── Final status decision ─────────────────────────────────────────────────
    if risk_score < 30:
        status = "Approved"
    elif risk_score < 70:
        status = "Review"
    else:
        status = "Rejected"

    return {
        "risk_score": risk_score,
        "status":     status,
        "reasons":    reasons,
    }
