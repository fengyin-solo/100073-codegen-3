"""养护计划编排规则：类型规则配置、保存前校验与规则调整后的存量重判。

判定口径集中收在这里，路由层不做业务判断：

- 间隔：同一养护对象、同一养护类型，相邻两条未作废计划的开工日期至少相隔
  「最小间隔天数」；间隔为 0 表示该类型不做间隔限制。
- 提前量：开工日期距当前日期不足「提前量天数」时判为不合规（已开工的计划不追溯）。
- 在途：同一养护对象、同一养护类型已有未作废且未完工的计划时，不允许再排同类型计划。
- 撞档：同一养护对象的两条计划工期（开工日期~完工日期）重叠时，后开工的一条判为不合规。
- 数据：养护对象必须能在道路/桥梁/隧道台账里按编码或名称找到；计划编号不允许重复。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.store import store

MODULE = "plan"
RULE_MODULE = "plan_rule"
REQUIRED_FIELDS = ["计划编号", "养护类型", "养护对象", "开工日期"]
OPTIONAL_FIELDS = ["完工日期", "预算金额", "编制人员", "审批人员"]
STATUS_ORDER = ["待编制", "待审批", "已批复", "已作废"]
ACTION_RULES = {"提交审批": "待审批", "确认批复": "已批复", "作废计划": "已作废"}
NEGATIVE_ACTIONS = ["作废计划"]

# 违规编码：前端用它定位要高亮的字段和冲突计划
CODE_MISSING = "缺少必填字段"
CODE_DUPLICATE_NO = "计划编号重复"
CODE_OBJECT_NOT_FOUND = "养护对象不存在"
CODE_DATE_INVALID = "开工日期格式不正确"
CODE_END_BEFORE_START = "完工日期早于开工日期"
CODE_INTERVAL = "间隔未到"
CODE_LEAD = "提前量不足"
CODE_IN_FLIGHT = "已有在途养护计划"
CODE_OVERLAP = "排期撞档"

# 设施台账里可作为养护对象的模块与其名称字段
OBJECT_SOURCES = [
    ("road", "设施编码", "道路名称"),
    ("bridge", "桥梁编码", "桥梁名称"),
    ("tunnel", "隧道编码", "隧道名称"),
]


def today() -> date:
    return date.today()


def parse_date(value: Any) -> date | None:
    """把 2026-09-01 / 2026/9/1 这类写法解析成日期；解析不了就返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


class PlanService:
    # ------------------------------------------------------------------ 查询
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        # 每次读台账都按当前规则重算一遍合规标记，保证规则调整后立刻反映到列表里
        self.recheck_all(persist=False)
        rows = [row for row in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("计划编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def list_objects(self, keyword: str | None = None) -> list[dict[str, Any]]:
        """汇总道路/桥梁/隧道台账，给登记入口做养护对象候选与存在性校验。"""
        objects: list[dict[str, Any]] = []
        for module, code_field, name_field in OBJECT_SOURCES:
            kind = {"road": "道路", "bridge": "桥梁", "tunnel": "隧道"}[module]
            for row in store.rows(module):
                objects.append({
                    "对象分类": kind,
                    "对象编码": row.get(code_field, ""),
                    "对象名称": row.get(name_field, ""),
                })
        if keyword:
            objects = [
                item
                for item in objects
                if keyword in str(item["对象编码"]) or keyword in str(item["对象名称"])
            ]
        return objects

    # ------------------------------------------------------------ 类型规则
    def list_rules(self) -> list[dict[str, Any]]:
        return store.rows(RULE_MODULE)

    def find_rule(self, plan_type: str) -> dict[str, Any] | None:
        plan_type = str(plan_type or "").strip()
        for rule in store.rows(RULE_MODULE):
            if str(rule.get("养护类型", "")).strip() == plan_type:
                return rule
        return None

    def save_rule(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        """新增或调整某类养护的间隔与提前量；保存后存量计划按新规则全部重判。"""
        plan_type = str(values.get("养护类型") or "").strip()
        if not plan_type:
            return None, "养护类型不能为空"
        interval = self._to_int(values.get("最小间隔天数"))
        lead = self._to_int(values.get("提前量天数"))
        if interval is None or interval < 0:
            return None, "最小间隔天数必须是不小于 0 的整数（0 表示不限制间隔）"
        if lead is None or lead < 0:
            return None, "提前量天数必须是不小于 0 的整数"
        rows = store.rows(RULE_MODULE)
        rule = next((item for item in rows if str(item.get("养护类型", "")).strip() == plan_type), None)
        if rule is None:
            rule = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            rows.append(rule)
        rule["养护类型"] = plan_type
        rule["最小间隔天数"] = interval
        rule["提前量天数"] = lead
        summary = self.recheck_all(persist=True)
        return rule, summary

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    # -------------------------------------------------------- 保存前校验
    def validate_save(
        self,
        values: dict[str, Any],
        *,
        exclude_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """保存（新增/修改）前跑完全部拦截项，返回违规明细；空列表表示放行。"""
        violations: list[dict[str, Any]] = []

        missing = [
            field
            for field in REQUIRED_FIELDS
            if not str(values.get(field) or "").strip()
        ]
        if missing:
            violations.append(self._violation(CODE_MISSING, f"缺少必填字段：{'、'.join(missing)}", fields=missing))
            # 关键字段都不齐，后面的判定没有意义
            return violations

        plan_no = str(values.get("计划编号")).strip()
        plan_type = str(values.get("养护类型")).strip()
        target = str(values.get("养护对象")).strip()
        start = parse_date(values.get("开工日期"))
        end = parse_date(values.get("完工日期"))
        if start is None:
            violations.append(self._violation(
                CODE_DATE_INVALID,
                f"开工日期「{values.get('开工日期')}」无法识别，请按 2026-09-01 格式填写",
                fields=["开工日期"],
            ))
            return violations
        if end is not None and end < start:
            violations.append(self._violation(
                CODE_END_BEFORE_START,
                "完工日期不能早于开工日期，请调整排期",
                fields=["完工日期"],
            ))
            return violations

        rows = [row for row in store.rows(MODULE) if int(row.get("id", 0)) != (exclude_id or -1)]

        # 计划编号重复：指出与哪一条撞了，并给出修改入口
        dup = next((row for row in rows if str(row.get("计划编号", "")).strip() == plan_no), None)
        if dup is not None:
            violations.append(self._violation(
                CODE_DUPLICATE_NO,
                f"计划编号 {plan_no} 已被养护计划 {dup.get('计划编号')}（序号 {dup.get('id')}）占用，请更换编号",
                fields=["计划编号"],
                conflict=dup,
            ))

        # 养护对象必须在设施台账里
        obj = self.find_object(target)
        if obj is None:
            violations.append(self._violation(
                CODE_OBJECT_NOT_FOUND,
                f"养护对象「{target}」在道路、桥梁、隧道台账中均不存在，请核对后从台账中选择",
                fields=["养护对象"],
            ))
        else:
            target = obj["对象名称"]

        active = [row for row in rows if row.get("status") != STATUS_ORDER[-1]]

        # 间隔与提前量：规则按养护类型配置，间隔锚定同对象同类型更早的最近一条。
        # 已有同类型在途计划时由在途规则统一拦截，不再重复报间隔，避免一个坑报两条。
        rule = self.find_rule(plan_type)
        if rule is not None:
            interval = int(rule.get("最小间隔天数", 0))
            flight = self._find_in_flight(active, target, plan_type)
            if interval > 0 and flight is None:
                anchor = self._interval_anchor(active, target, plan_type, start)
                if anchor is not None:
                    anchor_start = parse_date(anchor.get("开工日期"))
                    if anchor_start is not None:
                        gap = (start - anchor_start).days
                        if gap < interval:
                            violations.append(self._violation(
                                CODE_INTERVAL,
                                f"距上一条同类型养护计划 {anchor.get('计划编号')}（开工 {anchor.get('开工日期')}）"
                                f"仅 {gap} 天，未达到「{plan_type}」最小间隔 {interval} 天的要求",
                                fields=["开工日期", "养护类型"],
                                conflict=anchor,
                            ))
            # 提前量只看计划自身排期（不依赖锚点），已开工的历史计划不追溯
            lead = int(rule.get("提前量天数", 0))
            if lead > 0 and start >= today():
                ahead = (start - today()).days
                if ahead < lead:
                    violations.append(self._violation(
                        CODE_LEAD,
                        f"开工日期 {start} 距今天仅剩 {ahead} 天，不足「{plan_type}」要求的"
                        f"提前量 {lead} 天，请改期或提前编制",
                        fields=["开工日期", "养护类型"],
                    ))

        # 在途：同对象同类型已有未作废且未完工的计划
        flight = self._find_in_flight(active, target, plan_type)
        if flight is not None:
            violations.append(self._violation(
                CODE_IN_FLIGHT,
                f"养护对象「{target}」已有在途的同类型养护计划 {flight.get('计划编号')}"
                f"（状态：{flight.get('status')}，工期：{self._period_text(flight)}），需先完成或作废后再编排",
                fields=["养护对象", "养护类型"],
                conflict=flight,
            ))

        # 撞档：与同一养护对象的在途计划工期重叠（类型不限）
        clash = self._find_overlap(active, target, start, end)
        if clash is not None:
            violations.append(self._violation(
                CODE_OVERLAP,
                f"排期 {start}~{self._end_text(end, start)} 与养护计划 {clash.get('计划编号')}"
                f"（工期：{self._period_text(clash)}）落在同一时间段",
                fields=["开工日期", "完工日期"],
                conflict=clash,
            ))

        return violations

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        values = self._canonical_object(values)
        violations = self.validate_save(values)
        if violations:
            return None, violations
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update(self._persist_fields(values))
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        self.recheck_all(persist=False)
        return entry, []

    def update_entry(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, [self._violation("养护计划不存在", f"养护计划 {entry_id} 不存在或已归档")]
        values = self._canonical_object(values)
        merged = {**entry, **{key: values[key] for key in values if values.get(key) is not None}}
        violations = self.validate_save(merged, exclude_id=entry_id)
        if violations:
            return None, violations
        entry.update(self._persist_fields(merged))
        self.recheck_all(persist=False)
        return entry, []

    def _canonical_object(self, values: dict[str, Any]) -> dict[str, Any]:
        """养护对象按编码或名称都能识别，落库统一成台账名称，保证同对象判定口径一致。"""
        if "养护对象" not in values:
            return values
        obj = self.find_object(values.get("养护对象"))
        if obj is not None:
            return {**values, "养护对象": obj["对象名称"]}
        return values

    # -------------------------------------------------------- 规则调整后重判
    def recheck_all(self, *, persist: bool = True) -> str:
        """按当前规则对全部已编好的计划重新判定，标出不合规的那几条。

        保存（validate_save）拦的是“再排一条”的场景；重判要处理存量台账里
        历史遗留的撞档/编号重复/对象缺失，因此违规落在每一对里后开工（同则 id 大）
        的一条上，避免两条互相标、也保证标出来的正好是需要调整的那几条。
        """
        rows = store.rows(MODULE)
        for row in rows:
            row["违规项"] = []

        seen_no: dict[str, dict[str, Any]] = {}
        for row in rows:
            plan_no = str(row.get("计划编号", "")).strip()
            if plan_no:
                if plan_no in seen_no:
                    first = seen_no[plan_no]
                    self._add_violation(row, self._violation(
                        CODE_DUPLICATE_NO,
                        f"计划编号 {plan_no} 与养护计划（序号 {first.get('id')}）重复",
                        fields=["计划编号"],
                        conflict=first,
                    ))
                else:
                    seen_no[plan_no] = row
            if str(row.get("养护对象") or "").strip() and self.find_object(row["养护对象"]) is None:
                self._add_violation(row, self._violation(
                    CODE_OBJECT_NOT_FOUND,
                    f"养护对象「{row.get('养护对象')}」在道路、桥梁、隧道台账中不存在",
                    fields=["养护对象"],
                ))

        active = [row for row in rows if row.get("status") != STATUS_ORDER[-1]]

        # 撞档：同对象两两比较，后开工的一条担责；缺开工日期的排到最后不参与担责
        def sort_key(row: dict[str, Any]) -> tuple[date, int]:
            parsed = parse_date(row.get("开工日期"))
            return (parsed or date.max, int(row.get("id", 0)))

        ordered = sorted(active, key=sort_key)
        for i, later in enumerate(ordered):
            later_start = parse_date(later.get("开工日期"))
            if later_start is None:
                continue
            later_end = parse_date(later.get("完工日期")) or later_start
            for earlier in ordered[:i]:
                if str(earlier.get("养护对象", "")).strip() != str(later.get("养护对象", "")).strip():
                    continue
                earlier_start = parse_date(earlier.get("开工日期"))
                if earlier_start is None:
                    continue
                earlier_end = parse_date(earlier.get("完工日期")) or earlier_start
                if later_start <= earlier_end and earlier_start <= later_end:
                    self._add_violation(later, self._violation(
                        CODE_OVERLAP,
                        f"排期与养护计划 {earlier.get('计划编号')}（工期：{self._period_text(earlier)}）重叠",
                        fields=["开工日期", "完工日期"],
                        conflict=earlier,
                    ))
                    break

        # 间隔锚定同对象同类型、开工更早的最近一条；提前量只看计划自身（尚未开工才检查）
        for row in ordered:
            start = parse_date(row.get("开工日期"))
            target = str(row.get("养护对象", "")).strip()
            plan_type = str(row.get("养护类型", "")).strip()
            if start is None or not target:
                continue
            rule = self.find_rule(plan_type)
            if rule is None:
                continue
            interval = int(rule.get("最小间隔天数", 0))
            anchor = self._interval_anchor(active, target, plan_type, start, exclude_id=int(row.get("id", 0)))
            if interval > 0 and anchor is not None:
                anchor_start = parse_date(anchor.get("开工日期"))
                if anchor_start is not None and (start - anchor_start).days < interval:
                    self._add_violation(row, self._violation(
                        CODE_INTERVAL,
                        f"距上一条同类型养护计划 {anchor.get('计划编号')}（开工 {anchor.get('开工日期')}）"
                        f"不足最小间隔 {interval} 天",
                        fields=["开工日期", "养护类型"],
                        conflict=anchor,
                    ))
            lead = int(rule.get("提前量天数", 0))
            if lead > 0 and start >= today() and (start - today()).days < lead:
                self._add_violation(row, self._violation(
                    CODE_LEAD,
                    f"开工日期 {start} 不足「{plan_type}」要求的提前量 {lead} 天",
                    fields=["开工日期", "养护类型"],
                ))

        flagged = [row for row in rows if row.get("违规项")]
        for row in rows:
            row["合规"] = not row.get("违规项")
            row["abnormal"] = bool(row.get("违规项"))
        if persist:
            pass  # 行是 store 里的引用，标记已经就地落账
        return f"已按新规则重判 {len(rows)} 条养护计划，其中 {len(flagged)} 条不合规"

    # ------------------------------------------------------------ 状态流转
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
        entry["abnormal"] = action in NEGATIVE_ACTIONS or bool(entry.get("违规项"))
        self.recheck_all(persist=False)
        return entry, f"养护计划已{action}"

    # ------------------------------------------------------------ 辅助方法
    def find_object(self, text: str) -> dict[str, Any] | None:
        text = str(text or "").strip()
        if not text:
            return None
        for item in self.list_objects():
            if text == str(item["对象编码"]) or text == str(item["对象名称"]):
                return item
        return None

    def _interval_anchor(
        self,
        rows: list[dict[str, Any]],
        target: str,
        plan_type: str,
        start: date,
        *,
        exclude_id: int | None = None,
    ) -> dict[str, Any] | None:
        """同对象同类型、开工更早（不含同一天）的最近一条计划。"""
        candidates: list[tuple[date, dict[str, Any]]] = []
        for row in rows:
            if exclude_id is not None and int(row.get("id", 0)) == exclude_id:
                continue
            if str(row.get("养护对象", "")).strip() != target:
                continue
            if str(row.get("养护类型", "")).strip() != plan_type:
                continue
            row_start = parse_date(row.get("开工日期"))
            if row_start is not None and row_start < start:
                candidates.append((row_start, row))
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]

    def _find_in_flight(
        self, rows: list[dict[str, Any]], target: str, plan_type: str
    ) -> dict[str, Any] | None:
        now = today()
        for row in rows:
            if str(row.get("养护对象", "")).strip() != target:
                continue
            if str(row.get("养护类型", "")).strip() != plan_type:
                continue
            end = parse_date(row.get("完工日期"))
            if end is not None and end < now:
                continue  # 已完工，不再算在途
            return row
        return None

    def _find_overlap(
        self,
        rows: list[dict[str, Any]],
        target: str,
        start: date,
        end: date | None,
    ) -> dict[str, Any] | None:
        end = end or start
        for row in rows:
            if str(row.get("养护对象", "")).strip() != target:
                continue
            row_start = parse_date(row.get("开工日期"))
            if row_start is None:
                continue
            row_end = parse_date(row.get("完工日期")) or row_start
            if start <= row_end and row_start <= end:
                return row
        return None

    @staticmethod
    def _violation(
        code: str,
        message: str,
        *,
        fields: list[str] | None = None,
        conflict: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        violation: dict[str, Any] = {"code": code, "message": message, "fields": fields or []}
        if conflict is not None:
            violation["冲突计划"] = {
                "id": conflict.get("id"),
                "计划编号": conflict.get("计划编号"),
                "养护类型": conflict.get("养护类型"),
                "养护对象": conflict.get("养护对象"),
                "开工日期": conflict.get("开工日期"),
                "完工日期": conflict.get("完工日期"),
                "status": conflict.get("status"),
            }
        return violation

    @staticmethod
    def _add_violation(row: dict[str, Any], violation: dict[str, Any]) -> None:
        codes = [item.get("code") for item in row.setdefault("违规项", [])]
        if violation["code"] not in codes:
            row["违规项"].append(violation)

    @staticmethod
    def _end_text(end: date | None, start: date) -> str:
        return str(end) if end is not None else f"{start}（未填完工日期）"

    def _period_text(self, row: dict[str, Any]) -> str:
        start = parse_date(row.get("开工日期"))
        end = parse_date(row.get("完工日期"))
        if start is None:
            return str(row.get("计划工期") or "日期未填")
        return f"{start}~{end or start}"

    def _persist_fields(self, values: dict[str, Any]) -> dict[str, Any]:
        data = {field: str(values.get(field) or "").strip() for field in REQUIRED_FIELDS}
        for field in OPTIONAL_FIELDS:
            value = values.get(field)
            if value is not None and str(value).strip():
                data[field] = value
        start = parse_date(data.get("开工日期"))
        end = parse_date(data.get("完工日期"))
        if start is not None:
            data["计划工期"] = f"{start}~{end or start}"
        return data
