# 一份规划生成提示词与台账

分镜生成时读取本文件。模型只决定一次来源节拍、声音安排、动作与摄影；程序负责重复字段、台词片段拼接、时间字段排版、台账和硬检查。不要先写一份全字段文字台账，再手写一份同内容提示词。

## 工作顺序

1. 来源已锁定后运行：

```text
python -B scripts/compile_plan.py context --project <项目目录> --segment seg001
```

返回实际来源文件、版本、摘要、项目配置及 `config_sha256`。读取锁定来源；用返回值填写规划，不假填版本或模型。长剧本另按 [long-script-index.md](long-script-index.md) 回查当前场次所需全局事实。

2. 只写一次 `plan.json`。完整可读例子见 [plan-example.json](plan-example.json)，对应原文见 [plan-example-source.txt](plan-example-source.txt)。例子中人物和制作设定仅服务该示例，实际任务用当前来源和配置替换；示例摘要不可沿用到其他文本。

3. 编译并硬检查：

```text
python -B scripts/compile_plan.py compile --project <项目目录> --segment seg001 --plan <plan.json>
```

返回可直接交付的 `prompt.txt`、包含原规划的 `ledger.json`、诊断与候选摘要。候选尚未语义复核时不会标为通过。编译已运行一次现有对白/结构校验器，不重复调用它检查同一稿。

4. 对候选做一次 [qc-fallback.md](qc-fallback.md) 要求的语义复核。写一份短复核记录：

```json
{
  "plan_sha256": "本次编译返回的实际规划摘要",
  "prompt_sha256": "本次编译返回的实际正文摘要",
  "passed": true,
  "note": "记录实际完成的来源、连续性与导演核对，以及必要的警告处理依据。",
  "warnings_reviewed": []
}
```

`warnings_reviewed` 填本次 `diagnostics` 中已核对警告的零基索引；没有警告才留空。有语义问题则 `passed=false`，`note` 写具体问题，修对应规划后重新编译；不能通过改复核标志掩盖未修问题。复核包括未解析台词和全段事件，不能仅核对警告列表。

```text
python -B scripts/compile_plan.py finalize --project <项目目录> --segment seg001 --build <编译返回的build> --review <复核.json>
```

这一步只核对候选、工具、来源和配置摘要并登记语义结果，不再运行一次完整校验。全部通过即交付，不再自发润色。提示词文件可直接复制；界面支持时打开文件预览。用户要求聊天内正文时逐字展示文件内容，不重新创作。导演详版的说明从同一规划提取，放在可复制正文之外。

## 规划字段

根对象必须有 `schema_version=1`、`source_version`、`source_sha256`、`config_sha256`、`defaults`、`beats`、`blocks`。未知字段会报错，避免把应该执行的内容静默漏掉。

- `defaults`：`style`、`characters`、`scene`、`atmosphere`、`sound` 五个非空中文单行字段；实际提供素材时加 `assets`。它们是本次规划共享的稳定事实，脚本在每块完整展开；某块有不同人物/场景/状态时用 `header` 覆盖对应字段，不让全局默认误带入新场景。声音方案须与配置一致。
- `beats`：每项含唯一 `id`、原文中可定位的精确 `evidence` 摘句；可加 `timing: "parallel" / "serial"`，串行动作必须有 `basis` 记录依据。摘句和映射不能自动证明剧情覆盖，遗漏和重演仍须语义复核。无关的时序字段不强填。
- `blocks`：按顺序编号；每项含 `duration`、`entry`、`exit`、`voices`、`shots`。`entry`/`exit` 是当前块状态，真正需要执行的起点必须同时写入首镜动作；它们不自动生成新动作。可选 `header`、`ending`、`silent_tail`、`notes`。
- `ending`：`独立收束` / `连续剪辑` / `剧情硬切`。省略时按制作配置决定，连续交付的非最终块连续剪辑，最终块独立收束。独立收束的 `silent_tail` 默认0.5秒，范围0.3–0.8；另外两种收尾不填此字段。明确的剧情硬切仍优先。
- `voices`：无口播时空列表。每个话轮只录入一次 `id`、`speaker`、`kind`（对白/OS/旁白）、逐字 `text`、`start`、`end`、`pause`、`profile`；`pause=null` 表示待核，`profile` 使用现有语速档。原文明确并发才加 `overlap` 依据。同人隔动作再次开口另建ID；不能为了少填字段合并话轮。
- `shots`：每镜含 `start`、`end`、所覆盖节拍ID列表 `beats`、`action`、`camera`。可选 `speech`、`performance`、`sound`、`screen_text`、`transition`、`notes`。执行描述保持中文单行，镜头ID由程序编号；时轴与五镜规则由原校验器检查。
- `speech`：`[{"voice": "V1"}]` 表示整句只在该镜出现；跨镜时用 `{"voice":"V1","span":[0,4]}`。范围是话轮 `text` 的零基Unicode字符位置，前含后不含，包含原标点；用程序定位切分点，不靠目测计算。各片段按原序完整覆盖，不重复录入台词正文。编译器拒绝遗漏、重叠、倒序和越界。
- `notes`：仅存实际需要的来源依据、观众/人物知情差异、可见性或导演复核说明，可用紧凑对象；不默认填一套空字段。必须执行的动作、声音、画面文字不能只写在 `notes` 中。

人物、场景、关键道具与动作真实性不是排版工具能判断的；未知事实继续按来源门禁处理。计划字段中的数字与英文键只是后台制作格式，生成给 Seedance 的指令仍是中文。

## 修改与恢复

修改镜头时更新同一规划的指定字段与必要相邻关系，复用不变字段。保存新候选，正文与台账由脚本共同再生；只展示受影响完整生成块或其文件，不重复交付无关块。不要直接改编译出来的提示词后沿用旧台账或旧质检结论。

源稿、配置、工具版本或候选文件变化时旧复核失效。文件路径和摘要只用于恢复与防止误用，不代表所有语义正确。历史手写提示词可继续按原模板校验；若只做小修改，不为接入新工具强制重建无关历史内容。
