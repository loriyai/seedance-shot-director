import json
import os
import shutil
import uuid
from pathlib import Path
import tempfile
import unittest

import validate_dialogue_and_timeline as v
from test_validate_dialogue_and_timeline import block, speech, two_shot_monologue, notice
from project_state import ProjectState


def declaration(identifier, name, kind, start, end, pause='0.3秒', profile='短剧常速', overlap='连续'):
    return f'口播段：{identifier}｜{name}｜{kind}｜{start:g}-{end:g}秒｜{profile}｜停顿{pause}｜{overlap}'


def typed(identifier, name, kind, words):
    return f'台词：{identifier}｜{name}｜{kind}：“{words}”'


def make_prompt(voices, fragments, length=15, count=5):
    text = block(length, count)
    text = text.replace('[镜头1]', '\n'.join(voices) + '\n[镜头1]')
    for shot, identifier, name, kind, words in reversed(fragments):
        text = text.replace(f'[镜头{shot}]', f'[镜头{shot}]\n' + typed(identifier, name, kind, words))
    return text


class NewVoiceTests(unittest.TestCase):
    def errors(self, diagnostics):
        return [d.message for d in diagnostics if d.level == 'ERROR']

    def test_pause_budget_uses_net_phonation(self):
        words = '我们现在出发，沿着山路前行，到了门口等我，不要擅自行动。'
        source = f'陈默：「{words}」'
        out = make_prompt([declaration('V1','陈默','对白',0,7,'1秒')],[(1,'V1','陈默','对白',words)],30,4)
        self.assertEqual(self.errors(v.validate_voice_pacing(source,out,30)),[])

    def test_explicit_zero_pause_slow_rate_is_error(self):
        out=make_prompt([declaration('V1','陈默','对白',0,2,'0秒')],[(1,'V1','陈默','对白','出发吧。')])
        self.assertTrue(self.errors(v.validate_voice_pacing('陈默：「出发吧。」',out,15)))

    def test_chain_must_match_its_shots(self):
        source='陈默OS：「原来我不是什么武侠男主，只是路边小兵。」'
        out=two_shot_monologue('连续口播：陈默OS｜10.0-14.2秒｜短剧常速｜跨镜连续，镜头切换不停顿，仅按原标点自然换气。')
        self.assertTrue(any('镜头不匹配' in e for e in self.errors(v.validate(source,out,15))))

    def test_audio_cannot_enter_silent_tail(self):
        out=make_prompt([declaration('V1','陈默','对白',12,15,'0.5秒')],[(5,'V1','陈默','对白','大家现在跟我往前走吧。')])
        self.assertTrue(any('无对白尾帧' in e for e in self.errors(v.validate('陈默：「大家现在跟我往前走吧。」',out,15))))

    def test_overlap_needs_explicit_source_annotation_on_both(self):
        a,b='大家现在跟我往前走吧。','到了门口千万别停下来。'
        voices=[declaration('V1','陈默','对白',0,2.5,'0.3秒'),declaration('V2','吴天德','对白',0,2.5,'0.3秒')]
        out=make_prompt(voices,[(1,'V1','陈默','对白',a),(1,'V2','吴天德','对白',b)])
        self.assertTrue(any('重叠' in e for e in self.errors(v.validate_voice_pacing(f'陈默：「{a}」\n吴天德：「{b}」',out,15))))
        out=out.replace('｜连续','｜重叠：原文要求二人同时齐声')
        self.assertEqual(self.errors(v.validate_voice_pacing(f'动作：二人同时齐声。\n陈默：「{a}」\n吴天德：「{b}」',out,15)),[])

    def test_separate_same_speaker_turns_stay_separate(self):
        source='陈默：「等我。」\n动作：陈默走到门口再次开口。\n陈默：「走吧。」'
        out=make_prompt([declaration('V1','陈默','对白',0,0.8),declaration('V2','陈默','对白',12,12.8)],[(1,'V1','陈默','对白','等我。'),(5,'V2','陈默','对白','走吧。')])
        self.assertEqual(self.errors(v.validate(source,out,15)),[])
        legacy=block().replace('[镜头1]','[镜头1]\n'+speech('陈默','等我。')).replace('[镜头5]','[镜头5]\n'+speech('陈默','走吧。'))
        self.assertEqual(self.errors(v.validate_voice_pacing(source,legacy,15)),[])

    def test_parenthesized_os_is_same_identity(self):
        self.assertEqual(v.canonical_speaker('陈默（OS）'),v.canonical_speaker('陈默OS'))
        self.assertEqual(v.validate_dialogue('陈默（OS）：「走吧。」','台词：陈默OS说：“走吧。”'),[])

    def test_explicit_label_without_speech_verb_is_parsed(self):
        self.assertEqual(v.validate_dialogue('陈默：「走吧。」','台词：陈默（对白）：“走吧。”'),[])

    def test_inline_narrative_speech_keeps_explicit_identity(self):
        source='院内，林舟把信放在桌上。林舟说：“明日出发。”沈遥看着信，没有伸手。沈遥说：“我在南门等你。”两人走出院门。'
        output=typed('V1','林舟','对白','明日出发。')+'\n'+typed('V2','沈遥','对白','我在南门等你。')
        self.assertEqual(v.validate_dialogue(source,output),[])
        self.assertTrue(self.errors(v.validate_dialogue(source,output.replace('南门','城门'))))

    def test_system_and_narrator_identities_do_not_collapse(self):
        for source,out in [
            ('系统甲：「出发。」\n系统乙：「留下。」',speech('系统乙','出发。')+'\n'+speech('系统甲','留下。')),
            ('陈默（旁白）：「出发。」\n吴天德（旁白）：「留下。」',speech('吴天德（旁白）','出发。')+'\n'+speech('陈默（旁白）','留下。')),
        ]:
            self.assertTrue(self.errors(v.validate_dialogue(source,out)))

    def test_unparsed_output_does_not_downgrade_known_change(self):
        source='陈默：「留下。」\n吴天德：「出发。」'
        out=speech('陈默','改动。')+'\n'+speech('吴天德','出发。')+'\n台词：“未知归属。”'
        self.assertTrue(self.errors(v.validate_dialogue(source,out)))

    def test_numeric_reading_uncertainty_is_warning_not_false_precision(self):
        out=make_prompt([declaration('V1','陈默','对白',0,2)],[(1,'V1','陈默','对白','编号2026。')])
        result=v.validate_voice_pacing('陈默：「编号2026。」',out,15)
        self.assertEqual(self.errors(result),[])
        self.assertTrue(any(d.level=='WARN' and '实际读法' in d.message for d in result))

    def test_fast_speech_extended_run_gets_advisory(self):
        words='大家现在跟我往前走吧'*3
        out=make_prompt([declaration('V1','陈默','对白',0,30/5.5,'0秒','短剧快节奏')],[(1,'V1','陈默','对白',words)],30,4)
        result=v.validate_voice_pacing(f'陈默：「{words}」',out,30)
        self.assertEqual(self.errors(result),[])
        self.assertTrue(any('超过3秒' in d.message for d in result))

    def test_ids_types_and_presence_are_checked(self):
        out=make_prompt([declaration('V1','陈默','OS',0,0.8)],[(1,'V1','陈默','对白','走吧。')])
        self.assertTrue(self.errors(v.validate_voice_pacing('陈默：「走吧。」',out,15)))
        out=make_prompt([],[(1,'V2','陈默','对白','走吧。')])
        self.assertTrue(self.errors(v.validate_voice_pacing('陈默：「走吧。」',out,15)))


class BlockContractTests(unittest.TestCase):
    def errors(self, diagnostics):
        return [d for d in diagnostics if d.level=='ERROR']

    def test_required_preamble_and_placeholder(self):
        out=block().replace('人物：陈默，青年，深色长衫。','')
        self.assertTrue(self.errors(v.validate_structure(out,15)))
        self.assertTrue(self.errors(v.validate_structure(block().replace('深色长衫','<待填写>'),15)))

    def test_model_caps_and_declared_duration(self):
        self.assertTrue(self.errors(v.validate_structure(block(30,10),30,model='2.0')))
        self.assertEqual(self.errors(v.validate_structure(block(30,10),30,model='2.5')),[])
        self.assertTrue(self.errors(v.validate_structure(block().replace('｜15秒｜16:9',''),15)))

    def test_tail_rebalance_and_thirty_remainder(self):
        self.assertEqual(self.errors(v.validate_structure(block(13,4)+'\n'+block(4,1,2),15)),[])
        self.assertEqual(self.errors(v.validate_structure(block(30,10)+'\n'+block(8,3,2),30)),[])
        self.assertTrue(self.errors(v.validate_structure(block(15,4),15)))

    def test_minimum_step_and_thirty_advisory(self):
        self.assertTrue(self.errors(v.validate_structure(block(4,1),15,min_duration=5)))
        self.assertTrue(self.errors(v.validate_structure(block(4.5,2),15,duration_step=1)))
        result=v.validate_structure(block(30,1),30)
        self.assertEqual(self.errors(result),[])
        self.assertTrue(any('8-12' in d.message for d in result))

    def test_deferred_is_opt_in(self):
        raw='陈默：「走吧。」'
        self.assertTrue(self.errors(v.validate(raw,notice(raw),15)))
        self.assertEqual(self.errors(v.validate(raw,notice(raw),15,allow_deferred=True)),[])

    def test_continuous_and_source_hard_cut_can_end_without_forced_silence(self):
        for mode in ('连续剪辑','剧情硬切'):
            out=block().replace('独立收束',mode)
            out=out[:out.index('无对白尾帧')]
            self.assertEqual(self.errors(v.validate_structure(out,15)),[])


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp_root=Path(os.environ.get('SEEDANCE_TEST_TMP',tempfile.gettempdir())).resolve()
        self.project=self.temp_root / ('seedance-test-' + uuid.uuid4().hex)
        self.project.mkdir()
        self.store=ProjectState(self.project)
        self.store.init('story')
        self.store.ingest('seg001','林舟：「明日出发。」')

    def tearDown(self):
        self.assertEqual(self.project.resolve().parent,self.temp_root)
        shutil.rmtree(self.project)

    def test_version_round_trip_and_recovery(self):
        revised='林舟：「明日启程。」'
        self.assertEqual(self.store.revise('seg001',revised,'用户明确确认'), 'V0.1')
        self.assertEqual(self.store.revise('seg001',revised,'重复确认'), 'V0.1')
        self.store.review('seg001','标记审阅稿')
        with self.assertRaises(ValueError): self.store.source('seg001')
        self.store.confirm('seg001',revised+'\n林舟沿石阶离开。')
        recovered=ProjectState(self.project)
        self.assertEqual(recovered.source('seg001')['version'],'C1')
        self.assertEqual(recovered.use_original('seg001'),'V0.1')
        self.assertEqual(recovered.use_original('seg001',initial=True),'V0')
        self.assertEqual(recovered.use_original('seg001'),'V0.1')
        self.store.review('seg001','新审阅方案')
        self.assertEqual(self.store.read()['segments']['seg001']['versions']['R2']['baseline'],'V0.1')

    def test_review_confirmation_with_approved_baseline_change(self):
        self.store.review('seg001','文字修订与表演审阅稿')
        self.store.confirm('seg001','林舟：「明日启程。」\n林舟走出院门。',baseline_text='林舟：「明日启程。」',reason='用户接受文字修订')
        state=self.store.read()['segments']['seg001']
        self.assertEqual(state['baseline'],'V0.1')
        self.assertEqual(self.store.verified_text(state['versions']['V0']),'林舟：「明日出发。」')
        self.assertNotIn('走出',self.store.verified_text(state['versions']['V0.1']))

    def test_immutable_original_and_tamper_detection(self):
        with self.assertRaises(ValueError): self.store.ingest('seg001','覆盖原文')
        self.store.use_original('seg001')
        record=self.store.read()['segments']['seg001']['versions']['V0']
        self.store.path(record['path']).write_text('外部篡改',encoding='utf-8')
        with self.assertRaises(ValueError): self.store.source('seg001')

    def test_stale_review_and_ledger_are_rejected(self):
        self.store.use_original('seg001')
        source=self.store.source('seg001')
        self.store.ledger('seg001',{'source_version':source['version'],'source_sha256':source['sha256'],'beats':[]})
        self.store.review('seg001','旧审阅稿')
        self.store.revise('seg001','新原文','用户更正')
        with self.assertRaises(ValueError): self.store.confirm('seg001','旧来源确认')
        self.assertEqual(self.store.read()['segments']['seg001']['ledger_status'],'stale')
        with self.assertRaises(ValueError): self.store.ledger('seg001',{'source_version':'V0','source_sha256':source['sha256']})

    def test_project_config_defaults_and_persistence(self):
        self.assertEqual(self.store.read()['config']['enhancement_level'],'light')
        self.store.config({'enhancement_policy':'always_enhance','style':{'custom':'淡墨国风'}})
        self.assertEqual(ProjectState(self.project).read()['config']['enhancement_policy'],'always_enhance')

    def test_path_traversal_and_install_directory_are_rejected(self):
        with self.assertRaises(ValueError): self.store.ingest('../outside','text')
        with self.assertRaises(ValueError): self.store.path('../../outside.txt')
        with self.assertRaises(ValueError): ProjectState(Path(__file__).resolve().parent)

    def test_explicit_initial_review_preserves_latest_baseline(self):
        self.store.revise('seg001','修订后的原文','用户确认')
        self.store.review('seg001','从最初V0制作的审阅稿',initial=True)
        self.store.confirm('seg001','从最初V0制作的确认稿')
        state=self.store.read()['segments']['seg001']
        self.assertEqual(state['baseline'],'V0.1')
        self.assertEqual(state['versions']['C1']['baseline'],'V0')
        self.assertEqual(self.store.use_original('seg001'),'V0.1')

    def test_exact_newlines_survive_restart(self):
        original='第一行\r\n第二行\r\n'
        self.store.ingest('seg002',original)
        self.store.use_original('seg002')
        record=ProjectState(self.project).read()['segments']['seg002']['versions']['V0']
        self.assertEqual(self.store.verified_text(record),original)

    def test_returning_to_original_deactivates_abandoned_review(self):
        self.store.review('seg001','已放弃的增强稿')
        self.store.use_original('seg001')
        with self.assertRaises(ValueError): self.store.confirm('seg001','旧增强稿内容')
        self.assertIn('R1',self.store.read()['segments']['seg001']['versions'])


if __name__=='__main__': unittest.main()
