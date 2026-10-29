# R 中间量与局部校验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按论文 B 与场景数据契约实现单点 R 中间量，并只对 A、B 各自第一个风险窗口及前五个探针逐项核验。

**Architecture:** `src/risk/risk_matrix.py` 提供无文件 I/O 的物理量、伤亡面积、缓解因子和单点风险函数；`src/risk/verify_r.py` 负责读取 config、场景数组与切片基准，调用既有 `ps.compute_ps`，组织局部重算和日志。所有路径从 config 所在目录解析，输入保持只读，校验日志落在仓库的 `experiments/validation/`。

**Tech Stack:** Python 3.12、NumPy、标准库 `argparse` / `csv` / `json` / `pathlib`。

**Spec:** 本轮用户任务；参数与索引契约取自 `lib/03_场景/README.md`、`lib/03_场景/config.json`、`lib/02_公式提取/公式提取.md` 和论文 A/B PDF。

## Global Constraints

- 仅写 `src/risk/risk_matrix.py`、`src/risk/verify_r.py`、四份指定日志，以及确有歧义时的 `report/assumptions.md`。
- 不修改 `lib/01_论文原文/`、`lib/02_公式提取/`、`lib/03_场景/`、`lib/04_任务书/`、`src/core/`、`src/algorithms/`。
- 不生成全量 R；验证范围限定为每场景 index 首窗及 `probe_points.csv` 前五行。
- 所有配置参数运行时读取；建筑体素输出 NaN；风险使用每飞行小时单位。
- 校正指数按已确认口径 `3/P_s`；`P_s=0` 按论文极限分支处理。
- 记录摘要中明确给出的简化：弹道碰撞能量使用竖直自由落体速度；开伞碰撞竖直速度采用终端速度。

## Review Focus

- `P_s=0`、`E_crash<=beta` 与 `E_crash=beta` 的分支必须遵守论文极限，不能造成除零或 NaN。
- 弹道碰撞能量的摘要简化忽略水平分量；面积仍使用式 (11)(12) 的水平/竖直速度比，二者不可混用。
- 开伞水平速度需要由式 (16)(19) 和 `T_1` 得到，落地时刻及终端竖直速度简化要能在日志中追溯。
- `M_p` 的分母可能为零；仅在式 (34) 适用分支调用比值，其他分支按论文处理。
- 切片比较必须把 NaN 位置一致性与有限值相对误差分开报告，并使用 README 规定的阈值。

---

### Task 1: 无 I/O 的 R 中间量模块

**Files:**
- Create: `src/risk/risk_matrix.py`

**Interfaces:**
- `compute_crash_energy(mass: float, velocity: Sequence[float]) -> float`
- `compute_correction_k(E_crash: float, beta: float, P_s: float) -> float`
- `compute_fatality_rate(P_s: float, E_crash: float, alpha: float, beta: float) -> float`
- `compute_casualty_area_ballistic(r_p: float, r_u: float, h_p: float, v_x: float, v_y: float) -> float`
- `compute_parachute_terminal_velocity(mass: float, gravity: float, rho: float, c_d_p: float, s_p: float) -> float`
- `compute_casualty_area_parachute(r_p: float, r_u: float, h_p: float, v_x: float, v_y: float) -> float`
- `compute_mitigation_Mp(A_c_b: float, A_c_p: float, P_f_b: float, P_f_p: float) -> float`
- `compute_mitigation_Ms(P_s: float, E_crash: float, alpha: float, beta: float) -> float`
- `compute_mitigation_M(M_p: float, M_s: float, E_crash_b: float, E_crash_p: float, beta: float, eta: float) -> float` for the three branches of B Eq. (34)
- `compute_final_R_point(pop_density: float, A_c_b: float, M: float, P_LOC: float, is_building: bool) -> float`, returning NaN for a building voxel

- [ ] Implement equations and validation for scalar inputs; docstrings state units and source equation.
- [ ] Add internal trajectory helpers using configured parameters: ballistic horizontal impact speed from Eq. (16) at free-fall time; for parachute, solve the two-stage vertical displacement from Eqs. (18)/(19)/(20) to get impact time and horizontal speed from Eqs. (16)/(19); use the scenario summary's vertical-speed simplifications for impact energy and area inputs.
- [ ] Verify the ballistic energy and casualty-area anchors at the documented 30 m and 90 m layers, and the parachute terminal-velocity/energy anchors, using an ephemeral command rather than adding test files.

### Task 2: Single-window and five-probe verifier

**Files:**
- Create: `src/risk/verify_r.py`
- Create: `experiments/validation/r_window_A.txt`
- Create: `experiments/validation/r_window_B.txt`
- Create: `experiments/validation/r_probe_A.txt`
- Create: `experiments/validation/r_probe_B.txt`
- Modify only if needed: `report/assumptions.md`

**Interfaces:**
- CLI accepts `--config`, optional `--scenes`, and optional output directory.
- Per scene, use config-resolved `city.npz`, `slices/index.json`, first listed window, `slices/probe_points.csv`, and existing `compute_ps`.
- Produce a window report and probe report without constructing or traversing a full R array.

- [ ] Read the first window and first five probe rows; derive `h_idx` from configured altitude origin/resolution.
- [ ] Recompute only each requested point using the module functions and 2-D `P_s` lookup; honor `building_mask` as the NaN mask.
- [ ] Compare window finite values at README tolerance, report NaN agreement, maximum relative error, failure count, and first ten failures; compare probes one by one.
- [ ] Write the four logs with a clear local-only conclusion and preserve every mismatch.

### Task 3: Final checks and assumption record

**Files:**
- Modify only if required: `report/assumptions.md`

- [ ] Run `python -m py_compile src/risk/risk_matrix.py src/risk/verify_r.py`.
- [ ] Run `python -m src.risk.verify_r --config lib/03_场景/config.json --scenes A B` and inspect all four logs.
- [ ] Run `git diff -- lib/01_论文原文 lib/02_公式提取 lib/03_场景 lib/04_任务书`; require no output.
- [ ] If the local baselines disagree with an equation interpretation or velocity-time simplification, append a concise assumption with evidence and impact; do not alter the inputs or tune formulas to force a match.

---

## Self-Review

- Spec coverage: all requested intermediate quantities, the explicitly requested fatality/mitigation branches, building NaN behavior, and the strictly local window/probe scope are assigned above.
- Step scan: implementation, local verification, and final read-only-directory checks are separate and independently checkable.
- Type consistency: shared risk functions are scalar and file-I/O free; the verifier owns all config/data loading.
- Review focus: zero sheltering, energy thresholds, differing velocity simplifications, denominator edge cases, and NaN matching are all called out for implementation and review.
- Proportion: this plan records interfaces and checks without duplicating the implementation.
