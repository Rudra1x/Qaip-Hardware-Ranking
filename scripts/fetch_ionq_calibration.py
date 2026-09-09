"""
fetch_ionq_calibration.py

Fetches the latest calibration (characterization) data for all available
IonQ QPU backends and saves each as a JSON file in data/.

Usage
-----
    export IONQ_API_KEY="your-api-key-here"
    python scripts/fetch_ionq_calibration.py

Output
------
    data/ionq_aria_1.json
    data/ionq_aria_2.json
    data/ionq_forte_1.json

The saved files are the raw IonQ API response with one extra field:
    _fetched_at  — ISO timestamp of when the fetch ran

These files are used by IonQAdapter in utils.py.

API reference
-------------
    GET https://api.ionq.co/v0.3/characterizations/backends/{backend}/current
    Authorization: apiKey <IONQ_API_KEY>
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("requests not installed. Run: pip install requests")
    sys.exit(1)

# Load .env if present (optional — works without python-dotenv too)
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file)
    except ImportError:
        # dotenv not installed — parse manually
        for line in _env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL   = "https://api.ionq.co/v0.3"
DATA_DIR   = Path(__file__).parent.parent / "data"

# All QPU backends available through Qollab
BACKENDS = [
    "qpu.aria-1",
    "qpu.aria-2",
    "qpu.forte-1",
]

# Map backend name → output filename
def backend_to_filename(backend: str) -> str:
    return "ionq_" + backend.replace("qpu.", "").replace("-", "_") + ".json"


# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch_calibration(backend: str, api_key: str) -> dict:
    """
    Fetch the most recent characterization for a backend.

    Endpoint: GET /characterizations/backends/{backend}/current
    """
    url     = f"{BASE_URL}/characterizations/backends/{backend}/current"
    headers = {"Authorization": f"apiKey {api_key}"}

    print(f"  Fetching {backend} ...", end=" ", flush=True)

    response = requests.get(url, headers=headers, timeout=30)

    if response.status_code == 200:
        data = response.json()
        data["_fetched_at"] = datetime.now(timezone.utc).isoformat()
        print(f"OK  (SPAM median: {data.get('fidelity', {}).get('spam', {}).get('median', 'n/a')},"
              f"  T1: {data.get('timing', {}).get('t1', 'n/a')}s)")
        return data

    elif response.status_code == 401:
        print("FAILED — invalid API key")
        raise ValueError("IonQ API key is invalid or expired. "
                         "Check cloud.ionq.com/settings/keys")

    elif response.status_code == 404:
        print("SKIPPED — backend not available")
        return None

    else:
        print(f"FAILED — HTTP {response.status_code}: {response.text[:120]}")
        raise RuntimeError(f"Unexpected response {response.status_code} for {backend}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    api_key = os.environ.get("IONQ_API_KEY", "").strip()

    if not api_key:
        print(
            "Error: IONQ_API_KEY environment variable not set.\n"
            "\n"
            "Steps to get your key:\n"
            "  1. Log in to cloud.ionq.com with your Qollab credentials\n"
            "  2. Go to Settings → API Keys\n"
            "  3. Generate a new key\n"
            "  4. export IONQ_API_KEY='your-key-here'\n"
            "  5. Re-run this script\n"
        )
        sys.exit(1)

    DATA_DIR.mkdir(exist_ok=True)

    print(f"Fetching IonQ calibration data")
    print(f"API base : {BASE_URL}")
    print(f"Output   : {DATA_DIR}/")
    print(f"Backends : {', '.join(BACKENDS)}")
    print()

    fetched = []
    skipped = []

    for backend in BACKENDS:
        try:
            data = fetch_calibration(backend, api_key)

            if data is None:
                skipped.append(backend)
                continue

            filename = DATA_DIR / backend_to_filename(backend)
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            fetched.append((backend, filename.name))

        except ValueError as e:
            # Bad API key — no point continuing
            print(f"\n{e}")
            sys.exit(1)

        except Exception as e:
            print(f"\nWarning: {backend} failed ({e}). Continuing.")
            skipped.append(backend)

    print()
    print("─" * 48)
    print(f"Done.  Saved {len(fetched)} file(s):")
    for backend, fname in fetched:
        print(f"  {fname}")

    if skipped:
        print(f"\nSkipped ({len(skipped)}): {', '.join(skipped)}")

    print()
    print("These files are ready to use with IonQAdapter in utils.py:")
    print("  from utils import IonQAdapter")
    print("  ionq = IonQAdapter.load('data/ionq_aria_1.json')")


if __name__ == "__main__":
    main()
