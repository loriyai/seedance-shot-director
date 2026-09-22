# V5 统一规划

分镜只写一次来源节拍、整句话轮、动作、摄影和声音来源。编译器从同一份规划生成直投正文、审计视图、硬检查和台账，不先写平行文字表再转录。

字段与话轮的实际编码契约见 [compiler-field-contract.md](compiler-field-contract.md)：起草前读一次，字段报错按那张对照表定位，不靠试错，也不重读编译器源码。

## 起草顺序

1. 先锁定全局骨架：一次性确定各生成块的时空边界、话轮分配、尾部预算与两侧留白位置，不先写镜头内容。骨架不可省，切点与留白互相依赖。
2. 骨架定稿后先预计算再写镜头：`plan_voices.py --text` 给出每句话轮的可发音单位、各语速档的可行区间与合法切分点；`plan_voices.py --plan` 对同一份骨架跑一次覆盖差分，漏句、调序、可发音单位总量不一致、档位越界、越出块时长、块内重叠、跨块片段超过单镜容量与缺语气都在这一步清零。跨块片段无法用 `span` 拆分，必须在骨架阶段就切到能装进单镜。手算单位与净发音语速最容易在收尾反复返工。

2b. 逐句扫语气：来源含可听情绪（骂、哭、颤、笑、狠、虚弱、迟疑、狂喜等）的话轮必须填 `tone`，系统与旁白类保持平稳；`compile` 的 `tone_coverage` 与 `check-block` 的同类字段用于逐块核对。可并行的台词与动作必须并行，不把动作排成无口白段。
3. 完整起草只保留“当前块＋下一块入口”；下一块入口确定后再冻结上一块边界，不提前写完全部块。
4. 第 1 块先跑编译管线冒烟：`check-block --block 1` 局部通过，并用同一份规划跑一次 `compile` 确认风格行、人物行、时间轴与台词渲染可编译；只起草一块时“来源覆盖不完整”类错误属预期，其他错误必须为 0。冒烟通过再起草第 2 块，更换话轮分段方式时重跑冒烟。

4b. 每块起草完先看事实自检表（`check-block` 的 `facts`）：场景名与 `scene_id` 是否一致、人物行是否只列了本块入镜角色、发声角色与音效来源是否齐全。整段 `compile` 会另出 `facts.txt`（含无口播头／中／尾区间与语气覆盖），红项清零后才进入语义复核。
5. 每完成一块写进同一份规划并立即 `check-block`；硬错误先局部修复再推进。规划按 3–4 块一批分次写入并即时检查，单次巨型写入一旦失败就要整份重发，成本远高于分批。

## 命令流程

```text
python -B scripts/plan_voices.py --source <锁定来源> --text "<话轮原文>" --profile 短剧常速 --start 0.5
python -B scripts/plan_voices.py --source <锁定来源> --plan <进行中的plan.json>
python -B scripts/compile_plan.py context --project <项目目录> --segment seg001
python -B scripts/compile_plan.py check-block --project <项目目录> --segment seg001 --plan <进行中的plan.json> --block 1
python -B scripts/compile_plan.py compile --project <项目目录> --segment seg001 --plan <plan.json>
python -B scripts/compile_plan.py finalize --project <项目目录> --segment seg001 --build <build> --review <review.json>
```

`context` 返回锁定来源、实际配置摘要、`config_sha256`、默认 `plan_schema_version=5` 和语义复核项；不假填版本、摘要或模型。V5 精简例子见 [plan-example-v5.json](plan-example-v5.json)，对应来源见 [plan-example-source.txt](plan-example-source.txt)。[plan-example.json](plan-example.json) 仅保留为 V4 兼容例子。

`check-block` 只读检查 V5 规划里指定的已起草块；省略 `--block` 时检查当前最后一块。进行中的 `blocks` 可只含已起草前缀，`beats` 可随块累加。输出局部硬错误、警告、镜数、静默镜数、镜头层统计、`tone_coverage`、本块 `facts`（场景名、可见人物、发声角色、无口播区间等）和边界是否确认；最多展示 8 条诊断，不写正式候选。已有下一块时自动读取其时空；没有下一块时用根级 `boundary_context.outgoing` 指出真实后继的时空；若后继尚未知且暂填 `null`，结果为 `provisional`，仅按同一时空临时检查，下一块入口确定后必须重查交界。确认当前块确为整段末块且没有外部后继时用 `--final-block`，仅表示尾部局部检查；不能据此宣称来源已完整覆盖。正式完整规划中的 `boundary_context.outgoing=null` 仍只表示确无后继。

`check-block` 不检查未起草来源的全段覆盖，也不登记或冻结块；当前块修改后须重查，交界改变时重查相邻块。`compile` 只在全部块完成后运行一次全段机械硬检查，返回 `prompt.txt`、`ledger.json`、诊断、`warning_groups`、镜头层 `stats` 与候选摘要。不对同一候选再单独运行一次校验器，也不把局部通过视为最终交付。

V5 复核记录只包含真实语义判断：

```json
{
  "plan_sha256": "编译返回的实际规划摘要",
  "prompt_sha256": "编译返回的实际正文摘要",
  "passed": true,
  "note": "记录实际语义核对与警告处理依据。",
  "warnings_reviewed": ["dialogue_delivery"],
  "checks": {
    "source_coverage": true,
    "action_causality": true,
    "spatial_continuity": true,
    "visual_readability": true,
    "sound_source_semantics": true
  }
}
```

`warnings_reviewed` 填编译结果 `warning_groups` 的全部类别名；无警告才为空列表。不再逐条复制数字索引。有语义问题时令 `passed=false`，修对应规划后重新编译；不用复核标志掩盖错误。`finalize` 只校验候选/来源/配置/工具摘要并登记结果，不重跑全部检查。

## 场景包与分次写入

同一 `scene_id` 的块共用**持久场景包**：块级抬头（`scene`、`atmosphere`）、`scene_design` 的 `lighting`／`tone`／`layering`／`depth_design`／`composition`／`environment` 与 `ambient_effects` 只定义一次，其余块逐字复用。`后景是…` 这类背景层短语在相邻块必须逐字一致，否则模型会在个别块里长出新的树林、楼阁或院落。

`blocking`（人物站位）**不进共享包**：它逐块按当下站位单独写。否则会把后面才发生的站位（尚未登场的门派、还没跑近的孩子）抄进提前的块；设计段里出现本块 `characters` 之外的角色名会被判为“提到本块未登场角色”。

规划按 3–4 块一批分次写入并即时 `check-block`。话轮时间轴默认按表演逐句设计；追求速度时可用 `plan_voices.py --text` 的建议区间批量生成初稿，再只回调情绪停顿与重音异常的少数话轮，不逐句试错。

## 根对象

新规划必须有：

- `schema_version: 5`
- `source_version`、`source_sha256`、`config_sha256`
- `boundary_context`
- `defaults`
- `beats`
- `blocks`
- 可选 `cast`（`{scene_id: [角色名]}`，本场在场人物台账）与 `aliases`（`{群体名: [成员名]}`，例如“家人”）
- 可选 `scenes`（`{scene_id: 场景名}`）：场景名由查表得出，直投 `场景：` 不再手写；同一 `scene_id` 必须对应同一场景名。

`boundary_context` 只含 `incoming` 与 `outgoing`；每项为 `null` 或 `{"scene_id":"…","time_id":"…"}`。`null` 表示锁定来源在该方向确实没有相邻片段，不是“未知”。处理中段、分批或局部修改时从全剧索引或相邻台账填真实时空。

`defaults` 必须含稳定的 `style`、`scene`、`atmosphere`；可选 `scene_name`（直投 `场景：` 只输出它，缺省取 `scene` 的第一分句）、`assets` 与抬头覆盖项 `visual_quality`（中文执行质感）、`render_quality_en`（英文质感前缀）、`negatives`（英文禁项）。`style`原样填写用户选定的完整选项文字；编译时以项目配置中的已选风格原文为准，不用提炼词替换。三者缺省时使用 [visual-style-system.md](visual-style-system.md) 的风格预设。某块不同才用 `header` 局部覆盖。不在 `defaults` 写自由文本人物或声音总括：人物由块记录生成。

`beats` 每项含唯一 `id` 与锁定来源内可定位的 `evidence`。可加 `timing: "parallel" / "serial"`；仅串行时填 `basis` 记录原文先后或物理依赖。无例外时不填空元数据。

## 生成块

每块必填：

- `duration`（4–15 秒整数，按自然内容 `ceil` 后再看留白；不写 7.5 这类界面选不出的值）
- `scene_id`、`time_id`
- `characters`
- `voices`
- `shots`

每块可选：

- `time_label`（元数据“时间”，缺省由 `time_id` 推导）、`weather`（缺省“无”）
- `scene_design`：对象，七项必填 `lighting`、`tone`、`layering`、`depth_design`、`blocking`、`composition`、`environment`，按顺序编译成块级设计段；其中六项（除 `blocking`）与同场景其他块逐字复用，`blocking` 逐块按当下站位写
- `track`：`文戏`（默认）或 `武戏`，决定镜位引导句用中性词还是战斗词
- `header`、`ending`、`silent_head`、`silent_tail`、`ambient_effects`、`entry`、`exit`、`notes`、`departed`（本块离场的角色名列表，作为“人物消失”的依据）

`characters` 是对象列表，无人时为空列表。每项必填 `name`，可选简短 `stage`、实际 `@素材` 的 `asset`、`offscreen`、`first_visible_shot`、`last_visible_shot` 与简述画外状态的 `note`。直投 `人物：` 只列本块可见角色；`offscreen` 的角色改写进 `画外：角色名（note）；`。同一场景相邻块的人物集合必须连续：角色消失要么本块标 `offscreen`，要么写进块级 `departed` 并给出离场依据；新角色首次出现必须能在来源节拍、镜头动作或 `entry`/`exit` 里找到依据，否则按硬错误处理。外貌、服装与剧情状态只在来源支持的镜头或实际素材绑定中处理，不用人物行补参考图。

`scene_id` 是地点，`time_id` 是连续叙事时间；任一变化都分块。`ending`、`silent_head`、`silent_tail` 只在需要覆盖项目默认时填。时空跳转会自动把前尾与后首无对白画面提高至至少 1 秒，不规划后期转场方法。

V5 的 `entry` / `exit` 在简单块可省略，编译器会用首镜与末镜 `action` 派生入口／出口状态；但**同场景连续块的状态延续必须显式填写 `entry`**，下一块首镜还要在动作里复述上一块的出口状态，`exit` 记录本块末镜留下的姿态、朝向与手部道具，供下一块承接核对。

`ambient_effects` 是可选块级列表，先判断当前场景是否有合理、克制且可持续的底声；有则在本块记录一次，避免多数镜头无理由“静默”。例如野外坟地可用轻风掠过荒草的底声，但不能据此新增大风天气或人物反应。用户指定画外声也可记录。每项仍使用 `type/text/provenance/basis`，`provenance` 只能为 `scene_ambient` / `user`，对应 `basis` 为 `scene` / `user`。

## 话轮

`voices` 无口播时为空列表。每个话轮只记一次：

- 必填 `id`、`speaker`、`kind`（对白/OS/旁白）、逐字 `text`、`start`、`end`。
- `profile` 省略时默认“短剧常速”；只在其他语速档时填写。
- `pause` 省略时默认 0.2 秒；明确不同才填数值，`null` 表示待人工核定并产生警告。
- 同一个原始连续话轮只建一个`voice`，不得按逗号、感叹号等标点建立多个声音对象；被动作、他人插话或时空变化真正打断时才建新ID。
- `tone` 在原文有明确特殊情绪或可听说话方式时填写简短中文语气，如`怒骂`、`颤声`；普通话轮省略。来源明确并发才加 `overlap`。

同人隔动作再次开口仍建新 ID，不为省字段合并话轮。

## 镜头

每镜必填 `start`、`end`、`beats`、`action`、`camera`；同块第二镜及以后应写 `transition`（进入本镜的转场方式，缺省按“硬切”编译并给出警告）。

机位配额（硬检查）：固定机位 5 镜块 ≤2、6–7 镜块 ≤3；每块至少 1 个移动镜头；不得连续三镜硬切，硬切占比 ≤50%；同场景每 3 个连续块至少 1 次环绕/升降/摇摄。

散文正文用到的镜头层字段：

- `shot_size`：主体强绑定景别，如 `林舟的中景`；缺省时从 `camera` 提取，提取不到主体会给出警告。
- `movement`：运镜方式，如 `缓推`、`横移跟随`、`固定机位`；缺省时从 `camera` 提取。
- `depth`：景深状态，如 `浅景深`、`中等景深`。
- `environment`：本镜可见的环境持续状态（空气介质或背景持续动态）；缺省时用块级 `scene_design.environment`。
- `reaction`：来源支持或低风险物理副反应，用于“引发……”“强制导致……”分句。
- `label`：功能标签，只进入后台审计视图；缺省按 5／6／7 镜或 11 镜自动推导。
- `camera` 仍是后台机位与构图记录，参与隐藏切镜检查，不直接进入散文正文。

- `action_basis` 省略时等于本镜 `beats`；只在动作实际依据为其中子集时填写。它不能引用本镜外节拍。
- `speech: [{"voice":"V1"}]` 表示整个话轮在该镜。确需跨镜时用 `span:[start,end]`，范围是话轮 `text` 的零基 Unicode 位置，前含后不含。内部端点必须符合 [dialogue-normalization.md](dialogue-normalization.md)；用程序定位，不靠目测。
- 同一`voice`在同一镜即便分配了相邻`span`，直投时仍合为一行`台词：`，不按标点另起行。多个不同话轮即使说话人相同，也不越过来源动作或停顿强行合并。
- `effects` 只写本镜相对 `ambient_effects` 的变化；没有就省略。实际声音项用 `type/text/provenance/basis`，来源声/可见动作声的 `basis` 引用本镜 beat，用户声写 `user`。当块级和镜级均无声音时自动编译为“静默”，不虚构音效。已有 `ambient_effects` 时不可在镜头显式声称静默。
- `action`只写本镜实际可见的表演、动作和可见结果；不复述台词含义、抽象心理或OS。`camera`依表演设计固定与运动的对照，运动镜头写清起点、路径、落点。
- 可选 `performance`、`screen_text`、`notes`只在确有信息时填写。必须执行的动作、声音或画面文字不得只放 `notes`。

15 秒块默认 5 镜、允许 5–7 镜（群体入场、对白密集、情绪反转或顺序明确的多动作链才可增加，不得拆同一表演目标凑数），任何单镜最长 5 秒；其他硬约束见 [core-invariants.md](core-invariants.md)。

## 修改与恢复

修镜头时只更新同一规划的指定字段及必要相邻关系，复用其余字段，然后生成新候选。不直接修改编译出的 `prompt.txt` 却沿用旧台账。来源、配置、工具或候选文件变化时旧复核失效。V1–V4 继续兼容历史规划，但不用它们生成新冗余规划。

## 覆盖与台账复核清单

台账信息直接写在统一规划与检查结果里，不另建平行表格。

### 输出前逐条检查

- 每个来源节拍只发生一次，可跨镜映射有序片段；优先完整覆盖整段。短尾按生成块拆分规则合并或联合重排，只有用户明确同意暂存的未完稿才登记未使用。
- 每句台词出现一次且只出现一次；归一化比较后，输出台词按原顺序逐字覆盖原文。只忽略换行两侧排版缩进；外语、型号、数字及任何尚未获准删除的行内空格都属于锁定文本，增删或合并必须报错。
- 同一句台词跨镜时，每个内部切分点都位于锁定来源已有的自然口播标点，或由同一话轮原始换行确定性生成且经反查成立的逗号之后，标点归前片段；任意新增标点、空格变化和不对应原始换行的逗号不得作为切点。
- 台词说话人正确，角色对白、OS 与旁白相互区分。
- 关键动作有可见结果；动作说明不遗漏。
- 跨场景或同场景跨时间已拆块；地点改变时换 `scene_id`，同地点时间跳转时换 `time_id`，内部及`boundary_context`所示跨批边界两侧各有至少1秒无对白画面；新时空变化有来源依据，不替用户设计后期转场。
- 输出没有新增剧情、人物关系、反转或结局。

发现遗漏、重复、顺序变化、说话人错配或新增叙事，停止输出并重划生成块或镜头。

### 自动检查的边界

脚本只对能可靠识别的台词格式提供机械检查；无说话人引号段、多行混排、“念/不念”、简称归属和未闭合引号均可能需要人工台账。出现覆盖不完整警告时，即使脚本退出码为 0，也不能宣称全量台词、动作或剧情已通过。屏幕文字和动作中的台词关键词引用不计为实际口播。原文的整体顺序、语气、因果以及自然收尾是否完整，必须另做语义复核。
