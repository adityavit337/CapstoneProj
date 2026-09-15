#pragma once
// A=0 (XIAO S3), B=1 (DevKit V1), C=2 (ESP32-WROOM / ESP32 Dev Module).
// CLI builds may override with -DANCHOR_INDEX=1. Coordinates live in room.json.
#ifndef ANCHOR_INDEX
#define ANCHOR_INDEX 0
#endif
constexpr bool ENABLE_REFERENCE_TRANSMIT = false; // Enable only at checklist stage 5.
