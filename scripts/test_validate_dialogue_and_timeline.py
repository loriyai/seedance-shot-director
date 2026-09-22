"""Regression checks for text contracts, not assertions about rendered videos."""

import unittest

import validate_dialogue_and_timeline as validator


def block(duration=15, count=5, number=1):
    lines = [f"生成块 {number:02d}｜{duration:g}秒｜16:9", "国风3D人物与旧布木石材质，无配乐，保留环境声。", "人物：陈默", "场景：坟间小路与两座墓碑。", "本块氛围与站位：阴天柔光，陈默站在两坟之间。", "收尾方式：独立收束"]
    for index in range(count):
        start = duration * index / count
        end = duration * (index + 1) / count
        lines += [
            f"[镜头{index + 1}]",
            f"时间区间：{start:.6f}-{end:.6f}秒。",
            "画面与动作：陈默背向摄影机，沿墓间小路向纵深走远。",
            "摄影机与构图：固定侧后方中远景，双坟在画面两侧，陈默位于小路中轴。",
        ]
    tail_start = max(0, duration - 0.5)
    lines.append(f"声音安排：{tail_start:g}-{duration:g}秒无口播，仅保留本镜动作或状态的连续画面，不定格。")
    lines.append("无对白尾帧：最后0.5秒无对白，陈默继续走远，保留脚步声。")
    return "\n".join(lines)


def speech(name, words):
    return f"台词：{name}说：“{words}”"


def notice(raw):
    return f"本次未使用文案：\n{raw}\n（“{raw}”不足4s，本次未使用，请合并到下一次的分段文案中）"


def two_shot_monologue(chain=None):
    prompt = block()
    if chain:
        prompt = prompt.replace("[镜头1]", chain + "\n[镜头1]")
    prompt = prompt.replace(
        "时间区间：0.000000-3.000000秒。",
        "时间区间：0.000000-3.000000秒。\n" + speech("陈默OS", "原来我不是什么武侠男主，"),
    )
    prompt = prompt.replace(
        "时间区间：3.000000-6.000000秒。",
        "时间区间：3.000000-6.000000秒。\n" + speech("陈默OS", "只是路边小兵。"),
    )
    return prompt


class ValidatorTests(unittest.TestCase):
    def assertNoErrors(self, diagnostics):
        self.assertFalse([item.render() for item in diagnostics if item.level == "ERROR"])

    def assertHas(self, diagnostics, text, level=None):
        self.assertTrue(any(text in item.message and (level is None or item.level == level) for item in diagnostics), [item.render() for item in diagnostics])

    def test_full_fifteen_has_five_continuous_shots(self):
        self.assertEqual(validator.validate_structure(block(), 15), [])

    def test_fifteen_shots_outside_five_to_seven_is_hard_error(self):
        for count in (4, 8):
            with self.subTest(count=count):
                self.assertHas(validator.validate_structure(block(count=count), 15), "5-7镜", "ERROR")
        for count in (5, 6, 7):
            with self.subTest(count=count):
                self.assertNoErrors([d for d in validator.validate_structure(block(count=count), 15)
                                     if '镜' in d.message])

    def test_short_blocks_are_legal_and_fractional_durations_are_rejected(self):
        self.assertNoErrors(validator.validate_structure(block() + "\n" + block(8, 3, 2), 15))
        self.assertNoErrors(validator.validate_structure(block() + "\n\n" + block(8, 3, 2), 15))
        self.assertNoErrors(validator.validate_structure(block(13, 4) + "\n" + block(4, 1, 2), 15))
        self.assertNoErrors(validator.validate_structure(block(8, 3) + "\n" + block(number=2) + "\n" + block(number=3), 15))
        self.assertHas(validator.validate_structure(block(7.5, 3), 15), "整数", "ERROR")

    def test_four_seconds_is_inclusive_minimum(self):
        self.assertNoErrors(validator.validate_structure(block(4, 1), 15))
        for seconds in (3.99, 3.95, 15.01):
            with self.subTest(seconds=seconds):
                self.assertHas(validator.validate_structure(block(seconds, 1), 15), "只能为 4-15 秒", "ERROR")

    def test_thirty_mode_still_works(self):
        self.assertNoErrors(validator.validate_structure(block(30, 10), 30))

    def test_any_shot_over_five_seconds_fails(self):
        self.assertHas(validator.validate_structure(block(30, 5), 30), "最长不得超过5秒", "ERROR")
        self.assertNoErrors(validator.validate_structure(block(25, 5), 30))
        almost = block().replace("0.000000-3.000000", "0.000000-5.0000001")
        self.assertHas(validator.validate_structure(almost, 15), "最长不得超过5秒", "ERROR")

    def test_missing_and_repeated_shot_numbers(self):
        for number in (2, 7):
            self.assertHas(validator.validate_structure(block().replace("[镜头3]", f"[镜头{number}]"), 15), "编号必须", "ERROR")

    def test_repeated_block_number(self):
        self.assertHas(validator.validate_structure(block() + "\n" + block(), 15), "生成块编号重复", "ERROR")

    def test_timeline_gap_and_wrong_total(self):
        self.assertHas(validator.validate_structure(block().replace("3.000000-6.000000", "3.010000-6.000000"), 15), "不连续", "ERROR")
        self.assertHas(validator.validate_structure(block().replace("12.000000-15.000000", "12.000000-14.990000"), 15), "总长", "ERROR")

    def test_camera_distance_cannot_replace_timeline(self):
        prompt = block(4, 1).replace("时间区间：0.000000-4.000000秒。", "摄影距离：0-4米。")
        self.assertHas(validator.validate_structure(prompt, 15), "缺少“起点-终点秒”", "ERROR")

    def test_fixed_camera_is_not_missing_movement(self):
        self.assertEqual(validator.shot_risk_warnings(block(4, 1), 4, "01", "1"), [])

    def test_camera_internal_cut_errors_but_entry_transition_does_not(self):
        prompt = block(4, 1).replace("固定侧后方", "先拍正面，再切到侧后方")
        self.assertHas(validator.shot_risk_warnings(prompt, 4, "01", "1"), "额外切镜", "ERROR")
        self.assertFalse(any("额外切镜" in item.message for item in validator.shot_risk_warnings(block(4, 1) + "\n衔接：切到本镜。", 4, "01", "1")))

    def test_missing_camera_mode_warns(self):
        self.assertHas(validator.shot_risk_warnings("摄影机与构图：侧后方中远景。", 4, "01", "1"), "固定机位或主运镜", "WARN")

    def test_speech_capacity_and_spoken_numerals_warn(self):
        diagnostics = validator.shot_risk_warnings(speech("陈默", "我捡到一本绝世秘籍，给我十年，我一定提着仇人的头来祭拜你们。评分88。"), 2, "01", "1")
        self.assertHas(diagnostics, "对白容量风险", "WARN")
        self.assertHas(diagnostics, "实际读法", "WARN")

    def test_sparse_single_shot_speech_warns_about_slow_pace(self):
        diagnostics = validator.shot_risk_warnings(speech("陈默", "原来我不是武侠男主"), 6, "01", "1")
        self.assertHas(diagnostics, "台词慢节奏风险", "WARN")

    def test_action_keyword_and_screen_text_are_not_spoken(self):
        output = "画面与动作：说到“秘籍”时，陈默取书。\n画面文字：古书显示“秘籍”。\n" + speech("陈默", "秘籍。")
        self.assertEqual(validator.validate_dialogue("陈默：「秘籍。」", output), [])

    def test_explicit_multiline_corner_quote(self):
        source = "陈默「爹！娘！\n我捡到一本秘籍\n给我十年」"
        self.assertEqual(validator.validate_dialogue(source, speech("陈默", "爹！娘！我捡到一本秘籍，给我十年")), [])

    def test_bare_quote_never_silently_claims_complete_coverage(self):
        source = "陈默低头\n「爹！娘！」\n系统：「结算完毕。」"
        self.assertHas(validator.validate_dialogue(source, speech("系统", "结算完毕。")), "覆盖不完整", "WARN")

    def test_unclosed_source_quote_warns(self):
        self.assertHas(validator.validate_dialogue("陈默：「还没说完", speech("陈默", "还没说完")), "未闭合", "WARN")

    def test_unclosed_output_quote_warns(self):
        self.assertHas(validator.validate_dialogue("陈默：「走。」", speech("陈默", "走。") + "陈默说：“等一下"), "覆盖不完整", "WARN")

    def test_unquoted_continuation_requires_review(self):
        self.assertHas(validator.validate_dialogue("陈默：我记得那场雨\n也记得你转身时的背影。", speech("陈默", "我记得那场雨，也记得你转身时的背影。")), "无引号连续台词", "WARN")

    def test_os_is_distinct_from_dialogue(self):
        source = "陈默OS：「江湖，我来了！」"
        self.assertEqual(validator.validate_dialogue(source, speech("陈默OS", "江湖，我来了！")), [])
        self.assertHas(validator.validate_dialogue(source, speech("陈默", "江湖，我来了！")), "错归属", "ERROR")

    def test_system_and_narration_are_explicit_audio(self):
        source = "系统：「结算中。」\n旁白：「十年后。」"
        output = speech("系统声音", "结算中。") + "\n" + speech("旁白", "十年后。")
        self.assertEqual(validator.validate_dialogue(source, output), [])

    def test_display_only_does_not_require_dialogue(self):
        source = "画面文字：「评分：88」\n陈默：「报仇！」"
        self.assertEqual(validator.validate_dialogue(source, speech("陈默", "报仇！")), [])
        mixed = "系统：「第一世悟性10 不念\n第二世资质0」"
        self.assertHas(validator.validate_dialogue(mixed, ""), "朗读", "WARN")

    def test_dialogue_may_span_shots(self):
        source = "陈默：「江湖，我来了！」"
        output = "[镜头1]\n" + speech("陈默", "江湖，") + "\n[镜头2]\n" + speech("陈默", "我来了！")
        self.assertEqual(validator.validate_dialogue(source, output), [])
        self.assertEqual(validator.validate_dialogue_split_boundaries(source, output, "01", {"陈默"}), [])

    def test_dialogue_cannot_split_inside_continuous_words(self):
        source = "陈默：「江湖，我来了！」"
        output = "[镜头1]\n" + speech("陈默", "江") + "\n[镜头2]\n" + speech("陈默", "湖，我来了！")
        self.assertHas(validator.validate_dialogue_split_boundaries(source, output, "01", {"陈默"}), "已有标点", "ERROR")

    def test_dialogue_cannot_split_inside_punctuation_cluster(self):
        source = "陈默：「真的吗？！我不信。」"
        output = "[镜头1]\n" + speech("陈默", "真的吗？") + "\n[镜头2]\n" + speech("陈默", "！我不信。")
        self.assertHas(validator.validate_dialogue_split_boundaries(source, output, "01", {"陈默"}), "已有标点", "ERROR")

    def test_redundant_dialogue_spaces_warn_but_foreign_spacing_does_not(self):
        _, diagnostics = validator.analyse_source_dialogue('陈默：「我  不走。」')
        self.assertHas(diagnostics, "多余空格", "WARN")
        _, diagnostics = validator.analyse_source_dialogue('陈默：「Seedance 2.5 可以用。」')
        self.assertFalse(any('多余空格' in item.message for item in diagnostics))
        _, diagnostics = validator.analyse_source_dialogue('陈默：「我\u00a0不走。」')
        self.assertHas(diagnostics, "多余空格", "WARN")
        _, diagnostics = validator.analyse_source_dialogue('画面文字：「天 地」')
        self.assertFalse(any('多余空格' in item.message for item in diagnostics))

    def test_dialogue_split_cannot_hide_behind_new_voice_ids_or_silent_shot(self):
        source = '陈默：「明日出发。」'
        output = '[镜头1]\n' + speech('陈默', '明日') + '\n[镜头2]\n画面与动作：陈默抬头。\n[镜头3]\n' + speech('陈默', '出发。')
        self.assertHas(
            validator.validate_dialogue_split_boundaries(source, output, '01', {'陈默'}),
            '已有标点',
            'ERROR',
        )

    def test_dialogue_split_rule_also_crosses_generation_block_boundary(self):
        source = '陈默：「明日出发。」'
        first = block(number=1).replace('[镜头5]', '[镜头5]\n' + speech('陈默', '明日'))
        second = block(number=2).replace('[镜头1]', '[镜头1]\n' + speech('陈默', '出发。'))
        self.assertHas(validator.validate_voice_pacing(source, first + '\n' + second, 15), '已有标点', 'ERROR')

    def test_dialogue_cannot_split_at_quote_but_can_at_normalised_newline(self):
        quoted = '他说：“好。”然后走。'
        self.assertFalse(validator.valid_speech_split_boundary(quoted, quoted.index('”')))
        source = '陈默：「第一行\n第二行。」'
        output = '[镜头1]\n' + speech('陈默', '第一行，') + '\n[镜头2]\n' + speech('陈默', '第二行。')
        self.assertEqual(validator.validate_dialogue_split_boundaries(source, output, '01', {'陈默'}), [])
        self.assertFalse(validator.source_backed_speech_boundary(
            '陈默：「第一行第二行。」', '第一行，第二行。', 4, '陈默', '对白'
        ))

    def test_normalised_newline_boundary_also_crosses_generation_blocks(self):
        source = '陈默：「第一行\n第二行。」'
        first = block(number=1).replace('[镜头5]', '[镜头5]\n' + speech('陈默', '第一行，'))
        second = block(number=2).replace('[镜头1]', '[镜头1]\n' + speech('陈默', '第二行。'))
        diagnostics = validator.validate_dialogue_split_boundaries(
            source, first + '\n' + second, None, {'陈默'}
        )
        self.assertEqual(diagnostics, [])

    def test_spaced_foreign_dialogue_keeps_legal_cross_shot_boundary(self):
        source = '陈默：「Seedance 2.5 可以用，明天试试。」'
        output = (
            '[镜头1]\n' + speech('陈默', 'Seedance 2.5 可以用，')
            + '\n[镜头2]\n' + speech('陈默', '明天试试。')
        )
        self.assertEqual(validator.validate_dialogue(source, output), [])
        self.assertEqual(
            validator.validate_dialogue_split_boundaries(source, output, '01', {'陈默'}),
            [],
        )

    def test_newline_normalisation_preserves_existing_punctuation_and_final_line(self):
        self.assertEqual(
            validator.normalise_utterance('第一行\n第二行\n最后一句'),
            '第一行，第二行，最后一句',
        )
        self.assertEqual(
            validator.normalise_utterance('第一行！\n第二行。\n最后一句'),
            '第一行！第二行。最后一句',
        )
        for punctuation in ('、', '；', '：', ';', ':'):
            with self.subTest(punctuation=punctuation):
                self.assertEqual(
                    validator.normalise_utterance(f'甲{punctuation}\n乙'),
                    f'甲{punctuation}乙',
                )
        turns = validator.extract_source_dialogue('陈默：甲；\n乙')
        self.assertEqual([turn.text for turn in turns], ['甲；乙'])
        self.assertFalse(validator.normalise_utterance('第一行\n最后一句').endswith('，'))

    def test_sound_arrangement_cannot_use_legacy_or_inline_bypass(self):
        without_last = '\n'.join(line for line in block().splitlines() if not line.startswith('声音安排：'))
        self.assertNoErrors(validator.validate_structure(without_last, 15))
        doubled = block() + '\n声音安排：本镜无口播，仅保留环境与动作声与连续画面。'
        self.assertHas(validator.validate_structure(doubled, 15), '最多输出一次', 'ERROR')
        inline = block().replace(
            '画面与动作：陈默背向摄影机，沿墓间小路向纵深走远。',
            '画面与动作：陈默背向摄影机，声音安排：0-1秒无口播，随后沿墓间小路走远。',
            1,
        )
        self.assertHas(validator.validate_structure(inline, 15), '独立字段', 'ERROR')

    def test_order_and_added_or_repeated_speech_fail(self):
        source = "陈默：「问。」\n吴天德：「答。」"
        first, second = speech("陈默", "问。"), speech("吴天德", "答。")
        for output in (second + "\n" + first, first + "\n" + second + "\n" + first, first):
            self.assertHas(validator.validate_dialogue(source, output), "不一致", "ERROR")

    def test_substring_repetition_is_not_false_duplicate(self):
        self.assertEqual(validator.validate_dialogue("陈默：「走。」\n陈默：「走。走。」", speech("陈默", "走。走。走。")), [])

    def test_exact_deferred_suffix_is_excluded(self):
        source = "陈默：「走。」\n陈默：「再见。」"
        prompt = block() + "\n" + speech("陈默", "走。") + "\n" + notice("陈默：「再见。」")
        diagnostics = validator.validate(source, prompt, 15, allow_deferred=True)
        self.assertNoErrors(diagnostics)
        self.assertHas(diagnostics, "不足 4 秒仍须人工复核", "WARN")

    def test_only_deferred_text_does_not_require_video(self):
        raw = "陈默：「走。」"
        self.assertNoErrors(validator.validate(raw, notice(raw), 15, allow_deferred=True))

    def test_changed_or_non_suffix_deferred_text_fails(self):
        source = "陈默：「走。」\n陈默：「再见。」"
        for raw in ("陈默：「快走。」", "陈默：「走。」"):
            self.assertHas(validator.validate(source, block() + "\n" + notice(raw), 15), "不能从覆盖检查排除", "ERROR")

    def test_legacy_entry_and_missing_context_warn(self):
        prompt = block() + "\n入口状态：保持十年前坟墓构图，陈默进入原来的位置。"
        diagnostics = validator.validate_structure(prompt, 15)
        self.assertHas(diagnostics, "留在后台", "WARN")
        self.assertHas(diagnostics, "上一块上下文", "WARN")

    def test_spoken_units_expand_common_arabic_numerals(self):
        self.assertEqual(validator.spoken_unit_count("评分88"), 5)
        self.assertEqual(validator.spoken_unit_count("悟性50，资质38，血脉0"), 12)
        self.assertEqual(validator.spoken_unit_count("10、11、101、3.14"), 11)

    def test_cross_shot_direct_prompt_no_longer_requires_voice_chain(self):
        source = "陈默OS：「原来我不是什么武侠男主，只是路边小兵。」"
        diagnostics = validator.validate_voice_pacing(source, two_shot_monologue(), 15)
        self.assertNoErrors(diagnostics)

    def test_legacy_pacing_without_pause_budget_requires_review(self):
        source = "陈默OS：「原来我不是什么武侠男主，只是路边小兵。」"
        chain = "连续口播：陈默OS｜0.0-6.0秒｜短剧常速｜跨镜连续，镜头切换不停顿，仅按原标点自然换气。"
        diagnostics = validator.validate_voice_pacing(source, two_shot_monologue(chain), 15)
        self.assertHas(diagnostics, "估时偏慢", "WARN")
        self.assertHas(diagnostics, "17 个可发音单位", "WARN")

    def test_natural_four_point_two_second_chain_passes(self):
        source = "陈默OS：「原来我不是什么武侠男主，只是路边小兵。」"
        chain = "连续口播：陈默OS｜0.0-4.2秒｜短剧常速｜跨镜连续，镜头切换不停顿，仅按原标点自然换气。"
        self.assertEqual(validator.validate_voice_pacing(source, two_shot_monologue(chain), 15), [])
        self.assertNoErrors(validator.validate(source, two_shot_monologue(chain), 15))

    def test_voice_chain_format_profile_and_bounds_are_enforced(self):
        source = "陈默OS：「原来我不是什么武侠男主，只是路边小兵。」"
        malformed = "连续口播：陈默OS｜0.0-4.2秒｜短剧常速｜跨镜连续。"
        self.assertHas(validator.validate_voice_pacing(source, two_shot_monologue(malformed), 15), "格式不完整", "ERROR")
        unknown = "连续口播：陈默OS｜0.0-4.2秒｜电影语速｜跨镜连续，镜头切换不停顿，仅按原标点自然换气。"
        self.assertHas(validator.validate_voice_pacing(source, two_shot_monologue(unknown), 15), "未知连续口播语速档", "ERROR")
        outside = "连续口播：陈默OS｜13.0-16.0秒｜短剧常速｜跨镜连续，镜头切换不停顿，仅按原标点自然换气。"
        self.assertHas(validator.validate_voice_pacing(source, two_shot_monologue(outside), 15), "超出本块", "ERROR")


if __name__ == "__main__":
    unittest.main()
