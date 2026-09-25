"""养护计划接口：台账查询、登记/修改、编排规则配置与状态流转。

编排规则（间隔、提前量、在途、撞档）全部由 PlanService 判定，路由层只负责
把违规明细和“与哪一条计划冲突”原样回给前端，台账导出与打印入口保持不变。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult, RuleResult
from app.services.plan import PlanService

router = APIRouter(prefix="/api/plan", tags=["养护计划"])

service = PlanService()

LIST_FIELDS = ["计划编号", "养护类型", "养护对象", "计划工期", "预算金额", "编制人员", "审批人员", "计划状态"]
STATUSES = ["待编制", "待审批", "已批复", "已作废"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按计划编号检索"),
    status: str | None = Query(default=None, description="待编制、待审批、已批复、已作废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按计划编号与状态过滤养护计划台账；每条都带当前规则下的合规标记。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/rules", response_model=list[dict])
def list_rules() -> list[dict[str, Any]]:
    """读取各养护类型的编排规则（最小间隔天数、提前量天数）。"""
    return service.list_rules()


@router.get("/objects", response_model=list[dict])
def list_objects(
    keyword: str | None = Query(default=None, description="按编码或名称过滤养护对象候选"),
) -> list[dict[str, Any]]:
    """养护对象候选：来自道路、桥梁、隧道台账。"""
    return service.list_objects(keyword)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出养护计划台账清单：返回全量数据，供打印与归档照常使用。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "plan", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条养护计划明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"养护计划 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条养护计划；间隔未到、已有在途、排期撞档或数据有误时一律不保存，
    并逐条例明原因与冲突计划。"""
    entry, violations = service.create_entry(payload.values)
    if violations:
        return ActionResult(ok=False, message="养护计划未通过编排规则校验，未保存", violations=violations)
    return ActionResult(ok=True, message="养护计划已登记", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """修改养护计划后按同一套编排规则重新校验，不通过则原样保留数据、说明原因。"""
    entry, violations = service.update_entry(entry_id, payload.values)
    if violations:
        if entry is None and violations and violations[0].get("code") == "养护计划不存在":
            return ActionResult(ok=False, message=violations[0]["message"], violations=violations)
        return ActionResult(ok=False, message="修改未通过编排规则校验，未保存", violations=violations)
    return ActionResult(ok=True, message="养护计划已修改", entry=entry)


@router.post("/rules", response_model=RuleResult)
def save_rule(payload: EntryPayload) -> RuleResult:
    """调整某养护类型的间隔与提前量；保存后已编好的计划按新规则全部重判，
    返回不合规的那几条。"""
    rule, recheck_message = service.save_rule(payload.values)
    if rule is None:
        return RuleResult(ok=False, message=recheck_message or "规则参数不合法")
    flagged = [row for row in service.list_entries(page=1, size=10000)[0] if not row.get("合规", True)]
    return RuleResult(
        ok=True,
        message=f"养护类型「{rule.get('养护类型')}」的编排规则已保存",
        rule=rule,
        recheck_message=recheck_message,
        flagged=flagged,
    )


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条养护计划执行提交审批、确认批复、作废计划；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
