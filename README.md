# IndoorBLE

IndoorBLE is an experimental, local BLE RSSI indoor-positioning system. A moving ESP32 tag broadcasts BLE advertisements; three fixed ESP32 anchors scan them, forward RSSI observations over Wi-Fi to a laptop, and a local dashboard estimates the tag's 2D position.

It includes ESP32 firmware, a dependency-light Python receiver and solver, a browser dashboard, simulation/replay tooling, CSV logging, and automated tests. It is a capstone/lab prototype, not a production tracking or safety system.

> **Accuracy note:** RSSI is affected by multipath, antenna orientation, body blocking, room geometry, and radio differences. Compilation and simulation are not physical accuracy results. Calibrate and evaluate using measured ground truth before reporting accuracy.

## How it works

```text
BLE tag --> Anchor A --\
           Anchor B --- UDP/9000 over private Wi-Fi --> Python service --> local dashboard
           Anchor C --/                                      |
                                                         CSV logs + estimates
```

1. The tag sends non-connectable BLE advertisements containing an ID, boot session, sequence number, requested transmit power, and optional channel label.
2. Anchors A, B, and C passively scan, attach an RSSI measurement, and send JSON datagrams to the laptop.
3. The Python service validates and de-duplicates packets, filters RSSI over a short window, derives approximate ranges, and applies bounded trilateration.
4. The dashboard at `http://127.0.0.1:8000` shows anchors, estimates, diagnostics, and a ground-truth form.

See [the protocol reference](docs/PROTOCOL.md) for the wire format, freshness and de-duplication rules, log schema, and trust boundary.

## Requirements

| Component | Default setup |
|---|---|
| Tag | BLE-capable ESP32; current inventory lists a Seeed XIAO ESP32-S3 |
| Anchors A, B, C | ESP32-WROOM development boards, at least 4 MB flash |
| Firmware toolchain | Arduino CLI or Arduino IDE; Espressif Arduino core **3.3.7** |
| Anchor Arduino target | **ESP32 Dev Module** with **Huge APP (3MB No OTA/1MB SPIFFS)** |
| Laptop | Windows 11 recommended; Python 3.11+ |
| Network | Anchors and laptop on the same ordinary, trusted 2.4 GHz LAN |

The authoritative board targets are in [config/boards.json](config/boards.json). Python runtime and tests use only the standard library; `requirements.txt` records that expectation. Keep antennas clear of metal, use USB data cables for flashing, and keep antenna height/orientation consistent.

## Quick start: simulated dashboard

Simulation exercises the receiver, solver, UI, and logs without Bluetooth, Wi-Fi, or physical boards.

```powershell
Set-Location 'C:\Users\Odysseus\Desktop\Capstone'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -v
.\.venv\Scripts\python.exe -m indoor_ble.server --simulate
```

Open `http://127.0.0.1:8000`. The page must show **SIMULATED DATA**. Press `Ctrl+C` to stop; output is written to a new `logs/simulation_<timestamp>/` directory.

Replay the included synthetic capture:

```powershell
.\.venv\Scripts\python.exe -m indoor_ble.server --replay sample/observations_simulated.csv
```

## Run with three physical anchors

The complete focused guide is [docs/THREE_ANCHOR_SETUP.md](docs/THREE_ANCHOR_SETUP.md). The essential workflow follows.

### 1. Survey the room

Set measured room dimensions and A/B/C locations in [config/room.json](config/room.json). The anchors must be inside the room, distinct, and non-collinear. Spread them around the room rather than placing them in a line.

Regenerate the firmware constants after every geometry or tag-ID change:

```powershell
.\.venv\Scripts\python.exe tools/configure_firmware.py
```

This generates `firmware/libraries/IndoorBLE/src/RoomConfig.h`; rebuild and reflash afterward.

### 2. Add local Wi-Fi settings

Create the ignored local header and enter 2.4 GHz Wi-Fi credentials plus the laptop's LAN IPv4 address:

```powershell
Copy-Item firmware/libraries/IndoorBLE/src/NetworkConfig.example.h firmware/libraries/IndoorBLE/src/NetworkConfig.h
ipconfig
```

Edit `NetworkConfig.h` and replace all placeholders. Use the laptop's active LAN IPv4 for `LAPTOP_IP`, not `127.0.0.1`, a router address, or a VPN address. Do not commit this file.

### 3. Build distinct anchor images

Install the pinned Arduino core, then use the build helper:

```powershell
arduino-cli core update-index --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core install esp32:esp32@3.3.7 --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
.\.venv\Scripts\python.exe tools/build_anchors.py
```

It regenerates room constants and outputs separate images at `build/anchor_A`, `build/anchor_B`, and `build/anchor_C`. Build one with `--anchor A` (or B/C). Each image has its own `ANCHOR_INDEX`; never flash the same index to all anchors.

### 4. Flash tag and anchors

- Flash `firmware/tag_minimal` to the moving tag for baseline positioning.
- Flash each matching network image to its labelled WROOM anchor.
- In Arduino IDE, set `ANCHOR_INDEX` in `firmware/anchor_network/AnchorConfig.h` to 0 (A), 1 (B), or 2 (C) before each build/upload.
- Use the FQBN listed in [config/boards.json](config/boards.json). WROOM anchors need at least 4 MB flash and the Huge APP partition.

A representative CLI flow is:

```powershell
arduino-cli compile --fqbn 'esp32:esp32:esp32:PartitionScheme=huge_app' --libraries firmware/libraries --build-property 'compiler.cpp.extra_flags=-DANCHOR_INDEX=0' --output-dir build/anchor_A firmware/anchor_network
arduino-cli upload --fqbn 'esp32:esp32:esp32:PartitionScheme=huge_app,UploadSpeed=115200' --port COM7 --input-dir build/anchor_A
arduino-cli monitor --port COM7 --config baudrate=115200
```

Replace `COM7` with the actual port and match index/output to A, B, or C.

### 5. Start live positioning

```powershell
.\.venv\Scripts\python.exe -m indoor_ble.server
```

The service receives anchors on UDP 9000 and serves its UI only at `127.0.0.1:8000`. If necessary, allow inbound UDP 9000 narrowly on the Windows **Private** firewall profile for the local subnet. Do not port-forward the UDP or HTTP services.

Wait for all A/B/C anchors to be online. A baseline estimate requires fresh readings from all three. Record known tag positions in the dashboard to create real `ground_truth.csv` evaluation data.

## Modes and output

| Command | Use | Sockets |
|---|---|---|
| `python -m indoor_ble.server` | Live three-anchor positioning | UDP 9000 + local HTTP 8000 |
| `python -m indoor_ble.server --simulate` | Synthetic moving-tag demo | Local HTTP only |
| `python -m indoor_ble.server --replay sample/observations_simulated.csv` | Synthetic packet replay | Local HTTP only |
| `python -m indoor_ble.server --manual` | Two-board sequential RSSI survey | Local HTTP only |

Common options: `--config path/to/room.json`, `--log-dir path`, and `--duration SECONDS`.

Each run creates a timestamped log directory unless `--log-dir` is set:

- `observations.csv` — accepted and duplicate valid observations.
- `positions.csv` — baseline, channel-fusion, and optional Kalman estimates.
- `ground_truth.csv` — manually recorded true points and simultaneous errors.

Synthetic packets and logs retain a `simulated` flag; do not use them as hardware evaluation.

## Configuration and experiments

[config/room.json](config/room.json) is the single source of truth for geometry, anchor IDs, network ports, RSSI model values, filtering, and reference-calibration settings.

- `rssi_at_1m` and `path_loss_n` are initial assumptions, not universal BLE constants. Measure them with the installed tag and room.
- `window_s`, `stale_s`, and `min_samples` determine which readings can contribute to a position.
- `kalman` enables optional constant-velocity display tracking.

The channel tag (`firmware/tag_channels`) emits bursts labelled 37/38/39 and sets matching advertising masks through the platform API. Scanner callbacks record the payload label, not an independently verified RF channel. [docs/EXPERIMENT.md](docs/EXPERIMENT.md) describes source auditing, runtime checks, optional reference scheduling, calibration limitations, and the external capture required for an over-the-air channel claim.

For a simple first radio demonstration without Wi-Fi, flash `tag_minimal` plus `anchor_distance`, then run:

```powershell
.\.venv\Scripts\python.exe -m indoor_ble.server --manual
```

This is a sequential stationary-tag survey with one moved receiver, not simultaneous tracking. See [docs/TWO_BOARD_REVIEW.md](docs/TWO_BOARD_REVIEW.md).

## Validation and limitations

Run local checks with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
.\.venv\Scripts\python.exe -m compileall -q indoor_ble tools
```

Tests cover packet validation, duplicate handling, geometry, filtering, estimation, calibration safeguards, CSV logging, local HTTP/UDP behavior, simulation, and replay. The evidence actually gathered and remaining hardware checks are in [docs/VALIDATION.md](docs/VALIDATION.md).

Keep these claims separate:

- A successful firmware build does not prove radio reception.
- Simulation/replay validates software behavior against generated data, not physical accuracy.
- RSSI ranging is approximate; evaluate many measured positions, orientations, and sessions.
- The optional inter-anchor reference experiment is diagnostic by default and is not survey-free positioning.
- UDP data is unencrypted and unauthenticated; use a trusted private LAN only.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Upload stalls or no serial port | Use a data cable, verify the single board's COM port, hold **BOOT** while connecting on WROOM boards, then press **EN** if needed. |
| Anchor shows `CONFIG_REQUIRED` | Create `NetworkConfig.h` from its example and replace each placeholder. |
| Dashboard loads but anchors are offline | Confirm the same non-isolated 2.4 GHz LAN, correct laptop IPv4, and Private firewall access for UDP 9000. |
| Anchors online but no estimate | Verify all A/B/C indices, geometry, tag ID, and fresh readings from every anchor. |
| Program does not fit | Confirm at least 4 MB flash and select ESP32 Dev Module + Huge APP. |
| Estimate sits at a wall or residual is high | Recheck survey coordinates and RSSI calibration; improve anchor geometry and antenna consistency. |

## Project layout

```text
config/       Room geometry, board inventory, calibration examples
firmware/     Tag/anchor sketches and the IndoorBLE Arduino library
indoor_ble/   Python server, protocol parser, solver, simulation, and web UI
docs/         Setup, protocol, experiments, and validation records
sample/       Synthetic replay data
tests/        Automated Python tests
tools/        Firmware generation, builds, sample generation, and SDK audit
```

## Documentation

- [Three-anchor setup](docs/THREE_ANCHOR_SETUP.md)
- [Protocol and local security model](docs/PROTOCOL.md)
- [Two-board manual survey](docs/TWO_BOARD_REVIEW.md)
- [Channel and reference experiments](docs/EXPERIMENT.md)
- [Validation record](docs/VALIDATION.md)
