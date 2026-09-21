import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parent.parent
REFERENCES = ROOT / 'references'


class V119DocumentationContractTests(unittest.TestCase):
    def read(self, relative):
        return (ROOT / relative).read_text(encoding='utf-8')

    def test_fast_path_and_hard_rules_remain_explicit(self):
        skill = self.read('SKILL.md')
        core = self.read('references/core-invariants.md')
        enhancement = self.read('references/script-enhancement.md')
        self.assertIn('Seedance Shot Director V1.23', skill)
        self.assertIn('轻度剧本审阅', skill)
        self.assertIn('轻度剧本审阅', self.read('references/intake-gate.md'))
        self.assertIn('多字、少字、错别字', enhancement)
        self.assertIn('台词换行规范化', enhancement)
        self.assertNotIn('细节增强', enhancement)
        self.assertNotIn('🟦', enhancement)
        self.assertNotIn('🟩', enhancement)
        self.assertIn('MARKER = re.compile(r"[🟨🟥]', self.read('scripts/strip_markers.py'))
        self.assertIn('scripts/plan_voices.py', skill)
        self.assertIn('scripts/prepare_source.py', skill)
        self.assertIn('schema_version=5', skill)
        self.assertIn('scripts/check_source_coverage.py', skill)
        self.assertIn('scripts/strip_markers.py', skill)
        self.assertIn('覆盖差分是硬闸门', skill)
        self.assertIn('编译管线冒烟', skill)
        self.assertIn('实际时长 15 秒的生成块默认 5 镜，允许 5–7 镜', core)
        self.assertIn('单镜均不得超过 5 秒', core)
        self.assertIn('同场景跨时间', core)
        self.assertIn('最后一镜固定输出一次', core)
        self.assertIn('台词行只允许三种形式', core)
        self.assertIn('不得把说话方式写进语气栏', core)
        self.assertIn('一次顺序语义扫描', enhancement)
        self.assertIn('unresolved_utterances', enhancement)
        self.assertIn('疑似多余空格', enhancement)
        self.assertIn('不新增独立反应节拍', enhancement)
        self.assertIn('立即继续分镜', enhancement)
        self.assertIn('check_source_coverage.py', enhancement)
        self.assertIn('strip_markers.py', enhancement)

    def test_field_contract_is_pinned_for_drafting(self):
        contract = self.read('references/compiler-field-contract.md')
        unified = self.read('references/unified-plan.md')
        self.assertIn('defaults` 必须含 `style`、`scene`、`atmosphere`', contract)
        self.assertIn('V5 不接受镜头级 `action_basis`', contract)
        self.assertIn('完整消费', contract)
        self.assertIn('第一块冒烟测试', contract)
        self.assertIn('compiler-field-contract.md', unified)

    def test_v5_review_is_semantic_not_mechanical(self):
        unified = self.read('references/unified-plan.md')
        qc = self.read('references/qc-fallback.md')
        for name in ('source_coverage', 'action_causality', 'spatial_continuity',
                     'visual_readability', 'sound_source_semantics'):
            self.assertIn(name, unified)
            self.assertIn(name, qc)
        self.assertIn('warning_groups', unified)
        self.assertNotIn('"character_headers"', unified)

    def test_long_script_first_pass_is_light_and_scope_bound(self):
        skill = self.read('SKILL.md')
        intake = self.read('references/intake-gate.md')
        index = self.read('references/long-script-index.md')
        assets = self.read('references/asset-list-spec.md')
        core = self.read('references/core-invariants.md')
        preflight = self.read('references/preflight-diagnosis.md')
        self.assertIn('完整剧本先做一次轻量通读', skill)
        self.assertIn('不写未处理场次的长摘要或动作台账', intake)
        self.assertIn('精读当前片段、前后相邻场和相关索引条目', intake)
        self.assertIn('只有用户明确要求完整资产清单', assets)
        self.assertIn('不阻断当前片段', core)
        self.assertIn('无关未来 P0 只写入全局索引', preflight)
        self.assertIn('"index_schema": "lite-v1"', index)
        self.assertIn('禁止写 `summary`', index)
        self.assertIn('scripts/merge_story_index.py', index)
        self.assertIn('review_status=pending', index)
        self.assertIn('payoff_ref`、`clue_hint', index)
        self.assertIn('最终 `reviewed` 索引不得残留仅回收候选', index)
        self.assertIn('当前片段执行档案', index)

    def test_compact_example_and_relative_links_resolve(self):
        example = json.loads((REFERENCES / 'plan-example-v5.json').read_text(encoding='utf-8'))
        self.assertEqual(example['schema_version'], 5)
        for document in ROOT.rglob('*.md'):
            text = document.read_text(encoding='utf-8')
            for match in re.finditer(r'\[[^\]]*\]\(([^)]+)\)', text):
                target = match.group(1).split('#', 1)[0]
                if not target or re.match(r'https?://', target) or '<' in target:
                    continue
                self.assertTrue((document.parent / target).exists(), f'{document}: {target}')


if __name__ == '__main__':
    unittest.main()
