# 单位数字模板

这些 PNG 由游戏资源里的 `BeaufortforLOL-Bold` 渲染：0–9，字号 18–44（步长 2）。
运行时只读 PNG，不依赖 Pillow 或字体文件。

来源字体：
`../lorwright-artifacts/analysis/resources/extracted/BeaufortforLOL-Bold__137.ttf`

重新生成时保持文件名 `<digit>-<size>.png`，`DigitReader` 会按文件名首段识别数字，
并先裁到笔画外框再归一化到 16×24。
