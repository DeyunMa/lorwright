"""Run the shared Pie64 startup workflow and save a verification screenshot.

Requires an installed lorwright project and a running Pie64 instance.
This compatibility workaround does not change the APK or system properties.
Example on f1, from the project directory:
  .venv/Scripts/python.exe tools/start_lor_pie64.py --serial 127.0.0.1:5555
Use --restart only to intentionally stop an existing client. Otherwise it is
only brought to the foreground. The same workflow is used by lorwright launch
when adb.launch_mode is pie64_trace. A live foreground process is not proof of
a loaded main menu; inspect the saved screenshot before reporting that result.
"""
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

import cv2

from lorwright.device.adb import AdbDevice
from lorwright.device.startup import PACKAGE


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--adb", default="C:/Program Files/BlueStacks_nxt/HD-Adb.exe")
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("logs/startup"))
    args = parser.parse_args()
    out = args.out / uuid.uuid4().hex
    out.mkdir(parents=True, exist_ok=False)
    device = AdbDevice(serial=args.serial, adb=args.adb, launch_mode="pie64_trace")
    receipt = {"serial": args.serial, "success": False}
    try:
        if args.restart:
            device.restart_app(PACKAGE)
        else:
            device.launch(PACKAGE)
        receipt["focus"] = device.current_focus()
        if PACKAGE not in receipt["focus"]:
            raise RuntimeError("LoR未保持前台，启动未验证")
        frame = device.screencap()
        if not cv2.imwrite(str(out / "screen.png"), frame.image):
            raise RuntimeError("无法保存启动截图")
        receipt["success"] = True
        print(f"LoR已在前台，临时跟踪已停止；截图：{out / 'screen.png'}")
        return 0
    except RuntimeError as error:
        receipt["error"] = str(error)
        print(f"启动未验证：{error}")
        return 1
    finally:
        device.close()
        (out / "result.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
