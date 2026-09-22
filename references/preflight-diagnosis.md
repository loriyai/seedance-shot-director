# 任务与风险预诊断 V1.20

## 目标

静默确定当前阶段、首要风险和最小参考集。预诊断不进入剧本或可复制提示词，不因低风险制作细节追问。[core-invariants.md](core-invariants.md) 已在启动时读取，下面只路由阶段增量文件。

## 先判断阶段

1. 完整剧本轻量建档或紧凑全局索引；同期只问目标时长、风格、资产列表三项。
2. 分段文案到达时先问“轻度剧本审阅 / 直接按原版分镜”，每次重问；再按选择做首次审阅、审阅稿局部修改、重新优化、确认或回到原版。
3. 分镜规划与编译。
4. 分镜生成块局部修改。

进入分镜前只检查必需配置、已锁定来源，以及当前处理范围及其必要连续性依赖。用户刚确认剧本且当前范围无 P0/配置缺口时，直接进入分镜，不再停下请求第二次确认。

分段文案在用户做出选择前只做原样保存，不解析、不细化、不预跑工具。

## 最小路由

### 剧本审阅

轻度审阅只读：

- `script-enhancement.md`
- `dialogue-normalization.md`
- 需要调用状态时的 `project-state.md`

即使文本含情绪、多人或道具，也不在轻度审阅阶段默认加载情绪、构图、摄影、空间或战斗模块。用户明确要求情绪设计，或存在影响基本逻辑的 P0 空间疑点时，才读对应专项文件。

### 分镜通用

新分镜默认读：

- `dialogue-normalization.md`（有口播时）
- `dialogue-capacity.md`、`dialogue-coverage.md`（有口播时）
- `generation-block-splitting.md`
- `shot-splitting.md`、`timing-allocation.md`
- `unified-plan.md`
- `generation-block-contract.md`、`prompt-template.md`
- `qc-fallback.md`

不另读 `generation-block-ledger.md` 来重建平行台账；V5 的节拍、人物、声音和镜头已在同一规划中，只在查历史台账语义时读该文件。

### 分镜专项（命中才读）

- 动作密集：`shot-task-and-physicalization.md`；高密度战斗再加 `combat-previs.md`。
- 多人、群像或对峙：`composition-directing.md` 和 `spatial-continuity.md`。
- 多场景、同场景跨时间或复杂衔接：`camera-transition.md` 和 `spatial-continuity.md`；只判定时空边界与无对白画面，不为用户决定后期转场方法。
- 情绪、悬疑或权谋反应：`emotion-microexpression-director.md`。
- `@素材`、服装状态版本或剧情内文字：`asset-binding-and-screen-text.md`。
- 生成块局部修改：`local-modification.md`；改时长再加 `timing-allocation.md`。

## 风险判定

可同时标记多种类型，但只选一个首要失败风险：对白容量/归属、动作闭环、多人轴线、时空边界、道具状态、信息揭示、素材绑定或修改范围。

- 机械闸门（不追问，直接按规则修）：块时长必须为整数且 4–15 秒、固定机位与硬切配额、人物台账连续性（`cast`/`offscreen`/`departed`）、`场景：` 只写场景名、`声音安排：` 只写真实约束、尾部余量超限的疑似填秒。
- **P0 必须追问**：当前处理范围或其必要连续性依赖中的身份、关系、说话人、行动目标、冲突结果、关键道具归属或时空无法从来源确定；必需配置缺失；或与当前范围相关的已标记 P0 未解决。
- **P1 可自行执行**：已成立动作的路径、接触点、可见状态和低风险制作设定；不增加新表演节拍。
- **P2 可选**：次要色彩、纹理、辅助声音和装饰性构图；提示词过载时先删。

无关未来 P0 只写入全局索引，处理到相关场次时再追问，不得阻断当前范围。P1/P2 不得伪装成剧情事实，不用制作选择回避 P0。面向 Seedance 的指令使用中文；`@素材`名、型号、专有标识和原文外语台词保持原样。
