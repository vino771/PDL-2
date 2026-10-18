import logging
import os
from pathlib import Path

import firebase_admin
from firebase_admin import credentials
from firebase_admin import db
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")
key_path = Path(os.getenv("FIREBASE_KEY_PATH", "serviceAccountKey.json"))
if not key_path.is_absolute():
    key_path = BASE_DIR / key_path
database_url = os.getenv(
    "FIREBASE_DATABASE_URL",
    "https://floating-solar-panel-default-rtdb."
    "asia-southeast1.firebasedatabase.app/",
)


if firebase_admin._DEFAULT_APP_NAME not in firebase_admin._apps:
    cred = credentials.Certificate(str(key_path))
    firebase_admin.initialize_app(
        cred,
        {"databaseURL": database_url}
    )


def get_data():

    try:
        ref = db.reference("/floatingSolarPanel")

        data = ref.get()

        return data
    except Exception:
        logger.exception("Failed to read /floatingSolarPanel from Firebase.")
        raise