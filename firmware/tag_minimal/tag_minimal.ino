#include <IndoorBLE.h>
#include "TagConfig.h"
#if !defined(ARDUINO_ARCH_ESP32) || !defined(CONFIG_BT_BLUEDROID_ENABLED)
#error "Two-board review tag: select ESP32 Dev Module on an ESP32-WROOM board."
#endif
uint32_t sequence=0;
void setup() { IndoorBLE::begin(); }
void loop() {
  IndoorBLE::startBurst(0,TAG_ID,0,sequence++); // 0 means all channels / unspecified RSSI channel.
  delay(450);
  IndoorBLE::stopBurst();
  delay(50);
}
