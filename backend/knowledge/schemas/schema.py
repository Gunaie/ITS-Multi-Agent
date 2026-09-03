from pydantic import BaseModel
from typing import List


class UploadResponse(BaseModel):
    """
    文件上传的响应数据模型
    """
    status:str  # 响应状态
    message:str # 响应的消息内容
    file_name:str # 上传的文件名
    chunks_added:int # 上传文档切分之后的文档块数量



class QueryResponse(BaseModel):
    """
    查询的响应数据模型
    """
    question:str # 用户提问问题
    answer:str # 模型的回答

class QueryRequest(BaseModel):
    """
    查询的请求数据模型
    """
    question: str  # 用户提问问题


class ContextItem(BaseModel):
    """检索到的单条上下文（RAG 评测用）"""
    title: str   # 来源文档标题
    content: str  # 文档片段内容


class QueryEvalResponse(BaseModel):
    """
    评测专用查询响应：在 answer 之外额外返回检索到的 contexts，
    供 RAG 质量评测（faithfulness/context_precision 等指标）使用。
    生产 /query 接口不受影响。
    """
    question: str
    answer: str
    contexts: List[ContextItem]  # 检索到的参考文档片段

