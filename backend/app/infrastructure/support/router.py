"""
人工工单与消息反馈 API（业务闭环）

- POST   /support/tickets            创建人工工单（转人工/投诉/在线未解决）
- GET    /support/tickets            查看本人工单列表
- GET    /support/tickets/{id}       查看本人工单详情
- POST   /support/tickets/{id}/cancel 取消本人工单
- POST   /support/feedback           对某轮助手消息点赞/点踩（幂等：重复提交即更新）
- GET    /support/feedback           查看本人反馈历史
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from common.infrastructure.auth.deps import get_current_user
from common.infrastructure.limiter import limiter
from infrastructure.database.support_repository import (
    TicketRepo, FeedbackRepo, TICKET_STATUS, FEEDBACK_RATING,
)

router = APIRouter(prefix="/support", tags=["support"])

_TICKET_CATEGORIES = ["技术问题", "服务投诉", "维修进度", "保修政策", "其他"]
_FEEDBACK_REASONS = {
    "up": ["回答准确", "步骤清晰", "解决了问题"],
    "down": ["回答不准确", "没解决问题", "内容过时", "答非所问"],
}


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------
class TicketCreate(BaseModel):
    content: str = Field(min_length=2, max_length=2000, description="问题描述")
    session_id: str = Field(default="", max_length=64)
    category: str = Field(default="技术问题", max_length=50)
    contact: str = Field(default="", max_length=100, description="联系方式（可选）")


class FeedbackCreate(BaseModel):
    session_id: str = Field(max_length=64)
    turn_index: int = Field(ge=0, description="助手消息轮次序号（从 0 开始）")
    rating: str = Field(description="up=点赞 / down=点踩")
    reason: str = Field(default="", max_length=255)
    comment: str = Field(default="", max_length=1000)


class StatusUpdate(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# 工单
# ---------------------------------------------------------------------------
@router.post("/tickets")
@limiter.limit("5/minute")
def create_ticket(request: Request, ticket_in: TicketCreate,
                  current_user: dict = Depends(get_current_user)):
    category = ticket_in.category if ticket_in.category in _TICKET_CATEGORIES else "技术问题"
    ticket_id = TicketRepo.create(
        user_id=current_user["id"],
        username=current_user["username"],
        session_id=ticket_in.session_id,
        category=category,
        content=ticket_in.content,
        contact=ticket_in.contact,
    )
    return {"id": ticket_id, "status": "open",
            "message": "工单已创建，客服人员将尽快与您联系。"}


@router.get("/tickets")
def list_tickets(request: Request, current_user: dict = Depends(get_current_user)):
    return TicketRepo.list_by_user(current_user["id"])


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int, current_user: dict = Depends(get_current_user)):
    ticket = TicketRepo.get_for_user(ticket_id, current_user["id"])
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")
    return ticket


@router.post("/tickets/{ticket_id}/cancel")
@limiter.limit("10/minute")
def cancel_ticket(request: Request, ticket_id: int,
                  current_user: dict = Depends(get_current_user)):
    affected = TicketRepo.update_status(ticket_id, current_user["id"], "cancelled")
    if not affected:
        raise HTTPException(status_code=404, detail="工单不存在或状态未变化")
    return {"id": ticket_id, "status": "cancelled"}


# ---------------------------------------------------------------------------
# 反馈
# ---------------------------------------------------------------------------
@router.post("/feedback")
@limiter.limit("20/minute")
def submit_feedback(request: Request, feedback_in: FeedbackCreate,
                    current_user: dict = Depends(get_current_user)):
    if feedback_in.rating not in FEEDBACK_RATING:
        raise HTTPException(status_code=422, detail="rating 仅支持 up/down")
    allowed_reasons = _FEEDBACK_REASONS[feedback_in.rating]
    reason = feedback_in.reason if feedback_in.reason in allowed_reasons else ""
    result = FeedbackRepo.upsert(
        user_id=current_user["id"],
        username=current_user["username"],
        session_id=feedback_in.session_id,
        turn_index=feedback_in.turn_index,
        rating=feedback_in.rating,
        reason=reason,
        comment=feedback_in.comment,
    )
    return {"message": "感谢您的反馈！" if feedback_in.rating == "up" else "已收到您的反馈，我们会持续改进。",
            **result}


@router.get("/feedback")
def list_feedback(request: Request, current_user: dict = Depends(get_current_user)):
    return FeedbackRepo.list_by_user(current_user["id"])
