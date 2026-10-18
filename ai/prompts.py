"""
prompts.py
----------
Prompt templates for each AI agent.

All prompts ask Ollama to return structured JSON only.
The prompts are intentionally concise for the lightweight qwen2.5:0.5b model.
"""


def electrical_agent_prompt(data: dict) -> str:
    voltage = data.get("voltage", "N/A")
    current = data.get("current", "N/A")
    power = data.get("power", "N/A")
    ldr_avg = data.get("ldr_avg", "N/A")

    return f"""You are an electrical risk analyst for a floating solar panel system.
Sensor data:
- Voltage: {voltage}
- Current: {current}
- Power: {power}
- LDR average: {ldr_avg}

Fields showing N/A are not available in this system.

Analyse the risk of electrical issues. Reply ONLY with valid JSON in this exact format:
{{
  "risk": "LOW|MEDIUM|HIGH",
  "confidence": <0.0-1.0>,
  "reason": "<short explanation>",
  "recommended_action": "MONITOR|SAFE_MODE|INSPECTION_REQUIRED"
}}"""


def environmental_agent_prompt(data: dict, history: list) -> str:
    temperature = data.get("temperature", "N/A")
    humidity = data.get("humidity", "N/A")
    water_level = data.get("waterLevel", "N/A")
    ph = data.get("pH", "N/A")
    tracking_status = data.get("trackingStatus", "N/A")

    history_str = "No historical data available."
    if history:
        temps = [str(h.get("sensors", {}).get("temperature", "?")) for h in history[-5:]]
        wls = [str(h.get("sensors", {}).get("waterLevel", "?")) for h in history[-5:]]
        history_str = f"Recent temperatures: {' → '.join(temps)}\nRecent water levels: {' → '.join(wls)}"

    return f"""You are an environmental risk analyst for a floating solar panel system.
Current sensor data:
- Temperature: {temperature} °C
- Humidity: {humidity} %
- Water Level: {water_level} %
- pH: {ph}
- Tracking Status: {tracking_status}

{history_str}

Analyse environmental risk. Reply ONLY with valid JSON in this exact format:
{{
  "risk": "LOW|MEDIUM|HIGH",
  "confidence": <0.0-1.0>,
  "reason": "<short explanation>",
  "recommended_action": "MONITOR|SAFE_MODE|INSPECTION_REQUIRED"
}}"""


def maintenance_agent_prompt(data: dict, history: list) -> str:
    ldr_top_left = data.get("topLeft", "N/A")
    ldr_top_right = data.get("topRight", "N/A")
    ldr_bot_left = data.get("bottomLeft", "N/A")
    ldr_bot_right = data.get("bottomRight", "N/A")
    h_angle = data.get("horizontalAngle", "N/A")
    v_angle = data.get("verticalAngle", "N/A")
    temp_status = data.get("temperatureStatus", "N/A")
    water_status = data.get("waterStatus", "N/A")
    ldr_status = data.get("ldrStatus", "N/A")

    history_str = "No historical data available."
    if history:
        recent = history[-5:]
        history_str = f"Last {len(recent)} readings available for trend analysis."

    return f"""You are a predictive maintenance analyst for a floating solar panel system.
Current readings:
- LDR: TopLeft={ldr_top_left}, TopRight={ldr_top_right}, BottomLeft={ldr_bot_left}, BottomRight={ldr_bot_right}
- Solar Tracking: H={h_angle}° V={v_angle}°
- System Status: temperature={temp_status}, water={water_status}, ldr={ldr_status}

{history_str}

Predict maintenance needs. Use conservative language (e.g., "possible anomaly", "inspection recommended").
Reply ONLY with valid JSON in this exact format:
{{
  "maintenance_required": true|false,
  "priority": "LOW|MEDIUM|HIGH",
  "reason": "<short explanation>",
  "recommended_action": "NONE|MONITOR|INSPECTION_REQUIRED|IMMEDIATE_ACTION"
}}"""


def decision_agent_prompt(electrical: dict, environmental: dict, maintenance: dict) -> str:
    return f"""You are the decision orchestrator for a floating solar panel AI safety system.

Agent results:
- Electrical risk: {electrical.get('risk', 'N/A')} (confidence: {electrical.get('confidence', 'N/A')})
- Environmental risk: {environmental.get('risk', 'N/A')} (confidence: {environmental.get('confidence', 'N/A')})
- Maintenance priority: {maintenance.get('priority', 'N/A')} (required: {maintenance.get('maintenance_required', 'N/A')})

Combine the above to produce a final safety decision.
Reply ONLY with valid JSON in this exact format:
{{
  "overall_risk": "LOW|MEDIUM|HIGH",
  "confidence": <0.0-1.0>,
  "recommended_action": "MONITOR|SAFE_MODE|INSPECTION_REQUIRED",
  "reason": "<short explanation combining all agent findings>",
  "maintenance_required": true|false
}}"""
