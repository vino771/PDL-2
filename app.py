# pyrefly: ignore [missing-import]
import streamlit as st
from firebase_service import get_data

st.set_page_config(
    page_title="Floating Solar Panel",
    page_icon="☀️",
    layout="wide"
)


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


render_dashboard()
