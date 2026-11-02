"""设备层：ADB（手机/模拟器）与桌面（mss+pynput）。"""

from __future__ import annotations

from lorwright.device.adb import AdbDevice
from lorwright.device.base import Device, Frame
from lorwright.device.desktop import DesktopDevice

__all__ = ["AdbDevice", "DesktopDevice", "Device", "Frame", "make_device"]


def make_device(kind: str = "auto", **kwargs):
    """按类型创建设备。auto = 有 adb 设备就用 adb，否则用桌面。"""
    if kind == "desktop":
        return DesktopDevice(**kwargs)
    if kind == "adb":
        return AdbDevice(**kwargs)
    devs = AdbDevice.list_devices()
    if devs:
        return AdbDevice(serial=devs[0], **kwargs)
    return DesktopDevice(**kwargs)
