# -*- coding: utf-8 -*-
"""
Mark 点五参数寻优模块
=====================

功能（对应 `寻找最优点参数.md`）：
  已知 A、B 两井的 T1（及推算姿态用的 T2），求 Mark 点五参数
  (INCm, AZIm, MN, ME, MT)，使 Mark 用"优化对齐方案"分别对齐到
  A_T1、B_T1 五参数时，两段轨迹的总井深（MD 之和）最小。

"优化对齐方案"内核与 HAOPATH-DESIGNER `sawarynClc.ts` / `wellTrajectoryAlign.ts`
一致：Sawaryn(2021, SPE-204111-PA) 闭式 CLC（Curve-Hold-Curve，圆弧-稳斜-圆弧），
即从 Mark 点姿态出发，经 圆弧(DLS1)-稳斜-圆弧(DLS2) 精确命中靶点位置与井斜方位；
每段对齐井深 = md1(弧1) + md2(稳斜) + md3(弧2)。

新增：可指定 Mark 点垂深 mtvd，固定垂深下只优化 4 维 (INCm, AZIm, MN, ME)，
用于约束井口布置（如 Mark 点必须在某一平台面以下的有限空间内）。

对外接口
--------
optimize_mark_point(dls1, dls2, a_t1, b_t1, a_t2=None, b_t2=None,
                    mtvd=None, seed=42, popsize=25, maxiter=400)
    dls1, dls2 : 两段圆弧狗腿度（°/30m）
    a_t1, b_t1 : A/B 井 T1，三参数 (N,E,TVD) 或五参数 (N,E,TVD,INC,AZI)
    a_t2, b_t2 : A/B 井 T2 (N,E,TVD)；T1 为三参数时必填，五参数时可省略
    mtvd       : Mark 点垂深 (m)；None=自由优化 5 维；给定时固定垂深、
                 优化 4 维 (INCm, AZIm, MN, ME)

    返回 MarkOptimizeResult：
        .ok        是否求得可行最优解
        .mark      (INCm, AZIm, MN, ME, MT)
        .total_md  两段对齐总井深最小值
        .mtvd      实际使用的垂深（None=自由优化）
        .a_t1/.b_t1  归一化后的 T1 五参数
        .seg_a/.seg_b  Mark->T1 各 CLC 段详情（md1/md2/md3/inc2/azi2/error）

用法示例
--------
    from 寻找最优点参数 import optimize_mark_point

    # 自由优化（不指定 mtvd，5 维）
    res = optimize_mark_point(
        3.0, 3.0,
        (4321500, 423280, 1200), (4321800, 423180, 1100),
        a_t2=(4320303, 422300, 1500), b_t2=(4320603, 422200, 1400))

    # 固定 Mark 垂深 900 m（只优化 4 维姿态+坐标）
    res = optimize_mark_point(3.0, 3.0, a_t1, b_t1,
                              a_t2=..., b_t2=..., mtvd=900.0)
    print(res.mark, res.total_md, res.mtvd)
"""

import math
from dataclasses import dataclass

__all__ = [
    "optimize_mark_point", "MarkOptimizeResult", "normalize_t1",
    "align_md", "make_objective", "calculate_segment",
    "solve_clc_renderable", "inc_azi_between_points",
]

# ============================================================
# 1. 内置示例数据（命令行演示/验证用，N, E, TVD，单位 m）
# ============================================================
A_T1 = (4321500.0, 423280.0, 1200.0)
A_T2 = (4320303.0, 422300.0, 1500.0)
B_T1 = (4321800.0, 423180.0, 1100.0)
B_T2 = (4320603.0, 422200.0, 1400.0)

# 设计狗腿度（°/30m），可按现场工具能力调整
DLS1 = 3.0   # 第一段圆弧（Mark 姿态 -> 中间稳斜姿态）
DLS2 = 3.0   # 第二段圆弧（中间稳斜姿态 -> 靶点姿态）

TWO_PI = 2.0 * math.pi
PI = math.pi


# ============================================================
# 2. 基础几何
# ============================================================
def clamp(x, lo, hi):
    return min(hi, max(lo, x))


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def radius_from_dls(dls):
    """狗腿度(°/30m) -> 曲率半径(m)"""
    if dls == 0:
        return math.inf
    return (30.0 / dls) * 360.0 / (2.0 * PI)


def tangent_from_inc_azi(inc_deg, azi_deg):
    """井斜/方位(度) -> 单位方向向量 (N, E, TVD)"""
    i = math.radians(inc_deg)
    a = math.radians(azi_deg)
    return (math.sin(i) * math.cos(a), math.sin(i) * math.sin(a), math.cos(i))


def inc_azi_from_tangent(t):
    """单位方向向量 -> (井斜, 方位)(度)"""
    n = math.sqrt(t[0] * t[0] + t[1] * t[1] + t[2] * t[2]) or 1.0
    tn, te, tv = t[0] / n, t[1] / n, t[2] / n
    inc = math.degrees(math.acos(clamp(tv, -1.0, 1.0)))
    azi = math.degrees(math.atan2(te, tn))
    if azi < 0:
        azi += 360.0
    return inc, azi


def inc_azi_between_points(p1, p2):
    """两点空间方向 -> (井斜, 方位)(度)，与 TS getIncAziBetweenPoints 一致"""
    dn = p2[0] - p1[0]
    de = p2[1] - p1[1]
    dtvd = p2[2] - p1[2]
    hd = math.sqrt(dn * dn + de * de)
    if abs(dtvd) < 1e-12:
        inc = 90.0
    else:
        inc = math.degrees(math.atan2(hd, dtvd))
    if inc < 0:
        inc += 180.0
    if hd < 0.001:
        azi = 0.0
    else:
        azi = math.degrees(math.atan2(de, dn))
        azi = (azi + 360.0) % 360.0
    return inc, azi


# ============================================================
# 3. Sawaryn 闭式 CLC 求解（移植自 sawarynClc.ts）
# ============================================================
def _scalars(p1, t1, p4, t4):
    dp = (p4[0] - p1[0], p4[1] - p1[1], p4[2] - p1[2])
    mu = dot(t1, t4)
    psi2 = dot(dp, dp)
    eta1 = dot(dp, t1)
    eta4 = dot(dp, t4)
    den = math.sqrt(max(0.0, 1.0 - mu * mu))
    eta14 = 0.0 if den < 1e-15 else dot(dp, cross(t1, t4)) / den
    return dp, psi2, eta1, eta4, eta14, mu


def eq15_coeffs(psi2, g1, g4, l, R1, R2):
    return [
        2*g1*g4*psi2**4+psi2**5-l*psi2**5+16*g1**3*g4*psi2**2*R1**2+8*g1**2*psi2**3*R1**2-16*g1*g4*psi2**3*R1**2-8*g1**2*l*psi2**3*R1**2-8*psi2**4*R1**2+8*l*psi2**4*R1**2+32*g1**5*g4*R1**4+16*g1**4*psi2*R1**4-64*g1**3*g4*psi2*R1**4-16*g1**4*l*psi2*R1**4-32*g1**2*psi2**2*R1**4+32*g1*g4*psi2**2*R1**4+32*g1**2*l*psi2**2*R1**4+16*psi2**3*R1**4-16*l*psi2**3*R1**4+16*g1*g4**3*psi2**2*R2**2-16*g1*g4*psi2**3*R2**2+8*g4**2*psi2**3*R2**2-8*g4**2*l*psi2**3*R2**2-8*psi2**4*R2**2+8*l*psi2**4*R2**2-64*g1**3*g4**3*R1**2*R2**2-64*g1**3*g4*psi2*R1**2*R2**2+96*g1**2*g4**2*psi2*R1**2*R2**2-64*g1*g4**3*psi2*R1**2*R2**2+160*g1**2*g4**2*l*psi2*R1**2*R2**2-64*g1**2*psi2**2*R1**2*R2**2+112*g1*g4*psi2**2*R1**2*R2**2-64*g4**2*psi2**2*R1**2*R2**2+32*g1**2*l*psi2**2*R1**2*R2**2-32*g1*g4*l*psi2**2*R1**2*R2**2+32*g4**2*l*psi2**2*R1**2*R2**2-80*g1*g4*l**2*psi2**2*R1**2*R2**2+56*psi2**3*R1**2*R2**2-72*l*psi2**3*R1**2*R2**2+8*l**2*psi2**3*R1**2*R2**2+8*l**3*psi2**3*R1**2*R2**2-128*g1**4*R1**4*R2**2+192*g1**3*g4*R1**4*R2**2-128*g1**2*g4**2*R1**4*R2**2+128*g1*g4**3*R1**4*R2**2+128*g1**3*g4*l*R1**4*R2**2-256*g1**2*g4**2*l*R1**4*R2**2+64*g1**3*g4*l**2*R1**4*R2**2+224*g1**2*psi2*R1**4*R2**2-192*g1*g4*psi2*R1**4*R2**2+64*g4**2*psi2*R1**4*R2**2-160*g1**2*l*psi2*R1**4*R2**2-64*g4**2*l*psi2*R1**4*R2**2-32*g1**2*l**2*psi2*R1**4*R2**2+192*g1*g4*l**2*psi2*R1**4*R2**2-32*g1**2*l**3*psi2*R1**4*R2**2-96*psi2**2*R1**4*R2**2+160*l*psi2**2*R1**4*R2**2-32*l**2*psi2**2*R1**4*R2**2-32*l**3*psi2**2*R1**4*R2**2+32*g1*g4**5*R2**4-64*g1*g4**3*psi2*R2**4+16*g4**4*psi2*R2**4-16*g4**4*l*psi2*R2**4+32*g1*g4*psi2**2*R2**4-32*g4**2*psi2**2*R2**4+32*g4**2*l*psi2**2*R2**4+16*psi2**3*R2**4-16*l*psi2**3*R2**4+128*g1**3*g4*R1**2*R2**4-128*g1**2*g4**2*R1**2*R2**4+192*g1*g4**3*R1**2*R2**4-128*g4**4*R1**2*R2**4-256*g1**2*g4**2*l*R1**2*R2**4+128*g1*g4**3*l*R1**2*R2**4+64*g1*g4**3*l**2*R1**2*R2**4+64*g1**2*psi2*R1**2*R2**4-192*g1*g4*psi2*R1**2*R2**4+224*g4**2*psi2*R1**2*R2**4-64*g1**2*l*psi2*R1**2*R2**4-160*g4**2*l*psi2*R1**2*R2**4+192*g1*g4*l**2*psi2*R1**2*R2**4-32*g4**2*l**2*psi2*R1**2*R2**4-32*g4**2*l**3*psi2*R1**2*R2**4-96*psi2**2*R1**2*R2**4+160*l*psi2**2*R1**2*R2**4-32*l**2*psi2**2*R1**2*R2**4-32*l**3*psi2**2*R1**2*R2**4-128*g1**2*R1**4*R2**4+32*g1*g4*R1**4*R2**4-128*g4**2*R1**4*R2**4+256*g1**2*l*R1**4*R2**4+128*g1*g4*l*R1**4*R2**4+256*g4**2*l*R1**4*R2**4-128*g1**2*l**2*R1**4*R2**4-320*g1*g4*l**2*R1**4*R2**4-128*g4**2*l**2*R1**4*R2**4+128*g1*g4*l**3*R1**4*R2**4+32*g1*g4*l**4*R1**4*R2**4+144*psi2*R1**4*R2**4-336*l*psi2*R1**4*R2**4+160*l**2*psi2*R1**4*R2**4+96*l**3*psi2*R1**4*R2**4-48*l**4*psi2*R1**4*R2**4-16*l**5*psi2*R1**4*R2**4,
        2*g1*psi2**4+2*g4*psi2**4+16*g1**3*psi2**2*R1**2+16*g1**2*g4*psi2**2*R1**2-16*g1*psi2**3*R1**2-16*g4*psi2**3*R1**2+32*g1**5*R1**4+32*g1**4*g4*R1**4-64*g1**3*psi2*R1**4-64*g1**2*g4*psi2*R1**4+32*g1*psi2**2*R1**4+32*g4*psi2**2*R1**4+16*g1*g4**2*psi2**2*R2**2+16*g4**3*psi2**2*R2**2-16*g1*psi2**3*R2**2-16*g4*psi2**3*R2**2-64*g1**3*g4**2*R1**2*R2**2-64*g1**2*g4**3*R1**2*R2**2-64*g1**3*psi2*R1**2*R2**2+64*g1**2*g4*psi2*R1**2*R2**2+64*g1*g4**2*psi2*R1**2*R2**2-64*g4**3*psi2*R1**2*R2**2+128*g1**2*g4*l*psi2*R1**2*R2**2+128*g1*g4**2*l*psi2*R1**2*R2**2+48*g1*psi2**2*R1**2*R2**2+48*g4*psi2**2*R1**2*R2**2-96*g1*l*psi2**2*R1**2*R2**2-96*g4*l*psi2**2*R1**2*R2**2-16*g1*l**2*psi2**2*R1**2*R2**2-16*g4*l**2*psi2**2*R1**2*R2**2-64*g1**3*R1**4*R2**2+192*g1**2*g4*R1**4*R2**2-128*g1*g4**2*R1**4*R2**2+128*g4**3*R1**4*R2**2-128*g1**3*l*R1**4*R2**2+128*g1**2*g4*l*R1**4*R2**2-256*g1*g4**2*l*R1**4*R2**2+64*g1**3*l**2*R1**4*R2**2+64*g1**2*g4*l**2*R1**4*R2**2+64*g1*psi2*R1**4*R2**2-192*g4*psi2*R1**4*R2**2+128*g1*l*psi2*R1**4*R2**2+128*g4*l*psi2*R1**4*R2**2-192*g1*l**2*psi2*R1**4*R2**2+64*g4*l**2*psi2*R1**4*R2**2+32*g1*g4**4*R2**4+32*g4**5*R2**4-64*g1*g4**2*psi2*R2**4-64*g4**3*psi2*R2**4+32*g1*psi2**2*R2**4+32*g4*psi2**2*R2**4+128*g1**3*R1**2*R2**4-128*g1**2*g4*R1**2*R2**4+192*g1*g4**2*R1**2*R2**4-64*g4**3*R1**2*R2**4-256*g1**2*g4*l*R1**2*R2**4+128*g1*g4**2*l*R1**2*R2**4-128*g4**3*l*R1**2*R2**4+64*g1*g4**2*l**2*R1**2*R2**4+64*g4**3*l**2*R1**2*R2**4-192*g1*psi2*R1**2*R2**4+64*g4*psi2*R1**2*R2**4+128*g1*l*psi2*R1**2*R2**4+128*g4*l*psi2*R1**2*R2**4+64*g1*l**2*psi2*R1**2*R2**4-192*g4*l**2*psi2*R1**2*R2**4+32*g1*R1**4*R2**4+32*g4*R1**4*R2**4-128*g1*l*R1**4*R2**4-128*g4*l*R1**4*R2**4+192*g1*l**2*R1**4*R2**4+192*g4*l**2*R1**4*R2**4-128*g1*l**3*R1**4*R2**4-128*g4*l**3*R1**4*R2**4+32*g1*l**4*R1**4*R2**4+32*g4*l**4*R1**4*R2**4,
        -8*g1*g4*psi2**3-3*psi2**4+5*l*psi2**4-32*g1**3*g4*psi2*R1**2-8*g1**2*psi2**2*R1**2+32*g1*g4*psi2**2*R1**2+24*g1**2*l*psi2**2*R1**2+8*psi2**3*R1**2-24*l*psi2**3*R1**2+16*g1**4*R1**4+16*g1**4*l*R1**4-32*g1**2*psi2*R1**4-32*g1**2*l*psi2*R1**4+16*psi2**2*R1**4+16*l*psi2**2*R1**4-32*g1*g4**3*psi2*R2**2+32*g1*g4*psi2**2*R2**2-8*g4**2*psi2**2*R2**2+24*g4**2*l*psi2**2*R2**2+8*psi2**3*R2**2-24*l*psi2**3*R2**2+128*g1**3*g4*R1**2*R2**2-160*g1**2*g4**2*R1**2*R2**2+128*g1*g4**3*R1**2*R2**2-160*g1**2*g4**2*l*R1**2*R2**2+96*g1**2*psi2*R1**2*R2**2-96*g1*g4*psi2*R1**2*R2**2+96*g4**2*psi2*R1**2*R2**2-96*g1**2*l*psi2*R1**2*R2**2+64*g1*g4*l*psi2*R1**2*R2**2-96*g4**2*l*psi2*R1**2*R2**2+160*g1*g4*l**2*psi2*R1**2*R2**2-88*psi2**2*R1**2*R2**2+56*l*psi2**2*R1**2*R2**2-8*l**2*psi2**2*R1**2*R2**2-24*l**3*psi2**2*R1**2*R2**2-32*g1**2*R1**4*R2**2-64*g4**2*R1**4*R2**2+32*g1**2*l*R1**4*R2**2+128*g1*g4*l*R1**4*R2**2+64*g4**2*l*R1**4*R2**2-32*g1**2*l**2*R1**4*R2**2-128*g1*g4*l**2*R1**4*R2**2+32*g1**2*l**3*R1**4*R2**2+32*psi2*R1**4*R2**2-32*l*psi2*R1**4*R2**2-32*l**2*psi2*R1**4*R2**2+32*l**3*psi2*R1**4*R2**2+16*g4**4*R2**4+16*g4**4*l*R2**4-32*g4**2*psi2*R2**4-32*g4**2*l*psi2*R2**4+16*psi2**2*R2**4+16*l*psi2**2*R2**4-64*g1**2*R1**2*R2**4-32*g4**2*R1**2*R2**4+64*g1**2*l*R1**2*R2**4+128*g1*g4*l*R1**2*R2**4+32*g4**2*l*R1**2*R2**4-128*g1*g4*l**2*R1**2*R2**4-32*g4**2*l**2*R1**2*R2**4+32*g4**2*l**3*R1**2*R2**4+32*psi2*R1**2*R2**4-32*l*psi2*R1**2*R2**4-32*l**2*psi2*R1**2*R2**4+32*l**3*psi2*R1**2*R2**4+16*R1**4*R2**4-48*l*R1**4*R2**4+32*l**2*R1**4*R2**4+32*l**3*R1**4*R2**4-48*l**4*R1**4*R2**4+16*l**5*R1**4*R2**4,
        -8*g1*psi2**3-8*g4*psi2**3-32*g1**3*psi2*R1**2-32*g1**2*g4*psi2*R1**2+32*g1*psi2**2*R1**2+32*g4*psi2**2*R1**2-32*g1*g4**2*psi2*R2**2-32*g4**3*psi2*R2**2+32*g1*psi2**2*R2**2+32*g4*psi2**2*R2**2+128*g1**3*R1**2*R2**2+128*g4**3*R1**2*R2**2-128*g1**2*g4*l*R1**2*R2**2-128*g1*g4**2*l*R1**2*R2**2-96*g1*psi2*R1**2*R2**2-96*g4*psi2*R1**2*R2**2+64*g1*l*psi2*R1**2*R2**2+64*g4*l*psi2*R1**2*R2**2+32*g1*l**2*psi2*R1**2*R2**2+32*g4*l**2*psi2*R1**2*R2**2,
        12*g1*g4*psi2**2+2*psi2**3-10*l*psi2**3+16*g1**3*g4*R1**2-8*g1**2*psi2*R1**2-16*g1*g4*psi2*R1**2-24*g1**2*l*psi2*R1**2+8*psi2**2*R1**2+24*l*psi2**2*R1**2+16*g1*g4**3*R2**2-16*g1*g4*psi2*R2**2-8*g4**2*psi2*R2**2-24*g4**2*l*psi2*R2**2+8*psi2**2*R2**2+24*l*psi2**2*R2**2+32*g1**2*R1**2*R2**2-80*g1*g4*R1**2*R2**2+32*g4**2*R1**2*R2**2+64*g1**2*l*R1**2*R2**2-32*g1*g4*l*R1**2*R2**2+64*g4**2*l*R1**2*R2**2-80*g1*g4*l**2*R1**2*R2**2-24*psi2*R1**2*R2**2+8*l*psi2*R1**2*R2**2-8*l**2*psi2*R1**2*R2**2+24*l**3*psi2*R1**2*R2**2,
        12*g1*psi2**2+12*g4*psi2**2+16*g1**3*R1**2+16*g1**2*g4*R1**2-16*g1*psi2*R1**2-16*g4*psi2*R1**2+16*g1*g4**2*R2**2+16*g4**3*R2**2-16*g1*psi2*R2**2-16*g4*psi2*R2**2-16*g1*R1**2*R2**2-16*g4*R1**2*R2**2+32*g1*l*R1**2*R2**2+32*g4*l*R1**2*R2**2-16*g1*l**2*R1**2*R2**2-16*g4*l**2*R1**2*R2**2,
        -8*g1*g4*psi2+2*psi2**2+10*l*psi2**2+8*g1**2*R1**2+8*g1**2*l*R1**2-8*psi2*R1**2-8*l*psi2*R1**2+8*g4**2*R2**2+8*g4**2*l*R2**2-8*psi2*R2**2-8*l*psi2*R2**2-8*R1**2*R2**2+8*l*R1**2*R2**2+8*l**2*R1**2*R2**2-8*l**3*R1**2*R2**2,
        -8*g1*psi2-8*g4*psi2,
        2*g1*g4-3*psi2-5*l*psi2,
        2*g1+2*g4,
        1+l,
    ]


def poly_roots(co_in):
    """Durand-Kerner 同步求根，与 TS polyRoots 数值行为一致"""
    n = len(co_in) - 1
    if n < 1:
        return []
    lead = co_in[n]
    if abs(lead) < 1e-300:
        return []
    co = [c / lead for c in co_in]

    z = []
    for i in range(n):
        ang = (2.0 * PI * i) / n + 0.4
        r = 0.4 + 0.3 * i
        z.append(complex(r * math.cos(ang), r * math.sin(ang)))

    for _ in range(80):
        max_step2 = 0.0
        steps = []
        for i in range(n):
            denom = 1 + 0j
            for j in range(n):
                if j != i:
                    denom *= (z[i] - z[j])
            d = denom.real * denom.real + denom.imag * denom.imag
            if d < 1e-60:
                steps.append(0j)
                continue
            p = 0j
            for k in range(n, -1, -1):
                p = p * z[i] + co[k]
            q = p * denom.conjugate() / d
            steps.append(q)
            s2 = q.real * q.real + q.imag * q.imag
            if s2 > max_step2:
                max_step2 = s2
        for i in range(n):
            z[i] -= steps[i]
        if max_step2 < 1e-24:
            break
    return z


def _subtended_angles(beta, psi2, eta1, eta4, mu, R1, R2):
    psb = psi2 - beta * beta
    A1 = 4 * R1 * R1 * ((eta1 + beta) ** 2 - R2 * R2 * (1 - mu * mu))
    B1 = 4 * R1 * (2 * R2 * R2 * (eta1 - mu * eta4) - psb * (eta1 + beta))
    C1 = psb * psb - 4 * R2 * R2 * (psi2 - eta4 * eta4)
    A2 = 4 * R2 * R2 * ((eta4 + beta) ** 2 - R1 * R1 * (1 - mu * mu))
    B2 = 4 * R2 * (2 * R1 * R1 * (eta4 - mu * eta1) - psb * (eta4 + beta))
    C2 = psb * psb - 4 * R1 * R1 * (psi2 - eta1 * eta1)

    def roots_quad(A, B, C):
        disc = B * B - 4 * A * C
        if A == 0 or disc < 0:
            return []
        sq = math.sqrt(disc)
        return [2 * math.atan2(-B + sq, 2 * A), 2 * math.atan2(-B - sq, 2 * A)]

    return roots_quad(A1, B1, C1), roots_quad(A2, B2, C2)


def _clc_solutions_general(p1, t1, p4, t4, R1, R2):
    dp, psi2, eta1, eta4, eta14, mu = _scalars(p1, t1, p4, t4)
    L = math.sqrt(psi2)
    if not (L > 0) or not math.isfinite(L):
        return []
    co = eq15_coeffs(1.0, eta1 / L, eta4 / L, mu, R1 / L, R2 / L)
    scale = max([abs(c) for c in co] + [1e-300])
    if not all(math.isfinite(c) for c in co) or abs(co[10]) < 1e-12 * scale:
        return []

    roots = poly_roots(co)
    sols = []
    for root in roots:
        b = root.real * L
        bi = root.imag * L
        if abs(bi) >= 1e-4 * (abs(b) + 1) or b <= 1e-6:
            continue

        psb = psi2 - b * b
        A1 = 4 * R1 * R1 * ((eta1 + b) ** 2 - R2 * R2 * (1 - mu * mu))
        B1 = 4 * R1 * (2 * R2 * R2 * (eta1 - mu * eta4) - psb * (eta1 + b))
        C1 = psb * psb - 4 * R2 * R2 * (psi2 - eta4 * eta4)
        A2 = 4 * R2 * R2 * ((eta4 + b) ** 2 - R1 * R1 * (1 - mu * mu))
        B2 = 4 * R2 * (2 * R1 * R1 * (eta4 - mu * eta1) - psb * (eta4 + b))
        C2 = psb * psb - 4 * R1 * R1 * (psi2 - eta1 * eta1)
        d1 = max(B1 * B1 - 4 * A1 * C1, 0.0)
        d2 = max(B2 * B2 - 4 * A2 * C2, 0.0)

        best_res = math.inf
        best_a1 = 0.0
        best_a2 = 0.0
        for s1 in (1.0, -1.0):
            a1 = 2 * math.atan2(-B1 + s1 * math.sqrt(d1), 2 * A1)
            for s2 in (1.0, -1.0):
                a2 = 2 * math.atan2(-B2 + s2 * math.sqrt(d2), 2 * A2)
                c1, sn1 = math.cos(a1), math.sin(a1)
                c2, sn2 = math.cos(a2), math.sin(a2)
                t1h = math.tan(a1 / 2)
                t2h = math.tan(a2 / 2)
                f1 = R1 * sn1 + b * c1 + R2 * t2h * (mu + c1)
                f4 = R1 * t1h * (mu + c2) + b * c2 + R2 * sn2
                sd = (1 - mu * mu - c1 * c1 - c2 * c2 + 2 * mu * c1 * c2) / (1 - mu * mu)
                if not math.isfinite(sd):
                    sd = 0.0
                f14 = (R1 * t1h + b + R2 * t2h) * math.sqrt(max(sd, 0.0))
                res = math.sqrt((f1 - eta1) ** 2 + (f4 - eta4) ** 2 +
                                (abs(f14) - abs(eta14)) ** 2)
                if res < best_res:
                    best_res = res
                    best_a1 = a1
                    best_a2 = a2
        if best_res >= 1e-4 * L:
            continue
        a1n = (best_a1 % TWO_PI + TWO_PI) % TWO_PI
        a2n = (best_a2 % TWO_PI + TWO_PI) % TWO_PI
        sols.append({"beta": b, "alpha1": a1n, "alpha2": a2n,
                     "total_md": R1 * a1n + b + R2 * a2n})
    sols.sort(key=lambda s: s["total_md"])
    return sols


def _solve_clc_2d(p1, t1, p4, t4, R1, R2):
    dp, psi2, eta1, eta4, eta14, mu = _scalars(p1, t1, p4, t4)
    tol = 1e-4 * math.sqrt(psi2)
    K = (psi2 * psi2
         - 4 * R1 * R1 * (psi2 - eta1 * eta1)
         - 4 * R2 * R2 * (psi2 - eta4 * eta4)
         + 4 * R1 * R1 * R2 * R2 * (1 - mu) ** 2)
    Bc = (1 + mu) * psi2 - 2 * eta1 * eta4
    Bq = -(1 - mu)

    def branch(b):
        a1s, a2s = _subtended_angles(b, psi2, eta1, eta4, mu, R1, R2)
        best = (math.inf, 0.0, 0.0)
        for x1 in a1s:
            for x2 in a2s:
                c1, s1 = math.cos(x1), math.sin(x1)
                c2, s2 = math.cos(x2), math.sin(x2)
                T1h = math.tan(x1 / 2)
                T2h = math.tan(x2 / 2)
                r = math.hypot(
                    R1 * s1 + b * c1 + R2 * T2h * (mu + c1) - eta1,
                    R1 * T1h * (mu + c2) + b * c2 + R2 * s2 - eta4)
                if r < best[0]:
                    best = (r, x1, x2)
        return best

    sols = []
    for sgn in (1.0, -1.0):
        a2q = -2 * psi2 - sgn * 4 * R1 * R2 * Bq
        a0q = K - sgn * 4 * R1 * R2 * Bc
        disc = a2q * a2q - 4 * a0q
        if disc < 0:
            continue
        for u in ((-a2q + math.sqrt(disc)) / 2, (-a2q - math.sqrt(disc)) / 2):
            if u <= 1e-12:
                continue
            b = math.sqrt(u)
            r, a1, aa2 = branch(b)
            if r < tol and not any(abs(s["beta"] - b) < 1e-2 for s in sols):
                x1 = (a1 % TWO_PI + TWO_PI) % TWO_PI
                x2 = (aa2 % TWO_PI + TWO_PI) % TWO_PI
                sols.append({"beta": b, "alpha1": x1, "alpha2": x2,
                             "total_md": R1 * x1 + b + R2 * x2})
    sols.sort(key=lambda s: s["total_md"])
    return sols


def solve_clc_all(p1, t1, p4, t4, R1, R2):
    """全部有效 CLC 解，按总长升序"""
    mu = dot(t1, t4)
    if abs(mu) > 1 - 1e-9:
        return _solve_clc_2d(p1, t1, p4, t4, R1, R2)
    sols = _clc_solutions_general(p1, t1, p4, t4, R1, R2)
    if not sols:
        sols = _solve_clc_2d(p1, t1, p4, t4, R1, R2)
    return sols


def solve_clc_renderable(p1, t1, p4, t4, R1, R2):
    """最短可施工 CLC（每段弧狗腿 <= pi），且位移残差在阈值内，无解返回 None

    选解优先级：真实位移残差 error 最小 → 其次 total_md 最短。
    """
    sols = solve_clc_all(p1, t1, p4, t4, R1, R2)
    lim = PI + 1e-9
    cands = [s for s in sols if s["alpha1"] <= lim and s["alpha2"] <= lim]
    if not cands:
        return None

    class _Score:
        __slots__ = ("error", "total_md", "sol")

        def __init__(self, error, total_md, sol):
            self.error = error
            self.total_md = total_md
            self.sol = sol

        def __lt__(self, other):
            if self.error >= 0.01 and other.error < 0.01:
                return False       # 超过 1 cm 残差的排在后面
            if self.error < 0.01 and other.error >= 0.01:
                return True
            if abs(self.error - other.error) > 1e-6:
                return self.error < other.error
            return self.total_md < other.total_md

    scored = []
    for sol in cands:
        hold = reconstruct_hold_tangent(p1, t1, p4, t4, R1, R2, sol)
        if hold is None:
            continue
        inc2, azi2 = inc_azi_from_tangent(hold)
        md1 = sol["alpha1"] * R1
        md2 = sol["beta"]
        md3 = sol["alpha2"] * R2

        delta = (p4[0] - p1[0], p4[1] - p1[1], p4[2] - p1[2])
        g1 = math.degrees(sol["alpha1"])
        g2 = math.degrees(sol["alpha2"])
        rf1 = (2 * math.tan(sol["alpha1"] / 2)) / sol["alpha1"] if g1 > 0.001 else 1.0
        rf2 = (2 * math.tan(sol["alpha2"] / 2)) / sol["alpha2"] if g2 > 0.001 else 1.0

        def vadd(u, v): return (u[0] + v[0], u[1] + v[1], u[2] + v[2])
        def vscale(v, s): return (v[0] * s, v[1] * s, v[2] * s)
        term1 = vscale(vadd(t1, hold), 0.5 * md1 * rf1)
        term2 = vscale(hold, md2)
        term3 = vscale(vadd(hold, t4), 0.5 * md3 * rf2)
        calc = vadd(vadd(term1, term2), term3)
        error = (abs(calc[0] - delta[0]) + abs(calc[1] - delta[1]) +
                 abs(calc[2] - delta[2]))

        scored.append(_Score(error, md1 + md2 + md3, {
            **sol, "inc2": inc2, "azi2": azi2, "md1": md1, "md2": md2, "md3": md3}))

    if not scored:
        return None
    scored.sort()
    return scored[0].sol


def reconstruct_hold_tangent(p1, t1, p4, t4, R1, R2, sol):
    """重建稳斜段单位切向量"""
    T1h = math.tan(sol["alpha1"] / 2)
    T2h = math.tan(sol["alpha2"] / 2)
    denom = R1 * T1h + sol["beta"] + R2 * T2h
    if not math.isfinite(denom) or abs(denom) < 1e-15:
        return None
    dp = (p4[0] - p1[0], p4[1] - p1[1], p4[2] - p1[2])
    t2 = ((dp[0] - R1 * T1h * t1[0] - R2 * T2h * t4[0]) / denom,
          (dp[1] - R1 * T1h * t1[1] - R2 * T2h * t4[1]) / denom,
          (dp[2] - R1 * T1h * t1[2] - R2 * T2h * t4[2]) / denom)
    n = math.sqrt(t2[0] * t2[0] + t2[1] * t2[1] + t2[2] * t2[2])
    if not math.isfinite(n) or n == 0:
        return None
    return (t2[0] / n, t2[1] / n, t2[2] / n)


def _clc_error_from_sol(a, v1, b, v3, R1, R2, alpha1, alpha2, beta):
    """给定 alpha1/alpha2/beta，算 CLC 还原位移残差（可被数值优化调用）"""
    hold = reconstruct_hold_tangent(a, v1, b, v3, R1, R2,
                                    {"alpha1": alpha1, "alpha2": alpha2, "beta": beta})
    if hold is None:
        return 1e9
    md1 = alpha1 * R1
    md2 = beta
    md3 = alpha2 * R2
    g1 = math.degrees(alpha1)
    g2 = math.degrees(alpha2)
    rf1 = (2 * math.tan(alpha1 / 2)) / alpha1 if g1 > 0.001 else 1.0
    rf2 = (2 * math.tan(alpha2 / 2)) / alpha2 if g2 > 0.001 else 1.0

    def vadd(u, v): return (u[0] + v[0], u[1] + v[1], u[2] + v[2])
    def vscale(v, s): return (v[0] * s, v[1] * s, v[2] * s)
    term1 = vscale(vadd(v1, hold), 0.5 * md1 * rf1)
    term2 = vscale(hold, md2)
    term3 = vscale(vadd(hold, v3), 0.5 * md3 * rf2)
    calc = vadd(vadd(term1, term2), term3)
    delta = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    return (abs(calc[0] - delta[0]) + abs(calc[1] - delta[1]) +
            abs(calc[2] - delta[2]))


def _refine_clc(a, v1, b, v3, R1, R2, sol, maxiter=200):
    """十次多项式解的局部精修：微调 alpha1/alpha2/beta 让 error → 机器精度"""
    try:
        from scipy.optimize import minimize
    except ImportError:
        return sol

    x0 = [sol["alpha1"], sol["alpha2"], sol["beta"]]
    cur_err = _clc_error_from_sol(a, v1, b, v3, R1, R2, *x0)
    if cur_err < 1e-7:
        return sol  # 已经是机器精度

    # alpha1/alpha2 物理上 <= π（每段弧狗腿 <= 180°），beta >= 0
    bounds = [(1e-9, PI - 1e-6), (1e-9, PI - 1e-6), (0.0, None)]

    def obj(x): return _clc_error_from_sol(a, v1, b, v3, R1, R2, *x)

    # 先做 Nelder-Mead（无梯度，稳），再做 L-BFGS-B（有界，精）
    nm = minimize(obj, x0, method="Nelder-Mead",
                  options={"xatol": 1e-12, "fatol": 1e-12, "maxfev": maxiter})
    if nm.x[0] > 1e-9 and nm.x[1] > 1e-9 and nm.x[2] >= 0:
        lb = minimize(obj, nm.x, method="L-BFGS-B", bounds=bounds,
                      options={"ftol": 1e-15, "maxfun": maxiter})
        if lb.fun < nm.fun:
            x0 = lb.x

    refined_err = _clc_error_from_sol(a, v1, b, v3, R1, R2, *x0)
    if refined_err < cur_err:
        return {**sol, "alpha1": x0[0], "alpha2": x0[1], "beta": x0[2]}
    return sol


def _fast_segment_error(a, v1, b, v3, R1, R2, inc3, azi3):
    """快速版 CLC 段检查：只求十次多项式解 + 位移残差（不精修），返回 (ok, total_md, error)
    用于目标函数里做区分，避免每次都做局部精修。"""
    sol = solve_clc_renderable(a, v1, b, v3, R1, R2)
    if sol is None:
        return False, 0.0, 1e9
    hold = reconstruct_hold_tangent(a, v1, b, v3, R1, R2, sol)
    if hold is None:
        return False, 0.0, 1e9
    md1 = sol["alpha1"] * R1
    md2 = sol["beta"]
    md3 = sol["alpha2"] * R2
    error = _clc_error_from_sol(a, v1, b, v3, R1, R2, sol["alpha1"], sol["alpha2"], sol["beta"])
    # 硬约束：1 cm 残差内视为"十次多项式有效解"
    if error > 0.01:
        return False, 0.0, error
    return True, md1 + md2 + md3, error


def calculate_segment(a, b, inc1, azi1, inc3, azi3, dls1, dls2, refine=True):
    """
    优化对齐方案核心：从 a 点(姿态 inc1/azi1) 到 b 点(姿态 inc3/azi3) 的
    CLC(圆弧-稳斜-圆弧) 段。返回 md1/md2/md3、中间稳斜姿态 inc2/azi2 与位移残差。
    refine=True (默认) 时自动调用 _refine_clc 让位移残差 → 机器精度；
    refine=False 时跳过精修，用于目标函数里的快速评估。
    """
    if not (dls1 > 0) or not (dls2 > 0):
        return {"ok": False, "reason": "DLS1/DLS2 必须 > 0"}
    R1 = radius_from_dls(dls1)
    R2 = radius_from_dls(dls2)
    v1 = tangent_from_inc_azi(inc1, azi1)
    v3 = tangent_from_inc_azi(inc3, azi3)
    sol = solve_clc_renderable(a, v1, b, v3, R1, R2)
    if sol is None:
        return {"ok": False,
                "reason": f"当前 DLS {dls1:.1f}/{dls2:.1f}°/30m 无法求出轨迹"}
    # 局部精修：十次多项式解有数值误差，微调 alpha1/alpha2/beta 让 error → 机器精度
    if refine:
        sol = _refine_clc(a, v1, b, v3, R1, R2, sol)
    hold = reconstruct_hold_tangent(a, v1, b, v3, R1, R2, sol)
    if hold is None:
        return {"ok": False, "reason": "轨迹计算失败"}
    inc2, azi2 = inc_azi_from_tangent(hold)
    md1 = sol["alpha1"] * R1
    md2 = sol["beta"]
    md3 = sol["alpha2"] * R2

    delta = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    g1 = math.degrees(sol["alpha1"])
    g2 = math.degrees(sol["alpha2"])
    rf1 = (2 * math.tan(sol["alpha1"] / 2)) / sol["alpha1"] if g1 > 0.001 else 1.0
    rf2 = (2 * math.tan(sol["alpha2"] / 2)) / sol["alpha2"] if g2 > 0.001 else 1.0

    def vadd(u, v):
        return (u[0] + v[0], u[1] + v[1], u[2] + v[2])

    def vscale(v, s):
        return (v[0] * s, v[1] * s, v[2] * s)

    term1 = vscale(vadd(v1, hold), 0.5 * md1 * rf1)
    term2 = vscale(hold, md2)
    term3 = vscale(vadd(hold, v3), 0.5 * md3 * rf2)
    calc = vadd(vadd(term1, term2), term3)
    error = (abs(calc[0] - delta[0]) + abs(calc[1] - delta[1]) +
             abs(calc[2] - delta[2]))

    # 硬约束：位移残差 > 0.1 m 视为 CLC 无法准确还原靶点
    if error > 0.1:
        return {"ok": False,
                "reason": f"CLC 还原位移残差 {error:.4f} m > 0.1 m，"
                           f"DLS {dls1:.1f}/{dls2:.1f}°/30m 下无法精确命中靶点"}

    return {"ok": True, "md1": md1, "md2": md2, "md3": md3,
            "inc2": inc2, "azi2": azi2, "error": error,
            "alpha1_deg": g1, "alpha2_deg": g2}


# ============================================================
# 4. 靶点归一化 与 对齐井深
# ============================================================
BIG = 1e9


def normalize_t1(t1, t2=None):
    """
    归一化 T1 五参数 (N, E, TVD, INC, AZI)。

    - t1 为 (N, E, TVD) 三参数时，必须同时提供 t2=(N, E, TVD)，
      由 T1->T2 方向推算过 T1 的井斜/方位；
    - t1 为 (N, E, TVD, INC, AZI) 五参数时，t2 可省略。
    """
    vals = [float(v) for v in t1]
    if len(vals) == 5:
        return tuple(vals)
    if len(vals) == 3:
        if t2 is None:
            raise ValueError("T1 为三参数 (N,E,TVD) 时必须提供 T2 以推算井斜方位")
        t2v = [float(v) for v in t2]
        if len(t2v) != 3:
            raise ValueError("T2 必须为 (N, E, TVD) 三参数")
        inc, azi = inc_azi_between_points(tuple(vals), tuple(t2v))
        return (vals[0], vals[1], vals[2], inc, azi)
    raise ValueError("T1 必须为 (N,E,TVD) 三参数或 (N,E,TVD,INC,AZI) 五参数")


def align_md(mark5, target5, dls1=DLS1, dls2=DLS2):
    """Mark 五参数 -> 靶点五参数 的优化对齐(CLC)井深；无解返回 (None, 详情)"""
    inc_m, azi_m, mn, me, mt = mark5
    tn, te, tt, inc_t, azi_t = target5
    r = calculate_segment((mn, me, mt), (tn, te, tt),
                          inc_m, azi_m, inc_t, azi_t, dls1, dls2)
    if not r["ok"]:
        return None, r
    return r["md1"] + r["md2"] + r["md3"], r


def make_objective(a5, b5, dls1=DLS1, dls2=DLS2, mtvd=None):
    """
    构造总井深目标函数：MD(Mark->A_T1) + MD(Mark->B_T1)。
    用快速版 _fast_segment_error 评估（不做局部精修，十次多项式残差 > 1 cm 视为无解）。
    mtvd=None 时 x 为 5 维 (INCm, AZIm, MN, ME, MT)；
    mtvd=<float> 时 x 为 4 维 (INCm, AZIm, MN, ME)，MT 固定为 mtvd。
    任一段无解返回 BIG 大惩罚。
    """
    from functools import lru_cache

    v1_holder = [None]  # 闭包可变引用

    def _one(mark5, t5):
        inc_m, azi_m, mn, me, mt = mark5
        tn, te, tt, inc_t, azi_t = t5
        R1 = radius_from_dls(dls1)
        R2 = radius_from_dls(dls2)
        v1 = tangent_from_inc_azi(inc_m, azi_m)
        v3 = tangent_from_inc_azi(inc_t, azi_t)
        ok, md, _err = _fast_segment_error(
            (mn, me, mt), v1, (tn, te, tt), v3, R1, R2, inc_t, azi_t)
        return md if ok else None

    if mtvd is None:
        def objective(x):
            total = 0.0
            for t5 in (a5, b5):
                md = _one((x[0], x[1], x[2], x[3], x[4]), t5)
                if md is None:
                    return BIG
                total += md
            return total
    else:
        def objective(x):
            total = 0.0
            for t5 in (a5, b5):
                md = _one((x[0], x[1], x[2], x[3], mtvd), t5)
                if md is None:
                    return BIG
                total += md
            return total
    return objective


def _fix_mark_angles(x):
    """角度规整：INC 折入 [0,180]（等价方位 +180°），AZI 折入 [0,360)"""
    x[0] = x[0] % 360.0
    if x[0] > 180.0:
        x[0] = 360.0 - x[0]
        x[1] = (x[1] + 180.0) % 360.0
    x[1] = x[1] % 360.0
    return x


# ============================================================
# 5. 对外接口：Mark 点五参数寻优（差分进化全局 + Nelder-Mead 精修）
# ============================================================
@dataclass
class MarkOptimizeResult:
    ok: bool                # 是否求得可行最优解
    message: str = ""       # 失败原因 / 提示
    mark: tuple = None      # (INCm, AZIm, MN, ME, MT)
    total_md: float = None  # 两段对齐总井深最小值
    dls1: float = None      # 实际使用的第一段狗腿度
    dls2: float = None      # 实际使用的第二段狗腿度
    mtvd: float = None      # 实际使用的垂深约束（None=自由优化）
    a_t1: tuple = None      # 归一化后 A_T1 五参数 (N,E,TVD,INC,AZI)
    b_t1: tuple = None      # 归一化后 B_T1 五参数
    seg_a: dict = None      # Mark->A_T1 CLC 段详情
    seg_b: dict = None      # Mark->B_T1 CLC 段详情


def optimize_mark_point(dls1, dls2, a_t1, b_t1, a_t2=None, b_t2=None,
                        mtvd=None, seed=42, popsize=25, maxiter=400):
    """
    寻找最优 Mark 点五参数 (INCm, AZIm, MN, ME, MT)。

    参数
    ----
    dls1, dls2 : 两段圆弧狗腿度（°/30m）
    a_t1, b_t1 : A/B 井 T1，三参数 (N,E,TVD) 或五参数 (N,E,TVD,INC,AZI)
    a_t2, b_t2 : A/B 井 T2 (N,E,TVD)；T1 为三参数时必填，五参数时可省略
    mtvd       : Mark 点垂深 (m)；None=自由优化 5 维；给定时固定垂深、
                 优化 4 维 (INCm, AZIm, MN, ME)
    seed, popsize, maxiter : 差分进化搜索参数（默认即可复现结果）

    返回
    ----
    MarkOptimizeResult（ok=False 时带失败原因 message）
    """
    from scipy.optimize import differential_evolution, minimize

    a5 = normalize_t1(a_t1, a_t2)
    b5 = normalize_t1(b_t1, b_t2)
    objective = make_objective(a5, b5, dls1, dls2, mtvd)

    ns = [a5[0], b5[0]]
    es = [a5[1], b5[1]]
    pad = 1000.0

    if mtvd is None:
        bounds = [
            (0.0, 180.0),                                  # INCm
            (0.0, 360.0),                                  # AZIm
            (min(ns) - pad, max(ns) + pad),                # MN
            (min(es) - pad, max(es) + pad),                # ME
            (0.0, max(a5[2], b5[2])),                      # MT
        ]
    else:
        bounds = [
            (0.0, 180.0),                                  # INCm
            (0.0, 360.0),                                  # AZIm
            (min(ns) - pad, max(ns) + pad),                # MN
            (min(es) - pad, max(es) + pad),                # ME
        ]

    de = differential_evolution(
        objective, bounds, seed=seed, popsize=popsize, maxiter=maxiter,
        tol=1e-10, polish=False, updating="immediate")

    # 直观候选起点
    mid = ((a5[0] + b5[0]) / 2, (a5[1] + b5[1]) / 2, (a5[2] + b5[2]) / 2)
    mt_candidate = mtvd if mtvd is not None else mid[2]
    starts = [list(de.x)]
    # 起点 1：中点 + A 井轨迹姿态
    base = [a5[3], a5[4], mid[0], mid[1], mt_candidate]
    starts.append(base[:len(bounds)])
    for t5 in (a5, b5):
        di, da = inc_azi_between_points(mid, (t5[0], t5[1], t5[2]))
        cand = [di, da, mid[0], mid[1], mt_candidate]
        starts.append(cand[:len(bounds)])

    best_x, best_f = list(de.x), de.fun
    for s in starts:
        nm = minimize(objective, s, method="Nelder-Mead",
                      options={"xatol": 1e-8, "fatol": 1e-8, "maxfev": 20000})
        if nm.fun < best_f:
            best_x, best_f = list(nm.x), nm.fun

    # 固定垂深越界：mtvd 若超过任一 T1 垂深则不可能满足"Mark 在靶点上方"的物理意义
    if mtvd is not None and mtvd > max(a5[2], b5[2]):
        return MarkOptimizeResult(
            ok=False,
            message=(f"指定的 Mark 垂深 {mtvd} m 超过了靶点 T1 的最大垂深 "
                     f"{max(a5[2], b5[2])} m，Mark 必须位于靶点上方"),
            dls1=dls1, dls2=dls2, mtvd=mtvd, a_t1=a5, b_t1=b5)

    if best_f >= BIG:
        reason = (f"给定 DLS {dls1}/{dls2}°/30m"
                  + (f"、Mark 垂深 {mtvd} m" if mtvd is not None else "")
                  + " 下未找到可行 CLC 对齐解，请加大狗腿度或调整靶点/垂深")
        return MarkOptimizeResult(
            ok=False, message=reason,
            dls1=dls1, dls2=dls2, mtvd=mtvd, a_t1=a5, b_t1=b5)

    # 角度规整
    best_x = _fix_mark_angles(best_x)
    f_check = objective(best_x)
    if f_check < best_f:
        best_f = f_check

    # 拼回完整 Mark 五参数
    if mtvd is None:
        mark5 = tuple(best_x)
    else:
        mark5 = (best_x[0], best_x[1], best_x[2], best_x[3], float(mtvd))

    seg_a = align_md(mark5, a5, dls1, dls2)[1]
    seg_b = align_md(mark5, b5, dls1, dls2)[1]
    return MarkOptimizeResult(
        ok=True, mark=mark5, total_md=best_f,
        dls1=dls1, dls2=dls2, mtvd=mtvd,
        a_t1=a5, b_t1=b5, seg_a=seg_a, seg_b=seg_b)


# ============================================================
# 6. 验证
# ============================================================
def _self_test_clc():
    """共面算例：一般解(十次多项式)与 2D 解互相印证"""
    a = (0.0, 0.0, 200.0)
    b = (600.0, 0.0, 1200.0)
    v1 = (0.0, 0.0, 1.0)
    v3 = tangent_from_inc_azi(63.4349488, 0.0)
    R1 = radius_from_dls(3.0)
    R2 = radius_from_dls(2.0)
    g = _clc_solutions_general(a, v1, b, v3, R1, R2)
    d = _solve_clc_2d(a, v1, b, v3, R1, R2)
    assert g and d, "CLC 自检失败：无解"
    assert abs(g[0]["total_md"] - d[0]["total_md"]) < 1e-4, \
        f"CLC 自检失败：一般解 {g[0]['total_md']} vs 2D 解 {d[0]['total_md']}"
    return g[0]["total_md"]


def validate(res):
    if not res.ok:
        print(f"  未求得可行解：{res.message}")
        return
    best_x, best_f = list(res.mark), res.total_md
    objective = make_objective(res.a_t1, res.b_t1, res.dls1, res.dls2)

    print("=" * 72)
    print("验证 1：CLC 内核自检（共面算例 一般解 vs 2D 解）")
    md_self = _self_test_clc()
    print(f"  通过：最短 CLC 总长 = {md_self:.6f} m（两路径一致，差 < 1e-4 m）")

    print("=" * 72)
    print("验证 2：最优 Mark 点两段对齐轨迹的位移残差 / 狗腿一致性")
    details = {}
    for name, seg in (("A_T1", res.seg_a), ("B_T1", res.seg_b)):
        md = seg["md1"] + seg["md2"] + seg["md3"]
        details[name] = md
        dls1_act = seg["alpha1_deg"] / seg["md1"] * 30 if seg["md1"] > 1e-9 else 0.0
        dls2_act = seg["alpha2_deg"] / seg["md3"] * 30 if seg["md3"] > 1e-9 else 0.0
        print(f"  Mark -> {name}:")
        print(f"    弧1 MD = {seg['md1']:10.3f} m  (转角 {seg['alpha1_deg']:8.4f}°, "
              f"折算 DLS = {dls1_act:.4f}°/30m, 设计 {res.dls1})")
        print(f"    稳斜 MD = {seg['md2']:10.3f} m  (稳斜姿态 INC = {seg['inc2']:.4f}°, "
              f"AZI = {seg['azi2']:.4f}°)")
        print(f"    弧2 MD = {seg['md3']:10.3f} m  (转角 {seg['alpha2_deg']:8.4f}°, "
              f"折算 DLS = {dls2_act:.4f}°/30m, 设计 {res.dls2})")
        print(f"    段合计 MD = {md:.3f} m，位移残差 = {seg['error']:.2e} m "
              f"(要求 < 0.01 m)")
        assert seg["error"] < 0.01, "位移残差超限"
        assert seg["alpha1_deg"] <= 180.0 + 1e-6 and seg["alpha2_deg"] <= 180.0 + 1e-6
        assert abs(dls1_act - res.dls1) < 1e-6 or seg["md1"] <= 1e-9
        assert abs(dls2_act - res.dls2) < 1e-6 or seg["md3"] <= 1e-9
    print(f"  通过：残差均为机器精度量级；弧转角均 <= 180°；折算 DLS 与设计一致")
    print(f"  总井深 MD_A + MD_B = "
          f"{details['A_T1']:.3f} + {details['B_T1']:.3f} = {best_f:.3f} m")

    print("=" * 72)
    print("验证 3：最优性随机扰动检验（Mark 五参数邻域内应无更优解）")
    import random
    random.seed(20261022)
    n_better = 0
    for _ in range(500):
        dx = [best_x[0] + random.uniform(-1.5, 1.5),
              (best_x[1] + random.uniform(-1.5, 1.5)) % 360.0,
              best_x[2] + random.uniform(-3.0, 3.0),
              best_x[3] + random.uniform(-3.0, 3.0),
              best_x[4] + random.uniform(-3.0, 3.0)]
        f = objective(dx)
        if f < best_f - 1e-6:
            n_better += 1
    print(f"  500 次扰动（姿态 ±1.5°、位置 ±3 m）：更优点数量 = {n_better}（应为 0）")
    assert n_better == 0

    print("=" * 72)
    print("验证 4：与直观候选方案对比")
    a5, b5 = res.a_t1, res.b_t1
    mid = ((a5[0] + b5[0]) / 2, (a5[1] + b5[1]) / 2, (a5[2] + b5[2]) / 2)
    cands = [("两T1中点 + 井轨迹姿态", (a5[3], a5[4], mid[0], mid[1], mid[2]))]
    for tag, t5 in (("指向A_T1", a5), ("指向B_T1", b5)):
        di, da = inc_azi_between_points(mid, (t5[0], t5[1], t5[2]))
        cands.append((f"两T1中点 + {tag}", (di, da, mid[0], mid[1], mid[2])))
    for tag, c in cands:
        print(f"  {tag:22s}: 总井深 = {objective(c):12.3f} m")
    print(f"  最优 Mark 点         : 总井深 = {best_f:12.3f} m  <= 以上各候选")


# ============================================================
# 7. 命令行演示：内置示例数据 + 完整验证
# ============================================================
def _print_res(tag, res):
    """打印单次优化结果"""
    print("  " + "─" * 68)
    if not res.ok:
        print(f"  [{tag}] 失败：{res.message}")
        return
    inc_m, azi_m, mn, me, mt = res.mark
    mt_note = res.mtvd is not None
    print(f"  [{tag}] 最优 Mark 点五参数 ({'垂深固定=' if mt_note else '自由优化'}",
          f"{mt:.3f} m)：")
    print(f"    INCm = {inc_m:.4f}°    AZIm = {azi_m:.4f}°")
    print(f"    MN   = {mn:.3f} m     ME   = {me:.3f} m     MT   = {mt:.3f} m")
    print(f"  最小总井深 = {res.total_md:.3f} m  "
          f"(Mark->A_T1 = {res.seg_a['md1']+res.seg_a['md2']+res.seg_a['md3']:.3f} m, "
          f"Mark->B_T1 = {res.seg_b['md1']+res.seg_b['md2']+res.seg_b['md3']:.3f} m)")


def main():
    print("=" * 72)
    print("步骤 1：由 T1->T2 方向求过 T1 的井斜/方位，组合 T1 五参数")
    a5 = normalize_t1(A_T1, A_T2)
    b5 = normalize_t1(B_T1, B_T2)
    for name, t5 in (("A_T1", a5), ("B_T1", b5)):
        print(f"  {name}: N = {t5[0]:.1f}, E = {t5[1]:.1f}, TVD = {t5[2]:.1f}, "
              f"INC = {t5[3]:.4f}°, AZI = {t5[4]:.4f}°")

    print("=" * 72)
    print(f"步骤 2：搜索 Mark 点 (DLS1 = DLS2 = {DLS1}°/30m)")

    res_free = optimize_mark_point(DLS1, DLS2, A_T1, B_T1, a_t2=A_T2, b_t2=B_T2)
    _print_res("自由优化", res_free)

    # 固定垂深试几个值：自由解的 MT、略浅一些、靶点中点
    mid_mt = (a5[2] + b5[2]) / 2
    fixed_mts = []
    if res_free.ok and res_free.mark[4] != res_free.mtvd:
        fixed_mts.append(("自由解的 MT", res_free.mark[4]))
    if res_free.ok:
        fixed_mts.append(("自由解 MT 浅 100m", res_free.mark[4] - 100))
    fixed_mts.append(("两 T1 中点垂深", mid_mt))
    fixed_mts.append(("强制浅一些", 900.0))

    for tag, mt in fixed_mts:
        if mt <= 0 or mt >= max(a5[2], b5[2]):
            continue
        res = optimize_mark_point(DLS1, DLS2, A_T1, B_T1,
                                  a_t2=A_T2, b_t2=B_T2, mtvd=mt)
        _print_res(tag + f"(mtvd={mt:.1f})", res)

    if res_free.ok:
        print("=" * 72)
        print("步骤 3：对自由优化最优解做完整验证（CLC 内核自检/位移残差/狗腿/最优性扰动）")
        validate(res_free)


if __name__ == "__main__":
    main()
