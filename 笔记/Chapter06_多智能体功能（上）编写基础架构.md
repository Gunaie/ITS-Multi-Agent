# ITS 智能客服系统 —— 多智能体开发实战

**主题**: 基于 OpenAI Agents SDK 构建企业级多智能体基础设施层搭建

**时长**: 1 天

**讲师**：胡中奎

**版本**：v1.0 



## 1、任务目标



**1.1 理论知识**

**1.理解 Multi-Agent (多智能体) 架构**:

**Orchestrator (调度员)**: 系统的核心大脑，负责意图识别和任务分发。

 **Sub-Agents (子智能体)**: 专注于特定领域的专家（如技术顾问、业务办理员）。

 **Handoff (交接)**: 智能体之间如同接力赛一般的任务移交机制。

**2.掌握 OpenAI Agents SDK 核心组件**:

​    `Agent`: 智能体的定义（指令、工具、模型）。

​    `Runner`: 智能体的运行引擎，负责管理对话循环。

   `Function Tool`: 让智能体具备执行代码的能力。

**3.理解 MCP (Model Context Protocol)**:

   一种标准化的协议，让大模型能像插拔 USB 设备一样连接外部数据源（如百度地图、阿里百炼通用搜索）。



**1.2 动手实战**

1. **搭建基础设施**: 配置模型客户端、编写自定义工具函数（知识库、服务站）、接入 MCP 服务器（地图、搜索）。
2. **编写核心智能体**: 实现调度智能体、技术顾问智能体、综合服务智能体。
3. **搭建 FastAPI 后端**: 集成 SDK，实现流式接口。



##  2、项目环境与结构

### 2.1 准备项目环境

1.在项目根目录创建 `backend/app` 作为后端代码主目录

2.创建虚拟环境并激活：

```shell
python -m venv .venv
.venv\Scripts\activate     # Windows
```

3.安装依赖：

```shell
pip install -r  requirements.txt
```



### 2.2 项目结构搭建

项目采用分层架构，核心模块划分如下：

```sql
backend/app/
├── core_agents/                    # 核心智能体定义
│   ├── __init__.py
│   ├── orchestrator.py             # 调度智能体
│   ├── technical_agent.py          # 技术顾问智能体
│   └── comprehensive_service_agent.py # 全能业务智能体
├── infrastructure/                 # 基础设施层
│   ├── clients/                    # 模型客户端
│   │   └── client_utils.py
│   ├── database/                   # 数据库连接池
│   │   └── database.py
│   ├── logger/                     # 日志系统
│   │   └── logger.py
│   ├── mcp/                        # MCP 服务器管理
│   │   ├── manager.py
│   │   └── servers.py
│   ├── prompt_loader/              # 提示词加载器
│   │   └── prompt_loader.py
│   ├── tools/                      # 工具集
│   │   ├── knowledge_tools.py
│   │   ├── map_tools.py
│   │   └── service_station_tools.py
│   └── __init__.py
├── application/                    # 应用逻辑层
│   ├── agent_service.py            # 智能体服务入口
│   ├── session_manager.py          # 会话与记忆管理
│   ├── stream_processor.py         # 流式响应处理
│   └── __init__.py
├── presentation/                   # 表现层
│   ├── response_utils.py           # 响应构造工具
│   ├── schemas.py                  # 数据模型定义
│   ├── routes.py                   # API 路由
│   └── __init__.py
├── config/                         # 配置管理
│   ├── env_loader.py
│   ├── settings.py
│   └── __init__.py
├── prompts/                        # 提示词库（Markdown 文件）
│   ├── orchestrator.md
│   ├── technical_agent.md
│   └── comprehensive_service_agent.md
├── main.py                         # FastAPI 应用入口
└── __init__.py
```

**说明**：该结构清晰分离了智能体定义、工具集成、会话管理与 API 层，便于扩展和维护。



## 3、关键技术栈

- **OpenAI Agents SDK**：官方智能体框架，支持 Agent、Tool、Handoff、Streaming
- **FastAPI**：现代异步 Web 框架，支持 SSE 流式响应
- **MySQL + Connection Pool**：用户会话与记忆持久化
- **MCP (Model Context Protocol)**：连接外部工具与数据源（搜索、地图等）
- **多模型支持**：通过 `client_utils.py` 可灵活切换不同模型服务商



## 4、构建多智能体协作流水线

智能体协作流程可类比 **医院分诊与专家会诊**：

1. **分诊台（调度智能体）**：初步判断用户意图，决定转交哪个科室
2. **专科医生（子智能体）**：深度处理某一类问题（技术/业务）
3. **返回分诊台**：子智能体完成处理后，将结果与控制权交回分诊台
4. **最终总结**：分诊台整合各科室结果，向用户做简洁确认



### 4.1 创建核心智能体

#### 1.创建调度智能体

##### 1. 目标

创建系统的"大脑"——调度智能体，负责分析用户请求、拆解复杂任务，并协调各子智能体协同工作，确保多步骤任务有序执行。

**模块位置**: `backend/app/core_agents/orchestrator.py`



##### 2. 需求分析

1. **智能体的核心职责是什么？**
   - **任务调度**：分析用户请求，判断问题类型（技术问题/业务问题）
   - **智能分发**：将任务转交给合适的子智能体处理
   - **流程控制**：管理任务执行顺序，确保多步骤任务按序完成
   - **结果整合**：在各子智能体完成任务后，进行最终总结
2. **如何实现智能的调度决策？**
   - **意图识别**：分析用户输入，判断问题类型
   - **历史感知**：检查对话历史，避免重复执行已完成的步骤
   - **流程编排**：对于多步骤任务，按顺序调用不同子智能体
   - **异常处理**：处理无法识别或超出范围的问题类型
3. **与其他智能体的关系如何管理？**
   - **交接机制**：通过`handoff`定义明确的交接关系
   - **控制权流转**：子智能体完成任务后必须返回控制权
   - **工具标准化**：为交接动作设置统一的工具名和描述
   - **边界清晰**：确保调度智能体不越界处理专业问题

##### 3. 实现流程

1. **智能体初始化**
   - 加载调度智能体专属提示词（`orchestrator.md`）
   - 配置轻量级模型（sub_model）降低调度成本
   - 设置合适的温度参数（0.3）确保调度稳定性
2. **定义交接关系**
   - 为技术顾问智能体创建交接：`transfer_to_technical_agent`
   - 为全能业务智能体创建交接：`transfer_to_comprehensive_service_agent`
   - 为每个交接设置清晰的功能描述
3. **注入返回机制**
   - 为两个子智能体注入`return_to_orchestrator`交接工具
   - 确保子智能体完成任务后能将控制权交回
4. **流程执行逻辑**
   - 用户提问 → 调度智能体判断意图 → 调用相应交接工具
   - 子智能体处理 → 调用`return_to_orchestrator` → 控制权返回
   - 调度智能体检查任务完成情况 → 给出最终总结或继续下一步

##### 4. 代码实现

```python
from agents import Agent, handoff, ModelSettings
from backend.app.core_agents.technical_agent import technical_agent
from backend.app.core_agents.comprehensive_service_agent import comprehensive_service_agent
from backend.app.infrastructure.clients.client_utils import sub_model
from backend.app.infrastructure.prompt_loader import load_prompt

# 创建调度智能体
orchestrator_agent = Agent(
    name="调度智能体",
    instructions=load_prompt("orchestrator"),  # 从prompts/orchestrator.md加载
    model=sub_model,  # 使用轻量模型降低调度成本
    model_settings=ModelSettings(temperature=0.3),  # 较低温度确保调度稳定性
    handoffs=[
        handoff(
            agent=technical_agent,
            tool_name_override="transfer_to_technical_agent",
            tool_description_override="处理技术问题（涉及设备故障、操作步骤、原理说明、维修建议等）以及实时资讯类问题（如股票价格、天气、新闻等）。",
        ),
        handoff(
            agent=comprehensive_service_agent,
            tool_name_override="transfer_to_comprehensive_service_agent",
            tool_description_override="处理业务问题（服务站查询与导航）。",
        ),
    ]
)

# 为子智能体注入返回调度智能体的交接机制
# 确保子智能体完成任务后能正确返回控制权
if not any(h.tool_name == "return_to_orchestrator" for h in comprehensive_service_agent.handoffs):
    comprehensive_service_agent.handoffs.append(
        handoff(
            agent=orchestrator_agent,
            tool_name_override="return_to_orchestrator",
            tool_description_override="完成业务办理后，必须返回调度智能体进行结果整合",
        )
    )

# 为technical_agent注入返回机制
if not any(h.tool_name == "return_to_orchestrator" for h in technical_agent.handoffs):
    technical_agent.handoffs.append(
        handoff(
            agent=orchestrator_agent,
            tool_name_override="return_to_orchestrator",
            tool_description_override="完成技术咨询后，必须返回调度智能体进行结果整合",
        )
    )
```



#### 2.创建技术顾问智能体

##### 1.目标

创建"技术专家"——技术顾问智能体，专门处理技术维修类和实时资讯类问题，确保技术问题的准确性和时效性。

**模块位置**: `backend/app/core_agents/technical_agent.py`

##### 2.需求分析

1. **技术顾问智能体的核心职责是什么？**

   - **技术问题解答**：解决设备故障、操作步骤、原理说明、维修建议等私域和公域技术问题
   - **实时资讯查询**：提供股票价格、天气、新闻、版本号等实时信息
   - **智能分流**：自动判断问题类型并采用相应处理流程
   - **来源声明**：明确区分知识库答案和网络搜索结果

2. **如何处理不同类型的问题？**

   - **技术维修类**：优先查询私域知识库，无结果时再联网搜索
   - **实时资讯类**：直接使用联网搜索，跳过知识库查询
   - **流程隔离**：两类问题采用完全不同的处理流程，防止混淆

3. **如何保证回答的准确性和权威性？**

   - **知识库优先**：技术问题优先从权威知识库获取答案
   - **来源标注**：网络搜索结果必须标注信息来源
   - **边界明确**：严格限制处理范围，拒绝非技术/非实时问题

   

##### 3.实现流程

1. **智能体初始化**

   - 加载技术顾问智能体专属提示词（`technical_agent.md`）
   - 配置主力模型（main_model）确保回答质量
   - 设置适中温度参数（0.5）平衡准确性和创造性

2. **工具集成**

   - 集成私域知识库查询工具：`query_knowledge`
   - 接入搜索MCP服务器：`search_mcp`（提供`bailian_web_search`工具）

3. **执行流程设计**

   - **第一步：问题类型判断**

     - 实时资讯类：涉及当前时间点之后的数据
     - 技术维修类：涉及设备故障、操作步骤等通用技术知识

   - **第二步：按类型执行**

     - 实时资讯 → 直接调用`bailian_web_search`
     - 技术问题 → 先调用`query_knowledge` → 无结果再调用`bailian_web_search`

   - **第三步：返回控制权**

     - 完成回答后必须调用`return_to_orchestrator`

     

##### 4.代码实现

```python
from agents import Agent, ModelSettings
from backend.app.infrastructure.clients.client_utils import main_model
from backend.app.infrastructure.tools.knowledge_tools import query_knowledge
from backend.app.infrastructure.mcp.servers import search_mcp
from backend.app.infrastructure.prompt_loader import load_prompt

technical_agent = Agent(
    name="技术顾问智能体",
    instructions=load_prompt("technical_agent"),  # 从prompts/technical_agent.md加载
    model=main_model,  # 使用主力模型确保回答质量
    model_settings=ModelSettings(
        temperature=0.5,  # 适中温度平衡准确性与创造性
        max_tokens=2048,  # 限制最大输出长度
    ),
    tools=[query_knowledge],  # 私域知识库查询工具
    mcp_servers=[search_mcp],  # 搜索MCP服务器（提供bailian_web_search工具）
)
```



#### 3.创建全能业务智能体 

##### 1. 目标

创建"业务专员"——全能业务智能体，专门处理服务站查询与普通地点导航，确保地理位置信息的准确性和业务逻辑的正确性。

**模块位置**: `backend/app/core_agents/comprehensive_service_agent.py`

##### 2. 需求分析

1. **智能体的核心职责是什么？**
   - **服务站查询**：查找官方授权服务站、维修点、售后中心
   - **普通地点导航**：为景点、学校、商场等非服务类POI提供导航
   - **位置解析**：智能识别用户当前位置或指定起点
   - **导航生成**：为推荐的地点生成可点击的导航链接
2. **如何处理服务站查询与普通导航的区别？**
   - **服务站查询**：必须使用数据库坐标，确保数据一致性
   - **普通导航**：可以使用地理编码工具解析地址
   - **流程隔离**：两类场景使用不同的工具链，防止数据污染
   - **坐标标准**：所有坐标必须统一为BD09LL（百度系）
3. **如何保证业务逻辑的正确性？**
   - **意图判断**：通过关键词识别用户真实意图
   - **数据验证**：确保服务站坐标来自权威数据库
   - **结果呈现**：提供完整的服务站信息（名称、地址、电话、距离）

##### 3. 实现流程

1. **智能体初始化**
   - 加载全能业务智能体专属提示词（`comprehensive_service_agent.md`）
   - 配置主力模型（main_model）确保业务处理能力
   - 设置适中温度参数（0.6）平衡准确性和用户体验
2. **工具集成**
   - **位置相关工具**：
     - `resolve_user_location_from_text`：解析用户当前位置
     - `geocode_address`：将地址转换为坐标（仅用于非服务站）
   - **服务站相关工具**：
     - `query_nearest_repair_shops_by_coords`：查询最近的服务站
   - **MCP服务器**：
     - `baidu_map_mcp`：提供地图相关功能（搜索、导航等）
3. **执行流程设计**
   - **第一步：意图判断**
     - 服务站意图：包含维修、售后、品牌+服务相关词
     - 普通POI意图：非服务类地点名称
   - **第二步：按类型执行**
     - 服务站流程：位置解析 → 数据库查询  → 导航生成
     - 普通POI流程：位置解析 → 地址编码 → 导航生成
   - **第三步：返回控制权**
     - 完成业务后必须调用`return_to_orchestrator`

##### 4.代码实现

```python
from agents import Agent, ModelSettings
from backend.app.infrastructure.clients.client_utils import main_model
from backend.app.infrastructure.tools.service_station_tools import (
    resolve_user_location_from_text,
    query_nearest_repair_shops_by_coords
)
from backend.app.infrastructure.tools.map_tools import geocode_address
from backend.app.infrastructure.mcp.servers import baidu_map_mcp
from backend.app.infrastructure.prompt_loader import load_prompt

comprehensive_service_agent = Agent(
    name="全能业务智能体",
    instructions=load_prompt("comprehensive_service_agent"),  # 从prompts/comprehensive_service_agent.md加载
    model=main_model,  # 使用主力模型确保业务处理能力
    model_settings=ModelSettings(
        temperature=0.6,  # 适中温度平衡准确性与用户体验
        max_tokens=2048,  # 限制最大输出长度
    ),
    tools=[
        resolve_user_location_from_text,  # 解析用户当前位置
        query_nearest_repair_shops_by_coords,  # 查询最近服务站
        geocode_address  # 地址转坐标（仅用于非服务站）
    ],
    mcp_servers=[baidu_map_mcp],  # 百度地图MCP服务器
)
```



### 4.2 核心智能体协作总结

| 智能体             | 角色定位 | 核心职责                     | 关键工具                    | 模型配置        |
| :----------------- | :------- | :--------------------------- | :-------------------------- | :-------------- |
| **调度智能体**     | 系统总控 | 任务分析、智能分发、流程控制 | handoff交接工具             | 轻量模型(t=0.3) |
| **技术顾问智能体** | 技术专家 | 技术问题解答、实时资讯查询   | query_knowledge、search_mcp | 主力模型(t=0.5) |
| **全能业务智能体** | 业务专员 | 服务站查询、地点导航         | 位置工具、地图mcp           | 主力模型(t=0.6) |

**协作流程示例**：

> 用户："电脑蓝屏了怎么办？然后帮我找附近的小米服务站"
>
> 1. 调度智能体分析：包含两个独立任务
> 2. 调用transfer_to_technical_agent → 技术顾问智能体
> 3. 技术顾问智能体：query_knowledge → 返回解决方案 → return_to_orchestrator
> 4. 调度智能体：调用transfer_to_comprehensive_service_agent → 全能业务智能体
> 5. 全能业务智能体：位置解析 → 服务站查询 → 导航生成 → return_to_orchestrator
> 6. 调度智能体：总结两个任务的处理结果

这种三层智能体架构实现了**职责分离、专业分工、流程可控**的设计目标，既能处理单一专业问题，也能协作完成复杂多步骤任务。



## 5、构建基础设施

有了Agent作为躯体，接下来我们需准备好"大脑"（Model）、"双手"（Tools）和"感官"（MCP）。这些基础设施是智能体系统能够正常运转的关键支撑。

#### 5.1 配置管理与环境隔离

良好的配置管理是系统可维护性的关键，我们通过分层配置和环境变量实现灵活的配置管理。

##### 1. 目标

创建统一的配置管理系统，支持多环境部署，确保敏感信息的安全性。

**模块位置**:

- `backend/app/config/env_loader.py`
- `backend/app/config/settings.py`

##### 2. 需求分析

1. **配置来源**
   - 环境变量：存储敏感信息和环境相关配置
   - 配置文件：存储应用级别的默认配置
   - 代码常量：存储不常更改的业务常量
2. **配置分类**
   - **模型配置**：API密钥、Base URL、模型名称
   - **数据库配置**：连接参数、连接池设置
   - **外部服务**：知识库URL、地图API密钥等
   - **应用配置**：日志级别、超时时间等
3. **环境隔离**
   - 开发环境：使用开发专用的API端点
   - 测试环境：隔离的测试数据
   - 生产环境：生产级别的安全和性能配置

##### 3. 实现流程

1. **环境变量加载**
   - 使用`python-dotenv`加载`.env`文件
   - 提供明确的加载路径，避免环境变量丢失
2. **配置类定义**
   - 创建`SettingConfig`类，封装所有配置项
   - 为每个配置项提供适当的默认值
3. **配置验证**
   - 在应用启动时验证关键配置是否存在
   - 记录配置加载状态，便于排查问题

##### 4. 代码实现

环境变量加载：

```python
import os
from dotenv import load_dotenv

def load_env():
    # 明确指定.env文件路径
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(base_dir, ".env")

    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"Loaded configuration from {env_path}")
    else:
        # 回退到默认行为（向上搜索）
        load_dotenv()
        print("Warning: .env not found in app, loaded from default search path.")
```

配置类定义：

```python
import os
from .env_loader import load_env

load_env()

class SettingConfig(object):
    # API Keys & URLs
    SF_API_KEY = os.getenv("SF_API_KEY")
    SF_BASE_URL = os.getenv("SF_BASE_URL")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
    AL_BAILIAN_API_KEY = os.getenv("AL_BAILIAN_API_KEY")
    AL_BAILIAN_BASE_URL = os.getenv("AL_BAILIAN_BASE_URL")

    # Model Names
    OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME")
    SF_MODEL_NAME = os.getenv("SF_MODEL_NAME")
    MAIN_MODEL_NAME = os.getenv("MAIN_MODEL_NAME")
    SUB_MODEL_NAME = os.getenv("SUB_MODEL_NAME")
    
    MAIN_MODEL_NAME_LIST = os.getenv("MAIN_MODEL_NAME_LIST", "").split(",")
    SUB_MODEL_NAME_LIST = os.getenv("SUB_MODEL_NAME_LIST", "").split(",")

    # Database
    MYSQL_HOST = os.getenv("MYSQL_HOST")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
    MYSQL_USER = os.getenv("MYSQL_USER")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")
    MYSQL_CHARSET = os.getenv("MYSQL_CHARSET", "utf8mb4")
    MYSQL_CONNECT_TIMEOUT = int(os.getenv("MYSQL_CONNECT_TIMEOUT", 10))
    MYSQL_MAX_CONNECTIONS = int(os.getenv("MYSQL_MAX_CONNECTIONS", 5))


setting_config = SettingConfig()
```



#### 5.2 数据库连接池

数据库是存储用户会话和记忆的关键组件，我们使用连接池管理数据库连接，提高性能和可靠性。

##### 1. 目标

创建高效的数据库连接池，支持用户会话和记忆的持久化存储，确保系统在高并发下的稳定性。

**模块位置**: `backend/app/infrastructure/database.py`

##### 2. 需求分析

1. **连接池的必要性**
   - **性能**：避免每次查询都建立新连接
   - **可靠性**：管理连接生命周期，防止连接泄漏
   - **可配置性**：支持最大连接数、超时时间等参数调整
2. **数据库设计考虑**
   - **会话存储**：存储用户的多轮对话历史
   - **记忆管理**：支持按会话ID隔离不同对话的记忆
   - **性能优化**：合理的索引设计和查询优化
3. **错误处理**
   - 连接失败时的重试机制
   - 查询超时时的优雅降级
   - 连接泄漏的预防和检测

##### 3. 实现流程

1. **连接池初始化**
   - 读取数据库配置参数
   - 创建`PooledDB`连接池实例
2. **连接管理**
   - 提供统一的连接获取接口
   - 确保使用后连接正确归还到连接池
3. **查询封装**
   - 封装常用的数据库操作
   - 提供参数化查询，防止SQL注入

##### 4. 代码实现

```python
import pymysql
from dbutils.pooled_db import PooledDB
from backend.app.config.settings import setting_config

class DatabasePool:
    _pool = None

    @classmethod
    def get_pool(cls):
        if cls._pool is None:
            cls._pool = PooledDB(
                creator=pymysql,
                maxconnections=setting_config.MYSQL_MAX_CONNECTIONS,
                host=setting_config.MYSQL_HOST,
                user=setting_config.MYSQL_USER,
                password=setting_config.MYSQL_PASSWORD,
                port=setting_config.MYSQL_PORT,
                database=setting_config.MYSQL_DATABASE,
                charset=setting_config.MYSQL_CHARSET,
                connect_timeout=setting_config.MYSQL_CONNECT_TIMEOUT
            )
        return cls._pool

    @classmethod
    def get_connection(cls):
        return cls.get_pool().connection()

# Initialize pool on import if needed, or just provide access
pool = DatabasePool.get_pool()
```





####  5.3 构建模型大脑

Model Client模型客户端是智能体躯干的"大脑"，负责提供思维和推理能力。我们设计为支持多模型服务商，以便根据需求灵活切换。

**模块位置**: `backend/app/infrastructure/clients/client_utils.py`

##### 1.目标

创建可配置、可扩展的模型客户端，支持多个模型服务商（如阿里云百炼、硅基流动、OpenAI等），并为不同智能体分配适合的模型。

##### 2.需求分析

1. **为什么要支持多模型？**

   - **成本控制**：调度智能体使用轻量模型，降低推理成本
   - **性能优化**：技术/业务智能体使用主力模型，保证回答质量
   - **灵活切换**：可根据场景选择不同服务商的模型，避免单点故障
   - **功能适配**：不同模型在推理、代码生成、中文理解等方面各有所长

2. **如何管理多个模型的配置？**

   - **环境变量管理**：通过.env文件集中管理API密钥和Base URL
   - **统一客户端**：使用标准化的AsyncOpenAI客户端，兼容OpenAI API标准
   - **配置集中化**：将模型配置统一到`settings.py`，便于维护和更新
   - **多模型列表**：支持配置多个主力模型和轻量模型，实现负载均衡

3. **模型分配策略**

   - **主力模型（main_model）**：处理复杂的技术问题和业务逻辑，需要较强的推理能力
   - **轻量模型（sub_model）**：用于调度智能体的意图判断和任务分发，响应快且成本低
   - **模型列表**：可配置多个模型实例，实现简单的故障转移

   

##### 3.实现流程

当系统启动时，模型客户端的构建流程如下：

1. **环境配置加载**

   - 调用`load_env()`函数从.env文件加载环境变量
   - 通过`SettingConfig`类读取所有模型相关配置
   - 验证关键配置项是否存在（如API密钥、Base URL）

2. **客户端实例化**

   - 为主力模型创建`AsyncOpenAI`客户端，连接到阿里云百炼或其他主力模型服务
   - 为轻量模型创建`AsyncOpenAI`客户端，连接到硅基流动或其他轻量模型服务
   - 配置超时、重试等连接参数

3. **模型包装**

   - 使用`OpenAIChatCompletionsModel`将客户端包装为Agent SDK可用的模型格式
   - 为主力模型和轻量模型分别创建模型实例
   - 配置默认的模型参数（如temperature、max_tokens等）

4. **模型注册与使用**

   - 在智能体定义时，通过`model`参数指定使用的模型实例
   - 调度智能体使用`sub_model`，子智能体使用`main_model`
   - 支持动态切换模型（通过配置不同的模型名称）

   

##### 4.代码实现

```python
import os
from dotenv import load_dotenv
from agents import OpenAIChatCompletionsModel
from openai import AsyncOpenAI
from backend.app.config.settings import setting_config

# 加载配置项
OPENAI_API_KEY = setting_config.OPENAI_API_KEY
OPENAI_BASE_URL = setting_config.OPENAI_BASE_URL

SF_API_KEY = setting_config.SF_API_KEY
SF_BASE_URL = setting_config.SF_BASE_URL
SUB_MODEL_NAME = setting_config.SUB_MODEL_NAME

AL_BAILIAN_API_KEY = setting_config.AL_BAILIAN_API_KEY
AL_BAILIAN_BASE_URL = setting_config.AL_BAILIAN_BASE_URL
MAIN_MODEL_NAME = setting_config.MAIN_MODEL_NAME

# 创建模型客户端

# 主模型客户端 - 连接到阿里云百炼（Qwen）
main_model_client = AsyncOpenAI(
    base_url=AL_BAILIAN_BASE_URL, 
    api_key=AL_BAILIAN_API_KEY
)

# 子模型客户端 - 连接到硅基流动（DeepSeek）
sub_model_client = AsyncOpenAI(
    base_url=SF_BASE_URL,  # 硅基流动base url
    api_key=SF_API_KEY     # 硅基流动api key
)

# 创建主调度模型
main_model = OpenAIChatCompletionsModel(
    model=MAIN_MODEL_NAME,
    openai_client=main_model_client)

sub_model = OpenAIChatCompletionsModel(
    model=SUB_MODEL_NAME,
    openai_client=sub_model_client)
```



#### 5.3  构建模型双手

智能体本身无法直接查询数据库或调用外部API，我们需要编写Python函数并用`@function_tool`装饰器封装，使其成为Agent可调用的工具。这些工具就像智能体的"双手"，能够执行具体的操作。

##### 1. 目标

创建一系列功能工具，使智能体能够与外部系统交互，包括知识库查询、地理位置解析、服务站查询等，扩展智能体的实际能力边界。

**模块位置**:

- `backend/app/infrastructure/tools/knowledge_tools.py`
- `backend/app/infrastructure/tools/map_tools.py`
- `backend/app/infrastructure/tools/service_station_tools.py`



##### 2.需求分析

1. **工具的分类与职责**

   - **知识库工具**：查询私域知识库，获取技术问题的标准答案
   - **地图工具**：地理编码、坐标转换等基础地图功能
   - **服务站工具**：查询附近的维修服务站、解析用户位置等业务功能
   - **工具分层**：基础工具提供原子操作，业务工具组合基础工具完成复杂任务

2. **工具设计原则**

   - **单一职责原则**：每个工具只完成一个明确的功能
   - **友好错误处理**：捕获异常并返回结构化的错误信息，避免智能体困惑
   - **类型安全**：使用Python类型注解明确参数和返回类型，提供清晰的接口
   - **异步支持**：所有工具函数都是异步的，避免阻塞主线程
   - **文档完整**：每个工具都有详细的docstring，说明功能、参数和返回值

3. **工具调用规范**

   - **参数验证**：在函数内部验证输入参数的合法性，提供友好的错误提示
   - **结果标准化**：返回统一格式的JSON数据，便于智能体解析和后续处理
   - **日志记录**：记录工具调用的关键信息，便于调试和监控
   - **超时控制**：为外部API调用设置合理的超时时间，避免长时间等待

   

##### 3.实现流程

工具的开发和使用遵循以下流程：

1. **工具函数定义**
   - 编写普通Python异步函数，实现具体的功能逻辑
   - 使用`@function_tool`装饰器标记函数为Agent工具
   - 添加详细的文档字符串，说明工具的功能、参数、返回值和使用示例
2. **工具集成到智能体**
   - 在智能体定义时通过`tools`参数注册工具列表
   - 确保工具的函数签名与智能体的调用方式匹配
   - 工具按照使用频率和关联性进行合理分组
3. **工具测试与验证**
   - 编写独立的测试用例验证工具功能
   - 模拟异常情况（网络超时、参数错误、服务不可用等）
   - 确保错误处理机制正常工作，返回结构化的错误信息
4. **工具优化与维护**
   - 监控工具的使用频率和性能指标
   - 根据实际使用情况优化工具的实现
   - 定期更新工具以适应外部API的变化



##### 4.代码实现

以知识库查询工具为例：

```python
import httpx
from typing import Optional
from agents import function_tool
from backend.app.config.settings import setting_config
KNOWLEDGE_BASE_URL = setting_config.KNOWLEDGE_BASE_URL
from backend.app.infrastructure.logger import logger

@function_tool
async def query_knowledge(
        question: Optional[str] = None
) -> dict:
    """
    查询电脑问题知识库服务
    
    该工具用于查询私域知识库中的技术问题解决方案。当用户询问技术问题时，
    智能体应优先使用此工具获取权威答案。
    
    参数:
    - question: 用户的技术问题，如"电脑蓝屏怎么办"
    
    返回:
    - 包含查询结果的字典，结构为：
      {
        "answer": "具体解答内容",  # 知识库返回的答案
        "source": "知识库",        # 答案来源标识
        "confidence": 0.95         # 答案置信度（可选）
      }
      或错误时返回：
      {
        "error": "错误描述",
        "fallback": "建议用户重新提问或联系人工客服"
      }
    
    示例:
    >>> await query_knowledge("如何安装Windows系统")
    {
        "answer": "安装Windows系统的步骤包括：1. 准备安装U盘...",
        "source": "知识库",
        "confidence": 0.98
    }
    """
    async with httpx.AsyncClient() as client:
        try:
            # 发送请求到知识库服务
            response = await client.post(
                f"{KNOWLEDGE_BASE_URL}/query",
                json={"question": question},
                timeout=120.0  # 设置2分钟超时
            )
            response.raise_for_status()  # 检查HTTP状态码
            
            # 解析并返回结果
            result = response.json()
            return {
                "answer": result.get("content", ""),
                "source": "知识库",
                "confidence": result.get("confidence", 0.9)
            }
            
        except httpx.HTTPError as e:
            # HTTP错误处理
            logger.error(f"知识库工具HTTP错误: {str(e)}")
            return {
                "error": f"知识库服务暂时不可用: {str(e)}",
                "fallback": "请尝试重新提问或联系人工客服"
            }
        except Exception as e:
            # 其他异常处理
            logger.error(f"知识库工具未知错误: {str(e)}")
            return {
                "error": f"知识库查询失败: {str(e)}",
                "fallback": "请尝试重新提问或联系人工客服"
            }
```



服务站查询工具示例：

**逻辑分析：**

1. 从连接池获取数据库连接。

2. 执行 SQL 查询（使用 Haversine 公式计算距离）。

3. 返回包含服务站信息的 JSON 数据。

```python
@function_tool
def query_nearest_repair_shops_by_coords(lat: float, lng: float, limit: int = 5) -> str:
    """
    根据给定的经纬度坐标，查询数据库中最近的维修站/服务站。
    
    注意：此工具仅用于查询官方授权服务站，不得用于普通POI查询。
    
    Args:
        lat (float): 纬度 (BD09LL坐标系)
        lng (float): 经度 (BD09LL坐标系)
        limit (int): 返回结果数量限制，默认为5
        
    Returns:
        str: JSON格式的查询结果，包含最近的维修站列表。
        成功时返回：
        {
            "ok": true,
            "count": 3,
            "data": [
                {
                    "service_station_name": "小米之家(光谷店)",
                    "address": "武汉市洪山区光谷广场",
                    "phone": "027-88888888",
                    "distance_km": 1.5,
                    "latitude": 30.505,
                    "longitude": 114.404
                }
            ]
        }
        失败时返回：
        {
            "ok": false,
            "error": "错误描述"
        }
    """
    connection = None
    cursor = None
    try:
        # 获取数据库连接
        connection = pool.connection()
        cursor = connection.cursor(DictCursor)

        # 使用Haversine公式计算距离
        sql = """
        SELECT
            service_station_name,
            address,
            phone,
            latitude,
            longitude,
            (
                6371 * acos(
                    cos(radians(%s)) *
                    cos(radians(latitude)) *
                    cos(radians(longitude) - radians(%s)) +
                    sin(radians(%s)) *
                    sin(radians(latitude))
                )
            ) AS distance_km
        FROM repair_shops
        WHERE 
            latitude IS NOT NULL 
            AND longitude IS NOT NULL
        ORDER BY distance_km ASC
        LIMIT %s
        """
        cursor.execute(sql, (lat, lng, lat, limit))
        rows = cursor.fetchall()

        logger.info(f"[NearestShops] 找到 {len(rows)} 个服务站，坐标 ({lat}, {lng})")

        return json.dumps({
            "ok": True,
            "count": len(rows),
            "data": rows,
            "query": {"lat": lat, "lng": lng, "limit": limit}
        }, ensure_ascii=False, default=str)

    except Exception as e:
        logger.error(f"[NearestShops] 数据库查询失败: {e}", exc_info=True)
        return json.dumps({
            "ok": False,
            "error": f"数据库查询失败: {str(e)}",
            "query": {"lat": lat, "lng": lng, "limit": limit}
        }, ensure_ascii=False)
    finally:
        # 确保资源释放
        if cursor:
            cursor.close()
        if connection:
            connection.close()
```



  **逻辑分析：**

1. 尝试调用百度地图 MCP 的 Geocode API 解析地址。

2. 如果失败，尝试使用 IP 定位。

3. 如果都失败，返回默认坐标（兜底策略）。

4. 最终返回标准化的 JSON 字符串。

```python
@function_tool
async def resolve_user_location_from_text(
    user_input: str,
    user_ip: str = "192.168.1.4"
) -> str:
    """
    智能解析用户当前位置（起点），用于导航或服务站查询。

    ✅ 适用场景：
    - 用户说“我在武汉”、“从当前位置出发”等；
    - 无明确位置时，通过 user_ip 地址兜底定位。
    ⚠️ 注意：
    - 返回坐标为 BD09LL（百度经纬度）；
    - 仅用于获取**起点**，不可作为终点使用。
    
    - 最终兜底返回北京坐标 (39.9042, 116.4074)。

    Args:
        user_input (str): 用户输入的位置描述（可选）
        user_ip (str): 用户 IP 地址（用于兜底定位）
    
    返回 JSON 字符串：
    {
        "ok": bool,
        "lat": float,
        "lng": float,
        "source": "geocode" | "ip" | "fallback",
        "original_input": str,
        "error": str?  # 仅当 ok=False 时存在
    }
    """
    original_input = user_input
    user_input = user_input.strip() if user_input else ""

    # === Step 1: 尝试 Geocode ===
    if user_input:
        try:
            logger.debug(f"[Location] Trying geocode for: '{user_input}'")
            geo_result = await baidu_map_mcp.call_tool(tool_name="map_geocode", arguments={"address": user_input})
            text = geo_result.content[0].text
            text=json.loads(text)
            result=text['result']
            if isinstance(result, dict) and "lat" in result['location'] and "lng" in result['location']:
                lat = float(result['location']['lat'])
                lng = float(result['location']['lng'])
                logger.info(f"[Location] Geocode success: '{user_input}' → ({lat}, {lng})")
                return json.dumps({
                    "ok": True,
                    "lat": lat,
                    "lng": lng,
                    "source": "geocode",
                    "original_input": original_input
                }, ensure_ascii=False)
            else:
                logger.warning(f"[Location] Geocode returned invalid result: {geo_result}")
        except Exception as e:
            logger.warning(f"[Location] Geocode failed for '{user_input}': {e}")

    # === Step 2: 尝试 IP 定位 ===
    if user_ip and user_ip not in ("127.0.0.1", "localhost", "::1"):
        try:
            logger.debug(f"[Location] Trying IP location for: {user_ip}")
            ip_result = await baidu_map_mcp.call_tool("map_ip_location", {"ip": user_ip})
        
            # 解析 MCP 返回的 TextContent
            text = ip_result.content[0].text
            data = json.loads(text)
        
            # 检查状态
            if data.get("status") != 0:
                logger.warning(f"[Location] IP location API error: {data.get('message', 'unknown')}")
                raise ValueError("IP location API returned non-zero status")
        
            point = data.get("content", {}).get("point", {})
            x_str = point.get("x")
            y_str = point.get("y")
        
            if not x_str or not y_str:
                logger.warning(f"[Location] Missing x/y in IP location result: {data}")
                raise ValueError("Missing x/y coordinates")
        
            # 转换墨卡托 → 经纬度
            x = float(x_str)
            y = float(y_str)
            lng, lat = bd09mc_to_bd09(x, y)  # 注意顺序：返回 (lng, lat)
            
            logger.info(f"[Location] IP location success: {user_ip} → ({lat:.6f}, {lng:.6f})")
            return json.dumps({
            "ok": True,
            "lat": lat,
            "lng": lng,
            "source": "ip",
            "original_input": original_input
        }, ensure_ascii=False)
        
        except Exception as e:
            logger.warning(f"[Location] IP location failed for {user_ip}: {e}")    
    

    # === Step 3: 兜底 ===
    fallback_lat, fallback_lng = 39.9042, 116.4074
    logger.info("[Location] Using fallback coordinates (Beijing)")
    return json.dumps({
        "ok": False,
        "error": "无法解析用户位置，使用默认坐标",
        "lat": fallback_lat,
        "lng": fallback_lng,
        "source": "fallback",
        "original_input": original_input
    }, ensure_ascii=False)


```





#### 5.5  连接模型感官

MCP（Model Context Protocol）允许智能体连接外部数据源和工具，扩展其感知能力。我们通过MCP服务器集成搜索和地图服务，就像为智能体添加了"眼睛"和"耳朵"。



##### 1.目标

通过MCP协议为智能体提供外部能力，包括联网搜索和百度地图服务，使其能够获取实时信息和地理位置数据，突破大语言模型的知识和时间限制。

**模块位置**:

- `backend/app/infrastructure/mcp/servers.py`
- `backend/app/infrastructure/mcp/manager.py`



##### 2.需求分析

1. **MCP服务器的选择与设计**

   - **搜索MCP**：提供联网搜索能力，获取实时信息（新闻、股价、天气等）以及公域技术问题
   - **地图MCP**：提供地图相关功能，如地点搜索、路径规划、周边查询等
   - **协议兼容**：选择支持SSE（Server-Sent Events）的MCP服务器，实现实时数据流
   - **服务稳定**：选择可靠的第三方服务商，确保服务的高可用性

2. **MCP连接管理与优化**

   - **连接池管理**：管理MCP服务器的连接，避免频繁建立连接的开销
   - **错误处理与重试**：处理连接失败、超时等异常情况，可以选择优雅降级
   - **资源生命周期管理**：在应用启动和关闭时正确初始化和清理连接
   - **超时控制**：为不同操作设置合理的超时时间，避免长时间阻塞

3. **MCP工具发现与使用**

   - **工具自动发现**：MCP服务器启动时自动发现可用的工具列表
   - **工具缓存机制**：缓存MCP服务器的工具列表，提高系统性能
   - **工具映射与别名**：将MCP工具名映射为中文或更友好的名称，便于前端展示
   - **工具权限控制**：根据需要控制智能体对MCP工具的访问权限

   

##### 3.实现流程

MCP服务器的集成和使用遵循以下流程：

1. **MCP服务器配置**

   - 从环境变量读取MCP服务器的URL和认证信息
   - 根据服务商要求配置请求头、超时时间等参数
   - 创建`MCPServerSse`实例，配置连接参数和缓存策略

2. **MCP连接管理**

   - 在应用启动时（`lifespan`）建立MCP连接
   - 在智能体运行期间保持连接活跃，定期发送心跳包
   - 在应用关闭时正确清理连接，释放资源
   - 监控连接状态，实现自动重连机制

3. **MCP工具集成与使用**

   - 将MCP服务器添加到智能体的`mcp_servers`列表中
   - 智能体运行时自动发现和调用MCP提供的工具
   - 在流式处理器中处理MCP工具调用事件，提供用户友好的展示

4. **MCP工具映射与优化**

   - 创建工具名称映射表，将技术性工具名映射为业务术语
   - 在前端展示时使用友好的中文名称
   - 根据使用频率优化工具调用顺序

   

##### 4.代码实现

MCP服务器配置（`servers.py`）：

```python
from agents.mcp import MCPServerSse
from backend.app.config.settings import setting_config

# 1. 通用网络资源检索 MCP - 连接到达摩院DashScope
search_url = setting_config.DASHSCOPE_BASE_URL
search_api_key = setting_config.DASHSCOPE_API_KEY

search_mcp = MCPServerSse(
    name="general_web_search_mcp",
    params={
        "url": search_url,
        "headers": {"Authorization": f"Bearer {search_api_key}"},
        "timeout": 60,  # 连接超时时间
        "sse_read_timeout": 300,  # SSE读取超时时间
    },
    client_session_timeout_seconds=60,  # 客户端会话超时
    cache_tools_list=True,  # 缓存工具列表，提高性能
)

# 2. 百度地图 MCP - 连接百度地图开放平台
baidu_ak = setting_config.BAIDUMAP_AK
baidu_map_mcp = MCPServerSse(
    name="baidu_map_mcp",
    params={
        "url": f"https://mcp.map.baidu.com/sse?ak={baidu_ak}",
        "timeout": 60,
        "sse_read_timeout": 300
    },
    client_session_timeout_seconds=60,
    cache_tools_list=True,
)

# 导出所有MCP服务器列表
all_mcp_servers = [
    search_mcp,
    baidu_map_mcp
]
```

MCP连接管理器（`manager.py`）：

```python
from backend.app.infrastructure.logger import logger
from backend.app.infrastructure.mcp.servers import (
    baidu_map_mcp,
    search_mcp,
)

async def mcp_connect():
    """
    建立所有MCP服务器的连接
    
    在FastAPI应用启动时调用，初始化所有MCP连接。
    每个MCP连接独立处理，一个连接失败不影响其他连接。
    """
    logger.info("开始建立MCP服务器连接...")
    
    # 建立百度地图MCP连接
    try:
        await baidu_map_mcp.connect()
        logger.info(" 百度地图MCP连接成功")
    except Exception as e:
        logger.error(f"百度地图MCP连接失败: {str(e)}")
        # 记录详细异常信息，但不中断应用启动
        logger.debug(f"百度地图MCP连接异常详情: {traceback.format_exc()}")
    
    # 建立搜索MCP连接
    try:
        await search_mcp.connect()
        logger.info("搜索MCP连接成功")
    except Exception as e:
        logger.error(f" 搜索MCP连接失败: {str(e)}")
        logger.debug(f"搜索MCP连接异常详情: {traceback.format_exc()}")
    
    logger.info("MCP服务器连接建立完成")


async def mcp_cleanup():
    """
    清理所有MCP服务器的连接
    
    在FastAPI应用关闭时调用，优雅地关闭所有MCP连接。
    即使某个连接关闭失败，也不影响其他连接的关闭。
    """
    logger.info("开始清理MCP服务器连接...")
    
    # 清理百度地图MCP连接
    try:
        await baidu_map_mcp.cleanup()
        logger.info(" 百度地图MCP连接清理成功")
    except Exception as e:
        logger.warning(f"百度地图MCP连接清理异常: {str(e)}")
    
    # 清理搜索MCP连接
    try:
        await search_mcp.cleanup()
        logger.info(" 搜索MCP连接清理成功")
    except Exception as e:
        logger.warning(f"搜索MCP连接清理异常: {str(e)}")
    
    logger.info("MCP服务器连接清理完成")
```

FastAPI生命周期管理（`main.py`）：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI应用生命周期管理
    
    在应用启动时建立MCP连接，在应用关闭时清理连接。
    确保资源正确初始化和释放。
    """
    # 应用启动时执行
    logger.info("应用启动，建立MCP连接...")
    try:
        await mcp_connect()
        logger.info("MCP连接建立完成")
    except Exception as e:
        logger.error(f"MCP连接建立失败: {str(e)}")
    
    yield  # 应用运行期间
    
    # 应用关闭时执行
    logger.info("应用关闭，清理MCP连接...")
    try:
        await mcp_cleanup()
        logger.info("MCP连接清理完成")
    except Exception as e:
        logger.error(f"MCP连接清理失败: {str(e)}")
```



#### 5.6 构建基础设施总结

通过基础设施构建，我们为智能体系统搭建了完整的支持体系：

1. **模型大脑**：多模型客户端支持，灵活分配推理能力
2. **工具双手**：丰富的功能工具集，扩展智能体能力边界
3. **MCP感官**：连接外部数据源，获取实时信息和地理位置
4. **配置管理**：统一的环境配置，支持多环境部署
5. **数据持久化**：高效的数据库连接池

这些基础设施共同构成了智能体系统的坚实基座，使得上层的智能体能够专注于任务处理，而不必关心底层的技术细节。在后续章节中，我们将基于这些基础设施实现智能体的协同工作和流式响应。





