"""提供风险模型中间量、单点计算与全量风险矩阵生成。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import math

import numpy as np

from .ps import compute_ps


def compute_crash_energy(mass: float, velocity: Sequence[float]) -> float:
    """按 B 式 (7) 计算撞击动能；质量单位 kg、速度单位 m/s、能量单位 J。"""
    if mass <= 0:
        raise ValueError("无人机质量必须大于零。")
    if len(velocity) == 0:
        raise ValueError("撞击速度向量不能为空。")

    speed_squared = math.fsum(float(component) ** 2 for component in velocity)
    return 0.5 * mass * speed_squared


def compute_correction_k(E_crash: float, beta: float, P_s: float) -> float:
    """按 B 式 (8) 计算校正因子；能量单位 J，P_s 无量纲，输出无量纲。"""
    if E_crash < 0:
        raise ValueError("撞击能量不能为负数。")
    if beta <= 0:
        raise ValueError("致死能量阈值 beta 必须大于零。")
    if P_s < 0:
        raise ValueError("遮蔽系数 P_s 不能为负数。")
    if E_crash <= beta:
        return 1.0
    if P_s == 0:
        # P_s 趋近于零且 E_crash 大于 beta 时，(beta/E_crash)^(3/P_s) 趋近于零。
        return 0.0

    return min(1.0, (beta / E_crash) ** (3.0 / P_s))


def compute_fatality_rate(P_s: float, E_crash: float, alpha: float, beta: float) -> float:
    """按 B 式 (6)、(8)、(9) 计算致死率；P_s 无量纲，能量单位 J，输出概率。"""
    if P_s < 0:
        raise ValueError("遮蔽系数 P_s 不能为负数。")
    if E_crash < 0:
        raise ValueError("撞击能量不能为负数。")
    if alpha <= 0 or beta <= 0:
        raise ValueError("alpha 和 beta 必须大于零。")
    if E_crash <= beta:
        return 0.0
    if P_s == 0:
        # B 式 (9) 给出 P_s 趋近于零时、超阈值撞击的全暴露极限。
        return 1.0

    ratio_power = (beta / E_crash) ** (3.0 / P_s)
    correction = compute_correction_k(E_crash, beta, P_s)
    denominator = 1.0 - 2.0 * correction + math.sqrt(alpha / beta) * ratio_power
    if denominator == 0:
        raise ZeroDivisionError("致死率公式的分母为零。")

    return (1.0 - correction) / denominator


def _compute_casualty_area(r_p: float, r_u: float, h_p: float, v_x: float, v_y: float) -> float:
    """按 B 式 (11)(12)(21) 的几何项计算伤亡面积；长度单位 m，面积单位 m²。"""
    if r_p < 0 or r_u < 0 or h_p < 0:
        raise ValueError("半径和人员高度不能为负数。")
    if v_y == 0:
        raise ValueError("竖直撞击速度不能为零。")

    impact_distance = h_p * abs(v_x) / abs(v_y)
    combined_radius = r_p + r_u
    return 2.0 * combined_radius * impact_distance + math.pi * combined_radius**2


def compute_casualty_area_ballistic(
    r_p: float,
    r_u: float,
    h_p: float,
    v_x: float,
    v_y: float,
) -> float:
    """按 B 式 (11)(12) 计算弹道伤亡面积；参数为 m、m/s，返回 m²。"""
    return _compute_casualty_area(r_p, r_u, h_p, v_x, v_y)


def compute_parachute_terminal_velocity(
    mass: float,
    gravity: float,
    rho: float,
    c_d_p: float,
    s_p: float,
) -> float:
    """按 B 式 (22) 计算开伞终端速度；输入 SI 单位，返回 m/s。"""
    if mass <= 0 or gravity <= 0 or rho <= 0 or c_d_p <= 0 or s_p <= 0:
        raise ValueError("质量、重力、空气密度、阻力系数和伞面面积必须大于零。")

    return math.sqrt(2.0 * mass * gravity / (rho * c_d_p * s_p))


def compute_casualty_area_parachute(
    r_p: float,
    r_u: float,
    h_p: float,
    v_x: float,
    v_y: float,
) -> float:
    """按 B 式 (21) 与式 (11) 的几何项计算开伞伤亡面积；输入 m、m/s，返回 m²。"""
    return _compute_casualty_area(r_p, r_u, h_p, v_x, v_y)


def compute_mitigation_Mp(A_c_b: float, A_c_p: float, P_f_b: float, P_f_p: float) -> float:
    """按 B 式 (31) 计算 M_p；面积单位 m²，致死率无量纲，输出无量纲。"""
    if A_c_b <= 0:
        raise ValueError("弹道伤亡面积 A_c_b 必须大于零。")
    if P_f_b == 0:
        raise ZeroDivisionError("B 式 (31) 的弹道致死率 P_f,b 为零，M_p 比值无定义。")

    return (A_c_p * P_f_p) / (A_c_b * P_f_b)


def compute_mitigation_Ms(P_s: float, E_crash: float, alpha: float, beta: float) -> float:
    """按 B 式 (31) 计算 M_s=P_f,b；P_s 无量纲、能量单位 J，输出无量纲。"""
    return compute_fatality_rate(P_s, E_crash, alpha, beta)


def compute_mitigation_M(
    M_p: float,
    M_s: float,
    E_crash_b: float,
    E_crash_p: float,
    beta: float,
    eta: float,
) -> float:
    """按 B 式 (34) 合成 M1/M2；能量单位 J，eta 与输出均无量纲。"""
    if beta <= 0:
        raise ValueError("致死能量阈值 beta 必须大于零。")
    if not 0.0 <= eta <= 1.0:
        raise ValueError("降落伞展开成功率 eta 必须位于 [0, 1]。")
    if E_crash_b <= beta:
        return 0.0
    if E_crash_p >= beta:
        return eta * M_p * M_s + (1.0 - eta) * M_s
    if E_crash_b > beta >= E_crash_p:
        return (1.0 - eta) * M_s
    return 0.0


def compute_final_R_point(
    pop_density: float,
    A_c_b: float,
    M: float,
    P_LOC: float,
    is_building: bool,
) -> float:
    """按 A 式 (5)–(8) 与 B 式 (35)–(37) 计算单点 R；输出 casualties/(flight hour)。"""
    if is_building:
        return float(np.nan)
    if pop_density < 0 or A_c_b < 0 or P_LOC < 0:
        raise ValueError("人口密度、伤亡面积和 P(LOC) 不能为负数。")

    # B 式 (10) 的未缓解固有量为 D_p * A_c,b；A 式再乘 P(LOC)。
    return P_LOC * pop_density * A_c_b * M


def ballistic_impact_components(
    height: float,
    mass: float,
    v_cruise: float,
    gravity: float,
    rho: float,
    c_d_u: float,
    s_u: float,
) -> tuple[float, float]:
    """返回弹道水平/竖直撞击速度；高度 m、质量 kg、速度 m/s，其余 SI 单位。"""
    if height <= 0 or mass <= 0 or v_cruise < 0 or gravity <= 0 or rho <= 0 or c_d_u <= 0 or s_u <= 0:
        raise ValueError("弹道运动参数必须满足正高度、正质量和正物理参数。")

    # 场景摘要将竖直速度简化为自由落体；式 (16) 用相同自由落体时间计算水平阻力衰减。
    fall_time = math.sqrt(2.0 * height / gravity)
    drag_area = rho * c_d_u * s_u
    horizontal = (2.0 * mass * v_cruise) / (drag_area * v_cruise * fall_time + 2.0 * mass)
    vertical = math.sqrt(2.0 * gravity * height)
    return horizontal, vertical


def _log_cosh(value: float) -> float:
    """稳定计算 log(cosh(value))。"""
    absolute = abs(value)
    return absolute + math.log1p(math.exp(-2.0 * absolute)) - math.log(2.0)


def _log_sinh_positive(value: float) -> float:
    """稳定计算正数输入的 log(sinh(value))。"""
    if value <= 0:
        raise ValueError("log(sinh(x)) 需要 x 大于零。")
    return value + math.log1p(-math.exp(-2.0 * value)) - math.log(2.0)


def _acosh_exp(log_value: float) -> float:
    """在 log 域计算 acosh(exp(log_value))。"""
    if log_value < 0:
        raise ValueError("acosh(exp(x)) 的输入要求 x 非负。")
    return log_value + math.log1p(math.sqrt(max(0.0, 1.0 - math.exp(-2.0 * log_value))))


def _asinh_exp(log_value: float) -> float:
    """在 log 域计算 asinh(exp(log_value))。"""
    return log_value + math.log1p(math.sqrt(1.0 + math.exp(-2.0 * log_value)))


def parachute_impact_components(
    height: float,
    mass: float,
    v_cruise: float,
    gravity: float,
    rho: float,
    c_d_u: float,
    s_u: float,
    c_d_p: float,
    s_p: float,
    deployment_time: float,
) -> tuple[float, float, float]:
    """返回开伞撞击速度与总时间；按 B 式(19)(20)使用失效后的全局时间，输入 SI 单位。"""
    if height <= 0 or mass <= 0 or v_cruise < 0 or gravity <= 0 or rho <= 0:
        raise ValueError("开伞运动参数必须满足正高度、正质量和正物理参数。")
    if c_d_u <= 0 or s_u <= 0 or c_d_p <= 0 or s_p <= 0 or deployment_time < 0:
        raise ValueError("阻力参数必须大于零，开伞时间不能为负数。")

    parachute_terminal = compute_parachute_terminal_velocity(mass, gravity, rho, c_d_p, s_p)
    ballistic_drag = rho * c_d_u * s_u
    ballistic_lambda = math.sqrt(gravity * ballistic_drag / (2.0 * mass))
    ballistic_terminal = math.sqrt(2.0 * mass * gravity / ballistic_drag)
    ballistic_scale = 2.0 * mass / ballistic_drag

    horizontal_at_deployment = (
        2.0 * mass * v_cruise
        / (ballistic_drag * v_cruise * deployment_time + 2.0 * mass)
    )
    vertical_at_deployment = ballistic_terminal * math.tanh(ballistic_lambda * deployment_time)
    drop_before_deployment = ballistic_scale * _log_cosh(ballistic_lambda * deployment_time)

    if drop_before_deployment >= height:
        horizontal, vertical = ballistic_impact_components(
            height, mass, v_cruise, gravity, rho, c_d_u, s_u
        )
        return horizontal, vertical, math.sqrt(2.0 * height / gravity)

    remaining_height = height - drop_before_deployment
    parachute_drag = rho * c_d_p * s_p
    parachute_lambda = math.sqrt(gravity * parachute_drag / (2.0 * mass))
    parachute_scale = 2.0 * mass / parachute_drag

    # 论文式(19)(20)把第二阶段时间写成全局 t，并在 t1 到 t2 上积分；
    # 因此这里的时间参数直接用失效后的绝对秒数，不再减去开伞时刻。
    vertical_ratio = vertical_at_deployment / parachute_terminal
    if math.isclose(vertical_ratio, 1.0, rel_tol=1e-12, abs_tol=0.0):
        vertical_branch = "terminal"
        vertical_offset = 0.0
    elif vertical_ratio < 1.0:
        vertical_branch = "tanh"
        vertical_offset = math.atanh(vertical_ratio)
    else:
        # 本场景开伞时的下降速度可能高于开伞终端速度；原式的 arctanh
        # 此时没有实数值，采用同一运动方程的 arccoth 实数分支。
        vertical_branch = "coth"
        vertical_offset = 0.5 * math.log(
            (vertical_ratio + 1.0) / (vertical_ratio - 1.0)
        )

    def vertical_speed_at(time_from_failure: float) -> float:
        """按全局时间计算式(19)第二阶段竖直速度。"""
        if vertical_branch == "terminal":
            return parachute_terminal
        argument = parachute_lambda * time_from_failure + vertical_offset
        if vertical_branch == "tanh":
            return parachute_terminal * math.tanh(argument)
        return parachute_terminal / math.tanh(argument)

    def vertical_displacement_from_deployment(time_from_failure: float) -> float:
        """计算式(20)中 t1 至当前全局时刻的第二阶段竖直位移。"""
        if vertical_branch == "terminal":
            return parachute_terminal * (time_from_failure - deployment_time)
        start_argument = parachute_lambda * deployment_time + vertical_offset
        end_argument = parachute_lambda * time_from_failure + vertical_offset
        if vertical_branch == "tanh":
            log_ratio = _log_cosh(end_argument) - _log_cosh(start_argument)
        else:
            log_ratio = _log_sinh_positive(end_argument) - _log_sinh_positive(start_argument)
        return parachute_scale * log_ratio

    # 通过 y_d(t2)=height 解撞地时刻；t2 不是固定飞行时长。
    lower_time = deployment_time
    upper_time = deployment_time + 1.0
    while vertical_displacement_from_deployment(upper_time) < remaining_height:
        upper_time = deployment_time + 2.0 * (upper_time - deployment_time)
    for _ in range(80):
        midpoint_time = (lower_time + upper_time) / 2.0
        if vertical_displacement_from_deployment(midpoint_time) < remaining_height:
            lower_time = midpoint_time
        else:
            upper_time = midpoint_time
    impact_time = (lower_time + upper_time) / 2.0

    # 式(19)的水平速度和式(20)的水平位移均使用 t1 到 t2 的全局时间。
    horizontal_at_impact = (
        2.0 * mass * horizontal_at_deployment
        / (parachute_drag * horizontal_at_deployment * impact_time + 2.0 * mass)
    )
    vertical_at_impact = vertical_speed_at(impact_time)
    horizontal_displacement_first = ballistic_scale * math.log(
        (ballistic_drag * v_cruise * deployment_time + 2.0 * mass) / (2.0 * mass)
    )
    horizontal_displacement_second = (2.0 * mass / parachute_drag) * math.log(
        (parachute_drag * horizontal_at_deployment * impact_time + 2.0 * mass)
        / (parachute_drag * horizontal_at_deployment * deployment_time + 2.0 * mass)
    )
    # 按式(20)形成两阶段水平总位移；d_p 仍按式(21)使用撞击瞬时速度比。
    _horizontal_displacement = horizontal_displacement_first + horizontal_displacement_second

    return horizontal_at_impact, vertical_at_impact, impact_time


def _prepare_layer_model(
    height: float,
    table1: Mapping[str, Any],
    supplementary: Mapping[str, Any],
) -> dict[str, float]:
    """预计算同一高度层共享的弹道与开伞中间量。"""
    mass = float(table1["MASS"])
    gravity = float(table1["G"])
    cruise_speed = float(table1["V_CRUISE"])
    rho = float(supplementary["RHO"])
    c_d_u = float(supplementary["C_D_U"])
    s_u = float(supplementary["S_U"])
    c_d_p = float(supplementary["C_D_P"])
    s_p = float(supplementary["S_P"])
    r_p = float(supplementary["R_P"])
    r_u = float(supplementary["R_U"])
    h_p = float(supplementary["H_P"])

    # 此处沿用局部校验器已使用的中间量链，公式实现保持不变。
    ballistic_vx, ballistic_vy = ballistic_impact_components(
        height, mass, cruise_speed, gravity, rho, c_d_u, s_u
    )
    ballistic_energy = compute_crash_energy(mass, (0.0, ballistic_vy))
    ballistic_area = compute_casualty_area_ballistic(
        r_p, r_u, h_p, ballistic_vx, ballistic_vy
    )

    parachute_vx, parachute_vy, _ = parachute_impact_components(
        height,
        mass,
        cruise_speed,
        gravity,
        rho,
        c_d_u,
        s_u,
        c_d_p,
        s_p,
        float(supplementary["T_1"]),
    )
    parachute_energy = compute_crash_energy(mass, (0.0, parachute_vy))
    parachute_area = compute_casualty_area_parachute(
        r_p, r_u, h_p, parachute_vx, parachute_vy
    )
    return {
        "ballistic_energy": ballistic_energy,
        "ballistic_area": ballistic_area,
        "parachute_energy": parachute_energy,
        "parachute_area": parachute_area,
    }


def _compute_r_for_density(
    pop_density: float,
    ps_value: float,
    layer_model: Mapping[str, float],
    table1: Mapping[str, Any],
    supplementary: Mapping[str, Any],
) -> float:
    """按现有中间量函数计算一个人口密度与 P_s 的 R 值。"""
    alpha = float(table1["ALPHA"])
    beta = float(table1["BETA"])
    fatality_ballistic = compute_fatality_rate(
        ps_value, layer_model["ballistic_energy"], alpha, beta
    )
    fatality_parachute = compute_fatality_rate(
        ps_value, layer_model["parachute_energy"], alpha, beta
    )
    mitigation_mp = compute_mitigation_Mp(
        layer_model["ballistic_area"],
        layer_model["parachute_area"],
        fatality_ballistic,
        fatality_parachute,
    )
    mitigation_ms = compute_mitigation_Ms(
        ps_value, layer_model["ballistic_energy"], alpha, beta
    )
    mitigation = compute_mitigation_M(
        mitigation_mp,
        mitigation_ms,
        layer_model["ballistic_energy"],
        layer_model["parachute_energy"],
        beta,
        float(supplementary["ETA"]),
    )
    return compute_final_R_point(
        pop_density,
        layer_model["ballistic_area"],
        mitigation,
        float(table1["P_LOC"]),
        False,
    )


def compute_r_matrix(
    building_footprint: np.ndarray,
    pop_density: np.ndarray,
    building_mask: np.ndarray,
    config: Mapping[str, Any],
    ps_field: np.ndarray | None = None,
) -> np.ndarray:
    """生成完整风险矩阵 R，返回 float64 数组，形状为 `[i,j,h_idx]`。

    若未传入 `ps_field`，直接调用 `compute_ps` 从二维建筑 footprint 计算。
    人口密度来自 `city.npz`（人/m²），其余风险参数来自唯一来源
    `config.json`；建筑体素按场景契约保留为 NaN。
    """
    footprint = np.asarray(building_footprint)
    density = np.asarray(pop_density)
    mask = np.asarray(building_mask)
    table2 = config["table2"]
    expected_shape = (
        int(table2["N_I"]),
        int(table2["N_J"]),
        int(table2["N_H"]),
    )
    plane_shape = expected_shape[:2]

    if footprint.shape != plane_shape or footprint.ndim != 2:
        raise ValueError(
            f"building_footprint 必须符合配置平面形状 {plane_shape}，实际为 {footprint.shape}。"
        )
    if footprint.dtype != np.bool_:
        raise TypeError("building_footprint 必须为 bool 数组。")
    if density.shape != plane_shape or density.ndim != 2:
        raise ValueError(
            f"pop_density 必须符合配置平面形状 {plane_shape}，实际为 {density.shape}。"
        )
    if not np.issubdtype(density.dtype, np.number):
        raise TypeError("pop_density 必须是数值数组。")
    if not np.isfinite(density).all() or np.any(density < 0):
        raise ValueError("pop_density 必须全部为有限非负数。")
    if mask.shape != expected_shape or mask.ndim != 3:
        raise ValueError(
            f"building_mask 必须符合配置形状 {expected_shape}，实际为 {mask.shape}。"
        )
    if mask.dtype != np.bool_:
        raise TypeError("building_mask 必须为 bool 数组。")

    if ps_field is None:
        ps_values = compute_ps(footprint, density, dict(config))
    else:
        ps_values = np.asarray(ps_field)
    if ps_values.shape != plane_shape or ps_values.ndim != 2:
        raise ValueError(f"P_s 必须符合配置平面形状 {plane_shape}，实际为 {ps_values.shape}。")
    if not np.issubdtype(ps_values.dtype, np.number):
        raise TypeError("P_s 必须是数值数组。")
    if not np.isfinite(ps_values).all() or np.any(ps_values < 0):
        raise ValueError("P_s 必须全部为有限非负数。")

    # 相同 P_s 的单点风险对人口密度呈线性；每层只计算每个唯一 P_s 的
    # 单位人口系数，再一次性扩展到平面，避免对近亿个体素执行 Python 标量循环。
    unique_ps, inverse = np.unique(ps_values, return_inverse=True)
    if len(unique_ps) <= np.iinfo(np.uint16).max:
        inverse = inverse.astype(np.uint16, copy=False)

    coords = config["coords"]
    origin_z = float(coords["origin"][2])
    resolution = float(coords["resolution"])
    R = np.full(expected_shape, np.nan, dtype=np.float64)

    for h_idx in range(expected_shape[2]):
        height = origin_z + h_idx * resolution
        layer_model = _prepare_layer_model(height, config["table1"], config["supplementary"])
        per_density = np.fromiter(
            (
                _compute_r_for_density(
                    1.0,
                    float(ps_value),
                    layer_model,
                    config["table1"],
                    config["supplementary"],
                )
                for ps_value in unique_ps
            ),
            dtype=np.float64,
            count=len(unique_ps),
        )
        if not np.isfinite(per_density).all():
            raise FloatingPointError(f"高度层 h_idx={h_idx} 生成了非有限的空中格风险系数。")

        layer_values = per_density[inverse] * density
        layer_mask = mask[:, :, h_idx]
        layer_values[layer_mask] = np.nan
        R[:, :, h_idx] = layer_values

    return R
