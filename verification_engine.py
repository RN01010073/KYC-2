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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 1. NAME MATCHING ENGINE (Fuzzy token-sort & token-set)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 2. BIOMETRIC FACE MATCHING ENGINE (Webcam Selfie vs DigiLocker Photo)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# YuNet + SFace Deep Learning Face Verification models (lazy-loaded)
_yunet_detector = None
_sface_recognizer = None


def _get_face_models():
    """Load or lazily initialize YuNet Face Detector and SFace Face Recognizer."""
    global _yunet_detector, _sface_recognizer
    if _sface_recognizer is not None and _yunet_detector is not None:
        return _yunet_detector, _sface_recognizer

    models_dir = os.path.join(os.path.dirname(__file__), "models_weights")
    os.makedirs(models_dir, exist_ok=True)
    yunet_path = os.path.join(models_dir, "face_detection_yunet.onnx")
    sface_path = os.path.join(models_dir, "face_recognition_sface.onnx")

    # Auto-download on cold start (e.g. Render) if missing
    if not os.path.exists(yunet_path) or os.path.getsize(yunet_path) < 10000:
        try:
            print("Downloading YuNet model weights...")
            import requests
            url = "https://huggingface.co/opencv/face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx"
            r = requests.get(url, allow_redirects=True, timeout=60)
            if r.status_code == 200:
                with open(yunet_path, "wb") as mf:
                    mf.write(r.content)
        except Exception as e:
            print(f"Failed to download YuNet: {e}")

    if not os.path.exists(sface_path) or os.path.getsize(sface_path) < 1000000:
        try:
            print("Downloading SFace model weights...")
            import requests
            url = "https://huggingface.co/opencv/face_recognition_sface/resolve/main/face_recognition_sface_2021dec.onnx"
            r = requests.get(url, allow_redirects=True, timeout=120)
            if r.status_code == 200:
                with open(sface_path, "wb") as mf:
                    mf.write(r.content)
        except Exception as e:
            print(f"Failed to download SFace: {e}")

    if os.path.exists(yunet_path) and os.path.exists(sface_path):
        try:
            _yunet_detector = cv2.FaceDetectorYN.create(yunet_path, "", (320, 320))
            _sface_recognizer = cv2.FaceRecognizerSF.create(sface_path, "")
            print("Loaded YuNet and SFace models successfully")
            return _yunet_detector, _sface_recognizer
        except Exception as e:
            print(f"Failed to initialize SFace/YuNet: {e}")

    return None, None


def _detect_and_crop_face(img: np.ndarray) -> np.ndarray | None:
    """Detect primary face using OpenCV Haar Cascade fallback and return 128x128 cropped gray face."""
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    haarcascades_dir = getattr(cv2, "data", None)
    haarcascades_dir = getattr(haarcascades_dir, "haarcascades", None)
    if not haarcascades_dir:
        import glob
        candidates = glob.glob("/opt/**/*haarcascade_frontalface_default.xml", recursive=True) +                      glob.glob("/usr/**/*haarcascade_frontalface_default.xml", recursive=True)
        if not candidates:
            return _center_crop_gray(gray)
        cascade_path = candidates[0]
    else:
        cascade_path = haarcascades_dir + "haarcascade_frontalface_default.xml"

    if not os.path.exists(cascade_path):
        return _center_crop_gray(gray)

    face_cascade = cv2.CascadeClassifier(cascade_path)
    if face_cascade.empty():
        return _center_crop_gray(gray)

    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40))
    if len(faces) == 0:
        return _center_crop_gray(gray)

    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    face_crop = gray[y:y+h, x:x+w]
    return cv2.resize(face_crop, (128, 128))


def verify_face(selfie_path: str | None, dl_photo_b64: str | None) -> dict:
    """
    Biometric face match between applicant's live webcam selfie and
    official government photo from DigiLocker using deep learning (SFace + YuNet).
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

    # 1. Primary: Deep Learning Face Recognition (YuNet + SFace)
    detector, recognizer = _get_face_models()
    if detector is not None and recognizer is not None:
        try:
            detector.setInputSize((selfie_img.shape[1], selfie_img.shape[0]))
            _, faces1 = detector.detect(selfie_img)

            detector.setInputSize((dl_img.shape[1], dl_img.shape[0]))
            _, faces2 = detector.detect(dl_img)

            if faces1 is not None and len(faces1) > 0 and faces2 is not None and len(faces2) > 0:
                f1 = max(faces1, key=lambda f: f[2] * f[3])
                f2 = max(faces2, key=lambda f: f[2] * f[3])

                aligned1 = recognizer.alignCrop(selfie_img, f1)
                aligned2 = recognizer.alignCrop(dl_img, f2)

                feat1 = recognizer.feature(aligned1)
                feat2 = recognizer.feature(aligned2)

                cosine_sim = float(recognizer.match(feat1, feat2, cv2.FaceRecognizerSF_FR_COSINE))
                print(f"Deep face comparison cosine similarity: {cosine_sim:.4f}")

                # Standard SFace match threshold: 0.363
                if cosine_sim >= 0.363:
                    matched = True
                    # Scale from [0.363, 0.70] -> [62%, 99%]
                    scaled = 62 + int(((cosine_sim - 0.363) / (0.70 - 0.363)) * 36)
                    score_pct = max(62, min(99, scaled))
                elif cosine_sim >= 0.25:
                    matched = False
                    score_pct = int(40 + ((cosine_sim - 0.25) / (0.363 - 0.25)) * 20)
                else:
                    matched = False
                    score_pct = max(5, int((max(0.0, cosine_sim) / 0.25) * 38))

                reason = (
                    f"Face matched with {score_pct}% biometric confidence"
                    if matched
                    else f"Face match confidence low ({score_pct}%)"
                )
                return {
                    "matched": matched,
                    "score": score_pct,
                    "reason": reason
                }
        except Exception as e:
            print(f"Deep learning face verification exception: {e}")

    # 2. Fallback: Structural & Histogram matching
    face1 = _detect_and_crop_face(selfie_img)
    face2 = _detect_and_crop_face(dl_img)

    if face1 is None or face2 is None:
        return {
            "matched": False,
            "score": 30,
            "reason": "Clear face could not be detected in one or both images"
        }

    face1_eq = cv2.equalizeHist(face1)
    face2_eq = cv2.equalizeHist(face2)

    res = cv2.matchTemplate(face1_eq, face2_eq, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(res)
    corr_score = max(0.0, float(max_val))

    hist1 = cv2.calcHist([face1_eq], [0], None, [64], [0, 256])
    hist2 = cv2.calcHist([face2_eq], [0], None, [64], [0, 256])
    cv2.normalize(hist1, hist1)
    cv2.normalize(hist2, hist2)
    hist_score = max(0.0, float(cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)))

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

    final_confidence = (corr_score * 0.45) + (hist_score * 0.35) + (orb_score * 0.20)
    score_pct = int(min(100, max(0, final_confidence * 100)))

    matched = score_pct >= 50
    reason = f"Face matched with {score_pct}% confidence" if matched else f"Face match confidence low ({score_pct}%)"

    return {
        "matched": matched,
        "score": score_pct,
        "reason": reason
    }


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 3. PADDLEOCR / RAPIDOCR INTEGRATION & PARSING (LOW-MEMORY ONNX RUNTIME)
# ==============================================================================

_ocr_engine = None


def _get_ocr_engine():
    """Lazy-load RapidOCR (PaddleOCR ONNX engine) once with low memory footprint (<100MB)."""
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _ocr_engine = RapidOCR()
            print("RapidOCR (PaddleOCR ONNX) loaded successfully with low memory footprint")
        except Exception as e:
            print(f"RapidOCR load note: {e}")
            _ocr_engine = None
    return _ocr_engine


def run_paddle_ocr_file(file_path: str) -> str:
    """
    Runs PaddleOCR (via lightweight ONNX engine) on a given image or PDF.
    Handles decrypting encrypted uploaded files beforehand.
    Returns concatenated extracted plain text within safe memory limits (<100MB).
    """
    if not file_path or not os.path.exists(file_path):
        return ""

    engine = _get_ocr_engine()
    if engine is None:
        print("OCR engine unavailable")
        return ""

    try:
        from PIL import Image as PILImage

        # Decrypt uploaded file
        decrypted_bytes = read_upload(file_path)
        ext = os.path.splitext(file_path)[1].lower() or ".png"

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = os.path.join(tmp_dir, f"doc_input{ext}")
            if decrypted_bytes:
                with open(tmp_path, "wb") as f:
                    f.write(decrypted_bytes)
            else:
                import shutil
                shutil.copy(file_path, tmp_path)

            image_paths = []
            if ext == ".pdf":
                try:
                    import pypdfium2 as pdfium
                    pdf = pdfium.PdfDocument(tmp_path)
                    for i, page in enumerate(pdf):
                        if i >= 2:
                            break
                        bmp = page.render(scale=2)
                        pil_img = bmp.to_pil()
                        page_p = os.path.join(tmp_dir, f"page_{i}.png")
                        pil_img.save(page_p)
                        image_paths.append(page_p)
                except Exception as e:
                    print(f"PDF extraction error: {e}")
                    image_paths = [tmp_path]
            else:
                image_paths = [tmp_path]

            extracted_lines = []
            for img_p in image_paths:
                try:
                    res, _ = engine(img_p)
                    if res:
                        for line in res:
                            if line and len(line) >= 2:
                                txt = str(line[1]).strip()
                                if txt:
                                    extracted_lines.append(txt)
                except Exception as e:
                    print(f"OCR page error on {img_p}: {e}")

            text_result = "\n".join(extracted_lines)
            print(f"PaddleOCR (ONNX) extracted {len(extracted_lines)} lines of text")
            return text_result

    except Exception as e:
        print(f"OCR execution error: {e}")

    return ""


# Maintain aliases so existing calls work seamlessly
run_surya_ocr_file = run_paddle_ocr_file


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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 4. ADDRESS VERIFICATION ENGINES (Permanent & Current)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 5. RISK ASSESSMENT ENGINE
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

