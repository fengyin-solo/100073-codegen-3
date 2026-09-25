"""养护计划编排规则接口：按养护类型维护间隔与提前量，规则变更后自动重判已编计划。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.planrule import PlanRuleService

router = APIRouter(prefix="/api/planrule", tags=["编排规则"])

service = PlanRuleService()


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按养护类型检索"),
    status: str | None = Query(default=None, description="启用、停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按养护类型与启用状态过滤编排规则列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出编排规则清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "planrule", "total": total, "items": items}


@router.post("/reevaluate", response_model=ActionResult)
def reevaluate_entries() -> ActionResult:
    """按当前启用规则重新判定全部已编计划，不合规的会在计划台账里标出来。"""
    return ActionResult(ok=True, message=service.reevaluate())


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条编排规则明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"编排规则 {entry_id} 不存在")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条编排规则；保存成功后已编计划会按新规则重新判定。"""
    entry, problems, reevaluate_message = service.create_entry(payload.values)
    if problems:
        return ActionResult(ok=False, message="；".join(problems))
    return ActionResult(ok=True, message=f"编排规则已登记；{reevaluate_message}", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """修改一条编排规则；保存成功后已编计划会按新规则重新判定。"""
    entry, problems, reevaluate_message = service.update_entry(entry_id, payload.values)
    if problems:
        return ActionResult(ok=False, message="；".join(problems))
    return ActionResult(ok=True, message=f"编排规则已保存；{reevaluate_message}", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条编排规则执行启用规则、停用规则；状态变化后同样触发全量重判。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
