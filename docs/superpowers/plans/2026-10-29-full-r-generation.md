# Full R Generation and Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate each scene's full in-memory R array and validate all indexed windows and all probes without changing model formulas or source data.

**Architecture:** Add a full-array generator to `risk_matrix.py` that reuses its existing scalar risk functions and `compute_ps`, with layer-level reuse across the 442 observed P_s values. Extend `verify_r.py` with an explicit full/sample scope, preserving the current sample path and writing full-scope JSON plus a text summary.

**Tech Stack:** Python, NumPy, existing JSON/CSV readers, argparse.

**Spec:** Current user request; source contracts in `lib/03_场景/README.md` and each scene's `slices/README.md`.

## Global Constraints

- Leave `01_论文原文/`, `02_公式提取/`, `03_场景/`, and `04_任务书/` unchanged.
- Do not modify `src/core/`, `src/algorithms/`, or `tests/`; do not run planners or generate paths.
- Keep the README pointwise threshold at `1e-5`; report the separately accepted engineering tolerance as tolerance acceptance, never strict PASS.
- Reuse `compute_ps` and existing risk-model intermediate functions; do not change their formulas.
- Generate full R in memory and validate it; write only the requested validation JSON and full-summary text outputs.

## Files and Responsibilities

- `src/risk/risk_matrix.py`: add shape-checked full R generation, returning float64 `[i,j,h_idx]` with building voxels as NaN.
- `src/risk/verify_r.py`: add full-scope window/probe/statistics validation, JSON serialization, and `--scene` / `--scope` CLI while preserving sample validation.
- `experiments/validation/validation_A.json`, `validation_B.json`: per-scene full validation details.
- `experiments/validation/r_full_summary.txt`: combined human-readable full-run report.

## Review Focus

- A/B use `float32` window references and full-size boolean masks; test NaN masks separately from finite-value relative errors.
- Window metadata uses world height `z`, while R uses `h_idx`; validate the configured origin/resolution mapping and array bounds.
- Building-class probes must remain NaN; open probes use the CSV's expected value and the README tolerance.
- Summary medians are histogram estimates; compare global statistics using the slices README's 1% allowance and state the median method.
- The engineering tolerance is documented in `report/assumptions.md`; keep it distinct from the README threshold and preserve strict mismatch counts.

---

### Task 1: Full in-memory R generation

**Files:**
- Modify: `src/risk/risk_matrix.py`

**Interface:**
- Add `compute_r_matrix(building_footprint, pop_density, building_mask, config, ps_field=None) -> np.ndarray`.
- If `ps_field` is omitted, call `compute_ps(building_footprint, pop_density, config)`; otherwise validate its 2D shape.
- Validate configured `(N_I, N_J, N_H)` dimensions. Derive altitude from `coords.origin[2]` and `coords.resolution`.
- For each height, reuse existing scalar intermediate functions to calculate one per-density coefficient for each unique P_s, then broadcast coefficients over the plane. Set `building_mask` voxels to NaN and return float64.

- [x] Confirm the existing scalar functions cover the layer model inputs without changing their formulas.
- [x] Implement shape/value validation and the layer loop with unique-P_s reuse.
- [x] Run an import/smoke call on both real scenes and confirm output shape and NaN counts equal `building_mask` counts.

### Task 2: Full-scope verification and reports

**Files:**
- Modify: `src/risk/verify_r.py`
- Create: `experiments/validation/validation_A.json`
- Create: `experiments/validation/validation_B.json`
- Create: `experiments/validation/r_full_summary.txt`

**Interface:**
- Add `--scene A` or `--scene B` selection (omitting it runs both) and `--scope sample|full`, defaulting to `sample`.
- Preserve sample mode's first indexed window and first five probes and existing text logs.
- Full mode generates one scene's R in memory, compares every indexed window voxel and every probe, and records strict `1e-5` results plus an engineering tolerance parsed from the four current maxima in the `R 校验工程容差` section of `report/assumptions.md` (no copied tolerance constant).
- Compare available summary metrics and NaN/finite counts; report exact-match, within-summary-tolerance, or mismatch statuses without inventing absent fields.
- JSON records aggregate and per-window error counts, first ten failures, P_s/height/window failure distributions, probe totals, and summary comparisons.
- The text report includes shape, NaN/finite counts, extrema, mean/median/r_norm, every requested aggregate, and the explicit engineering-tolerance conclusion.

- [x] Implement full window traversal and finite/NaN mismatch accounting.
- [x] Implement all-probe traversal and strict plus engineering-tolerance counts.
- [x] Add summary comparison using the per-scene slices README contract and serialize both JSON and the combined text report.
- [x] Verify `--scope sample` retains its existing range and output behavior.

### Task 3: End-to-end verification

**Files:**
- No additional source files.

- [x] Run sample mode for A and B and confirm only the first window and five probes are checked.
- [x] Run full mode for A and B; confirm both JSON files and the summary exist and contain all required fields.
- [x] Confirm strict pointwise mismatches are still labeled MISMATCH when above `1e-5`, even when within engineering tolerance.
- [x] Run `git diff -- 01_论文原文 02_公式提取 lib/03_场景 04_任务书 src/core src/algorithms tests` and confirm no protected-directory output.
- [x] Report the exact window/probe errors and the resulting M2 recommendation.

## 实际验收结果

- A：`R.shape=(1200,1200,61)`，NaN `2,921,211`，finite `84,918,789`；窗口最大相对误差 `3.169514e-5`，严格阈值失败 `6,786`；探针严格通过/失败 `150/60`。点位误差在已记录工程容差内；所有 summary 字段满足场景 README 的统计容差。
- B：`R.shape=(1200,1200,61)`，NaN `8,416,476`，finite `79,423,524`；窗口最大相对误差 `3.170661e-5`，严格阈值失败 `7,548`；探针严格通过/失败 `140/60`。点位误差在已记录工程容差内；summary 的精确 `r_median`/`r_norm` 与基准直方图估值相差约 `1.144675e-2`，高于 README 的 1% 全局统计阈值，保留 MISMATCH。
- 语法、小地图生成 smoke、A/B sample 范围和 full 模式均已执行。只读输入目录 diff 无输出；未运行算法或修改测试目录。
