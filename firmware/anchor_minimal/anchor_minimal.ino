#include <IndoorBLE.h>
void setup() {
  IndoorBLE::begin();
  IndoorBLE::startScan();
  Serial.println("SCAN_READY: waiting for IndoorBLE tag; duplicate PDUs intentionally visible");
}
void loop() {
  IndoorBLE::Observation o;
  while (IndoorBLE::receive(o)) IndoorBLE::print(o);
  delay(5);
}
