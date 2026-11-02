#include "HX711.h"

const int DT_PIN = 21;
const int SCK_PIN = 22;
HX711 scale;

// ==========================================
// 🔻 Gradient calibration table (edit here) 🔻
// ==========================================
// Must be sorted from light to heavy! The first point must be {0, 0.0}
const int TABLE_SIZE = 4; // number of rows in the table

struct CalibrationPoint {
  long raw;       // internal ADC value
  float weight;   // true weight (g)
};

CalibrationPoint calTable[TABLE_SIZE] = {
  {0,      0.0},   // point 1: zero-load reference (always 0, 0)
  {34728,  0.96},  // raw value measured with a 0.96 g reference weight
  {104820, 2.89},  // raw value measured with a 2.89 g reference weight
  {230198, 6.54}   // raw value measured with a 6.54 g reference weight
  // Replace the rows above with data you measured yourself!
};
// ==========================================

void setup() {
  Serial.begin(115200);
  scale.begin(DT_PIN, SCK_PIN);
  scale.tare(); // zero the scale at boot
}

// Core lookup: map a raw ADC value to weight via the calibration table
float calculateWeight(long raw) {
  // 1. Below zero (e.g. the pan was lifted up) -> clamp to 0
  if (raw <= calTable[0].raw) return 0.0;

  // 2. Walk the table to find the segment this value falls into
  for (int i = 0; i < TABLE_SIZE - 1; i++) {
    if (raw >= calTable[i].raw && raw <= calTable[i+1].raw) {
      // Linear interpolation: draw a straight line between the two points
      float rawRange = calTable[i+1].raw - calTable[i].raw;
      float weightRange = calTable[i+1].weight - calTable[i].weight;
      float rawOffset = raw - calTable[i].raw;
      return calTable[i].weight + (rawOffset / rawRange) * weightRange;
    }
  }

  // 3. Beyond the table maximum: extrapolate with the last segment's slope
  float rawRange = calTable[TABLE_SIZE-1].raw - calTable[TABLE_SIZE-2].raw;
  float weightRange = calTable[TABLE_SIZE-1].weight - calTable[TABLE_SIZE-2].weight;
  float rawOffset = raw - calTable[TABLE_SIZE-2].raw;
  return calTable[TABLE_SIZE-2].weight + (rawOffset / rawRange) * weightRange;
}

void loop() {
  // Obeys commands from the Python host
  if (Serial.available() > 0) {
    char command = Serial.read();

    if (command == 'R') {
      if (scale.is_ready()) {
        long raw = scale.get_value(5);            // averaged raw value
        float true_weight = calculateWeight(raw); // look up the true weight
        Serial.println(true_weight, 3);           // send to host, 3 decimals
      } else {
        Serial.println("Error");
      }
    }
    else if (command == 'T') {
      scale.tare();
      Serial.println("OK");
    }
  }
}
