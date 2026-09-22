# Seedance Shot Director

版本：V1.27

V1.27 把"交付物里的事实"从手写改成机器推导并加三道事实门禁：`场景：` 由根级 `scenes`（`{scene_id: 场景名}`）查表得出，同一 `scene_id` 必须同名、块级场景名与查表冲突为硬错误、不同 `scene_id` 共用同名给警告；`人物：` 只列本块真实入镜的角色，未标 `offscreen` 的角色必须出现在某镜动作里，否则硬错误，镜中出现本场 `cast` 成员却没列也给警告；`scene_design` 只写持久背景层，`blocking` 逐块写，设计段提到本块未登场角色给警告。`compile` 另产 `facts.txt`、`check-block` 内联 `facts` 自检表（场景名、可见人物、画外、发声角色、无口播头/中/尾、语气覆盖、音效来源），交付前红项清零；`SKILL.md` 写明进入分镜后连续推进到整段 `finalize` 才算交付，单轮未完必须标已完成/剩余块号。新增 `scripts/test_v127_fact_gates.py` 回归。

V1.26 补三类规则漏洞并加对应机械检查：一是"凑时长"只在尾部被检查，块内无口播填空没人管——`compile_plan.py` 现在按 `max(2.0, 0.15×块时长)` 检查头部、中间与尾部无口播区间（扣除跨时空必需的 1 秒留白），并要求台词与可并行动作并行，`core-invariants.md`、`generation-block-splitting.md`、`timing-allocation.md` 同步写明"15 秒块 5–7 镜是上限框架，不是时长目标"。二是 `tone` 是可选字段、缺语气没人报——情绪信号词命中而语气留空时 `compile_plan.py` 与 `plan_voices.py` 都报"疑似缺少语气"，`check-block` 增列 `tone_coverage`，`unified-plan.md` 起草顺序加入"逐句扫语气"。三是跨块片段不能用 `span` 拆分，超过单镜容量会在起草中期才暴露——`plan_voices.py --plan` 按语速档上限在骨架阶段直接报错。交付节奏方面，`SKILL.md` 明确冒烟是内部闸门而非交付边界（通过后写完本批再交付），`intake-gate.md` 增加超长分段前置体量提示与按批推进。新增 `scripts/test_v126_rule_hardening.py` 回归这些检查。

历史版本变更（V1.20–V1.25 的逐版说明）已从本文件移除，需要时用 `git log --oneline` 与本仓库的历史提交查看。

将剧本与片段编译为 Seedance 2.0/2.5 中文国风分镜，支持默认轻度的剧本审阅（语法错漏与台词换行规范化）、独立编剧建议、项目状态恢复与局部修改。

本版完整15秒默认五镜、允许五到七镜（仅群体入场、对白密集、情绪反转或顺序明确的多动作链可增加），任何单镜最长5秒；因下一时空边界无法合并的内部短块可按4–14.9秒生成，镜数至少为`ceil(时长/5)`且最多5镜；结尾仍可联合重排最后两块。2.0的30秒目标编译为不超过15秒的块，2.5可使用原生30秒；实际入口限制另行记录。

“原版”统一指最新修订基线，V0永不覆盖。轻度审阅只做语法错漏检查与台词换行规范化，不改写台词、不做表演细化。台词/剧情改写建议单独列出，获准形成来源修订后才进入分镜。

执行简版默认；收尾采用自动模式：同一连续时空的非最终块连续剪辑，真正末块独立收束，时空跳转两侧仍各留至少1秒无口播画面。可选择导演详版、自定义风格、配乐、稳定声线及强制独立/连续模式。审阅档位不作为保存偏好：每次发送分段文案都重新询问“轻度剧本审阅 / 直接按原版分镜”。用户项目状态存当前项目，不写入技能安装目录。

接收阶段只问三项：目标时长、风格、是否输出资产列表。模型由时长决定，15秒用Seedance 2.0、30秒用Seedance 2.5，不单独询问；画幅、配乐、收尾与简版沿用默认。工作范围只限于用户给出的文件：不列目录、不读同目录其他文件；通读按每块2000–3000行推进，四到五次读取内完成，引用写范围而不逐条 grep 行号。

完整剧本首次仍通读全剧，但只建立 `lite-v1` 轻量连续性索引，不为未处理场次预写剧情长摘要、动作台账或空间档案；具体分镜采用“当前片段＋必要相邻场＋相关索引”，只在身份揭示、伏笔回收、关键道具链或冲突 P0 命中时定点回查远距原文。索引设上限：人物≤15、关系≤8、场景≤10、道具≤8、时间线≤8、伏笔≤6，超出先合并或降级。分片索引可由 `scripts/merge_story_index.py` 做严格机械合并，一次跨段语义审计后再登记。

主要入口为 SKILL.md。模型配置、项目状态、声音格式与30秒例子分别见 references/model-and-production-config.md、references/project-state.md、references/prompt-template.md、references/prompt-template.md。

验证：

```text
python -B -X utf8 -m unittest discover -s scripts -p "test_*.py" -v
python -B -X utf8 scripts/validate_dialogue_and_timeline.py --source source.txt --output prompt.txt --duration 15 --model 2.0
python -B -X utf8 scripts/prepare_source.py --source source.txt --output source-preflight.json
python -B -X utf8 scripts/plan_voices.py --source source.txt --text "台词原文" --profile 短剧常速 --start 0.5
python -B -X utf8 scripts/plan_voices.py --source source.txt --plan plan.json
python -B -X utf8 scripts/check_source_coverage.py --source source.txt --draft review.txt --narration
python -B -X utf8 scripts/derive_review.py --source source.txt --edits edits.json --output R1.md
python -B -X utf8 scripts/strip_markers.py --review R1.txt --output clean.txt
python -B -X utf8 scripts/project_state.py --help
python -B -X utf8 scripts/compile_plan.py --help
```

校验器核对可解析结构、声音身份与时间关系，保留需要人工复核的警告。测试通过不等于实际视频效果通过。

按入口可设置 --min-duration 和 --duration-step；默认4秒为工作流下限，并非所有入口的官方最小值。--allow-deferred 仅用于用户明确同意暂存未完稿的旧格式兼容，不是默认短尾策略。
