#pragma once
#include <Arduino.h>
#include <BLEDevice.h>
#include <sdkconfig.h>
#include <soc/soc_caps.h>
#if !defined(SOC_BLE_SUPPORTED) || !defined(CONFIG_BT_BLUEDROID_ENABLED)
#error "This backend requires Bluedroid. Include IndoorBLE.h to select the board's backend."
#endif
#include <esp_bt.h>
#include <esp_bt_main.h>
#include <esp_gap_ble_api.h>
#include <esp_random.h>
#include <freertos/FreeRTOS.h>
#include <freertos/event_groups.h>
#include <freertos/queue.h>

namespace IndoorBLE {
// This is an experimental manufacturer payload (company ID 0xffff), not a
// registered commercial allocation. Total advertisement: 24 bytes, no scan reply.
constexpr size_t WIRE_SIZE = 19;
constexpr uint16_t DEFAULT_TAG_ID = 100;
constexpr uint8_t CHANNELS[] = {37, 38, 39};
static_assert(ADV_CHNL_37 == 1 && ADV_CHNL_38 == 2 && ADV_CHNL_39 == 4 && ADV_CHNL_ALL == 7,
              "SDK advertising channel mask definitions changed");
struct Observation {
  uint8_t kind, channel, mask;
  uint16_t id;
  uint32_t boot, seq, time_ms;
  int8_t tx_dbm, rssi;
};
inline QueueHandle_t readings;
inline EventGroupHandle_t events;
inline uint32_t bootId;
inline volatile uint32_t queueDrops = 0;
constexpr EventBits_t DATA=1, ADV_ON=2, ADV_OFF=4, SCAN_PARAMS=8, SCAN_ON=16, SCAN_OFF=32, FAILED=64;

inline uint8_t channelMask(uint8_t channel) {
  switch (channel) {
    case 0: return ADV_CHNL_ALL;
    case 37: return ADV_CHNL_37;
    case 38: return ADV_CHNL_38;
    case 39: return ADV_CHNL_39;
    default: abort();
  }
}
inline uint32_t read32(const uint8_t *p) {
  return uint32_t(p[0]) | uint32_t(p[1])<<8 | uint32_t(p[2])<<16 | uint32_t(p[3])<<24;
}
inline void write32(uint8_t *p, uint32_t x) {
  for (int i=0;i<4;i++) p[i]=uint8_t(x>>(8*i));
}
inline bool decode(const uint8_t *p, size_t n, Observation &o) {
  if (n != WIRE_SIZE || p[0]!=0xff || p[1]!=0xff || p[2]!='I' || p[3]!='P' || p[4]!=1 || p[5]>1) return false;
  if (!(p[8]==0 || p[8]==37 || p[8]==38 || p[8]==39) || p[9]!=channelMask(p[8])) return false;
  o.kind=p[5]; o.id=uint16_t(p[6]) | uint16_t(p[7])<<8;
  o.channel=p[8]; o.mask=p[9]; o.boot=read32(p+10); o.seq=read32(p+14); o.tx_dbm=int8_t(p[18]);
  return o.id != 0;
}
inline void signal(EventBits_t bit, esp_bt_status_t status) {
  xEventGroupSetBits(events,bit | (status==ESP_BT_STATUS_SUCCESS ? 0 : FAILED));
}
inline void gap(esp_gap_ble_cb_event_t event, esp_ble_gap_cb_param_t *p) {
  switch(event) {
    case ESP_GAP_BLE_ADV_DATA_RAW_SET_COMPLETE_EVT: signal(DATA,p->adv_data_raw_cmpl.status); break;
    case ESP_GAP_BLE_ADV_START_COMPLETE_EVT: signal(ADV_ON,p->adv_start_cmpl.status); break;
    case ESP_GAP_BLE_ADV_STOP_COMPLETE_EVT: signal(ADV_OFF,p->adv_stop_cmpl.status); break;
    case ESP_GAP_BLE_SCAN_PARAM_SET_COMPLETE_EVT: signal(SCAN_PARAMS,p->scan_param_cmpl.status); break;
    case ESP_GAP_BLE_SCAN_START_COMPLETE_EVT: signal(SCAN_ON,p->scan_start_cmpl.status); break;
    case ESP_GAP_BLE_SCAN_STOP_COMPLETE_EVT: signal(SCAN_OFF,p->scan_stop_cmpl.status); break;
    case ESP_GAP_BLE_SCAN_RESULT_EVT: {
      if (p->scan_rst.search_evt != ESP_GAP_SEARCH_INQ_RES_EVT) break;
      const uint8_t *data=p->scan_rst.ble_adv;
      size_t n=p->scan_rst.adv_data_len;
      for (size_t i=0;i<n;) {
        uint8_t len=data[i];
        if (!len || i+1+len>n) break;
        Observation o{};
        if (len>=2 && data[i+1]==0xff && decode(data+i+2,len-1,o)) {
          o.rssi=p->scan_rst.rssi; o.time_ms=millis();
          if (xQueueSend(readings,&o,0)!=pdTRUE) queueDrops++;
        }
        i+=len+1;
      }
      break;
    }
    default: break;
  }
}
inline void fail(const char *operation) {
  Serial.printf("FATAL %s: GAP failed or timed out; no measurement claim. Reset board.\n",operation);
  while(true) delay(1000);
}
inline void prepare(EventBits_t bit) { xEventGroupClearBits(events,bit|FAILED); }
inline void complete(esp_err_t result, EventBits_t bit, const char *operation) {
  if (result!=ESP_OK) fail(operation);
  EventBits_t got=xEventGroupWaitBits(events,bit|FAILED,pdTRUE,pdFALSE,pdMS_TO_TICKS(3000));
  if (!(got&bit) || (got&FAILED)) fail(operation);
}
inline void begin() {
  Serial.begin(115200);
  delay(1000); // Bounded delay: boot also works from a power bank.
  Serial.printf("IndoorBLE chip=%s sdk=%s\n",ESP.getChipModel(),ESP.getSdkVersion());
  readings=xQueueCreate(128,sizeof(Observation)); events=xEventGroupCreate();
  if (!readings || !events) fail("allocation");
  // Arduino's ESP32 runtime may already own the controller. Its BLE initializer
  // handles that state safely, then forwards GAP events to this radio backend.
  if (!BLEDevice::init("IndoorBLE")) fail("BLE init");
  BLEDevice::setCustomGapHandler(gap);
  if (esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_ADV,ESP_PWR_LVL_N0)!=ESP_OK) fail("tx power");
  bootId=esp_random();
}
inline void startScan() {
  esp_ble_scan_params_t p{};
  p.scan_type=BLE_SCAN_TYPE_PASSIVE;
  p.own_addr_type=BLE_ADDR_TYPE_PUBLIC;
  p.scan_filter_policy=BLE_SCAN_FILTER_ALLOW_ALL;
  p.scan_interval=160; p.scan_window=120; // 100 ms / 75 ms; leave airtime for Wi-Fi.
  p.scan_duplicate=BLE_SCAN_DUPLICATE_DISABLE;
  prepare(SCAN_PARAMS); complete(esp_ble_gap_set_scan_params(&p),SCAN_PARAMS,"scan params");
  prepare(SCAN_ON); complete(esp_ble_gap_start_scanning(0),SCAN_ON,"scan start");
}
inline void stopScan() {
  prepare(SCAN_OFF); complete(esp_ble_gap_stop_scanning(),SCAN_OFF,"scan stop");
}
inline void startBurst(uint8_t kind,uint16_t id,uint8_t channel,uint32_t sequence) {
  const uint8_t mask=channelMask(channel);
  uint8_t adv[24]={2,1,6,20,0xff};
  uint8_t *p=adv+5;
  p[0]=0xff;p[1]=0xff;p[2]='I';p[3]='P';p[4]=1;p[5]=kind;
  p[6]=uint8_t(id);p[7]=uint8_t(id>>8);p[8]=channel;p[9]=mask;
  write32(p+10,bootId);write32(p+14,sequence);p[18]=0; // requested radio power, not measured EIRP
  prepare(DATA); complete(esp_ble_gap_config_adv_data_raw(adv,sizeof(adv)),DATA,"adv payload");
  esp_ble_adv_params_t params{};
  params.adv_int_min=0x00a0; params.adv_int_max=0x00a0; // 100 ms + controller random delay
  params.adv_type=ADV_TYPE_NONCONN_IND; params.own_addr_type=BLE_ADDR_TYPE_PUBLIC;
  params.channel_map=static_cast<esp_ble_adv_channel_t>(mask);
  params.adv_filter_policy=ADV_FILTER_ALLOW_SCAN_ANY_CON_ANY;
  prepare(ADV_ON); complete(esp_ble_gap_start_advertising(&params),ADV_ON,"adv start");
  Serial.printf("ADV_OK kind=%s id=%u channel=%u mask=0x%02x seq=%lu boot=%lu tx_dbm=0\n",
                kind?"reference":"tag",id,channel,mask,(unsigned long)sequence,(unsigned long)bootId);
}
inline void stopBurst() {
  prepare(ADV_OFF); complete(esp_ble_gap_stop_advertising(),ADV_OFF,"adv stop");
}
inline bool receive(Observation &o) { return xQueueReceive(readings,&o,0)==pdTRUE; }
inline void print(const Observation &o) {
  Serial.printf("RX kind=%s id=%u rssi=%d time_ms=%lu channel_label=%u mask=0x%02x seq=%lu tx_boot=%lu\n",
                o.kind?"reference":"tag",o.id,o.rssi,(unsigned long)o.time_ms,o.channel,o.mask,
                (unsigned long)o.seq,(unsigned long)o.boot);
}
}
