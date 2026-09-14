# 时长模式

目标时长在当前任务确定为15/30秒，用户已给出就采用，之后沿用直至明确更改。完整剧本先配置并等待处理范围，不自动生成开头。

目标与单次可执行时长分开：按 [model-and-production-config.md](model-and-production-config.md) 将30秒目标映射到2.0的多个15秒以内块，或2.5的原生30秒块。最终校验 --duration 使用编译后的块上限，不是整段文案总时长。

完整15秒块默认五镜，可按表演与连续运镜需要调整。优先完整收尾，短尾和最后两块重排按 [generation-block-splitting.md](generation-block-splitting.md)，不默认丢到下一次文案。最小时长与步长服从实际入口配置。
