# 桌游推荐系统 - 功能说明

本文档主要介绍桌游推荐系统的核心功能，重点描述数据模型和推荐API的工作方式。

## 1. 项目概览

本项目旨在提供一个基于用户偏好的智能桌游推荐服务。它利用了检索增强生成（RAG）技术，结合向量数据库（ChromaDB）和大型语言模型（OpenAI GPT）来提供高质量的桌游推荐。

## 2. 核心模块

### 2.1. 桌游数据模型 (`src/backend/app/models/board_game.py`)

此模块定义了桌游在关系型数据库中的核心数据结构。`BoardGame`模型包含了桌游的详细信息。

**主要字段包括：**

*   `id`: 桌游的唯一标识符 (Integer, 主键)
*   `name`: 桌游名称 (String, 必填)
*   `description`: 桌游描述 (Text)
*   `min_players`: 最少玩家人数 (Integer)
*   `max_players`: 最多玩家人数 (Integer)
*   `play_time_min`: 最短游戏时长 (分钟, Integer)
*   `play_time_max`: 最长游戏时长 (分钟, Integer)
*   `complexity`: 游戏复杂度评分 (Float)
*   `image_url`: 桌游图片链接 (String)
*   `accessories`: 配件列表 (Text, 支持Markdown)
*   `tutorials`: 教程链接 (Text, JSON格式)
*   `status`: 桌游状态 (例如: "pending", "approved")
*   `created_by`: 创建者用户ID (ForeignKey)
*   以及相关的关系字段如 `creator`, `categories`, `tags`, `favorites`, `reviews`, `changes`。

### 2.2. 桌游推荐API (`src/backend/app/api/endpoints/recommendations.py`)

此模块提供了基于RAG的桌游推荐API端点。它处理用户输入的偏好，并通过以下步骤生成推荐：

1.  **接收用户请求**：用户提供偏好描述、期望的推荐数量等信息。
2.  **信息检索 (Retrieval)**：
    *   使用用户的偏好文本查询ChromaDB向量数据库。
    *   ChromaDB根据语义相似度返回一批相关的桌游元数据（如名称、描述、玩家人数等）。这些元数据是从主数据库同步并生成了向量索引的。
3.  **上下文构建**：将从ChromaDB检索到的桌游信息格式化为一段上下文文本。
4.  **生成 (Generation)**：
    *   将用户的原始偏好和构建的上下文文本一起发送给OpenAI的大型语言模型 (LLM)。
    *   LLM被指示根据这些信息，以JSON格式推荐指定数量的桌游，并提供推荐理由。
5.  **结果处理与返回**：
    *   解析LLM返回的JSON，提取推荐的桌游名称列表和解释。
    *   根据LLM推荐的桌游名称，从主关系型数据库中查询完整的桌游对象信息。
    *   将完整的桌游对象（转换为Pydantic schéma `schemas.BoardGame`）和LLM生成的解释组合成最终的API响应。

## 3. API接口说明

### 端点: `POST /recommendations/`

*   **请求体 (`RecommendationRequest`)**:

    ```json
    {
        "preference": "我喜欢策略类游戏，适合2-4人，不要太复杂，最好能在一个小时内结束。",
        "limit": 3,
        "retrieval_limit": 10
    }
    ```

    *   `preference` (str, 必填): 用户的桌游偏好描述。
    *   `limit` (int, 可选, 默认: 5): 希望LLM最终推荐的桌游数量。
    *   `retrieval_limit` (int, 可选, 默认: 10): 从ChromaDB中检索的用于构建上下文的桌游数量上限（当前代码中硬编码上限为20）。

*   **响应体 (`RecommendationResponse`)**:

    ```json
    {
        "recommendations": [
            {
                "id": 101,
                "name": "卡坦岛",
                "description": "一款经典的资源管理和交易游戏...",
                "min_players": 3,
                "max_players": 4,
                "play_time_min": 60,
                "play_time_max": 90,
                "complexity": 2.33,
                "image_url": "http://example.com/catan.jpg",
                // ... 其他 schemas.BoardGame 中的字段
            }
            // ... 其他推荐的桌游
        ],
        "explanation": "基于您的策略偏好和时长要求，我们推荐了卡坦岛，因为它..."
    }
    ```

    *   `recommendations` (List[`schemas.BoardGame`]): 包含推荐桌游详细信息的列表。每个桌游对象符合`schemas.BoardGame`定义的结构。
    *   `explanation` (str): LLM生成的关于为什么推荐这些桌游的解释。

## 4. 功能依赖假设

为了使推荐系统正常工作，以下组件和数据需要准备就绪：

*   **主数据库 (SQL)**: 包含所有桌游的完整详细信息，其结构由 `app.models.board_game.BoardGame` 定义。
*   **ChromaDB向量数据库**:
    *   需要一个正在运行的ChromaDB实例。
    *   ChromaDB中需要有一个集合（例如："board_games_collection"），其中存储了桌游的向量嵌入（基于名称、描述等文本信息生成）和关键元数据（至少包括`name`, `description`, `min_players`, `max_players`, `play_time_min`, `play_time_max`, `complexity`，用于构建LLM的上下文）。
*   **OpenAI API**:
    *   需要有效的OpenAI API密钥 (`OPENAI_API_KEY`)。
    *   配置OpenAI基础URL (`OPENAI_BASE_URL`，如果使用代理或自定义端点)。
    *   指定用于聊天的模型名称 (`OPENAI_MODEL_NAME`) 和用于生成嵌入的模型名称 (`OPENAI_EMBEDDING_MODEL_NAME`)。

这些配置项通常在 `app.core.config.settings` 中管理。 
