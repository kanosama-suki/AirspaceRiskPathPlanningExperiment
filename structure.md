# 项目结构与已完成工作

本文记录从目录骨架创建之后，本次对话中实际完成的文件、程序和只读检查结果。路径均相对于项目根目录 `C:\Users\kano\Desktop\ffjj`。

## 目录骨架

以下目录按 `plan.md` 的建议创建，目前只在有检查输出的目录中生成了文件：

| 路径 | 作用 | 当前状态 |
|---|---|---|
| `05_规划书/` | 规划书及后续执行记录目录 | 已创建，当前为空 |
| `src/` | 可复用程序代码根目录 | 已创建 |
| `src/core/` | 坐标、网格、碰撞和公共评估等核心模块预留目录 | 已创建，当前为空 |
| `src/risk/` | 风险数据读取、检查和校验程序目录 | 已创建，包含三个只读检查脚本 |
| `src/algorithms/` | 五种路径规划算法预留目录 | 已创建，当前为空 |
| `src/io/` | 配置、场景和结果读写模块预留目录 | 已创建，当前为空 |
| `tests/` | 单元测试和小地图测试预留目录 | 已创建，当前为空 |
| `experiments/` | 实验配置、原始结果、汇总表和图表目录 | 已创建 |
| `experiments/configs/` | 实验批次配置预留目录 | 已创建，当前为空 |
| `experiments/raw/` | 原始检查日志和 JSON 记录 | 已创建，包含 A/B 场景检查输出 |
| `experiments/tables/` | 实验汇总表预留目录 | 已创建，当前为空 |
| `experiments/figures/` | 图表输出预留目录 | 已创建，当前为空 |
| `report/` | 参数审计、假设和报告材料目录 | 已创建，包含两个审计文档 |

## 已完成工作

### 1. 目录初始化

根据 `plan.md` 的目录建议创建了上述 13 个目录。没有移动、删除或修改 `lib/03_场景/`、`lib/02_公式提取/`、`lib/04_任务书/` 下的输入文件。

### 2. 参数来源审计

读取了场景配置、场景数据契约、公式提取和规划书相关章节，建立了参数来源映射，并在后续核查中修正和扩充：

| 文件 | 作用 |
|---|---|
| `report/parameter_sources.md` | 记录参数名、来源文件、`config.json` 键路径、单位、候选使用模块和备注。覆盖配置文件的实际叶子键，并单列不来自配置的派生量。 |
| `report/assumptions.md` | 记录参数来源审计中的未决假设、六项危险项 D1-D6、`DESIGN` / `MISSING` / `OMITTED` 分类以及 M1 阻断结论。 |

审计补充了公式提取文件中定义但原表遗漏的 `P_f`，并把 `P_LOC` 与 `P_f` 的关系保留为待人工核对；同时将 `alpha/ALPHA`、`beta/BETA` 的符号映射标为未最终确认。

当前审计结论是不能进入 M1。主要阻断项是 `P_LOC` 与 `P_f` 的关系、alpha/beta 键映射、`T_1` 的阶段时间映射，以及综合代价中 `distance_cost` 的完整尺度未闭合。

### 3. 场景容器只读检查

| 文件 | 作用 |
|---|---|
| `src/risk/inspect_scene.py` | 只读读取配置指定的场景 `city.npz`、`slices/`、`ps_check/` 文件，输出键、数组形状、dtype、NaN/finite 统计、窗口和探针清单、summary 字段以及缺失项。它不计算 `P_s`，不生成或重算完整 `R`。 |
| `experiments/raw/inspect_A.txt` | 场景 A 的容器和校验文件事实报告。 |
| `experiments/raw/inspect_B.txt` | 场景 B 的容器和校验文件事实报告。 |

检查发现两个 `city.npz` 实际包含 `building_mask`、`pop_density`、`building_footprint` 和 `meta`，但没有完整 `R` 键。两个场景的窗口、探针、summary 和 `ps_check` 文件均可读取。

运行入口：

```powershell
python src/risk/inspect_scene.py `
  --config lib/03_场景/config.json `
  --output-dir experiments/raw `
  --scenes A B
```

### 4. 风险基准索引对齐检查

| 文件 | 作用 |
|---|---|
| `src/risk/verify_align.py` | 只读检查 summary、`index.json`、`win_*.npz`、`probe_points.csv` 和 `ps_check/` 是否能按数据契约读取和定位。窗口只打印自身统计和角点/中心值，不与完整 `R` 做逐点比较。 |
| `experiments/raw/align_A.txt` | 场景 A 的索引对齐日志，包含六个区段和三节结论。 |
| `experiments/raw/align_B.txt` | 场景 B 的索引对齐日志，包含六个区段和三节结论。 |

两个场景都满足窗口文件、探针文件和三类 `ps_check` 基准存在，窗口形状符合 README 契约，探针索引列存在。由于 `city.npz` 没有完整 `R`，summary 与实测 `R` 的对齐结论为 `MISMATCH`，不能进入下一版逐点 `verify.py`。

运行入口：

```powershell
python src/risk/verify_align.py `
  --config lib/03_场景/config.json `
  --output-dir experiments/raw `
  --scenes A B
```

### 5. 场景数据契约检查

| 文件 | 作用 |
|---|---|
| `src/risk/check_data_contract.py` | 只读执行九项契约检查：`R_shape`、`NaN_vs_building`、`building_mask_shape_vs_R`、`pop_density_shape`、`indexed_files_exist`、`summary_fields`、`ps_check_classes`、`window_indices_in_R_range`、`probe_indices_in_R_range`。它读取已有 inspect 报告作为缺失事实的辅助证据，不使用 summary 或窗口数据替代完整 `R`。 |
| `experiments/raw/contract_A.json` | 场景 A 的九项结构化检查结果。 |
| `experiments/raw/contract_B.json` | 场景 B 的九项结构化检查结果。 |

两个 JSON 均为 `PASS=4`、`FAIL=5`、`status=FAIL`。四项通过的是人口密度形状、索引文件和探针文件存在、summary 字段完整、`ps_check` 三类基准存在。五项失败都来自实际缺少完整 `R`：无法检查 `R` 形状、`R` NaN 与建筑掩码、建筑掩码与 `R` 形状、窗口索引范围以及探针索引范围。

运行入口：

```powershell
python src/risk/check_data_contract.py `
  --config lib/03_场景/config.json `
  --output-dir experiments/raw `
  --scenes A B
```

## 只读边界与验证

本次创建的三个程序都只读取配置、场景容器和已有校验基准；没有实现风险矩阵、没有计算遮蔽系数 `P_s`、没有重采样路径，也没有修改输入目录。已检查：

- `git diff -- lib/03_场景` 无输出；
- `git diff -- lib/02_公式提取` 无输出；
- `git diff -- lib/04_任务书` 无输出；
- 三个 Python 脚本均通过语法编译检查；
- A/B 两组日志和 JSON 输出均已生成。

当前项目还没有实现五种规划算法、公共路径评估器、风险矩阵生成器或实验运行器；`src/core/`、`src/algorithms/`、`src/io/`、`tests/` 和实验配置/汇总/图表目录仍是预留结构。
