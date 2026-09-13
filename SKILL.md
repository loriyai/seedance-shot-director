---
name: seedance-shot-director
description: "将剧本、分段文案或对白稿转换为可直接投喂 Seedance 2.0 / 2.5 的工业级国风漫剧分镜提示词；支持用户在分镜前选择受控优化，补足动作、表情和细节但不新增或改写剧情；适用于 3D 国风动漫、武侠、仙侠、悬疑和权谋类镜头设计。"
---

# Seedance Shot Director

## 任务边界

- 核心工作是分镜化、画面化和提示词化；仅当用户明确选择“优化分段剧本”时，才在分镜前执行 [script-enhancement.md](references/script-enhancement.md) 的受控增强。任何模式都不得新增或改写剧情、反转、人物关系、行动目标或结局。
- 每个新片段先保存为不可覆盖的“原版剧本 V0”。用户确认错漏字、标点、说话人或表现方式修订时，按 [script-enhancement.md](references/script-enhancement.md) 另存递增的修订原版 `V0.1`、`V0.2`……；不得覆盖最初 V0，也不得把动作扩写混入修订原版。只有用户确认后的优化稿才能成为当前分镜来源。
- 台词、旁白与 OS 在优化阶段逐字锁定；疑似文字错误只标记，不静默修改。进入分镜阶段后，换行仅能按 [dialogue-normalization.md](references/dialogue-normalization.md) 做口播排版规范化。
- 面向 Seedance 的可复制提示词只输出中文，不附英文版或中英双语版；必要的型号、素材标识和原文外语台词保持原样，不擅自翻译或改写。
- 分镜生成阶段可补足不改变叙事的外观、材质、天气、光线、环境和动作细节；剧本优化阶段只能补充 [script-enhancement.md](references/script-enhancement.md) 白名单内且有来源依据的可见动作和表演细节。身份、关系、行动目标、冲突结果、说话人归属、时间或空间跳转不明确时，先追问。
- 默认画幅 `16:9`。目标时长必须在本对话中确定为 `15 秒`或 `30 秒`；完整剧本还必须在生成前确定视频风格和是否输出资产列表。按 [intake-gate.md](references/intake-gate.md) 执行前置门禁。
- 生成块是可独立投喂的视频提示词。`15 秒`模式下，完整块严格为 15 秒、五个镜头；仅最后一个尾块可按 `4-<15 秒`实际时长生成，并按内容密度使用 1-5 个镜头。不足 4 秒的尾部原文不生成、不并回上一块，须单独暂存并提示合并到下一次分段文案。`30 秒`块按剧情密度使用 8-12 个镜头。
- 每块自包含，禁止使用“同上”“沿用上一块”“参考前文”。局部修改只重写指定块和必要的相邻衔接。

## 输入识别与前置流程

1. 用户明确指定“完整剧本”“这是完整剧本”“发送完整剧本”“分段文案”“只处理这段”或“修改镜头”时，以其说明为准。明确标注为完整剧本时，完全跳过字数统计与 `150000` 门禁，直接做结构扫描和后台建档；不得为了分类、报告或确认而运行统计脚本。仅在用户未说明输入类型时，才按“汉字数量＋标点符号数量”计算正文近似字数，不超过 `1200` 视为短分段，超过则推断为完整剧本。
2. 仅对“未注明类型、由字数推断为完整剧本”的输入执行超大文件门禁：正文近似字数超过 `150000` 时，先暂停并询问是否误发送；用户确认无误后才继续。统计必须运行 `scripts/count_script_chars.py` 或使用其中的同一算法，严禁用文件大小、UTF-8/UTF-16 字节数、编码单元数或聊天包装长度代替。
3. 明确标注的完整剧本，或通过推断型超大文件门禁的完整剧本，只做一次人物、场景、道具、时间线、空间关系后台建档，并询问三个前置选项：目标时长、固定五项视频风格、是否输出资产列表。三项完成后等待用户发送片段；不得因收到完整剧本而自动生成开头。
4. 无论是否输出资产列表，都必须完成后台资产建档。选择输出时按 [asset-list-spec.md](references/asset-list-spec.md) 输出；风格按 [style-profiles.md](references/style-profiles.md) 记录。
5. 分段文案只有在前置配置完成后才进入处理。收到每个新片段时先锁定原版 V0，再按 [intake-gate.md](references/intake-gate.md) 询问“1. 优化分段剧本；2. 不优化，直接按原版分镜”；用户在同一消息中已明确选择时不得重复询问。
6. 用户选择优化时读取 [script-enhancement.md](references/script-enhancement.md)，对原稿已有动作采用原位替换式细化，输出带标记的审阅稿并等待“确认剧本”；确认前不得拆生成块或生成分镜。用户选择不优化、发送“使用原版剧本”，或确认优化稿后，才锁定当前分镜来源并继续。
7. “修改剧本/修改某段”按 [script-enhancement.md](references/script-enhancement.md) 处理；“修改镜头/修改生成块”按 [local-modification.md](references/local-modification.md) 处理，不得混用两类底稿。
8. 配置完成后按 [preflight-diagnosis.md](references/preflight-diagnosis.md) 静默识别任务类型、叙事密度和首要失败风险，据此读取必要参考文件；只有 P0 叙事信息缺失时才追问。
9. 固定视觉层使用短而稳定的句子；详细规则只用于生成前台账与质检。按当前模式读取参考文件，不全量加载。

## 生成流程

1. 确认当前分镜来源已经锁定为当前原版基线（V0 或最新 V0.x）或用户确认后的干净优化稿；审阅标记、疑点说明和版本提示不得进入生成块。依据预诊断结果确定本段的主任务、首要失败风险、必读参考和提示词信息优先级，不把诊断过程输出给用户。
2. 提取每个不可丢失的来源节拍：事件、动作及结果、台词/OS、说话人、人物、道具、场景、时间跳转和空间状态。
3. 对含对白的段落，先按 [dialogue-normalization.md](references/dialogue-normalization.md) 规范化可连续口播的换行，再按 [dialogue-capacity.md](references/dialogue-capacity.md) 建立不依赖镜头边界的连续声音轨。默认使用短剧常速；同一说话人、同一语气且语义连续的逗号短句连贯说完，切镜、回忆画面和反应镜头不得自动增加气口。超出容量时新增块，不压缩语速；明显低于所选语速档时重排时间，不用空白拖长。
4. 按 [generation-block-splitting.md](references/generation-block-splitting.md) 以“连续声音轨＋必须串行的来源动作”判断最少必要块数；受控优化补入的动作默认与口播、回忆或反应画面并行，不得仅因细节更多而增加块数。`15 秒`完整块优先一个主要场景且固定五镜。最后剩余内容若自然时长为 `4-<15 秒`，按实际时长生成 1-5 镜尾块；若不足 4 秒，原文单独暂存并输出规定提示，不生成镜头。跨场景时写清每个场景的光线、氛围、站位和转场原因。
5. 在后台建立入口、出口、来源节拍与“台词/镜头”映射台账；为每块确定观众此刻应看到的重点，优先给关键台词、包袱、反应或离场留出时间。首镜选择明确焦点，不默认远景或空镜；每块不必重复完整的起承转合。
6. 按 [shot-splitting.md](references/shot-splitting.md) 与 [timing-allocation.md](references/timing-allocation.md) 拆镜：先锁定连续声音轨的起止时间，再把动作、回忆、反应和镜头变化覆盖到声音轨上，最后才确定五个视觉镜头的边界。一个编号对应一个连续镜头；五镜是视觉结构，不是五段口播。同一句或同一口气的台词可以跨镜连续，切镜不停顿。只有来源明确要求先后或存在物理依赖的动作才串行累加，容不下时重划块边界。
7. 用 [prompt-template.md](references/prompt-template.md) 编译为可执行提示词。块头只保留当前场景稳定事实；完整入口状态和跨块剪辑安排留在后台，首镜写清必要起点。逐镜明确重要进出场的起点、路径、终点，以及台词与动作的“同时／说到某词时／说完后”关系。同一段口播跨两个以上镜头或属于节奏风险长段时，输出一行“连续口播”全局约束；普通单镜短句不增加该行。表演、光线与声音、台词及衔接按需出现，不额外倾倒后台标签。人物动作和台词使用全名或明确身份。
8. 按需读取 [spatial-continuity.md](references/spatial-continuity.md)、[emotion-microexpression-director.md](references/emotion-microexpression-director.md)、[camera-transition.md](references/camera-transition.md)；仅高密度战斗读取 [combat-previs.md](references/combat-previs.md)。出现用户提供的 `@素材` 或剧情内可见文字时，读取 [asset-binding-and-screen-text.md](references/asset-binding-and-screen-text.md)。
9. 在输出前执行 [dialogue-coverage.md](references/dialogue-coverage.md) 与 [qc-fallback.md](references/qc-fallback.md) 的 P0/P1 检查；发现典型生成风险时按 [failure-repair-playbook.md](references/failure-repair-playbook.md) 修复。可用时运行 `scripts/validate_dialogue_and_timeline.py --source <当前已锁定的分镜来源> --output <生成块> --duration 15`。

## 输出契约

- 剧本优化审阅稿不是 Seedance 提示词，单独遵循 [script-enhancement.md](references/script-enhancement.md) 的标记与审核契约；用户确认后移除标记，保留获准内容，再进入以下生成块输出契约。
- 可复制正文的块头、镜头编号和字段以 [generation-block-contract.md](references/generation-block-contract.md) 与 [prompt-template.md](references/prompt-template.md) 为唯一准则。
- 可复制正文使用中文镜头指令，不自动附加英文翻译、英文技术块或双语复述。
- 时长、画幅和质检状态仅在块标题或后台台账出现；可复制正文不重复组合时长与画幅，也不用旧式约束标签。
- 固定视觉层统一渲染质感，不把单一光线、粒子特效或无额外文字限制套到所有场景。具体光线、特效、焦点、景深与运镜逐镜写明。
- 每块末镜预留 `0.3-0.8 秒`无对白收束，保持位置或运动路径、视线、道具与情绪连续；允许人物继续走动、摄影机继续运动，不强迫站定或冻结。原稿明确要求的黑屏、死亡或转场按剧情处理。
- 五镜只规定视觉切分，不规定一句台词占一个镜头；同一说话人的连续口播可贯穿多个镜头，声音不因画面切换、回忆插入或反应镜头而重启、停顿或重复。
- 独立生成块不得用“原来的位置”“保持十年前构图”“上一句话”代替当前画面。跨块匹配留在后台，前台写清本块可见的空间、年龄、服装或环境变化；只有实际提供了参考图/视频时才引用其内容。

## 参考路由

- [preflight-diagnosis.md](references/preflight-diagnosis.md)：生成前的任务类型、叙事密度、风险等级与参考文件路由。
- [script-enhancement.md](references/script-enhancement.md)：分镜前的可选剧本增强、原稿锁定、审阅标记、版本切换与确认门禁。
- [generation-block-contract.md](references/generation-block-contract.md)：独立块头、场景/站位、入口出口和五镜头契约。
- [prompt-template.md](references/prompt-template.md)：可复制正文的逐镜字段和书写骨架。
- [composition-directing.md](references/composition-directing.md)：逐镜主体落点、层次、留白、遮挡与关系构图。
- [prompt-layering.md](references/prompt-layering.md) 与 [visual-style-system.md](references/visual-style-system.md)：稳定视觉层、场景变量光影和负面约束。
- [dialogue-capacity.md](references/dialogue-capacity.md)、[dialogue-normalization.md](references/dialogue-normalization.md)、[dialogue-coverage.md](references/dialogue-coverage.md)：对白容量、换行排版和逐字覆盖。
- [shot-splitting.md](references/shot-splitting.md)、[timing-allocation.md](references/timing-allocation.md)、[shot-task-and-physicalization.md](references/shot-task-and-physicalization.md)：镜头边界、空镜预算、时长与动作闭环。
- [camera-transition.md](references/camera-transition.md) 与 [spatial-continuity.md](references/spatial-continuity.md)：切镜动机、转场、轴线和块间承接。
- [generation-block-ledger.md](references/generation-block-ledger.md) 与 [qc-fallback.md](references/qc-fallback.md)：覆盖台账、质量门禁和修复。
- [failure-repair-playbook.md](references/failure-repair-playbook.md)：常见生成失败的症状、原因与最小修复顺序。
- [asset-list-spec.md](references/asset-list-spec.md)、[style-profiles.md](references/style-profiles.md)、[local-modification.md](references/local-modification.md)：按需读取的资产、风格与分镜生成块局部修改规则。
- [asset-binding-and-screen-text.md](references/asset-binding-and-screen-text.md)：`@素材`精确绑定、资产状态版本与剧情内文字的可见性协议。
- [intake-gate.md](references/intake-gate.md)：完整剧本配置、超大文件确认和“等待片段后生成”的前置状态机。

## 核心约束

- 当前已锁定分镜来源中的每个事件与每句台词只能覆盖一次；台词逐字、语序与说话人不变，OS、旁白、对白相互区分。优化稿只有经过用户“确认剧本”才能成为该来源。
- 空镜只可用于时间跳转、空间揭示、情绪留白或转场；`15 秒`块通常至多一个，且不超过 `1.5 秒`，不得连续出现。
- 相邻镜头不得用重复凝视、推镜、握拳、皱眉或环境动态凑时长。同一情绪可有意义地延续，不强制每镜升级、转折或新增动作。
- 每个镜头用合并后的自然语言明确主动作、持续状态或可见结果；摄影信息至少让主体关系、景别、观察角度和主运镜或固定机位可执行，焦点、景深、光线、环境和声音仅在承担叙事功能或发生变化时写。无变化或与块头相同的信息不重复。“后跟拍”“缓慢推进”“电影感”等词不能单独成立。
- 提示词按“原文与说话人 → 连续性 → 可见表演与镜头执行 → 光线与声音 → 风格装饰”的顺序保护信息；需要压缩时先删重复和装饰性内容，不得牺牲剧情、台词、时长或连续性。
- 自动检查只验证可解析的文字和结构；出现未归属台词、混排朗读标注或覆盖不完整警告时，必须补做人工台账核对，不能将零错误视为全剧情或实际视频效果已通过。
- 输出前必须清零可自动判断的口播节奏错误：声明的连续口播不得慢于或快于所选语速档，同一连续话轮跨镜时不得遗漏“连续口播”约束。情绪慢速只能由原文的哽咽、迟疑、庄重宣告等明确依据触发，不能用于填满 15 秒。
