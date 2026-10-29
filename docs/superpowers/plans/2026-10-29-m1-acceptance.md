# M1 验收与已知差异处理实施计划

> 执行方式：Native，由当前主代理按步骤完成。

**目标：** 记录 B 场景 summary 中位数的已知基准精度差异，并让全量校验仅在该差异是唯一剩余问题时，可由显式参数接受。

**方案：** 保持风险公式、严格阈值和输入文件不变。在 `verify_r.py` 增加仅作用于 full 范围的 `--accept-known-diff`；只有工程容差检查通过，且 summary 差异仅来自 B 的 `r_median` / `r_norm` 时，才返回 0。同步更新 assumptions、M1 状态和验收记录。

**技术栈：** Python、argparse、JSON 校验记录、Markdown/TXT 文档。

**依据：** 用户本轮 M1 验收要求；`AGENTS.md` 工作流；`lib/03_场景/README.md` 的 1% summary 统计阈值。

## 全局约束

- 不改风险计算公式、`risk_matrix.py`、算法和场景输入。
- 不把 B 的 `1.1447%` 写成计算通过；只记录为“基准精度限制接受”。
- 不传接受开关时，全量校验失败仍返回退出码 1。
- M1 报告数值只采用已有 A/B 全量校验 JSON。
- 执行 `git diff -- 01_论文原文 02_公式提取 03_场景 04_任务书` 并确认无输出。

## 文件职责

- `src/risk/verify_r.py`：识别已明确接受的 B summary 差异、保留其他失败的严格退出行为，并在输出中说明接受状态。
- `report/assumptions.md`：记录 M1 全局统计容差、A/B 中位数差异、精确 `R_norm` 口径和接受决定。
- `report/m1_acceptance.md`：记录本次 M1 的实际统计、验收状态和 M2 入口。
- `experiments/validation/validation_A.json`、`validation_B.json`、`r_full_summary.txt`：保存全量机器校验结果。
- `AGENTS.md`、`plan.md`、`report/AI使用说明.md`：按项目工作流同步里程碑和本次 AI 使用记录。

## 实施步骤

- [x] 从 A/B 全量校验 JSON 核对 shape、NaN、finite、summary 差异和窗口/探针工程容差状态。
- [x] 在 `verify_r.py` 增加 `--accept-known-diff` 和唯一差异判断：仅接受 B 的 `r_median`/`r_norm` summary MISMATCH，误差须匹配 assumptions 中记录的 `1.1447%`（按显示精度容许舍入），且工程点位、结构及其他 summary 项均满足；该参数只允许 `--scope full`。
- [x] 更新全量摘要和终端消息；无开关时保留退出码 1，出现其他失败时拒绝接受。
- [x] 更新 `assumptions.md`，标明 B 差异是已知基准精度限制接受，并更新全量模式状态。
- [x] 运行 A/B full 校验，生成 `report/m1_acceptance.md`，记录真实结构统计、工程容差和 summary 状态。
- [x] 同步 M1/M2 状态和 AI 使用记录；验证 CLI 帮助、接受条件正反例、pytest 与只读目录 diff。

## 验收检查

- `python -m src.risk.verify_r --help` 显示 `--accept-known-diff`。
- 仅有允许的 B summary 差异时，该开关接受；无开关、工程容差失败、结构失败或其他 summary 差异时拒绝。
- `report/m1_acceptance.md` 列出 A/B 的 shape、NaN 数、finite 数和 M2 入口。
- `python -m src.risk.verify_r --scope full` 返回 1；同命令加 `--accept-known-diff` 在唯一已知差异条件下返回 0。
- `git diff -- 01_论文原文 02_公式提取 03_场景 04_任务书` 无输出。
