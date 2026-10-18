
from collections import deque
from pathlib import Path
from queue import Queue, Empty
from threading import Lock
from time import time
import csv
import io
import os

import firebase_admin
from firebase_admin import credentials, db
from flask import Flask, jsonify, request, Response
from dotenv import load_dotenv

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")
KEY_FILE = Path(
    os.getenv("FIREBASE_KEY_PATH", str(BASE_DIR / "serviceAccountKey.json"))
)
if not KEY_FILE.is_absolute():
    KEY_FILE = BASE_DIR / KEY_FILE

DATABASE_URL = os.getenv(
    "FIREBASE_DATABASE_URL",
    "https://floating-solar-panel-default-rtdb."
    "asia-southeast1.firebasedatabase.app/",
)

if firebase_admin._DEFAULT_APP_NAME not in firebase_admin._apps:
    cred = credentials.Certificate(str(KEY_FILE))
    firebase_admin.initialize_app(
        cred,
        {"databaseURL": DATABASE_URL}
    )

sensor_ref = db.reference("/floatingSolarPanel/sensors")
tracking_ref = db.reference("/floatingSolarPanel/tracking")

logs = deque(maxlen=200)
log_lock = Lock()
command_queue = Queue()
sequence = 0


def process_serial_line(raw_line):
    """Parse TL,TR,BL,BR,ServoX,ServoY,pH,SolarV."""
    global sequence

    raw_line = raw_line.strip()

    if not raw_line:
        return "ignored"

    try:
        values = next(csv.reader(io.StringIO(raw_line)))

        # Skip the CSV header printed by Arduino setup()
        if values[0].strip().upper() == "TL":
            return "header"

        if len(values) != 8:
            raise ValueError("Expected exactly 8 CSV values")

        tl, tr, bl, br, servo_x, servo_y = map(
            int, values[:6]
        )
        ph = float(values[6])
        solar_v = float(values[7])

        if any(v < 0 or v > 1023 for v in [tl, tr, bl, br]):
            raise ValueError("LDR readings must be 0–1023")

        if not (0 <= servo_x <= 180 and 0 <= servo_y <= 180):
            raise ValueError("Servo angles must be 0–180")

        if not (0 <= ph <= 14 and 0 <= solar_v <= 5.0):
            raise ValueError("pH or voltage outside expected range")

        # Update only these sensor fields.
        # Other existing fields, such as temperature and humidity,
        # are not replaced.
        sensor_ref.update({
            "topLeft": tl,
            "topRight": tr,
            "bottomLeft": bl,
            "bottomRight": br,
            "ph": ph,
            "solarVoltage": solar_v,
        })

        # Update only tracking fields.
        tracking_ref.update({
            "horizontalAngle": servo_x,
            "verticalAngle": servo_y,
            "status": "TRACKING",
        })

        with log_lock:
            sequence += 1
            logs.append({
                "seq": sequence,
                "line": raw_line,
                "time": time(),
            })

        print(
            f"Firebase updated | LDR={tl},{tr},{bl},{br} "
            f"| servo={servo_x},{servo_y} "
            f"| pH={ph:.2f} | SolarV={solar_v:.2f}"
        )

        return "updated"

    except Exception as exc:
        print(f"Rejected serial line: {raw_line!r} | {exc}")
        return "invalid"


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "solar-bridge"})


@app.get("/send")
def receive_serial():
    raw_line = request.args.get("out", "")
    result = process_serial_line(raw_line)

    status_code = 200 if result in ("updated", "header", "ignored") else 400

    return jsonify({"result": result}), status_code


@app.get("/getLog")
def get_latest_log():
    with log_lock:
        latest = logs[-1]["line"] if logs else ""
    return Response(latest, mimetype="text/plain")


@app.get("/log")
def get_logs():
    since = request.args.get("since", default=0, type=int)
    limit = request.args.get("n", default=50, type=int)
    limit = max(1, min(limit, 200))

    with log_lock:
        items = [item for item in logs if item["seq"] > since]
        items = items[-limit:]
        latest = logs[-1]["line"] if logs else ""

    return jsonify({
        "seq": sequence,
        "latest": latest,
        "lines": items,
    })


@app.route("/cmd", methods=["GET", "POST"])
def commands():
    if request.method == "POST":
        body = request.get_json(silent=True)

        if isinstance(body, dict):
            command = str(body.get("cmd", ""))
        else:
            command = request.get_data(as_text=True)

        if command:
            command_queue.put(command)

        return jsonify({"queued": bool(command)})

    try:
        return Response(command_queue.get_nowait(), mimetype="text/plain")
    except Empty:
        return Response("", mimetype="text/plain")


@app.post("/reset")
def reset():
    with log_lock:
        logs.clear()
    return jsonify({"status": "logs cleared"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=False)
