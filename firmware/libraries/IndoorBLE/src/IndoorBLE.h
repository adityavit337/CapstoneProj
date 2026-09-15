#pragma once
#include <sdkconfig.h>
#if defined(CONFIG_BT_NIMBLE_ENABLED)
#include "NimbleRadio.h"
#elif defined(CONFIG_BT_BLUEDROID_ENABLED)
#include "BluedroidRadio.h"
#else
#error "A native BLE-capable ESP32 target is required; ESP8266 and ESP32-S2 are unsupported."
#endif
