

#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include "HT_SSD1306Wire.h"  // Heltec OLED library (included with board package)

// =============================================================
// CONFIGURATION -- UPDATE THESE VALUES
// =============================================================

// WiFi credentials –– If you need to run the code, please update these fields with your own wifi network credrentilas.
const char* WIFI_SSID     = "N/A"; 
const char* WIFI_PASSWORD = "N/A"; 

// MQTT broker settings (using HiveMQ free public broker as default)
const char* MQTT_BROKER   = "broker.hivemq.com";
const int   MQTT_PORT     = 1883;
const char* MQTT_TOPIC    = "iot-coursework/axel/sensors";
const char* MQTT_CLIENT   = "heltec-env-monitor-001";

// Sensor pins
#define DHT_PIN   7
#define LDR_PIN   6
#define DHT_TYPE  DHT22

// Sampling interval (milliseconds)
// 2.5 minutes = 150000 ms
#define SAMPLE_INTERVAL_MS 150000

// =============================================================
// GLOBAL OBJECTS
// =============================================================

DHT dht(DHT_PIN, DHT_TYPE);
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

// Heltec V3 OLED: address 0x3C, SDA = GPIO 17, SCL = GPIO 18, geometry 128x64
// (These are the correct I2C pins for the Heltec V3 OLED)
SSD1306Wire display(0x3c, 500000, SDA_OLED, SCL_OLED, GEOMETRY_128_64, RST_OLED);

unsigned long lastSampleTime = 0;
unsigned long sampleCount = 0;

// =============================================================
// SETUP
// =============================================================

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n=== Indoor Environment Monitor ===");

  // Initialize OLED
  display.init();
  display.setFont(ArialMT_Plain_10);
  display.clear();
  display.drawString(0, 0, "Starting up...");
  display.display();

  // Initialize DHT sensor
  dht.begin();

  // Configure LDR pin for analog reading
  analogReadResolution(12);  // 12-bit ADC (0-4095)
  pinMode(LDR_PIN, INPUT);

  // Connect to WiFi
  connectWiFi();

  // Configure MQTT
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);

  // Take an initial reading immediately
  lastSampleTime = millis() - SAMPLE_INTERVAL_MS;

  Serial.println("Setup complete. Starting data collection...");
}

// =============================================================
// MAIN LOOP
// =============================================================

void loop() {
  // Maintain WiFi connection
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  // Maintain MQTT connection
  if (!mqttClient.connected()) {
    connectMQTT();
  }
  mqttClient.loop();

  // Check if it is time to take a reading
  unsigned long now = millis();
  if (now - lastSampleTime >= SAMPLE_INTERVAL_MS) {
    lastSampleTime = now;
    sampleCount++;
    readAndPublish();
  }

  delay(100);  // Small delay to prevent busy-looping
}

// =============================================================
// SENSOR READING AND PUBLISHING
// =============================================================

void readAndPublish() {
  // Read DHT22
  float temperature = dht.readTemperature();    // Celsius
  float humidity    = dht.readHumidity();        // Percent

  // Read LDR (take average of 10 readings for stability)
  int lightRaw = 0;
  for (int i = 0; i < 10; i++) {
    lightRaw += analogRead(LDR_PIN);
    delay(10);
  }
  lightRaw = lightRaw / 10;

  // Convert light to a rough percentage (0 = dark, 100 = bright)
  // The mapping depends on your specific LDR module; adjust if needed
  float lightPercent = map(lightRaw, 0, 4095, 0, 100);

  // Check for DHT read errors
  bool dhtOk = !isnan(temperature) && !isnan(humidity);

  if (!dhtOk) {
    Serial.println("WARNING: DHT22 read failed. Retrying...");
    delay(2000);
    temperature = dht.readTemperature();
    humidity    = dht.readHumidity();
    dhtOk = !isnan(temperature) && !isnan(humidity);
  }

  // Build JSON payload
  String payload = "{";
  payload += "\"sample\": " + String(sampleCount) + ", ";
  payload += "\"temperature_c\": " + (dhtOk ? String(temperature, 1) : "null") + ", ";
  payload += "\"humidity_pct\": " + (dhtOk ? String(humidity, 1) : "null") + ", ";
  payload += "\"light_raw\": " + String(lightRaw) + ", ";
  payload += "\"light_pct\": " + String(lightPercent, 1) + ", ";
  payload += "\"wifi_rssi\": " + String(WiFi.RSSI()) + ", ";
  payload += "\"uptime_s\": " + String(millis() / 1000);
  payload += "}";

  // Publish via MQTT
  if (mqttClient.connected()) {
    bool sent = mqttClient.publish(MQTT_TOPIC, payload.c_str());
    if (sent) {
      Serial.println("MQTT published: " + payload);
    } else {
      Serial.println("MQTT publish FAILED");
    }
  } else {
    Serial.println("MQTT not connected. Data: " + payload);
  }

  // Update OLED display
  updateDisplay(temperature, humidity, lightPercent, dhtOk);

  // Also print to Serial for debugging
  Serial.println("Sample #" + String(sampleCount));
  if (dhtOk) {
    Serial.println("  Temp: " + String(temperature, 1) + " C");
    Serial.println("  Humidity: " + String(humidity, 1) + " %");
  }
  Serial.println("  Light: " + String(lightRaw) + " raw (" + String(lightPercent, 1) + "%)");
  Serial.println("  WiFi RSSI: " + String(WiFi.RSSI()) + " dBm");
  Serial.println();
}

// =============================================================
// OLED DISPLAY
// =============================================================

void updateDisplay(float temp, float hum, float light, bool dhtOk) {
  display.clear();
  display.setFont(ArialMT_Plain_10);

  display.drawString(0, 0, "Indoor Environment Monitor");
  display.drawString(0, 12, "------------------------");

  if (dhtOk) {
    display.drawString(0, 24, "Temp: " + String(temp, 1) + " C");
    display.drawString(0, 36, "Humidity: " + String(hum, 1) + " %");
  } else {
    display.drawString(0, 24, "Temp: ERROR");
    display.drawString(0, 36, "Humidity: ERROR");
  }

  display.drawString(0, 48, "Light: " + String(light, 1) + "%  #" + String(sampleCount));

  display.display();
}

// =============================================================
// WIFI CONNECTION
// =============================================================

void connectWiFi() {
  Serial.print("Connecting to WiFi: ");
  Serial.println(WIFI_SSID);

  display.clear();
  display.drawString(0, 0, "Connecting WiFi...");
  display.drawString(0, 12, WIFI_SSID);
  display.display();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(1000);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected!");
    Serial.println("IP: " + WiFi.localIP().toString());

    display.clear();
    display.drawString(0, 0, "WiFi connected!");
    display.drawString(0, 12, "IP: " + WiFi.localIP().toString());
    display.display();
    delay(2000);
  } else {
    Serial.println("\nWiFi connection FAILED. Will retry...");
    display.clear();
    display.drawString(0, 0, "WiFi FAILED");
    display.drawString(0, 12, "Will retry...");
    display.display();
    delay(5000);
  }
}

// =============================================================
// MQTT CONNECTION
// =============================================================

void connectMQTT() {
  Serial.print("Connecting to MQTT broker: ");
  Serial.println(MQTT_BROKER);

  int attempts = 0;
  while (!mqttClient.connected() && attempts < 5) {
    if (mqttClient.connect(MQTT_CLIENT)) {
      Serial.println("MQTT connected!");
    } else {
      Serial.print("MQTT failed (rc=");
      Serial.print(mqttClient.state());
      Serial.println("). Retrying in 5s...");
      delay(5000);
      attempts++;
    }
  }
}
