# Quant System — AI Architecture Rules

**MANDATORY / HIGHEST-PRIORITY PROJECT RULE**

本项目所有 AI Agent、开发人员及自动化工具必须遵守本文件。

## 核心铁律

**Skill 是逻辑层，Python 是执行层。** Skill 负责业务逻辑、分析逻辑、判断逻辑、交易逻辑、评分模型、分类分级、条件判断、信号判断、财报分析、预期差分析、因果归因、策略规则、风险判断、买入/卖出/持有/观察等结论，以及所有具有业务含义的规则。Python 负责数据获取、API 调用、清洗、转换、格式化、调度、Skill 调用、数据库读写、结果存储、历史数据、服务接口、前端数据供应和展示。Python 不得承担核心业务判断。

## 不得复制 Skill 逻辑

业务规则不得在 Python 中重复实现。正确架构：Python → 获取数据 → 调用 Skill → Skill 分析/判断/评分 → 结构化结果 → Python 保存 → 数据库/API/UI。

## Skill 是唯一业务逻辑权威

GitHub Skill / Knowledge 是业务逻辑 Single Source of Truth。若 Python、数据库、文档或其他地方冲突，以 Skill 为准，不得绕过 Skill。

## 数据库不是业务逻辑层

数据库只保存原始/处理数据、Skill 输入/输出、历史结果、时间序列、状态、运行记录和审计记录。数值的业务含义必须由 Skill 定义。

## 修改逻辑必须修改 Skill

修改业务规则时：用户需求 → 确认 Skill → 修改 Skill → 测试 Skill → Python 调用 Skill → 保存结果。禁止直接修改 Python 判断条件。

## 新功能开发顺序

① 明确业务逻辑 → ② 确认/新建 Skill → ③ 写入 Skill → ④ 定义输入输出 → ⑤ 测试 Skill → ⑥ Python 接入 → ⑦ 数据流转 → ⑧ 数据库存储 → ⑨ API/UI。不得先写 Python 再硬塞业务逻辑。

## AI 开始工作前必须检查本文件

开始修改前必须读取本文件、确认逻辑层/执行层、涉及业务判断时优先检查 Skill、禁止直接把业务逻辑写入 Python、完成后再次自检。无法判断时默认按逻辑层处理，优先放入 Skill。

## 防止逻辑漂移

禁止 Skill、Python、数据库、前端各自维护一套规则。业务规则应保持：Skill → 唯一业务判断 → 结构化输出 → Python 执行 → 数据库/API/UI。

## Python 可以技术判断，不能业务判断

允许 Python 判断 API 成功、字段存在、格式正确、数据库连接、任务执行、文件存在、超时。不允许 Python 判断股票是否值得买、基本面、财报超预期、评分、风险等级、信号、买卖或交易原因。后者必须由 Skill 判断。

## Skill 输出必须结构化

```json
{
  "decision": "...",
  "score": 0,
  "level": "...",
  "reason": "...",
  "risk": "...",
  "confidence": 0
}
```

Python 只负责接收、保存、查询、展示，不重新解释业务含义。

## 冲突优先级

1. 用户明确的新要求
2. AI_RULES.md
3. GitHub Skill / Knowledge
4. 项目技术实现
5. Python 旧逻辑
6. 数据库历史逻辑

## 核心原则

Skill 决定“怎么想、怎么判断、得出什么结论”。Python 决定“怎么取、怎么跑、怎么存、怎么传、怎么展示”。

**Skill 是大脑，Python 是手脚。** Python 可以执行 Skill 的决定，但不能替 Skill 做决定。

## 最终检查

每次修改后检查是否新增业务判断、是否放入 Skill、Python 是否出现新业务规则、是否复制 Skill 判断、是否修改 Skill 输出含义、是否出现两套规则、是否应新增/修改 Skill、是否遵守本文件。若违反，先修正架构再提交。

END OF AI_RULES.md
