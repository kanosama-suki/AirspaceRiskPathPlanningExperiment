# 实验产物目录整理实施计划

> **执行要求：** 按任务逐项完成；所有输入资料目录保持只读，移动文件时保留原内容。

**目标：** 统一场景采集记录、校验产物和人工报告的存放位置，并让脚本默认输出、路径引用和 `structure.md` 与实际目录一致。

**方案：** `experiments/raw/` 保留实验运行原始记录及场景采集记录；检查脚本生成的日志和 JSON 归入 `experiments/validation/`；人工整理的诊断、说明、验收和结论归入 `report/`。各脚本继续支持显式 `--output-dir`，未指定时按其产物类别选择默认目录。

**技术栈：** Python、PowerShell、Git、pytest、Markdown。

**依据：** 用户本轮目录约定；`AGENTS.md`、`plan.md`；仓库当前实际文件结构。

## 全局约束

- 不修改或移动 `lib/01_论文原文/`、`lib/02_公式提取/`、`lib/03_场景/`、`lib/04_任务书/` 下的输入文件。
- `experiments/raw/inspect_A.txt` 和 `inspect_B.txt` 是采集记录，继续留在 `raw/`。
- `src/inspection/inspect_scene.py` 继续作为采集程序；`src/validation/` 中的程序继续作为校验程序。
- 不删除任何既有产物；文档改名时更新仓库内可定位的引用。
- 校验脚本只写校验产物，不自动修改人工维护的 `report/` 文档。
- `structure.md` 只按仓库当前实际结构描述目录和文件用途，不列不存在的目录或预设文件。

## 变更文件结构

- 修改 `src/inspection/inspect_scene.py`：采集输出默认落入 `experiments/raw/`。
- 修改 `src/risk/verify_ps.py`、`src/risk/verify_r.py`、`src/validation/verify_align.py`、`src/validation/check_data_contract.py`：校验输出默认落入 `experiments/validation/`。
- 移动 `experiments/raw/` 中已有的 P_s/R/索引/数据契约检查日志与 JSON 到 `experiments/validation/`。
- 移动人工诊断、决策和验收材料到 `report/`，按 Markdown 内容命名为 `.md`。
- 更新 `report/assumptions.md`、`report/AI使用说明.md` 及移动报告中的结果路径；检查已有计划文档的路径说明是否仍表示当前输出位置。
- 重写根目录 `structure.md`，描述当前真实目录树和文件用途。

## 重点复核

- 采集记录不能随校验日志迁入 `validation/`：检查后确认 `inspect_A/B.txt` 仍在 `raw/`。
- 机器可读全量校验 JSON 不属于实验运行原始结果：检查后确认 `validation_A/B.json` 位于 `validation/`。
- 报告间的相对/仓库路径引用不能因移动和扩展名调整而失效：用 `rg` 搜索旧文件名并逐项复核。
- 脚本显式输出目录的调用方式必须继续可用：验证参数接口并运行现有测试。
- 结构文档不得把规划中的空目录或不存在的 `05_规划书/` 写成已存在目录。

---

### 任务 1：归档已有产物

**文件：**
- 移动：`experiments/raw/ps_check_A.txt`、`ps_check_B.txt`、`r_full_summary.txt`、`r_window_A.txt`、`r_window_B.txt`、`r_probe_A.txt`、`r_probe_B.txt`、`validation_A.json`、`validation_B.json` 到 `experiments/validation/`。
- 移动并将 `.txt` 改为 `.md`：`dp_itemized`、`m1_acceptance`、`openparachute_diagnosis`、`ps_diagnosis_A`、`ps_diagnosis_B`、`r_tolerance_decision`、`reflect_disambig`、`residual_source`、`speed_sensitivity`、`summary_median_diagnosis`、`time_interval_explanation` 到 `report/`。
- 保留：`experiments/raw/inspect_A.txt`、`inspect_B.txt`。

- [x] 按清单移动文件，确认数量、文件大小和内容均保留。
- [x] 用仓库搜索列出旧路径引用，作为脚本和报告修改的核对清单。

### 任务 2：统一脚本默认输出目录

**文件：**
- 修改：`src/inspection/inspect_scene.py`
- 修改：`src/risk/verify_ps.py`
- 修改：`src/risk/verify_r.py`
- 修改：`src/validation/verify_align.py`
- 修改：`src/validation/check_data_contract.py`

- [x] 将采集器的默认输出设为仓库 `experiments/raw/`，将四个校验器的默认输出设为 `experiments/validation/`。
- [x] 保留 `--output-dir` 显式覆盖能力；数据契约校验器仍从 `experiments/raw/` 读取 `inspect_*.txt`。
- [x] 移除 P_s 校验器自动追加 `report/assumptions.md` 的行为，使验证脚本只写校验日志。
- [x] 更新参数帮助文本及调用约定，避免再把校验结果描述为 raw 产物。

### 任务 3：修正文档引用并更新结构索引

**文件：**
- 修改：`report/assumptions.md`、`report/AI使用说明.md`
- 修改：迁入 `report/` 的相关报告及 `docs/superpowers/plans/` 中仍表示当前路径的说明
- 重写：`structure.md`

- [x] 把验收 JSON/日志引用更新到 `experiments/validation/`，把人工验收记录引用更新到 `report/`。
- [x] 在移动报告内部修正其所引用的校验日志路径。
- [x] 依据 `Get-ChildItem` / `rg --files` 盘点结果编写实际目录树；只写目录、文件和各自用途。

### 任务 4：验证整理结果

**检查：**
- [x] `python -m pytest -q`（10 passed）。
- [x] 对五个脚本运行 `--help`，确认输出目录参数仍可选或可显式覆盖。
- [x] 搜索旧报告文件名和 `raw/validation_*.json`、`raw/r_*.txt` 等过时引用；未发现遗留引用。
- [x] 确认采集记录在 `raw/`、检查日志和 JSON 在 `validation/`、人工结论在 `report/`。
- [x] 运行 `git diff -- lib/01_论文原文 lib/02_公式提取 lib/03_场景 lib/04_任务书`，无输出。
