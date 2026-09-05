"""
RAG 质量评测 — 自建 LLM-as-judge，指标对齐 Ragas 框架

评测知识库 RAG 链路（检索 + 生成）的四个维度：
  1. faithfulness      忠实度   — 回答中的陈述是否都能由检索资料支撑（防幻觉）
  2. answer_relevancy  答案相关性 — 回答是否切题、完整
  3. context_precision 上下文精度 — 检索回的资料中有多少与问题相关
  4. context_recall    上下文召回 — 标准答案要点是否都被检索资料覆盖
  另加: 检索命中率（规则断言，expected_doc 是否出现在检索结果标题中）

不依赖 ragas 库（knowledge venv 的 langchain 1.6.1 与 ragas 版本约束冲突），
judge LLM 走百炼 OpenAI 兼容端点（temperature=0），默认跟随 technical 模型，
可用环境变量 RAG_EVAL_JUDGE_MODEL 覆盖。

前置条件: 知识库服务已运行（8001，且含 /query_eval 接口）。
用法:
  .venv/Scripts/python.exe backend/tests/eval_rag_quality.py
输出:
  - 控制台表格
  - docs/RAG_EVAL_REPORT.md
  - backend/tests/rag_eval_results.json
"""
import sys, os, json, asyncio, re, argparse
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "app")))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..")))

import httpx
from config.settings import settings

KB_URL = os.environ.get("KB_EVAL_URL", "http://127.0.0.1:8001")
# judge 模型可通过环境变量覆盖（默认跟随 technical 模型；当前=qwen3.8-max-0902）
# ⚠️ 该模型为思考模型：单次 judge 调用可达 1-2 分钟，超时需放宽；百炼免费额度并发上限低，
# 大并发会触发限流（ReadTimeout/挂起），评测务必低并发（条目级 ≤2）+ 失败重试。
JUDGE_MODEL = os.environ.get("RAG_EVAL_JUDGE_MODEL") or settings.TECHNICAL_MODEL_NAME or "qwen3.8-max-0902"

# =========================================================================
# 数据集：15 条，覆盖知识库 15 篇故障排查文档
# ground_truth_points 为该问题标准答案应覆盖的关键要点（语义判断，非逐字）
# expected_doc 为期望检索命中的文档标题关键词（规则断言检索命中率）
# =========================================================================
RAG_DATASET = [
    {"id": "RAG01", "question": "笔记本电脑开机黑屏怎么办",
     "ground_truth_points": ["检查电源和电池是否正常", "外接显示器判断是否屏幕问题", "强制重启或释放静电", "安全模式排查显卡驱动", "硬件故障送修"],
     "expected_doc": "黑屏"},
    {"id": "RAG02", "question": "电脑按电源键完全没反应无法开机",
     "ground_truth_points": ["检查电源适配器和供电", "长按电源键放电", "可拆卸电池取出重装", "内存重新插拔", "仍无效送修检测"],
     "expected_doc": "无法开机"},
    {"id": "RAG03", "question": "电脑蓝屏报错怎么解决",
     "ground_truth_points": ["记录蓝屏错误代码和驱动文件名", "进入安全模式", "卸载或回滚问题驱动", "系统还原或修复", "检测内存硬件"],
     "expected_doc": "蓝屏"},
    {"id": "RAG04", "question": "笔记本进水了紧急怎么处理",
     "ground_truth_points": ["立即断电强制关机", "倒置排水并擦干表面", "切勿尝试开机", "不要用吹风机热风吹", "通风晾干48小时以上或送修"],
     "expected_doc": "进水"},
    {"id": "RAG05", "question": "笔记本电池无法充电怎么回事",
     "ground_truth_points": ["检查电源适配器和连接线", "重置或更新电池驱动", "检查电源管理设置", "电池校准", "电池老化送修更换"],
     "expected_doc": "电池"},
    {"id": "RAG06", "question": "笔记本发热严重风扇声音很大",
     "ground_truth_points": ["清理散热口灰尘", "检查是否堵住通风口", "更换散热硅脂", "风扇异响可能硬件故障", "必要时送修"],
     "expected_doc": "发热"},
    {"id": "RAG07", "question": "笔记本屏幕花屏显示异常",
     "ground_truth_points": ["外接显示器判断是屏幕还是主机问题", "更新或重装显卡驱动", "检查屏幕排线", "外接正常则是屏幕硬件故障", "送修检测"],
     "expected_doc": "花屏"},
    {"id": "RAG08", "question": "如何重装Windows系统",
     "ground_truth_points": ["备份重要数据", "制作系统安装U盘", "设置BIOS启动项", "分区安装系统", "安装驱动和补丁"],
     "expected_doc": "系统重装"},
    {"id": "RAG09", "question": "电脑很卡运行缓慢怎么优化",
     "ground_truth_points": ["任务管理器查看CPU内存占用", "禁用开机启动项", "清理磁盘和临时文件", "查杀病毒恶意软件", "考虑升级内存或固态硬盘"],
     "expected_doc": "卡顿"},
    {"id": "RAG10", "question": "怎么安装和更新驱动程序",
     "ground_truth_points": ["从官网按型号下载驱动", "设备管理器更新驱动", "注意驱动版本与系统兼容", "驱动异常可回滚", "安装后重启"],
     "expected_doc": "驱动"},
    {"id": "RAG11", "question": "Windows系统更新失败怎么办",
     "ground_truth_points": ["运行Windows更新疑难解答", "清空更新缓存", "检查磁盘空间是否充足", "手动下载补丁安装", "重启后重试"],
     "expected_doc": "更新失败"},
    {"id": "RAG12", "question": "笔记本连不上WiFi无线网络",
     "ground_truth_points": ["确认WiFi开关开启和飞行模式关闭", "重启路由器测试", "检查或重装无线网卡驱动", "网络重置", "检查WLAN AutoConfig服务"],
     "expected_doc": "WiFi"},
    {"id": "RAG13", "question": "蓝牙连不上设备怎么排查",
     "ground_truth_points": ["确认蓝牙功能已开启", "移除设备后重新配对", "更新蓝牙驱动", "检查蓝牙支持服务", "硬件问题送修"],
     "expected_doc": "蓝牙"},
    {"id": "RAG14", "question": "怎么查询笔记本是否在保修期内",
     "ground_truth_points": ["保修期限说明", "凭序列号或发票查询保修", "保修范围一般为非人为损坏", "可购买延保", "人为损坏如进水不在保修范围"],
     "expected_doc": "保修"},
    {"id": "RAG15", "question": "联想官方客服电话是多少怎么联系售后",
     "ground_truth_points": ["官方客服热线", "在线支持渠道", "服务网点查询方式", "可预约维修", "准备好设备序列号"],
     "expected_doc": "客服"},

    # -------------------------------------------------------------------------
    # RAG16-RAG30 扩充（2026-09-05）：验证四层过滤对多样化问法的泛化性
    # 维度：口语化换说法 / 主题漂移陷阱(易检索到表面相近的错误文档) / 噪声长上下文 /
    #       产品类目守卫(PC域不应混入电视手机文档) / 服务类与多意图
    # -------------------------------------------------------------------------
    # --- 口语化/换说法（同主题不同表达，测检索鲁棒性） ---
    {"id": "RAG16", "question": "电脑开不了机，电源指示灯也不亮",
     "ground_truth_points": ["检查电源线插座和电源适配器是否正常", "长按电源键30秒以上释放静电", "可拆卸电池取下重新装回", "重新插拔内存条", "仍无法开机送修检测电源或主板"],
     "expected_doc": "无法开机"},
    {"id": "RAG17", "question": "笔记本摔了一下屏幕出现竖条纹显示不正常",
     "ground_truth_points": ["外接显示器判断是屏幕还是显卡问题", "摔落可能导致屏幕或排线损坏", "更新或重装显卡驱动排查", "外接正常则是屏幕硬件损坏", "送修更换屏幕或排线"],
     "expected_doc": "花屏"},
    {"id": "RAG18", "question": "Windows更新总是失败提示错误代码怎么办",
     "ground_truth_points": ["记录错误代码如0x80070002和0x80240438", "运行Windows更新疑难解答", "清空更新缓存后重试", "检查网络和磁盘空间是否充足", "系统文件损坏可DISM修复或手动下载补丁"],
     "expected_doc": "更新失败"},
    {"id": "RAG19", "question": "家里无线网搜不到信号连不上怎么办",
     "ground_truth_points": ["确认WiFi开关开启且飞行模式关闭", "重启路由器和光猫测试", "重启电脑网络适配器", "检查或重装无线网卡驱动", "重置网络协议后重新连接"],
     "expected_doc": "WiFi"},
    {"id": "RAG24", "question": "笔记本电池充不进电一直显示0%",
     "ground_truth_points": ["检查电源适配器和充电接口连接", "重新插拔电池尝试", "更新电池驱动和电源管理软件", "使用电池校准功能", "电池老化或损坏送修更换"],
     "expected_doc": "电池"},
    {"id": "RAG28", "question": "ThinkPad风扇一直狂转机身很烫怎么解决",
     "ground_truth_points": ["清理散热口和风扇积灰", "保持通风口畅通避免软面使用", "关闭高负载程序降低发热", "更换散热硅脂", "风扇异响或持续过热送修"],
     "expected_doc": "发热"},
    # --- 主题漂移陷阱（表面相近但应命中另一文档，测LLM相关性剔除与检索精度） ---
    {"id": "RAG20", "question": "更新完显卡驱动后屏幕出现条纹乱码",
     "ground_truth_points": ["更新或重装显卡驱动排查软件原因", "外接显示器判断是屏幕还是主机问题", "外接显示正常则是屏幕或排线硬件故障", "检查屏幕排线是否松动损坏", "硬件故障送修检测更换屏幕"],
     "expected_doc": "花屏"},
    {"id": "RAG21", "question": "装完系统更新后电脑变得特别卡",
     "ground_truth_points": ["任务管理器查看CPU内存磁盘占用", "禁用不必要的开机启动项", "清理磁盘和临时文件", "查杀病毒和恶意软件", "仍卡顿考虑升级内存或固态硬盘"],
     "expected_doc": "卡顿"},
    {"id": "RAG22", "question": "重装完系统后连不上无线网了",
     "ground_truth_points": ["确认WiFi开关开启飞行模式关闭", "重装系统后无线网卡驱动可能未安装", "设备管理器检查无线网卡状态", "从官网下载重装无线网卡驱动", "检查WLAN服务并重置网络"],
     "expected_doc": "WiFi"},
    {"id": "RAG23", "question": "笔记本不小心进水了，这种情况还能保修吗",
     "ground_truth_points": ["进水属于人为损坏不在免费保修范围", "保修范围限于正常使用下的硬件故障", "保修期自发票日期起算无发票按出厂日期", "主要部件保修期限视具体机型而定", "可联系官方客服评估付费维修方案"],
     "expected_doc": "保修"},
    # --- 噪声长上下文（问题描述冗长含干扰信息，测检索抗噪） ---
    {"id": "RAG25", "question": "我上周刚买的联想笔记本，昨晚看视频时屏幕突然全黑了，但键盘背光还亮着，这是怎么回事",
     "ground_truth_points": ["外接显示器判断是屏幕还是主机问题", "强光下贴近观察判断是否背光故障", "释放静电后重新开机", "进入安全模式卸载重装显卡驱动", "屏幕或背光硬件故障联系售后送修"],
     "expected_doc": "黑屏"},
    {"id": "RAG26", "question": "帮我看看我爸的联想笔记本，今天早上按下开机键之后风扇转了一下就停了，反复几次都开不了机",
     "ground_truth_points": ["检查电源线和插座供电是否正常", "检查电源模块或适配器是否故障", "拔掉外接设备长按电源键放电", "重新插拔内存条", "电源或主板故障送修检测"],
     "expected_doc": "无法开机"},
    # --- 产品类目守卫（PC域问题不应混入智能电视/手机等非PC文档） ---
    {"id": "RAG27", "question": "笔记本开机电源灯亮着但屏幕全黑没有任何显示",
     "ground_truth_points": ["外接显示器判断屏幕还是主机问题", "强光下观察隐约画面判断背光故障", "释放静电后重新开机", "重新插拔内存条擦拭金手指", "屏幕背光等硬件故障送修更换"],
     "expected_doc": "黑屏"},
    # --- 服务类与多意图 ---
    {"id": "RAG29", "question": "电脑坏了想预约官方维修服务该怎么操作",
     "ground_truth_points": ["拨打联想官方服务热线报修", "官网在线报修预约", "官方App内预约维修", "微信公众号也可报修", "报修前准备机型序列号和故障描述"],
     "expected_doc": "客服"},
    {"id": "RAG30", "question": "怎么用主机序列号查询保修期还剩多久",
     "ground_truth_points": ["官网输入序列号SN码查询保修状态", "保修期自购买发票日期起算", "无发票按出厂日期计算可能偏短", "查询内容含整机与主要部件剩余保修", "也可致电客服查询保修状态"],
     "expected_doc": "保修"},
]


# =========================================================================
# Judge LLM 调用（百炼 OpenAI 兼容端点，judge 模型可通过 RAG_EVAL_JUDGE_MODEL 覆盖）
# =========================================================================
# 全局 judge 并发上限：百炼免费额度并发极低，4路以上实测触发限流(ReadTimeout/挂起)，保守 4
_JUDGE_SEM = asyncio.Semaphore(4)


async def judge_llm(system_prompt: str, user_prompt: str) -> str:
    """调百炼 chat completions，返回模型文本。失败返回空串。"""
    url = f"{settings.AL_BAILIAN_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.AL_BAILIAN_API_KEY}",
               "Content-Type": "application/json"}
    payload = {
        "model": JUDGE_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "max_tokens": 4096,
    }
    # 失败重试 3 次（指数退避 2s/4s），吸收网络瞬断/百炼偶发超时
    for attempt in range(3):
        try:
            # qwen3.8-max 为思考模型，faithfulness 长输出 judge 实测可超 60s，放宽到 180s
            async with _JUDGE_SEM, httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"] or ""
        except Exception as e:
            if attempt == 2:
                print(f"  [judge LLM 调用失败(已重试3次)] {type(e).__name__}: {e}")
                return ""
            print(f"  [judge LLM 第{attempt + 1}次失败，重试] {type(e).__name__}: {e}")
            await asyncio.sleep(2 * (attempt + 1))


def parse_json_obj(text: str) -> dict:
    """从 LLM 输出中提取 JSON 对象（容忍 ```json 包裹或前后多余文字）。"""
    if not text:
        return {}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


def _format_contexts(contexts: list) -> str:
    parts = []
    for i, c in enumerate(contexts, 1):
        title = c.get("title", "未知")
        content = (c.get("content", "") or "")[:1500]  # 限制单段长度，避免超长
        parts.append(f"【资料{i}】(来源: {title})\n{content}")
    return "\n\n".join(parts) if parts else "（无检索资料）"


# =========================================================================
# 四个指标（对齐 Ragas 定义）
# =========================================================================
async def score_faithfulness(question: str, contexts: list, answer: str) -> tuple:
    """忠实度：回答中的事实陈述是否都能由资料支撑。返回 (score, reason)。"""
    sys_p = (
        "你是RAG系统评测专家。任务：判断【回答】中的事实陈述是否都能由【参考资料】支撑。"
        "步骤：1)把回答拆解为若干条独立事实陈述；2)逐条判断该陈述能否从参考资料语义推出"
        "（语义一致即可，不要求逐字）；3)统计能被支撑的陈述数。"
        "只输出JSON，格式：{\"supported\": 被支撑数, \"total\": 总陈述数, \"reason\": \"简述\"}。"
    )
    user_p = f"【问题】{question}\n\n【参考资料】\n{_format_contexts(contexts)}\n\n【回答】\n{answer}"
    obj = parse_json_obj(await judge_llm(sys_p, user_p))
    supported = obj.get("supported", 0)
    total = obj.get("total", 0)
    score = (supported / total) if total else 0.0
    return min(max(score, 0.0), 1.0), obj.get("reason", "")


async def score_answer_relevancy(question: str, answer: str) -> tuple:
    """答案相关性：回答是否切题且完整。返回 (score, reason)。"""
    sys_p = (
        "你是RAG系统评测专家。任务：判断【回答】是否切题、完整地回答了【问题】。"
        "评分标准：1=切题且完整覆盖问题；0.5=部分相关但不完整或含明显冗余；0=答非所问。"
        "只输出JSON，格式：{\"score\": 0或0.5或1, \"reason\": \"简述\"}。"
    )
    user_p = f"【问题】{question}\n\n【回答】\n{answer}"
    obj = parse_json_obj(await judge_llm(sys_p, user_p))
    try:
        score = float(obj.get("score", 0))
    except (TypeError, ValueError):
        score = 0.0
    return min(max(score, 0.0), 1.0), obj.get("reason", "")


async def score_context_precision(question: str, contexts: list) -> tuple:
    """上下文精度：检索资料中与问题相关的比例。返回 (score, reason)。"""
    sys_p = (
        "你是RAG系统评测专家。任务：判断【参考资料】中每一段是否与【问题】相关"
        "（即该段是否包含回答问题所需的信息）。"
        f"共有 {len(contexts)} 段资料，逐段判断相关与否，统计相关段数。"
        "只输出JSON，格式：{\"relevant_count\": 相关段数, \"total\": 总段数, \"reason\": \"简述\"}。"
    )
    user_p = f"【问题】{question}\n\n【参考资料】\n{_format_contexts(contexts)}"
    obj = parse_json_obj(await judge_llm(sys_p, user_p))
    rel = obj.get("relevant_count", 0)
    total = obj.get("total", len(contexts)) or len(contexts)
    score = (rel / total) if total else 0.0
    return min(max(score, 0.0), 1.0), obj.get("reason", "")


async def score_context_recall(question: str, contexts: list, gt_points: list) -> tuple:
    """上下文召回：标准答案要点被检索资料覆盖的比例。返回 (score, reason)。"""
    gt = "\n".join(f"{i}. {p}" for i, p in enumerate(gt_points, 1))
    sys_p = (
        "你是RAG系统评测专家。任务：判断【标准答案要点】中的每一条是否都被【参考资料】覆盖"
        "（语义覆盖即可，不要求逐字）。统计被覆盖的要点数。"
        "只输出JSON，格式：{\"covered\": 覆盖数, \"total\": 要点总数, \"reason\": \"简述\"}。"
    )
    user_p = (f"【问题】{question}\n\n【标准答案要点】\n{gt}\n\n"
              f"【参考资料】\n{_format_contexts(contexts)}")
    obj = parse_json_obj(await judge_llm(sys_p, user_p))
    covered = obj.get("covered", 0)
    total = obj.get("total", len(gt_points)) or len(gt_points)
    score = (covered / total) if total else 0.0
    return min(max(score, 0.0), 1.0), obj.get("reason", "")


# =========================================================================
# 主流程
# =========================================================================
async def fetch_query_eval(client: httpx.AsyncClient, question: str) -> dict:
    """调知识库 /query_eval，返回 {answer, contexts}。"""
    resp = await client.post(f"{KB_URL}/query_eval", json={"question": question}, timeout=90.0)
    resp.raise_for_status()
    data = resp.json()
    return {"answer": data.get("answer", ""), "contexts": data.get("contexts", [])}


def retrieval_hit(expected_doc: str, contexts: list) -> bool:
    """规则断言：expected_doc 关键词是否出现在任一检索结果标题中。"""
    kw = expected_doc.strip()
    return any(kw in (c.get("title", "") or "") for c in contexts)


async def evaluate_case(client: httpx.AsyncClient, case: dict) -> dict:
    """评测单条：取检索结果 + 并发跑 4 个 LLM 指标。"""
    cid = case["id"]
    print(f"\n[{cid}] {case['question']}")
    # /query_eval 失败重试 3 次（退避 2s/4s），吸收网络瞬断/容器内 LLM 偶发失败
    r = None
    for attempt in range(3):
        try:
            r = await fetch_query_eval(client, case["question"])
            break
        except Exception as e:
            if attempt == 2:
                print(f"  [ERROR] /query_eval 调用失败(已重试3次): {e}")
                return {"id": cid, "question": case["question"], "error": str(e)}
            print(f"  [/query_eval 第{attempt + 1}次失败，重试] {type(e).__name__}: {e}")
            await asyncio.sleep(2 * (attempt + 1))

    answer, contexts = r["answer"], r["contexts"]
    hit = retrieval_hit(case["expected_doc"], contexts)
    titles = [c.get("title", "?") for c in contexts]
    print(f"  检索命中: {'✅' if hit else '❌'} | 资料数: {len(contexts)} | 标题: {titles}")

    # 并发 4 个 judge 指标
    faith, rel, prec, rec = await asyncio.gather(
        score_faithfulness(case["question"], contexts, answer),
        score_answer_relevancy(case["question"], answer),
        score_context_precision(case["question"], contexts),
        score_context_recall(case["question"], contexts, case["ground_truth_points"]),
    )
    result = {
        "id": cid, "question": case["question"],
        "expected_doc": case["expected_doc"], "retrieval_hit": hit,
        "context_titles": titles,
        "answer": answer[:500],
        "faithfulness": round(faith[0], 3), "faithfulness_reason": faith[1],
        "answer_relevancy": round(rel[0], 3), "answer_relevancy_reason": rel[1],
        "context_precision": round(prec[0], 3), "context_precision_reason": prec[1],
        "context_recall": round(rec[0], 3), "context_recall_reason": rec[1],
    }
    print(f"  忠实度={result['faithfulness']:.2f} 相关性={result['answer_relevancy']:.2f} "
          f"上下文精度={result['context_precision']:.2f} 上下文召回={result['context_recall']:.2f}")
    return result


def write_report(results: list) -> None:
    ok = [r for r in results if "error" not in r]
    n = len(ok)
    avg = lambda k: round(sum(r[k] for r in ok) / n, 3) if n else 0
    hit_rate = round(sum(1 for r in ok if r["retrieval_hit"]) / n, 3) if n else 0

    print("\n" + "=" * 78)
    print(f"RAG 评测结果：{len(ok)}/{len(results)} 条成功")
    print(f"  检索命中率(规则)   : {hit_rate:.2%}")
    print(f"  faithfulness       : {avg('faithfulness'):.3f}")
    print(f"  answer_relevancy   : {avg('answer_relevancy'):.3f}")
    print(f"  context_precision  : {avg('context_precision'):.3f}")
    print(f"  context_recall     : {avg('context_recall'):.3f}")
    print("=" * 78)

    # 原始 JSON
    with open(os.path.join(_HERE, "rag_eval_results.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now().isoformat(), "judge_model": JUDGE_MODEL,
                   "summary": {"retrieval_hit_rate": hit_rate, "faithfulness": avg("faithfulness"),
                               "answer_relevancy": avg("answer_relevancy"),
                               "context_precision": avg("context_precision"),
                               "context_recall": avg("context_recall")},
                   "results": results}, f, ensure_ascii=False, indent=2)

    # Markdown 报告
    docs_dir = os.path.normpath(os.path.join(_HERE, "..", "..", "docs"))
    os.makedirs(docs_dir, exist_ok=True)
    lines = [
        "# RAG 质量评测报告",
        f"\n> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')} | Judge 模型：{JUDGE_MODEL} | 数据集：{n} 条",
        "\n## 指标说明（对齐 Ragas 框架，自建 LLM-as-judge）\n",
        "| 指标 | 含义 |",
        "|------|------|",
        "| 检索命中率 | 期望文档是否被检索到（规则断言，非 LLM） |",
        "| faithfulness 忠实度 | 回答陈述能否由检索资料支撑（防幻觉） |",
        "| answer_relevancy 答案相关性 | 回答是否切题完整 |",
        "| context_precision 上下文精度 | 检索资料中与问题相关的比例 |",
        "| context_recall 上下文召回 | 标准答案要点被检索资料覆盖的比例 |",
        f"\n## 总体得分\n",
        f"- 检索命中率：**{hit_rate:.1%}**",
        f"- 忠实度 faithfulness：**{avg('faithfulness'):.3f}**",
        f"- 答案相关性 answer_relevancy：**{avg('answer_relevancy'):.3f}**",
        f"- 上下文精度 context_precision：**{avg('context_precision'):.3f}**",
        f"- 上下文召回 context_recall：**{avg('context_recall'):.3f}**",
        "\n## 逐条明细\n",
        "| ID | 问题 | 检索命中 | 忠实度 | 相关性 | 上下文精度 | 上下文召回 |",
        "|----|------|:---:|:---:|:---:|:---:|:---:|",
    ]
    for r in results:
        if "error" in r:
            lines.append(f"| {r['id']} | {r['question']} | ERROR | - | - | - | - |")
            continue
        lines.append(
            f"| {r['id']} | {r['question']} | {'✅' if r['retrieval_hit'] else '❌'} | "
            f"{r['faithfulness']:.2f} | {r['answer_relevancy']:.2f} | "
            f"{r['context_precision']:.2f} | {r['context_recall']:.2f} |"
        )
    # 低分案例
    low = [r for r in ok if min(r["faithfulness"], r["answer_relevancy"],
                                r["context_precision"], r["context_recall"]) < 0.7]
    if low:
        lines.append("\n## 待改进案例（任一指标 < 0.7）\n")
        for r in low:
            lines.append(f"### {r['id']} {r['question']}")
            lines.append(f"- 检索标题：{', '.join(r['context_titles'])}")
            lines.append(f"- 忠实度 {r['faithfulness']:.2f}：{r['faithfulness_reason']}")
            lines.append(f"- 上下文召回 {r['context_recall']:.2f}：{r['context_recall_reason']}\n")

    with open(os.path.join(docs_dir, "RAG_EVAL_REPORT.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n报告已写入 docs/RAG_EVAL_REPORT.md 和 backend/tests/rag_eval_results.json")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", default="", help="只跑指定ID，逗号分隔")
    args = parser.parse_args()
    dataset = RAG_DATASET
    if args.ids:
        want = {s.strip() for s in args.ids.split(",") if s.strip()}
        dataset = [c for c in RAG_DATASET if c["id"] in want]

    print(f"RAG 质量评测（知识库 {KB_URL}，judge={JUDGE_MODEL}），共 {len(dataset)} 条")
    async with httpx.AsyncClient() as client:
        # 先健康检查
        try:
            h = await client.get(f"{KB_URL}/health", timeout=10)
            h.raise_for_status()
        except Exception as e:
            print(f"[FATAL] 知识库服务 {KB_URL} 不可用：{e}")
            sys.exit(1)

        # 条目级并发（2 路）：各条 judge 相互独立，gather 保序返回；单条内 4 指标已并发。
        # ⚠️ 并发度勿再调高：百炼免费额度并发极低，4 路条目并发实测触发限流(见 JUDGE_MODEL 注释)
        entry_sem = asyncio.Semaphore(2)

        async def eval_guarded(case: dict) -> dict:
            async with entry_sem:
                return await evaluate_case(client, case)

        results = list(await asyncio.gather(*(eval_guarded(c) for c in dataset)))

    write_report(results)


if __name__ == "__main__":
    asyncio.run(main())
