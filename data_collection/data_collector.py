"""
Data Collector -- MQTT Subscriber + OpenWeatherMap API Poller

This script runs continuously on your computer and:
1. Subscribes to the MQTT topic where the ESP32 publishes sensor data
2. Polls OpenWeatherMap API every 15 minutes for outdoor weather
3. Logs everything into CSV files with timestamps

Run this script on your laptop/PC while the ESP32 is collecting data.
Keep it running for the full week of data collection.

Usage:
    pip install paho-mqtt requests
    python data_collector.py

Configuration:
    Update the variables in the CONFIG section below.
"""

import json
import csv
import time
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import threading

from http.server import HTTPServer, SimpleHTTPRequestHandler
import paho.mqtt.client as mqtt
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# =============================================================
# CONFIG -- UPDATE THESE VALUES
# =============================================================

# MQTT settings (must match the Arduino sketch)
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC = "iot-coursework/axel/sensors"

OWM_API_KEY = os.getenv("OPENWEATHER_API_KEY", "YOUR_API_KEY_HERE")
OWM_CITY = "London"
OWM_COUNTRY = "GB"
OWM_URL = "https://api.openweathermap.org/data/2.5/weather"

# Polling interval for weather API (seconds)
# 5 minutes = 300 seconds (matches indoor sensor sampling rate)
WEATHER_POLL_INTERVAL = 150  # Poll every 2.5 minutes to get more frequent outdoor data

# Output directory for CSV files
DATA_DIR = Path(__file__).parent / "data"

# =============================================================
# FILE SETUP
# =============================================================

def setup_data_files():
    """Create the data directory and CSV files with headers if they don't exist."""
    DATA_DIR.mkdir(exist_ok=True)

    sensor_file = DATA_DIR / "indoor_sensor_data.csv"
    weather_file = DATA_DIR / "outdoor_weather_data.csv"

    if not sensor_file.exists():
        with open(sensor_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp_utc",
                "timestamp_local",
                "sample_number",
                "temperature_c",
                "humidity_pct",
                "light_raw",
                "light_pct",
                "wifi_rssi",
                "uptime_s"
            ])
        print(f"Created {sensor_file}")

    if not weather_file.exists():
        with open(weather_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp_utc",
                "timestamp_local",
                "outdoor_temp_c",
                "outdoor_humidity_pct",
                "outdoor_pressure_hpa",
                "outdoor_wind_speed_ms",
                "outdoor_wind_deg",
                "outdoor_clouds_pct",
                "outdoor_visibility_m",
                "weather_description",
                "sunrise_utc",
                "sunset_utc"
            ])
        print(f"Created {weather_file}")

    return sensor_file, weather_file


# =============================================================
# MQTT SUBSCRIBER (Indoor Sensor Data)
# =============================================================

def on_connect(client, userdata, flags, rc, properties=None):
    """Called when MQTT connection is established."""
    if rc == 0:
        print(f"[MQTT] Connected to {MQTT_BROKER}")
        client.subscribe(MQTT_TOPIC)
        print(f"[MQTT] Subscribed to: {MQTT_TOPIC}")
    else:
        print(f"[MQTT] Connection failed with code {rc}")


def on_message(client, userdata, msg):
    """Called when a message is received from the ESP32."""
    sensor_file = userdata["sensor_file"]

    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        now_utc = datetime.now(timezone.utc)
        now_local = datetime.now()

        row = [
            now_utc.isoformat(),
            now_local.strftime("%Y-%m-%d %H:%M:%S"),
            payload.get("sample", ""),
            payload.get("temperature_c", ""),
            payload.get("humidity_pct", ""),
            payload.get("light_raw", ""),
            payload.get("light_pct", ""),
            payload.get("wifi_rssi", ""),
            payload.get("uptime_s", "")
        ]

        with open(sensor_file, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(row)

        temp = payload.get("temperature_c", "?")
        hum = payload.get("humidity_pct", "?")
        light = payload.get("light_pct", "?")
        print(f"[SENSOR] {now_local.strftime('%H:%M:%S')} -- "
              f"Temp: {temp}C, Humidity: {hum}%, Light: {light}%")

    except json.JSONDecodeError:
        print(f"[MQTT] Failed to parse message: {msg.payload}")
    except Exception as e:
        print(f"[MQTT] Error processing message: {e}")


def on_disconnect(client, userdata, rc, properties=None, reasonCode=None):
    """Called when disconnected from MQTT broker."""
    print(f"[MQTT] Disconnected (rc={rc}). Will auto-reconnect...")


# =============================================================
# WEATHER API POLLER (Outdoor Data)
# =============================================================

def poll_weather(weather_file):
    """Fetch current weather from OpenWeatherMap and log to CSV."""
    params = {
        "q": f"{OWM_CITY},{OWM_COUNTRY}",
        "appid": OWM_API_KEY,
        "units": "metric"  # Celsius
    }

    try:
        resp = requests.get(OWM_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        now_utc = datetime.now(timezone.utc)
        now_local = datetime.now()

        main = data.get("main", {})
        wind = data.get("wind", {})
        clouds = data.get("clouds", {})
        sys_info = data.get("sys", {})
        weather_desc = data.get("weather", [{}])[0].get("description", "")
        visibility = data.get("visibility", "")

        # Convert sunrise/sunset from unix timestamp
        sunrise = datetime.fromtimestamp(
            sys_info.get("sunrise", 0), tz=timezone.utc
        ).strftime("%H:%M:%S") if sys_info.get("sunrise") else ""

        sunset = datetime.fromtimestamp(
            sys_info.get("sunset", 0), tz=timezone.utc
        ).strftime("%H:%M:%S") if sys_info.get("sunset") else ""

        row = [
            now_utc.isoformat(),
            now_local.strftime("%Y-%m-%d %H:%M:%S"),
            main.get("temp", ""),
            main.get("humidity", ""),
            main.get("pressure", ""),
            wind.get("speed", ""),
            wind.get("deg", ""),
            clouds.get("all", ""),
            visibility,
            weather_desc,
            sunrise,
            sunset
        ]

        with open(weather_file, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(row)

        print(f"[WEATHER] {now_local.strftime('%H:%M:%S')} -- "
              f"Outdoor: {main.get('temp', '?')}C, "
              f"Humidity: {main.get('humidity', '?')}%, "
              f"Clouds: {clouds.get('all', '?')}%, "
              f"{weather_desc}")

    except requests.exceptions.RequestException as e:
        print(f"[WEATHER] API request failed: {e}")
    except Exception as e:
        print(f"[WEATHER] Error: {e}")


def weather_polling_loop(weather_file):
    """Continuously poll weather data at the configured interval."""
    print(f"[WEATHER] Starting weather polling every {WEATHER_POLL_INTERVAL}s "
          f"for {OWM_CITY}, {OWM_COUNTRY}")

    while True:
        poll_weather(weather_file)
        time.sleep(WEATHER_POLL_INTERVAL)


# =============================================================
# FILE DOWNLOAD SERVER
# =============================================================

class DataFileHandler(SimpleHTTPRequestHandler):
    """Simple HTTP handler that serves the CSV data files."""

    def do_GET(self):
        if self.path == "/" or self.path == "":
            # List available files
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            html = "<h2>IoT Data Files</h2><ul>"
            html += '<li><a href="/indoor">indoor_sensor_data.csv</a></li>'
            html += '<li><a href="/outdoor">outdoor_weather_data.csv</a></li>'
            html += "</ul>"
            self.wfile.write(html.encode())
        elif self.path == "/indoor":
            self._serve_file(DATA_DIR / "indoor_sensor_data.csv")
        elif self.path == "/outdoor":
            self._serve_file(DATA_DIR / "outdoor_weather_data.csv")
        else:
            self.send_error(404)

    def _serve_file(self, filepath):
        if filepath.exists():
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Disposition",
                             f"attachment; filename={filepath.name}")
            self.end_headers()
            with open(filepath, "rb") as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404, "File not found yet -- no data collected")

    def log_message(self, format, *args):
        # Suppress request logs to keep console clean
        pass


def start_file_server():
    """Start a simple HTTP server to serve data files for download."""
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), DataFileHandler)
    print(f"[HTTP] File download server running on port {port}")
    print(f"[HTTP] Visit your Railway public URL to download CSV files")
    server.serve_forever()


# =============================================================
# MAIN
# =============================================================

def main():
    print("=" * 60)
    print("  IoT Data Collector")
    print("  Indoor sensors (MQTT) + Outdoor weather (API)")
    print("=" * 60)
    print()

    # Validate API key
    if OWM_API_KEY == "YOUR_API_KEY_HERE" or not OWM_API_KEY:
        print("WARNING: OpenWeatherMap API key not set!")
        print("Set OPENWEATHER_API_KEY environment variable or update .env file.")
        print("Continuing without weather data...")
        print()

    # Set up data files
    sensor_file, weather_file = setup_data_files()
    print(f"Sensor data -> {sensor_file}")
    print(f"Weather data -> {weather_file}")
    print()

    # Start weather polling in a background thread
    if OWM_API_KEY != "YOUR_API_KEY_HERE":
        weather_thread = threading.Thread(
            target=weather_polling_loop,
            args=(weather_file,),
            daemon=True
        )
        weather_thread.start()
    else:
        print("[WEATHER] Skipping weather polling (no API key)")

    # Start file download server in background thread
    http_thread = threading.Thread(target=start_file_server, daemon=True)
    http_thread.start()

    # Set up and start MQTT client
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="data-collector-laptop"
    )
    client.user_data_set({"sensor_file": sensor_file})
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=1, max_delay=60)

    print(f"[MQTT] Connecting to {MQTT_BROKER}:{MQTT_PORT}...")
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as e:
        print(f"[MQTT] Initial connection failed: {e}")
        print("Make sure your internet connection is active.")
        sys.exit(1)

    # This blocks and handles reconnections automatically
    print()
    print("Data collection is running. Press Ctrl+C to stop.")
    print("Keep this script running for the full week!")
    print()

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nStopping data collection...")
        client.disconnect()
        print("Done. Data saved in:", DATA_DIR)


if __name__ == "__main__":
    main()
