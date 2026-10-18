# pyrefly: ignore [missing-import]
import uuid
import streamlit as st
from firebase_service import get_data
import requests
import os

st.set_page_config(
    page_title="Floating Solar Panel",
    page_icon="☀️",
    layout="wide"
)

# ---------------------------------------------------------------------------
# Session-state initialisation (runs once per browser session)
# ---------------------------------------------------------------------------

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []          # list of {"role":..,"content":..}

if "servo_apply_clicked" not in st.session_state:
    st.session_state.servo_apply_clicked = False

if "servo_last_result" not in st.session_state:
    st.session_state.servo_last_result = None   # dict from send_servo_command()

# Bridge URL (used for servo commands)
BRIDGE_URL = os.getenv("BRIDGE_URL", "http://127.0.0.1:8080")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_servo_state():
    """Read /floatingSolarPanel/servoControl from Firebase via firebase_service."""
    try:
        import firebase_admin
        from firebase_admin import db
        ref = db.reference("/floatingSolarPanel/servoControl")
        data = ref.get()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _set_mode_auto():
    """Write mode=AUTO, status=IDLE to Firebase servoControl node."""
    try:
        import firebase_admin
        from firebase_admin import db
        ref = db.reference("/floatingSolarPanel/servoControl")
        ref.update({"mode": "AUTO", "status": "IDLE"})
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Main dashboard fragment (existing — refreshes every 30s)
# ---------------------------------------------------------------------------

@st.fragment(run_every="30s")
def render_dashboard():
    st.title("☀️ Floating Solar Panel Monitoring System")
    st.write("Real-time monitoring dashboard")

    read_failed = False
    try:
        data = get_data()
    except Exception:
        data = {}
        read_failed = True
        st.error("Firebase read failed; check the dashboard server logs.")

    if not isinstance(data, dict):
        data = {}
        if not read_failed:
            st.error("No data received from Firebase.")

    sensors = data.get("sensors")
    sensors = sensors if isinstance(sensors, dict) else {}
    tracking = data.get("tracking")
    tracking = tracking if isinstance(tracking, dict) else {}
    system = data.get("system")
    system = system if isinstance(system, dict) else {}

    # -----------------------------
    # SENSOR DATA
    # -----------------------------

    st.header("🌡️ Environmental Monitoring")
    col1, col2, col3 = st.columns(3)

    with col1:
        temperature = sensors.get("temperature")
        st.metric(
            "Temperature",
            f"{temperature} °C" if temperature is not None else "N/A"
        )

    with col2:
        humidity = sensors.get("humidity")
        st.metric(
            "Humidity",
            f"{humidity} %" if humidity is not None else "N/A"
        )

    with col3:
        water_level = sensors.get("waterLevel")
        st.metric(
            "Water Level",
            f"{water_level} %" if water_level is not None else "N/A"
        )

    # -----------------------------
    # pH AND SOLAR VOLTAGE
    # -----------------------------

    st.subheader("🧪 Water Quality & Electrical Monitoring")
    ph_value = sensors.get(
        "pH",
        sensors.get("ph", sensors.get("waterPH"))
    )
    solar_voltage = sensors.get(
        "solarVoltage",
        sensors.get("solarV", sensors.get("voltage"))
    )

    col_ph, col_voltage = st.columns(2)
    with col_ph:
        st.metric(
            "Water pH",
            f"{ph_value}" if ph_value is not None else "N/A"
        )
    with col_voltage:
        st.metric(
            "Solar Voltage",
            f"{solar_voltage} V" if solar_voltage is not None else "N/A"
        )

    # -----------------------------
    # SOLAR TRACKING
    # -----------------------------

    st.header("🔄 Solar Tracking")
    col1, col2, col3 = st.columns(3)

    with col1:
        horizontal_angle = tracking.get("horizontalAngle")
        st.metric(
            "Horizontal Angle",
            f"{horizontal_angle}°" if horizontal_angle is not None else "N/A"
        )

    with col2:
        vertical_angle = tracking.get("verticalAngle")
        st.metric(
            "Vertical Angle",
            f"{vertical_angle}°" if vertical_angle is not None else "N/A"
        )

    with col3:
        st.metric("Tracking Status", tracking.get("status", "UNKNOWN"))

    # -----------------------------
    # LDR
    # -----------------------------

    st.header("☀️ LDR Sensors")
    col1, col2, col3, col4 = st.columns(4)

    for column, key, label in zip(
        (col1, col2, col3, col4),
        ("topLeft", "topRight", "bottomLeft", "bottomRight"),
        ("Top Left", "Top Right", "Bottom Left", "Bottom Right"),
    ):
        with column:
            value = sensors.get(key)
            st.metric(label, value if value is not None else "N/A")

    # -----------------------------
    # SYSTEM STATUS
    # -----------------------------

    st.header("⚠️ System Status")
    st.write("Temperature Status:", system.get("temperatureStatus", "UNKNOWN"))
    st.write("Water Status:", system.get("waterStatus", "UNKNOWN"))
    st.write("LDR Status:", system.get("ldrStatus", "UNKNOWN"))
    st.write("Overall Status:", system.get("overallStatus", "UNKNOWN"))

    # -----------------------------
    # AI SAFETY & PREDICTION
    # -----------------------------

    st.divider()
    st.header("🤖 AI Safety & Prediction")
    ai_data = data.get("aiAnalysis")
    ai_data = ai_data if isinstance(ai_data, dict) else {}
    has_analysis = (
        "overall_risk" in ai_data and "evaluated_at" in ai_data
    )

    ai_status = ai_data.get("aiStatus", "AI OFFLINE")
    status_colors = {
        "AI ONLINE": "🟢",
        "AI ANALYZING": "🔵",
        "AI WARNING": "🟠",
        "AI ERROR": "🔴",
        "AI OFFLINE": "⚫",
    }
    st.write(
        f"**AI System Status:** "
        f"{status_colors.get(ai_status, '⚪')} {ai_status}"
    )

    last_error = ai_data.get("lastError")
    if last_error:
        st.error(f"AI service diagnostic: {last_error}")
    if not has_analysis:
        st.info("No completed AI analysis is available yet.")

    overall_risk = ai_data.get("overall_risk", "N/A") if has_analysis else "N/A"
    risk_colors = {
        "HIGH": "🔴",
        "MEDIUM": "🟠",
        "LOW": "🟢",
        "UNKNOWN": "⚪",
        "N/A": "⚪",
    }
    risk_icon = risk_colors.get(str(overall_risk).upper(), "⚪")
    confidence = ai_data.get("confidence") if has_analysis else None
    try:
        confidence_display = (
            f"{float(confidence) * 100:g}%"
            if confidence is not None
            else "N/A"
        )
    except (TypeError, ValueError):
        confidence_display = "N/A"

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric("Overall Risk", f"{risk_icon} {overall_risk}")
    with col_b:
        st.metric("AI Confidence", confidence_display)
    with col_c:
        st.metric(
            "Recommended Action",
            (
                ai_data.get(
                    "final_action",
                    ai_data.get("recommended_action", "N/A")
                )
                if has_analysis else "N/A"
            )
        )

    st.subheader("Agent Analysis")
    col_e, col_v, col_m = st.columns(3)
    electrical_risk = ai_data.get("electrical_risk", "N/A") if has_analysis else "N/A"
    environmental_risk = (
        ai_data.get("environmental_risk", "N/A") if has_analysis else "N/A"
    )
    with col_e:
        st.metric(
            "⚡ Electrical Risk",
            f"{risk_colors.get(str(electrical_risk).upper(), '⚪')} "
            f"{electrical_risk}"
        )
    with col_v:
        st.metric(
            "🌿 Environmental Risk",
            f"{risk_colors.get(str(environmental_risk).upper(), '⚪')} "
            f"{environmental_risk}"
        )

    maintenance_required = (
        ai_data.get("maintenance_required") if has_analysis else None
    )
    maintenance_priority = (
        ai_data.get("maintenance_priority", "N/A") if has_analysis else "N/A"
    )
    with col_m:
        if isinstance(maintenance_required, bool):
            maintenance_display = (
                "⚠️ Required" if maintenance_required else "✅ Not Required"
            )
        else:
            maintenance_display = "N/A"
        st.metric("🔧 Maintenance", maintenance_display)

    st.subheader("AI Reasoning")
    reason = ai_data.get("reason") if has_analysis else None
    st.info(
        reason if isinstance(reason, str) and reason else
        "No completed analysis reasoning is available."
    )

    if has_analysis and ai_data.get("safety_override"):
        st.warning(
            "🔒 **Safety Rule Override Active** — The deterministic safety controller "
            "escalated the action beyond the AI recommendation."
        )

    simulated_action = ai_data.get("simulated_action") if has_analysis else None
    if simulated_action:
        st.subheader("Simulated Action")
        st.code(simulated_action, language=None)

    if maintenance_required is True:
        st.warning(
            f"⚠️ **Maintenance Required** | Priority: **{maintenance_priority}**\n\n"
            "Inspection recommended before next operational cycle."
        )
    elif maintenance_required is False:
        st.success("✅ No maintenance action required at this time.")

    timestamp = (
        ai_data.get("evaluated_at")
        or ai_data.get("lastUpdated", "Never")
        if has_analysis else
        "Never"
    )
    st.caption(f"Last AI Analysis: {timestamp}")

    # -------------------------------------------------------------------------
    # Store latest data snapshot in session_state so chatbot can access it
    # -------------------------------------------------------------------------
    st.session_state["_latest_firebase_data"] = data


# ---------------------------------------------------------------------------
# SERVO CONTROL SECTION (new — does not use @st.fragment so button clicks
# trigger a full rerun, which is what we want for explicit user actions)
# ---------------------------------------------------------------------------

def render_servo_control():
    st.divider()
    st.header("🎛️ Servo Position Control")

    servo_state = _get_servo_state()
    current_mode = servo_state.get("mode", "AUTO")
    current_status = servo_state.get("status", "IDLE")

    # ---- Mode selector ----
    st.subheader("Control Mode")
    mode_col, status_col = st.columns([2, 3])

    with mode_col:
        mode_choice = st.radio(
            "Servo Mode",
            options=["AUTO (LDR Tracking)", "MANUAL (Dashboard Control)"],
            index=0 if current_mode != "MANUAL" else 1,
            key="servo_mode_radio",
            help=(
                "AUTO: Arduino uses LDR sensors to track the sun automatically.\n"
                "MANUAL: Send specific angle commands from this dashboard.\n"
                "Note: switching back to AUTO does not send a command; "
                "the Arduino's LDR loop resumes naturally."
            ),
        )

    with status_col:
        status_icons = {
            "IDLE": "⚪ IDLE",
            "PENDING": "🔵 PENDING — command sent, waiting for Arduino to report back",
            "CONFIRMED": "🟢 CONFIRMED — Arduino reported matching angles",
            "FAILED": "🔴 FAILED — no confirmation received in time",
        }
        st.info(
            f"**Current mode:** {current_mode}  \n"
            f"**Command status:** {status_icons.get(current_status, current_status)}"
        )
        if current_status == "CONFIRMED":
            st.caption(
                f"Confirmed at: {servo_state.get('confirmedAt', '?')}  \n"
                f"Confirmed H={servo_state.get('confirmedH', '?')}°  "
                f"V={servo_state.get('confirmedV', '?')}°"
            )
        if current_status == "FAILED":
            err = servo_state.get("lastError", "")
            if err:
                st.warning(f"Reason: {err}")

    # ---- Switch to AUTO ----
    is_manual_selected = "MANUAL" in mode_choice
    if not is_manual_selected:
        if current_mode == "MANUAL":
            if st.button(
                "↩️ Switch to AUTO (LDR Tracking)",
                key="servo_switch_auto_btn",
            ):
                if _set_mode_auto():
                    st.success(
                        "Mode set to AUTO. "
                        "The Arduino's LDR tracking will resume on its next cycle."
                    )
                    st.rerun()
                else:
                    st.error("Failed to update Firebase. Check logs.")
        else:
            st.info(
                "Currently in AUTO mode — LDR tracking is active. "
                "Select MANUAL above to send specific angle commands."
            )
        return  # Nothing more to show in AUTO mode.

    # ---- MANUAL mode controls ----
    st.subheader("Manual Servo Position")
    st.caption(
        "ℹ️ **Requirement:** The Arduino sketch must handle `SERVO:H=<n>:V=<n>` "
        "commands in its `Serial.available()` loop. If it does not, the command "
        "will be injected but silently ignored, and the status will show **FAILED** "
        "after 30 seconds."
    )

    req_h = servo_state.get("requestedH", 90)
    req_v = servo_state.get("requestedV", 45)

    angle_col1, angle_col2 = st.columns(2)
    with angle_col1:
        h_angle = st.number_input(
            "Horizontal Angle (°)",
            min_value=0,
            max_value=180,
            value=int(req_h) if req_h is not None else 90,
            step=1,
            key="servo_h_input",
            help="Horizontal servo position: 0–180 degrees.",
        )
    with angle_col2:
        v_angle = st.number_input(
            "Vertical Angle (°)",
            min_value=0,
            max_value=180,
            value=int(req_v) if req_v is not None else 45,
            step=1,
            key="servo_v_input",
            help="Vertical servo position: 0–180 degrees.",
        )

    st.caption(
        "Click **Apply Position** to send the command. "
        "Adjusting the sliders alone does NOT send a command."
    )

    # ---- Apply button (explicit action — avoids accidental duplicate commands) ----
    if st.button(
        "📡 Apply Position",
        key="servo_apply_btn",
        type="primary",
        help="Sends the SERVO command to the Arduino via the bridge.",
    ):
        # Import locally to avoid circular issues and keep the top of app.py clean.
        from servo_control import send_servo_command
        result = send_servo_command(int(h_angle), int(v_angle))
        st.session_state.servo_last_result = result

    # Show result of the most recent apply click.
    last_result = st.session_state.get("servo_last_result")
    if last_result is not None:
        if last_result.get("ok"):
            st.success(
                f"✅ Command queued (ID: `{last_result.get('command_id')}`).  \n"
                "The Chrome extension will inject it into the Tinkercad serial "
                "input on its next poll (≤2 s).  \n"
                "Status will change to **CONFIRMED** once the Arduino "
                "reports back matching angles, or **FAILED** after 30 s."
            )
        else:
            st.error(
                f"❌ Command failed: {last_result.get('error', 'Unknown error')}  \n"
                "Ensure `firebase_bridge.py` is running and the Chrome extension "
                "is connected to an active Tinkercad simulation."
            )

    # ---- Live tracking comparison ----
    with st.expander("📊 Live tracking vs requested", expanded=False):
        try:
            data = get_data() or {}
        except Exception:
            data = {}
        tracking = data.get("tracking") or {}
        actual_h = tracking.get("horizontalAngle", "N/A")
        actual_v = tracking.get("verticalAngle", "N/A")
        req_h_now = servo_state.get("requestedH", "—")
        req_v_now = servo_state.get("requestedV", "—")
        comp_col1, comp_col2 = st.columns(2)
        with comp_col1:
            st.metric("Requested H", f"{req_h_now}°" if req_h_now != "—" else "—")
            st.metric("Actual H (from Arduino)", f"{actual_h}°" if actual_h != "N/A" else "N/A")
        with comp_col2:
            st.metric("Requested V", f"{req_v_now}°" if req_v_now != "—" else "—")
            st.metric("Actual V (from Arduino)", f"{actual_v}°" if actual_v != "N/A" else "N/A")
        st.caption(
            "Actual values are from the latest Arduino CSV upload. "
            "They update as new serial data arrives through the bridge."
        )

    # ---- Architecture note ----
    with st.expander("ℹ️ How command delivery works", expanded=False):
        st.markdown(
            """
**Command delivery path:**

```
Dashboard (Apply Position)
  → POST http://127.0.0.1:8080/cmd  (firebase_bridge.py Flask server)
    → in-memory command queue
      → Chrome extension content.js (polls /cmd every 2 s)
        → Tinkercad serial input box (typed + button clicked by extension)
          → Arduino Serial.available() handler
            → Servo movement (if Arduino supports SERVO:H=n:V=n)
              → Next CSV line reported: TL,TR,BL,BR,ServoX,ServoY,pH,SolarV
                → firebase_bridge.py confirms command (angles match ±3°)
```

**Limitations:**
- The command is injected as text into the Tinkercad serial monitor input.
  The Arduino must explicitly parse `SERVO:H=<n>:V=<n>` strings.
- If the Arduino sketch only does LDR tracking without parsing serial input,
  the command will arrive but be silently ignored.
- "CONFIRMED" status means the Arduino **reported** angles matching the request;
  it does NOT mean the servo physically moved to a specific physical position.
- The bridge uses an **in-memory** queue; restarting `firebase_bridge.py`
  drops any queued but undelivered commands.
            """
        )


# ---------------------------------------------------------------------------
# CHATBOT SECTION (new — below AI analysis, read-only)
# ---------------------------------------------------------------------------

def render_chatbot():
    st.divider()
    st.header("💬 FPS Assistant (Powered by Ollama qwen2.5:0.5b)")
    st.caption(
        "Ask questions about current sensor readings, AI analysis, risk levels, "
        "maintenance, and operational guidance.  \n"
        "⚠️ **This chatbot is strictly read-only.** "
        "To control servos, use the Servo Control section above."
    )

    # ---- Import chatbot helpers ----
    try:
        from ai.chatbot import chat_with_ollama, build_context_snapshot
    except ImportError as e:
        st.error(f"Chatbot module could not be loaded: {e}")
        return

    # ---- Build context from latest Firebase snapshot ----
    latest_data = st.session_state.get("_latest_firebase_data", {})
    context = build_context_snapshot(latest_data)

    # ---- Display conversation history ----
    chat_container = st.container()
    with chat_container:
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    # ---- Chat input ----
    user_input = st.chat_input(
        "Ask about sensor readings, risk levels, maintenance…",
        key="fps_chat_input",
    )

    if user_input:
        # Append user message.
        st.session_state.chat_history.append(
            {"role": "user", "content": user_input}
        )
        with chat_container:
            with st.chat_message("user"):
                st.markdown(user_input)

        # Get reply from Ollama.
        with chat_container:
            with st.chat_message("assistant"):
                with st.spinner("Thinking…"):
                    # Only pass the last 10 turns to avoid token overflow.
                    recent = st.session_state.chat_history[-10:]
                    reply = chat_with_ollama(recent, context)
                st.markdown(reply)

        # Append assistant reply.
        st.session_state.chat_history.append(
            {"role": "assistant", "content": reply}
        )

    # ---- Chat controls ----
    if st.session_state.chat_history:
        if st.button("🗑️ Clear chat history", key="clear_chat_btn"):
            st.session_state.chat_history = []
            st.rerun()

    # ---- Context preview (collapsed) ----
    with st.expander("🔍 Sensor context sent to model", expanded=False):
        if latest_data:
            st.code(context, language="text")
        else:
            st.info(
                "No Firebase data available yet. "
                "The dashboard refreshes every 30 s — please wait."
            )


# ---------------------------------------------------------------------------
# Page assembly
# ---------------------------------------------------------------------------

render_dashboard()
render_servo_control()
render_chatbot()
