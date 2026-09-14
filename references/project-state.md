# 项目状态与恢复

长剧本、多片段或多轮修订必须在当前项目/工作目录保存 `seedance_state/`；短任务也保存V0，避免“后台永久保留”只有口头承诺。不用技能安装目录承载用户材料。

状态包含项目ID、配置、片段ID、不可覆盖的V0/V0.x、审阅版R1…、确认版C1…、当前基线/审阅/分镜来源指针与台账。每份文本记录SHA-256，恢复前验证摘要；被外部改动的文件不可静默当作原稿。文件原子写入，版本只新增；同内容重试不产生空修订。

使用 `scripts/project_state.py`，以下路径均替换为当前项目实际路径，版本正文必须来自用户材料或获准内容：

```text
python -B scripts/project_state.py --project <项目目录> init --id story
python -B scripts/project_state.py --project <项目目录> ingest --segment seg001 --input <原文.txt>
python -B scripts/project_state.py --project <项目目录> revise --segment seg001 --input <仅获准修订的原文.txt> --reason <用户确认依据>
python -B scripts/project_state.py --project <项目目录> review --segment seg001 --input <完整标记审阅稿.txt>
python -B scripts/project_state.py --project <项目目录> confirm --segment seg001 --input <干净确认稿.txt>
python -B scripts/project_state.py --project <项目目录> use-original --segment seg001
python -B scripts/project_state.py --project <项目目录> source --segment seg001
```

`source` 返回已验证的实际文件路径、版本与摘要，供对白校验器 --source 使用。没选原版、没确认增强或来源变化待重审时拒绝输出活动来源。

`use-original --initial` 明确回到最初V0，普通命令采用当前基线。`review --initial` 仅在用户明确要求从最初原版重新增强时使用；确认版记录实际使用V0，但不覆盖当前V0.x基线。任何审阅开始后基线再次变化，确认会阻断并要求重新审阅。普通重新增强读取当前基线，不能以旧R稿叠加；局部修改可基于当前R稿另存下一版。

确认时若包含已经明确接受的文字修订，可同时提供 `--baseline-input <只含获准来源修订的原文.txt> --reason <依据>`，原版修订和干净确认稿在一次状态提交中登记。动作增强不混入V0.x。独立编剧建议只有明确接受后才进入来源修订，不能因确认表演稿而自动接受。

## 局部审阅替换

首次审阅用 `review` 保存全文。局部修改先用 `review-context --segment seg001` 获取当前审阅文件、版本和摘要，再用 `review-patch --segment seg001 --input <替换.json>`；两者均带全局参数 `--project <项目目录>`。JSON包含当前 `review_version`、`review_sha256`、`edits: [{"old": "原句及必要唯一上下文", "new": "修改后对应文本"}]`。`old`须在当前稿中唯一，多个替换基于同一底稿且不得重叠；工具保存完整R新版本并返回路径/摘要，保留未改字符与换行。重复原句须扩大上下文，不猜测位置。原文没变不创建空版本。

前台展示变化及最新完整文件，不把差异清单当作完整底稿。确认仍由用户完成，工具不会因保存补丁自动确认增强或接受旁列编剧建议。

## 全剧索引与编译产物

完整剧本可作为独立片段ID保存原版，不必先锁定为分镜来源。`story-index --segment screenplay --input <索引.json>` 保存按 [long-script-index.md](long-script-index.md) 人工理解得到的全局索引，检查其基线版本及摘要。来源修订后 `index_status=stale`，增量更新受影响索引并重新登记；工具不自动抽取或证明全剧情理解。

统一规划按 [unified-plan.md](unified-plan.md) 编译。候选提示词、台账写入 `seedance_state/builds/<片段ID>/<内容摘要>/`；文件不变则不覆盖。硬检查结果与候选摘要绑定；`finalize` 核对来源、配置、工具和候选文件均未变化，再记录语义复核。没有语义通过不得把硬检查零错误当作已完成。手动修改提示词文件后应回到规划修改并重新编译。

## 制作配置

`config --input <配置.json>` 合并本任务设置；默认轻度、执行简版、无配乐、独立收束。记录模型/入口/时长范围、画幅、风格、增强偏好、声线与素材绑定。一次选择不自动推广到全局；用户明确“后续都如此”才设置持续偏好。具体键见模型与制作配置文档。

## 台账

`ledger --segment seg001 --input <台账.json>` 须包含 `source_version` 与 `source_sha256`，与当前来源一致才保存。台账需要的信息直接包含在统一规划及检查结果中：来源节拍ID、事实依据、声音话轮、镜头片段映射、入口/出口、实际时长和必要的资产/知情状态；不另写一套冗余表格。

来源或配置变更将台账标为stale，不能沿用“通过”；可复用未受影响映射，只重查实际受影响块及相邻连续性，然后重新登记。工具只保存/核对版本摘要，不自动判断增强是否合法或影片效果；确认授权、文本清理和语义覆盖由技能核对。
