#pragma once
#include <Arduino.h>
#include <BLEDevice.h>
#include <esp_bt.h>
#include <esp_random.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <host/ble_hs.h>
#include <host/ble_gap.h>
#include <host/util/util.h>

namespace IndoorBLE {
constexpr size_t WIRE_SIZE=19;
constexpr uint8_t CHANNELS[]={37,38,39};
struct Observation {
  uint8_t kind,channel,mask;
  uint16_t id;
  uint32_t boot,seq,time_ms;
  int8_t tx_dbm,rssi;
};
inline QueueHandle_t readings;
inline uint32_t bootId;
inline volatile uint32_t queueDrops=0;
inline uint8_t ownAddressType;
inline uint8_t channelMask(uint8_t channel) {
  switch(channel) {
    case 0:return 0x07;
    case 37:return 0x01;
    case 38:return 0x02;
    case 39:return 0x04;
    default:abort();
  }
}
inline uint32_t read32(const uint8_t *p) {
  return uint32_t(p[0]) | uint32_t(p[1])<<8 | uint32_t(p[2])<<16 | uint32_t(p[3])<<24;
}
inline void write32(uint8_t *p,uint32_t x) { for(int i=0;i<4;i++) p[i]=uint8_t(x>>(8*i)); }
inline bool decode(const uint8_t *p,size_t n,Observation &o) {
  if(n!=WIRE_SIZE || p[0]!=0xff || p[1]!=0xff || p[2]!='I' || p[3]!='P' || p[4]!=1 || p[5]>1) return false;
  if(!(p[8]==0 || p[8]==37 || p[8]==38 || p[8]==39) || p[9]!=channelMask(p[8])) return false;
  o.kind=p[5];o.id=uint16_t(p[6]) | uint16_t(p[7])<<8;o.channel=p[8];o.mask=p[9];
  o.boot=read32(p+10);o.seq=read32(p+14);o.tx_dbm=int8_t(p[18]);return o.id!=0;
}
inline void fail(const char *operation) {
  Serial.printf("FATAL %s: NimBLE/HCI failed; no measurement claim. Reset board.\n",operation);
  while(true)delay(1000);
}
inline void check(int result,const char *operation) {
  if(result || !ble_hs_synced())fail(operation);
}
inline void begin() {
  Serial.begin(115200);delay(1000);
  Serial.printf("IndoorBLE chip=%s sdk=%s backend=NimBLE\n",ESP.getChipModel(),ESP.getSdkVersion());
  readings=xQueueCreate(128,sizeof(Observation));
  if(!readings)fail("allocation");
  // Use the packaged initializer exercised by Arduino's BLE Scan example.
  // Arduino owns host configuration, synchronization and the host task;
  // native GAP operations below retain explicit advertising-channel control.
  if(!BLEDevice::init("IndoorBLE"))fail("init");
  check(ble_hs_id_infer_auto(0,&ownAddressType),"host address");
  ESP_ERROR_CHECK(esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_ADV,ESP_PWR_LVL_N0));
  bootId=esp_random();
}
inline void startBurst(uint8_t kind,uint16_t id,uint8_t channel,uint32_t sequence) {
  const uint8_t mask=channelMask(channel);
  uint8_t adv[24]={2,1,6,20,0xff};uint8_t *p=adv+5;
  p[0]=0xff;p[1]=0xff;p[2]='I';p[3]='P';p[4]=1;p[5]=kind;
  p[6]=uint8_t(id);p[7]=uint8_t(id>>8);p[8]=channel;p[9]=mask;
  write32(p+10,bootId);write32(p+14,sequence);p[18]=0;
  // NimBLE legacy APIs synchronously wait for HCI command completion. Called
  // from Arduino's application task, never the host callback/event context.
  check(ble_gap_adv_set_data(adv,sizeof(adv)),"adv data");
  ble_gap_adv_params params{};
  params.conn_mode=BLE_GAP_CONN_MODE_NON;params.disc_mode=BLE_GAP_DISC_MODE_NON;
  params.itvl_min=0x00a0;params.itvl_max=0x00a0;
  params.channel_map=mask;
  check(ble_gap_adv_start(ownAddressType,nullptr,BLE_HS_FOREVER,&params,nullptr,nullptr),"adv start");
  Serial.printf("ADV_OK kind=%s id=%u channel=%u mask=0x%02x seq=%lu boot=%lu tx_dbm=0\n",
                kind?"reference":"tag",id,channel,mask,(unsigned long)sequence,(unsigned long)bootId);
}
inline void stopBurst() { check(ble_gap_adv_stop(),"adv stop"); }
inline void report(const uint8_t *data,size_t n,int8_t rssi) {
  for(size_t i=0;i<n;) {
    uint8_t len=data[i];if(!len || i+len+1>n)break;
    Observation o{};
    if(len>=2 && data[i+1]==0xff && decode(data+i+2,len-1,o)) {
      o.rssi=rssi;o.time_ms=millis();if(xQueueSend(readings,&o,0)!=pdTRUE)queueDrops++;
    }
    i+=len+1;
  }
}
inline int scanEvent(ble_gap_event *event,void *) {
  if(event->type==BLE_GAP_EVENT_DISC)report(event->disc.data,event->disc.length_data,event->disc.rssi);
  return 0;
}
inline void startScan() {
  ble_gap_disc_params params{};params.passive=1;params.filter_duplicates=0;params.itvl=160;params.window=120;
  check(ble_gap_disc(ownAddressType,BLE_HS_FOREVER,&params,scanEvent,nullptr),"scan start");
}
inline void stopScan() { check(ble_gap_disc_cancel(),"scan stop"); }
inline bool receive(Observation &o) { return xQueueReceive(readings,&o,0)==pdTRUE; }
inline void print(const Observation &o) {
  Serial.printf("RX kind=%s id=%u rssi=%d time_ms=%lu channel_label=%u mask=0x%02x seq=%lu tx_boot=%lu\n",
                o.kind?"reference":"tag",o.id,o.rssi,(unsigned long)o.time_ms,o.channel,o.mask,(unsigned long)o.seq,(unsigned long)o.boot);
}
}
