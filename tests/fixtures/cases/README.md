# 实战截图案例

可以把实战截图留作以后重复使用的案例。图片放在 tests/fixtures/screens/，在本目录增加 JSON 标注。
不需要启动 f1，运行：

    rtk proxy .venv/bin/python -m pytest tests/test_screen_cases.py -q

## 标注约定

参考 historical.json，每份文件包含 schema_version、source、profiles、cases。

- source：记录设备、游戏版本、采集日期、期望值的核对依据，以及图片是否连续。
  不知道版本或日期时写 unknown，不要从文件名猜。游戏升级后新建文件，保留旧版案例。
- profiles：保存原始截图尺寸 capture_size、识别设计尺寸 design_size，以及按设计
  尺寸标定的 layout 矩形 [x,y,w,h]。历史标定保存在 JSON 内，不随当前配置变化。
- cases：每个案例有唯一 id、screens 下的相对图片路径 image、profile 和 expected。
  expected 支持 ui_state、mana、nexus_hp、enemy_nexus_hp、hand_costs、hand_expanded、
  my_unit_count、enemy_unit_count。只写人工核对过的字段；不确定的字段省略，不填 null。
  费用与单位数量为识别验收值时，必须注明局部遮挡等已知限制，不能把漏检误写成真值。

测试先校验 JSON 字段、尺寸、矩形和图片路径，再运行真实的归一化与 StateParser。
每张图使用独立 parser，不继承另一张图的法力/血量，避免缓存掩盖缺失读数。
当前 historical.json 的期望取自已有回归测试；它们是独立历史截图，不能当作
一次真实连续操作的前后帧，也不证明新版游戏仍适用。

## 怎样采集有用的案例

1. 保留原始完整截图，不缩放、不加标记。图片可按版本/日期建子目录。
2. 优先采集同一操作前、动画中、稳定后的画面，例如收起手牌、展开手牌、拖牌后。
3. 另记动作、时间、实例、实际分辨率及人工看到的变化；真正连续的记录才标为连续。
4. 首先核对 UI 状态和安全性，再标注费用、血量、单位等细节。失败案例同样值得保留。
5. 截图不要包含密码、登录令牌、私人聊天等；提交前检查账号信息。含敏感信息的原图
   留在不入库的 artifacts 中，用不含敏感信息的对局画面作为仓库 fixture。

单图案例验证识别结果；它本身不能证明手势实际生效。动作结果验证还需要真实连续帧，
或明确标为合成的状态序列测试，不要把不同对局的图片拼成实测成功证据。
