// Classic ESP32 two-board review receiver. Pair with tag_minimal (ID 100, all channels).
// Uses the bundled Arduino BLE Scan API. No IndoorBLE library or Wi-Fi needed.
// Keep anchor_network and tag_channels for the future multi-anchor experiment.
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <math.h>

constexpr uint16_t TAG_ID = 100;
QueueHandle_t samples;
BLEScan *scanner;

class TagCallbacks : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice device) override {
    if (!device.haveManufacturerData()) return;
    auto data = device.getManufacturerData();
    if (data.length() != 19) return;
    const uint8_t *p = reinterpret_cast<const uint8_t *>(data.c_str());
    // Only baseline IndoorBLE tags; ignore phones, references and channel trials.
    if (p[0]!=0xff || p[1]!=0xff || p[2]!='I' || p[3]!='P' ||
        p[4]!=1 || p[5]!=0 || (uint16_t(p[6]) | uint16_t(p[7])<<8)!=TAG_ID ||
        p[8]!=0 || p[9]!=7) return;
    int rssi = device.getRSSI();
    if (rssi < 0 && rssi >= -127) xQueueSend(samples, &rssi, 0);
  }
};
TagCallbacks callbacks;

void setup() {
  Serial.begin(115200);
  delay(1000);  // Does not wait for a USB monitor to open.
  Serial.printf("DISTANCE_RECEIVER chip=%s sdk=%s tag=%u\n", ESP.getChipModel(), ESP.getSdkVersion(), TAG_ID);
  samples = xQueueCreate(256, sizeof(int));
  if (!samples) { Serial.println("FATAL: sample allocation"); while(true) delay(1000); }
  BLEDevice::init("DistanceReceiver");
  scanner = BLEDevice::getScan();
  scanner->setAdvertisedDeviceCallbacks(&callbacks, true);
  scanner->setActiveScan(false);
  scanner->setInterval(100);
  scanner->setWindow(99);
  Serial.println("Keep still. Copy RSSI_AVG to the website. Each window is 3 seconds.");
}

void loop() {
  scanner->start(3, false);
  int rssi, count=0, sum=0, squares=0, weakest=0, strongest=-127;
  while (xQueueReceive(samples, &rssi, 0)==pdTRUE) {
    count++; sum+=rssi; squares+=rssi*rssi;
    if (rssi<weakest) weakest=rssi;
    if (rssi>strongest) strongest=rssi;
  }
  if (count>=3) {
    float mean=float(sum)/count;
    float sd=sqrtf(fmaxf(0, float(squares)/count-mean*mean));
    Serial.printf("RSSI_AVG=%.2f dBm samples=%d spread_sd=%.2f min=%d max=%d window_ms=3000\n",
                  mean, count, sd, weakest, strongest);
  } else {
    Serial.printf("NO_RELIABLE_READING samples=%d: check tag power, antenna and tag_minimal firmware\n", count);
  }
  scanner->clearResults();
  delay(100);
}
