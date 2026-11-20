"""提示时点轮换试行的可复跑分析（Python 3.11 标准库）。

口径：
- 分派以 assignment 中已公布的锁定名单为准；转班、跨班接触不重写分派。
- 结果窗口以 windows 中“取消后重新发布的有效窗口”为准；没有有效窗口的班
  不进入点估计的分母，但在区间/边界中保留。
- 主要估计是区组内“分派组-对照组”差值的等权平均；区组是随机单位，学生不是。
- delivery 只用于可证实接触的分层描述，不用于定义随机组。
- contacts / moves 只用于接触审计和敏感性描述，不由得分反推。

运行：
    python3 -I trial_analysis.py
    python3 -I trial_analysis.py --json analysis_results.json
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from record_reader import read_records  # noqa: E402

T975 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
    7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179,
    13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101,
    19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064,
    25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}
T80 = {
    1: 1.000, 2: 0.816, 3: 0.765, 4: 0.741, 5: 0.727, 6: 0.718,
    7: 0.711, 8: 0.706, 9: 0.703, 10: 0.700, 11: 0.697, 12: 0.695,
    13: 0.694, 14: 0.692, 15: 0.691, 16: 0.690, 17: 0.689, 18: 0.688,
    19: 0.688, 20: 0.687, 21: 0.686, 22: 0.686, 23: 0.685, 24: 0.685,
    25: 0.684, 26: 0.684, 27: 0.684, 28: 0.683, 29: 0.683, 30: 0.683,
}


def tcrit(df: int) -> float:
    return T975.get(df, 1.96)


def tpow(df: int) -> float:
    return T80.get(df, 0.674)


def avg(values):
    return sum(values) / len(values)


def stdev(values):
    return statistics.stdev(values) if len(values) > 1 else 0.0


def signflip_p(values) -> float:
    """精确符号翻转双侧 p 值；values 为区组/接触簇层面的配对差值。"""
    observed = abs(avg(values))
    hits = 0
    for signs in itertools.product((1, -1), repeat=len(values)):
        if abs(avg([s * v for s, v in zip(signs, values)])) >= observed - 1e-12:
            hits += 1
    return hits / 2 ** len(values)


def mean_ci(values):
    m = avg(values)
    se = stdev(values) / math.sqrt(len(values))
    half = tcrit(len(values) - 1) * se
    return {"n": len(values), "mean": m, "sd": stdev(values), "se": se,
            "lo": m - half, "hi": m + half, "p_signflip": signflip_p(values)}


def cluster_mean(values_by_cluster):
    """按接触簇汇总的均值及其聚类稳健标准误。"""
    all_values = [v for vs in values_by_cluster.values() for v in vs]
    n, g = len(all_values), len(values_by_cluster)
    m = avg(all_values)
    if g < 2:
        return {"n": n, "g": g, "mean": m, "se": None, "lo": None, "hi": None}
    var = g / (g - 1) * sum((sum(v - m for v in vs)) ** 2
                           for vs in values_by_cluster.values()) / n ** 2
    se = math.sqrt(var)
    half = tcrit(g - 1) * se
    return {"n": n, "g": g, "mean": m, "se": se, "lo": m - half, "hi": m + half}


def cluster_diff(rows):
    """rows: (score, is_treatment, cluster)。聚类稳健的均值差。"""
    treated = [y for y, t, _ in rows if t]
    control = [y for y, t, _ in rows if not t]
    mt, mc = avg(treated), avg(control)
    influence = defaultdict(float)
    for y, t, cl in rows:
        if t:
            influence[cl] += (y - mt) / len(treated)
        else:
            influence[cl] -= (y - mc) / len(control)
    g = len({cl for _, _, cl in rows})
    var = g / (g - 1) * sum(v * v for v in influence.values()) if g > 1 else float("nan")
    se = math.sqrt(var)
    half = tcrit(g - 1) * se
    return {"diff": mt - mc, "se": se, "g": g,
            "lo": mt - mc - half, "hi": mt - mc + half,
            "n_t": len(treated), "n_c": len(control)}


def effective_windows(windows):
    """每班一个有效结果窗口；取消后仅在更晚发布的有效窗口才算补开。"""
    by_room = defaultdict(list)
    for row in windows:
        by_room[row["room"]].append(row)
    result = {}
    for room, rows in by_room.items():
        cancelled = [r for r in rows if r["state"] == "cancelled"]
        active = [r for r in rows if r["state"] == "active"]
        if not cancelled:
            valid, basis = active, "scheduled"
        else:
            last_cancel = max(r["open_day"] for r in cancelled)
            valid = [r for r in active if r["open_day"] > last_cancel]
            basis = "reopened" if valid else "cancelled_no_valid_window"
        if valid:
            result[room] = {
                "open": min(r["open_day"] for r in valid),
                "close": max(r["close_day"] for r in valid),
                "valid": True, "basis": basis,
            }
        else:
            result[room] = {"open": None, "close": None,
                            "valid": False, "basis": basis}
    return result


def build(folder):
    tables = read_records(folder)
    assignment = tables["assignment"]
    room_info = {}
    for row in assignment:
        room_info[row["room"]] = {
            "week": row["week"], "block": row["block"],
            "assigned": row["assigned"], "published": row["published"],
        }
    enrollment = tables["enrollment"]
    room_of = {row["student"]: row["room"] for row in enrollment}
    windows = effective_windows(tables["windows"])

    by_student = defaultdict(list)
    for row in tables["observations"]:
        by_student[row["student"]].append(row)
    scores, excluded = {}, []
    for student, rows in by_student.items():
        room = room_of[student]
        w = windows[room]
        keep = [r for r in rows if w["valid"] and w["open"] <= r["day"] <= w["close"]]
        drop = [r for r in rows if r not in keep]
        if drop:
            excluded.append({"student": student, "room": room,
                             "dropped": drop, "window": w})
        if keep:
            scores[student] = avg([r["score"] for r in keep])

    rooms_by_block = defaultdict(list)
    for room, info in room_info.items():
        rooms_by_block[(info["week"], info["block"])].append(room)
    blocks = []
    for key in sorted(rooms_by_block):
        rooms = rooms_by_block[key]
        treatment = [r for r in rooms if room_info[r]["assigned"]]
        control = [r for r in rooms if not room_info[r]["assigned"]]
        if len(treatment) != 1 or len(control) != 1:
            raise ValueError(f"区组 {key} 不是一处理一对照")
        t, c = treatment[0], control[0]
        students_t = [r["student"] for r in enrollment if r["room"] == t]
        students_c = [r["student"] for r in enrollment if r["room"] == c]
        scores_t = [scores[s] for s in students_t if s in scores]
        scores_c = [scores[s] for s in students_c if s in scores]
        diff = avg(scores_t) - avg(scores_c) if scores_t and scores_c else None
        blocks.append({
            "week": key[0], "block": key[1], "treatment": t, "control": c,
            "n_t": len(students_t), "n_c": len(students_c),
            "obs_t": len(scores_t), "obs_c": len(scores_c),
            "scores_t": scores_t, "scores_c": scores_c,
            "mean_t": avg(scores_t) if scores_t else None,
            "mean_c": avg(scores_c) if scores_c else None,
            "diff": diff,
            "window_t": windows[t], "window_c": windows[c],
        })

    def cell_bounds(values, n, lo, hi):
        return (sum(values) + lo * (n - len(values))) / n, \
               (sum(values) + hi * (n - len(values))) / n

    for b in blocks:
        lo_t, hi_t = cell_bounds(b["scores_t"], b["n_t"], 0, 10)
        lo_c, hi_c = cell_bounds(b["scores_c"], b["n_c"], 0, 10)
        b["bounds_0_10"] = (lo_t - hi_c, hi_t - lo_c)
        lo_t, hi_t = cell_bounds(b["scores_t"], b["n_t"], 4, 10)
        lo_c, hi_c = cell_bounds(b["scores_c"], b["n_c"], 4, 10)
        b["bounds_empirical"] = (lo_t - hi_c, hi_t - lo_c)
        # 只对“没有有效窗口”的班按 [0,10] 处理；其余缺测暂时按已观测均值。
        st = (b["mean_t"], b["mean_t"]) if b["window_t"]["valid"] else (0, 10)
        sc = (b["mean_c"], b["mean_c"]) if b["window_c"]["valid"] else (0, 10)
        b["bounds_structural"] = (st[0] - sc[1], st[1] - sc[0])

    # 接触/转班把区组连成簇；只用于标准误与审计，不改分派。
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    room_block = {}
    for b in blocks:
        key = (b["week"], b["block"])
        find(key)
        room_block[b["treatment"]] = key
        room_block[b["control"]] = key
    for row in tables["contacts"]:
        union(room_block[row["room"]], room_block[row["other"]])
    for row in tables["moves"]:
        union(room_block[room_of[row["student"]]], room_block[row["to_room"]])
    block_component = {key: find(key) for key in room_block.values()}
    room_component = {room: block_component[key] for room, key in room_block.items()}
    student_component = {s: room_component[room] for s, room in room_of.items()}

    return {
        "tables": tables, "room_info": room_info, "room_of": room_of,
        "windows": windows, "scores": scores, "excluded_obs": excluded,
        "blocks": blocks, "room_block": room_block,
        "block_component": block_component, "room_component": room_component,
        "student_component": student_component,
    }


def contact_audit(ctx):
    room_info, room_block = ctx["room_info"], ctx["room_block"]
    events = []
    for row in ctx["tables"]["contacts"]:
        a, b = row["room"], row["other"]
        events.append({
            "kind": row["kind"], "week": row["week"], "day": row["day"],
            "rooms": [a, b],
            "blocks": [list(room_block[a]), list(room_block[b])],
            "same_block": room_block[a] == room_block[b],
            "cross_arm": room_info[a]["assigned"] != room_info[b]["assigned"],
        })
    moves = []
    for row in ctx["tables"]["moves"]:
        src, dst = ctx["room_of"][row["student"]], row["to_room"]
        moves.append({
            "student": row["student"], "day": row["day"],
            "from": src, "to": dst,
            "from_block": list(room_block[src]), "to_block": list(room_block[dst]),
            "cross_arm": room_info[src]["assigned"] != room_info[dst]["assigned"],
        })
    components = defaultdict(list)
    for b in ctx["blocks"]:
        components[ctx["block_component"][(b["week"], b["block"])]].append(b)
    comp_rows = []
    for key, bs in sorted(components.items(),
                          key=lambda kv: (kv[1][0]["week"], kv[1][0]["block"])):
        edges = []
        for row in ctx["tables"]["contacts"]:
            if ctx["room_component"][row["room"]] != key:
                continue
            same_block = room_block[row["room"]] == room_block[row["other"]]
            cross_arm = room_info[row["room"]]["assigned"] != room_info[row["other"]]["assigned"]
            edges.append({"kind": row["kind"], "rooms": [row["room"], row["other"]],
                          "same_block": same_block, "cross_arm": cross_arm})
        for row in ctx["tables"]["moves"]:
            src, dst = ctx["room_of"][row["student"]], row["to_room"]
            if ctx["room_component"][src] != key:
                continue
            same_block = room_block[src] == room_block[dst]
            cross_arm = room_info[src]["assigned"] != room_info[dst]["assigned"]
            edges.append({"kind": "转班", "rooms": [src, dst],
                          "same_block": same_block, "cross_arm": cross_arm})
        comp_rows.append({
            "blocks": [[b["week"], b["block"], b["treatment"], b["control"]] for b in bs],
            "units": len(bs),
            "cross_block_edges": [e for e in edges if not e["same_block"]],
            "cross_arm_edges": [e for e in edges if e["cross_arm"]],
            "blocks_sharing_outcome_information": sorted(
                {tuple(b["week"] for b in bs)}),
        })
    return {"contacts": events, "moves": moves, "components": comp_rows}


def compliance(ctx):
    tables, room_info = ctx["tables"], ctx["room_info"]
    receipt = {row["student"]: row["independent_first"] for row in tables["delivery"]}
    enrolled = tables["enrollment"]

    def status(student):
        if student not in receipt:
            return "no_receipt"
        return "independent_first" if receipt[student] else "other_order"

    table = {}
    for arm, label in ((True, "assigned"), (False, "comparison")):
        students = [r["student"] for r in enrolled
                    if room_info[r["room"]]["assigned"] is arm]
        observed = [s for s in students if s in ctx["scores"]]
        table[label] = {
            "enrolled": dict(Counter(status(s) for s in students)),
            "observed": dict(Counter(status(s) for s in observed)),
            "n_enrolled": len(students), "n_observed": len(observed),
        }
    return table


def delivered_contrasts(ctx):
    room_info = ctx["room_info"]
    tables = ctx["tables"]
    receipt = {row["student"]: row["independent_first"] for row in tables["delivery"]}

    def arm(student):
        return room_info[ctx["room_of"][student]]["assigned"]

    groups = defaultdict(list)
    for student, score in ctx["scores"].items():
        if student not in receipt:
            key = "no_receipt"
        else:
            key = "independent_first" if receipt[student] else "other_order"
        arm_label = "assigned" if arm(student) else "comparison"
        groups[(arm_label, key)].append(score)
    table = []
    for (a, key), values in sorted(groups.items()):
        table.append({"arm": a, "delivery": key, "n": len(values),
                      "mean": avg(values), "sd": stdev(values)})
    rows = []
    for student, score in ctx["scores"].items():
        if student in receipt and receipt[student] and arm(student):
            rows.append((score, True, ctx["student_component"][student]))
        elif student in receipt and not receipt[student] and not arm(student):
            rows.append((score, False, ctx["student_component"][student]))
    concordant = cluster_diff(rows) if rows else None
    rows = []
    for student, score in ctx["scores"].items():
        if student in receipt:
            rows.append((score, receipt[student], ctx["student_component"][student]))
    any_receipt = cluster_diff(rows) if rows else None
    return {"groups": table, "concordant": concordant,
            "delivered_true_vs_false": any_receipt}


def audit_proposals(ctx, rows):
    """把候选名单按“是否还能形成独立、一处理一对照的区组”分级。

    A：区内教师不同、无讨论组、教师不跨区组——可保留区组随机化。
    B：有联合讨论，但讨论只发生在同区组内——可保留区组，但两班不再互为
       独立对照，只能回答“该讨论组整体”的效果；需另设未参与讨论的对照。
    C：同教师带两班，或教师跨区组，或讨论组跨区组/跨臂——按班分派已不能
       回答原问题；只能整簇分派或重新排期。
    """
    out = []
    for name in sorted({r["proposal"] for r in rows}):
        prs = [r for r in rows if r["proposal"] == name]
        by_block = defaultdict(list)
        for r in prs:
            by_block[r["block"]].append(r)
        block_rows = []
        for block, br in sorted(by_block.items()):
            teachers = {r["teacher"] for r in br}
            partners = {r["partner"] for r in br if r["partner"]}
            partner_rooms = {r["partner"] for r in br if r["partner"]}
            partner_in_block = partner_rooms == {r["room"] for r in br}
            partner_outside = partner_rooms - {r["room"] for r in br}
            block_rows.append({
                "block": block,
                "rooms": [r["room"] for r in br],
                "n_rooms": len(br),
                "eligible": sum(r["eligible"] for r in br),
                "teachers": sorted(teachers),
                "shared_teacher": len(teachers) == 1 and len(br) > 1,
                "partner_links": len(partners),
                "discussion_within_block": bool(partners) and partner_in_block
                and not partner_outside,
                "discussion_outside_block": bool(partner_outside),
            })
        teacher_blocks = defaultdict(set)
        for r in prs:
            teacher_blocks[r["teacher"]].add(r["block"])
        cross_block_teacher = {t: sorted(bs) for t, bs in teacher_blocks.items()
                               if len(bs) > 1}
        # 讨论组是否跨越区组
        room_block = {r["room"]: r["block"] for r in prs}
        partner_cross_block = any(
            r["partner"] in room_block and room_block[r["partner"]] != r["block"]
            for r in prs if r["partner"]
        )
        partner_unknown = any(r["partner"] and r["partner"] not in room_block
                              for r in prs if r["partner"])
        shared_teacher_blocks = [b["block"] for b in block_rows if b["shared_teacher"]]
        discussion_blocks = [b["block"] for b in block_rows
                             if b["discussion_within_block"]]
        discussion_outside = any(b["discussion_outside_block"] for b in block_rows)

        reasons = []
        if cross_block_teacher:
            reasons.append(f"教师跨区组: {cross_block_teacher}")
        if partner_cross_block or partner_unknown or discussion_outside:
            reasons.append("讨论组跨区组或指向名单外的班")
        if shared_teacher_blocks:
            reasons.append(f"同教师带两班: 区组 {shared_teacher_blocks}")
        if discussion_blocks:
            reasons.append(f"区内联合讨论: 区组 {discussion_blocks}")

        if cross_block_teacher or partner_cross_block or partner_unknown or discussion_outside:
            grade = "C"
            verdict = ("教师或讨论组跨区组混用：区组不再独立，按班分派无法保留原对照；"
                       "只能整簇分派、拆开教师/讨论组，或重排后重新抽签")
        elif shared_teacher_blocks:
            grade = "C"
            verdict = ("同一位教师带两班：练习可能经教师或同教师协调外溢到对照，"
                       "按班分派已不满足原问题的可比较条件；需拆开教师后重排")
        elif discussion_blocks:
            grade = "B"
            verdict = ("联合讨论只在区组内：可保留区组随机化，但两班不再互为独立对照；"
                       "只能回答“讨论组整体”的效果，且须另设未参与讨论的对照")
        else:
            grade = "A"
            verdict = "教师不跨班、无讨论组：保留独立区组与干净对照，可回答原问题"
        out.append({
            "proposal": name,
            "rooms": len(prs),
            "blocks": len(by_block),
            "eligible": sum(r["eligible"] for r in prs),
            "block_rows": block_rows,
            "cross_block_teacher": cross_block_teacher,
            "partner_cross_block": partner_cross_block,
            "shared_teacher_blocks": shared_teacher_blocks,
            "discussion_blocks": discussion_blocks,
            "reasons": reasons,
            "grade": grade,
            "verdict": verdict,
        })
    return out


def required_blocks(effect, sd):
    n = 2
    while n < 500:
        if (tcrit(n - 1) + tpow(n - 1)) * sd / math.sqrt(n) <= effect:
            return n
        n += 1
    return None


def approx_power(effect, se):
    z = statistics.NormalDist()
    return z.cdf(effect / se - 1.96) + z.cdf(-effect / se - 1.96)


def mde_table(sds):
    rows = []
    for n in (4, 8, 9, 11, 12, 14, 16, 20, 24, 30):
        for sd in sds:
            se = sd / math.sqrt(n)
            rows.append({
                "blocks": n, "sd": sd,
                "half_95": tcrit(n - 1) * se,
                "mde_80": (tcrit(n - 1) + tpow(n - 1)) * se,
                "power_0.5": approx_power(0.5, se),
                "power_0.7": approx_power(0.7, se),
            })
    return rows


def summarise(ctx):
    blocks = ctx["blocks"]
    diffs = [b["diff"] for b in blocks if b["diff"] is not None]
    itt = mean_ci(diffs)
    comp_diffs = defaultdict(list)
    for b in blocks:
        if b["diff"] is not None:
            comp_diffs[ctx["block_component"][(b["week"], b["block"])]].append(b["diff"])
    itt_cluster = cluster_mean(comp_diffs)

    valid_blocks = [b for b in blocks if b["window_t"]["valid"] and b["window_c"]["valid"]]
    invalid_blocks = [b for b in blocks
                      if not (b["window_t"]["valid"] and b["window_c"]["valid"])]

    bounds = {}
    for key in ("bounds_0_10", "bounds_empirical", "bounds_structural"):
        bounds[key] = (avg([b[key][0] for b in blocks]),
                       avg([b[key][1] for b in blocks]))

    tipping = None
    if invalid_blocks:
        b = invalid_blocks[0]
        other = [b["mean_c"] for b in blocks if b["diff"] is not None]
        impute = avg(other)
        vals = []
        for c in [i / 4 for i in range(41)]:
            vals.append((c, (sum(diffs) + b["mean_t"] - c) / len(blocks),
                         signflip_p(diffs + [b["mean_t"] - c])))
        tipping = {
            "block": [b["week"], b["block"], b["treatment"], b["control"]],
            "control_mean_imputed_at_other_controls": impute,
            "overall_at_impute": (sum(diffs) + b["mean_t"] - impute) / len(blocks),
            "min_p": min(v[2] for v in vals),
            "max_abs_mean": max(vals, key=lambda v: abs(v[1]))[1],
            "range": vals,
        }

    # 学生级对比：只用于说明“不是随机单位”，不作为主估计。
    assigned = [s for s in ctx["scores"]
                if ctx["room_info"][ctx["room_of"][s]]["assigned"]]
    comparison = [s for s in ctx["scores"]
                  if not ctx["room_info"][ctx["room_of"][s]]["assigned"]]
    yt = [ctx["scores"][s] for s in assigned]
    yc = [ctx["scores"][s] for s in comparison]
    student_naive = {
        "n_t": len(yt), "n_c": len(yc),
        "mean_t": avg(yt), "mean_c": avg(yc), "diff": avg(yt) - avg(yc),
        "se_welch": math.sqrt(statistics.variance(yt) / len(yt) +
                              statistics.variance(yc) / len(yc)),
    }
    rows = [(ctx["scores"][s], ctx["room_info"][ctx["room_of"][s]]["assigned"],
             ctx["student_component"][s]) for s in ctx["scores"]]
    student_cluster = cluster_diff(rows)

    # 接触无关子集：只作敏感性描述，不当作新的随机对照。
    affected = set()
    for row in ctx["tables"]["contacts"]:
        affected |= {row["room"], row["other"]}
    for row in ctx["tables"]["moves"]:
        affected |= {ctx["room_of"][row["student"]], row["to_room"]}
    contact_free = [b for b in blocks
                    if b["treatment"] not in affected and b["control"] not in affected]
    control_clean = [b for b in blocks if b["control"] not in affected]
    treatment_clean = [b for b in blocks if b["treatment"] not in affected]

    def subset(bs):
        d = [b["diff"] for b in bs if b["diff"] is not None]
        return mean_ci(d) if d else None

    # 敏感性：转班学生按首班保留（主分析）vs 从两侧剔除。
    movers = {row["student"] for row in ctx["tables"]["moves"]}
    score = ctx["scores"]
    block_diffs_nomove = []
    for b in blocks:
        def m(room):
            vals = [score[s] for _, s in [(b, r["student"]) for r in ctx["tables"]["enrollment"]
                                          if r["room"] == room]
                    if s in score and s not in movers]
            return avg(vals) if vals else None
        mt, mc = m(b["treatment"]), m(b["control"])
        if mt is not None and mc is not None:
            block_diffs_nomove.append(mt - mc)

    # 敏感性：把每班“首个窗口”当作有效（忽略取消/补开）会得到什么。
    # 这是常见错误口径：2D 在取消窗口之后补开的日 35 观测会被丢掉。
    naive_windows = {}
    by_room = defaultdict(list)
    for row in ctx["tables"]["windows"]:
        by_room[row["room"]].append(row)
    for room, rows in by_room.items():
        first = min(rows, key=lambda r: (r["open_day"], r["close_day"], r["day"]))
        naive_windows[room] = (first["open_day"], first["close_day"])
    naive_scores = {}
    for row in ctx["tables"]["observations"]:
        room = ctx["room_of"][row["student"]]
        if room in naive_windows and \
                naive_windows[room][0] <= row["day"] <= naive_windows[room][1]:
            naive_scores[row["student"]] = row["score"]
    naive_diffs = []
    rows_of_room = defaultdict(list)
    for row in ctx["tables"]["enrollment"]:
        rows_of_room[row["room"]].append(row["student"])
    for b in blocks:
        def m2(room):
            vals = [naive_scores[s] for s in rows_of_room[room] if s in naive_scores]
            return avg(vals) if vals else None
        mt, mc = m2(b["treatment"]), m2(b["control"])
        if mt is not None and mc is not None:
            naive_diffs.append(mt - mc)

    sensitivity = {
        "primary": itt,
        "movers_excluded": mean_ci(block_diffs_nomove) if block_diffs_nomove else None,
        "naive_windows": mean_ci(naive_diffs) if naive_diffs else None,
    }

    # 证据分级：哪些比较有设计依据，哪些只能描述。
    ledger = [
        {"question": "按锁定分派，试行班比对照班高多少（主估计）",
         "status": "有设计依据",
         "estimate": itt,
         "note": "11 个完整区组的等权平均；随机化单位是区组。缺测区组另按边界处理。"},
        {"question": "3H 无有效窗口是否会把结论翻向另一边",
         "status": "有设计依据（区间）",
         "estimate": {"lo": bounds["bounds_0_10"][0],
                      "hi": bounds["bounds_0_10"][1]},
         "note": "只对无窗口班取 0–10 的任意补值；点估计不在分母里消失。"},
        {"question": "接触只发生在部分班时，原分派是否仍可比",
         "status": "仅描述",
         "estimate": {"contact_free": subset(contact_free),
                      "control_clean": subset(control_clean),
                      "treatment_clean": subset(treatment_clean)},
         "note": "按实际接触事后切分会打破随机化，且样本小；这些子集不能当作新的随机对照。"},
        {"question": "实际先独立写的人是否得分更高",
         "status": "仅描述",
         "estimate": delivered_contrasts(ctx)["delivered_true_vs_false"],
         "note": "交付顺序与得分可能同时受班级/教师影响，不能反过来推定随机分派。"},
        {"question": "把同向交付的人与对照相比",
         "status": "仅描述",
         "estimate": delivered_contrasts(ctx)["concordant"],
         "note": "这是依从者对比（per-protocol 式），不是随机化对比；不能外推到全体。"},
    ]

    return {
        "n_blocks": len(blocks),
        "n_complete_blocks": len(diffs),
        "n_invalid_window_blocks": len(invalid_blocks),
        "windows": ctx["windows"],
        "excluded_observations": ctx["excluded_obs"],
        "blocks": [{k: v for k, v in b.items()
                    if k not in ("scores_t", "scores_c")} for b in blocks],
        "itt_complete_case": itt,
        "itt_cluster": itt_cluster,
        "bounds": bounds,
        "tipping": tipping,
        "student_naive": student_naive,
        "student_cluster": student_cluster,
        "contact_free": {"blocks": [[b["week"], b["block"], b["treatment"], b["control"]]
                                    for b in contact_free], "estimate": subset(contact_free)},
        "control_clean": {"blocks": [[b["week"], b["block"], b["treatment"], b["control"]]
                                    for b in control_clean], "estimate": subset(control_clean)},
        "treatment_clean": {"blocks": [[b["week"], b["block"], b["treatment"], b["control"]]
                                      for b in treatment_clean], "estimate": subset(treatment_clean)},
        "compliance": compliance(ctx),
        "delivered": delivered_contrasts(ctx),
        "audit": contact_audit(ctx),
        "proposals": audit_proposals(ctx, ctx["tables"]["proposals"]),
        "sensitivity": sensitivity,
        "ledger": ledger,
        "power": mde_table([stdev([b["diff"] for b in blocks if b["diff"] is not None]),
                            0.804]),
        "required_blocks": {
            f"{effect:.1f}": {f"sd_{sd:.3f}": required_blocks(effect, sd)
                              for sd in (0.644, 0.804)}
            for effect in (0.4, 0.5, 0.6, 0.7, 1.0)
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", type=Path, default=HERE / "records")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    ctx = build(args.records)
    result = summarise(ctx)
    # 学生级是错误单位下的参照；与区组等权估计差多少正说明这一点。
    result["student_naive"]["diff_from_block_itt"] = \
        result["student_naive"]["diff"] - result["itt_complete_case"]["mean"]

    print("== 单位与窗口 ==")
    print(f"区组 {result['n_blocks']} 个；两侧均有观测 {result['n_complete_blocks']} 个；"
          f"无效窗口区组 {result['n_invalid_window_blocks']} 个")
    for room, w in sorted(result["windows"].items()):
        span = "无有效窗口" if not w["valid"] else f"{w['open']}-{w['close']}"
        print(f"  {room}: {span} ({w['basis']})")
    print(f"窗口外观测 {len(result['excluded_observations'])} 条")

    print("\n== 区组明细 ==")
    print("  轮 区组 处理 对照  obs(T/C)  mean(T)  mean(C)   diff     0–10 边界")
    for b in result["blocks"]:
        d = "  --  " if b["diff"] is None else f"{b['diff']:+.3f}"
        mt = " -- " if b["mean_t"] is None else f"{b['mean_t']:.2f}"
        mc = " -- " if b["mean_c"] is None else f"{b['mean_c']:.2f}"
        lo, hi = b["bounds_0_10"]
        print(f"  {b['week']}  {b['block']}   {b['treatment']}  {b['control']}   "
              f"{b['obs_t']}/{b['obs_c']}    {mt}     {mc}    {d}   "
              f"[{lo:+.3f},{hi:+.3f}]")

    print("\n== 区组配对 ITT（完整区组） ==")
    itt = result["itt_complete_case"]
    print(f"  n={itt['n']} mean={itt['mean']:+.3f} sd={itt['sd']:.3f} "
          f"se={itt['se']:.3f} 95%CI=[{itt['lo']:+.3f},{itt['hi']:+.3f}] "
          f"符号翻转 p={itt['p_signflip']:.3f}")
    cl = result["itt_cluster"]
    print(f"  接触簇稳健: g={cl['g']} se={cl['se']:.3f} "
          f"95%CI=[{cl['lo']:+.3f},{cl['hi']:+.3f}]")
    print("  学生级（仅对照，不是随机单位）: "
          f"diff={result['student_naive']['diff']:+.3f} "
          f"se={result['student_naive']['se_welch']:.3f}；"
          f"按接触簇 se={result['student_cluster']['se']:.3f}")

    print("\n== 缺测边界 ==")
    for key, label in (("bounds_structural", "只把无有效窗口的班按 0–10"),
                       ("bounds_empirical", "所有缺测按经验支撑 4–10"),
                       ("bounds_0_10", "所有缺测按 0–10")):
        lo, hi = result["bounds"][key]
        print(f"  {label}: [{lo:+.3f},{hi:+.3f}]")
    if result["tipping"]:
        t = result["tipping"]
        print(f"  无窗口区组 {t['block']}；把对照均值设为其他对照均值 "
              f"{t['control_mean_imputed_at_other_controls']:.3f} 时总体 "
              f"{t['overall_at_impute']:+.3f}；任何 0–10 补值下最小符号翻转 "
              f"p={t['min_p']:.3f}")

    print("\n== 口径敏感性（完整区组均值差） ==")
    for label, key in (("主分析：转班按首班保留", "primary"),
                       ("剔除转班学生", "movers_excluded"),
                       ("把首个窗口当有效（忽略取消/补开，错误口径）", "naive_windows")):
        est = result["sensitivity"][key]
        if est:
            print(f"  {label}: n={est['n']} mean={est['mean']:+.3f} "
                  f"95%CI=[{est['lo']:+.3f},{est['hi']:+.3f}]")

    print("\n== 接触审计 ==")
    for e in result["audit"]["contacts"]:
        print(f"  {e['kind']} {e['rooms']} 区组={e['blocks']} "
              f"同区组={e['same_block']} 跨臂={e['cross_arm']}")
    for m in result["audit"]["moves"]:
        print(f"  转班 {m['student']}: {m['from']}->{m['to']} "
              f"区组={m['from_block']}->{m['to_block']} 跨臂={m['cross_arm']}")
    for c in result["audit"]["components"]:
        same = [e for e in c["cross_arm_edges"]]
        print(f"  接触簇: 含 {c['units']} 个区组 {c['blocks']}")
        if c["cross_block_edges"]:
            print(f"    跨区组接触: {c['cross_block_edges']}")
        if same:
            print(f"    跨臂接触: {same}")

    print("\n== 交付/依从（描述） ==")
    for arm, row in result["compliance"].items():
        print(f"  {arm}: 入组 {row['n_enrolled']} {row['enrolled']}；"
              f"有观测 {row['n_observed']} {row['observed']}")
    for row in result["delivered"]["groups"]:
        print(f"  {row['arm']:10s} {row['delivery']:18s} n={row['n']:3d} "
              f"mean={row['mean']:.3f}")
    for label, est in (("同向交付（分派且先独立 vs 对照且非先独立）",
                        result["delivered"]["concordant"]),
                       ("实际先独立 vs 实际非先独立", result["delivered"]["delivered_true_vs_false"])):
        if est:
            print(f"  {label}: diff={est['diff']:+.3f} se={est['se']:.3f} "
                  f"95%CI=[{est['lo']:+.3f},{est['hi']:+.3f}]（描述，不是随机对比）")

    print("\n== 结论台账 ==")
    for entry in result["ledger"]:
        est = entry["estimate"]
        if est and "mean" in est and "n" in est:
            shown = f"mean={est['mean']:+.3f} 95%CI=[{est['lo']:+.3f},{est['hi']:+.3f}]"
        elif est and "lo" in est:
            shown = f"[{est['lo']:+.3f},{est['hi']:+.3f}]"
        else:
            shown = ""
        print(f"  [{entry['status']}] {entry['question']} {shown}")
        print(f"      {entry['note']}")

    print("\n== 下一轮名单审计 ==")
    for p in result["proposals"]:
        shared = [b["block"] for b in p["block_rows"] if b["shared_teacher"]]
        discuss = [b["block"] for b in p["block_rows"] if b["discussion_within_block"]]
        print(f"  [{p['grade']}] {p['proposal']}: {p['blocks']} 区组/{p['rooms']} 班，"
              f"合格 {p['eligible']}；同教师区组={shared} 区内讨论区组={discuss} "
              f"跨区组教师={bool(p['cross_block_teacher'])}")
        print(f"    -> {p['verdict']}")

    print("\n== 单位数与功效（sd 取当前区组差值） ==")
    n_current_a = result["n_blocks"]
    n_a = [p for p in result["proposals"] if p["grade"] == "A"]
    n_a_blocks = sum(p["blocks"] for p in n_a)
    print(f"  当前已公布区组 {n_current_a} 个；下一轮 A 级名单可用区组 {n_a_blocks} 个"
          f"（若与当前证据合并，最多 {n_current_a + n_a_blocks} 个，但两轮条件不同，"
          f"只能作为下一轮的规划上限，不能直接合并估计）")
    for row in result["power"]:
        if row["blocks"] in (4, 8, 11, 12, 16, 20, 24):
            print(f"  {row['blocks']:2d} 区组 sd={row['sd']:.3f} "
                  f"95%半宽={row['half_95']:.3f} MDE80={row['mde_80']:.3f} "
                  f"power(0.5)={row['power_0.5']:.2f} power(0.7)={row['power_0.7']:.2f}")
    print("  达到 80% 功效所需区组数:")
    for effect, row in result["required_blocks"].items():
        print(f"    效应 {effect}: {row}")

    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                        default=str), encoding="utf-8")
        print(f"\n已写出 {args.json}")


if __name__ == "__main__":
    main()
