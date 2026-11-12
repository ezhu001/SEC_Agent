# Qwen 的职责和可执行验证契约（v2）

三个角色仍为 Planner、Verifier、Corrector，分别由 LangGraph 的 plan_task、verify、correct 节点承载。菜单选择跳过 Planner；全部检查被 Python 的来源证据确认时跳过 Verifier 模型调用；正常成功路径跳过 Corrector。没有增加新的图节点。

## 来源和范围

解析器 v9 保存报表标题、Total 等行组标题、XBRL entity/context ID、维度以及合并范围声明，并记录来源位置。标题中的单词可以跨相邻 inline span；保留其真实 DOM 文本，不添加不存在的 consolidated 字样。

Python 的 scope_assessment 返回 ESTABLISHED、RESTRICTED 或 UNRESOLVED。发行人匹配的 XBRL 上下文，加上明确合并标题或与发行人关联的合并声明，可以确认主报表范围。附注中的重复行只有在同一文件、同一 concept/context/entity、期间、金额、单位、scale、维度等事实身份一致时才能关联到已确认的主报表。维度为空本身不够；子公司、分部、母公司单体范围不能被全局声明覆盖。

适用的毛利恒等式仍只由 Python 处理，用于确认会计概念，不自动证明范围。收入口径策略仍区分 Net sales 和另行报告的收入总额。

## 模型边界与输出

实际 prompt 在 config/prompts.py，契约在 agents/verification_contract.py。resolved_by_python 中的检查不能被模型重开。模型只审核 open_checks，引用 evidence_catalogue 中的 ID，不抄写引文，不选择替代行，不扩展搜索，不计算。

示例：某个范围问题确实没有足够证据时，可返回：

```json
{
  "checks": [{
    "check": "reporting_scope",
    "status": "UNCERTAIN",
    "evidence_ids": ["row:context"],
    "reason_code": "insufficient_evidence",
    "reason": "The supplied context does not establish issuer-wide scope."
  }]
}
```

Python 核对 ID 是否属于当前文件和当前行、证据类型是否支持该检查，并还原原文及来源位置。PASS 需要支持性证据；FAIL 需要矛盾证据；UNCERTAIN 可以引用模糊上下文，证据缺失时可用空 ID 列表。范围结论不能只根据 statement type 或任意一个 consolidated 单词。

总 verdict、error_type、findings 由 Python 从逐项观察汇总。审计保留模型原始 ID 响应，以及程序还原后的引用。confidence 不是校准概率。可选 accounting identity/certificate 不能被变成模型要求的前置条件。

## 修复和恢复

无效 ID、错误证据类型或不成立的范围结论只能得到一次契约修复机会；持续无效时返回 ERROR，不把无效模型输出当成财务证据或扩展依据。HTTP/schema 重试有独立的有限预算。

有效 FAIL/UNCERTAIN 可进入预算内的恢复。已拒绝的行保持排除。UNCERTAIN 的行只有在支持证据指纹变化后才可重新审核；相同证据不能反复尝试。替代行必须重新经过 eligibility、概念和范围审核以及最终选择/分母 guard。

历史 v1 审计和测试结果保留。外部评分器 v2 的事实等价性检查、参考金额和标签不进入运行时请求。
