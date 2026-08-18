import requests
import xmltodict
import json
import os

def test_eaadhaar_fetch(access_token: str):
    url = "https://api.digitallocker.gov.in/public/oauth2/1/documents/eaadhaar"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/xml"
    }

    resp = requests.get(url, headers=headers)
    print("STATUS CODE:", resp.status_code)
    print("RAW RESPONSE (first 1000 chars):")
    print(resp.text[:1000])
    print("-" * 60)

    if resp.status_code != 200:
        print("❌ Request failed — check token/scope, not a parsing issue.")
        return

    try:
        parsed = xmltodict.parse(resp.text)
        print("PARSED STRUCTURE:")
        print(json.dumps(parsed, indent=2)[:2000])  # just to see the shape
    except Exception as e:
        print("⚠️ Response isn't valid XML — might be JSON or base64. Error:", e)
        return

    # crude search: does 'address'-like data show up anywhere?
    text_lower = resp.text.lower()
    has_address_hint = any(k in text_lower for k in ["vtc", "dist", "pincode", "loc=", "house"])
    print("✅ Address-like fields present?" if has_address_hint else "❌ No address fields detected in raw response")


if __name__ == "__main__":
    token = os.environ["2ed21d38c74cc1b4a5741ab3e9c8e0af05c95a38"]
    test_eaadhaar_fetch(token)