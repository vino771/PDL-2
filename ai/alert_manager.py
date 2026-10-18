"""
alert_manager.py
-----------------
AI Alert Manager — integrates with existing alert infrastructure.

Since the existing project did not have an email/Telegram alert system,
this module implements it from scratch using the same .env configuration.
Cooldown/de-duplication prevents repeated alerts for the same condition.
"""

import logging
import os
import smtplib
import time
from email.mime.text import MIMEText
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger("ALERT")

# ---- Configuration ----
EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
EMAIL_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))

TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

ALERT_COOLDOWN = int(os.getenv("ALERT_COOLDOWN_SECONDS", "300"))

# ---- State ----
_last_alert_time: Dict[str, float] = {}
_last_alert_risk: Optional[str] = None


def _should_alert(risk: str, action: str) -> bool:
    """Return True if enough time has passed since the last alert for this risk level."""
    global _last_alert_risk
    now = time.time()
    key = f"{risk}:{action}"
    last = _last_alert_time.get(key, 0)
    if (now - last) >= ALERT_COOLDOWN:
        _last_alert_time[key] = now
        _last_alert_risk = risk
        return True
    return False


def _format_message(result: Dict[str, Any]) -> str:
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M")
    risk = result.get("overall_risk", "N/A")
    action = result.get("final_action", result.get("recommended_action", "N/A"))
    reason = result.get("reason", "N/A")
    maint = "⚠️ INSPECTION RECOMMENDED" if result.get("maintenance_required") else "✅ Not required"
    override = ""
    if result.get("safety_override"):
        override = "\n🔒 SAFETY RULE OVERRIDE ACTIVE"
    return (
        f"⚠️ FLOATING SOLAR AI ALERT\n\n"
        f"Risk Level: {risk}\n\n"
        f"Issue:\n{reason}\n\n"
        f"AI Recommendation:\n{action}\n\n"
        f"Maintenance:\n{maint}"
        f"{override}\n\n"
        f"Time: {ts}"
    )


def send_email_alert(result: Dict[str, Any]) -> bool:
    """Send an email alert. Returns True on success."""
    if not EMAIL_ENABLED:
        return False
    if not all([EMAIL_FROM, EMAIL_PASSWORD, EMAIL_TO]):
        logger.warning("Email alert enabled but credentials not configured.")
        return False

    msg_text = _format_message(result)
    risk = result.get("overall_risk", "N/A")

    try:
        msg = MIMEText(msg_text)
        msg["Subject"] = f"🚨 Solar Panel AI Alert — Risk: {risk}"
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO

        with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)

        logger.info(f"Email alert sent to {EMAIL_TO}.")
        return True
    except Exception as exc:
        logger.error(f"Email alert failed: {exc}")
        return False


def send_telegram_alert(result: Dict[str, Any]) -> bool:
    """Send a Telegram alert. Returns True on success."""
    if not TELEGRAM_ENABLED:
        return False
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        logger.warning("Telegram alert enabled but bot token/chat ID not configured.")
        return False

    msg_text = _format_message(result)
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        resp = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg_text},
            timeout=10,
        )
        if resp.ok:
            logger.info("Telegram alert sent.")
            return True
        else:
            logger.error(f"Telegram API error: {resp.text}")
            return False
    except Exception as exc:
        logger.error(f"Telegram alert failed: {exc}")
        return False


def maybe_send_alert(result: Dict[str, Any]) -> None:
    """
    Send alerts if conditions are met and cooldown has elapsed.
    Only sends for MEDIUM or HIGH risk.
    """
    risk = result.get("overall_risk", "LOW")
    action = result.get("final_action", result.get("recommended_action", "MONITOR"))

    if risk not in ("MEDIUM", "HIGH"):
        return

    if not _should_alert(risk, action):
        logger.debug(f"Alert suppressed — cooldown active for {risk}:{action}.")
        return

    logger.info(f"Sending alerts for risk={risk}, action={action}.")
    send_email_alert(result)
    send_telegram_alert(result)
