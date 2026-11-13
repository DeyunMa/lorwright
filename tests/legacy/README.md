# 历史测试归档

`test_mapnav_960.py.txt` 是 960×540 地图空间的旧回归测试，已不参与 pytest。
地图迁移到 1080p 后，新的基准在 `tests/test_mapnav.py`。

2026-11-12 复核：归档测试声称 `m3-g6.jpg` 没有可走线，但现存的
`tests/fixtures/mapnav_960_legacy/m3-g6.jpg` 可见通往钱袋节点的发光线；
该历史描述不能作为事件完成前后路线变化的证据。
