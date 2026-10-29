# AI 使用说明

## 本次 M1 验收工作（2026-10-29）

- **Agent / 模型：** Codex，GPT-6 系列模型。
- **参与环节：** 阅读项目规则和校验实现；核对现有 A/B 全量校验 JSON 与场景 README；修改 `src/risk/verify_r.py` 的已知差异接受条件；更新 `report/assumptions.md`、M1 验收记录和项目状态。
- **人工提供的任务约束：** 不改风险公式、不碰算法、不修改输入文件；B 的 `1.1447%` 中位数差异只按基准精度限制接受，不能写成计算通过；未显式接受时保留严格失败行为。
- **人工核查：** 本地代码读取 `experiments/validation/validation_A.json`、`experiments/validation/validation_B.json`、A/B `summary.json` 和 README；确认 shape、NaN/finite 计数、窗口/探针工程容差状态及 B summary mismatch 键。桶边界和计数未出现在 summary 中，因此没有补造分桶或声称复算通过。
- **采用的 AI 输出：** `verify_r.py` 的显式 `--accept-known-diff` 开关与窄条件判断；assumptions 中的 M1 接受口径；`report/m1_acceptance.md` 中基于本地校验结果的验收记录。
- **拒绝/保留事项：** 未将 B 的 `r_median` / `r_norm` 从 MISMATCH 改成 PASS；未放宽 README 的 1% 统计容差；未改公式、场景输入或生成全量 R 数据文件。
- **验证：** 本地 full 校验在不带接受开关时返回 `1`；带 `--accept-known-diff` 时返回 `0` 并保留 B summary MISMATCH。`python -m pytest -q` 为 `10 passed`，模块编译检查通过。
- **截图索引：** 本次文本任务未采集交互截图，无截图文件可列。
- **验证原则：** 最终统计和验收状态以本地 Python 程序及其全量校验 JSON 为依据；AI 未代替实验运行或生成风险数据。

## 本次实验产物目录整理（2026-10-29）

- **参与环节：** 按项目目录约定归位场景采集记录、检查脚本日志、机器可读校验结果和人工诊断说明；调整相关脚本的默认输出目录；更新 `structure.md` 和现有路径引用。
- **人工提供的任务约束：** `experiments/raw/` 保存真实运行记录和场景采集结果；`experiments/validation/` 保存检查脚本输出；`report/` 保存人工整理的说明和结论；只读输入资料保持不变。
- **采用的 AI 输出：** 检查脚本默认目录调整、既有产物归档和结构索引更新。场景采集记录 `inspect_A/B.txt` 仍留在 `experiments/raw/`；校验日志及 JSON 位于 `experiments/validation/`；诊断和验收说明位于 `report/`。
- **验证：** `python -m pytest -q` 为 `10 passed`；`python -m compileall -q src tests` 成功；五个采集/校验脚本的 `--help` 均正常；只读输入目录的 Git diff 无输出。
- **变更范围：** 未改写场景数组、论文、公式或任务书；调整了 P_s 校验器，使其只写验证日志，不自动追加人工维护的 assumptions 文档。
