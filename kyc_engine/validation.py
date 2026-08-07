import re
from datetime import datetime
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Individual KYC validation (unchanged)
# ─────────────────────────────────────────────────────────────────────────────
 
def validate_kyc(form_data: dict, document_data: dict) -> dict:
    errors = []
 
    if form_data.get("name") != document_data.get("name"):
        errors.append("Name mismatch")
 
    if not dob_values_match(form_data.get("dob"), document_data.get("dob")):
        errors.append("DOB mismatch")
 
    if errors:
        return {"status": "failed", "errors": errors}
 
    return {"status": "passed"}
 
 
def _normalize_dob(value) -> str | None:
    """Convert supported DOB formats into a canonical YYYY-MM-DD string."""
    if not value:
        return None
 
    value = str(value).strip()
    if not value:
        return None
 
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
 
    return None
 
 
def dob_values_match(left, right) -> bool:
    """Match DOBs even when equivalent dates are written in different formats."""
    if not left or not right:
        return False
 
    left_normalized = _normalize_dob(left)
    right_normalized = _normalize_dob(right)
 
    if left_normalized and right_normalized:
        return left_normalized == right_normalized
 
    return str(left).strip().lower() == str(right).strip().lower()
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Format validators
# ─────────────────────────────────────────────────────────────────────────────
 
def _valid_gstin(value: str) -> bool:
    pattern = r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}Z[A-Z\d]{1}$"
    return bool(value and re.match(pattern, value.strip().upper()))
 
 
def _valid_pan(value: str) -> bool:
    return bool(value and re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", value.strip().upper()))
 
 
def _valid_ifsc(value: str) -> bool:
    return bool(value and re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", value.strip().upper()))
 
 
def _valid_aadhaar(value: str) -> bool:
    if not value:
        return False
    digits = re.sub(r"\s", "", value)
    return len(digits) == 12 and digits.isdigit()
 
 
def _valid_mobile(value: str) -> bool:
    if not value:
        return False
    digits = re.sub(r"[\s\+\-]", "", value)
    return len(digits) >= 10 and digits[-10:].isdigit()
 
 
def _valid_email(value: str) -> bool:
    return bool(value and re.match(r"^[\w\.\+\-]+@[\w\-]+\.[a-zA-Z]{2,}$", value.strip()))
 
 
def _valid_account_number(value: str) -> bool:
    if not value:
        return False
    digits = re.sub(r"[\s\-]", "", value)
    return 9 <= len(digits) <= 18 and digits.isdigit()
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Vendor KYC validation
# ─────────────────────────────────────────────────────────────────────────────
 
def validate_vendor_kyc(
    form_data: dict,
    ocr_cheque_data: dict = None,
    ocr_aadhaar_data: dict = None,
) -> dict:
    errors   = []
    warnings = []
 
    if not form_data.get("business_name", "").strip():
        errors.append("Business name is required")
 
    if not form_data.get("business_type", "").strip():
        errors.append("Business type is required")
 
    if not form_data.get("business_phone", "").strip():
        errors.append("Business contact number is required")
 
    if not form_data.get("business_email", "").strip():
        errors.append("Business email is required")
 
    gstin = form_data.get("gstin", "").strip().upper()
    if not gstin:
        errors.append("GSTIN is required")
    elif not _valid_gstin(gstin):
        errors.append("GSTIN format is invalid (expected: 22AAAAA0000A1Z5)")
 
    biz_pan = form_data.get("business_pan", "").strip().upper()
    if not biz_pan:
        errors.append("Business PAN is required")
    elif not _valid_pan(biz_pan):
        errors.append("Business PAN format is invalid (expected: AAAAA0000A)")
 
    if gstin and len(gstin) >= 12 and biz_pan and len(biz_pan) == 10:
        if gstin[2:12] != biz_pan:
            errors.append("PAN embedded in GSTIN does not match the business PAN provided")
 
    sig_pan = form_data.get("signatory_pan", "").strip().upper()
    if sig_pan and not _valid_pan(sig_pan):
        errors.append("Signatory PAN format is invalid")
 
    if not form_data.get("signatory_dob") and not form_data.get("sig1_dob"):
        warnings.append("Signatory date of birth not provided")
 
    aadhaar_raw = (
        form_data.get("sig1_aadhaar")
        or form_data.get("signatory_aadhaar")
        or ""
    )
    if not aadhaar_raw:
        errors.append("Authorised signatory Aadhaar is required")
    elif not _valid_aadhaar(aadhaar_raw):
        errors.append("Aadhaar number must be exactly 12 digits")
 
    phone = form_data.get("business_phone", "")
    if phone and not _valid_mobile(phone):
        errors.append("Business contact number format is invalid")
 
    email = form_data.get("business_email", "")
    if email and not _valid_email(email):
        errors.append("Business email format is invalid")
 
    acc_num     = form_data.get("account_number", "")
    acc_confirm = form_data.get("account_number_confirm", "")
    ifsc        = form_data.get("ifsc_code", "").strip().upper()
 
    if acc_num:
        if not _valid_account_number(acc_num):
            errors.append("Account number must be between 9 and 18 digits")
        if acc_confirm and acc_num != acc_confirm:
            errors.append("Account number and confirmation do not match")
 
    if ifsc and not _valid_ifsc(ifsc):
        errors.append("IFSC code format is invalid (expected: ABCD0123456)")
 
    if ocr_cheque_data:
        ocr_ifsc = (ocr_cheque_data.get("ifsc") or "").strip().upper()
        ocr_acc  = re.sub(r"[\s\-]", "", ocr_cheque_data.get("account_number") or "")
 
        if ocr_ifsc and ifsc and ocr_ifsc != ifsc:
            errors.append(f"IFSC mismatch: declared '{ifsc}' but cheque shows '{ocr_ifsc}'")
 
        if ocr_acc and acc_num:
            clean_acc = re.sub(r"[\s\-]", "", acc_num)
            if ocr_acc[-4:] != clean_acc[-4:]:
                errors.append("Account number last 4 digits do not match cheque OCR — please verify")
 
    if ocr_aadhaar_data:
        sig_name = (
            form_data.get("sig1_name") or form_data.get("signatory_name") or ""
        ).strip().lower()
        ocr_name = (ocr_aadhaar_data.get("name") or "").strip().lower()
 
        if sig_name and ocr_name:
            sig_tokens = set(sig_name.split())
            ocr_tokens = set(ocr_name.split())
            if not (sig_tokens & ocr_tokens):
                warnings.append("Signatory name on Aadhaar does not match the name provided in the form")
 
    if not form_data.get("reg_address_line1", "").strip():
        errors.append("Registered address is required")
    if not form_data.get("reg_city", "").strip():
        errors.append("Registered city is required")
    if not form_data.get("reg_pin", "").strip():
        errors.append("Registered PIN code is required")
 
    status = "failed" if errors else "passed"
    return {"status": status, "errors": errors, "warnings": warnings}
 
 
# ─────────────────────────────────────────────────────────────────────────────
# GSTIN state code → state name map
# ─────────────────────────────────────────────────────────────────────────────
 
# Maps 2-digit GSTIN state code to canonical state name AND common aliases
# so we can fuzzy-match against whatever the user typed in the form.
_GSTIN_STATE_MAP: dict[str, dict] = {
    "01": {"name": "Jammu & Kashmir",         "aliases": ["jammu", "kashmir", "j&k", "jk"]},
    "02": {"name": "Himachal Pradesh",         "aliases": ["himachal", "hp"]},
    "03": {"name": "Punjab",                   "aliases": ["punjab"]},
    "04": {"name": "Chandigarh",               "aliases": ["chandigarh"]},
    "05": {"name": "Uttarakhand",              "aliases": ["uttarakhand", "uttaranchal", "uk"]},
    "06": {"name": "Haryana",                  "aliases": ["haryana"]},
    "07": {"name": "Delhi",                    "aliases": ["delhi", "new delhi", "ncr"]},
    "08": {"name": "Rajasthan",                "aliases": ["rajasthan"]},
    "09": {"name": "Uttar Pradesh",            "aliases": ["uttar pradesh", "up"]},
    "10": {"name": "Bihar",                    "aliases": ["bihar"]},
    "11": {"name": "Sikkim",                   "aliases": ["sikkim"]},
    "12": {"name": "Arunachal Pradesh",        "aliases": ["arunachal"]},
    "13": {"name": "Nagaland",                 "aliases": ["nagaland"]},
    "14": {"name": "Manipur",                  "aliases": ["manipur"]},
    "15": {"name": "Mizoram",                  "aliases": ["mizoram"]},
    "16": {"name": "Tripura",                  "aliases": ["tripura"]},
    "17": {"name": "Meghalaya",                "aliases": ["meghalaya"]},
    "18": {"name": "Assam",                    "aliases": ["assam"]},
    "19": {"name": "West Bengal",              "aliases": ["west bengal", "wb", "bengal"]},
    "20": {"name": "Jharkhand",                "aliases": ["jharkhand"]},
    "21": {"name": "Odisha",                   "aliases": ["odisha", "orissa"]},
    "22": {"name": "Chhattisgarh",             "aliases": ["chhattisgarh", "chattisgarh"]},
    "23": {"name": "Madhya Pradesh",           "aliases": ["madhya pradesh", "mp"]},
    "24": {"name": "Gujarat",                  "aliases": ["gujarat"]},
    "25": {"name": "Daman & Diu",              "aliases": ["daman", "diu"]},
    "26": {"name": "Dadra & Nagar Haveli",     "aliases": ["dadra", "nagar haveli", "dnh"]},
    "27": {"name": "Maharashtra",              "aliases": ["maharashtra", "mh"]},
    "28": {"name": "Andhra Pradesh",           "aliases": ["andhra pradesh", "ap", "andhra"]},
    "29": {"name": "Karnataka",                "aliases": ["karnataka"]},
    "30": {"name": "Goa",                      "aliases": ["goa"]},
    "31": {"name": "Lakshadweep",              "aliases": ["lakshadweep"]},
    "32": {"name": "Kerala",                   "aliases": ["kerala"]},
    "33": {"name": "Tamil Nadu",               "aliases": ["tamil nadu", "tn", "tamilnadu"]},
    "34": {"name": "Puducherry",               "aliases": ["puducherry", "pondicherry"]},
    "35": {"name": "Andaman & Nicobar",        "aliases": ["andaman", "nicobar", "a&n"]},
    "36": {"name": "Telangana",                "aliases": ["telangana", "ts"]},
    "37": {"name": "Andhra Pradesh (New)",     "aliases": ["andhra pradesh", "andhra", "ap"]},
    "38": {"name": "Ladakh",                   "aliases": ["ladakh"]},
    "96": {"name": "Foreign",                  "aliases": ["foreign"]},
    "97": {"name": "Other Territory",          "aliases": ["other"]},
    "99": {"name": "Centre Jurisdiction",      "aliases": ["centre", "center"]},
}
 
 
def _state_code_to_name(code: str) -> str | None:
    entry = _GSTIN_STATE_MAP.get(code)
    return entry["name"] if entry else None
 
 
def _state_matches_code(declared_state: str, state_code: str) -> bool:
    """
    Return True if the declared state string is a reasonable match
    for the given GSTIN state code.
    """
    entry = _GSTIN_STATE_MAP.get(state_code)
    if not entry:
        return False
 
    declared_lower = declared_state.strip().lower()
    canonical      = entry["name"].lower()
    aliases        = entry["aliases"]
 
    # Exact canonical match
    if declared_lower == canonical:
        return True
 
    # Alias match
    for alias in aliases:
        if alias in declared_lower or declared_lower in alias:
            return True
 
    # Token-based fallback: share at least one meaningful word
    declared_tokens = set(declared_lower.split())
    canonical_tokens = set(canonical.split())
    if declared_tokens & canonical_tokens:
        return True
 
    return False
 
 
def _normalize_name(s: str) -> str:
    """Lowercase, strip extra spaces, remove common noise words."""
    noise = {"private", "limited", "pvt", "ltd", "llp", "inc", "co", "and", "&", "."}
    tokens = re.sub(r"[^\w\s]", " ", s.lower()).split()
    return " ".join(t for t in tokens if t not in noise)
 
 
def _names_match(a: str, b: str) -> bool:
    """Fuzzy name match: token overlap after normalisation."""
    if not a or not b:
        return False
    ta = set(_normalize_name(a).split())
    tb = set(_normalize_name(b).split())
    if not ta or not tb:
        return False
    overlap = ta & tb
    # At least half of the shorter name's tokens must overlap
    min_tokens = min(len(ta), len(tb))
    return len(overlap) >= max(1, min_tokens // 2)
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Cross-check engine
# ─────────────────────────────────────────────────────────────────────────────
 
def compute_vendor_cross_checks(
    form_data: dict,
    ocr_pan_data: dict,
    ocr_aadhaar_data: dict = None,
    ocr_cheque_data: dict = None,
) -> list:
    """
    Run all document cross-checks for vendor KYC.
 
    Parameters
    ----------
    form_data        : flat dict of submitted form fields
    ocr_pan_data     : output of process_id_proof(bpan_path, "pan")
    ocr_aadhaar_data : output of process_id_proof(aadhf_path, "aadhaar")  [optional]
    ocr_cheque_data  : output of process_cancelled_cheque(cheque_path)     [optional]
 
    Returns
    -------
    List of check dicts:
        {
            "label":       str,          # Short display title
            "description": str,          # What was verified
            "expected":    str | None,   # Value from form / GSTIN pattern
            "found":       str | None,   # Value from OCR / computed
            "passed":      bool | None,  # True / False / None (could not check)
            "severity":    str,          # "critical" | "warning" | "info"
        }
    """
    checks = []
 
    gstin     = (form_data.get("gstin") or "").strip().upper()
    biz_pan   = (form_data.get("business_pan") or "").strip().upper()
    biz_name  = (form_data.get("business_name") or "").strip()
    reg_state = (form_data.get("reg_state") or "").strip()
 
    ocr_pan_num  = (ocr_pan_data.get("pan")  or "").strip().upper()
    ocr_pan_name = (ocr_pan_data.get("name") or "").strip()
 
    # ── 1. Business PAN on form vs card PAN ───────────────────────────────────
    if ocr_pan_num:
        passed = ocr_pan_num == biz_pan
        checks.append({
            "label":       "Business PAN — form vs card",
            "description": "PAN number extracted from the uploaded PAN card image vs the PAN entered in the form",
            "expected":    biz_pan or "—",
            "found":       ocr_pan_num,
            "passed":      passed,
            "severity":    "critical",
        })
    else:
        checks.append({
            "label":       "Business PAN — form vs card",
            "description": "PAN number extracted from the uploaded PAN card image vs the PAN entered in the form",
            "expected":    biz_pan or "—",
            "found":       None,
            "passed":      None,
            "severity":    "critical",
        })
 
    # ── 2. Business name on PAN form vs card ──────────────────────────────────
    if ocr_pan_name:
        passed = _names_match(ocr_pan_name, biz_name)
        checks.append({
            "label":       "Business name — PAN form vs card",
            "description": "Name printed on the business PAN card vs the business name entered in the form",
            "expected":    biz_name or "—",
            "found":       ocr_pan_name,
            "passed":      passed,
            "severity":    "warning",
        })
    else:
        checks.append({
            "label":       "Business name — PAN form vs card",
            "description": "Name printed on the business PAN card vs the business name entered in the form",
            "expected":    biz_name or "—",
            "found":       None,
            "passed":      None,
            "severity":    "warning",
        })
 
    # ── 4. GSTIN state code vs declared registration state ────────────────────
    if gstin and len(gstin) >= 2:
        state_code      = gstin[:2]
        mapped_state    = _state_code_to_name(state_code)
 
        if mapped_state and reg_state:
            passed = _state_matches_code(reg_state, state_code)
            checks.append({
                "label":       "GSTIN state code vs declared state",
                "description": f"First 2 digits of GSTIN ({state_code}) map to '{mapped_state}' — this must match the registered state in the form",
                "expected":    f"{state_code} → {mapped_state}",
                "found":       reg_state,
                "passed":      passed,
                "severity":    "critical",
            })
        elif not mapped_state:
            checks.append({
                "label":       "GSTIN state code vs declared state",
                "description": f"First 2 digits of GSTIN ({state_code}) — state code not recognised",
                "expected":    state_code,
                "found":       reg_state or "—",
                "passed":      None,
                "severity":    "warning",
            })
        else:
            # reg_state missing — already caught in validation
            checks.append({
                "label":       "GSTIN state code vs declared state",
                "description": f"First 2 digits of GSTIN ({state_code}) map to '{mapped_state}'",
                "expected":    f"{state_code} → {mapped_state}",
                "found":       "State not provided",
                "passed":      False,
                "severity":    "critical",
            })
    else:
        checks.append({
            "label":       "GSTIN state code vs declared state",
            "description": "First 2 digits of GSTIN encode the state — could not extract (invalid GSTIN)",
            "expected":    "—",
            "found":       reg_state or "—",
            "passed":      None,
            "severity":    "warning",
        })
 
    # ── 5. Aadhaar address state vs declared state ────────────────────────────
    if ocr_aadhaar_data:
        aadhaar_addr = (ocr_aadhaar_data.get("address") or "").lower()
        if aadhaar_addr and reg_state:
 
            detected_state = None
 
            # Find which state appears in Aadhaar address
            for entry in _GSTIN_STATE_MAP.values():
 
                state_name = entry["name"]
 
                if state_name.lower() in aadhaar_addr:
                    detected_state = state_name
                    break
 
                for alias in entry["aliases"]:
                    if alias.lower() in aadhaar_addr:
                        detected_state = state_name
                        break
 
                if detected_state:
                    break
 
            passed = (
                detected_state is not None
                and detected_state.lower() == reg_state.lower()
            )
 
            checks.append({
                "label": "Declared state vs Aadhaar state",
                "description": "State extracted from Aadhaar address compared with the declared registration state",
                "expected": reg_state,
                "found": detected_state,
                "passed": passed,
                "severity": "warning",
            })
        else:
            checks.append({
                "label":       "Declared state vs Aadhaar address",
                "description": "Could not verify — Aadhaar address or declared state missing",
                "expected":    reg_state or "—",
                "found":       None,
                "passed":      None,
                "severity":    "info",
            })
    else:
        checks.append({
            "label":       "Declared state vs Aadhaar address",
            "description": "Aadhaar OCR did not return address data — check skipped",
            "expected":    reg_state or "—",
            "found":       None,
            "passed":      None,
            "severity":    "info",
        })
 
    # ── 6. IFSC code — form vs cancelled cheque OCR ───────────────────────────
    declared_ifsc = (form_data.get("ifsc_code") or "").strip().upper()
    if ocr_cheque_data:
        ocr_ifsc = (ocr_cheque_data.get("ifsc") or "").strip().upper()
        if ocr_ifsc:
            passed = declared_ifsc == ocr_ifsc
            checks.append({
                "label":       "IFSC code — form vs cheque OCR",
                "description": "IFSC code entered in the bank details form vs the IFSC extracted via OCR from the uploaded cancelled cheque",
                "expected":    declared_ifsc or "—",
                "found":       ocr_ifsc,
                "passed":      passed,
                "severity":    "critical",
            })
        else:
            checks.append({
                "label":       "IFSC code — form vs cheque OCR",
                "description": "IFSC code entered in the bank details form vs the IFSC extracted via OCR from the uploaded cancelled cheque",
                "expected":    declared_ifsc or "—",
                "found":       None,
                "passed":      None,
                "severity":    "critical",
            })
    else:
        checks.append({
            "label":       "IFSC code — form vs cheque OCR",
            "description": "IFSC code entered in the bank details form vs the IFSC extracted via OCR from the uploaded cancelled cheque",
            "expected":    declared_ifsc or "—",
            "found":       None,
            "passed":      None,
            "severity":    "critical",
        })
 
    # ── 7. Account number — form vs cancelled cheque OCR ─────────────────────
    declared_acc = re.sub(r"[\s\-]", "", form_data.get("account_number") or "")
    if ocr_cheque_data:
        ocr_acc_raw = re.sub(r"[\s\-]", "", ocr_cheque_data.get("account_number") or "")
        if ocr_acc_raw:
            # Compare last 4 digits (full number is masked in storage; OCR may be partial)
            if len(declared_acc) >= 4 and len(ocr_acc_raw) >= 4:
                passed = declared_acc[-4:] == ocr_acc_raw[-4:]
            else:
                passed = declared_acc == ocr_acc_raw if (declared_acc and ocr_acc_raw) else None
 
            # Display masked versions for security
            def _mask(n):
                return ("X" * (len(n) - 4) + n[-4:]) if len(n) >= 4 else n
 
            checks.append({
                "label":       "Account number — form vs cheque OCR",
                "description": "Last 4 digits of the account number entered in the form vs the account number extracted via OCR from the cancelled cheque",
                "expected":    _mask(declared_acc) if declared_acc else "—",
                "found":       _mask(ocr_acc_raw),
                "passed":      passed,
                "severity":    "critical",
            })
        else:
            checks.append({
                "label":       "Account number — form vs cheque OCR",
                "description": "Last 4 digits of the account number entered in the form vs the account number extracted via OCR from the cancelled cheque",
                "expected":    ("X" * max(0, len(declared_acc) - 4) + declared_acc[-4:]) if len(declared_acc) >= 4 else (declared_acc or "—"),
                "found":       None,
                "passed":      None,
                "severity":    "critical",
            })
    else:
        checks.append({
            "label":       "Account number — form vs cheque OCR",
            "description": "Last 4 digits of the account number entered in the form vs the account number extracted via OCR from the cancelled cheque",
            "expected":    ("X" * max(0, len(declared_acc) - 4) + declared_acc[-4:]) if len(declared_acc) >= 4 else (declared_acc or "—"),
            "found":       None,
            "passed":      None,
            "severity":    "critical",
        })
 
    # ── 8. Aadhaar number — form vs Aadhaar card OCR ─────────────────────────
    form_aadhaar_raw = re.sub(r"\s", "", (
        form_data.get("sig1_aadhaar") or
        form_data.get("signatory_aadhaar") or ""
    ))
    if ocr_aadhaar_data:
        ocr_aadhaar_num = re.sub(r"\s", "", ocr_aadhaar_data.get("aadhaar") or "")
        if ocr_aadhaar_num:
            if len(form_aadhaar_raw) == 12 and len(ocr_aadhaar_num) == 12:
                passed = form_aadhaar_raw == ocr_aadhaar_num
            else:
                passed = None
 
            def _mask_aadhaar(n):
                return ("XXXX XXXX " + n[-4:]) if len(n) >= 4 else n
 
            checks.append({
                "label":       "Aadhaar number — form vs Aadhaar card OCR",
                "description": "Aadhaar number entered in the signatory details form vs the number extracted via OCR from the uploaded Aadhaar card image",
                "expected":    _mask_aadhaar(form_aadhaar_raw) if form_aadhaar_raw else "—",
                "found":       _mask_aadhaar(ocr_aadhaar_num),
                "passed":      passed,
                "severity":    "critical",
            })
        else:
            checks.append({
                "label":       "Aadhaar number — form vs Aadhaar card OCR",
                "description": "Aadhaar number entered in the signatory details form vs the number extracted via OCR from the uploaded Aadhaar card image",
                "expected":    ("XXXX XXXX " + form_aadhaar_raw[-4:]) if len(form_aadhaar_raw) >= 4 else (form_aadhaar_raw or "—"),
                "found":       None,
                "passed":      None,
                "severity":    "critical",
            })
    else:
        checks.append({
            "label":       "Aadhaar number — form vs Aadhaar card OCR",
            "description": "Aadhaar number entered in the signatory details form vs the number extracted via OCR from the uploaded Aadhaar card image",
            "expected":    ("XXXX XXXX " + form_aadhaar_raw[-4:]) if len(form_aadhaar_raw) >= 4 else (form_aadhaar_raw or "—"),
            "found":       None,
            "passed":      None,
            "severity":    "critical",
        })
 
    return checks