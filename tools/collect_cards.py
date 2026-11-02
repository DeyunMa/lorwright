"""采集卡牌模板：先截整帧，人工裁剪。

用法（设备连着时）：
    python tools/collect_cards.py --device adb
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from lorwright.device import AdbDevice, DesktopDevice


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="adb", choices=["adb", "desktop"])
    ap.add_argument("--out", default="logs/collect")
    args = ap.parse_args()

    dev = AdbDevice() if args.device == "adb" else DesktopDevice()
    frame = dev.screencap()
    dev.close()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "frame.png"
    cv2.imwrite(str(path), frame.image)
    print(f"已保存整帧: {path} ({frame.width}x{frame.height})")
    print("下一步：裁出手牌卡面，存到 assets/cards/<card_id>.png")


if __name__ == "__main__":
    main()
