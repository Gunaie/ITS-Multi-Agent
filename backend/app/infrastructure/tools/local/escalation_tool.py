"""
转人工工单工具 — 供业务服务专家在对话中调用

触发场景:
1. 用户明确要求转人工 / 找客服 / 投诉；
2. 用户问题经排查确认无法在线解决（如疑似主板/屏幕硬件故障且用户拒绝送修指引，
   或多次沟通仍未解决）。
工具内部直接落库 support_tickets，并向用户返回工单编号与后续跟进说明。
"""
from agents import function_tool, RunContextWrapper

from common.infrastructure.logging.logger import logger
from infrastructure.database.support_repository import TicketRepo

_CATEGORIES = {"技术问题": "技术问题", "投诉": "服务投诉", "服务投诉": "服务投诉",
               "维修进度": "维修进度", "保修": "保修政策", "保修政策": "保修政策",
               "其他": "其他"}


@function_tool
async def request_human_support(
    ctx: RunContextWrapper,
    issue_summary: str,
    category: str = "技术问题",
    contact: str = "",
) -> str:
    """
    为用户创建人工支持工单（转人工/投诉）。仅在用户明确要求人工服务、
    发起投诉，或问题确认无法在线解决时调用；普通故障排查不要调用本工具。

    Args:
        issue_summary: 用户问题/诉求的简要概括（一句话，包含设备型号与核心诉求）。
        category: 工单类别，可选 "技术问题"/"投诉"/"维修进度"/"保修政策"/"其他"。
        contact: 用户主动留下的联系方式（电话/邮箱）；用户未提供则留空，不要编造。
    """
    try:
        session = getattr(ctx, "context", None)
        ctx_dict = {}
        session_id = ""
        if session is not None:
            session_id = getattr(session, "session_id", "") or ""
            raw = getattr(session, "context", None)
            if isinstance(raw, dict):
                ctx_dict = raw
        user = ctx_dict.get("current_user")
        if not isinstance(user, dict) or not user.get("id"):
            # 未取到登录态时不应发生（接口强制鉴权）；给出可解释的降级回复
            logger.error("request_human_support: missing current_user in session context")
            return "转人工失败：登录状态已失效，请刷新页面重新登录后再试。"

        ticket_id = TicketRepo.create(
            user_id=user["id"],
            username=user.get("username") or "",
            session_id=session_id,
            category=_CATEGORIES.get(category, "技术问题"),
            content=issue_summary,
            contact=contact,
        )
        logger.info(f"Created human-support ticket #{ticket_id} for user {user.get('username')}")
        return (
            f"已为您创建人工支持工单（编号：#{ticket_id}）。"
            "客服人员将尽快通过系统消息或您预留的联系方式与您联系，"
            "请保持联系方式畅通。您也可以在本会话中随时向我补充问题细节。"
        )
    except Exception as e:
        logger.error(f"request_human_support failed: {e}", exc_info=True)
        return (
            "很抱歉，创建人工工单时服务暂时不可用。"
            "请稍后重试，或直接拨打联想官方客服热线 400-100-6000 联系人工客服。"
        )
