"""Compile distinct A/B/C network-anchor images using the board inventory."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor", choices=("A", "B", "C"), help="Build one anchor; default builds all three")
    parser.add_argument("--cli", help="Path to arduino-cli")
    parser.add_argument("--cli-config", help="Path to arduino-cli.yaml")
    parser.add_argument("--config", default=str(ROOT / "config/room.json"), help="Room configuration used to generate firmware constants")
    args = parser.parse_args()
    bundled = ROOT / ".tools/arduino-cli/arduino-cli.exe"
    cli = args.cli or (str(bundled) if bundled.is_file() else shutil.which("arduino-cli"))
    if not cli:
        parser.error("arduino-cli was not found; install it or supply --cli")
    cli_config = args.cli_config
    if not cli_config and not args.cli and bundled.is_file():
        local_config = ROOT / ".tools/arduino-cli.yaml"
        if local_config.is_file():
            cli_config = str(local_config)
    boards = json.loads((ROOT / "config/boards.json").read_text(encoding="utf-8"))
    if not (ROOT / "firmware/libraries/IndoorBLE/src/NetworkConfig.h").is_file():
        print("NetworkConfig.h is missing: builds will scan on serial only. Configure Wi-Fi and laptop IP, then rebuild before network use.", flush=True)
    subprocess.run([sys.executable, str(ROOT / "tools/configure_firmware.py"), "--config", args.config], check=True)
    for name in ((args.anchor,) if args.anchor else ("A", "B", "C")):
        index = ("A", "B", "C").index(name)
        output = ROOT / "build" / f"anchor_{name}"
        command = [cli]
        if cli_config:
            command += ["--config-file", cli_config]
        command += [
            "compile", "--fqbn", boards[name]["fqbn"],
            "--libraries", str(ROOT / "firmware/libraries"),
            "--build-property", f"compiler.cpp.extra_flags=-DANCHOR_INDEX={index}",
            "--build-path", str(ROOT / "build" / f"compile_anchor_{name}"),
            "--output-dir", str(output),
            str(ROOT / "firmware/anchor_network"),
        ]
        print(f"Building anchor {name} (index {index}): {boards[name]['fqbn']}", flush=True)
        subprocess.run(command, check=True)
        print(f"Anchor {name} firmware: {output}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
