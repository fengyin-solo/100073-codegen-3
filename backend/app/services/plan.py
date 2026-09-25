"""养护计划业务规则：状态流转、字段校验与筛选口径都收在这里。

编排判定（间隔没到、在途冲突、排期重叠、编号重复、对象不存在）也收在本模块；
间隔与提前量的取值由 planrule 模块维护，这里只读取启用中的规则做判定。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "plan"
RULE_MODULE = "planrule"
REQUIRED_FIELDS = ["计划编号", "养护类型", "养护对象", "计划开始日期", "计划结束日期"]
EDITABLE_FIELDS = [
    "计划编号", "养护类型", "养护对象", "计划开始日期", "计划结束日期",
    "计划工期", "预算金额", "编制人员", "审批人员", "计划状态",
]
STATUS_ORDER = ["待编制", "待审批", "已批复", "已作废"]
ACTION_RULES = {"提交审批": "待审批", "确认批复": "已批复", "作废计划": "已作废"}
NEGATIVE_ACTIONS = ["作废计划"]
CLOSED_STATUS = "已作废"
IN_FLIGHT_STATUSES = {"待编制", "待审批"}
FACILITY_MODULES = (
    ("road", "设施编码", "道路名称"),
    ("bridge", "桥梁编码", "桥梁名称"),
    ("tunnel", "隧道编码", "隧道名称"),
)


def _parse_date(raw: Any) -> date | None:
    try:
        return date.fromisoformat(str(raw or "").strip())
    except ValueError:
        return None


def _to_int(raw: Any, default: int = 0) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _span(row: dict[str, Any]) -> str:
    return f"{row.get('计划开始日期') or '?'} ~ {row.get('计划结束日期') or '?'}"


def find_facility(target: str) -> dict[str, Any] | None:
    """在道路/桥梁/隧道台账里找养护对象，设施编码或名称命中都算存在。"""
    for module, code_field, name_field in FACILITY_MODULES:
        for row in store.rows(module):
            if target and target in (str(row.get(code_field, "")), str(row.get(name_field, ""))):
                return row
    return None


def active_rule(plan_type: str) -> dict[str, Any] | None:
    """取养护类型当前启用中的编排规则；没有启用规则时返回 None。"""
    for row in store.rows(RULE_MODULE):
        if row.get("养护类型") == plan_type and row.get("status") == "启用":
            return row
    return None


def find_duplicate(plan_no: str, exclude_id: int | None = None) -> dict[str, Any] | None:
    for row in store.rows(MODULE):
        if exclude_id is not None and int(row.get("id", 0)) == exclude_id:
            continue
        if plan_no and str(row.get("计划编号")) == plan_no:
            return row
    return None


def evaluate_plan(
    values: dict[str, Any],
    *,
    exclude_id: int | None = None,
    check_lead: bool = True,
) -> list[str]:
    """按编排规则判定一条计划（不必已入库），返回全部不合规原因，空列表表示合规。

    check_lead 只在登记/修改时为 True；规则调整后的重判不追溯提前量，
    否则所有临近开工的已编计划都会被误判成不合规。
    """
    problems: list[str] = []
    plan_no = str(values.get("计划编号") or "").strip()
    plan_type = str(values.get("养护类型") or "").strip()
    target = str(values.get("养护对象") or "").strip()

    duplicate = find_duplicate(plan_no, exclude_id)
    if duplicate is not None:
        problems.append(
            f"计划编号 {plan_no} 与已有养护计划（id={duplicate.get('id')}）重复，"
            "请更换计划编号，或打开那条计划修改"
        )

    if target and find_facility(target) is None:
        problems.append(
            f"养护对象「{target}」不在道路/桥梁/隧道设施台账中，请改选台账内的设施编码或名称"
        )

    start = _parse_date(values.get("计划开始日期"))
    end = _parse_date(values.get("计划结束日期"))
    if start is None or end is None:
        problems.append("计划开始日期/计划结束日期缺失或格式应为 YYYY-MM-DD")
        return _dedup(problems)
    if end < start:
        problems.append("计划结束日期早于计划开始日期，请调整排期")
        return _dedup(problems)

    rule = active_rule(plan_type)
    if rule is None:
        problems.append(
            f"养护类型「{plan_type}」没有启用中的编排规则，请先到编排规则模块配置间隔与提前量"
        )
        return _dedup(problems)

    if check_lead:
        lead = _to_int(rule.get("提前天数"))
        if (start - date.today()).days < lead:
            problems.append(
                f"按编排规则需提前 {lead} 天编制，计划开始日期 {start.isoformat()} 距今天不足 {lead} 天"
            )

    interval = _to_int(rule.get("间隔天数"))
    for row in store.rows(MODULE):
        if exclude_id is not None and int(row.get("id", 0)) == exclude_id:
            continue
        if row.get("status") == CLOSED_STATUS:
            continue
        other_no = row.get("计划编号")
        same_target = str(row.get("养护对象")) == target
        if not same_target:
            continue
        if row.get("status") in IN_FLIGHT_STATUSES:
            problems.append(
                f"养护对象「{target}」已有在途养护计划 {other_no}（状态：{row.get('status')}），"
                "不允许重复编制"
            )
        other_start = _parse_date(row.get("计划开始日期"))
        other_end = _parse_date(row.get("计划结束日期"))
        if other_start is None or other_end is None:
            continue
        if start <= other_end and other_start <= end:
            problems.append(
                f"排期 {start.isoformat()} ~ {end.isoformat()} 与养护计划 {other_no}（{_span(row)}）"
                "落在同一时间段"
            )
        elif str(row.get("养护类型")) == plan_type and row.get("status") == "已批复":
            gap = (start - other_end).days if start > other_end else (other_start - end).days
            if gap < interval:
                problems.append(
                    f"与养护计划 {other_no}（{_span(row)}）的间隔 {gap} 天 "
                    f"小于编排规则要求的 {interval} 天"
                )
    return _dedup(problems)


def _dedup(problems: list[str]) -> list[str]:
    seen: set[str] = set()
    return [item for item in problems if not (item in seen or seen.add(item))]


def reevaluate_all() -> list[dict[str, Any]]:
    """规则调整后重判全部未作废计划，不合规的打上标记并返回清单。"""
    violations: list[dict[str, Any]] = []
    for row in store.rows(MODULE):
        if row.get("status") == CLOSED_STATUS:
            continue
        problems = evaluate_plan(row, exclude_id=int(row.get("id", 0)), check_lead=False)
        if problems:
            row["abnormal"] = True
            row["合规提示"] = "；".join(problems)
            violations.append({
                "id": row.get("id"),
                "计划编号": row.get("计划编号"),
                "原因": row["合规提示"],
            })
        else:
            row["abnormal"] = False
            row["合规提示"] = ""
    return violations


class PlanService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("计划编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(
        self, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[str], dict[str, Any] | None]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, [f"缺少必填字段：{'、'.join(missing)}"], None
        problems = evaluate_plan(values)
        if problems:
            conflict = find_duplicate(str(values.get("计划编号") or "").strip())
            return None, problems, conflict
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in EDITABLE_FIELDS:
            if field in values:
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["合规提示"] = ""
        rows.append(entry)
        return entry, [], None

    def update_entry(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[str], dict[str, Any] | None]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, [f"养护计划 {entry_id} 不存在或已归档"], None
        merged = {**entry, **{field: values[field] for field in EDITABLE_FIELDS if field in values}}
        missing = [field for field in REQUIRED_FIELDS if not str(merged.get(field) or "").strip()]
        if missing:
            return None, [f"缺少必填字段：{'、'.join(missing)}"], None
        problems = evaluate_plan(merged, exclude_id=entry_id)
        if problems:
            conflict = find_duplicate(str(merged.get("计划编号") or "").strip(), exclude_id=entry_id)
            return None, problems, conflict
        for field in EDITABLE_FIELDS:
            if field in values:
                entry[field] = values[field]
        entry["abnormal"] = False
        entry["合规提示"] = ""
        return entry, [], None

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"养护计划 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于养护计划可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        if action in NEGATIVE_ACTIONS:
            entry["合规提示"] = ""
        return entry, f"养护计划已{action}"
