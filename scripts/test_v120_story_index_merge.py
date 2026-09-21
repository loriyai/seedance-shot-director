import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid

from merge_story_index import digest, merge_parts, validate_final_index
from project_state import ProjectState


SOURCE = '第一行。\n第二行。\n第三行。\n第四行。\n第五行。\n第六行。'


def empty_part(part_id, owned_ref):
    return {
        'index_schema': 'lite-v1-part',
        'source_version': 'V0',
        'source_sha256': digest(SOURCE),
        'part_id': part_id,
        'owned_ref': owned_ref,
        'characters': [],
        'relationships': [],
        'scenes': [],
        'key_props': [],
        'timeline': [],
        'foreshadowing': [],
        'unknowns': [],
    }


def example_parts():
    first = empty_part('part_01', 'L1-L3')
    first['context_ref'] = ['L4']
    first['characters'] = [
        {'id': 'part_01:C002', 'names': ['乙'], 'first_ref': 'L3'},
        {'id': 'part_01:C001', 'names': ['甲'], 'first_ref': 'L1',
         'identity_changes': [{'scene': 'part_01:S001', 'state': '收到书信', 'ref': 'L2'}],
         'stable': [{'fact': '佩剑', 'ref': 'L1'}]},
    ]
    first['relationships'] = [
        {'id': 'part_01:R001', 'parties': ['part_01:C001', 'part_01:C002'],
         'changes': [{'scene': 'part_01:S001', 'state': '约定同行', 'ref': 'L3', 'known': '双方知情'}]},
    ]
    first['scenes'] = [{'id': 'part_01:S001', 'place': '院内', 'ref': 'L1-L3', 'time': '白日'}]
    first['key_props'] = [
        {'id': 'part_01:P001', 'names': ['书信'],
         'changes': [{'scene': 'part_01:S001', 'state': '由甲持有', 'ref': 'L2'}]},
    ]
    first['timeline'] = [
        {'id': 'part_01:T001', 'scene': 'part_01:S001', 'event': '甲收到书信', 'ref': 'L2',
         'result': '决定出发'},
    ]
    first['foreshadowing'] = [
        {'id': 'part_01:F001', 'clue': '信封未署名', 'clue_ref': 'L2',
         'knowledge_gap': '人物与观众都不知道寄信者'},
    ]
    first['unknowns'] = [
        {'id': 'part_01:U001', 'scene': 'part_01:S001', 'type': 'identity', 'issue': '寄信者未知',
         'ref': 'L2', 'blocks': '寄信者正面出镜'},
    ]

    second = empty_part('part_02', 'L4-L6')
    # 同名不等于同一实体；机械拼接必须保留这条独立观察。
    second['characters'] = [{'id': 'part_02:C001', 'names': ['甲'], 'first_ref': 'L4'}]
    second['scenes'] = [{'id': 'part_02:S001', 'place': '山门', 'ref': 'L4-L6'}]
    second['timeline'] = [
        {'id': 'part_02:T001', 'scene': 'part_02:S001', 'event': '另一名甲抵达山门', 'ref': 'L4'},
    ]
    return first, second


class StoryIndexMergeTests(unittest.TestCase):
    def setUp(self):
        self.first, self.second = example_parts()

    def merged(self):
        return merge_parts([self.first, self.second], source_text=SOURCE, source_version='V0')

    def test_mechanical_merge_is_stable_sorted_and_does_not_resolve_names(self):
        result = self.merged()
        self.assertEqual(result['review_status'], 'pending')
        self.assertEqual(result['coverage'], [
            {'part_id': 'part_01', 'owned_ref': 'L1-L3'},
            {'part_id': 'part_02', 'owned_ref': 'L4-L6'},
        ])
        self.assertEqual([item['names'] for item in result['characters']], [['甲'], ['乙'], ['甲']])
        self.assertEqual([item['id'] for item in result['characters']], ['C001', 'C002', 'C003'])
        self.assertEqual(result['characters'][0]['merged_from'], ['part_01:C001'])
        self.assertEqual(result['characters'][2]['merged_from'], ['part_02:C001'])
        self.assertEqual(result['relationships'][0]['parties'], ['C001', 'C002'])
        self.assertEqual(result['timeline'][1]['scene'], 'S002')

        reversed_result = merge_parts([self.second, self.first], source_text=SOURCE, source_version='V0')
        self.assertEqual(result, reversed_result)
        self.assertEqual(
            json.dumps(result, ensure_ascii=False, sort_keys=True),
            json.dumps(reversed_result, ensure_ascii=False, sort_keys=True),
        )

    def test_source_version_hash_and_schema_are_strict(self):
        for mutation in ('version', 'hash', 'field'):
            first = copy.deepcopy(self.first)
            if mutation == 'version':
                first['source_version'] = 'V0.1'
            elif mutation == 'hash':
                first['source_sha256'] = '0' * 64
            else:
                first['scenes'][0]['location'] = first['scenes'][0].pop('place')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                merge_parts([first, self.second], source_text=SOURCE, source_version='V0')

    def test_duplicate_temporary_ids_are_rejected(self):
        first = copy.deepcopy(self.first)
        first['characters'].append(copy.deepcopy(first['characters'][0]))
        with self.assertRaisesRegex(ValueError, 'ID重复'):
            merge_parts([first, self.second], source_text=SOURCE, source_version='V0')

    def test_owned_ranges_must_cover_source_once_without_gaps(self):
        cases = [('gap', 'L5-L6'), ('overlap', 'L3-L6'), ('tail', 'L4-L5')]
        for name, owned_ref in cases:
            second = copy.deepcopy(self.second)
            second['owned_ref'] = owned_ref
            # Keep record refs within the mutated range so coverage is the failure under test.
            if name == 'gap':
                second['characters'][0]['first_ref'] = 'L5'
                second['timeline'][0]['ref'] = 'L5'
                second['scenes'][0]['ref'] = 'L5-L6'
            elif name == 'tail':
                second['scenes'][0]['ref'] = 'L4-L5'
            with self.subTest(name=name), self.assertRaises(ValueError):
                merge_parts([self.first, second], source_text=SOURCE, source_version='V0')

    def test_record_refs_cannot_escape_owned_range_even_through_context(self):
        first = copy.deepcopy(self.first)
        first['characters'][0]['first_ref'] = 'L4'
        self.assertIn('L4', first['context_ref'])
        with self.assertRaisesRegex(ValueError, 'owned_ref'):
            merge_parts([first, self.second], source_text=SOURCE, source_version='V0')

    def test_context_must_be_immediately_adjacent_and_once_per_side(self):
        first = copy.deepcopy(self.first)
        first['context_ref'] = ['L5']
        with self.assertRaisesRegex(ValueError, '紧邻'):
            merge_parts([first, self.second], source_text=SOURCE, source_version='V0')

        first['context_ref'] = ['L4', 'L4-L5']
        with self.assertRaisesRegex(ValueError, '每侧最多一段'):
            merge_parts([first, self.second], source_text=SOURCE, source_version='V0')

    def test_cross_part_payoff_candidate_must_be_resolved_before_review(self):
        second = copy.deepcopy(self.second)
        second['foreshadowing'] = [
            {'id': 'part_02:F001', 'payoff': '寄信者身份揭晓', 'payoff_ref': 'L5',
             'clue_hint': '可能回应前段未署名书信'},
        ]
        result = merge_parts([self.first, second], source_text=SOURCE, source_version='V0')
        self.assertEqual(result['foreshadowing'][1]['clue_hint'], '可能回应前段未署名书信')

        unresolved = copy.deepcopy(result)
        unresolved['review_status'] = 'reviewed'
        with self.assertRaisesRegex(ValueError, '回收候选'):
            validate_final_index(unresolved, source_text=SOURCE, source_version='V0')

        clue, payoff = result['foreshadowing']
        clue['payoff'] = payoff['payoff']
        clue['payoff_ref'] = payoff['payoff_ref']
        clue['merged_from'].extend(payoff['merged_from'])
        result['foreshadowing'] = [clue]
        result['review_status'] = 'reviewed'
        validated = validate_final_index(result, source_text=SOURCE, source_version='V0')
        self.assertEqual(validated['foreshadowing'][0]['payoff_ref'], 'L5')

    def test_final_validation_requires_review_and_global_ids(self):
        result = self.merged()
        with self.assertRaisesRegex(ValueError, 'review_status'):
            validate_final_index(result, source_text=SOURCE, source_version='V0')
        result['review_status'] = 'reviewed'
        validated = validate_final_index(result, source_text=SOURCE, source_version='V0')
        self.assertEqual(validated['review_status'], 'reviewed')
        result['characters'][0]['id'] = 'part_01:C001'
        with self.assertRaisesRegex(ValueError, '编号规则'):
            validate_final_index(result, source_text=SOURCE, source_version='V0')

    def test_internal_ids_are_rewritten_and_dangling_links_are_rejected(self):
        result = self.merged()
        self.assertEqual(result['characters'][0]['identity_changes'][0]['scene'], 'S001')
        self.assertEqual(result['key_props'][0]['changes'][0]['scene'], 'S001')
        broken = copy.deepcopy(self.first)
        broken['relationships'][0]['parties'][1] = '人物乙'
        with self.assertRaisesRegex(ValueError, '不能使用名称'):
            merge_parts([broken, self.second], source_text=SOURCE, source_version='V0')

        result['review_status'] = 'reviewed'
        result['timeline'][0]['scene'] = 'S999'
        with self.assertRaisesRegex(ValueError, '不存在'):
            validate_final_index(result, source_text=SOURCE, source_version='V0')

    def test_reviewed_provenance_and_p0_type_remain_unambiguous(self):
        result = self.merged()
        result['review_status'] = 'reviewed'
        result['characters'][1]['merged_from'] = list(result['characters'][0]['merged_from'])
        with self.assertRaisesRegex(ValueError, '重复归入'):
            validate_final_index(result, source_text=SOURCE, source_version='V0')

        first = copy.deepcopy(self.first)
        first['unknowns'][0]['type'] = '普通疑问'
        with self.assertRaisesRegex(ValueError, 'P0 类型'):
            merge_parts([first, self.second], source_text=SOURCE, source_version='V0')


class StoryIndexProjectStateTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path(os.environ.get('SEEDANCE_TEST_TMP', tempfile.gettempdir())).resolve()
        self.project = self.temp_root / ('seedance-v120-' + uuid.uuid4().hex)
        self.project.mkdir()
        self.store = ProjectState(self.project)
        self.store.init('story')
        self.store.ingest('screenplay', SOURCE)

    def tearDown(self):
        self.assertEqual(self.project.resolve().parent, self.temp_root)
        shutil.rmtree(self.project)

    def test_project_state_accepts_only_reviewed_lite_index(self):
        first, second = example_parts()
        index = merge_parts([first, second], source_text=SOURCE, source_version='V0')
        with self.assertRaises(ValueError):
            self.store.story_index('screenplay', index)
        index['review_status'] = 'reviewed'
        self.store.story_index('screenplay', index)
        stored = self.store.read()['segments']['screenplay']['story_index']
        self.assertEqual(stored['index_schema'], 'lite-v1')
        self.assertEqual(stored['review_status'], 'reviewed')

    def test_old_string_lists_and_stale_baselines_are_rejected(self):
        old = {
            'index_schema': 'lite-v1', 'source_version': 'V0', 'source_sha256': digest(SOURCE),
            'coverage': [{'part_id': 'full', 'owned_ref': 'L1-L6'}], 'review_status': 'reviewed',
            'characters': ['甲'], 'relationships': [], 'scenes': [], 'key_props': [],
            'timeline': [], 'foreshadowing': [], 'unknowns': [],
        }
        with self.assertRaises(ValueError):
            self.store.story_index('screenplay', old)

        first, second = example_parts()
        index = merge_parts([first, second], source_text=SOURCE, source_version='V0')
        index['review_status'] = 'reviewed'
        self.store.story_index('screenplay', index)
        self.store.revise('screenplay', SOURCE + '\n第七行。', '用户增加一行')
        self.assertEqual(self.store.read()['segments']['screenplay']['index_status'], 'stale')
        with self.assertRaises(ValueError):
            self.store.story_index('screenplay', index)


if __name__ == '__main__':
    unittest.main()
