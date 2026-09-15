#pragma once
// All three anchors: ESP32-WROOM / ESP32 Dev Module, Huge APP partition.
// A=0, B=1, C=2. Set a different index before uploading to each board.
// tools/build_anchors.py builds all three IDs using config/boards.json.
// CLI builds may override with -DANCHOR_INDEX=1. Coordinates live in room.json.
#ifndef ANCHOR_INDEX
#define ANCHOR_INDEX 0
#endif
constexpr bool ENABLE_REFERENCE_TRANSMIT = false; // Optional inter-anchor calibration experiment.
