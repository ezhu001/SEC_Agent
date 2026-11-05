# Qwen 的职责和可执行验证契约

## 这次问题的根因

旧请求把 `accounting_identity: UNAVAILABLE` 无区别地放进各个组件的 verifier 输入。模型把“不适用或没有可选恒等式证明”扩展成了“缺少必需证据”，恢复模型又继承了这个错误理由。仅有 JSON 形状校验不能阻止这种越权。

`revenue = Total net sales` 已由注册概念、来源、金额维度和期间确认时，verifier 不应再要求收入调节表、毛利恒等式或其他未注册条件。R&D intensity 的 numerator 是 R&D expense，denominator 是 revenue；两行分别核验，不要求每行同时包含公式全部元素。

## 有明确 prompt，但 prompt 不是可执行权限

实际 system prompt 在 `src/financial_filing_agent/config/prompts.py` 的 `PLANNER`、`VERIFIER`、`CORRECTOR` 中。客户端通过本地 Ollama `/api/chat` 发送 system prompt 和当前任务 JSON，并在 `format` 中发送本次请求的动态 JSON Schema。

每次调用是独立请求。先前某次成功识别并不会自动成为模型的长期记忆。共享状态和注册概念必须由程序显式传入。

可执行的限制在 `agents/verification_contract.py`、`agents/verifier.py` 和状态图中。模型不能执行 Python、增加公式依赖、修改源数据或自己调用搜索工具。

| 角色 | 允许做什么 | 禁止做什么 |
|---|---|---|
| Planner | 把自由问题映射到注册公式和明确期间；菜单模式无需它 | 编造公式、猜测期间、计算答案 |
| Verifier | 审核一行、一个组件中尚未解决的检查项，提供源文本依据 | 重开已确认映射、要求新证明、选择替代行、扩大搜索、计算 |
| Corrector | 根据被程序接受的具体问题，选择现有候选或在预算内请求扩大搜索 | 继承未经验证的自由文字、索要可选恒等式、虚构数据或越过预算 |

模型的 confidence 不是可信概率，也不能替代证据和程序校验。

## 当前 revenue 请求的边界

对于此处 R&D intensity 的 revenue 行，Python 会确认：

- 注册映射：Total net sales → revenue。
- 来源属于 operations，且与当前文件关联。
- FY2025 有唯一源值。
- 是金额，不是比例；单位兼容性另由 Python 校验。
- 在 `rd_intensity` 中的角色固定为 denominator。

这些项进入 `resolved_by_python`，verifier 无权否决或添加条件。剩余的 `open_checks` 通常只有 `reporting_scope`，即检查当前证据上下文是否支持合并报表口径。

收入和 R&D 请求不再携带无关的 `accounting_identity=UNAVAILABLE`，也不携带供替代选择的其他候选行。毛利恒等式仍由 Python 独立处理；它从不成为普通报表项目的必需条件。

## 从文本约束变成输出约束

每个请求单独生成输出 grammar：

1. `check` 只能取本次开放检查项；已解决项目不在可输出枚举中。
2. 检查结果数必须恰好等于开放检查项数，不能用空 `checks` 声称全部通过。
3. 每个检查只能使用对应的证据字段。合并范围不能用行名 `label` 冒充依据。
4. 范围检查的引文只能从当前行真实上下文的可用片段中选择；Python 还会核对引用确实存在。
5. 合并口径 PASS 要引用源文本中的 `consolidated` 表述。字段确实缺失时，可以结构化报告 missing_field；不能把空字段当 PASS。
6. 总 verdict、findings、error_type 由 Python 从逐项状态及源引用汇总，模型的重复摘要不能改变它们。FAIL/UNCERTAIN 需要具体依据。
7. 不能把可选 certificate、accounting identity 或 reconciliation 升格为必需证据。

例如，本次范围检查的合法结果包含：

```json
{
  "verdict": "PASS",
  "error_type": "none",
  "confidence": 0.9,
  "reason": "The supplied context supports consolidated reporting scope.",
  "findings": [],
  "checks": [{
    "check": "reporting_scope",
    "status": "PASS",
    "evidence_field": "nearby_context",
    "observation": "quote",
    "evidence_quote": "CONSOLIDATED STATEMENTS OF OPERATIONS",
    "reason": "The actual statement heading establishes the scope."
  }]
}
```

无效输出只获得一次契约纠正机会。持续违反契约时返回 `VerifierContractError`（或结构解析层的 `DecoderError`），不把它伪装成财务证据不足，不触发 corrector 或扩大搜索。HTTP/JSON 解析重试也有独立有限预算，不能形成无限循环。模型只需给每个开放检查作出带来源的观察；程序从这些观察生成唯一的总体结论，不要求模型把同一判断重复填写成几个可能矛盾的摘要。

只有被接受的、有来源依据的负面 findings 或确定性的 guard 失败，才可能进入恢复。恢复输入剔除了自由解释及不适用恒等式字段，并严格执行剩余搜索预算。

## UI 和审计

侧边栏新增 **Qwen responsibilities and actual prompts**：可查看实际三个 system prompts 和通用输出 schema。每次运行的 **Verification** 中可查看实际契约、开放检查、逐项结果及源引文；完整 audit 的 `decoder_calls[].request.format` 是发给 Ollama 的本次动态 schema。

模型原话保存在 `model_reason` 及原始响应中。主进度显示的是已校验的检查项、状态和引用，不把模型自由文字当作程序规则。Qwen 开关仍然保留。

## 实测及局限

最终逐项引用版对用户这份 Apple 文件的 FY2025 R&D intensity 返回 SUCCESS：Python 计算 `34,550 / 416,161 × 100 = 8.302075398703867%`。R&D 与 revenue 分别提供了合并报表上下文引用；decoder 调用 2 次，恢复 0 次，扩大搜索 0 次。审计：`artifacts/runs/d10426e0394c4c168ded12e0827a34c9/audit.json`。

另一个真实模型反例把 Total cost of sales 作为 revenue 候选。模型给出有源引用的 concept_match=FAIL；恢复器选择现有 Total net sales，重新核验后 SUCCESS，Python 得到收入增长 6.425511782832739%。审计：`artifacts/runs/e43840da7d934774a7f90198e097fd29/audit.json`。该次辅助 scope 子项仍将成本分区与收入分区混淆，说明模型解释不是形式化证明；契约现已补充每个检查项的精确定义，明确同一合并报表的收入/成本分区不构成 reporting_scope 差异。主错误定位和恢复成功不等于所有辅助解释都正确。

完整回归为 **93 项通过、1 项 CUDA 不可用跳过**，报告 `artifacts/executable-verifier-final.xml`。测试覆盖虚构证明要求、缺失或错误引用、空检查列表、固定检查被重开、摘要与观察矛盾、合法缺失字段、禁止越权扩大搜索及正常恢复。

开发中曾出现空检查列表、引用错误字段等无效回答，均被拦截并保留 ERROR 审计，没有触发扩大搜索。针对原始“缺少收入恒等式”的复现测试验证了有限纠正、持续越权报错和禁止恢复扩张。

这套契约保证权限、结构、来源引用和路由边界，不保证模型对所有新会计措辞都作出正确解释。新的、模糊的语义判断仍须评估；不能因为 JSON 合法或模型自信就宣称绝对可靠。报表范围缺少明确支持时可以返回待定，而不是推断出一个答案。
