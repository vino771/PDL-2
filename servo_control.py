"""
servo_control.py
----------------
Servo control helper for the Floating Solar Panel dashboard.

Responsibilities
----------------
- Read the current servo control state from Firebase
  (/floatingSolarPanel/servoControl).
- Write a new servo command (mode, requested angles, command ID) to Firebase.
- POST the command string to the firebase_bridge /cmd queue so the Chrome
  extension can inject it into the Tinkercad serial input box.
- Detect command confirmation by comparing the Arduino's reported servo
  angles (from /floatingSolarPanel/tracking) with the requested angles.

This module is read/write ONLY for the /floatingSolarPanel/servoControl path.
It never modifies /floatingSolarPanel/sensors, /floatingSolarPanel/tracking,
or /floatingSolarPanel/aiAnalysis.

Command format sent to Arduino (plain text):
    SERVO:H=<0-180>:V=<0-180>
    e.g. SERVO:H=90:V=45

The Arduino sketch must have a Serial.available() handler that recognises this
prefix.  If the sketch does not support it, the command will be silently
ignored; the status will remain PENDING and eventually time out.  The bridge
and extension WILL deliver the text — we cannot guarantee Arduino-side
execution without an acknowledgement line in the CSV stream.

Mode semantics
--------------
AUTO   : LDR-based tracking is in charge (default / initial state).
MANUAL : Dashboard requested specific angles; command queued for Arduino.

Returning to AUTO does NOT send any command — the Arduino's LDR loop resumes
naturally once no SERVO: command overrides it (depends on Arduino sketch).
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import requests
import firebase_admin
from firebase_admin import db

logger = logging.getLogger("SERVO_CTRL")

# Bridge base URL — must match firebase_bridge.py's Flask server.
BRIDGE_URL = os.getenv("BRIDGE_URL", "http://127.0.0.1:8080")

# Firebase path for servo control state (separate from sensor telemetry).
SERVO_CONTROL_PATH = "/floatingSolarPanel/servoControl"

# Angle confirmation tolerance (degrees). A confirmed servo position within
# this many degrees of the requested position counts as "confirmed".
CONFIRM_TOLERANCE_DEG = 3

# Seconds before a PENDING command is considered FAILED (no confirmation seen).
CONFIRM_TIMEOUT_SEC = 30


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_angle(value: Any, name: str) -> Tuple[bool, str]:
    """Return (ok, error_message).  Accepts int or float in [0, 180]."""
    try:
        if isinstance(value, bool):
            raise ValueError("boolean is not an angle")
        angle = int(value)
    except (TypeError, ValueError):
        return False, f"{name} must be an integer."
    if not (0 <= angle <= 180):
        return False, f"{name} must be between 0 and 180 degrees."
    return True, ""


# ---------------------------------------------------------------------------
# Firebase read
# ---------------------------------------------------------------------------

def get_servo_state() -> Dict[str, Any]:
    """
    Read /floatingSolarPanel/servoControl from Firebase.
    Returns a dict (may be empty if the node does not exist yet).
    """
    try:
        ref = db.reference(SERVO_CONTROL_PATH)
        data = ref.get()
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.error("Failed to read servo control state: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Firebase write
# ---------------------------------------------------------------------------

def _write_servo_state(payload: Dict[str, Any], merge: bool = True) -> bool:
    """
    Write servo control state to Firebase.
    merge=True  → update only the provided keys (safe for partial updates).
    merge=False → replace the entire node.
    """
    try:
        ref = db.reference(SERVO_CONTROL_PATH)
        if merge:
            ref.update(payload)
        else:
            ref.set(payload)
        return True
    except Exception as exc:
        logger.error("Failed to write servo control state: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------

def send_servo_command(
    horizontal: int,
    vertical: int,
) -> Dict[str, Any]:
    """
    Queue a SERVO command and record it in Firebase.

    Steps
    -----
    1. Validate angles.
    2. Build a unique command ID.
    3. Write PENDING state to /floatingSolarPanel/servoControl.
    4. POST the command string to the bridge /cmd queue.
    5. Return a result dict describing what happened.

    Returns
    -------
    dict with keys: ok (bool), command_id (str), error (str|None)
    """
    ok_h, err_h = validate_angle(horizontal, "Horizontal angle")
    ok_v, err_v = validate_angle(vertical, "Vertical angle")
    if not ok_h:
        return {"ok": False, "command_id": None, "error": err_h}
    if not ok_v:
        return {"ok": False, "command_id": None, "error": err_v}

    h = int(horizontal)
    v = int(vertical)
    command_id = f"cmd_{uuid.uuid4().hex[:12]}"
    cmd_text = f"SERVO:H={h}:V={v}"
    now_iso = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    # 1. Write PENDING to Firebase BEFORE dispatching the command so the
    #    dashboard sees the state immediately on the next Streamlit rerun.
    _write_servo_state({
        "mode": "MANUAL",
        "requestedH": h,
        "requestedV": v,
        "commandId": command_id,
        "status": "PENDING",
        "requestedAt": now_iso,
        "confirmedAt": None,
        "confirmedH": None,
        "confirmedV": None,
    }, merge=False)

    # 2. POST command to bridge /cmd queue.
    bridge_ok = False
    bridge_error = None
    try:
        resp = requests.post(
            f"{BRIDGE_URL}/cmd",
            json={"cmd": cmd_text},
            timeout=5,
        )
        if resp.ok:
            bridge_ok = True
            logger.info(
                "Servo command queued: %s (id=%s)", cmd_text, command_id
            )
        else:
            bridge_error = f"Bridge returned HTTP {resp.status_code}"
            logger.warning("Bridge /cmd POST failed: %s", bridge_error)
    except requests.exceptions.ConnectionError:
        bridge_error = (
            "Bridge server is not reachable at "
            f"{BRIDGE_URL}. Is firebase_bridge.py running?"
        )
        logger.warning("Bridge unreachable: %s", bridge_error)
    except requests.exceptions.Timeout:
        bridge_error = "Bridge /cmd POST timed out."
        logger.warning(bridge_error)
    except Exception as exc:
        bridge_error = str(exc)
        logger.exception("Unexpected error posting to bridge /cmd")

    if not bridge_ok:
        # Mark as FAILED immediately — we know the command was not queued.
        _write_servo_state({
            "status": "FAILED",
            "lastError": bridge_error or "Unknown bridge error",
        })
        return {"ok": False, "command_id": command_id, "error": bridge_error}

    return {"ok": True, "command_id": command_id, "error": None}


# ---------------------------------------------------------------------------
# Confirmation check
# ---------------------------------------------------------------------------

def check_and_confirm(
    servo_state: Dict[str, Any],
    tracking: Dict[str, Any],
) -> Optional[str]:
    """
    Check whether the Arduino's reported angles match the last request.

    This is called every dashboard refresh.  It does NOT send any commands.

    Parameters
    ----------
    servo_state : dict — current /floatingSolarPanel/servoControl node
    tracking    : dict — current /floatingSolarPanel/tracking node

    Returns the new status string if it changed, else None.
    """
    if servo_state.get("status") != "PENDING":
        return None

    requested_h = servo_state.get("requestedH")
    requested_v = servo_state.get("requestedV")
    if requested_h is None or requested_v is None:
        return None

    actual_h = tracking.get("horizontalAngle")
    actual_v = tracking.get("verticalAngle")
    if actual_h is None or actual_v is None:
        return None

    # Check timeout.
    requested_at_str = servo_state.get("requestedAt")
    if requested_at_str:
        try:
            requested_at = datetime.fromisoformat(requested_at_str)
            elapsed = (
                datetime.now(timezone.utc).astimezone() - requested_at
            ).total_seconds()
            if elapsed > CONFIRM_TIMEOUT_SEC:
                now_iso = datetime.now(
                    timezone.utc
                ).astimezone().isoformat(timespec="seconds")
                _write_servo_state({
                    "status": "FAILED",
                    "lastError": (
                        f"No confirmation after {CONFIRM_TIMEOUT_SEC}s. "
                        "The Arduino may not support SERVO: commands, "
                        "or the extension was not connected."
                    ),
                    "confirmedAt": now_iso,
                })
                return "FAILED"
        except ValueError:
            pass

    # Check angle proximity.
    if (
        abs(int(actual_h) - int(requested_h)) <= CONFIRM_TOLERANCE_DEG
        and abs(int(actual_v) - int(requested_v)) <= CONFIRM_TOLERANCE_DEG
    ):
        now_iso = datetime.now(
            timezone.utc
        ).astimezone().isoformat(timespec="seconds")
        _write_servo_state({
            "status": "CONFIRMED",
            "confirmedAt": now_iso,
            "confirmedH": int(actual_h),
            "confirmedV": int(actual_v),
        })
        logger.info(
            "Servo command confirmed: H=%s V=%s", actual_h, actual_v
        )
        return "CONFIRMED"

    return None  # Still PENDING.


# ---------------------------------------------------------------------------
# Mode switch
# ---------------------------------------------------------------------------

def set_mode_auto() -> bool:
    """
    Switch to AUTO mode (LDR tracking).

    Does NOT send any serial command — the Arduino's LDR loop resumes
    naturally.  Writes mode=AUTO to Firebase so the dashboard reflects it.
    """
    return _write_servo_state({"mode": "AUTO", "status": "IDLE"})
