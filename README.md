# Seedance Shot Director

版本：`V1.03`

将完整剧本、短分段文案或对白稿转换为可直接投喂 Seedance 2.0 / 2.5 的中文国风短剧分镜提示词。

## 核心能力

- 目标时长在对话中选择为 15 秒或 30 秒，并在后续同一对话中保持默认。
- 一段少于 1200 字的分段文案可按事件容量拆分为 N 个独立生成块。
- 每个 15 秒生成块严格拆分为 5 个镜头；每个 30 秒生成块根据该块剧情密度动态决定镜头数量，通常为 8-12 个镜头。
- 15 秒和 30 秒的时长均按剧情节拍、对白长度、动作复杂度和情绪张力动态分配，不使用固定秒数组合。
- 支持 3D 国风动漫、暗黑武侠、超写实仙侠、东方奇幻、国漫江湖、悬疑和权谋等视觉方向。
- 支持情绪微表情、空间轴线、角色连续性和局部镜头修改。
- 采用三层提示词结构、镜头三任务法则、动作/情绪物理化和有动机的镜头衔接。
- 有对白时执行自然语速与反应容量预检；为每个生成块维护来源节拍、入口/出口状态、资产和质检台账。
- 高密度战斗才启用 R1/R2/R3 战斗专项规则，普通文戏不会套用战斗快切和 Hit-Stop 约束。
- 默认画幅为 `16:9`。
- 允许补充画面、动作、运镜和表演细节，但不新增关键剧情、反转、人物关系或结局。
- 每个 15 秒或 30 秒生成块均可独立复制使用。

## 输入识别

用户明确说明输入类型时，以用户说明为准。未明确说明时：

- `1200 字以内（含 1200 字）`默认视为短分段。
- 超过 `1200 字`默认视为完整剧本。
- 用户明确指定的局部镜头修改优先级最高，不按字数重新判断。

## 目录结构

```text
SKILL.md
agents/openai.yaml
references/
  asset-list-spec.md
  emotion-microexpression-director.md
  prompt-layering.md
  dialogue-capacity.md
  shot-task-and-physicalization.md
  camera-transition.md
  generation-block-ledger.md
  combat-previs.md
  duration-mode.md
  generation-block-contract.md
  generation-block-splitting.md
  local-modification.md
  prompt-template.md
  qc-fallback.md
  shot-splitting.md
  spatial-continuity.md
  style-profiles.md
  timing-allocation.md
```

## 安装

将整个目录放入 Codex 的 skills 目录：

```text
~/.codex/skills/seedance-shot-director
```

安装后可通过 `$seedance-shot-director` 调用，也可以直接提交剧本或分段文案让系统自动识别。处理分段文案时，Skill 会先使用当前对话选定的 15 秒或 30 秒模式，再按事件容量拆成 N 个独立生成块。

## 版本说明

当前版本为 `V1.03`，重点包含：

- 短分段按事件容量拆分为 N 个独立生成块。
- 15/30 秒目标时长在对话内选择并保持默认。
- 每个生成块重复固定风格、固定规则和独立状态锚点。

- 15 秒严格五镜头规则。
- 30 秒动态镜头拆分和动态时长分配。
- 情绪微表情导演层。
- 空间轴线与跨镜头连续性。
- 指定镜头的局部修改流程。
- 质量检查与失败回退机制。
- 三层提示词解耦、镜头任务与物理化、对白容量检查、镜头衔接动机和生成块工业台账。
- 逐镜构图字段与构图导演规则，明确主体落点、前中后景、遮挡、引导线、留白和多人关系边界。
- 连续换行台词的排版规范化、逐字对白覆盖台账和说话人匹配校验。
- `validate_dialogue_and_timeline.py` 可执行检查台词覆盖、重复台词、时间轴、五镜头、构图字段、模糊指代、空镜预算和块尾无对白缓冲。
