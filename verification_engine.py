import base64
import json
import os
import re
import subprocess
import tempfile
import platform
from datetime import datetime, timezone, timedelta
from pathlib import Path
from html import unescape

import cv2
import numpy as np
from PIL import Image
from rapidfuzz import fuzz


# ────────────────────────────────────────────────────────────────────────
# 1. NAME MATCHING ENGINE (Fuzzy token-sort & token-set)
# ────────────────────────────────────────────────────────────────────────

HONORIFICS = {"mr", "mrs", "ms", "miss", "shri", "smt", "shrimati", "dr", "prof", "md", "kumari"}

def normalize_name(name: str | None) -> str:
    """Normalize Indian names: strip titles, remove punctuation, collapse whitespace."""
    if not name:
        return ""
    # Lowercase & replace punctuation with space
    clean = re.sub(r"[^a-zA-Z\s]", " ", str(name).lower())
    tokens = clean.split()
    filtered = [t for t in tokens if t not in HONORIFICS]
    return " ".join(filtered)


def match_names(form_name: str | None, dl_name: str | None) -> dict:
    """
    Compares applicant-submitted name with DigiLocker verified name.
    Gracefully handles reversed name order, initials, and honorifics.
    """
    norm_form = normalize_name(form_name)
    norm_dl = normalize_name(dl_name)

    if not norm_form or not norm_dl:
        return {
            "matched": False,
            "score": 0,
            "reason": "Missing name in submission or government records"
        }

    # Direct equality
    if norm_form == norm_dl:
        return {"matched": True, "score": 100, "reason": "Exact match"}

    # RapidFuzz token matchers
    sort_ratio = fuzz.token_sort_ratio(norm_form, norm_dl)
    set_ratio = fuzz.token_set_ratio(norm_form, norm_dl)
    partial_ratio = fuzz.partial_ratio(norm_form, norm_dl)

    combined_score = int(max(sort_ratio, (set_ratio * 0.7 + partial_ratio * 0.3)))
    matched = combined_score >= 75

    reason = "Name matched with high confidence" if matched else f"Name similarity below threshold ({combined_score}%)"
    return {"matched": matched, "score": combined_score, "reason": reason}


# ────────────────────────────────────────────────────────────────────────
# 2. BIOMETRIC FACE MATCHING ENGINE (Webcam Selfie vs DigiLocker Photo)
# ────────────────────────────────────────────────────────────────────────

def _load_image_from_b64(b64_str: str) -> np.ndarray | None:
    """Decode base64 string to OpenCV BGR image."""
    try:
        if "," in b64_str:
            b64_str = b64_str.split(",", 1)[1]
        img_bytes = base64.b64decode(b64_str)
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        return img
    except Exception as e:
        print(f"Failed to decode base64 photo: {e}")
        return None


from storage import read_upload


def _load_image_from_file(file_path: str) -> np.ndarray | None:
    """Load image from disk via storage.read_upload (handles decryption) or cv2."""
    if not file_path or not os.path.exists(file_path):
        return None
    try:
        decrypted = read_upload(file_path)
        if decrypted:
            nparr = np.frombuffer(decrypted, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is not None:
                return img
        img = cv2.imread(file_path)
        return img
    except Exception as e:
        print(f"Failed to read image from {file_path}: {e}")
        return None


def _center_crop_gray(gray: np.ndarray) -> np.ndarray | None:
    """Return a 128x128 center crop of a grayscale image as face detection fallback."""
    h, w = gray.shape
    cy, cx = h // 2, w // 2
    crop_size = min(h, w) // 2
    face_crop = gray[cy - crop_size:cy + crop_size, cx - crop_size:cx + crop_size]
    if face_crop.size > 0:
        return cv2.resize(face_crop, (128, 128))
    return None


def _detect_and_crop_face(img: np.ndarray) -> np.ndarray | None:
    """Detect primary face using OpenCV Haar Cascade and return 128x128 cropped gray face."""
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Safely resolve Haar cascade path — cv2.data.haarcascades may be None in
    # some headless/minimal OpenCV builds on cloud platforms (e.g. Render).
    haarcascades_dir = getattr(cv2, "data", None)
    haarcascades_dir = getattr(haarcascades_dir, "haarcascades", None)
    if not haarcascades_dir:
        # Attempt known fallback paths for opencv-python-headless on Linux
        import glob
        candidates = glob.glob("/opt/**/*haarcascade_frontalface_default.xml", recursive=True) + \
                     glob.glob("/usr/**/*haarcascade_frontalface_default.xml", recursive=True)
        if not candidates:
            print("Haar cascade XML not found; skipping face detection, using center crop.")
            return _center_crop_gray(gray)
        cascade_path = candidates[0]
    else:
        cascade_path = haarcascades_dir + "haarcascade_frontalface_default.xml"

    if not os.path.exists(cascade_path):
        print(f"Haar cascade XML missing at {cascade_path}; using center crop.")
        return _center_crop_gray(gray)

    face_cascade = cv2.CascadeClassifier(cascade_path)
    if face_cascade.empty():
        print("CascadeClassifier failed to load; using center crop.")
        return _center_crop_gray(gray)

    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40))
    if len(faces) == 0:
        return _center_crop_gray(gray)

    # Largest detected face
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    face_crop = gray[y:y+h, x:x+w]
    return cv2.resize(face_crop, (128, 128))


def verify_face(selfie_path: str | None, dl_photo_b64: str | None) -> dict:
    """
    Biometric face match between applicant's live webcam selfie and
    official government photo from DigiLocker.
    Returns confidence score (0-100) and match boolean.
    """
    if not selfie_path or not dl_photo_b64:
        return {
            "matched": False,
            "score": 0,
            "reason": "Missing selfie photo or DigiLocker official photo"
        }

    selfie_img = _load_image_from_file(selfie_path)
    dl_img = _load_image_from_b64(dl_photo_b64)

    if selfie_img is None or dl_img is None:
        return {
            "matched": False,
            "score": 0,
            "reason": "Could not decode selfie or government photo"
        }

    face1 = _detect_and_crop_face(selfie_img)
    face2 = _detect_and_crop_face(dl_img)

    if face1 is None or face2 is None:
        return {
            "matched": False,
            "score": 30,
            "reason": "Clear face could not be detected in one or both images"
        }

    # Equalize histograms to normalize contrast/lighting differences
    face1_eq = cv2.equalizeHist(face1)
    face2_eq = cv2.equalizeHist(face2)

    # 1. Structural template correlation
    res = cv2.matchTemplate(face1_eq, face2_eq, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(res)
    corr_score = max(0.0, float(max_val))

    # 2. Histogram correlation
    hist1 = cv2.calcHist([face1_eq], [0], None, [64], [0, 256])
    hist2 = cv2.calcHist([face2_eq], [0], None, [64], [0, 256])
    cv2.normalize(hist1, hist1)
    cv2.normalize(hist2, hist2)
    hist_score = max(0.0, float(cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)))

    # 3. Feature keypoint matching (ORB)
    orb = cv2.ORB_create(nfeatures=200)
    kp1, des1 = orb.detectAndCompute(face1_eq, None)
    kp2, des2 = orb.detectAndCompute(face2_eq, None)

    orb_score = 0.5
    if des1 is not None and des2 is not None and len(des1) > 5 and len(des2) > 5:
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = bf.match(des1, des2)
        if matches:
            good_matches = [m for m in matches if m.distance < 60]
            orb_score = min(1.0, len(good_matches) / max(len(des1), len(des2)))

    # Weighted biometric confidence
    final_confidence = (corr_score * 0.45) + (hist_score * 0.35) + (orb_score * 0.20)
    score_pct = int(min(100, max(0, final_confidence * 100)))

    # Threshold for match: 60%
    matched = score_pct >= 60
    reason = f"Face matched with {score_pct}% confidence" if matched else f"Face match confidence low ({score_pct}%)"

    return {
        "matched": matched,
        "score": score_pct,
        "reason": reason
    }


# ────────────────────────────────────────────────────────────────────────
# 3. SURYA OCR INTEGRATION & PARSING
# ────────────────────────────────────────────────────────────────────────

def _html_block_to_text(html_str: str) -> str:
    if not html_str:
        return ""
    html_str = re.sub(r"<br\s*/?>", "\n", html_str, flags=re.IGNORECASE)
    html_str = re.sub(r"<li[^>]*>", "\n", html_str, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", html_str)
    return unescape(text).strip()


def run_surya_ocr_file(file_path: str) -> str:
    """
    Runs Surya OCR on a given image or PDF using the tested CLI workflow.
    Handles decrypting encrypted uploaded files beforehand.
    Returns concatenated extracted plain text.
    """
    if not file_path or not os.path.exists(file_path):
        return ""

    creationflags = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0

    with tempfile.TemporaryDirectory() as tmp_cwd:
        # Decrypt uploaded file to temporary plain file
        decrypted_bytes = read_upload(file_path)
        ext = os.path.splitext(file_path)[1] or ".png"
        tmp_target = os.path.join(tmp_cwd, f"doc_input{ext}")

        if decrypted_bytes:
            with open(tmp_target, "wb") as f:
                f.write(decrypted_bytes)
        else:
            import shutil
            shutil.copy(file_path, tmp_target)

        stem = Path(tmp_target).stem
        try:
            subprocess.run(
                ["surya_ocr", tmp_target],
                cwd=tmp_cwd,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
                creationflags=creationflags,
            )
            result_path = os.path.join(tmp_cwd, "results", "surya", stem, "results.json")
            if os.path.exists(result_path):
                with open(result_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                pages = data.get(stem, [])
                extracted_lines = []
                for page in pages:
                    for block in page.get("blocks", []):
                        t = _html_block_to_text(block.get("html", ""))
                        if t:
                            extracted_lines.append(t)
                return "\n".join(extracted_lines)
        except Exception as e:
            print(f"Surya OCR execution note: {e}")

    return ""


def clean_address_text(raw: str) -> str:
    """Standardize address text for comparison."""
    if not raw:
        return ""
    raw = re.sub(r"(Address|Pin Code|State|Country)\s*[:\-]", " ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"[^\w\s]", " ", raw)
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip().lower()


def extract_pincode(text: str) -> str | None:
    """Extract 6-digit Indian postal PIN code."""
    if not text:
        return None
    matches = re.findall(r"\b([1-9][0-9]{5})\b", text)
    return matches[-1] if matches else None


def extract_bill_date(ocr_text: str) -> tuple[str | None, bool]:
    """
    Extracts date from utility bill / bank statement and verifies if it is <= 90 days old.
    Returns (extracted_date_str, is_recent_bool).
    """
    if not ocr_text:
        return None, False

    # Matches DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD, or DD Mon YYYY
    date_patterns = [
        r"\b(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})\b",
        r"\b(\d{4})[\/\-\.](\d{1,2})[\/\-\.](\d{1,2})\b",
        r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s,]+(\d{4})\b",
    ]

    now = datetime.now()
    cutoff_date = now - timedelta(days=90)

    for pattern in date_patterns:
        match = re.search(pattern, ocr_text, re.IGNORECASE)
        if match:
            date_str = match.group(0)
            # Try parsing
            for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
                try:
                    parsed = datetime.strptime(date_str, fmt)
                    # Sanity check: cannot be in future, and >= cutoff
                    is_recent = cutoff_date <= parsed <= (now + timedelta(days=1))
                    return date_str, is_recent
                except ValueError:
                    continue
            return date_str, True  # Default true if date string found

    return None, False


# ────────────────────────────────────────────────────────────────────────
# 4. ADDRESS VERIFICATION ENGINES (Permanent & Current)
# ────────────────────────────────────────────────────────────────────────

def verify_permanent_address(form_perm: dict, dl_address: str | None, uploaded_proof_path: str | None) -> dict:
    """
    Dual-source permanent address verification:
    1. MoRTH Driving Licence address from DigiLocker (Primary).
    2. Uploaded permanent address proof via Surya OCR (Aadhaar Back fallback).
    """
    form_pin = form_perm.get("perm_pin", "").strip()
    form_addr_str = f"{form_perm.get('perm_address_line1', '')} {form_perm.get('perm_city', '')} {form_perm.get('perm_state', '')} {form_pin}"
    clean_form = clean_address_text(form_addr_str)

    # 1. Check DigiLocker DL Address
    if dl_address:
        clean_dl = clean_address_text(dl_address)
        dl_pin = extract_pincode(dl_address)
        ratio = fuzz.token_set_ratio(clean_form, clean_dl)

        pin_matched = bool(form_pin and dl_pin and form_pin == dl_pin)
        if (pin_matched and ratio >= 50) or ratio >= 70:
            return {
                "matched": True,
                "score": ratio,
                "source": "DigiLocker MoRTH Driving Licence",
                "verified_address": dl_address,
                "reason": f"Matched with DigiLocker Driving Licence address ({ratio}%)"
            }

    # 2. Check Uploaded Proof (Aadhaar Back) via Surya OCR
    if uploaded_proof_path and os.path.exists(uploaded_proof_path):
        ocr_text = run_surya_ocr_file(uploaded_proof_path)
        if ocr_text:
            ocr_pin = extract_pincode(ocr_text)
            clean_ocr = clean_address_text(ocr_text)
            ratio = fuzz.token_set_ratio(clean_form, clean_ocr)

            pin_matched = bool(form_pin and ocr_pin and form_pin == ocr_pin)
            if (pin_matched and ratio >= 45) or ratio >= 65:
                return {
                    "matched": True,
                    "score": ratio,
                    "source": "Uploaded Address Proof (Aadhaar Back OCR)",
                    "verified_address": ocr_text[:200],
                    "reason": f"Matched with uploaded Aadhaar proof ({ratio}%)"
                }

    return {
        "matched": False,
        "score": 0,
        "source": "None",
        "verified_address": None,
        "reason": "Permanent address could not be verified against DL or uploaded proof"
    }


def verify_current_address(form_curr: dict, uploaded_bill_path: str | None, same_as_perm: bool, perm_matched: bool) -> dict:
    """
    Current address verification:
    - If same_as_perm is True: Inherits permanent address verification status.
    - If same_as_perm is False: Processes uploaded utility bill/bank statement via Surya OCR,
      verifies 6-digit PIN code, and confirms bill recency <= 90 days.
    """
    if same_as_perm:
        return {
            "matched": perm_matched,
            "recency_valid": True,
            "bill_date": None,
            "source": "Same as Permanent Address",
            "reason": "Current address declared same as verified permanent address" if perm_matched else "Permanent address unverified"
        }

    # If different address, must verify uploaded utility bill / statement
    if not uploaded_bill_path or not os.path.exists(uploaded_bill_path):
        return {
            "matched": False,
            "recency_valid": False,
            "bill_date": None,
            "source": "None",
            "reason": "Current address differs from permanent address, but no utility bill was provided"
        }

    ocr_text = run_surya_ocr_file(uploaded_bill_path)
    bill_date, recency_valid = extract_bill_date(ocr_text)

    form_pin = form_curr.get("curr_pin", "").strip()
    form_city = form_curr.get("curr_city", "").strip().lower()
    form_addr = f"{form_curr.get('curr_address_line1', '')} {form_city} {form_curr.get('curr_state', '')} {form_pin}"

    ocr_pin = extract_pincode(ocr_text)
    clean_ocr = clean_address_text(ocr_text)
    ratio = fuzz.token_set_ratio(clean_address_text(form_addr), clean_ocr)

    pin_or_city_matched = (form_pin and ocr_pin and form_pin == ocr_pin) or (form_city and form_city in clean_ocr)
    address_matched = pin_or_city_matched or ratio >= 55

    matched = address_matched and recency_valid
    reason = "Utility bill address & recency valid" if matched else "Utility bill address mismatched or bill older than 90 days"

    return {
        "matched": matched,
        "recency_valid": recency_valid,
        "bill_date": bill_date,
        "source": "Utility Bill / Bank Statement OCR",
        "reason": reason
    }


# ────────────────────────────────────────────────────────────────────────
# 5. RISK ASSESSMENT ENGINE
# ────────────────────────────────────────────────────────────────────────

def compute_risk_v2(
    name_matched: bool,
    name_score: int,
    dob_matched: bool,
    face_matched: bool,
    face_score: int,
    perm_addr_matched: bool,
    curr_addr_matched: bool,
    pep_status: str | None,
    doc_dup: bool,
    mobile_dup: bool,
    email_dup: bool
) -> tuple[int, list[str], str]:
    """
    Computes weighted compliance risk score (0 - 100) and final decision:
    - Score < 25: approved
    - Score 25 - 59: review
    - Score >= 60: rejected
    """
    score = 0
    reasons = []

    # 1. Name Check
    if not name_matched or name_score < 70:
        score += 30
        reasons.append(f"Name mismatch between applicant form and DigiLocker ({name_score}%)")

    # 2. DOB Check
    if not dob_matched:
        score += 25
        reasons.append("Date of Birth mismatch with official government record")

    # 3. Biometric Face Match
    if not face_matched or face_score < 60:
        score += 35
        reasons.append(f"Live selfie failed facial verification against government photo ({face_score}%)")

    # 4. Permanent Address
    if not perm_addr_matched:
        score += 20
        reasons.append("Permanent address could not be verified against DigiLocker or Aadhaar proof")

    # 5. Current Address
    if not curr_addr_matched:
        score += 20
        reasons.append("Current residential address proof unverified or older than 90 days")

    # 6. Politically Exposed Person (PEP)
    if pep_status and pep_status.strip().lower() in ("yes", "pep"):
        score += 30
        reasons.append("Applicant flagged as Politically Exposed Person (PEP)")

    # 7. Deduplication Flags
    if doc_dup:
        score += 40
        reasons.append("Duplicate ID number already exists in registered applications")
    if mobile_dup:
        score += 20
        reasons.append("Duplicate mobile number registered on another application")
    if email_dup:
        score += 20
        reasons.append("Duplicate email address registered on another application")

    score = min(100, score)

    if score < 25:
        decision = "approved"
    elif score < 60:
        decision = "review"
    else:
        decision = "rejected"

    return score, reasons, decision
