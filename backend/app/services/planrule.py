"""养护计划编排规则：按养护类型配置间隔与提前量。

规则保存或启停后，会调用 plan 模块的 reevaluate_all 把已编计划按新规则
重新判定一遍，不合规的计划会被打上标记并随响应返回清单。
"""
from __future__ import annotations

from typing import Any

from app.services import plan as plan_service
from app.store import store

MODULE = "planrule"
REQUIRED_FIELDS = ["规则编号", "养护类型", "间隔天数", "提前天数"]
EDITABLE_FIELDS = ["规则编号", "养护类型", "间隔天数", "提前天数", "适用对象", "生效日期", "编制人员", "规则状态"]
STATUS_ORDER = ["启用", "停用"]
ACTION_RULES = {"启用规则": "启用", "停用规则": "停用"}


def _to_int(raw: Any) -> int | None:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _reevaluate_message() -> str:
    violations = plan_service.reevaluate_all()
    if not violations:
        return "已按新规则重新判定，全部已编计划均合规"
    numbers = "、".join(str(item["计划编号"]) for item in violations)
    return f"已按新规则重新判定，{len(violations)} 条计划不合规：{numbers}"


class PlanRuleService:
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
            rows = [row for row in rows if keyword in str(row.get("养护类型", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def _validate(
        self, values: dict[str, Any], exclude_id: int | None = None
    ) -> tuple[list[str], dict[str, Any]]:
        problems: list[str] = []
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field, "") or "").strip()]
        if missing:
            problems.append(f"缺少必填字段：{'、'.join(missing)}")
            return problems, {}
        rule_no = str(values.get("规则编号") or "").strip()
        for row in store.rows(MODULE):
            if exclude_id is not None and int(row.get("id", 0)) == exclude_id:
                continue
            if str(row.get("规则编号")) == rule_no:
                problems.append(f"规则编号 {rule_no} 与已有编排规则（id={row.get('id')}）重复，请更换编号")
                break
        for field in ("间隔天数", "提前天数"):
            number = _to_int(values.get(field))
            if number is None or number < 0:
                problems.append(f"{field}应为不小于 0 的整数")
        plan_type = str(values.get("养护类型") or "").strip()
        for row in store.rows(MODULE):
            if exclude_id is not None and int(row.get("id", 0)) == exclude_id:
                continue
            if row.get("养护类型") == plan_type and row.get("status") == "启用":
                problems.append(
                    f"养护类型「{plan_type}」已有启用中的编排规则 {row.get('规则编号')}，"
                    "请先停用或修改那条规则"
                )
                break
        cleaned = {
            field: (_to_int(values.get(field)) if field in ("间隔天数", "提前天数") else values.get(field))
            for field in EDITABLE_FIELDS
            if field in values
        }
        return problems, cleaned

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], str]:
        problems, cleaned = self._validate(values)
        if problems:
            return None, problems, ""
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update(cleaned)
        entry["status"] = "启用"
        entry["规则状态"] = "启用"
        entry["pending"] = False
        entry["abnormal"] = False
        rows.append(entry)
        return entry, [], _reevaluate_message()

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, [f"编排规则 {entry_id} 不存在"], ""
        merged = {**entry, **values}
        problems, cleaned = self._validate(merged, exclude_id=entry_id)
        if problems:
            return None, problems, ""
        for field, value in cleaned.items():
            entry[field] = value
        return entry, [], _reevaluate_message()

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"编排规则 {entry_id} 不存在"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于编排规则可执行范围"
        target = ACTION_RULES[action]
        if target == "启用":
            for row in store.rows(MODULE):
                if (
                    int(row.get("id", 0)) != entry_id
                    and row.get("养护类型") == entry.get("养护类型")
                    and row.get("status") == "启用"
                ):
                    return None, (
                        f"养护类型「{entry.get('养护类型')}」已有启用中的编排规则 "
                        f"{row.get('规则编号')}，请先停用那条规则"
                    )
        entry["status"] = target
        entry["规则状态"] = target
        return entry, f"编排规则已{action}；{_reevaluate_message()}"

    def reevaluate(self) -> str:
        """手动触发一次全量重判，供计划台账页的「按规则重新判定」按钮使用。"""
        return _reevaluate_message()
