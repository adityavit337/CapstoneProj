#include <IndoorBLE.h>
#if !defined(CONFIG_IDF_TARGET_ESP32) || !defined(CONFIG_BT_BLUEDROID_ENABLED)
#error "Anchors require a classic ESP32 target with Bluedroid BLE (for example ESP32 Dev Module or AI Thinker ESP32-CAM)."
#endif
#include <WiFi.h>
#include <WiFiUdp.h>
#include <RoomConfig.h>
#if __has_include(<NetworkConfig.h>)
#include <NetworkConfig.h>
#else
#include <NetworkConfig.example.h>
#endif
#include "AnchorConfig.h"
static_assert(ANCHOR_INDEX>=0 && ANCHOR_INDEX<3,"ANCHOR_INDEX must be 0, 1 or 2");
const auto &placement=ANCHOR_PLACEMENTS[ANCHOR_INDEX];
WiFiUDP udp;
IPAddress laptop;
bool validNetwork=false,udpReady=false;
uint32_t lastConnect=0,lastHeartbeat=0,lastSync=0,syncPhase=0,syncAt=0,lastEcho=0;
bool referenceAllowed=false;
bool haveReferenceSlot=false;
uint32_t lastReferenceSlot=0;
uint32_t referenceSequence=0;

void sendText(const char *text) {
  if (!udpReady || WiFi.status()!=WL_CONNECTED) return;
  if (udp.beginPacket(laptop,RECEIVER_PORT)) { udp.write((const uint8_t*)text,strlen(text)); udp.endPacket(); }
}
void networkTick() {
  uint32_t now=millis();
  if (!validNetwork) return;
  if (WiFi.status()!=WL_CONNECTED) {
    udpReady=false;
    if (now-lastConnect>=10000) {
      lastConnect=now; Serial.println("WIFI reconnecting"); WiFi.disconnect(); WiFi.begin(WIFI_SSID,WIFI_PASSWORD);
    }
    return;
  }
  if (!udpReady) {
    udp.stop(); udpReady=udp.begin(0)!=0; // Ephemeral port; server replies to its source.
    Serial.printf("WIFI connected local=%s anchor=%s coordinate=(%.2f,%.2f)\n",WiFi.localIP().toString().c_str(),placement.id,placement.x,placement.y);
  }
  if (now-lastHeartbeat>=1000) {
    lastHeartbeat=now; lastEcho=now;
    char body[256];
    snprintf(body,sizeof(body),"{\"v\":1,\"type\":\"heartbeat\",\"simulated\":false,\"anchor\":\"%s\",\"anchor_boot\":%lu,\"uptime_ms\":%lu,\"queue_drops\":%lu}",
             placement.id,(unsigned long)IndoorBLE::bootId,(unsigned long)now,(unsigned long)IndoorBLE::queueDrops);
    sendText(body);
    Serial.printf("HEARTBEAT anchor=%s receiver_ack_age_ms=%lu queue_drops=%lu\n",placement.id,(unsigned long)(lastSync?now-lastSync:0xffffffffUL),(unsigned long)IndoorBLE::queueDrops);
  }
  int size=udp.parsePacket();
  if (size) {
    char reply[96]; int n=udp.read(reply,sizeof(reply)-1); if (n<0) return; reply[n]=0;
    if (udp.remoteIP()!=laptop || udp.remotePort()!=RECEIVER_PORT) return;
    unsigned long echo,phase; int enabled;
    if (sscanf(reply,"SYNC1 %lu %lu %d",&echo,&phase,&enabled)==3 && echo==lastEcho && now-uint32_t(echo)<=200 && phase<12000) {
      // Approximate half-RTT correction. 300 ms slot guards exceed accepted RTT.
      syncPhase=(phase+(now-uint32_t(echo))/2)%12000; syncAt=now; lastSync=now;
      referenceAllowed=enabled==1;
    }
  }
}
void drainReadings() {
  IndoorBLE::Observation o;
  while(IndoorBLE::receive(o)) {
    if ((o.kind==0 && o.id!=CONFIGURED_TAG_ID) || (o.kind==1 && o.id==placement.wireId)) continue;
    IndoorBLE::print(o);
    char body[480];
    snprintf(body,sizeof(body),"{\"v\":1,\"type\":\"observation\",\"simulated\":false,\"anchor\":\"%s\",\"anchor_boot\":%lu,\"uptime_ms\":%lu,\"kind\":\"%s\",\"tx_id\":%u,\"tx_boot\":%lu,\"seq\":%lu,\"channel\":%u,\"channel_mask\":%u,\"rssi\":%d,\"tx_dbm\":%d}",
             placement.id,(unsigned long)IndoorBLE::bootId,(unsigned long)o.time_ms,o.kind?"reference":"tag",o.id,(unsigned long)o.boot,(unsigned long)o.seq,o.channel,o.mask,o.rssi,o.tx_dbm);
    sendText(body); // No unbounded backlog: disconnected observations stay on serial only.
  }
}
void referenceTick() {
  if (!ENABLE_REFERENCE_TRANSMIT || !referenceAllowed || !lastSync || millis()-lastSync>4000 || !udpReady) return;
  uint32_t elapsed=millis()-syncAt;
  uint32_t phase=(syncPhase+elapsed)%12000;
  uint32_t slotStart=6000+ANCHOR_INDEX*2000;
  // Enter only in the narrow start window, once per frame. No late catch-up burst.
  if (phase<slotStart+300 || phase>slotStart+450) return;
  // Local cooldown survives new sync phases and prevents repeated entry in a slot.
  if (haveReferenceSlot && millis()-lastReferenceSlot<10000) return;
  lastReferenceSlot=millis(); haveReferenceSlot=true;
  uint32_t slotBudget=slotStart+1700-phase; // End before the trailing 300 ms guard.
  IndoorBLE::stopScan();
  for (uint8_t ch : IndoorBLE::CHANNELS) {
    if (millis()-lastReferenceSlot+400>slotBudget) break;
    IndoorBLE::startBurst(1,placement.wireId,ch,referenceSequence);
    uint32_t start=millis();
    while(millis()-start<300) { networkTick(); drainReadings(); delay(5); }
    IndoorBLE::stopBurst(); delay(30);
  }
  referenceSequence++;
  IndoorBLE::startScan();
}
void setup() {
  IndoorBLE::begin();
  Serial.printf("ANCHOR %s at (%.2f,%.2f) m; references=%s\n",placement.id,placement.x,placement.y,ENABLE_REFERENCE_TRANSMIT?"enabled":"disabled");
  validNetwork=laptop.fromString(LAPTOP_IP) && strcmp(WIFI_SSID,"YOUR_2_4_GHZ_WIFI_SSID")!=0;
  if (validNetwork) { WiFi.mode(WIFI_STA); WiFi.setSleep(false); WiFi.begin(WIFI_SSID,WIFI_PASSWORD); }
  else Serial.println("CONFIG_REQUIRED: edit NetworkConfig.h; serial scanning remains available");
  IndoorBLE::startScan();
}
void loop() { networkTick(); drainReadings(); referenceTick(); delay(5); }
