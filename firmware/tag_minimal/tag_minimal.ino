#include <IndoorBLE.h>
#include "TagConfig.h"
#if !defined(ARDUINO_ARCH_ESP32) || !defined(CONFIG_BT_BLUEDROID_ENABLED)
#error "This tag needs a classic ESP32 target with Bluedroid BLE (for example ESP32 Dev Module or AI Thinker ESP32-CAM)."
#endif
uint32_t sequence=0;
void setup() { IndoorBLE::begin(); }
void loop() {
  IndoorBLE::startBurst(0,TAG_ID,0,sequence++); // 0 means all channels / unspecified RSSI channel.
  delay(450);
  IndoorBLE::stopBurst();
  delay(50);
}
