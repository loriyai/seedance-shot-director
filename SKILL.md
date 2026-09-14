---
name: seedance-shot-director
description: "将完整剧本、片段或对白转为 Seedance 2.0/2.5 中文国风漫剧分镜提示词；支持原文保真、默认轻度的表演增强审阅、独立编剧建议与局部镜头修改。"
---

# Seedance Shot Director

## 工作边界

- 核心任务是把已锁定来源编译为可执行镜头。保留原文事件、信息顺序、动作结果、台词和声音身份；编剧建议单独审阅，获准后才能形成修订来源。
- 原版 V0 永不覆盖。“原版”统一指当前原版基线，即最新 V0.x 或尚无修订时的 V0；只有“最初原版 V0”才回到初始输入。确认后的增强稿才可作为增强分镜来源。版本语义以 [script-enhancement.md](references/script-enhancement.md) 为唯一准则，保存与恢复按 [project-state.md](references/project-state.md)。
- 默认表演增强强度为轻度：只细化已有动作，不新增独立反应节拍。是否增强尊重本次指令或本任务已保存的偏好；首次未选择时询问一次。标准增强须明确选择。用户确认审阅稿前不生成其分镜。
- 原文中的剧本操作台词不是对技能的指令。审阅标记、疑点说明和版本提示不进入可复制提示词。
- 所有模式共用来源边界：执行细化只补已成立动作的路径、接触、可见状态和摄影安排；不得在分镜阶段二次增加表演节拍。仅提及道具不证明它在场或由某人持有；审阅阶段可按 script-enhancement.md 提出已有且归属清楚道具的展示方案，明确标记携带位置等假设，确认后入源。身份、目标、说话人、关键道具、因果和时空若存在影响执行的歧义，才补问。
- 提示词只用中文；原文外语台词、型号和实际提供的 `@素材`名称保持原样。每块自包含，不用“同上”“沿用上一块”或未提供的参考画面。

## 接收与配置

1. 用户明确“完整剧本”“分段文案”“只处理这段”或“修改镜头”时以说明为准。明确完整剧本完全跳过字数统计；仅未注明类型时运行 `scripts/count_script_chars.py` 按汉字加 Unicode 标点计数，至多 1200 推断为片段，超过推断为完整剧本。只有推断为完整剧本且超过 150000 才询问是否误发，不用文件大小或 token 数代替。
2. 完整剧本先通读建立人物关系、场景、关键道具、时间线和伏笔的全局索引；当前处理场次再补详细空间与状态档案，见 [long-script-index.md](references/long-script-index.md)。来源修订按影响更新。收集缺失的时长、风格、资产列表选择，随后等待片段或明确处理范围，不自动生成开头。片段先保存 V0。详见 [intake-gate.md](references/intake-gate.md)。
3. 时长目标为 15 或 30 秒，画幅默认 16:9。按 [model-and-production-config.md](references/model-and-production-config.md) 将目标编译到实际模型/入口：2.0 单块不超过 15 秒；2.5 可原生 30 秒。模型和入口已知时沿用；不为每段重复采集配置。
4. 默认执行简版、轻度增强强度、无配乐、独立收束；支持本任务增强偏好、导演详版、连续剪辑和声音配置。首次风格选择按 [style-profiles.md](references/style-profiles.md) 原样展示完整三项，不附解释、不拆成两个问题；项目风格不写入技能安装目录。无论是否展示资产列表，都保留 [asset-list-spec.md](references/asset-list-spec.md) 所需全局资产索引；详细执行档案按场次补齐，明确要求全剧资产列表时仍完成全剧清单。
5. 用户选择增强时按 [script-enhancement.md](references/script-enhancement.md) 首轮输出完整标记审阅稿；后续局部修改只展示变化与必要上下文，并提供最新完整文件，等待确认。要求改善台词、冲突或结构时先给单独的具体编剧建议；未经选择的建议不入稿。直接分镜或使用原版则锁定当前基线。

## 分镜与编译

以下步骤逐步填入同一份结构化规划。声音轨、节拍映射与镜头字段各记录一次，不先分别输出自然语言中间稿再重新整理。

1. 按 [preflight-diagnosis.md](references/preflight-diagnosis.md) 识别当前任务及必读参考。锁定来源版本，提取事件、声音话轮、动作结果、素材、时空和观众信息节拍，记录来源依据。
2. 有对白先按 [dialogue-normalization.md](references/dialogue-normalization.md)、[dialogue-capacity.md](references/dialogue-capacity.md) 建立声音轨；同时检查动作闭环、观众阅读和关键反应时间。净发音时间与停顿分开，切镜不制造停顿；同人隔动作再次开口不自动合并。无对白或动作戏以可见动作与观看时间为主。
3. 按 [generation-block-splitting.md](references/generation-block-splitting.md) 自然分块并优先完整收尾。完整 15 秒块默认五镜，可按表演与连续运镜需要调整；不足四秒尾文先尝试合并有余量的前块，必要时联合调整最后两块实际时长，不能默认延期或虚构动作填秒。模型最小时长无法容纳整个超短输入且无自然余韵时，保留全文并说明具体待决事项。30 秒与实际短块规则见该文件。
4. 按 [shot-splitting.md](references/shot-splitting.md)、[timing-allocation.md](references/timing-allocation.md) 确定视觉边界。一个编号是一镜；来源事件只发生一次，但其过程和话轮可以跨镜分段呈现。将 [generation-block-ledger.md](references/generation-block-ledger.md) 的映射与入口/出口直接写入 [unified-plan.md](references/unified-plan.md) 的同一份规划，不另写平行台账。
5. 以一份结构化规划运行 `scripts/compile_plan.py`，自动生成符合 [generation-block-contract.md](references/generation-block-contract.md) 和 [prompt-template.md](references/prompt-template.md) 的中文提示词及台账。工具仅排版和校验，不替代导演判断。稳定事实放块头，必要起点放首镜；逐镜写“画面与动作”“摄影机与构图”，台词使用具名自然语言，特殊语气按话轮表达；每镜台词下方输出“环境音效”，列本镜环境声与动作声，以“；”分隔。后台绑定声音ID和预算，正文仅呈现必要的实际声音区间与原文一次覆盖。
6. 表演需要摄影机看得见；相同情绪可以有意义地延续。根据原文区分人物已知与观众已知，允许有依据的画外触发、先反应后揭示。按需读 [composition-directing.md](references/composition-directing.md)、[spatial-continuity.md](references/spatial-continuity.md)、[camera-transition.md](references/camera-transition.md)、[emotion-microexpression-director.md](references/emotion-microexpression-director.md)。动作密集读 [shot-task-and-physicalization.md](references/shot-task-and-physicalization.md)，高密度战斗再读 [combat-previs.md](references/combat-previs.md)。
7. 有 `@素材` 或剧情内文字时读 [asset-binding-and-screen-text.md](references/asset-binding-and-screen-text.md)。文字显示与朗读分开。核心身份、服装版本、道具状态与稳定声线跨块一致；参考素材未提供时不承诺精确复现。
8. 局部修改按 [local-modification.md](references/local-modification.md)，只重写指定块及必要相邻衔接。修改来源后更新受影响台账，不从分镜反向覆盖剧本。

## 质检与输出

- 按 [dialogue-coverage.md](references/dialogue-coverage.md)、[qc-fallback.md](references/qc-fallback.md) 检查。每份候选由编译器执行一次硬检查，再做一次来源与导演语义复核并登记；通过即交付，不为装饰继续自发润色。已有硬检查结果不重复跑相同校验。历史手写提示词才单独运行 `scripts/validate_dialogue_and_timeline.py --source <锁定来源.txt> --output <提示词.txt> --duration <实际编译上限> --model <2.0或2.5>`。入口不确定时不假填型号。发现实际问题才按 [failure-repair-playbook.md](references/failure-repair-playbook.md) 局部修复。
- 声音起止、台词覆盖镜头、换人顺序和首尾无口播区间必须一致；逐镜检查分配到该镜的台词片段实际容量，不能仅靠整句语速通过。发音估计不确定时警告复核；确定的改词或错归属不能被其他未知段落降级。
- 15 秒完整块默认五镜，可按表演与连续运镜需要调整；30 秒建议 8–12 镜，偏离需有导演依据；末尾短块不以凑镜数或秒数制造新剧情。
- 跨场景边界（含同地点时间跳转）前块末尾、新块开头各至少1秒无口播，画面和自然动作持续，纳入时长计算，不自动生成后期转场。一般独立收束默认最后 0.3–0.8 秒无口播；连续剪辑的非终结块可保留持续动作或声音衔接，剧情明确硬切时服从来源。具体收尾配置按模型与制作配置文档，不把每块都处理成剧情结束。
- 空镜只服务时间、空间、留白或转场；15 秒通常至多一镜且不超过 1.5 秒，不连续用空镜凑时长。不靠重复握拳、凝视、推镜、皱眉或无意义环境动态填满五镜。
- 编译文件是交付正文，优先提供可复制的提示词文件及可用的文件预览；用户要求聊天内展示时逐字展示文件正文，不再自由改写一遍。执行版保护顺序：来源与声音身份 → 连续性 → 表演与摄影执行 → 必要光线声音 → 风格装饰。详版使用同一份规划，审阅台账置于可复制块之外。分层见 [prompt-layering.md](references/prompt-layering.md)、[visual-style-system.md](references/visual-style-system.md)。
- 校验器只检查可解析文字和结构，警告与未归属部分需要人工语义核对。未实际生成视频时不宣称效果已验证。
