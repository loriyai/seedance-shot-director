#!/usr/bin/env python3
"""Compile one shot plan into a self-contained prompt, ledger and hard-check report."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import re
import sys

from project_state import ProjectState, digest
from validate_dialogue_and_timeline import (validate, validate_structure, validate_voice_pacing,
    VOICE_PROFILES, Diagnostic,
    extract_output_dialogue, canonical_speaker, validate_sound_arrangement_layout,
    source_backed_speech_boundary, speaker_parts, HIDDEN_CUT, ACTION_CAMERA_HIDDEN_CUT)


V3_REVIEW_CHECKS = (
    'character_headers', 'sound_header', 'action_provenance',
    'shot_count', 'shot_duration', 'dialogue_boundaries', 'spacetime_boundaries',
    'hidden_cuts', 'effects_provenance',
)
V5_SEMANTIC_CHECKS = (
    'source_coverage', 'action_causality', 'spatial_continuity',
    'visual_readability', 'sound_source_semantics',
)
DEFAULT_VOICE_PROFILE = '短剧常速'
DEFAULT_VOICE_PAUSE = 0.2
MAX_SHOT_SECONDS = 5.0
SPEECH_SPLIT_PUNCTUATION = frozenset('，、；：。！？…,.!?;:')
SPEECH_BOUNDARY_FORBIDDEN_ADJACENT = frozenset('“”‘’「」『』（）()【】[]《》<>—-')
STAGE_TOKEN = re.compile(r'[\u3400-\u9fffA-Za-z0-9·_-]{1,16}')
CHARACTER_NAME_FORBIDDEN = re.compile(r'[，,；;：:、。！？!?（）()\[\]【】《》<>｜|@]')

# 智能体模板的抬头：风格选项原文 + 中文质感 + 英文质感 + 禁止项。
STYLE_VISUAL_DEFAULT = ('UE5光线追踪影视级写实渲染,高精度粒子流体特效,电影级画质,运镜丝滑,层次构图,'
                        '景深变化,画面细节饱满,光影层次清晰,明暗对比强烈,空间感强')
STYLE_QUALITY_EN_DEFAULT = (
    'Ultra-high definition, natural skin tone, delicate hair strands and fabric textures, naturally focused '
    'gaze, natural blinking, visible pores and fine lines. Subtle micro-expressions, slight trembling of '
    'eyelashes, breathing chest movement, clothing fluttering gently in the wind, composed and graceful '
    'movements;With ambient sound effects')
NEGATIVES_DEFAULT = (
    'no duplicates, no clones, passersby face mismatch with protagonist, no abrupt ending, avoid AI feel, '
    'stiff features, hand clipping, blurry, lip sync mismatch, plastic skin, uncanny valley, fake '
    'expressions, jitter, flicker, no BGM, no subtitles, no text')
SHOT_SIZE_LADDER = ('大远景', '远景', '全景', '中近景', '中景', '近景', '特写', '大特写')
SHOT_SIZE_PATTERN = re.compile(
    r'([\u4e00-\u9fffA-Za-z0-9·、；]{1,16})的(?:' + '|'.join(SHOT_SIZE_LADDER) + r')')
SHOT_SIZE_WORD = re.compile('|'.join(SHOT_SIZE_LADDER))
MOVEMENT_PATTERN = re.compile(
    r'固定机位|手持|缓推|急推|推近|推进|拉远|拉至|拉出|跟拍|跟随|横移|平移|前移|后移|上移|下移|'
    r'移焦|升降|摇摄|摇镜|环绕|上升|下降|俯冲')
TIME_LABEL_HINTS = (('黄昏', '黄昏'), ('傍晚', '傍晚'), ('清晨', '清晨'), ('凌晨', '凌晨'),
                    ('夜晚', '夜晚'), ('夜', '夜晚'), ('night', '夜晚'), ('dusk', '黄昏'),
                    ('evening', '傍晚'), ('morning', '清晨'), ('dawn', '清晨'),
                    ('白天', '白天'), ('日间', '白天'), ('day', '白天'))


def strip_end(text):
    return re.sub(r'[。；;，,、\s]+$', '', text)


def shot_size_of(shot):
    """返回（渲染用景别文本，是否为主体强绑定）。"""
    if 'shot_size' in shot:
        value = line(shot['shot_size'])
        return value, bool(SHOT_SIZE_PATTERN.search(value))
    match = SHOT_SIZE_PATTERN.search(shot['camera'])
    if match:
        return match.group(0), True
    match = SHOT_SIZE_WORD.search(shot['camera'])
    if match:
        return match.group(0), False
    return strip_end(shot['camera']), False


def movement_of(shot):
    if 'movement' in shot:
        return line(shot['movement'])
    match = MOVEMENT_PATTERN.search(shot['camera'])
    return match.group(0) if match else '固定机位'


def time_label_of(block):
    if 'time_label' in block:
        return line(block['time_label'])
    identity = line(block['time_id']).lower()
    for hint, label in TIME_LABEL_HINTS:
        if hint in identity:
            return label
    return '未注明'


def design_paragraph(header, block):
    design = block.get('scene_design')
    if design is None:
        return header['scene'] + '，' + header['atmosphere']
    keys(design, ('lighting', 'tone', 'layering', 'depth_design', 'blocking', 'composition', 'environment'))
    order = ('lighting', 'tone', 'layering', 'depth_design', 'blocking', 'composition', 'environment')
    return '，'.join(line(design[name]) for name in order)


def audio_line(block):
    names = []
    for voice in block['voices']:
        name = speaker_parts(voice['speaker'])[0]
        if name not in names:
            names.append(name)
    return '，'.join(name + '音频' for name in names) if names else '无'


STATIC_MOVEMENT = frozenset(('固定机位', '固定镜头', '固定', '静止机位', '静止'))


def is_static_movement(movement):
    return movement in STATIC_MOVEMENT or '固定' in movement or '静止' in movement


# 智能体散文模板：lead 引导句；lead_static 固定机位专用引导句；lead_soft/react_soft 为文戏替换词。
SLOT_LEAD_1 = {'lead': '画面猝然{t}切入，以{m}确立{sz}。', 'd': '{d}下，', 'end': '。',
               'prefix': '画面中心，', 'react': '，{r}'}
SLOT_LEAD_2 = {'lead': '紧接着光影交错，镜头{m}逼近至{sz}，通过{t}实现视觉衔接。',
               'lead_static': '紧接着光影交错，镜头保持在{sz}，通过{t}实现视觉衔接。',
               'd': '{d}将背景剥离，', 'end': '，', 'prefix': '', 'react': '，引发{r}'}
SLOT_LEAD_3 = {'lead': '视线随之{t}流转，以{m}锁定{sz}。', 'd': '在{d}的烘托中，', 'end': '，',
               'prefix': '', 'react': '，强制使得{r}'}
SLOT_LEAD_4 = {'lead': '随着{t}掠过，机位{m}切换为{sz}。',
               'lead_static': '随着{t}掠过，机位保持为{sz}。', 'd': '{d}引导焦点转移，此时',
               'end': '，', 'prefix': '', 'react': '，周围的{r}'}
SLOT_LEAD_5 = {'lead': '毫无征兆地{t}，镜头{m}捕捉到{sz}。',
               'lead_static': '毫无征兆地{t}，镜头捕捉到{sz}。', 'd': '{d}中，', 'end': '，',
               'prefix': '', 'react': '，强制刻画出{r}'}
SLOT_LEAD_6 = {'lead': '气流激荡间，以{t}带出{m}的{sz}。', 'lead_soft': '片刻静默间，以{t}带出{m}的{sz}。',
               'd': '在{d}的视觉牵引下，', 'end': '，', 'prefix': '', 'react': '，逼得{r}'}
SLOT_LEAD_7 = {'lead': '空间仿佛陷入极其短暂的死寂，{t}后机位{m}定格于{sz}。',
               'lead_static': '空间仿佛陷入极其短暂的死寂，{t}后机位定格于{sz}。',
               'd': '{d}将周遭一切虚化，', 'end': '，', 'prefix': '', 'react': '，强制描写{r}'}
SLOT_LEAD_8 = {'lead': '刹那间{t}撕裂画面，镜头以极具张力的{m}展现{sz}。',
               'lead_soft': '画面在{t}中收紧，镜头以极具张力的{m}展现{sz}。',
               'lead_static': '刹那间{t}切入，镜头以极具张力的构图展现{sz}。', 'd': '{d}中，', 'end': '，',
               'prefix': '', 'react': '，狂暴的能量强制导致{r}', 'react_soft': '，强制导致{r}'}
SLOT_LEAD_9 = {'lead': '余威未散，画面{t}过渡，镜头{m}对准{sz}。',
               'lead_soft': '情绪未散，画面{t}过渡，镜头{m}对准{sz}。',
               'lead_static': '情绪未散，画面{t}过渡，镜头对准{sz}。', 'd': '{d}下，', 'end': '，',
               'prefix': '', 'react': '，周遭{r}'}
SLOT_LEAD_10 = {'lead': '视线借由{t}平缓，{m}带出{sz}。', 'd': '{d}重新交代空间位置，', 'end': '，',
                'prefix': '', 'react': '，强制刻画出{r}'}
SLOT_LEAD_11 = {'lead': '最终，以极其深邃的{t}收束，镜头{m}拉至{sz}。',
                'lead_static': '最终，以极其深邃的{t}收束，镜头停留在{sz}。',
                'd': '{d}构建出完整的闭环空间，', 'end': '，', 'prefix': '', 'react': '，强制描写{r}'}

PROSE_SLOTS = {
    11: (SLOT_LEAD_1, SLOT_LEAD_2, SLOT_LEAD_3, SLOT_LEAD_4, SLOT_LEAD_5, SLOT_LEAD_6,
         SLOT_LEAD_7, SLOT_LEAD_8, SLOT_LEAD_9, SLOT_LEAD_10, SLOT_LEAD_11),
    7: (SLOT_LEAD_1, SLOT_LEAD_2, SLOT_LEAD_3, SLOT_LEAD_4, SLOT_LEAD_6, SLOT_LEAD_8, SLOT_LEAD_11),
    6: (SLOT_LEAD_1, SLOT_LEAD_2, SLOT_LEAD_3, SLOT_LEAD_4, SLOT_LEAD_8, SLOT_LEAD_11),
    5: (SLOT_LEAD_1, SLOT_LEAD_2, SLOT_LEAD_3, SLOT_LEAD_8, SLOT_LEAD_11),
}

# 功能标签只进入后台审计视图，不进入直投正文。
SLOT_LABELS = {
    11: ('建立', '推进', '展开', '对话', '承接', '深入', '高潮前奏', '高潮', '转折', '余波', '收尾'),
    7: ('建立', '推进', '展开', '对话', '承接', '高潮', '收尾'),
    6: ('建立', '推进', '展开', '对话', '高潮', '收尾'),
    5: ('建立', '推进', '展开', '高潮', '收尾'),
}


def shot_label(shot, shot_index, shot_count):
    if 'label' in shot:
        return line(shot['label'])
    table = SLOT_LABELS.get(shot_count) or (SLOT_LABELS[11] if shot_count >= 11 else None)
    if table and shot_index <= len(table):
        return table[shot_index - 1]
    return '未标注'


def prose_slot(shot_count, shot_index):
    table = PROSE_SLOTS.get(shot_count) or (PROSE_SLOTS[11] if shot_count >= 11 else PROSE_SLOTS[5])
    index = shot_index - 1 if shot_count >= 11 else min(shot_index - 1, len(table) - 1)
    return table[index]


def prose_slot_text(slot, key, track, static=False):
    if static and key == 'lead' and 'lead_static' in slot:
        return slot['lead_static']
    if track != '武戏' and key + '_soft' in slot:
        return slot[key + '_soft']
    return slot[key]


def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def keys(data, required, optional=()):
    if not isinstance(data, dict):
        raise ValueError('规划字段必须为对象。')
    missing = set(required) - data.keys()
    unknown = data.keys() - set(required) - set(optional)
    if missing or unknown:
        raise ValueError(f'规划字段缺失 {sorted(missing)}；未知字段 {sorted(unknown)}。')


def line(value):
    if not isinstance(value, str) or not value.strip() or '\n' in value or '\r' in value:
        raise ValueError('制作描述必须为非空单行文字。')
    return value


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('时间必须为有限数值。')
    return f'{value:g}'


def music_header(config):
    choice = config.get('music', 'none')
    if choice == 'none':
        return '无背景配乐'
    if choice == 'source':
        return '仅使用锁定来源明确要求的配乐'
    if choice == 'custom':
        return line(config.get('custom_music', '使用已确认的自定义配乐'))
    raise ValueError('无效配乐配置。')


def render_legacy_characters(value):
    """Keep legacy plans readable without leaking free-form descriptions."""
    value = line(value)
    if value == '无':
        return value
    names = [name.strip() for name in value.split('；')]
    if (not all(names) or any(
            name == '无' or CHARACTER_NAME_FORBIDDEN.search(name) or len(name) > 24
            for name in names)):
        raise ValueError('旧版characters只能写以中文分号分隔的角色名，或写“无”；不得写外貌、阶段或其他说明。')
    return '；'.join(names)


def render_characters(records, shot_count, separator='；'):
    if not isinstance(records, list):
        raise ValueError('V3每块characters必须为人物记录列表；无人场景使用空列表。')
    if not records:
        return '无'
    rendered = []
    for record in records:
        keys(record, ('name',), ('stage', 'asset', 'offscreen', 'first_visible_shot', 'last_visible_shot'))
        name = line(record['name'])
        if name == '无' or CHARACTER_NAME_FORBIDDEN.search(name) or len(name) > 24:
            raise ValueError('人物记录name只写一个人物或群体名称，不写外观、服装或表演描述。')
        if 'stage' in record:
            stage = line(record['stage'])
            if not STAGE_TOKEN.fullmatch(stage):
                raise ValueError('人物stage必须是简短后台阶段标识。')
        if 'asset' in record:
            asset = line(record['asset'])
            if not asset.startswith('@'):
                raise ValueError('人物asset必须是实际提供的@素材名称。')
        offscreen = record.get('offscreen', False)
        if type(offscreen) is not bool:
            raise ValueError('人物offscreen必须为布尔值。')
        visibility = {}
        for field in ('first_visible_shot', 'last_visible_shot'):
            if field in record:
                index = record[field]
                if type(index) is not int or not 1 <= index <= shot_count:
                    raise ValueError('人物首次/最后可见镜头必须是本块镜头范围内的整数。')
                visibility[field] = index
        if offscreen and visibility:
            raise ValueError('全块画外人物不能同时填写首次或最后可见镜头。')
        if not offscreen and visibility:
            first = visibility.get('first_visible_shot', 1)
            last = visibility.get('last_visible_shot', shot_count)
            if first > last:
                raise ValueError('人物首次可见镜头不能晚于最后可见镜头。')
        rendered.append(name)
    return separator.join(rendered)


def validate_effects(effects, shot_beats):
    if not isinstance(effects, list):
        raise ValueError('V3每镜effects必须为列表；确无声音时使用空列表或唯一字符串“静默”。')
    if not effects or effects == ['静默']:
        return ['静默']
    if any(not isinstance(effect, dict) for effect in effects):
        raise ValueError('effects中的实际声音必须使用结构化来源记录；仅“静默”可使用字符串简写。')
    rendered = []
    for effect in effects:
        if effect.get('type') == '静默':
            keys(effect, ('type', 'text'), ('provenance', 'basis'))
            if len(effects) != 1 or line(effect['text']) != '静默':
                raise ValueError('静默必须是本镜唯一effect，text固定为“静默”。')
            if ('provenance' in effect) != ('basis' in effect):
                raise ValueError('静默不需要来源；若兼容旧规划填写provenance与basis，必须同时提供。')
            if 'provenance' in effect:
                if effect['provenance'] not in ('source', 'visible_action', 'scene_ambient', 'user'):
                    raise ValueError('环境音效provenance无效。')
                basis = effect['basis']
                if effect['provenance'] in ('source', 'visible_action'):
                    if not isinstance(basis, list) or not basis or any(item not in shot_beats for item in basis):
                        raise ValueError('来源声或可见动作声的basis必须引用本镜来源节拍。')
                elif basis not in ('scene', 'user'):
                    raise ValueError('场景底声或用户指定声音的basis必须是scene或user。')
            return ['静默']
        keys(effect, ('type', 'text', 'provenance', 'basis'))
        if effect['type'] not in ('环境声', '动作声', '画外声', '静默'):
            raise ValueError('环境音效type只能为环境声、动作声、画外声或静默。')
        if effect['provenance'] not in ('source', 'visible_action', 'scene_ambient', 'user'):
            raise ValueError('环境音效provenance无效。')
        text = line(effect['text'])
        basis = effect['basis']
        if effect['provenance'] in ('source', 'visible_action'):
            if not isinstance(basis, list) or not basis or any(item not in shot_beats for item in basis):
                raise ValueError('来源声或可见动作声的basis必须引用本镜来源节拍。')
        elif basis not in ('scene', 'user'):
            raise ValueError('场景底声或用户指定声音的basis必须是scene或user。')
        rendered.append(text)
    return rendered


def validate_ambient_effects(effects):
    """Validate reusable block ambience without pretending it belongs to a shot beat."""
    if effects is None:
        return []
    if not isinstance(effects, list):
        raise ValueError('V5每块ambient_effects必须为列表。')
    rendered = []
    for effect in effects:
        if not isinstance(effect, dict):
            raise ValueError('ambient_effects必须使用结构化来源记录。')
        keys(effect, ('type', 'text', 'provenance', 'basis'))
        if effect['type'] not in ('环境声', '画外声'):
            raise ValueError('ambient_effects只能记录稳定环境声或用户指定的画外声。')
        if effect['provenance'] not in ('scene_ambient', 'user'):
            raise ValueError('ambient_effects只能使用scene_ambient或user来源。')
        expected_basis = 'scene' if effect['provenance'] == 'scene_ambient' else 'user'
        if effect['basis'] != expected_basis:
            raise ValueError('ambient_effects的basis必须与来源一致。')
        rendered.append(line(effect['text']))
    return rendered


def explicit_silence(effects):
    if effects == ['静默']:
        return True
    return (isinstance(effects, list) and len(effects) == 1
            and isinstance(effects[0], dict)
            and effects[0].get('type') == '静默'
            and effects[0].get('text') == '静默')


def warning_groups(diagnostics):
    """Collapse repeated mechanical warnings into stable review categories."""
    groups = {}
    for index, diagnostic in enumerate(diagnostics):
        if diagnostic.level != 'WARN':
            continue
        message = diagnostic.message
        if '空格' in message:
            category = 'dialogue_spacing'
        elif any(token in message for token in ('台词', '对白', '口播', '语速', '话轮', '停顿')):
            category = 'dialogue_delivery'
        elif any(token in message for token in ('摄影', '切镜', '机位', '景别', '构图', '景深', '光照')):
            category = 'camera_continuity'
        elif any(token in message for token in ('时空', '场景', '时间跨越', '转场')):
            category = 'spacetime_continuity'
        elif any(token in message for token in ('音效', '声音', '配乐')):
            category = 'sound_semantics'
        else:
            category = 'other'
        groups.setdefault(category, []).append(index)
    return groups


def beat_evidence(plan, beat_ids):
    """把镜头引用的节拍ID还原为锁定来源中的原句。"""
    index = {beat.get('id'): beat.get('evidence', '') for beat in plan.get('beats', [])}
    return [index.get(beat_id, '') for beat_id in beat_ids]


def background_clause(block):
    """取块级设计中的背景层短语，用于同场景参照物一致性核对。"""
    design = block.get('scene_design')
    if not isinstance(design, dict):
        return ''
    text = design.get('layering', '') or design.get('environment', '')
    for marker in ('后景是', '背景是', '远景是'):
        if marker in text:
            tail = text.split(marker, 1)[1]
            for separator in ('，', '。', '；'):
                tail = tail.split(separator, 1)[0]
            return tail.strip()
    return ''


def longest_common_substring(left, right):
    """返回两段文字的最长公共子串，用于机械核对措辞复用。"""
    best = ''
    for start in range(len(left)):
        for end in range(start + len(best) + 1, len(left) + 1):
            if left[start:end] in right:
                best = left[start:end]
            else:
                break
    return best


def shot_language_diagnostics(plan):
    """镜头语言契约的警告级检查：主体强绑定、环境持续状态、切镜方式与块级设计。"""
    diagnostics = []
    if plan.get('schema_version', 1) < 5:
        return diagnostics
    for index, block in enumerate(plan['blocks'], 1):
        label = f'{index:02d}'
        design = block.get('scene_design')
        if design is None:
            diagnostics.append(Diagnostic(
                'WARN',
                '本块缺少块级设计（光照、光影色彩、层次构图、景深设计、人物站位、构图原则、场景环境），当前按场景与氛围兜底。',
                label))
        if abs(block['duration'] - 30) < 1e-6 and len(block['shots']) != 11:
            diagnostics.append(Diagnostic(
                'WARN', f'30秒原生块默认11镜，本块为{len(block["shots"])}镜；偏离时须有原文与观看依据。',
                label))
        missing_environment = []
        frontal = []
        for shot_index, shot in enumerate(block['shots'], 1):
            if not isinstance(shot, dict):
                continue
            _size, bound = shot_size_of(shot)
            if not bound:
                diagnostics.append(Diagnostic(
                    'WARN', '景别未绑定具名主体，建议写成“角色名的中景”这类主体强绑定景别。',
                    label, str(shot_index)))
            if 'environment' not in shot and 'environment' not in (design or {}):
                missing_environment.append(str(shot_index))
            if shot_index > 1 and 'transition' not in shot:
                diagnostics.append(Diagnostic(
                    'WARN', '同块第二镜起建议写明进入本镜的切镜方式（转场），当前按硬切兜底。',
                    label, str(shot_index)))
            camera = shot.get('camera', '')
            action = shot.get('action', '')
            if '直视镜头' in camera or '正对镜头' in camera:
                diagnostics.append(Diagnostic(
                    'ERROR', '禁止播报式正脸：摄影机不得写成直视镜头或正对镜头，除来源明确要求打破第四面墙。',
                    label, str(shot_index)))
            if '正面' in camera and '过肩' not in camera and '侧' not in camera:
                frontal.append(str(shot_index))
            if '转身' in action and not any(mark in action for mark in ('背对', '侧对', '画左', '画右')):
                diagnostics.append(Diagnostic(
                    'WARN', '转身写了方向不明的说法，请用画面可判定方位（转向画左、转向画右或背对镜头）。',
                    label, str(shot_index)))
            if '面对' in action:
                diagnostics.append(Diagnostic(
                    'WARN', '动作含世界方位词“面对”，请改写为画面可判定方位，避免模型把人物转成正对镜头。',
                    label, str(shot_index)))
            evidence = ' '.join(beat_evidence(plan, shot.get('beats', [])))
            if shot['end'] - shot['start'] > 2 and any(word in evidence for word in ('一群', '鱼贯', '一队', '人马')):
                diagnostics.append(Diagnostic(
                    'WARN', '群体入场镜超过2秒：请写清从哪里进、几步内停、停在何处，或直接以已在场站开的构图起手。',
                    label, str(shot_index)))
            if '看看画像' in evidence and '看看陈默' in evidence and '同框' not in camera + shot.get('shot_size', ''):
                diagnostics.append(Diagnostic(
                    'WARN', '比对型节拍（看画像再看人）需要同框双主体构图，当前镜头未写同框，模型无法呈现对照。',
                    label, str(shot_index)))
            if shot.get('speech'):
                actors = {record.get('name') for record in block.get('characters', [])
                          if record.get('name') and record.get('name') in action}
                if len(actors) >= 3:
                    diagnostics.append(Diagnostic(
                        'WARN', '同一镜内出现三个及以上人物动作并带台词：一镜只保留一个主要表演目标，其余动作拆到相邻镜。',
                        label, str(shot_index)))
        if missing_environment:
            diagnostics.append(Diagnostic(
                'WARN', '有镜头缺少环境持续状态，正文会省略该分句；建议补写可见的空气介质或背景持续动态。',
                label, '、'.join(missing_environment)))
        limit = 2 if abs(block['duration'] - 15) < 1e-6 else (4 if block['duration'] > 15 else 1)
        if len(frontal) > limit:
            diagnostics.append(Diagnostic(
                'WARN', f'块内正面镜{len(frontal)}个超过上限{limit}：情绪爆发、对白拉扯与喜剧反差请改用侧前方、仰角或过肩机位。',
                label, '、'.join(frontal)))
    for index in range(1, len(plan['blocks'])):
        previous, current = plan['blocks'][index - 1], plan['blocks'][index]
        if previous.get('scene_id') != current.get('scene_id'):
            continue
        label = f'{index + 1:02d}'
        shared = longest_common_substring(background_clause(previous), background_clause(current))
        if len(shared) < 4:
            diagnostics.append(Diagnostic(
                'WARN', '同场景相邻块的背景参照物措辞不一致：请复用同一份场景参照物词组，背景层逐字一致，避免个别块长出新的树林、楼阁等景物。',
                label, '1'))
        if previous.get('time_id') == current.get('time_id') and not current.get('entry'):
            first_action = (current.get('shots') or [{}])[0].get('action', '')
            if not any(mark in first_action for mark in ('仍', '继续', '保持', '照旧', '依然', '还没', '接着', '未动')):
                diagnostics.append(Diagnostic(
                    'WARN', '连续块首镜未复述上一块出口状态（姿态、朝向、手部道具）：请在首镜写明“仍蹲着”这类可见承接。',
                    label, '1'))
    return diagnostics


def plan_stats(plan, prompt):
    """输出镜头层的可核对统计，供语义复核取证。"""
    histogram, closeups, near_shots, repeats, per_block = {}, 0, 0, 0, []
    for block in plan['blocks']:
        sizes = []
        for shot in block['shots']:
            size, _bound = shot_size_of(shot)
            word = SHOT_SIZE_WORD.search(size)
            label = word.group(0) if word else '未标注'
            sizes.append(label)
            histogram[label] = histogram.get(label, 0) + 1
            if label in ('特写', '大特写'):
                closeups += 1
            if label in ('近景', '中近景'):
                near_shots += 1
        for first, second in zip(sizes, sizes[1:]):
            if first == second:
                repeats += 1
        per_block.append({'block': len(per_block) + 1, 'shots': len(block['shots']),
                          'duration': block['duration'], 'shot_sizes': sizes})
    return {'total_shots': sum(item['shots'] for item in per_block),
            'blocks': per_block,
            'shot_size_histogram': histogram,
            'closeup_shots': closeups,
            'near_shots': near_shots,
            'adjacent_same_size_pairs': repeats,
            'silent_shots': prompt.count('本镜静默')}


def dialogue_split_boundary(text, index):
    """A split belongs after a complete run of natural speech punctuation."""
    if index in (0, len(text)):
        return True
    previous = text[index - 1]
    current = text[index]
    if previous in SPEECH_BOUNDARY_FORBIDDEN_ADJACENT or current in SPEECH_BOUNDARY_FORBIDDEN_ADJACENT:
        return False
    if previous not in SPEECH_SPLIT_PUNCTUATION or current in SPEECH_SPLIT_PUNCTUATION:
        return False
    if previous in '.,:' and index >= 2 and text[index - 2].isalnum() and current.isalnum():
        return False
    return True


def boundary_exists_in_source(source, text, index, speaker=None, kind=None):
    """Confirm a real or newline-normalised split belongs to one locked utterance."""
    return source_backed_speech_boundary(source, text, index, speaker, kind)


def spacetime_identity(block):
    """Keep place and narrative time explicit so same-place time jumps cannot be hidden."""
    return block.get('scene_id'), block.get('time_id')


def spacetime_changed(plan, left_index, right_index):
    return spacetime_identity(plan['blocks'][left_index]) != spacetime_identity(plan['blocks'][right_index])


def boundary_context_identity(plan, side):
    context = plan.get('boundary_context')
    if context is None:
        return None
    keys(context, ('incoming', 'outgoing'))
    adjacent = context[side]
    if adjacent is None:
        return None
    keys(adjacent, ('scene_id', 'time_id'))
    return line(adjacent['scene_id']), line(adjacent['time_id'])


def spacetime_changed_before(plan, index):
    if index > 0:
        return spacetime_changed(plan, index-1, index)
    incoming = boundary_context_identity(plan, 'incoming')
    return incoming is not None and incoming != spacetime_identity(plan['blocks'][0])


def spacetime_changed_after(plan, index):
    if index + 1 < len(plan['blocks']):
        return spacetime_changed(plan, index, index+1)
    outgoing = boundary_context_identity(plan, 'outgoing')
    return outgoing is not None and outgoing != spacetime_identity(plan['blocks'][-1])


def has_successor_context(plan, index):
    return index + 1 < len(plan['blocks']) or boundary_context_identity(plan, 'outgoing') is not None


def default_ending(plan, index, config):
    delivery = config.get('delivery', 'auto')
    if delivery not in ('auto', 'standalone', 'continuous'):
        raise ValueError('无效交付模式。')
    if delivery == 'standalone':
        return '独立收束'
    if has_successor_context(plan, index) and (delivery == 'continuous' or not spacetime_changed_after(plan, index)):
        return '连续剪辑'
    return '独立收束'


def block_handles(plan, index, config):
    block = plan['blocks'][index]
    changed_before = spacetime_changed_before(plan, index)
    changed_after = spacetime_changed_after(plan, index)
    ending = block.get('ending', default_ending(plan, index, config))
    head = max(block.get('silent_head', 0), 1 if changed_before else 0)
    tail = max(block.get('silent_tail', 0.5 if ending == '独立收束' else 0), 1 if changed_after else 0)
    return head, tail, ending


def render_style_line(header):
    """抬头第二行：技能风格选项原文 + 中文执行质感 + 英文质感块。"""
    return ';'.join((
        line(header['style']),
        line(header.get('visual_quality', STYLE_VISUAL_DEFAULT)),
        line(header.get('render_quality_en', STYLE_QUALITY_EN_DEFAULT)),
    )) + '。'


def prose_shot_line(shot, shot_index, shot_count, track, block_environment, transition,
                    dialogue, effects, screen_text=None):
    """按智能体模板把一镜拼成一段连续提示词。"""
    slot = prose_slot(shot_count, shot_index)
    size, _bound = shot_size_of(shot)
    movement = movement_of(shot)
    static = is_static_movement(movement)
    depth = line(shot['depth']) if 'depth' in shot else None
    environment = line(shot['environment']) if 'environment' in shot else block_environment
    reaction = strip_end(line(shot['reaction'])) if 'reaction' in shot else None
    action = strip_end(line(shot['action']))
    lead = prose_slot_text(slot, 'lead', track, static)
    body = lead.format(t=transition, m='固定机位' if static else movement, sz=size)
    if environment:
        body += (slot['d'].format(d=depth) if depth else '') + strip_end(environment) + slot['end']
    elif depth:
        body += slot['d'].format(d=depth)
    body += slot['prefix'] + action
    if screen_text:
        visible = line(screen_text).replace('【', '').replace('】', '')
        body += '，画面文字：【' + visible + '】'
    if reaction:
        body += prose_slot_text(slot, 'react', track, static).format(r=reaction)
    body += '。'
    if dialogue:
        body += '，'.join(dialogue)
    if effects:
        fx = '、'.join(strip_end(effect) for effect in effects)
        body += ('，伴随着' + fx + '；') if dialogue else ('伴随着' + fx + '；')
    else:
        body += '；' if dialogue else '本镜静默；'
    return f'[{number(shot["start"])}秒-{number(shot["end"])}秒] ' + body


def render(plan, source, config, *, audit=False):
    keys(plan, ('schema_version', 'source_version', 'source_sha256', 'config_sha256', 'defaults', 'beats', 'blocks'), ('boundary_context',))
    if plan['schema_version'] not in (1, 2, 3, 4, 5):
        raise ValueError('不支持的规划版本。')
    if plan['schema_version'] >= 4 and 'boundary_context' not in plan:
        raise ValueError('V4+规划必须提供boundary_context，明确本批前后是否存在相邻时空。')
    legacy = plan['schema_version'] < 3
    compact = plan['schema_version'] >= 5
    headers = (('style', 'characters', 'scene', 'atmosphere', 'sound') if legacy else
               ('style', 'scene', 'atmosphere'))
    header_optional = (('assets',) if legacy else
                       ('assets', 'visual_quality', 'render_quality_en', 'negatives'))
    keys(plan['defaults'], headers, header_optional)
    for value in plan['defaults'].values():
        line(value)
    if not isinstance(plan['beats'], list) or not plan['beats']:
        raise ValueError('规划需要来源节拍。')
    beats = set()
    for beat in plan['beats']:
        keys(beat, ('id', 'evidence'), ('timing', 'basis'))
        identifier = line(beat['id'])
        if identifier in beats or line(beat['evidence']) not in source:
            raise ValueError('节拍ID重复或来源摘句不在锁定原文中。')
        if 'timing' in beat and beat['timing'] not in ('parallel', 'serial'):
            raise ValueError('动作时序只能为parallel或serial。')
        if beat.get('timing') == 'serial':
            line(beat.get('basis'))
        beats.add(identifier)
    if not isinstance(plan['blocks'], list) or not plan['blocks']:
        raise ValueError('规划需要生成块。')
    output, used_beats = [], set()
    for block_index, block in enumerate(plan['blocks'], 1):
        if legacy:
            required = ('duration', 'entry', 'exit', 'voices', 'shots')
        elif compact:
            required = ('duration', 'characters', 'voices', 'shots', 'scene_id', 'time_id')
        else:
            required = ('duration', 'entry', 'exit', 'characters', 'voices', 'shots', 'scene_id', 'time_id')
        optional = ('header', 'ending', 'silent_tail', 'silent_head', 'scene_id', 'time_id', 'notes')
        if compact:
            optional += ('entry', 'exit', 'ambient_effects', 'time_label', 'weather',
                         'scene_design', 'track')
        keys(block, required, optional)
        if plan['schema_version'] >= 2:
            line(block.get('scene_id'))
        if not legacy:
            line(block.get('time_id'))
        if not isinstance(block['voices'], list) or not isinstance(block['shots'], list):
            raise ValueError('声音和镜头必须为列表。')
        if not block['shots']:
            raise ValueError('生成块至少需要一个镜头。')
        entry = line(block.get('entry', block['shots'][0].get('action', '')))
        exit_state = line(block.get('exit', block['shots'][-1].get('action', '')))
        header = {**plan['defaults'], **block.get('header', {})}
        keys(header, headers, header_optional)
        for value in header.values():
            line(value)
        head, tail, ending = block_handles(plan, block_index-1, config)
        for handle in (head, tail):
            number(handle)
            if handle < 0:
                raise ValueError('无口播衔接时段不能为负。')
        if head + tail >= block['duration']:
            raise ValueError('首尾衔接时段不能占满生成块。')
        if ending not in ('独立收束', '连续剪辑', '剧情硬切'):
            raise ValueError('无效收尾方式。')
        aspect = line(config.get('aspect_ratio', '16:9'))
        character_line = (render_legacy_characters(header['characters']) if legacy
                          else render_characters(block['characters'], len(block['shots'])))
        sound_line = header['sound'] if legacy else music_header(config)
        prose = compact and not audit
        if prose:
            block_track = block.get('track', '文戏')
            if block_track not in ('文戏', '武戏'):
                raise ValueError('生成块track只能为“文戏”或“武戏”。')
            block_environment = (line(block['scene_design']['environment'])
                                 if isinstance(block.get('scene_design'), dict) else header['atmosphere'])
            lines = [f'生成块 {block_index:02d}｜{number(block["duration"])}秒｜{aspect}',
                     render_style_line(header),
                     '禁止项：' + line(header.get('negatives', NEGATIVES_DEFAULT)) + '。']
            if config.get('music', 'none') != 'none':
                lines.append('配乐：' + sound_line + '。')
            lines += [
                '人物：' + render_characters(block['characters'], len(block['shots']), '，') + '；',
                '场景：' + header['scene'] + '；时间：' + time_label_of(block) + '；天气：'
                + line(block.get('weather', '无')) + '；',
                '音频：' + audio_line(block) + '；',
                design_paragraph(header, block) + '。',
            ]
        else:
            block_track = '文戏'
            block_environment = header['atmosphere']
            lines = [f'生成块 {block_index:02d}｜{number(block["duration"])}秒｜{aspect}',
                     header['style'] + '；' + sound_line,
                     '人物：' + character_line, '场景：' + header['scene'],
                     '本块氛围与站位：' + header['atmosphere']]
            if audit:
                lines.append('收尾方式：' + ending)
        if 'assets' in header:
            lines.append('素材绑定：' + header['assets'])
        if abs(block['duration'] - 15) < 1e-6 and not 5 <= len(block['shots']) <= 7:
            raise ValueError('完整15秒块必须有5-7镜（默认5镜），不接受其他镜数。')
        if block['duration'] < 15-1e-6:
            minimum_shots = max(1, math.ceil((block['duration']-1e-6) / MAX_SHOT_SECONDS))
            if not minimum_shots <= len(block['shots']) <= 5:
                raise ValueError(f'{number(block["duration"])}秒短块必须有{minimum_shots}-5镜，并继续满足单镜5秒上限。')
        ambient_effects = validate_ambient_effects(block.get('ambient_effects')) if compact else []
        voices, consumed = {}, {}
        for voice in block['voices']:
            voice_required = ('id', 'speaker', 'kind', 'text', 'start', 'end') if compact else ('id', 'speaker', 'kind', 'text', 'start', 'end', 'pause', 'profile')
            keys(voice, voice_required, ('overlap', 'tone', 'pause', 'profile'))
            identifier = line(voice['id'])
            if identifier in voices or any(c in identifier for c in '|｜'):
                raise ValueError('话轮ID重复或包含分隔符。')
            speaker = line(voice['speaker'])
            if any(c in speaker for c in '|｜'):
                raise ValueError('说话人不能包含分隔符。')
            profile = voice.get('profile', DEFAULT_VOICE_PROFILE)
            if voice['kind'] not in ('对白', 'OS', '旁白') or profile not in VOICE_PROFILES:
                raise ValueError('无效声音类型或语速档。')
            line(voice['text'])
            pause_value = voice.get('pause', DEFAULT_VOICE_PAUSE)
            pause = '待核' if pause_value is None else number(pause_value) + '秒'
            overlap = '重叠：' + line(voice['overlap']) if 'overlap' in voice else '连续'
            if 'tone' in voice:
                tone = line(voice['tone'])
                if any(mark in tone for mark in ('的语气', '说', 'OS', '旁白')):
                    raise ValueError(
                        '语气字段不得包含说话方式（说／内心OS／旁白）或“以……的语气”写法；'
                        '说话方式只能由声音类型决定，语气只写可听情绪。')
            if audit:
                lines.append(f'口播段：{identifier}｜{speaker}｜{voice["kind"]}｜{number(voice["start"])}-{number(voice["end"])}秒｜{profile}｜停顿{pause}｜{overlap}')
            voices[identifier], consumed[identifier] = voice, 0
        for shot_index, shot in enumerate(block['shots'], 1):
            if legacy:
                shot_required = ('start', 'end', 'beats', 'action', 'camera')
            elif compact:
                shot_required = ('start', 'end', 'beats', 'action', 'camera')
            else:
                shot_required = ('start', 'end', 'beats', 'action_basis', 'action', 'camera', 'effects')
            keys(shot, shot_required, ('speech', 'performance', 'sound', 'effects', 'screen_text',
                                       'transition', 'notes', 'shot_size', 'movement', 'depth',
                                       'reaction', 'environment', 'label'))
            if plan['schema_version'] == 2 and (not isinstance(shot.get('effects'), list) or not shot['effects']):
                raise ValueError('每镜需要非空effects列表，逐项列出场景环境声与动作声；确无声音则明确静默。')
            if not isinstance(shot['beats'], list) or not shot['beats'] or any(b not in beats for b in shot['beats']):
                raise ValueError('镜头必须映射到已登记来源节拍。')
            if not legacy:
                action_basis = shot.get('action_basis', shot['beats'])
                if (not isinstance(action_basis, list) or not action_basis or
                        any(item not in shot['beats'] for item in action_basis)):
                    raise ValueError('每镜action_basis必须引用本镜beats，不能用无来源动作填时长。')
                if HIDDEN_CUT.search(shot['camera']):
                    raise ValueError('一个编号只能是一镜；camera含隐藏切镜词，请拆为独立镜头。')
                if ACTION_CAMERA_HIDDEN_CUT.search(shot['action']):
                    raise ValueError('一个编号只能是一镜；action含明确摄影切镜语境，请拆为独立镜头。')
            if shot['end'] - shot['start'] > MAX_SHOT_SECONDS:
                raise ValueError('任何单镜最长不得超过5秒。')
            used_beats.update(shot['beats'])
            if not prose:
                lines += ['', f'[镜头{shot_index}]', f'时间区间：{number(shot["start"])}-{number(shot["end"])}秒。',
                          '画面与动作：' + line(shot['action']), '摄影机与构图：' + line(shot['camera'])]
                for field, label in (('performance', '表演'), ('screen_text', '画面文字'), ('transition', '衔接')):
                    if field in shot:
                        lines.append(label + '：' + line(shot[field]))
                if audit:
                    lines.append('功能标签：' + shot_label(shot, shot_index, len(block['shots'])))
            if not isinstance(shot.get('speech', []), list):
                raise ValueError('镜头台词必须为列表。')
            sound_arrangement = []
            changed_before = spacetime_changed_before(plan, block_index-1)
            if shot_index == 1 and changed_before and head:
                sound_arrangement.append(
                    f'0-{number(head)}秒无口播，仅保留可用于后期衔接的连续画面；环境与动作声可持续'
                )
            if shot_index == len(block['shots']):
                if tail:
                    sound_arrangement.append(
                        f'{number(block["duration"]-tail)}-{number(block["duration"])}秒无口播，'
                        '仅保留本镜动作或状态的连续画面，不定格'
                    )
                elif not shot.get('speech'):
                    sound_arrangement.append('本镜无口播，仅保留环境与动作声与连续画面')
                else:
                    sound_arrangement.append('本镜台词按来源合法标点自然连贯，不另拆分或增加停顿')
            if sound_arrangement and not audit and not prose:
                lines.append('声音安排：' + '；'.join(sound_arrangement) + '。')
            shot_dialogue = []
            for fragment in shot.get('speech', []):
                keys(fragment, ('voice',), ('span',))
                identifier = fragment['voice']
                if identifier not in voices:
                    raise ValueError('镜头引用了未声明话轮。')
                voice = voices[identifier]
                span = fragment.get('span', [0, len(voice['text'])])
                if not isinstance(span, list) or len(span) != 2 or any(type(n) is not int for n in span):
                    raise ValueError('话轮片段需提供整数[start,end]。')
                start, end = span
                if start != consumed[identifier] or not start < end <= len(voice['text']):
                    raise ValueError('话轮片段遗漏、重复、倒序或越界。')
                if ((start and (not dialogue_split_boundary(voice['text'], start) or
                                not boundary_exists_in_source(source, voice['text'], start,
                                                              voice['speaker'], voice['kind']))) or
                        (end < len(voice['text']) and (not dialogue_split_boundary(voice['text'], end) or
                                                      not boundary_exists_in_source(source, voice['text'], end,
                                                                                    voice['speaker'], voice['kind'])))):
                    raise ValueError('台词只能在原文已有标点或可核实的换行规范化逗号之后拆分，禁止把其他连贯词句拆到两个镜头。')
                if audit:
                    lines.append(f'台词：{identifier}｜{voice["speaker"]}｜{voice["kind"]}：“{voice["text"][start:end]}”')
                else:
                    verb = {'对白': '说', 'OS': '内心OS', '旁白': '旁白'}[voice['kind']]
                    delivery = voice['speaker'] + voice.get('tone', '') + verb
                    spoken = f'{delivery}：“{voice["text"][start:end]}”'
                    shot_dialogue.append(spoken)
                    if not prose:
                        lines.append(f'台词：{spoken}')
                consumed[identifier] = end
            if not audit:
                if legacy:
                    effects = shot.get('effects', [shot.get('sound', '无明确环境音效')])
                else:
                    local_effects = validate_effects(shot.get('effects', []), shot['beats'])
                    if compact and ambient_effects:
                        if explicit_silence(shot.get('effects')):
                            raise ValueError('本镜显式静默与本块ambient_effects冲突。')
                        effects = ambient_effects + ([] if local_effects == ['静默'] else local_effects)
                    else:
                        effects = local_effects
                if prose:
                    if effects == ['静默']:
                        effect_texts = []
                    else:
                        effect_texts = [line(effect).rstrip('；。') for effect in effects]
                    lines.append('')
                    lines.append(prose_shot_line(
                        shot, shot_index, len(block['shots']), block_track, block_environment,
                        line(shot.get('transition', '硬切')), shot_dialogue, effect_texts,
                        shot.get('screen_text')))
                    if sound_arrangement:
                        lines.append('声音安排：' + '；'.join(sound_arrangement) + '。')
                else:
                    lines.append('环境音效：' + '；'.join(line(effect).rstrip('；。') for effect in effects) + '。')
        if any(consumed[v] != len(voices[v]['text']) for v in voices):
            raise ValueError('声明的话轮未完整分配到镜头。')
        if audit and tail:
            lines.append(f'无对白尾帧：最后{tail:g}秒无对白，' + exit_state)
        output.append('\n'.join(lines))
    if beats != used_beats:
        raise ValueError('存在未映射到镜头的来源节拍。')
    return '\n\n'.join(output) + '\n'


def validate_plan_timing(plan, config):
    diagnostics = []
    for index, block in enumerate(plan['blocks']):
        label = f'{index+1:02d}'
        head, tail, _ = block_handles(plan, index, config)
        voices = {v['id']: v for v in block['voices']}
        if block['shots'] and (head > block['shots'][0]['end'] or tail > block['duration']-block['shots'][-1]['start']):
            diagnostics.append(Diagnostic('ERROR', '首尾无口播衔接时段必须容纳在首镜和末镜内。', label))
        for voice in voices.values():
            if voice['start'] < head-1e-6 or voice['end'] > block['duration']-tail+1e-6:
                diagnostics.append(Diagnostic('ERROR', '口播占用跨场景或收束的无口播时段。', label))
        for shot_index, shot in enumerate(block['shots'], 1):
            if shot['end'] - shot['start'] > MAX_SHOT_SECONDS:
                diagnostics.append(Diagnostic('ERROR', '任何单镜最长不得超过5秒。', label, str(shot_index)))
    return diagnostics


def check_block(project, segment, plan, block_number=None, *, final_block=False):
    """Read-only local check of one drafted V5 block; full-source coverage stays with compile."""
    store = ProjectState(Path(project))
    source_record = store.source(segment)
    config = store.read()['config']
    if plan.get('schema_version') != 5:
        raise ValueError('check-block只接受V5规划。')
    keys(plan, ('schema_version', 'source_version', 'source_sha256', 'config_sha256',
                'boundary_context', 'defaults', 'beats', 'blocks'))
    if plan['source_version'] != source_record['version'] or plan['source_sha256'] != source_record['sha256']:
        raise ValueError('规划来源已变化，请更新受影响规划。')
    if plan['config_sha256'] != digest(canonical(config)):
        raise ValueError('制作配置已变化，请复核受影响规划。')
    blocks = plan['blocks']
    if not isinstance(blocks, list) or not blocks:
        raise ValueError('规划需要至少一个已起草生成块。')
    if block_number is None:
        block_number = len(blocks)
    if type(block_number) is not int or not 1 <= block_number <= len(blocks):
        raise ValueError('检查块编号超出当前规划。')
    index = block_number - 1
    boundary_context_identity(plan, 'incoming')
    declared_outgoing = boundary_context_identity(plan, 'outgoing')
    if final_block and (index != len(blocks)-1 or declared_outgoing is not None):
        raise ValueError('--final-block只能用于最后一个已起草块，且批次outgoing须为null。')

    block = blocks[index]
    if not isinstance(block, dict) or not isinstance(block.get('shots'), list):
        raise ValueError('当前块需要已起草的镜头列表。')
    used = {beat for shot in block['shots'] for beat in shot.get('beats', [])}
    beats = [beat for beat in plan['beats'] if beat.get('id') in used]
    incoming = (dict(zip(('scene_id', 'time_id'), spacetime_identity(blocks[index-1])))
                if index else plan['boundary_context']['incoming'])
    if index + 1 < len(blocks):
        outgoing = dict(zip(('scene_id', 'time_id'), spacetime_identity(blocks[index+1])))
        boundary_confirmed = True
    elif declared_outgoing is not None:
        outgoing = plan['boundary_context']['outgoing']
        boundary_confirmed = True
    elif final_block:
        outgoing = None
        boundary_confirmed = True
    else:
        # An unknown successor is provisionally treated as same-time continuity.
        # Recheck this block once the next block or a real outgoing context exists.
        outgoing = dict(zip(('scene_id', 'time_id'), spacetime_identity(block)))
        boundary_confirmed = False
    local_plan = {key: plan[key] for key in ('schema_version', 'source_version',
                                             'source_sha256', 'config_sha256', 'defaults')}
    local_plan.update(boundary_context={'incoming': incoming, 'outgoing': outgoing},
                      beats=beats, blocks=[block])
    source = Path(source_record['path']).read_bytes().decode('utf-8')
    prompt = render(local_plan, source, config)
    audit_prompt = render(local_plan, source, config, audit=True)
    duration = config.get('max_duration', min(config.get('target_duration', 15),
                    15 if config.get('model') == '2.0' else 30))
    diagnostics = validate_structure(
        audit_prompt, duration, config.get('min_duration', 4), config.get('model'),
        config.get('duration_step'), check_sound_layout=False,
    )
    diagnostics += validate_voice_pacing(source, audit_prompt, duration)
    diagnostics += validate_sound_arrangement_layout(prompt)
    diagnostics += validate_plan_timing(local_plan, config)
    diagnostics += shot_language_diagnostics(local_plan)
    names = {canonical_speaker(v['speaker'], v['kind']) for v in block['voices']}
    actual, unassigned = extract_output_dialogue(prompt, names)
    expected, _ = extract_output_dialogue(audit_prompt, names)
    if unassigned or [(x.speaker, x.text) for x in actual] != [(x.speaker, x.text) for x in expected]:
        diagnostics.append(Diagnostic('ERROR', '直投正文的自然语言台词与后台话轮身份或正文不一致。'))
    errors = sum(d.level == 'ERROR' for d in diagnostics)
    warnings = sum(d.level == 'WARN' for d in diagnostics)
    stats = plan_stats(local_plan, prompt)
    return {
        'block': block_number,
        'status': 'hard_failed' if errors else ('local_passed' if boundary_confirmed else 'provisional'),
        'boundary_confirmed': boundary_confirmed,
        'errors': errors,
        'warnings': warnings,
        'shot_count': len(block['shots']),
        'silent_shots': prompt.count('环境音效：静默。') + prompt.count('本镜静默'),
        'stats': stats,
        'diagnostics': [asdict(d) for d in sorted(diagnostics, key=lambda d: d.level != 'ERROR')[:8]],
        'coverage': '未检查整段来源覆盖；全部块完成后仍须运行compile和语义复核。',
    }


def fingerprint():
    scripts = Path(__file__).resolve().parent
    return hashlib.sha256(b''.join((scripts / name).read_bytes() for name in
                                  ('compile_plan.py', 'project_state.py', 'validate_dialogue_and_timeline.py'))).hexdigest()


def compile_project(project, segment, plan):
    store = ProjectState(Path(project))
    source_record = store.source(segment)
    config = store.read()['config']
    if plan.get('source_version') != source_record['version'] or plan.get('source_sha256') != source_record['sha256']:
        raise ValueError('规划来源已变化，请更新受影响规划。')
    if plan.get('config_sha256') != digest(canonical(config)):
        raise ValueError('制作配置已变化，请复核受影响规划。')
    source = Path(source_record['path']).read_bytes().decode('utf-8')
    prompt = render(plan, source, config)
    duration = config.get('max_duration', min(config.get('target_duration', 15), 15 if config.get('model') == '2.0' else 30))
    audit_prompt = render(plan, source, config, audit=True)
    permitted_internal_short_blocks = {
        index + 1 for index, block in enumerate(plan['blocks'])
        if index < len(plan['blocks']) - 2
        and config.get('min_duration', 4)-1e-6 <= block['duration'] < 15-1e-6
        and spacetime_changed_after(plan, index)
    }
    diagnostics = validate(
        source,
        audit_prompt,
        duration,
        config.get('min_duration', 4),
        config.get('model'),
        config.get('duration_step'),
        check_sound_layout=False,
        permitted_internal_short_blocks=permitted_internal_short_blocks,
    )
    diagnostics += validate_sound_arrangement_layout(prompt)
    diagnostics += validate_plan_timing(plan, config)
    diagnostics += shot_language_diagnostics(plan)
    names = {canonical_speaker(v['speaker'], v['kind']) for b in plan['blocks'] for v in b['voices']}
    actual, unassigned = extract_output_dialogue(prompt, names)
    expected, _ = extract_output_dialogue(audit_prompt, names)
    if unassigned or [(x.speaker, x.text) for x in actual] != [(x.speaker, x.text) for x in expected]:
        diagnostics.append(Diagnostic('ERROR', '直投正文的自然语言台词与后台话轮身份或正文不一致。'))
    checks = [asdict(d) for d in diagnostics]
    plan_hash, prompt_hash = digest(canonical(plan)), digest(prompt)
    compiler_hash = fingerprint()
    build_hash = digest(canonical({'plan': plan_hash, 'compiler': compiler_hash}))
    build_relative = f'builds/{segment}/{build_hash}'
    build = store.path(build_relative)
    build.mkdir(parents=True, exist_ok=True)
    errors = sum(d.level == 'ERROR' for d in diagnostics)
    grouped_warnings = warning_groups(diagnostics)
    stats = plan_stats(plan, prompt)
    ledger = {'source_version': source_record['version'], 'source_sha256': source_record['sha256'],
              'config_sha256': plan['config_sha256'], 'plan_sha256': plan_hash, 'prompt_sha256': prompt_hash,
              'compiler_sha256': compiler_hash, 'plan': plan, 'stats': stats, 'diagnostics': checks,
              'warning_groups': grouped_warnings,
              'semantic_status': 'pending', 'status': 'hard_failed' if errors else 'needs_semantic_review'}
    # Content-addressed immutable candidates; the manifest is written last.
    for name, content in (('prompt.txt', prompt), ('ledger.json', canonical(ledger))):
        target = build / name
        if target.exists():
            if target.read_bytes().decode('utf-8') != content:
                raise ValueError('同一候选文件内容已变化，不覆盖。')
        else:
            with target.open('x', encoding='utf-8', newline='') as out:
                out.write(content)
    store.candidate(segment, build_relative, {'source_version': source_record['version'],
                    'source_sha256': source_record['sha256'], 'config_sha256': plan['config_sha256'],
                    'ledger_sha256': digest(canonical(ledger))})
    return {'build': build_relative, 'prompt': str(build / 'prompt.txt'), 'ledger': str(build / 'ledger.json'),
            'plan_sha256': plan_hash, 'prompt_sha256': prompt_hash, 'errors': errors,
            'warnings': sum(d.level == 'WARN' for d in diagnostics), 'warning_groups': grouped_warnings,
            'stats': stats, 'status': ledger['status'], 'diagnostics': checks}


def finalize(project, segment, build_relative, review):
    store = ProjectState(Path(project))
    build = store.path(build_relative)
    expected_parent = store.path(f'builds/{segment}')
    if build.parent != expected_parent:
        raise ValueError('候选不属于当前片段。')
    raw_ledger = (build / 'ledger.json').read_bytes().decode('utf-8')
    receipt = store.require_segment(store.read(), segment).get('candidates', {}).get(build_relative)
    if not receipt or digest(raw_ledger) != receipt['ledger_sha256']:
        raise ValueError('候选台账未登记或已变化，请重新编译。')
    ledger = json.loads(raw_ledger)
    keys(review, ('plan_sha256', 'prompt_sha256', 'passed', 'note', 'warnings_reviewed'), ('checks',))
    if type(review['passed']) is not bool:
        raise ValueError('语义复核结果必须为布尔值。')
    line(review['note'])
    if review['plan_sha256'] != ledger['plan_sha256'] or review['prompt_sha256'] != ledger['prompt_sha256']:
        raise ValueError('语义复核不属于该候选。')
    if digest(canonical(ledger['plan'])) != ledger['plan_sha256'] or digest((build / 'prompt.txt').read_bytes().decode('utf-8')) != ledger['prompt_sha256']:
        raise ValueError('候选文件已变化，请重新编译并复核。')
    if ledger['compiler_sha256'] != fingerprint():
        raise ValueError('编译或检查工具已变化，请重新编译。')
    config = store.read()['config']
    if ledger['config_sha256'] != digest(canonical(config)):
        raise ValueError('制作配置已变化，请重新编译。')
    if any(d['level'] == 'ERROR' for d in ledger['diagnostics']):
        raise ValueError('存在硬错误，不可登记为已完成。')
    warnings = [i for i, d in enumerate(ledger['diagnostics']) if d['level'] == 'WARN']
    reviewed = review['warnings_reviewed']
    schema = ledger['plan'].get('schema_version', 1)
    if not isinstance(reviewed, list):
        raise ValueError('已复核警告必须使用列表。')
    if schema >= 5:
        if any(type(item) is not str for item in reviewed):
            raise ValueError('V5已复核警告必须列出warning_groups的类别名，不接受旧式数字索引。')
        expected_warnings = set(ledger.get('warning_groups', {}))
        if review['passed'] and (len(reviewed) != len(set(reviewed)) or set(reviewed) != expected_warnings):
            raise ValueError('所有警告类别须完成语义复核后才可交付。')
    else:
        if any(type(item) is not int for item in reviewed):
            raise ValueError('V1-V4或兼容复核需列出诊断的零基整数索引。')
        if review['passed'] and (len(reviewed) != len(set(reviewed)) or set(reviewed) != set(warnings)):
            raise ValueError('所有警告须完成语义复核后才可交付。')
    if schema >= 5:
        checks = review.get('checks')
        keys(checks, V5_SEMANTIC_CHECKS)
        if any(type(checks[name]) is not bool for name in V5_SEMANTIC_CHECKS):
            raise ValueError('V5语义复核checks各项必须为布尔值。')
        if review['passed'] and not all(checks.values()):
            raise ValueError('V5语义复核存在未通过项目，不可登记为已完成。')
    elif schema >= 3:
        checks = review.get('checks')
        keys(checks, V3_REVIEW_CHECKS)
        if any(type(checks[name]) is not bool for name in V3_REVIEW_CHECKS):
            raise ValueError('V3语义复核checks各项必须为布尔值。')
        if review['passed'] and not all(checks.values()):
            raise ValueError('V3语义复核存在未通过项目，不可登记为已完成。')
    ledger['semantic_review'] = review
    ledger['semantic_status'] = 'passed' if review['passed'] else 'blocked'
    ledger['status'] = 'passed' if review['passed'] else 'semantic_blocked'
    store.ledger(segment, ledger)
    return {'status': ledger['status'], 'prompt': str(build / 'prompt.txt')}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('context', 'check-block', 'compile', 'finalize'))
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--segment', required=True)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--block', type=int)
    parser.add_argument('--final-block', action='store_true')
    parser.add_argument('--build')
    parser.add_argument('--review', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'context':
            store = ProjectState(args.project)
            config = store.read()['config']
            result = {'source': store.source(args.segment), 'config': config,
                      'config_sha256': digest(canonical(config)), 'plan_schema_version': 5,
                      'semantic_review_checks': list(V5_SEMANTIC_CHECKS)}
        elif args.command == 'check-block':
            if args.plan is None:
                raise ValueError('check-block需要--plan。')
            result = check_block(args.project, args.segment,
                                 json.loads(args.plan.read_text(encoding='utf-8')),
                                 args.block, final_block=args.final_block)
        elif args.command == 'compile':
            if args.plan is None:
                raise ValueError('compile需要--plan。')
            result = compile_project(args.project, args.segment, json.loads(args.plan.read_text(encoding='utf-8')))
        else:
            if args.review is None or not args.build:
                raise ValueError('finalize需要--build和--review。')
            result = finalize(args.project, args.segment, args.build, json.loads(args.review.read_text(encoding='utf-8')))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get('errors', 0) or result.get('status') == 'semantic_blocked' else 0
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    raise SystemExit(main())
