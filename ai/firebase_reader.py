"""
firebase_reader.py
------------------
Reads sensor data from the EXISTING Firebase Realtime Database.

This module is READ-ONLY. It does NOT modify any existing sensor data.
It uses the same Firebase connection as the existing system.

Firebase path (read):  /floatingSolarPanel
Firebase path (write): /floatingSolarPanel/aiAnalysis  (NEW — does not conflict)
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

# Re-use the existing firebase_admin initialisation from the parent project.
# We guard against double-initialisation since firebase_admin is a singleton.
import firebase_admin
from firebase_admin import credentials, db

logger = logging.getLogger("FIREBASE")

# ------------------------------------------------------------------ #
# Initialisation — only if not already done by the existing app       #
# ------------------------------------------------------------------ #

def _init_firebase() -> None:
    """Initialise Firebase Admin SDK if not already initialised."""
    if firebase_admin._DEFAULT_APP_NAME in firebase_admin._apps:
        logger.debug("Firebase already initialised — reusing existing app.")
        return

    key_path = os.getenv("FIREBASE_KEY_PATH", "serviceAccountKey.json")
    db_url = os.getenv(
        "FIREBASE_DATABASE_URL",
        "https://floating-solar-panel-default-rtdb.asia-southeast1.firebasedatabase.app/"
    )

    # Resolve path relative to project root (parent of ai/)
    if not os.path.isabs(key_path):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        key_path = os.path.join(root, key_path)

    cred = credentials.Certificate(key_path)
    firebase_admin.initialize_app(cred, {"databaseURL": db_url})
    logger.info("Firebase initialised by AI layer.")


_init_firebase()


# ------------------------------------------------------------------ #
# Sensor data reader                                                   #
# ------------------------------------------------------------------ #

def get_sensor_data() -> Optional[Dict[str, Any]]:
    """
    Read the complete /floatingSolarPanel node.

    Returns the raw dict as stored in Firebase, or None when the node is empty.
    Read failures are logged and re-raised so the service can publish an error
    state instead of confusing a failed read with absent sensor data.
    Does NOT modify any existing data.
    """
    try:
        ref = db.reference("/floatingSolarPanel")
        data = ref.get()
        if data:
            logger.info("Sensor data received from Firebase.")
        else:
            logger.warning("Firebase returned empty data.")
        return data
    except Exception:
        logger.exception("Failed to read Firebase data.")
        raise


def get_historical_data(limit: int = 20) -> list:
    """
    Attempt to read recent historical readings from /floatingSolarPanel/history.

    If the history node does not exist, returns an empty list.
    The AI module gracefully falls back to current-reading-only analysis.
    """
    try:
        ref = db.reference("/floatingSolarPanel/history")
        raw = ref.order_by_key().limit_to_last(limit).get()
        if raw:
            records = list(raw.values())
            logger.info(f"Historical data: {len(records)} records retrieved.")
            return records
        return []
    except Exception as exc:
        logger.debug(f"Historical data unavailable (this is fine): {exc}")
        return []


# ------------------------------------------------------------------ #
# AI analysis writer                                                   #
# ------------------------------------------------------------------ #

def write_ai_analysis(
    analysis: Dict[str, Any],
    *,
    replace: bool = False,
) -> bool:
    """
    Persist AI status updates or a complete analysis to
    /floatingSolarPanel/aiAnalysis.

    Status-only updates merge with the existing node. Pass replace=True for a
    completed analysis so stale fields from earlier results are removed.
    """
    return _write_ai_analysis(analysis, replace=replace)


def _write_ai_analysis(
    analysis: Dict[str, Any],
    *,
    replace: bool,
) -> bool:
    try:
        ref = db.reference("/floatingSolarPanel/aiAnalysis")
        payload = {
            **analysis,
            "lastUpdated": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        if replace:
            ref.set(payload)
        else:
            ref.update(payload)
        logger.info(
            "AI analysis %s Firebase.",
            "replaced in" if replace else "updated in",
        )
        return True
    except Exception as exc:
        logger.error("Failed to write AI analysis to Firebase: %s", exc)
        return False
