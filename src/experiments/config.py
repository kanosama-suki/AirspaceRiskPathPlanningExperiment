"""实验配置的类型化加载、严格校验和配置哈希。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from string import Formatter
from tomllib import TOMLDecodeError, loads as parse_toml
from typing import Literal, TypeVar, cast
import math


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class AlgorithmConfig:
    """确定性算法与采样算法的唯一实验名单。"""

    deterministic: tuple[str, ...]
    sampling: tuple[str, ...]

    @property
    def all_algorithms(self) -> tuple[str, ...]:
        return self.deterministic + self.sampling


@dataclass(frozen=True, slots=True)
class SeedConfig:
    """两类随机性对应的实验 seed。"""

    deterministic: int
    sampling: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RoutePoolConfig:
    """候选路线生成参数。"""

    candidate_routes_per_scene: int
    route_seed: int


@dataclass(frozen=True, slots=True)
class RouteGroupConfig:
    """一个 S/M/L 距离组的抽样和预算参数。"""

    name: str
    target_percentile: float
    percentile_min: float
    percentile_max: float
    routes_per_scene: int
    time_budget_s: float
    max_iterations: int


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    """并发执行参数；命令行可以覆盖 worker 数与执行器。"""

    workers: int
    executor: Literal["process", "thread"]


@dataclass(frozen=True, slots=True)
class ValidationConfig:
    """统一路径复核参数。"""

    path_resample_spacing_m: float


@dataclass(frozen=True, slots=True)
class RunOutputConfig:
    """正式与冒烟运行输出规则。"""

    raw_root: str
    snapshot_dir: str
    per_run_template: str
    tables_root: str


@dataclass(frozen=True, slots=True)
class FormalConfig:
    """S/M/L 正式实验配置。"""

    experiment_name: str
    scene_config: str
    route_manifest: str
    algorithms: AlgorithmConfig
    seeds: SeedConfig
    route_pool: RoutePoolConfig
    route_groups: Mapping[str, RouteGroupConfig]
    execution: ExecutionConfig
    validation: ValidationConfig
    output: RunOutputConfig


@dataclass(frozen=True, slots=True)
class SmokeConfig:
    """单条冻结路线的数据流冒烟配置。"""

    experiment_name: str
    scene_config: str
    route_manifest: str
    algorithms: AlgorithmConfig
    seeds: SeedConfig
    time_budget_s: float
    max_iterations: int
    execution: ExecutionConfig
    validation: ValidationConfig
    output: RunOutputConfig


@dataclass(frozen=True, slots=True)
class CalibrationConfig:
    """预算与并行吞吐校准配置。"""

    experiment_name: str
    formal_config: str
    time_budgets_s: tuple[float, ...]
    pilot_time_budgets_s: tuple[float, ...]
    graph_timeout_s: float
    """快速模式图搜索安全截止；full 模式改用正式分组预算。"""
    max_iterations: int
    worker_candidates: tuple[int, ...]
    routes_per_scene_group: int
    sampling_seed_count: int
    raw_root: str
    summary_csv: str


ExperimentConfig = FormalConfig | SmokeConfig | CalibrationConfig
ConfigT = TypeVar("ConfigT")


@dataclass(frozen=True, slots=True)
class LoadedConfig:
    """配置对象、来源路径、原始字节和 SHA-256。"""

    config: ExperimentConfig
    source_path: Path
    raw_bytes: bytes
    sha256: str


def _require_keys(
    table: Mapping[str, object],
    *,
    required: set[str],
    optional: set[str] | None = None,
    label: str,
) -> None:
    """要求必需键齐全，并拒绝拼写错误产生的未知键。"""
    allowed = required | (optional or set())
    missing = sorted(required.difference(table))
    unknown = sorted(set(table).difference(allowed))
    if missing:
        raise ValueError(f"{label} 缺少键：{missing}")
    if unknown:
        raise ValueError(f"{label} 含未知键：{unknown}")


def _table(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} 必须是表对象。")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{label} 必须是非空字符串。")
    return value.strip()


def _integer(value: object, label: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} 必须是整数。")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} 必须大于等于 {minimum}。")
    return value


def _number(value: object, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} 必须是数值。")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{label} 必须是有限数值。")
    if positive and parsed <= 0:
        raise ValueError(f"{label} 必须是正数。")
    return parsed


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{label} 必须是字符串数组。")
    parsed = tuple(_string(item, f"{label}[{index}]") for index, item in enumerate(value))
    if not parsed:
        raise ValueError(f"{label} 不能为空。")
    if len(set(parsed)) != len(parsed):
        raise ValueError(f"{label} 不能包含重复项。")
    return parsed


def _integer_tuple(
    value: object,
    label: str,
    *,
    minimum: int = 0,
) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{label} 必须是整数数组。")
    parsed = tuple(
        _integer(item, f"{label}[{index}]", minimum=minimum)
        for index, item in enumerate(value)
    )
    if not parsed:
        raise ValueError(f"{label} 不能为空。")
    if len(set(parsed)) != len(parsed):
        raise ValueError(f"{label} 不能包含重复项。")
    return parsed


def _number_tuple(value: object, label: str) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{label} 必须是数值数组。")
    parsed = tuple(
        _number(item, f"{label}[{index}]", positive=True)
        for index, item in enumerate(value)
    )
    if not parsed:
        raise ValueError(f"{label} 不能为空。")
    if len(set(parsed)) != len(parsed):
        raise ValueError(f"{label} 不能包含重复项。")
    return parsed


def _parse_algorithms(value: object) -> AlgorithmConfig:
    table = _table(value, "algorithms")
    _require_keys(table, required={"deterministic", "sampling"}, label="algorithms")
    deterministic = _string_tuple(table["deterministic"], "algorithms.deterministic")
    sampling = _string_tuple(table["sampling"], "algorithms.sampling")
    overlap = sorted(set(deterministic).intersection(sampling))
    if overlap:
        raise ValueError(f"算法不能同时属于确定性和采样组：{overlap}")
    return AlgorithmConfig(deterministic=deterministic, sampling=sampling)


def _parse_seeds(value: object) -> SeedConfig:
    table = _table(value, "seeds")
    _require_keys(table, required={"deterministic", "sampling"}, label="seeds")
    return SeedConfig(
        deterministic=_integer(table["deterministic"], "seeds.deterministic", minimum=0),
        sampling=_integer_tuple(table["sampling"], "seeds.sampling"),
    )


def _parse_execution(value: object) -> ExecutionConfig:
    table = _table(value, "execution")
    _require_keys(table, required={"workers", "executor"}, label="execution")
    executor = _string(table["executor"], "execution.executor")
    if executor not in {"process", "thread"}:
        raise ValueError("execution.executor 只能是 `process` 或 `thread`。")
    return ExecutionConfig(
        workers=_integer(table["workers"], "execution.workers", minimum=1),
        executor=cast(Literal["process", "thread"], executor),
    )


def _parse_validation(value: object) -> ValidationConfig:
    table = _table(value, "validation")
    _require_keys(table, required={"path_resample_spacing_m"}, label="validation")
    return ValidationConfig(
        path_resample_spacing_m=_number(
            table["path_resample_spacing_m"],
            "validation.path_resample_spacing_m",
            positive=True,
        )
    )


def _parse_run_output(value: object) -> RunOutputConfig:
    table = _table(value, "output")
    _require_keys(
        table,
        required={"raw_root", "snapshot_dir", "per_run_template", "tables_root"},
        label="output",
    )
    template = _string(table["per_run_template"], "output.per_run_template")
    required_fields = {"scene", "group", "algorithm", "route_id", "seed"}
    try:
        used_fields = {
            field_name
            for _, field_name, _, _ in Formatter().parse(template)
            if field_name
        }
    except ValueError as error:
        raise ValueError(f"output.per_run_template 格式无效：{error}") from error
    missing_fields = sorted(required_fields.difference(used_fields))
    if missing_fields:
        raise ValueError(f"output.per_run_template 缺少字段：{missing_fields}")
    return RunOutputConfig(
        raw_root=_string(table["raw_root"], "output.raw_root"),
        snapshot_dir=_string(table["snapshot_dir"], "output.snapshot_dir"),
        per_run_template=template,
        tables_root=_string(table["tables_root"], "output.tables_root"),
    )


def _parse_route_pool(value: object) -> RoutePoolConfig:
    table = _table(value, "route_pool")
    _require_keys(
        table,
        required={"candidate_routes_per_scene", "route_seed"},
        label="route_pool",
    )
    return RoutePoolConfig(
        candidate_routes_per_scene=_integer(
            table["candidate_routes_per_scene"],
            "route_pool.candidate_routes_per_scene",
            minimum=1,
        ),
        route_seed=_integer(table["route_seed"], "route_pool.route_seed", minimum=0),
    )


def _parse_route_groups(value: object) -> Mapping[str, RouteGroupConfig]:
    table = _table(value, "route_groups")
    if set(table) != {"S", "M", "L"}:
        raise ValueError("正式配置的 route_groups 必须且只能包含 S、M、L。")
    groups: dict[str, RouteGroupConfig] = {}
    for name, group_value in table.items():
        group = _table(group_value, f"route_groups.{name}")
        _require_keys(
            group,
            required={
                "target_percentile",
                "percentile_min",
                "percentile_max",
                "routes_per_scene",
                "time_budget_s",
                "max_iterations",
            },
            label=f"route_groups.{name}",
        )
        target = _number(group["target_percentile"], f"route_groups.{name}.target_percentile")
        percentile_min = _number(group["percentile_min"], f"route_groups.{name}.percentile_min")
        percentile_max = _number(group["percentile_max"], f"route_groups.{name}.percentile_max")
        if not (0 <= percentile_min < target < percentile_max <= 100):
            raise ValueError(
                f"route_groups.{name} 必须满足 0 <= percentile_min < target_percentile "
                "< percentile_max <= 100。"
            )
        groups[name] = RouteGroupConfig(
            name=name,
            target_percentile=target,
            percentile_min=percentile_min,
            percentile_max=percentile_max,
            routes_per_scene=_integer(
                group["routes_per_scene"],
                f"route_groups.{name}.routes_per_scene",
                minimum=1,
            ),
            time_budget_s=_number(
                group["time_budget_s"],
                f"route_groups.{name}.time_budget_s",
                positive=True,
            ),
            max_iterations=_integer(
                group["max_iterations"],
                f"route_groups.{name}.max_iterations",
                minimum=1,
            ),
        )
    ranges = sorted(
        (group.percentile_min, group.percentile_max, group.name)
        for group in groups.values()
    )
    if ranges[0][1] > ranges[1][0] or ranges[1][1] > ranges[2][0]:
        raise ValueError("S/M/L 的百分位区间不能重叠。")
    return groups


def _common_values(
    payload: Mapping[str, object],
) -> tuple[
    str,
    str,
    str,
    AlgorithmConfig,
    SeedConfig,
    ValidationConfig,
]:
    return (
        _string(payload["experiment_name"], "experiment_name"),
        _string(payload["scene_config"], "scene_config"),
        _string(payload["route_manifest"], "route_manifest"),
        _parse_algorithms(payload["algorithms"]),
        _parse_seeds(payload["seeds"]),
        _parse_validation(payload["validation"]),
    )


def _parse_formal(payload: Mapping[str, object]) -> FormalConfig:
    _require_keys(
        payload,
        required={
            "experiment_kind",
            "experiment_name",
            "scene_config",
            "route_manifest",
            "algorithms",
            "seeds",
            "route_pool",
            "route_groups",
            "execution",
            "validation",
            "output",
        },
        label="formal 配置",
    )
    (
        experiment_name,
        scene_config,
        route_manifest,
        algorithms,
        seeds,
        validation,
    ) = _common_values(payload)
    return FormalConfig(
        experiment_name=experiment_name,
        scene_config=scene_config,
        route_manifest=route_manifest,
        algorithms=algorithms,
        seeds=seeds,
        route_pool=_parse_route_pool(payload["route_pool"]),
        route_groups=_parse_route_groups(payload["route_groups"]),
        execution=_parse_execution(payload["execution"]),
        validation=validation,
        output=_parse_run_output(payload["output"]),
    )


def _parse_smoke(payload: Mapping[str, object]) -> SmokeConfig:
    _require_keys(
        payload,
        required={
            "experiment_kind",
            "experiment_name",
            "scene_config",
            "route_manifest",
            "algorithms",
            "seeds",
            "budget",
            "execution",
            "validation",
            "output",
        },
        label="smoke 配置",
    )
    (
        experiment_name,
        scene_config,
        route_manifest,
        algorithms,
        seeds,
        validation,
    ) = _common_values(payload)
    budget = _table(payload["budget"], "budget")
    _require_keys(
        budget,
        required={"time_budget_s", "max_iterations"},
        label="budget",
    )
    if len(seeds.sampling) != 1:
        raise ValueError("smoke 配置必须只包含一个 sampling seed。")
    return SmokeConfig(
        experiment_name=experiment_name,
        scene_config=scene_config,
        route_manifest=route_manifest,
        algorithms=algorithms,
        seeds=seeds,
        time_budget_s=_number(budget["time_budget_s"], "budget.time_budget_s", positive=True),
        max_iterations=_integer(budget["max_iterations"], "budget.max_iterations", minimum=1),
        execution=_parse_execution(payload["execution"]),
        validation=validation,
        output=_parse_run_output(payload["output"]),
    )


def _parse_calibration(payload: Mapping[str, object]) -> CalibrationConfig:
    _require_keys(
        payload,
        required={
            "experiment_kind",
            "experiment_name",
            "formal_config",
            "sampling_budget",
            "worker_candidates",
            "calibration",
            "output",
        },
        label="calibration 配置",
    )
    sampling_budget = _table(payload["sampling_budget"], "sampling_budget")
    _require_keys(
        sampling_budget,
        required={"time_budgets_s", "pilot_time_budgets_s", "max_iterations"},
        label="sampling_budget",
    )
    worker_candidates = _table(payload["worker_candidates"], "worker_candidates")
    _require_keys(worker_candidates, required={"workers"}, label="worker_candidates")
    calibration = _table(payload["calibration"], "calibration")
    _require_keys(
        calibration,
        required={"routes_per_scene_group", "sampling_seed_count", "graph_timeout_s"},
        label="calibration",
    )
    output = _table(payload["output"], "output")
    _require_keys(output, required={"raw_root", "summary_csv"}, label="output")
    return CalibrationConfig(
        experiment_name=_string(payload["experiment_name"], "experiment_name"),
        formal_config=_string(payload["formal_config"], "formal_config"),
        time_budgets_s=_number_tuple(
            sampling_budget["time_budgets_s"],
            "sampling_budget.time_budgets_s",
        ),
        pilot_time_budgets_s=_number_tuple(
            sampling_budget["pilot_time_budgets_s"],
            "sampling_budget.pilot_time_budgets_s",
        ),
        graph_timeout_s=_number(
            calibration["graph_timeout_s"],
            "calibration.graph_timeout_s",
            positive=True,
        ),
        max_iterations=_integer(
            sampling_budget["max_iterations"],
            "sampling_budget.max_iterations",
            minimum=1,
        ),
        worker_candidates=_integer_tuple(
            worker_candidates["workers"],
            "worker_candidates.workers",
            minimum=1,
        ),
        routes_per_scene_group=_integer(
            calibration["routes_per_scene_group"],
            "calibration.routes_per_scene_group",
            minimum=1,
        ),
        sampling_seed_count=_integer(
            calibration["sampling_seed_count"],
            "calibration.sampling_seed_count",
            minimum=1,
        ),
        raw_root=_string(output["raw_root"], "output.raw_root"),
        summary_csv=_string(output["summary_csv"], "output.summary_csv"),
    )


def load_config(path: Path) -> LoadedConfig:
    """读取 TOML，按 ``experiment_kind`` 返回严格类型化配置。"""
    resolved_path = path.expanduser()
    if not resolved_path.is_absolute():
        resolved_path = PROJECT_ROOT / resolved_path
    resolved_path = resolved_path.resolve()
    raw_bytes = resolved_path.read_bytes()
    try:
        payload = parse_toml(raw_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, TOMLDecodeError) as error:
        raise ValueError(f"无法解析实验配置 {resolved_path}：{error}") from error
    if not isinstance(payload, Mapping):
        raise ValueError("实验配置顶层必须是 TOML 表。")
    kind = _string(payload.get("experiment_kind"), "experiment_kind")
    if kind == "formal":
        parsed: ExperimentConfig = _parse_formal(payload)
    elif kind == "smoke":
        parsed = _parse_smoke(payload)
    elif kind == "calibration":
        parsed = _parse_calibration(payload)
    else:
        raise ValueError("experiment_kind 只能是 `formal`、`smoke` 或 `calibration`。")
    return LoadedConfig(
        config=parsed,
        source_path=resolved_path,
        raw_bytes=raw_bytes,
        sha256=sha256(raw_bytes).hexdigest(),
    )
