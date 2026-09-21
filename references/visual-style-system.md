# 稳定视觉系统与抬头前缀

## 抬头两行

每个生成块正文的第 2、3 行是稳定视觉层，也是整份提示词里**唯一允许英文**的位置：

```text
<技能已选风格选项原文>;<中文执行质感>;<英文质感前缀>;With ambient sound effects。
禁止项：<英文禁项串>。
```

风格行首句必须是 [style-profiles.md](style-profiles.md) 已选选项的原文，原样不改写、不概括；中文执行质感只写渲染质感与画面完成度，不写时长、画幅、固定运镜、固定景深或剧情事件；英文质感前缀写画质、材质、表演细节与声音边界；禁项行按当前风险给英文负向词。三行默认取本页三个预设，规划可用 `defaults.visual_quality`、`defaults.render_quality_en`、`defaults.negatives` 覆盖。

## 三个风格预设

**预设① 3D国风动漫,暗黑武侠/超写实仙侠风格**

```text
中文执行质感：UE5光线追踪影视级写实渲染,高精度粒子流体特效,电影级画质,运镜丝滑,层次构图,景深变化,画面细节饱满,光影层次清晰,明暗对比强烈,空间感强
英文质感前缀：Ultra-high definition, natural skin tone, delicate hair strands and fabric textures, naturally focused gaze, natural blinking, visible pores and fine lines. Subtle micro-expressions, slight trembling of eyelashes, breathing chest movement, clothing fluttering gently in the wind, composed and graceful movements
禁止项：no duplicates, no clones, passersby face mismatch with protagonist, no abrupt ending, avoid AI feel, stiff features, hand clipping, blurry, lip sync mismatch, plastic skin, uncanny valley, fake expressions, jitter, flicker, no BGM, no subtitles, no text
```

**预设② 3D国风动漫，眷思量风格，东方奇幻唯美风格**

```text
中文执行质感：唯美三维渲染,柔光与空气感,织物与发丝动态细腻,色彩清雅通透,层次清晰
英文质感前缀：Ultra-high definition, delicate hair strands and fabric textures, soft rim light, flowing hair and sleeves, naturally focused gaze, natural blinking; subtle micro-expressions, breathing chest movement, graceful movements
禁止项：no duplicates, no clones, no abrupt ending, avoid AI feel, stiff features, hand clipping, blurry, lip sync mismatch, plastic skin, uncanny valley, fake expressions, jitter, flicker, no BGM, no subtitles, no text
```

预设②去掉 `natural skin tone` 与 `visible pores`：唯美风格下这两项会把模型往写实皮肤推，与三维唯美渲染拉扯。

**预设③ 自定义**：由用户给出的中文风格转译出中文执行质感，英文前缀取预设①的中性子集（画质、发丝与织物、微表情、呼吸与衣摆动态），去掉与所选美术方向冲突的条目。

## 特效与文字边界

美术风格不规定所有人物的情绪强度。暗黑武侠仍可有意气风发、尴尬喜剧、温情和爆发式悲愤；具体表演由原文节拍决定，不写“全程克制”“全部低沉”或固定运镜节奏。

- `高精度粒子流体特效`保留在抬头，用于提升粒子渲染质量，**不因此新增雨、火、烟、爆炸等剧情事件**；事件仍由锁定来源决定。
- `no subtitles, no text` 不限制剧情明确出现的墓碑、书页、卷宗、牌匾、字幕或系统界面。描述文字内容时只保留原文给出的内容，不补写界面文案。
- 没有剧情依据时，禁止新增字幕、水印、旁白文字或界面文字。

## 块级设计七项

抬头的下一段是块级设计，按固定顺序写全局光照方案、光影色彩、层次构图、景深设计、人物站位、构图原则、场景地点环境描述（含氛围与动态细节），逐镜只补变化。同一连续场景的光源方向、色温、强度与深浅逻辑保持一致；换场景或同场景跨时间必须整段重写并说明差异。

连续场景在该段内选择一组清晰词并保持一致：

- 荒山白天：冷硬日光，低饱和土色，清晰短阴影。
- 陈府寿宴：暖灯笼主光，院外冷色补光，人物面部暖亮、门外留冷影。
- 系统空间：黑色虚空，古书淡金主光，背景无建筑反射。
- 紫衣门夜战：固定月光方向，真气光只照亮接触区域。

每场景再按需要写主光方向、软硬、色温、阴影边界、轮廓光、环境反射和特效光；同一连续场景不能无依据混用多套模糊冷光描述。

一致性清单不止光照与色彩：**背景参照物也必须一致**。同一 `scene_id` 的连续块沿用同一组背景层措辞（后景是什么、有哪些固定物件），块级设计不得为个别块改写背景层表述或引入其他块没有的景物。措辞漂移会让模型只在个别镜头里生成树林、楼阁、院落等新元素，而其他镜头没有，破坏同场景的空间连续感。
