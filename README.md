# Seedance Shot Director

版本：`v1.01`

将完整剧本、短分段文案或对白稿转换为可直接投喂 Seedance 2.0 / 2.5 的中文国风短剧分镜提示词。

## 核心能力

- 默认输出 15 秒生成块，严格拆分为 5 个镜头。
- 30 秒生成块根据剧情密度动态决定镜头数量和每镜时长，通常为 8-12 个镜头。
- 15 秒和 30 秒的时长均按剧情节拍、对白长度、动作复杂度和情绪张力动态分配，不使用固定秒数组合。
- 支持 3D 国风动漫、暗黑武侠、超写实仙侠、东方奇幻、国漫江湖、悬疑和权谋等视觉方向。
- 支持情绪微表情、空间轴线、角色连续性和局部镜头修改。
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

安装后可通过 `$seedance-shot-director` 调用，也可以直接提交剧本或分段文案让系统自动识别。

## 版本说明

当前版本为 `v1.01`，重点包含：

- 15 秒严格五镜头规则。
- 30 秒动态镜头拆分和动态时长分配。
- 情绪微表情导演层。
- 空间轴线与跨镜头连续性。
- 指定镜头的局部修改流程。
- 质量检查与失败回退机制。
