#include "HX711.h"
#include "BluetoothSerial.h"
#include <Preferences.h>

#if !defined(CONFIG_BT_ENABLED) || !defined(CONFIG_BLUEDROID_ENABLED)
#error Bluetooth is not enabled! Please run `make menuconfig` to and enable it
#endif

BluetoothSerial SerialBT;
Preferences preferences;

const int DT_PIN = 21;
const int SCK_PIN = 22;
HX711 scale;

const int TABLE_MAX = 16;
int numCalPoints = 0;
struct CalibrationPoint { long raw; float weight; };
CalibrationPoint calTable[TABLE_MAX];

bool needSave = false;

const char* NVS_NS = "calib";
const char* NVS_KEY_COUNT = "count";
const char* NVS_KEY_DATA = "data";

void sortCalTable() {
  for (int i = 0; i < numCalPoints - 1; i++) {
    for (int j = 0; j < numCalPoints - i - 1; j++) {
      if (calTable[j].raw > calTable[j + 1].raw) {
        CalibrationPoint tmp = calTable[j];
        calTable[j] = calTable[j + 1];
        calTable[j + 1] = tmp;
      }
    }
  }
}

void loadCalibration() {
  preferences.begin(NVS_NS, true);
  numCalPoints = preferences.getInt(NVS_KEY_COUNT, 0);
  if (numCalPoints == 0) {
    preferences.end();
    return;
  }
  String data = preferences.getString(NVS_KEY_DATA, "");
  preferences.end();

  if (data.length() == 0) { numCalPoints = 0; return; }

  int idx = 0;
  int start = 0;
  for (int i = 0; i <= data.length(); i++) {
    if (i == data.length() || data.charAt(i) == ',') {
      String token = data.substring(start, i);
      int sep = token.indexOf(':');
      if (sep > 0 && idx < TABLE_MAX) {
        calTable[idx].raw = token.substring(0, sep).toInt();
        calTable[idx].weight = token.substring(sep + 1).toFloat();
        idx++;
      }
      start = i + 1;
    }
  }
  numCalPoints = idx;
}

void saveCalibration() {
  preferences.begin(NVS_NS, false);
  preferences.putInt(NVS_KEY_COUNT, numCalPoints);
  String data = "";
  for (int i = 0; i < numCalPoints; i++) {
    data += String(calTable[i].raw) + ":" + String(calTable[i].weight);
    if (i < numCalPoints - 1) data += ",";
  }
  preferences.putString(NVS_KEY_DATA, data);
  preferences.end();
  needSave = false;
  SerialBT.println("SAVED");
}

void clearCalibration() {
  numCalPoints = 0;
  calTable[0] = {0, 0.0};
  numCalPoints = 1;
  saveCalibration();
  SerialBT.println("CLEARED");
}

void addCalPoint(long raw, float weight) {
  if (numCalPoints >= TABLE_MAX) {
    SerialBT.println("FULL");
    return;
  }
  calTable[numCalPoints++] = {raw, weight};
  sortCalTable();
  needSave = true;
  SerialBT.println("ADDED");
}

void listCalPoints() {
  SerialBT.println("--- CAL TABLE ---");
  for (int i = 0; i < numCalPoints; i++) {
    SerialBT.print(i);
    SerialBT.print(": raw=");
    SerialBT.print(calTable[i].raw);
    SerialBT.print(" weight=");
    SerialBT.println(calTable[i].weight, 4);
  }
  SerialBT.println("--- END ---");
  if (needSave) SerialBT.println("(unsaved)");
}

float calculateWeight(long raw) {
  if (numCalPoints == 0) return 0.0;
  if (raw <= calTable[0].raw) return 0.0;
  for (int i = 0; i < numCalPoints - 1; i++) {
    if (raw >= calTable[i].raw && raw <= calTable[i + 1].raw) {
      float rawRange = calTable[i + 1].raw - calTable[i].raw;
      float weightRange = calTable[i + 1].weight - calTable[i].weight;
      return calTable[i].weight + ((raw - calTable[i].raw) / rawRange) * weightRange;
    }
  }
  float rawRange = calTable[numCalPoints - 1].raw - calTable[numCalPoints - 2].raw;
  float weightRange = calTable[numCalPoints - 1].weight - calTable[numCalPoints - 2].weight;
  return calTable[numCalPoints - 2].weight
       + ((raw - calTable[numCalPoints - 2].raw) / rawRange) * weightRange;
}

void handleCommand(const String& cmd) {
  char c = cmd.charAt(0);
  switch (c) {
    case 'T': {
      scale.tare();
      SerialBT.println("OK");
      break;
    }
    case 'A': {
      int s1 = cmd.indexOf(' ');
      int s2 = cmd.indexOf(' ', s1 + 1);
      if (s1 > 0 && s2 > s1) {
        long raw = cmd.substring(s1 + 1, s2).toInt();
        float weight = cmd.substring(s2 + 1).toFloat();
        addCalPoint(raw, weight);
      } else {
        SerialBT.println("Usage: A <raw> <weight>");
      }
      break;
    }
    case 'L': {
      listCalPoints();
      break;
    }
    case 'C': {
      clearCalibration();
      break;
    }
    case 'S': {
      if (needSave) {
        saveCalibration();
      } else {
        SerialBT.println("NO CHANGE");
      }
      break;
    }
    case 'R': {
      if (scale.is_ready()) {
        long raw = scale.get_value(3);
        SerialBT.print("RAW:");
        SerialBT.println(raw);
      } else {
        SerialBT.println("RAW:ERROR");
      }
      break;
    }
    default:
      SerialBT.println("UNKNOWN");
      break;
  }
}

unsigned long lastSendTime = 0;

void setup() {
  Serial.begin(115200);
  SerialBT.begin("Lab_Scale_ESP32");
  Serial.println("Bluetooth started! Device name: Lab_Scale_ESP32");

  loadCalibration();
  if (numCalPoints == 0) {
    calTable[0] = {0, 0.0};
    numCalPoints = 1;
  }

  scale.begin(DT_PIN, SCK_PIN);

  // No forced tare at boot: probe readiness with a timeout so a missing
  // sensor cannot hang the device
  Serial.println("Checking HX711...");
  delay(500);
  if (scale.is_ready()) {
    scale.tare();
    Serial.println("HX711 initialized!");
  } else {
    Serial.println("HX711 missing or faulty! Skipping initial tare.");
  }
}
void loop() {
  static String cmdBuf;
  while (SerialBT.available() > 0) {
    char ch = SerialBT.read();
    if (ch == '\n' || ch == '\r') {
      if (cmdBuf.length() > 0) {
        handleCommand(cmdBuf);
        cmdBuf = "";
      }
    } else {
      cmdBuf += ch;
    }
  }

  if (millis() - lastSendTime > 200) {
    if (SerialBT.hasClient()) {
      if (scale.is_ready()) {
        long raw = scale.get_value(3);
        float true_weight = calculateWeight(raw);
        SerialBT.println(true_weight, 3);
      } else {
        // Sensor not ready: send an error marker
        SerialBT.println("HX711_ERROR");
      }
      lastSendTime = millis();
    }
  }
}
