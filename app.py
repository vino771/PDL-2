import streamlit as st
from firebase_service import get_data


st.set_page_config(
    page_title="Floating Solar Panel",
    page_icon="☀️",
    layout="wide"
)


st.title("☀️ Floating Solar Panel Monitoring System")

st.write(
    "Real-time monitoring dashboard"
)


data = get_data()


if data:

    sensors = data.get("sensors", {})
    tracking = data.get("tracking", {})
    system = data.get("system", {})


    # -----------------------------
    # SENSOR DATA
    # -----------------------------

    st.header("🌡️ Environmental Monitoring")


    col1, col2, col3 = st.columns(3)


    with col1:

        st.metric(
            "Temperature",
            f"{sensors.get('temperature', 0)} °C"
        )


    with col2:

        st.metric(
            "Humidity",
            f"{sensors.get('humidity', 0)} %"
        )


    with col3:

        st.metric(
            "Water Level",
            f"{sensors.get('waterLevel', 0)} %"
        )


    # -----------------------------
    # SOLAR TRACKING
    # -----------------------------

    st.header("🔄 Solar Tracking")


    col1, col2, col3 = st.columns(3)


    with col1:

        st.metric(
            "Horizontal Angle",
            f"{tracking.get('horizontalAngle', 0)}°"
        )


    with col2:

        st.metric(
            "Vertical Angle",
            f"{tracking.get('verticalAngle', 0)}°"
        )


    with col3:

        st.metric(
            "Tracking Status",
            tracking.get(
                "status",
                "UNKNOWN"
            )
        )


    # -----------------------------
    # LDR
    # -----------------------------

    st.header("☀️ LDR Sensors")


    col1, col2, col3, col4 = st.columns(4)


    with col1:

        st.metric(
            "Top Left",
            sensors.get(
                "topLeft",
                0
            )
        )


    with col2:

        st.metric(
            "Top Right",
            sensors.get(
                "topRight",
                0
            )
        )


    with col3:

        st.metric(
            "Bottom Left",
            sensors.get(
                "bottomLeft",
                0
            )
        )


    with col4:

        st.metric(
            "Bottom Right",
            sensors.get(
                "bottomRight",
                0
            )
        )


    # -----------------------------
    # SYSTEM STATUS
    # -----------------------------

    st.header("⚠️ System Status")


    st.write(
        "Temperature Status:",
        system.get(
            "temperatureStatus",
            "UNKNOWN"
        )
    )


    st.write(
        "Water Status:",
        system.get(
            "waterStatus",
            "UNKNOWN"
        )
    )


    st.write(
        "LDR Status:",
        system.get(
            "ldrStatus",
            "UNKNOWN"
        )
    )


    st.write(
        "Overall Status:",
        system.get(
            "overallStatus",
            "UNKNOWN"
        )
    )


else:

    st.error(
        "No data received from Firebase."
    )