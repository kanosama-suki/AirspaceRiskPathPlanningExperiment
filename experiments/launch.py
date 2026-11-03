"""命令行实验启动器：显示进度、ETA 和状态统计，并支持断点续跑。"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from time import monotonic
from typing import Any
import argparse
import json
import os
import subprocess
import sys

from experiments.run import MatrixTask, _filter_routes, _resolve_project_path, build_run_tasks
from src.experiments.config import FormalConfig, LoadedConfig, SmokeConfig, load_config
from src.experiments.route_generator import RouteSpec, load_route_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_PATH = PROJECT_ROOT / "experiments" / "validation" / "launcher_eta_profile.json"
FINISHED_STATUSES = {"success", "timeout_with_solution", "timeout_no_solution", "no_path", "invalid"}
TaskKey = tuple[str, str, str, str, int]


@dataclass(frozen=True, slots=True)
class LaunchPlan:
    """一次启动对应的配置、路线、任务和子进程命令。"""

    loaded: LoadedConfig
    selected_routes: tuple[RouteSpec, ...]
    tasks: tuple[MatrixTask, ...]
    workers: int
    executor_kind: str
    run_id: str
    command: tuple[str, ...]


def task_key(record: Mapping[str, object]) -> TaskKey:
    """从任务或原始记录中提取唯一运行键。"""
    return (
        str(record["scene"]),
        str(record["group"]),
        str(record["route_id"]),
        str(record["algorithm"]),
        int(record["seed"]),
    )


def matrix_task_key(task: MatrixTask) -> TaskKey:
    """返回矩阵任务的唯一运行键。"""
    return (
        task.route.scene,
        task.route.route_group,
        task.route.route_id,
        task.algorithm,
        task.seed,
    )


def _config_path(value: str | None, *, smoke: bool) -> Path:
    """解析启动器默认配置。"""
    if value is not None:
        return Path(value)
    return Path(
        "experiments/configs/smoke.toml"
        if smoke
        else "experiments/configs/formal.toml"
    )


def _run_id(value: str | None, *, smoke: bool) -> str:
    """返回可重复使用的批次 ID；同名批次默认可断点续跑。"""
    selected = value or ("sml-smoke-v1" if smoke else "sml-formal-v1")
    if Path(selected).name != selected or selected in {".", ".."}:
        raise ValueError("run_id 只能是单段标识，不能包含路径。")
    return selected


def _child_command(
    config_path: Path,
    *,
    scope: str,
    workers: int,
    executor_kind: str,
    run_id: str,
    scenes: Sequence[str] | None,
    groups: Sequence[str] | None,
    route_ids: Sequence[str] | None,
) -> tuple[str, ...]:
    """构造正式运行器命令，保证启动器与子进程使用同一参数。"""
    command = [
        sys.executable,
        "-u",
        "-m",
        "experiments.run",
        "--config",
        str(config_path),
        "--scope",
        scope,
        "--workers",
        str(workers),
        "--executor",
        executor_kind,
        "--run-id",
        run_id,
    ]
    if scenes:
        command.extend(("--scene", *scenes))
    if groups:
        command.extend(("--group", *groups))
    if route_ids:
        command.extend(("--route-id", *route_ids))
    return tuple(command)


def build_launch_plan(
    config_path: Path,
    *,
    scope: str,
    workers: int | None,
    executor_kind: str | None,
    run_id: str | None,
    scenes: Sequence[str] | None = None,
    groups: Sequence[str] | None = None,
    route_ids: Sequence[str] | None = None,
    smoke: bool = False,
) -> LaunchPlan:
    """加载配置和冻结路线，展开与 experiments.run 完全一致的任务清单。"""
    loaded = load_config(config_path)
    config = loaded.config
    if not isinstance(config, (FormalConfig, SmokeConfig)):
        raise TypeError("启动器只接受 formal 或 smoke 配置。")
    if smoke and not isinstance(config, SmokeConfig):
        raise TypeError("--smoke 必须配合 smoke 配置。")

    selected_workers = config.execution.workers if workers is None else workers
    selected_executor = config.execution.executor if executor_kind is None else executor_kind
    if selected_workers < 1:
        raise ValueError("worker 数必须是正整数。")
    if selected_executor not in {"process", "thread"}:
        raise ValueError("executor 只能是 process 或 thread。")

    route_path = _resolve_project_path(config.route_manifest, "route_manifest")
    routes = load_route_manifest(route_path)
    selected_routes = _filter_routes(
        routes,
        scene_names=scenes,
        group_names=groups,
        route_ids=route_ids,
        scope=scope,
    )
    selected_run_id = _run_id(run_id, smoke=isinstance(config, SmokeConfig))
    scene_hashes = {
        scene: "launcher-preview"
        for scene in sorted({route.scene for route in selected_routes})
    }
    tasks = build_run_tasks(
        config,
        selected_routes,
        scene_config_hashes=scene_hashes,
        experiment_config_hash=loaded.sha256,
        output=config.output,
        workers=selected_workers,
        executor_kind=selected_executor,
        run_id=selected_run_id,
        run_kind="smoke" if isinstance(config, SmokeConfig) else "matrix",
        spacing_m=config.validation.path_resample_spacing_m,
    )
    command = _child_command(
        loaded.source_path,
        scope=scope,
        workers=selected_workers,
        executor_kind=selected_executor,
        run_id=selected_run_id,
        scenes=scenes,
        groups=groups,
        route_ids=route_ids,
    )
    return LaunchPlan(
        loaded=loaded,
        selected_routes=selected_routes,
        tasks=tuple(tasks),
        workers=selected_workers,
        executor_kind=selected_executor,
        run_id=selected_run_id,
        command=command,
    )


def _identity_matches(
    record: Mapping[str, object],
    task: MatrixTask,
) -> bool:
    """核对已有记录是否属于当前任务和当前实验配置。"""
    return (
        record.get("scene") == task.route.scene
        and record.get("group") == task.route.route_group
        and record.get("route_id") == task.route.route_id
        and record.get("algorithm") == task.algorithm
        and record.get("seed") == task.seed
        and record.get("experiment_config_hash") == task.experiment_config_hash
    )


def load_completed_records(tasks: Sequence[MatrixTask]) -> dict[TaskKey, Mapping[str, object]]:
    """读取断点续跑会跳过的记录，并拒绝损坏或配置不匹配的文件。"""
    completed: dict[TaskKey, Mapping[str, object]] = {}
    for task in tasks:
        if not task.record_path.exists():
            continue
        matching: Mapping[str, object] | None = None
        for line in task.record_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"已有原始记录含损坏 JSON：{task.record_path}") from error
            if not isinstance(candidate, Mapping):
                raise TypeError(f"已有原始记录不是 JSON 对象：{task.record_path}")
            if _identity_matches(candidate, task):
                matching = candidate
        if matching is None:
            raise ValueError(f"已有原始记录身份或配置哈希不匹配：{task.record_path}")
        completed[matrix_task_key(task)] = matching
    return completed


def _load_profile(path: Path | None) -> dict[tuple[str, str, str], float]:
    """读取可选 ETA 画像；格式错误时回退为运行中统计，不中断实验。"""
    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        table = payload["runtime_seconds"]
        profile: dict[tuple[str, str, str], float] = {}
        for scene, group_table in table.items():
            for group, algorithm_table in group_table.items():
                for algorithm, value in algorithm_table.items():
                    runtime = float(value)
                    if runtime > 0:
                        profile[(str(scene), str(group), str(algorithm))] = runtime
        return profile
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
        return {}


def format_duration(seconds: float | None) -> str:
    """把秒数格式化为紧凑的时分秒文本。"""
    if seconds is None or not (seconds >= 0):
        return "估算中"
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class ProgressState:
    """累计实时事件、状态分布和按实际吞吐修正的 ETA。"""

    def __init__(
        self,
        tasks: Sequence[MatrixTask],
        completed: Mapping[TaskKey, Mapping[str, object]],
        *,
        workers: int,
        profile: Mapping[tuple[str, str, str], float],
    ) -> None:
        self.tasks = tuple(tasks)
        self.tasks_by_key = {matrix_task_key(task): task for task in self.tasks}
        self.completed_keys = set(completed)
        self.statuses: Counter[str] = Counter(
            str(record.get("status", "unknown")) for record in completed.values()
        )
        self.observed_runtimes: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        for record in completed.values():
            self._remember_runtime(record)
        self.workers = workers
        self.profile = dict(profile)
        self.new_work_seconds = 0.0
        self.new_runtime_count = 0
        self.current = "等待启动"

    def _remember_runtime(self, record: Mapping[str, object]) -> None:
        runtime = record.get("runtime_s")
        if not isinstance(runtime, (int, float)):
            return
        value = float(runtime)
        if value <= 0:
            return
        key = (str(record["scene"]), str(record["group"]), str(record["algorithm"]))
        self.observed_runtimes[key].append(value)

    def record_event(self, record: Mapping[str, object]) -> None:
        """接收一条完成事件；重复事件只更新状态，不重复计数。"""
        key = task_key(record)
        if key not in self.tasks_by_key:
            raise ValueError(f"运行器返回了任务清单之外的记录：{key}")
        status = str(record.get("status", "unknown"))
        self.current = f"{key[0]}/{key[1]}/{key[3]} seed={key[4]} -> {status}"
        if key in self.completed_keys:
            return
        self.completed_keys.add(key)
        self.statuses[status] += 1
        runtime = record.get("runtime_s")
        if isinstance(runtime, (int, float)) and float(runtime) > 0:
            value = float(runtime)
            self.new_work_seconds += value
            self.new_runtime_count += 1
            self._remember_runtime(record)

    def _mean(self, values: Sequence[float]) -> float | None:
        return sum(values) / len(values) if values else None

    def _estimate_runtime(self, task: MatrixTask) -> float:
        exact_key = (task.route.scene, task.route.route_group, task.algorithm)
        exact = self._mean(self.observed_runtimes.get(exact_key, ()))
        if exact is not None:
            return exact

        group_values = [
            value
            for (scene, group, _), values in self.observed_runtimes.items()
            if (scene, group) == (task.route.scene, task.route.route_group)
            for value in values
        ]
        group_mean = self._mean(group_values)
        if group_mean is not None:
            return group_mean

        profile_value = self.profile.get(exact_key)
        if profile_value is not None:
            return profile_value

        all_values = [
            value
            for values in self.observed_runtimes.values()
            for value in values
        ]
        observed_mean = self._mean(all_values)
        if observed_mean is not None:
            return observed_mean

        if task.iteration_budget is not None:
            return min(float(task.time_budget_s), max(5.0, task.iteration_budget / 900.0))
        graph_estimate = {"S": 20.0, "M": 120.0, "L": 600.0}
        return min(float(task.time_budget_s), graph_estimate.get(task.route.route_group, 120.0))

    def eta_seconds(self, elapsed_s: float) -> float | None:
        remaining = [
            task
            for task in self.tasks
            if matrix_task_key(task) not in self.completed_keys
        ]
        if not remaining:
            return 0.0
        remaining_work = sum(self._estimate_runtime(task) for task in remaining)
        if self.new_work_seconds > 0 and elapsed_s > 0:
            effective_workers = self.new_work_seconds / elapsed_s
            if self.new_runtime_count < self.workers:
                return None
            return remaining_work / max(effective_workers, 0.25)
        return remaining_work / max(self.workers, 1)

    def render(self, elapsed_s: float) -> str:
        total = len(self.tasks)
        completed = len(self.completed_keys)
        percent = 100.0 * completed / total if total else 100.0
        statuses = ",".join(
            f"{name}={self.statuses.get(name, 0)}"
            for name in ("success", "timeout_with_solution", "timeout_no_solution", "no_path", "invalid")
        )
        eta = format_duration(self.eta_seconds(elapsed_s))
        return (
            f"进度 {completed}/{total} ({percent:5.1f}%) | "
            f"已用 {format_duration(elapsed_s)} | 预计剩余 {eta} | "
            f"{statuses} | {self.current}"
        )


def _print_plan(
    plan: LaunchPlan,
    completed: Mapping[TaskKey, Mapping[str, object]],
    *,
    profile_path: Path | None,
) -> None:
    """打印启动前复核信息。"""
    config = plan.loaded.config
    print("城市空域风险路径规划实验")
    print(f"配置：{plan.loaded.source_path}")
    print(f"配置哈希：{plan.loaded.sha256}")
    print(f"实验：{config.experiment_name}")
    print(
        f"范围：{len(plan.selected_routes)} 条路线；"
        f"{len(plan.tasks)} 个任务；已完成 {len(completed)}；"
        f"待运行 {len(plan.tasks) - len(completed)}"
    )
    print(f"并行：{plan.executor_kind}；workers={plan.workers}；run_id={plan.run_id}")
    if isinstance(config, FormalConfig):
        for name in ("S", "M", "L"):
            group = config.route_groups[name]
            print(
                f"{name}：每场景 {group.routes_per_scene} 条；"
                f"时间预算 {group.time_budget_s:g} s；"
                f"采样上限 {group.max_iterations:,} 次"
            )
    raw_root = _resolve_project_path(config.output.raw_root, "raw_root")
    print(f"原始输出：{raw_root}")
    print(f"ETA 画像：{profile_path if profile_path and profile_path.is_file() else '未找到，使用运行中统计'}")
    print(f"启动命令：{subprocess.list2cmdline(plan.command)}")


def _reader(pipe: Any, output: Queue[str | None]) -> None:
    """在线程中读取子进程输出，避免阻塞定时进度刷新。"""
    try:
        for line in pipe:
            output.put(line.rstrip("\r\n"))
    finally:
        output.put(None)


def _event_from_line(line: str) -> Mapping[str, object] | None:
    """识别运行器输出的单行完成事件。"""
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, Mapping):
        return None
    required = {"scene", "group", "route_id", "algorithm", "seed", "status"}
    return payload if required.issubset(payload) else None


def run_and_monitor(
    plan: LaunchPlan,
    *,
    refresh_seconds: float,
    profile_path: Path | None,
) -> int:
    """启动 experiments.run，并持续输出进度、ETA 和累计状态。"""
    completed = load_completed_records(plan.tasks)
    state = ProgressState(
        plan.tasks,
        completed,
        workers=plan.workers,
        profile=_load_profile(profile_path),
    )
    if not plan.tasks:
        raise ValueError("任务清单为空，无法启动实验。")

    _print_plan(plan, completed, profile_path=profile_path)
    if len(completed) == len(plan.tasks):
        print("全部任务已有有效记录，无需重新运行。")
        return 0

    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    child = subprocess.Popen(
        plan.command,
        cwd=PROJECT_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    if child.stdout is None:
        raise RuntimeError("无法读取实验子进程输出。")

    output: Queue[str | None] = Queue()
    reader = Thread(target=_reader, args=(child.stdout, output), daemon=True)
    reader.start()
    started = monotonic()
    last_render = 0.0
    terminal = sys.stdout.isatty()
    try:
        while True:
            try:
                line = output.get(timeout=max(0.2, refresh_seconds))
            except Empty:
                line = ""
            if line is None:
                break
            event = _event_from_line(line)
            if event is not None:
                state.record_event(event)
            elif line:
                if terminal:
                    print()
                print(line)
                terminal = False
            now = monotonic()
            if now - last_render >= refresh_seconds:
                text = state.render(now - started)
                if terminal:
                    print(f"\r{text:<160}", end="", flush=True)
                else:
                    print(text, flush=True)
                last_render = now
        return_code = child.wait()
    except KeyboardInterrupt:
        child.terminate()
        return_code = child.wait(timeout=30)
        print(f"\n已中断。再次运行同一命令会从现有原始记录继续；退出码 {return_code}。")
        return 130
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=30)

    elapsed = monotonic() - started
    text = state.render(elapsed)
    if terminal:
        print(f"\r{text:<160}")
    else:
        print(text)
    if return_code == 0 and len(state.completed_keys) == len(plan.tasks):
        print(f"实验完成，用时 {format_duration(elapsed)}。")
    elif return_code == 0:
        print("运行器正常退出，但仍有任务记录缺失。")
    else:
        print(f"实验异常退出，退出码 {return_code}。可运行同一命令续跑。")
    return return_code


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析启动范围、并发和进度显示参数。"""
    parser = argparse.ArgumentParser(
        description="一键启动实验，并显示命令行进度、ETA、成功率和失败统计。",
    )
    parser.add_argument("--config", type=Path, help="实验配置；默认 formal.toml")
    parser.add_argument("--smoke", action="store_true", help="使用 smoke.toml")
    parser.add_argument(
        "--scope",
        choices=("sample", "full"),
        default="full",
        help="full 遍历全部路线；sample 每场景/组取首条路线",
    )
    parser.add_argument("--scene", dest="scenes", nargs="+", help="只运行指定场景")
    parser.add_argument("--group", dest="groups", nargs="+", help="只运行指定距离组")
    parser.add_argument("--route-id", dest="route_ids", nargs="+", help="只运行指定路线")
    parser.add_argument("--workers", type=int, help="并行 worker 数")
    parser.add_argument("--executor", choices=("process", "thread"), help="并行执行器")
    parser.add_argument("--run-id", help="批次标识；相同配置重跑会自动续跑")
    parser.add_argument(
        "--profile",
        type=Path,
        default=DEFAULT_PROFILE_PATH,
        help="可选 ETA 画像 JSON",
    )
    parser.add_argument(
        "--refresh-seconds",
        type=float,
        default=10.0,
        help="进度刷新间隔，默认 10 秒",
    )
    parser.add_argument("--dry-run", action="store_true", help="只显示任务计划和已有进度")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """命令行入口。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = _parse_args(argv)
    if args.refresh_seconds <= 0:
        raise ValueError("--refresh-seconds 必须大于 0。")
    config_path = _config_path(
        str(args.config) if args.config is not None else None,
        smoke=args.smoke,
    )
    plan = build_launch_plan(
        config_path,
        scope=args.scope,
        workers=args.workers,
        executor_kind=args.executor,
        run_id=args.run_id,
        scenes=args.scenes,
        groups=args.groups,
        route_ids=args.route_ids,
        smoke=args.smoke,
    )
    if args.dry_run:
        completed = load_completed_records(plan.tasks)
        _print_plan(plan, completed, profile_path=args.profile)
        state = ProgressState(
            plan.tasks,
            completed,
            workers=plan.workers,
            profile=_load_profile(args.profile),
        )
        print(state.render(0.0))
        return 0
    return run_and_monitor(
        plan,
        refresh_seconds=args.refresh_seconds,
        profile_path=args.profile,
    )


if __name__ == "__main__":
    raise SystemExit(main())
