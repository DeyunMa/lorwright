# 项目目录与图片

## 目录职责

| 位置 | 内容 |
|---|---|
| `src/lorwright/` | CLI、运行闭环和英雄包。英雄卡面及识别裁片随对应英雄包维护。 |
| `assets/`、`config/` | 共用视觉模板、数字字模、按钮和运行标定。 |
| `tests/`、`tests/fixtures/`、`.github/` | 测试代码、案例 JSON、截图来源说明和 CI。 |
| `tools/` | 测试数据准备、回放、采样和运维。 |
| `docs/`、`docs/history/` | 当前项目说明、阶段状态和历史开发记录。 |
| `research/` | 静态参考数据、研究记录和复核脚本。Jinx 候选池的快照和生成脚本放在 `research/jinx-pool/`。 |
| `../lorwright-test-data/` | 测试截图和研究图片。`fixtures/` 供 pytest 和回放，`archives/` 供历史对照，`research/` 保存研究原图。 |
| `logs/`、f1 的 `logs/` | 实机运行事件、停止截图和诊断原图。各环境独立保存。 |

## 2026-11-18 图片盘点

| 图片用途 | 数量 | 阶段整理后的去向 |
|---|---:|---|
| 共用运行模板与字模 | 391 | `assets/` |
| 英雄包运行图片 | 23 | `src/lorwright/core/champions/*/assets/` |
| 测试截图 | 190 | `../lorwright-test-data/fixtures/` |
| 历史截图 | 29 | `../lorwright-test-data/archives/`，包括已归档的重复图片 |
| 研究卡面和图标 | 27 | `../lorwright-test-data/research/` |
| 本机运行与诊断图 | 804 | 已忽略的 `logs/`。统计仅覆盖本次检查的本机工作区。 |

旧的 `../lorwright-artifacts/` 已从项目同级目录移到本机废纸篓。历史报告中的原路径用于标识当时的输入。需要原始诊断或研究输入时，可从废纸篓恢复该目录。

## 准备和维护测试数据

完整克隆后，在仓库根目录运行：

```sh
python tools/test_data.py
python -m pytest
```

准备脚本从固定提交 `491dc94` 恢复 190 张当前回归图片。需要历史截图和研究原图时，运行 `python tools/test_data.py --include-history` 恢复完整的 246 张。脚本保留原字节，遇到同名异内容会停止。浅克隆先获取对应提交。可用 `LORWRIGHT_TEST_DATA` 指定绝对路径，本地和 CI 在运行测试前准备当前回归图片。

新增回归图片前检查账户和凭据等敏感信息。安全裁剪放数据目录下的 `fixtures/<场景>/`，来源、标注和断言随仓维护。新增到基线以外的图片需随测试变更提供给其他验证环境。含账户信息的原图留在本地运行目录。

查询当前 Git 图片和体积可运行 `python tools/audit_assets.py --json`。回放和对照命令见[离线验收](offline-validation.md)。
