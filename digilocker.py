"""
DigiLocker / MeriPehchaan OAuth2 (PKCE) client, plus the identity
cross-check and risk-scoring logic used after a successful callback.

Config (CLIENT_ID / CLIENT_SECRET / REDIRECT_URI) is read from environment
variables only - see .env.example. Never hardcode real credentials here.

Endpoint reference (API Setu / DigiLocker Authorized Partner API spec):
  - Authorize:   {BASE}/oauth2/1/authorize
  - Token:       {BASE}/oauth2/2/token          (matches the version your
                                                   Setu app is provisioned for -
                                                   confirm in the Setu dashboard;
                                                   some partner apps are on
                                                   oauth2/1/token instead)
  - eAadhaar XML:{BASE}/oauth2/3/xml/eaadhaar    (only callable if the token
                                                   response's `eaadhaar` flag
                                                   is "Y", and your app has
                                                   the appropriate scope
                                                   approved by API Setu)

The token response itself already contains name / dob / gender / the
eaadhaar flag - no separate "list issued documents" call is required for
basic identity verification. Pulling the eAadhaar XML is what gets you an
address to cross-check against the form.
"""

import base64
import hashlib
import json
import os
import re
import secrets
import xml.etree.ElementTree as ET
from datetime import datetime
import httpx

CLIENT_ID = os.environ.get("DIGILOCKER_CLIENT_ID")
CLIENT_SECRET = os.environ.get("DIGILOCKER_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("DIGILOCKER_REDIRECT_URI")

BASE = "https://digilocker.meripehchaan.gov.in/public"
AUTHORIZE_URL = f"{BASE}/oauth2/1/authorize"
TOKEN_URL = f"{BASE}/oauth2/2/token"
EAADHAAR_XML_URL = f"{BASE}/oauth2/3/xml/eaadhaar"


def require_config():
    missing = [
        name for name, val in [
            ("DIGILOCKER_CLIENT_ID", CLIENT_ID),
            ("DIGILOCKER_CLIENT_SECRET", CLIENT_SECRET),
            ("DIGILOCKER_REDIRECT_URI", REDIRECT_URI),
        ] if not val
    ]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")


def generate_pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def build_authorize_url(state: str, challenge: str) -> str:
    require_config()
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": "avs",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{AUTHORIZE_URL}?{query}"


async def exchange_code_for_token(code: str, code_verifier: str) -> dict:
    require_config()
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code != 200:
        # Surface DigiLocker's actual error instead of a bare 400 crash,
        # so we can see error/error_description in Render logs.
        print(f"🔑 TOKEN EXCHANGE FAILED: {resp.status_code} — {resp.text}")
        raise RuntimeError(f"DigiLocker token exchange failed ({resp.status_code}): {resp.text}")
    return resp.json()


def decode_id_token_claims(id_token: str) -> dict:
    """Decode (NOT verify) the JWT payload to read identity claims for display."""
    try:
        payload_b64 = id_token.split(".")[1]
        padding = "=" * (-len(payload_b64) % 4)
        decoded = base64.urlsafe_b64decode(payload_b64 + padding)
        return json.loads(decoded)
    except Exception as e:
        return {"decode_error": str(e)}


async def fetch_eaadhaar_xml(access_token: str) -> str | None:
    """Returns the raw eAadhaar XML string, or None if the call fails/unavailable."""
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            EAADHAAR_XML_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code != 200:
        return None
    return resp.text


def parse_eaadhaar_xml(xml_text: str) -> dict:
    """
    Parses the fields we care about out of the signed eAadhaar XML.
    Field/attribute names follow the UIDAI e-KYC XML schema DigiLocker
    passes through; confirm exact attribute casing against a real sample
    response in the Setu dashboard sandbox before going live, since UIDAI
    has revised this schema across versions.
    """
    result = {"name": None, "dob": None, "address": None, "masked_aadhaar": None}
    try:
        root = ET.fromstring(xml_text)
        # UIDAI eKYC XML: <UidData uid="xxxxxxxxNNNN"><Poi name="..." dob=".../>
        # <Poa .../></UidData> - namespaces/casing vary by version.
        uid_data = root if root.tag.endswith("UidData") else root.find(".//{*}UidData")
        if uid_data is not None:
            uid = uid_data.attrib.get("uid")
            if uid:
                result["masked_aadhaar"] = "XXXXXXXX" + uid[-4:]
        poi = root.find(".//{*}Poi")
        if poi is not None:
            result["name"] = poi.attrib.get("name")
            result["dob"] = poi.attrib.get("dob")
        poa = root.find(".//{*}Poa")
        if poa is not None:
            parts = [
                poa.attrib.get(k) for k in
                ("house", "street", "lm", "loc", "vtc", "subdist", "dist", "state", "pc")
                if poa.attrib.get(k)
            ]
            result["address"] = ", ".join(parts) if parts else None
    except ET.ParseError:
        pass
    return result


def _normalize(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s.strip().lower())


def _normalize_date(s: str | None) -> str:
    """Normalize either YYYY-MM-DD (HTML date input) or DD-MM-YYYY (UIDAI) to YYYY-MM-DD."""
    if not s:
        return ""
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s


def cross_check(form_values: dict, ocr_values: dict) -> dict:
    """Compares form-submitted values against DigiLocker/eAadhaar-derived values."""
    checks = {}

    if form_values.get("name") and ocr_values.get("name"):
        checks["name_match"] = _normalize(form_values["name"]) == _normalize(ocr_values["name"])
    else:
        checks["name_match"] = None

    if form_values.get("dob") and ocr_values.get("dob"):
        checks["dob_match"] = _normalize_date(form_values["dob"]) == _normalize_date(ocr_values["dob"])
    else:
        checks["dob_match"] = None

    if form_values.get("address") and ocr_values.get("address"):
        form_tokens = set(_normalize(form_values["address"]).split())
        ocr_tokens = set(_normalize(ocr_values["address"]).split())
        overlap = len(form_tokens & ocr_tokens) / max(len(form_tokens), 1)
        checks["address_match"] = overlap >= 0.5
    else:
        checks["address_match"] = None

    # id_number_match only meaningful when the form ID type is Aadhaar and we
    # have a masked UID to compare the last 4 digits against.
    if (
        form_values.get("id_type") == "aadhaar"
        and form_values.get("id_number")
        and ocr_values.get("masked_aadhaar")
    ):
        form_last4 = re.sub(r"\D", "", form_values["id_number"])[-4:]
        ocr_last4 = ocr_values["masked_aadhaar"][-4:]
        checks["id_number_match"] = form_last4 == ocr_last4
    else:
        checks["id_number_match"] = None

    return checks


def compute_risk(checks: dict, dedup: dict, ocr_success: bool, pep_status: str | None) -> tuple[int, list[str]]:
    score = 0
    reasons = []

    if checks.get("name_match") is False:
        score += 35
        reasons.append("Name on form does not match DigiLocker identity record")
    if checks.get("dob_match") is False:
        score += 30
        reasons.append("Date of birth does not match DigiLocker identity record")
    if checks.get("address_match") is False:
        score += 10
        reasons.append("Address only partially matches DigiLocker record")
    if checks.get("id_number_match") is False:
        score += 25
        reasons.append("ID number does not match DigiLocker record")

    if dedup.get("doc_dup"):
        score += 40
        reasons.append("Duplicate ID document number found in existing records")
    if dedup.get("mobile_dup"):
        score += 15
        reasons.append("Mobile number already linked to another account")
    if dedup.get("email_dup"):
        score += 10
        reasons.append("Email already linked to another account")

    if not ocr_success:
        score += 15
        reasons.append("Could not retrieve identity data from DigiLocker to verify against")

    if pep_status in ("yes", "related"):
        score += 20
        reasons.append("Applicant flagged as a Politically Exposed Person (PEP) or related to one")

    return min(score, 100), reasons


def status_from_risk(score: int) -> str:
    if score >= 60:
        return "rejected"
    if score >= 25:
        return "review"
    return "approved"

