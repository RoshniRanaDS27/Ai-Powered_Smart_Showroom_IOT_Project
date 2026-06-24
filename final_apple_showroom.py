import RPi.GPIO as GPIO
import time
import sqlite3
import threading
from datetime import datetime
from flask import Flask, render_template_string

# ============================================
#  PIN CONFIGURATION
# ============================================
TRIG1 = 23
ECHO1 = 24
LED1 = 17
BUZZER1 = 18

TRIG2 = 5
ECHO2 = 6
LED2 = 27
BUZZER2 = 22

DIST_CM = 30
ANOMALY_SEC = 15.0
RECOMMEND_SEC = 17.0
GLITCH_FILTER = 5

PRODUCT_1 = "Apple Vision Pro"
PRODUCT_2 = "Apple Smart Ring"

# ============================================
#  FLASK + DATABASE
# ============================================
app = Flask(__name__)
DB_NAME = "showroom_logs.db"

latest_data = {
    "timestamp": "-",
    "dist1": "-",
    "dist2": "-",
    "dwell1": 0.0,
    "dwell2": 0.0,
    "score1": 0,
    "score2": 0,
    "led1": 0,
    "led2": 0,
    "buzzer1": 0,
    "buzzer2": 0,
    "status1": "Waiting",
    "status2": "Waiting",
    "system_status": "System Starting",
    "recommended_product": "No active recommendation",
    "recommendation_reason": "<li>Waiting for customer interaction</li>"
}

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sensor_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            sensor1_distance TEXT,
            sensor2_distance TEXT,
            sensor1_dwell REAL,
            sensor2_dwell REAL,
            sensor1_score REAL,
            sensor2_score REAL,
            led1_status INTEGER,
            led2_status INTEGER,
            buzzer1_status INTEGER,
            buzzer2_status INTEGER,
            recommended_product TEXT,
            recommendation_reason TEXT,
            system_status TEXT
        )
    """)

    conn.commit()
    conn.close()

def save_data():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO sensor_logs (
            timestamp,
            sensor1_distance,
            sensor2_distance,
            sensor1_dwell,
            sensor2_dwell,
            sensor1_score,
            sensor2_score,
            led1_status,
            led2_status,
            buzzer1_status,
            buzzer2_status,
            recommended_product,
            recommendation_reason,
            system_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        latest_data["timestamp"],
        str(latest_data["dist1"]),
        str(latest_data["dist2"]),
        latest_data["dwell1"],
        latest_data["dwell2"],
        latest_data["score1"],
        latest_data["score2"],
        latest_data["led1"],
        latest_data["led2"],
        latest_data["buzzer1"],
        latest_data["buzzer2"],
        latest_data["recommended_product"],
        latest_data["recommendation_reason"],
        latest_data["system_status"]
    ))

    conn.commit()
    conn.close()

# ============================================
#  GPIO SETUP
# ============================================
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

GPIO.setup(TRIG1, GPIO.OUT)
GPIO.setup(ECHO1, GPIO.IN)
GPIO.setup(LED1, GPIO.OUT)
GPIO.setup(BUZZER1, GPIO.OUT)

GPIO.setup(TRIG2, GPIO.OUT)
GPIO.setup(ECHO2, GPIO.IN)
GPIO.setup(LED2, GPIO.OUT)
GPIO.setup(BUZZER2, GPIO.OUT)

GPIO.output(TRIG1, GPIO.LOW)
GPIO.output(TRIG2, GPIO.LOW)
GPIO.output(LED1, GPIO.LOW)
GPIO.output(LED2, GPIO.LOW)
GPIO.output(BUZZER1, GPIO.LOW)
GPIO.output(BUZZER2, GPIO.LOW)

time.sleep(0.5)

# ============================================
#  ULTRASONIC MEASUREMENT
# ============================================
def measure_distance(trig, echo):
    GPIO.output(trig, GPIO.HIGH)
    time.sleep(0.00001)
    GPIO.output(trig, GPIO.LOW)

    timeout = time.time() + 0.04
    start = time.time()

    while GPIO.input(echo) == 0:
        start = time.time()
        if time.time() > timeout:
            return None

    stop = time.time()

    while GPIO.input(echo) == 1:
        stop = time.time()
        if time.time() > timeout:
            return None

    distance = (stop - start) * 34300 / 2
    return round(distance, 1)

# ============================================
#  ENGAGEMENT + RECOMMENDATION
# ============================================
def calculate_score(distance, dwell_time):
    if distance is None:
        return 0

    # Final practical scoring:
    # Score reaches 100 exactly when buzzer starts at 15 sec.
    # Recommendation appears 2 sec later at 17 sec.
    score = (min(dwell_time, ANOMALY_SEC) / ANOMALY_SEC) * 100

    return round(score, 1)

def get_dwell_status(dwell_time, detected):
    if not detected:
        return "No Detection"

    if dwell_time < 5:
        return "Browsing"

    if dwell_time < 12:
        return "Interested"

    if dwell_time < 15:
        return "Highly Interested"

    return "Engagement Alert"

def get_recommendation(score1, score2, dwell1, dwell2):
    if score1 >= 100 and dwell1 >= RECOMMEND_SEC and score1 >= score2:
        return (
            "Vision Pro Accessory Kit",
            """
            <li>Vision Pro Travel Case</li>
            <li>Extra Battery Holder</li>
            <li>Light Seal Cushion</li>
            <li>Lens Cleaning Kit</li>
            <li>AirPods Pro / Spatial Audio Earbuds</li>
            """
        )

    if score2 >= 100 and dwell2 >= RECOMMEND_SEC and score2 > score1:
        return (
            "Apple Smart Ring Band Kit",
            """
            <li>Premium Ring Band</li>
            <li>Magnetic Charging Dock</li>
            <li>Ring Protector</li>
            <li>Travel Pouch</li>
            <li>Wellness / Fitness Sync Pack</li>
            """
        )

    return (
        "No active recommendation",
        "<li>Customer engagement is not high enough for recommendation yet.</li>"
    )

def get_status_class(status):
    if status == "Browsing":
        return "status-browsing"
    if status == "Interested":
        return "status-interested"
    if status == "Highly Interested":
        return "status-high"
    if status == "Engagement Alert":
        return "status-alert"
    return "status-no"

# ============================================
#  SENSOR LOOP
# ============================================
def sensor_loop():
    global latest_data

    dwell_start1 = None
    dwell_start2 = None
    none_count1 = 0
    none_count2 = 0

    while True:
        current_time = time.time()

        dist1 = measure_distance(TRIG1, ECHO1)
        dist2 = measure_distance(TRIG2, ECHO2)

        # Sensor 1 logic
        if dist1 is not None and dist1 < DIST_CM:
            none_count1 = 0
            GPIO.output(LED1, GPIO.HIGH)

            if dwell_start1 is None:
                dwell_start1 = current_time

            if (current_time - dwell_start1) >= ANOMALY_SEC:
                GPIO.output(BUZZER1, GPIO.HIGH)
            else:
                GPIO.output(BUZZER1, GPIO.LOW)
        else:
            none_count1 += 1
            if none_count1 >= GLITCH_FILTER:
                dwell_start1 = None
                GPIO.output(LED1, GPIO.LOW)
                GPIO.output(BUZZER1, GPIO.LOW)

        # Sensor 2 logic
        if dist2 is not None and dist2 < DIST_CM:
            none_count2 = 0
            GPIO.output(LED2, GPIO.HIGH)

            if dwell_start2 is None:
                dwell_start2 = current_time

            if (current_time - dwell_start2) >= ANOMALY_SEC:
                GPIO.output(BUZZER2, GPIO.HIGH)
            else:
                GPIO.output(BUZZER2, GPIO.LOW)
        else:
            none_count2 += 1
            if none_count2 >= GLITCH_FILTER:
                dwell_start2 = None
                GPIO.output(LED2, GPIO.LOW)
                GPIO.output(BUZZER2, GPIO.LOW)

        dwell1 = round(current_time - dwell_start1, 1) if dwell_start1 else 0.0
        dwell2 = round(current_time - dwell_start2, 1) if dwell_start2 else 0.0

        score1 = calculate_score(dist1, dwell1)
        score2 = calculate_score(dist2, dwell2)

        recommended_product, recommendation_reason = get_recommendation(score1, score2, dwell1, dwell2)

        led1 = GPIO.input(LED1)
        led2 = GPIO.input(LED2)
        buzzer1 = GPIO.input(BUZZER1)
        buzzer2 = GPIO.input(BUZZER2)

        status1 = get_dwell_status(dwell1, led1)
        status2 = get_dwell_status(dwell2, led2)

        if buzzer1 or buzzer2:
            system_status = "High Engagement Alert"
        elif led1 or led2:
            system_status = "Live Engagement Tracking"
        else:
            system_status = "Monitoring"

        latest_data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "dist1": dist1 if dist1 is not None else "No Signal",
            "dist2": dist2 if dist2 is not None else "No Signal",
            "dwell1": dwell1,
            "dwell2": dwell2,
            "score1": score1,
            "score2": score2,
            "led1": led1,
            "led2": led2,
            "buzzer1": buzzer1,
            "buzzer2": buzzer2,
            "status1": status1,
            "status2": status2,
            "system_status": system_status,
            "recommended_product": recommended_product,
            "recommendation_reason": recommendation_reason
        }

        save_data()

        print(f"S1: {dist1} cm | Dwell: {dwell1:.1f}s | Score:{score1} | LED:{led1} | Buz:{buzzer1}")
        print(f"S2: {dist2} cm | Dwell: {dwell2:.1f}s | Score:{score2} | LED:{led2} | Buz:{buzzer2}")
        print(f"Recommendation: {recommended_product}")
        print("-" * 60)

        time.sleep(0.15)

# ============================================
#  DASHBOARD
# ============================================
@app.route("/")
def dashboard():
    d = latest_data
    status1_class = get_status_class(d["status1"])
    status2_class = get_status_class(d["status2"])

    return render_template_string(f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>AI Virtual Showroom Dashboard</title>
        <meta http-equiv="refresh" content="2">

        <style>
            body {{
                margin: 0;
                font-family: Arial, sans-serif;
                background: #f4f6fb;
                color: #1f2937;
            }}

            .header {{
                background: linear-gradient(90deg, #4c1d95, #7c3aed);
                color: white;
                padding: 28px 42px;
            }}

            .header h1 {{
                margin: 0;
                font-size: 32px;
            }}

            .header p {{
                margin-top: 8px;
                font-size: 15px;
            }}

            .container {{
                padding: 30px 40px;
            }}

            .grid {{
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 20px;
            }}

            .card {{
                background: white;
                border-radius: 16px;
                padding: 22px;
                box-shadow: 0 4px 14px rgba(0,0,0,0.08);
                margin-bottom: 20px;
            }}

            .card h2 {{
                margin-top: 0;
                color: #4c1d95;
            }}

            .value {{
                font-size: 32px;
                font-weight: bold;
                margin: 10px 0;
            }}

            .score {{
                font-size: 42px;
                font-weight: bold;
                color: #7c3aed;
            }}

            .ok {{
                color: #15803d;
                font-weight: bold;
            }}

            .alert {{
                color: #dc2626;
                font-weight: bold;
            }}

            .off {{
                color: #6b7280;
                font-weight: bold;
            }}

            .pill {{
                display: inline-block;
                padding: 8px 14px;
                border-radius: 20px;
                background: #ede9fe;
                color: #4c1d95;
                font-weight: bold;
                margin-top: 8px;
            }}

            .status-badge {{
                display: inline-block;
                padding: 10px 18px;
                border-radius: 999px;
                font-size: 18px;
                font-weight: 800;
                letter-spacing: 0.3px;
                min-width: 170px;
                text-align: center;
            }}

            .status-no {{
                background: #f3f4f6;
                color: #6b7280;
                border: 1px solid #d1d5db;
            }}

            .status-browsing {{
                background: #dbeafe;
                color: #1d4ed8;
                border: 1px solid #93c5fd;
            }}

            .status-interested {{
                background: #dcfce7;
                color: #15803d;
                border: 1px solid #86efac;
            }}

            .status-high {{
                background: #fef3c7;
                color: #b45309;
                border: 1px solid #fcd34d;
            }}

            .status-alert {{
                background: #fee2e2;
                color: #dc2626;
                border: 1px solid #fca5a5;
                animation: pulse 1s infinite;
            }}

            @keyframes pulse {{
                0% {{ transform: scale(1); }}
                50% {{ transform: scale(1.04); }}
                100% {{ transform: scale(1); }}
            }}

            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 10px;
            }}

            td {{
                padding: 10px;
                border-bottom: 1px solid #e5e7eb;
            }}
        </style>
    </head>

    <body>
        <div class="header">
            <h1>Apple Futuristic Product Showroom</h1>
            <p>Live Raspberry Pi CPS Dashboard | Dwell-Time Analytics | Smart Product Recommendations</p>
        </div>

        <div class="container">

            <div class="card">
                <h2>System Status</h2>
                <div class="value">{d["system_status"]}</div>
                <p><b>Last Updated:</b> {d["timestamp"]}</p>
                <span class="pill">Buzzer + 100% Score at 15 sec | Recommendation at 17 sec</span>
            </div>

            <div class="card">
                <h2>AI Recommendation Engine</h2>
                <div class="value">{d["recommended_product"]}</div>
                <p><b>Recommended items:</b></p><ul>{d["recommendation_reason"]}</ul>
            </div>

            <div class="grid">
                <div class="card">
                    <h2>{PRODUCT_1}</h2>
                    <p class="value">{d["dist1"]} cm</p>
                    <p>Engagement Score</p>
                    <div class="score">{d["score1"]}/100</div>

                    <table>
                        <tr><td>Detection Status</td><td><span class="status-badge {status1_class}">{d["status1"]}</span></td></tr>
                        <tr><td>Dwell Time</td><td>{d["dwell1"]} sec</td></tr>
                        <tr><td>LED Status</td><td class="{'ok' if d["led1"] else 'off'}">{'ON' if d["led1"] else 'OFF'}</td></tr>
                        <tr><td>Buzzer Status</td><td class="{'alert' if d["buzzer1"] else 'off'}">{'ON' if d["buzzer1"] else 'OFF'}</td></tr>
                    </table>
                </div>

                <div class="card">
                    <h2>{PRODUCT_2}</h2>
                    <p class="value">{d["dist2"]} cm</p>
                    <p>Engagement Score</p>
                    <div class="score">{d["score2"]}/100</div>

                    <table>
                        <tr><td>Detection Status</td><td><span class="status-badge {status2_class}">{d["status2"]}</span></td></tr>
                        <tr><td>Dwell Time</td><td>{d["dwell2"]} sec</td></tr>
                        <tr><td>LED Status</td><td class="{'ok' if d["led2"] else 'off'}">{'ON' if d["led2"] else 'OFF'}</td></tr>
                        <tr><td>Buzzer Status</td><td class="{'alert' if d["buzzer2"] else 'off'}">{'ON' if d["buzzer2"] else 'OFF'}</td></tr>
                    </table>
                </div>
            </div>

            <div class="card">
                <h2>CPS Requirement Coverage</h2>
                <table>
                    <tr><td>Sensor</td><td>2 HC-SR04 ultrasonic sensors detect customer proximity</td></tr>
                    <tr><td>Actuator</td><td>2 LEDs and 2 buzzers respond to detection and high engagement</td></tr>
                    <tr><td>Wireless Communication</td><td>Dashboard is accessed wirelessly through Raspberry Pi IP address</td></tr>
                    <tr><td>Data Storage</td><td>SQLite stores timestamp, distance, dwell time, score, recommendation, LED and buzzer status</td></tr>
                    <tr><td>Recommendation</td><td>Dashboard recommends a related product based on engagement score</td></tr>
                </table>
            </div>

        </div>
    </body>
    </html>
    """)

# ============================================
#  START SYSTEM
# ============================================
if __name__ == "__main__":
    init_db()

    t = threading.Thread(target=sensor_loop)
    t.daemon = True
    t.start()

    try:
        app.run(host="0.0.0.0", port=5000, debug=False)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        GPIO.cleanup()
        print("All GPIO cleaned up.")