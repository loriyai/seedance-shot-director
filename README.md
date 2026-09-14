# Seedance Shot Director

版本：V1.13

将剧本与片段编译为 Seedance 2.0/2.5 中文国风分镜，支持默认轻度的表演增强审阅、独立编剧建议、项目状态恢复与局部修改。

本版保持完整15秒严格五镜，优先完整收尾，必要时最后两块以实际时长联合重排。2.0的30秒目标编译为不超过15秒的块，2.5可使用原生30秒；实际入口限制另行记录。

“原版”统一指最新修订基线，V0永不覆盖。轻度只细化原动作；标准增强须明确选择。台词/剧情改写建议单独列出，获准形成来源修订后才进入分镜。

执行简版默认；可选择导演详版、本任务后续增强偏好、自定义风格、配乐、稳定声线与连续剪辑。用户项目状态存当前项目，不写入技能安装目录。

V1.13 用一份结构化规划生成提示词和台账，编译内置一次硬检查，随后一次语义复核；通过即交付，有实际问题才局部修复。审阅稿局部修改默认只展示变化并提供完整文件，原版与历史版本仍完整保存。长剧本首次建立全局索引，处理到对应场次再补详细执行档案。

主要入口为 SKILL.md。模型配置、项目状态、声音格式与30秒例子分别见 references/model-and-production-config.md、references/project-state.md、references/prompt-template.md、references/prompt-examples.md。

验证：

```text
python -B -X utf8 -m unittest discover -s scripts -p "test_*.py" -v
python -B -X utf8 scripts/validate_dialogue_and_timeline.py --source source.txt --output prompt.txt --duration 15 --model 2.0
python -B -X utf8 scripts/project_state.py --help
python -B -X utf8 scripts/compile_plan.py --help
```

按入口可设置 --min-duration 和 --duration-step；默认4秒为工作流下限，并非所有入口的官方最小值。--allow-deferred 仅用于用户明确同意暂存未完稿的旧格式兼容，不是默认短尾策略。

校验器核对可解析结构、声音身份与时间关系，保留需要人工复核的警告。测试通过不等于实际视频效果通过。
