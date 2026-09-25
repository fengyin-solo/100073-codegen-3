"""养护计划接口：维护养护计划，覆盖提交审批、确认批复、作废计划等动作。

登记与修改都会按编排规则判定：间隔没到、已有在途计划、排期落在同一时间段、
计划编号重复或养护对象不存在时一律不允许保存，并在报文里说明撞了哪条计划。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.plan import PlanService

router = APIRouter(prefix="/api/plan", tags=["养护计划"])

service = PlanService()

LIST_FIELDS = ["计划编号", "养护类型", "养护对象", "计划开始日期", "计划结束日期", "预算金额", "编制人员", "计划状态"]
STATUSES = ["待编制", "待审批", "已批复", "已作废"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按计划编号检索"),
    status: str | None = Query(default=None, description="待编制、待审批、已批复、已作废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按计划编号与状态过滤养护计划列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出养护计划清单（台账）：返回当前过滤条件下的全量数据。

    注意要注册在 /{entry_id} 之前，否则 export 会被当成计划 id 解析。
    """
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
    """登记一条养护计划；不合规时说明原因，编号重复时把已有计划一并返回便于跳转修改。"""
    entry, problems, conflict = service.create_entry(payload.values)
    if problems:
        return ActionResult(ok=False, message="；".join(problems), entry=conflict)
    return ActionResult(ok=True, message="养护计划已登记", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """修改一条养护计划；同样按编排规则判定，不合规不允许保存。"""
    entry, problems, conflict = service.update_entry(entry_id, payload.values)
    if problems:
        return ActionResult(ok=False, message="；".join(problems), entry=conflict)
    return ActionResult(ok=True, message="养护计划已保存", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条养护计划执行提交审批、确认批复、作废计划；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
