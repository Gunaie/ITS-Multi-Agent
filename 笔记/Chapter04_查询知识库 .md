# ITS 智能客服系统 —— 知识库查询实战

**主题**:  从检索到生成 —— 构建高精度 RAG 问答系统

**时长**: 1 天  

**讲师**：胡中奎

**版本**：v1.0



## 1、任务目标

**理论知识：**

1. 深入理解 **混合检索 (Hybrid Search)** 策略，解决单一向量检索的痛点。

2. 掌握 **Prompt Engineering (提示词工程)** 在 RAG 中的应用。

3. 理解 **重排序 (Re-ranking)** 的核心作用。



**动手实战**: 基于 Python + LangChain 实现“检索 + 生成”的完整闭环。

1. 实现对知识库文件标题基于 Jieba 分词与字符匹配的**粗排算法**。

2. 实现基于向量余弦相似度的**精排算法**。

3. 编写 **Prompt 模板**，实现上下文注入与防幻觉控制。

4. 开发 `/query` 接口，完成端到端的问答测试。



## 2、核心概念扫盲 

### 2.1 混合检索 (Hybrid Search)

#### 1. 什么是混合检索？

在前面，我们学习了向量检索（Embedding）概念。它很强，能懂“苹果”和“红富士”是一个东西。但是，它也有弱点：

单一的向量检索虽然能理解语义，但存在两个问题：

- **关键词丢失**：用户提问含具体术语（如“U盘启动”），但向量空间中未充分捕捉。
- **长尾覆盖弱**：冷门文档因训练数据少，Embedding 表示不准确。

混合检索 = **关键词/标题召回（广度） + 向量语义排序（精度）**，兼顾召回率与准确率。



#### 2. 为什么要用混合检索？

单纯依赖向量检索，经常会遇到“答非所问”的情况，特别是当用户的问题非常具体（如涉及型号、错误码、专有名词）时。单纯依赖关键词检索，又无法理解用户的自然语言描述（如“电脑总是死机”）。

混合检索结合了两者的优点：**既懂语义，又懂关键词**。



#### 3. 如何实现？

通常的流程是：

1. **多路召回**：同时发起向量检索和关键词检索，分别拿到一批候选文档。

2. **去重合并**：把两边的结果放在一起，去掉重复的。

3. **综合排序**：使用统一的标准对所有结果重新打分。

我们的流程是：

1. **第一路**：Chroma 向量库直接检索 chunk（语义粒度细）
2. **第二路**：基于原始 `.md` 文件**标题**做关键词+分词粗筛 → 再用 Embedding 精排（文档粒度全）
3. 最终将两路结果**合并去重 + 统一重排序**，取 Top-K 返回



**为什么标题很重要？**

联想知识库的标题高度概括（如“电脑蓝屏怎么办”），天然包含核心意图。利用标题做初筛，可快速过滤无关文档，提升整体效率。



### 2.2 提示词工程（Prompt） 

#### 1. 什么是 Prompt Engineering

大模型 (LLM) 就像一个非常有才华但需要明确指令的实习生。**Prompt (提示词)** 就是你发给实习生的工作派单。

**Prompt Engineering** 就是研究“怎么说话”，才能让大模型输出我们想要的结果。



#### 2. 为什么要用它？

在 RAG 系统中，我们不仅仅是把文档丢给模型，还需要约束它的行为：



**明确指令防幻觉**: 明确告诉它“只能用我给你的资料，不要自己瞎编”。

**格式控制**: 要求它输出特定的格式（如禁止使用 `[描述](url)`，改为纯 URL 换行展示，适配前端渲染

**风格统一**: 要求它用“专业的客服语气”回答。



**为什么不用 LangChain 的默认 Prompt？**

默认模板过于通用，无法满足企业级需求（如图片处理、品牌脱敏、格式统一），自定义 Prompt 是 RAG 效果调优的核心手段。



#### 3. 好的 Prompt 长什么样？

一个标准的  Prompt 通常包含：

**角色设定**: "你是一个专业的技术支持..."

**上下文 (Context)**: "这是我查到的资料：..."

**约束条件**: "如果资料里没有，就说不知道..."

**用户问题**: "用户问：...



### 2.3 重排序（Re-ranking）

#### 1. 什么是重排序？

初步检索可能返回 50 个候选，但只有前 3~5 个真正相关，Re-ranking 就是在初筛结果上，用更精细的模型或规则**重新打分排序**。



#### 2. 为什么要进行重排序？

**向量检索存在“语义漂移”问题**

单纯依赖 embedding 相似度时，可能召回语义相近但**事实不相关**的内容（例如“蓝屏” vs “黑屏”），尤其在知识条目短、关键词稀疏时更明显。

**单一检索路径覆盖不全**

- 向量检索擅长语义匹配，但对**标题、关键词等显式信息不敏感**
- 纯文本关键词匹配能抓住关键术语，但**无法理解同义表达**（如“开机失败” vs “无法启动”）
  → 任一路径单独使用都会漏掉部分高质量结果



 **提升 Top-K 结果质量**

RAG 系统通常只将 Top 3~5 的 chunk 输入大模型生成答案。若这些 chunk 包含噪声或次相关信息，会直接导致**答案错误或幻觉**

重排序通过多路信号融合，确保送入生成模型的是**最相关、最完整、最可靠**的知识片段



**混合检索策略落地** 

重排序是融合“向量检索 + 标题关键词匹配”等多路召回结果的关键环节，实现**1+1 > 2**的效果。

重排序不是可选项，而是高精度问答系统的必要环节**——它把“找得到”升级为“找得准”



#### 3. 重排序如何使用？

#### 3. 重排序如何使用？

**向量检索 (Route 1)：**
 Chroma 向量库直接检索 chunk（语义粒度细，适合内容匹配）

**标题匹配 (Route 2)：**

1. 扫描所有 `.md` 文件标题（来自 `./data/raw/`）
2. **粗排**：计算问题与标题的 Jieba 分词重合度 + 字符重合度，取 Top 50 标题
3. **精排**：对粗排 Top 5 的标题，计算其向量与问题向量的余弦相似度
4. 读取精排 Top 5 对应的完整文件内容（作为高置信度候选）

**合并去重：**

- 将 Route 1（向量 chunk）和 Route 2（整篇文档）的结果合并
- 基于 `page_content` 哈希或文本相似度去重，避免重复输入

**最终排序：**

- 对合并后的所有候选文档，统一使用**高精度 embedding 模型**重新计算与问题的相似度
- 返回最终 Top 5 结果，供生成模块使用

> 该策略兼顾**召回广度**（多路检索）与**排序精度**（重排序），显著提升问答准确率，尤其在短文档、专业术语场景下效果突出。



## 3、项目环境与结构（续）

本节延续第一天的架构，新增模块如下：

```python
knowledge/
├── business_logic/
│   ├── retrieval_service.py    # ← 新增：实现混合检索与重排序
│   └── query_service.py        # ← 新增：实现 Prompt 构造与 LLM 调用
├── presentation/
│   └── api/
│       └── routes.py           # ← 新增 /query 接口
└── config/
    └── settings.py             # ← 新增 TOP_ROUGH, TOP_FINAL 等配置
```

- **`retrieval_service.py`**：负责“找资料”，融合向量检索与标题匹配
- **`query_service.py`**：负责“答问题”，构造安全 Prompt 并调用 LLM
  - **`/query` 接口**：对外提供问答服务，输入问题，输出答案



## 4、构建查询流水线

构建搜索服务的过程，就像**组装一条流水线**，数据从用户问题流入，经过层层筛选和加工，最终流出为完美的答案。

我们将分为三个阶段来实现：

1. **检索服务 (Retrieval Service)**：负责“找”，从海量数据中捞出最相关的几条。
2. **问答服务 (Query Service)**：负责“答”，结合找到的资料生成回复。
3.  **接口层 (Presentation)**：负责“接”，暴露 API 供前端调用。



### 4.1 检索服务 (Retrieval Service)

#### 1. 目标

实现一个智能检索器，能够根据用户的问题，从 ChromaDB 和本地 Markdown 文件中，精准地找出最相关的文档片段。



#### 2. 需求分析

**1. 如何平衡速度与精度？**

- 先用**标题粗排**快速缩小范围（从 1000+ 文档 → 20 个）
- 再用**向量精排**提升相关性（20 → 5）

**2. 为何要两路召回？**

- **向量路**：擅长语义匹配（“开不了机” ≈ “无法启动”）
- **标题路**：擅长关键词命中（“U盘安装Win7” → 精准匹配标题）
- 两者互补，避免漏检

**3. 如何防止重复？**

- 使用 `(source路径, 内容前100字)` 作为去重 key
- 确保同一知识不被多次返回

#### 3. 实现流程

当用户提问时，`RetrievalService.retrieve()` 按以下步骤执行：

**1. 第一路：向量库检索**

- 调用 `Chroma.as_retriever().invoke(question)`
- 返回 top-k 个语义最相近的 **chunk**

**2. 第二路：标题匹配召回**

- 扫描 `./data/raw/` 下所有 `.md` 文件
- 提取标题，进行 **粗排（Jieba + 字符匹配）**
- 对粗排结果进行 **精排（Embedding 语义打分）**
- 读取完整文档内容，转为 `Document` 对象

**3. 合并与去重**

- 将两路结果合并为候选集
- 基于 `(source, content[:100])` 去重

**4. 统一重排序**

- 对所有候选计算与问题的 **余弦相似度**
- 按分数降序，返回 top-N（如 5 条）



> 该设计兼顾**语义泛化能力**与**关键词精确匹配**，显著提升实际问答准确率。



#### 4. 代码实现

**模块位置**: `business_logic/retrieval_service.py`

```python
import os
import re
import jieba
from typing import List, Dict, Any
from sklearn.metrics.pairwise import cosine_similarity
from langchain_core.documents import Document

import sys
# 将项目根目录添加到 sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_dir))))
sys.path.append(project_root)
sys.path.append("c:\\Users\\Administrator\\Desktop\\完整三件套\\its_project")

from backend.knowledge.config.settings import settings
from backend.knowledge.data_access.vector_store_manager import VectorStoreManager

class RetrievalService:
    def __init__(self):
        self.vector_manager = VectorStoreManager()

    def collect_md_metadata(self, folder_path: str) -> List[Dict[str, Any]]:
        """收集MD文件元数据（路径+标题）"""
        md_metadata = []
        if not os.path.exists(folder_path):
            return md_metadata

        filename_pattern = re.compile(r'^(.+?)-(.*?)\.md$')

        for filename in os.listdir(folder_path):
            if filename.endswith('.md'):
                match = filename_pattern.match(filename)
                if match:
                    title = match.group(2).strip()
                else:
                    title = os.path.splitext(filename)[0].strip()

                md_metadata.append({
                    "path": os.path.join(folder_path, filename),
                    "title": title
                })
        return md_metadata

    def rough_ranking(self, md_metadata: List[Dict], user_question: str) -> List[Dict]:
        """粗排：基于标题关键词重合度（混合模式）"""
        user_question = user_question.strip()
        if not user_question:
            for item in md_metadata:
                item["rough_score"] = 0
            return sorted(md_metadata, key=lambda x: x["rough_score"], reverse=True)[:settings.TOP_ROUGH]
        
        JIEBA_WEIGHT = 0.7
        
        for item in md_metadata:
            title = item.get("title", "")
            if not title or not title.strip():
                item["rough_score"] = 0
                continue
            
            question_chars = set(user_question)
            title_chars = set(title.strip())
            char_score = len(question_chars & title_chars) / (len(question_chars) + 1e-6) if question_chars else 0
            
            question_words = set(jieba.lcut(user_question))
            title_words = set(jieba.lcut(title.strip()))
            word_score = len(question_words & title_words) / (len(question_words) + 1e-6) if question_words else 0
            
            combined_score = JIEBA_WEIGHT * word_score + (1 - JIEBA_WEIGHT) * char_score
            item["rough_score"] = combined_score
        
        return sorted(md_metadata, key=lambda x: x.get("rough_score", 0), reverse=True)[:settings.TOP_ROUGH]

    def fine_ranking(self, rough_results: List[Dict], user_question: str) -> List[Dict]:
        """精排：结合Embedding语义相似度和粗排分数"""
        if not rough_results:
            return []

        question_embedding = self.vector_manager.embed_query(user_question)
        titles = [item["title"] for item in rough_results]
        title_embeddings = self.vector_manager.embed_documents(titles)
        semantic_similarities = cosine_similarity([question_embedding], title_embeddings).flatten()

        WEIGHT_ROUGH = 0.5
        WEIGHT_SEMANTIC = 0.5
        
        for i, item in enumerate(rough_results):
            semantic_score = max(0, float(semantic_similarities[i]))
            rough_score = item.get("rough_score", 0)
            combined_score = WEIGHT_ROUGH * rough_score + WEIGHT_SEMANTIC * semantic_score
            item["semantic_score"] = semantic_score
            item["combined_score"] = combined_score

        return sorted(rough_results, key=lambda x: x["combined_score"], reverse=True)[:settings.TOP_FINAL]

    def retrieve(self, user_question: str) -> List[Document]:
        all_candidates = []

        # 第一路：向量库检索
        retriever = self.vector_manager.get_retriever()
        vector_docs = retriever.invoke(user_question)
        all_candidates.extend(vector_docs)

        # 第二路：标题匹配召回
        if os.path.exists(settings.MD_FOLDER_PATH):
            metadata = self.collect_md_metadata(settings.MD_FOLDER_PATH)
            rough = self.rough_ranking(metadata, user_question)
            final_title_matches = self.fine_ranking(rough, user_question)

            for item in final_title_matches[:5]:
                try:
                    with open(item["path"], 'r', encoding='utf-8') as f:
                        content = f.read()
                        doc = Document(
                            page_content=content,
                            metadata={"source": item["path"], "title": item["title"]}
                        )
                        all_candidates.append(doc)
                except Exception as e:
                    print(f"读取文件失败 {item['path']}: {e}")

        # 去重
        seen = set()
        unique_candidates = []
        for doc in all_candidates:
            key = (doc.metadata.get("source", ""), doc.page_content[:100])
            if key not in seen:
                seen.add(key)
                unique_candidates.append(doc)

        if not unique_candidates:
            return []

        # 统一重排序
        question_emb = self.vector_manager.embed_query(user_question)
        candidate_texts = [doc.page_content for doc in unique_candidates]
        candidate_embs = self.vector_manager.embed_documents(candidate_texts)
        similarities = cosine_similarity([question_emb], candidate_embs).flatten()

        scored_docs = [(unique_candidates[i], float(similarities[i])) for i in range(len(unique_candidates))]
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        top_docs = [doc for doc, score in scored_docs[:settings.TOP_FINAL]]
        
        return top_docs
```



### 4.2 问答服务 (Query Service)

#### 1. 目标

基于检索结果，生成准确、安全、格式规范的回答，也即将检索到的“死”资料，转化为“活”的回答。

#### 2. 需求分析

**1. 如何防止幻觉？**

- 明确指令：“不能基于资料中未提及的信息”
- 设置兜底话术：“资料中未提及相关信息”

**2. 如何处理图片？**

- 原始 Markdown 图片语法 `![描述](url)` 不适合直接展示
- 后处理替换为纯 URL，每张图独占一行，便于前端解析

**3. 为何设置 temperature=0？**

- 技术支持场景要求**确定性输出**，避免随机性导致答案不一致



#### 3. 实现流程

**1.判空**：如果检索结果为空，直接返回“未找到相关资料”。

**2.拼接上下文**：`context = doc1 + "\n" + doc2 ...`

**3.填充 Prompt**：将 `context` 和 `user_question` 填入模板。

**4.调用 LLM**：使用 `ChatOpenAI.invoke()` 获取回复。

**5.后处理**：正则匹配清洗Markdown 图片语法 ，转为纯 URL



#### 4. 代码实现

**模块位置**: `business_logic/query_service.py`

~~~python
from langchain_openai import ChatOpenAI
from langchain_core.documents import Document
from typing import List
from backend.knowledge.config.settings import settings
import re

def clean_markdown_images(text: str) -> str:
    """将 [描述](url) 替换为纯 url，每张图单独一行"""
    pattern = r'!\$$[^$$]*\]\((https?://[^\s\)]+)\)'
    def replace_func(match):
        url = match.group(1)
        return f"\n{url}\n"
    cleaned = re.sub(pattern, replace_func, text)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()

class QueryService:
    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.MODEL,
            temperature=0,
            api_key=settings.API_KEY,
            base_url=settings.BASE_URL
        )

    def generate_answer(self, question: str, context_docs: List[Document]) -> str:
        """生成回答"""
        if not context_docs:
            return "未找到相关知识，请上传相关文档后再查询。"

        context_text = "\n\n".join([f"资料{i + 1}：{doc.page_content}" for i, doc in enumerate(context_docs)])
        
        prompt = f"""
       请根据以下资料回答用户问题，不能基于资料中未提及的信息。

       【重要格式要求】
        - 资料中的图片链接必须保留，但**不要使用 Markdown 图片语法（如 [描述](链接)）**。
        - 请直接写出**完整的图片 URL**（例如：https://example.com/image.png），每张图占一行。
        - 回答应简洁、步骤清晰，避免冗余信息。
        - 不要提及具体设备型号、品牌或软件版本（如“联想”、“UltraISO”等），除非问题明确要求。
        - 如果当前问题和资料中的信息不相关，直接回复“资料中未提及相关信息”。
        
        资料：```
        {context_text}
        ```
        
        用户问题：```
        {question}
        ```

        回答：
        """
        
        try:
            response = self.llm.invoke(prompt)
            answer = response.content
            cleaned_answer = clean_markdown_images(answer)
            return cleaned_answer
        except Exception as e:
            print(f"LLM调用失败: {e}")
            return "抱歉，生成回答时出现错误。"
~~~



### 4.3  Web 查询接口 (API Interface)

#### 1.目标

将检索与生成能力封装为 RESTful API，供前端调用。



#### 2.需求分析

**1.路径**: `POST /query`

**2.入参:** JSON 格式 `{"question": "..."}`

**3.出参**: JSON 格式 `{"answer": "...", "question": "..."}`



#### 3.实现流程

1.定义 Pydantic 模型 `QueryRequest` 和 `QueryResponse`。

2.在 `routes.py` 中实例化 `RetrievalService` 和 `QueryService`。

3.编写路由函数，串联“检索”和“生成”两个步骤。

4.添加异常处理 (Try-Except)。



#### 4.代码实现

**模块位置**: `presentation/api/routes.py`



```python
import os
import tempfile
from fastapi import APIRouter, UploadFile, File, HTTPException
from backend.knowledge.presentation.api.schemas import QueryRequest, QueryResponse, UploadResponse
from backend.knowledge.business_logic.file_processor import FileProcessor
from backend.knowledge.business_logic.retrieval_service import RetrievalService
from backend.knowledge.business_logic.query_service import QueryService

router = APIRouter()

# 实例化服务
file_processor = FileProcessor()
retrieval_service = RetrievalService()
query_service = QueryService()

@router.post("/upload", summary="上传文件到知识库", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        content = await file.read()
        temp_file.write(content)
        temp_file_path = temp_file.name

    try:
        chunks = file_processor.process_and_save_file(temp_file_path)
        return UploadResponse(
            status="success",
            message="文件已成功存入知识库",
            file_name=file.filename,
            chunks_added=chunks
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

@router.post("/query", summary="查询知识库", response_model=QueryResponse)
async def query_knowledge(request: QueryRequest):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    
    try:
        print("查询问题:", request.question)
        docs = retrieval_service.retrieve(request.question)
        answer = query_service.generate_answer(request.question, docs)
        print("生成的答案:", answer)
        return QueryResponse(question=request.question, answer=answer)
    except Exception as e:
        print(f"查询出错: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```



## 5、测试

### 5.1 启动服务

确保虚拟环境已激活，在 `backend/knowledge` 目录下运行：

```powershell
cd backend/knowledge 
python main.py
```

看到 `Uvicorn running on http://127.0.0.1:8001` 表示启动成功。

### 5.2 调用接口

1. 打开浏览器访问 : `http://127.0.0.1:8001/`
2. 找到 `/query` 接口，输入问题如：“电脑蓝屏怎么办？”

### 5.3 结果观察

1. 查看返回的 `answer` 是否基于知识库内容
2. 检查是否包含有效图片 URL（非 Markdown 语法）
3. 尝试无关问题，验证是否返回“资料中未提及相关信息”