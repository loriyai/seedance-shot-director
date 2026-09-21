# V5 编译器字段契约

本页把编译器实际接受的字段与编码方式一次写清，起草前读一遍，字段报错时按表核对，不靠试错、不重读 `compile_plan.py`。规则与 [unified-plan.md](unified-plan.md) 冲突时以本页的机械契约与工具实测为准。

## 规划根对象

- 必须：`schema_version: 5`、`source_version`、`source_sha256`、`config_sha256`、`defaults`、`beats`、`blocks`；V4 起 `boundary_context` 必填。
- `defaults` 必须含 `style`、`scene`、`atmosphere` 三项非空单行文本，可选 `assets`、`visual_quality`、`render_quality_en`、`negatives`（三个抬头覆盖项缺省取风格预设）；不写人物总括或声音总括。
- 某块场景或氛围不同时用块级 `header` 覆盖同名键，块内优先。
- `boundary_context.incoming` / `outgoing` 只能是 `null` 或 `{"scene_id":…, "time_id":…}`；`null` 仅表示该方向确实没有相邻片段，不表示未知。

## 生成块

- 必须：`duration`、`scene_id`、`time_id`、`characters`、`voices`、`shots`。
- 可选：`header`、`entry`、`exit`、`ending`、`silent_head`、`silent_tail`、`ambient_effects`、`notes`、`time_label`、`weather`、`scene_design`、`track`。
- `scene_design` 为对象且七项全必填：`lighting`、`tone`、`layering`、`depth_design`、`blocking`、`composition`、`environment`；缺省时正文按场景与氛围兜底并给出警告。
- `track` 只能为 `文戏`（默认）或 `武戏`；`time_label` 缺省由 `time_id` 推导，`weather` 缺省为 `无`。
- 15 秒块默认 5 镜、允许 5–7 镜（6 镜取 1／2／3／4／8／11 槽，7 镜取 1／2／3／4／6／8／11 槽）；30 秒原生块默认 11 镜（偏离给警告）；4–14.9 秒短块镜数为 `ceil(时长/5)` 至 5；任何单镜不超过 5 秒。
- 首尾无口播时段自动推导：入口时空变化 → 头部至少 1 秒；出口时空变化 → 尾部至少 1 秒；无后继且独立收束 → 尾部至少 0.5 秒。该时段必须落在首镜、末镜之内，且不能被任何口播占用。

## 节拍

- `beats[].evidence` 必须是锁定来源中逐字存在的子串，空格与标点都要一致。
- 登记的节拍必须全部被至少一个镜头引用；每个镜头的 `beats` 非空。
- V5 不接受镜头级 `action_basis`（出现即报未知字段）；省略时即等于本镜 `beats`。

## 话轮与镜头

- `voices[]` 必须：`id`、`speaker`、`kind`（对白/OS/旁白）、`text`、`start`、`end`；可选 `pause`、`profile`、`tone`、`overlap`。语法档位为短剧常速 4.0–5.2、短剧快节奏 4.5–5.8、情绪慢速 3.3–4.4 个可发音单位/秒。`tone` 只写可听情绪，不得出现“说”“OS”“旁白”或“以……的语气”这类说话方式，否则编译器直接报错——说话方式由 `kind` 决定。
- 同一块内每个话轮的 `text` 必须被本块镜头**完整消费**：`span` 从 0 连续推进到 `len(text)`，不能只消费一部分。
- 用 `span` 把一个话轮拆到多个镜头时，`voice.text` 必须是**来源里的完整话轮**：编译器会拿这段文本回查来源索引。片段文本不在索引中，任何内部切分都会报“台词只能在原文已有标点或可核实的换行规范化逗号之后拆分”。
- 因此长话轮跨生成块时，**不要用 `span` 跨块**：改为每块登记本块之内的片段（各自独立 `id`），每个片段在同一镜内用完，片段顺序拼接必须与来源话轮逐字一致。这是记账方式，直投正文仍然是每镜一行台词。
- 切分点只能落在来源已有标点之后，或同一话轮内部无标点换行经规范化得到的逗号之后；标点归前一片段。引号、括号与标点串内部、词中间都不是切点。
- 净发音语速 = 可发音单位 ÷（`end` − `start` − `pause`）必须落在所选档位内；文本含数字、外语、书名号等不定发音时只给警告，由人工按实际读法复核。

## 画面与声音字段

- 镜头必填：`start`、`end`、`beats`、`action`、`camera`；散文层可选：`shot_size`、`movement`、`depth`、`reaction`、`environment`、`label`、`transition`。
- `shot_size` 写主体强绑定景别（如 `林舟的中景`）；缺省从 `camera` 提取，提取不到具名主体给出 `camera_continuity` 警告。
- `movement` 写运镜方式（如 `缓推`、`固定机位`）；缺省从 `camera` 提取，仍找不到时按固定机位处理。
- `camera` 不得出现隐藏切镜措辞（切至、切到、切回、切换、间切、反打、蒙太奇，或景别词加“切”）。`action` 只有在同句出现摄影语境词时才按隐藏切镜拦下。
- `ambient_effects` 只接受 `scene_ambient` / `user` 来源与对应 `basis`；块级已有稳定底声时，镜头不得再写“静默”，镜头 `effects` 只记本镜相对变化。
- 镜头 `effects` 中 `source` / `visible_action` 的 `basis` 必须引用**本镜** `beats`。
- 末镜 `声音安排：` 由编译器按末镜是否带口播选择措辞：有口播写“本镜台词按来源合法标点自然连贯，不另拆分或增加停顿”，无口播写“本镜无口播，仅保留环境与动作声与连续画面”；无口播镜出现“台词”字样即为硬错误。
- 人物记录 `characters[]` 只渲染角色名；`stage`、`asset`、`offscreen`、`first_visible_shot`、`last_visible_shot` 留后台，且首次/最后可见镜头必须是本块范围内的整数。

## 第一块冒烟测试

新项目、换了编码方式或第一次写长话轮时，先只起草第 1 块跑通管线，再往下堆：

1. 起草第 1 块，`compile_plan.py check-block --block 1` 必须 `local_passed`（WARN 可留待语义复核，ERROR 必须改字段）。
2. 用同一份规划跑一次 `compile_plan.py compile`：此时只应出现“来源覆盖不完整”一类错误，其他结构、身份、风格与时间轴错误必须为 0。只起草一块时覆盖类错误属预期，不是失败。
3. 逐项确认风格行、`人物：`、时间轴、台词渲染与留白位置符合预期。
4. 冒烟通过后再起草第 2 块；若中途更换了话轮分段方式，重跑一次冒烟。

## 起草前预避的机械硬拦

按这三条写，可以少走一轮修复：

- 摄影与动作字段里出现“切”字会被当作隐藏切镜（例如“画面中部斜切构图”）；改用实体描述，如“刀锋横过画面前景”。
- 同一镜 `action` 里出现三个及以上具名角色并带台词会触发表演警告；次要角色写“家人／众人”，或把独立动作拆到相邻镜。
- 同场景相邻块的背景层短语（`后景是…`）必须逐字一致，否则触发参照物漂移警告；按 [unified-plan.md](unified-plan.md) 的场景包复用。

## 报错对照

- “未知字段/字段缺失”：核对上表允许键，注意 V5 不接受 `action_basis`。
- “声明的话轮未完整分配到镜头”：本块话轮被截断，补齐 span 或改为本块片段。
- “台词只能在原文已有标点…之后拆分”：用片段文本做了 `span` 切分，改回完整话轮或取消切分。
- “来源声或可见动作声的 basis 必须引用本镜来源节拍”：`basis` 写成了别镜的节拍。
- “一个编号只能是一镜”：把 `camera` 里的切镜措辞拆成独立编号。
- “生成块track只能为…”：`track` 只能写 `文戏` 或 `武戏`。
- “景别未绑定具名主体”：把景别写成 `角色名的中景` 这类主体强绑定形式，或在 `shot_size` 里补齐。
- “本块缺少块级设计”：补 `scene_design` 七项，或在导演详版中接受兜底。
