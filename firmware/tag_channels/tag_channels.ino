#include <IndoorBLE.h>
#include "TagConfig.h"
#if !defined(ARDUINO_XIAO_ESP32S3)
#error "Channel tag requires the dedicated XIAO_ESP32S3 target."
#endif
uint32_t cycleSequence=0;
void setup() { IndoorBLE::begin(); }
void loop() {
  for (uint8_t channel : IndoorBLE::CHANNELS) {
    // Common cycle sequence: each per-channel stream increments by exactly one.
    // startBurst sets the CONTROLLER channel map and waits for GAP completion.
    IndoorBLE::startBurst(0,TAG_ID,channel,cycleSequence);
    delay(BURST_MS);
    IndoorBLE::stopBurst();
    delay(GUARD_MS);
  }
  cycleSequence++;
}
