---
name: seedance-shot-director
description: "将剧本、分段文案或对白稿转换为可直接投喂 Seedance 2.0 / 2.5 的工业级国风漫剧分镜提示词；适用于 3D 国风动漫、武侠、仙侠、悬疑和权谋类镜头设计，不用于改写剧情创作。"
---

# Seedance Shot Director

## 任务边界

- 只做分镜化、画面化和提示词化，不改写剧本，不新增关键剧情、反转、人物关系或结局。
- 原文事件、动作说明、台词、旁白、OS、说话人和用户提供的 `@素材` 必须保留。换行仅能按 [dialogue-normalization.md](references/dialogue-normalization.md) 做口播排版规范化。
- 面向 Seedance 的可复制提示词只输出中文，不附英文版或中英双语版；必要的型号、素材标识和原文外语台词保持原样，不擅自翻译或改写。
- 可补足不改变叙事的外观、材质、天气、光线、环境和动作细节。身份、关系、行动目标、冲突结果、说话人归属、时间或空间跳转不明确时，先追问。
- 默认画幅 `16:9`。目标时长必须在本对话中确定为 `15 秒`或 `30 秒`；完整剧本还必须在生成前确定视频风格和是否输出资产列表。按 [intake-gate.md](references/intake-gate.md) 执行前置门禁。
- 生成块是可独立投喂的视频提示词。`15 秒`模式下，完整块严格为 15 秒、五个镜头；仅最后一个尾块可按 `4-<15 秒`实际时长生成，并按内容密度使用 1-5 个镜头。不足 4 秒的尾部原文不生成、不并回上一块，须单独暂存并提示合并到下一次分段文案。`30 秒`块按剧情密度使用 8-12 个镜头。
- 每块自包含，禁止使用“同上”“沿用上一块”“参考前文”。局部修改只重写指定块和必要的相邻衔接。

## 输入识别与前置流程

1. 用户明确指定“完整剧本”“这是完整剧本”“发送完整剧本”“分段文案”“只处理这段”或“修改镜头”时，以其说明为准。明确标注为完整剧本时，完全跳过字数统计与 `150000` 门禁，直接做结构扫描和后台建档；不得为了分类、报告或确认而运行统计脚本。仅在用户未说明输入类型时，才按“汉字数量＋标点符号数量”计算正文近似字数，不超过 `1200` 视为短分段，超过则推断为完整剧本。
2. 仅对“未注明类型、由字数推断为完整剧本”的输入执行超大文件门禁：正文近似字数超过 `150000` 时，先暂停并询问是否误发送；用户确认无误后才继续。统计必须运行 `scripts/count_script_chars.py` 或使用其中的同一算法，严禁用文件大小、UTF-8/UTF-16 字节数、编码单元数或聊天包装长度代替。
3. 明确标注的完整剧本，或通过推断型超大文件门禁的完整剧本，只做一次人物、场景、道具、时间线、空间关系后台建档，并询问三个前置选项：目标时长、固定五项视频风格、是否输出资产列表。三项完成后等待用户发送片段；不得因收到完整剧本而自动生成开头。
4. 无论是否输出资产列表，都必须完成后台资产建档。选择输出时按 [asset-list-spec.md](references/asset-list-spec.md) 输出；风格按 [style-profiles.md](references/style-profiles.md) 记录。
5. 分段文案只有在前置配置完成后才按事件与对白容量拆成块，再拆镜头。局部修改按 [local-modification.md](references/local-modification.md) 处理。
6. 配置完成后按 [preflight-diagnosis.md](references/preflight-diagnosis.md) 静默识别任务类型、叙事密度和首要失败风险，据此读取必要参考文件；只有 P0 叙事信息缺失时才追问。
7. 固定视觉层使用短而稳定的句子；详细规则只用于生成前台账与质检。按当前模式读取参考文件，不全量加载。

## 生成流程

1. 依据预诊断结果确定本段的主任务、首要失败风险、必读参考和提示词信息优先级，不把诊断过程输出给用户。
2. 提取每个不可丢失的来源节拍：事件、动作及结果、台词/OS、说话人、人物、道具、场景、时间跳转和空间状态。
3. 对含对白的段落，先按 [dialogue-normalization.md](references/dialogue-normalization.md) 规范化可连续口播的换行，再按 [dialogue-capacity.md](references/dialogue-capacity.md) 估算自然口播与反应容量。超出容量时新增块，不压缩语速。
4. 按 [generation-block-splitting.md](references/generation-block-splitting.md) 以事件容量划块；`15 秒`完整块优先一个主要场景且固定五镜。最后剩余内容若自然时长为 `4-<15 秒`，按实际时长生成 1-5 镜尾块；若不足 4 秒，原文单独暂存并输出规定提示，不生成镜头。跨场景时写清每个场景的光线、氛围、站位和转场原因。
5. 为每块建立入口、出口、来源节拍与“台词/镜头”映射台账。选择能快速建立焦点的开场镜头，不默认使用远景或空镜。
6. 按 [shot-splitting.md](references/shot-splitting.md) 与 [timing-allocation.md](references/timing-allocation.md) 拆镜并分配时间。每镜必须有唯一主目标、可见起点、过程、结果和结束状态；每镜至少推进情绪、动作/空间、信息或戏剧压力之一。
7. 用 [prompt-template.md](references/prompt-template.md) 把后台导演台账压缩为前台可执行提示词。每镜只输出画面与动作、摄影机与构图、表演、光线与声音、台词，以及确有必要的衔接；后台字段不得作为标签逐项倾倒到正文。人物动作和台词均用全名或明确身份，不使用模糊代词。
8. 按需读取 [spatial-continuity.md](references/spatial-continuity.md)、[emotion-microexpression-director.md](references/emotion-microexpression-director.md)、[camera-transition.md](references/camera-transition.md)；仅高密度战斗读取 [combat-previs.md](references/combat-previs.md)。出现用户提供的 `@素材` 或剧情内可见文字时，读取 [asset-binding-and-screen-text.md](references/asset-binding-and-screen-text.md)。
9. 在输出前执行 [dialogue-coverage.md](references/dialogue-coverage.md) 与 [qc-fallback.md](references/qc-fallback.md) 的 P0/P1 检查；发现典型生成风险时按 [failure-repair-playbook.md](references/failure-repair-playbook.md) 修复。可用时运行 `scripts/validate_dialogue_and_timeline.py --source <原剧本> --output <生成块> --duration 15`。

## 输出契约

- 可复制正文的块头、镜头编号和字段以 [generation-block-contract.md](references/generation-block-contract.md) 与 [prompt-template.md](references/prompt-template.md) 为唯一准则。
- 可复制正文使用中文镜头指令，不自动附加英文翻译、英文技术块或双语复述。
- 时长、画幅和质检状态仅在块标题或后台台账出现；可复制正文不重复组合时长与画幅，也不用旧式约束标签。
- 固定视觉层统一渲染质感，不把单一光线、粒子特效或无额外文字限制套到所有场景。具体光线、特效、焦点、景深与运镜逐镜写明。
- 每块末镜预留 `0.3-0.8 秒`无对白收束，锁定人物位置、视线、道具、动作结果与情绪。发生时间跳转时，写明视觉匹配和环境、年龄、服装、道具、季节或空间状态中的至少一项变化。

## 参考路由

- [preflight-diagnosis.md](references/preflight-diagnosis.md)：生成前的任务类型、叙事密度、风险等级与参考文件路由。
- [generation-block-contract.md](references/generation-block-contract.md)：独立块头、场景/站位、入口出口和五镜头契约。
- [prompt-template.md](references/prompt-template.md)：可复制正文的逐镜字段和书写骨架。
- [composition-directing.md](references/composition-directing.md)：逐镜主体落点、层次、留白、遮挡与关系构图。
- [prompt-layering.md](references/prompt-layering.md) 与 [visual-style-system.md](references/visual-style-system.md)：稳定视觉层、场景变量光影和负面约束。
- [dialogue-capacity.md](references/dialogue-capacity.md)、[dialogue-normalization.md](references/dialogue-normalization.md)、[dialogue-coverage.md](references/dialogue-coverage.md)：对白容量、换行排版和逐字覆盖。
- [shot-splitting.md](references/shot-splitting.md)、[timing-allocation.md](references/timing-allocation.md)、[shot-task-and-physicalization.md](references/shot-task-and-physicalization.md)：镜头边界、空镜预算、时长与动作闭环。
- [camera-transition.md](references/camera-transition.md) 与 [spatial-continuity.md](references/spatial-continuity.md)：切镜动机、转场、轴线和块间承接。
- [generation-block-ledger.md](references/generation-block-ledger.md) 与 [qc-fallback.md](references/qc-fallback.md)：覆盖台账、质量门禁和修复。
- [failure-repair-playbook.md](references/failure-repair-playbook.md)：常见生成失败的症状、原因与最小修复顺序。
- [asset-list-spec.md](references/asset-list-spec.md)、[style-profiles.md](references/style-profiles.md)、[local-modification.md](references/local-modification.md)：按需读取的资产、风格与局部修改规则。
- [asset-binding-and-screen-text.md](references/asset-binding-and-screen-text.md)：`@素材`精确绑定、资产状态版本与剧情内文字的可见性协议。
- [intake-gate.md](references/intake-gate.md)：完整剧本配置、超大文件确认和“等待片段后生成”的前置状态机。

## 核心约束

- 原文每个事件与每句台词只能覆盖一次；台词逐字、语序与说话人不变，OS、旁白、对白相互区分。
- 空镜只可用于时间跳转、空间揭示、情绪留白或转场；`15 秒`块通常至多一个，且不超过 `1.5 秒`，不得连续出现。
- 相邻镜头不得用重复凝视、推镜、握拳、皱眉或环境动态凑时长。同一情绪只有发生升级、转折或结果时才能二次表现。
- 每个镜头用合并后的自然语言明确主动作和可见结果；摄影信息至少让主体关系、景别、机位和主运镜可执行，焦点、景深、光线、环境和声音仅在承担叙事功能或发生变化时写。无变化或与块头相同的信息不重复。“后跟拍”“缓慢推进”“电影感”等词不能单独成立。
- 提示词按“原文与说话人 → 连续性 → 镜头执行 → 表演与声音 → 风格装饰”的顺序保护信息；需要压缩时先删重复和装饰性内容，不得牺牲剧情、台词、时长或连续性。
