# ADR-0003：主路径改为 ADB，桌面窗口作回退

- 状态：**Accepted**
- 日期：2026-11-02

## 背景

最初设计基于 Windows 桌面窗口：mss 截屏 + pynput 模拟鼠标。
在真机上验证 ADB 后，发现 ADB 路径明显更简单。

## 事实（真机验证）

小米 2510DRK44C，USB 调试：

- `adb devices` → `bc9e8c42 device`
- `adb exec-out screencap -p` → 1156×2510 PNG，正常
- `adb shell monkey -p com.riotgames.legendsofruneterra ...` → 游戏正常启动
- 加速器 TUN 模式下可进国际服

## 决策

**主路径改为 ADB**，桌面模式保留为调试回退。

```python
class Device(Protocol):
    def screencap(self) -> Frame: ...
    def tap(self, x: int, y: int) -> None: ...
    def swipe(self, x1, y1, x2, y2, ms: int) -> None: ...
    def size(self) -> tuple[int, int]: ...
```

## 对比

| 环节 | 桌面窗口 | ADB |
|---|---|---|
| 截图 | mss + 窗口定位 + DPI | `adb exec-out screencap -p` |
| 输入 | pynput + 坐标换算 | `adb shell input tap` |
| 多开 | 多窗口抢焦点 | `-s emulator-5554` |
| 后台运行 | 窗口须前台 | 可最小化 |
| 坐标 | 需换算窗口偏移 | 就是屏幕坐标 |

## 后果

| 影响 | 说明 |
|---|---|
| 代码更简单 | 少掉 DPI/焦点/窗口三个坑 |
| 多开天然支持 | 每个实例一个 serial |
| 可在 Mac 开发 | 手机连 Mac 即可，不必等 F1 |
| 依赖 adb | 需要平台工具；模拟器自带 |
| 分辨率绑定 | 模板必须按目标分辨率采 |

## 备选（已否决）

- 只用桌面窗口：多开和后台运行都难受
- 只用模拟器不用真机：调试时多一层开销
