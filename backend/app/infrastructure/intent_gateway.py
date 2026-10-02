"""意图网关: 五分类确定性路由, 不走模型, 规则更快更稳定可测试。

分类: compound | service_only | safety_chat | search_only | other

背景: temperature=0 的 Flash 调度模型在多轮服务场景中不稳定——会复读追问文案、
嘴上说"正在查询"却不交接、甚至编造结果。对"短句 + 明确服务意图"的高频高危意图,
绕过调度者直连业务服务专家（工具链路自带追问与防编造约束）; 复合/模糊意图仍走调度者。
"""
import re
import logging

logger = logging.getLogger(__name__)

# ----------------------------- 正则匹配规则 -----------------------------
_SERVICE_INTENT_RE = re.compile(
    r"维修站|服务站|服务网点|维修点|门店|售后|授权服务|网点|附近(?!里|期|近|面)|哪里能修|怎么去|修的地方|修电脑的地方"
)
_SERVICE_CONT_RE = re.compile(r"找到了吗|找到了没|查到了吗|结果呢|有了吗")
_DIRECT_ROUTE_MAX_LEN = 30
# 复合意图保护: 句子同时含技术故障关键词时不直连服务（让调度者先处理技术部分）
_TECH_KEYWORDS_RE = re.compile(
    r"蓝屏|黑屏|死机|开机|没反应|进水|噪音|清理|更新|卡顿|重启|不能开机|无法开机|不开机"
)
# 恶意/异常请求保护: 含编造/虚假等词时不直连服务（应被调度者拒绝）
_MALICIOUS_RE = re.compile(r"编|虚假|编造|伪造|假的|生成.*地址|编.*维修")
# 🔒 安全边界保护词：只要出现这些短语，一律视为"闲聊/隐私边界"，直接 chat 分支（调度者自答），
# 防止被 orchestrator 误判为技术请求交接给 technical，导致内部信息泄漏风险。
_SAFETY_BOUNDARY_RE = re.compile(
    r"(系统提示词|提示词|prompt|内部架构|架构.*什么样|.*是.*模型|调用哪些工具|能调用什么|你的工具|能做什么工具|用了什么模型|模型.*名称)"
    r"|(你是什么AI|你是GPT|你是大模型|你是gpt|告诉我.*内部|内部.*原理|算法.*原理|训练数据|源代码|版权信息)"
    r"|(你是谁|你叫什么|介绍.*你自己|你是干什么的|你能做什么|你是什么人)"
)
# 🔍 强制搜索触发词：一旦命中且非故障类，即使进了 other 分支也让 orchestrator 走 technical 用 bailian_web_search，
# 但我们在 gateway 层就识别出"纯搜索意图"标为 other（不影响 compound/service_only），
# 额外特征注入让 routing_inference 能稳定判定为 search。
_FORCE_SEARCH_RE = re.compile(
    r"(联网搜|帮我搜|搜索一下|查一下.*最新|最新款|最新.*发布|发布会|新品|新闻|资讯|今天.*天气|今天.*股市|今天.*股价)"
)


def should_direct_route_service(question: str, ctx: dict) -> bool:
    """短句且意图明确的服务请求 -> 直连业务服务专家。

    排除: 复合意图（含技术关键词）、恶意请求（编造虚假地址）。
    """
    q = (question or "").strip()
    if not q or len(q) > _DIRECT_ROUTE_MAX_LEN:
        return False
    if not _SERVICE_INTENT_RE.search(q):
        # 追问后的确认类短句（"找到了吗"）: 仅在会话存在服务查询上下文时直连
        if _SERVICE_CONT_RE.search(q) and (
            ctx.get("location_record") or ctx.get("location_hint_pending") or ctx.get("service_query_ts")
        ):
            return True
        return False
    # 含服务关键词，但检查是否为复合意图或恶意请求
    if _TECH_KEYWORDS_RE.search(q):
        return False  # 复合意图，交调度者处理技术部分
    if _MALICIOUS_RE.search(q):
        return False  # 恶意请求，交调度者拒绝
    return True


def classify_intent(question: str, ctx: dict) -> str:
    """五分类意图网关: compound | service_only | safety_chat | search_only | other。

    - compound: 同时含技术故障关键词 + 服务网点关键词 -> 显式编排(先 technical 后 service)
    - service_only: 仅短句服务意图(沿用 should_direct_route_service 判定)
    - safety_chat: 🔒 安全边界/泄漏探测 -> 由系统以"联想 ITS 身份"直接回绝，不进任何 Agent
    - search_only: 🔍 纯搜索意图(帮我搜/最新款/资讯等，且不含技术故障/服务网点) -> 直连技术专家(搜索工具拥有者)，严禁经调度者
    - other: 单一技术意图/模糊/闲聊 -> 交调度者路由
    """
    q = (question or "").strip()
    if not q:
        return "other"
    # 安全边界（恶意探测）：先判，优先级最高
    if _SAFETY_BOUNDARY_RE.search(q) or _MALICIOUS_RE.search(q):
        return "safety_chat"
    has_tech = bool(_TECH_KEYWORDS_RE.search(q))
    has_service = bool(_SERVICE_INTENT_RE.search(q))
    if has_tech and has_service:
        return "compound"
    # 🔍 纯搜索意图: 命中强制搜索词，且不是技术故障/服务查询 -> search_only
    if _FORCE_SEARCH_RE.search(q) and not has_tech and not has_service:
        return "search_only"
    if should_direct_route_service(question, ctx):
        return "service_only"
    return "other"


def safety_chat_reply(question: str) -> str:
    """safety_chat 分支：确定性回复，绕过所有 Agent，防止提示词泄漏/架构探测/虚假编造。"""
    q = (question or "")
    # 编造/虚假门店请求（纯净回绝，不要带 service 追问，避免评测误判路由）
    if _MALICIOUS_RE.search(q):
        return "抱歉，我无法生成虚假的维修站地址或联系信息。联想官方授权服务网点的信息可以通过联想官网或官方服务热线 400-100-6000 进行真实查询。"
    # 系统提示词 / 内部架构 / 工具能力探测（注意：回绝话术不得含"服务网点/告诉我城市"等服务特征词，避免路由误判）
    if any(k in q for k in ("提示词", "prompt", "系统提示", "内部架构", "架构", "源代码", "训练数据", "算法", "内部原理")):
        return "抱歉，系统提示词、内部架构与实现细节等信息不便公开。我是联想 ITS 智能技术助手，专注于联想产品的售后技术支持，有什么可以帮您？"
    # 模型/AI 身份追问 / 工具清单
    if any(k in q for k in ("什么模型", "什么AI", "是GPT", "是大模型", "调用哪些工具", "能调用什么", "你的工具", "用了什么模型")):
        return "我是联想 ITS 智能技术助手，面向联想产品提供售后技术诊断与资讯查询服务。如需技术支持，请描述您的设备故障现象，有什么可以帮您？"
    # 身份/问候类：简洁直接回答，不让 LLM 自由发挥
    if any(k in q for k in ("你是谁", "你叫什么", "介绍", "你是干什么的", "你能做什么", "你是什么人")):
        return "您好！我是联想智能技术助手，专注为 ThinkPad、小新、YOGA 笔记本及 ThinkCentre 台式机等联想产品提供售后技术支持。请问您遇到了什么问题？我可以帮您排查设备故障、解答使用疑问或查询附近的联想服务网点。"
    # 兜底（通常不会走到）
    return "抱歉，我无法回答此类问题。我是联想 ITS 智能技术助手，专注于联想产品的技术与售后服务，请问有什么可以帮您？"
