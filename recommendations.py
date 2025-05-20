"""
桌游推荐API模块，提供基于LLM的桌游推荐功能。

该模块使用OpenAI API来处理用户输入的喜好，并返回推荐的桌游列表。
"""
import logging
from typing import List, Optional
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.session import get_db
from app import crud, schemas
from app.core.config import settings
from app.models.board_game import BoardGame as BoardGameModel

from openai import OpenAI
import chromadb
from chromadb.utils import embedding_functions


# 创建路由器
router = APIRouter()

# 定义请求模型
class RecommendationRequest(BaseModel):
    """用户推荐请求模型"""
    preference: str
    limit: Optional[int] = 5
    # Optional: number of documents to retrieve from ChromaDB
    retrieval_limit: Optional[int] = 10

# 定义LLM响应模型 (用于内部 parsing)
class LLMRecommendation(BaseModel):
    recommended_game_names: List[str]
    explanation: str

# 定义响应模型
class RecommendationResponse(BaseModel):
    """推荐响应模型"""
    recommendations: List[schemas.BoardGame]
    explanation: str

# 创建OpenAI客户端
def get_openai_client():
    """
    获取OpenAI客户端实例。
    
    Returns:
        OpenAI: OpenAI客户端实例
    """
    if not settings.OPENAI_API_KEY:
        logging.error("未配置OpenAI API密钥")
        raise HTTPException(status_code=500, detail="服务器未正确配置OpenAI API")
    
    return OpenAI(
        base_url=settings.OPENAI_BASE_URL, 
        api_key=settings.OPENAI_API_KEY,
    )

# ChromaDB Client and Collection
def get_chroma_collection():
    """
    Initializes and returns a ChromaDB collection for board games.
    Assumes settings like CHROMA_PERSIST_PATH, CHROMA_COLLECTION_NAME,
    and OPENAI_EMBEDDING_MODEL_NAME are defined in app.core.config.settings.
    """
    try:
        if hasattr(settings, 'CHROMA_PERSIST_PATH') and settings.CHROMA_PERSIST_PATH:
            chroma_client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_PATH)
        else:
            logging.warning("CHROMA_PERSIST_PATH not set, using in-memory ChromaDB client.")
            chroma_client = chromadb.Client()


        openai_ef = embedding_functions.OpenAIEmbeddingFunction(
            api_key=settings.OPENAI_API_KEY,
            model_name=getattr(settings, 'OPENAI_EMBEDDING_MODEL_NAME', "text-embedding-ada-002") # Default if not set
        )
        
        collection_name = getattr(settings, 'CHROMA_COLLECTION_NAME', "board_games_collection") # Default if not set
        
        collection = chroma_client.get_or_create_collection(
            name=collection_name,
            embedding_function=openai_ef
        )
        return collection
    except Exception as e:
        logging.error(f"Failed to initialize ChromaDB collection: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error connecting to vector database.")


@router.post("", response_model=RecommendationResponse)
async def recommend_board_games(
    request: RecommendationRequest,
    db: Session = Depends(get_db)
):
    """
    基于用户喜好通过RAG推荐桌游。
    
    首先从ChromaDB检索相关桌游，然后使用OpenAI LLM生成推荐。
    
    Args:
        request: 包含用户喜好的请求对象
        db: 数据库会话
        
    Returns:
        RecommendationResponse: 推荐的桌游列表和解释
    """
    logging.info(f"收到RAG推荐请求: {request.preference}, limit: {request.limit}, retrieval_limit: {request.retrieval_limit}")
    
    try:
        # 1. Get ChromaDB collection
        chroma_collection = get_chroma_collection()
        
        # 2. Query ChromaDB for relevant board games
        retrieval_limit = request.retrieval_limit if request.retrieval_limit <= 20 else 20 # Cap retrieval for context window
        logging.info(f"Querying ChromaDB with preference: '{request.preference}', n_results={retrieval_limit}")
        
        chroma_results = chroma_collection.query(
            query_texts=[request.preference],
            n_results=retrieval_limit,
            include=['metadatas'] 
        )
        
        # 3. Format retrieved documents for the LLM prompt
        context_games_str = ""
        if chroma_results and chroma_results['metadatas'] and chroma_results['metadatas'][0]:
            context_list = []
            for i, meta in enumerate(chroma_results['metadatas'][0]):
                game_info = (
                    f"{i+1}. 名称: {meta.get('name', '未知')}\n"
                    f"   描述: {meta.get('description', '无')}\n"
                    f"   玩家人数: {meta.get('min_players', '?')}-{meta.get('max_players', '?')}\n"
                    f"   游戏时长: {meta.get('play_time_min', '?')}-{meta.get('play_time_max', '?')} 分钟\n"
                    f"   复杂度: {meta.get('complexity', '?')}"
                )
                context_list.append(game_info)
            context_games_str = "\n\n".join(context_list)
            logging.info(f"Context for LLM:\n{context_games_str}")
        else:
            context_games_str = "数据库中没有找到与用户偏好紧密匹配的桌游。请根据普遍知识进行推荐。"
            logging.info("No relevant games found in ChromaDB for the query.")

        # 4. Build the prompt for OpenAI LLM
        prompt = f"""
        作为一位资深的桌游推荐专家，请根据用户的喜好和我们数据库中可能相关的桌游列表，推荐 {request.limit} 款最适合的桌游。

        用户喜好: "{request.preference}"

        数据库中检索到的可能相关的桌游信息如下 (如果列表为空，请基于用户喜好和您的广泛知识进行推荐):
        --- BEGIN CONTEXT GAMES ---
        {context_games_str}
        --- END CONTEXT GAMES ---

        请仔细分析用户喜好和提供的游戏信息。你的任务是:
        1. 从提供的游戏列表 (如果适用) 或你的知识库中，挑选出最多 {request.limit} 款最符合用户喜好的桌游。
        2. 对每个推荐的桌游，请确保它真实存在。
        3. 提供一个整体的解释，说明为什么这些桌游适合该用户。

        请以JSON格式返回你的推荐，必须包含以下两个字段:
        - "recommended_game_names": 一个包含推荐桌游准确名称的列表 (例如: ["卡坦岛", "七大奇迹"])。
        - "explanation": 一段详细的中文解释，说明这些游戏为什么被推荐，它们如何满足用户的偏好。

        重要提示:
        - 如果提供的上下文中没有合适的游戏，可以从你的知识库中推荐。
        - 确保推荐的游戏名称是准确且常见的中文名称。
        - 返回的JSON必须严格符合上述结构。
        """
        
        # 5. Call OpenAI API
        client = get_openai_client()
        logging.info("Sending request to OpenAI LLM...")
        
        try:
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL_NAME,
                messages=[
                    {"role": "system", "content": "你是一位资深的桌游推荐专家。请根据用户偏好和提供的上下文信息，推荐桌游，并以指定的JSON格式返回结果。"},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )
            llm_response_content = response.choices[0].message.content
            logging.info(f"LLM raw response: {llm_response_content}")
        except Exception as e:
            logging.error(f"OpenAI API call failed: {str(e)}", exc_info=True)
            raise HTTPException(status_code=503, detail=f"LLM service error: {str(e)}")

        # 6. Parse LLM JSON Response
        try:
            llm_recommendation_data = json.loads(llm_response_content)
            llm_recommendation = LLMRecommendation(**llm_recommendation_data)
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse LLM JSON response: {str(e)}. Response: {llm_response_content}", exc_info=True)
            raise HTTPException(status_code=500, detail="Error parsing recommendations from LLM.")
        except Exception as e: # Catches Pydantic validation errors too
            logging.error(f"Invalid LLM response structure: {str(e)}. Response: {llm_response_content}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Invalid recommendation format from LLM: {str(e)}")

        recommended_game_names = llm_recommendation.recommended_game_names
        explanation = llm_recommendation.explanation
        
        logging.info(f"LLM recommended game names: {recommended_game_names}")
        logging.info(f"LLM explanation: {explanation}")

        # 7. Fetch full BoardGame objects from main DB
        recommended_games_from_db: List[schemas.BoardGame] = []
        if recommended_game_names:
            for name in recommended_game_names:
                # game_obj will be type hinted in the next step
                game_obj: Optional[BoardGameModel] = crud.board_game.get_by_name(db=db, name=name)
                if game_obj:
                    recommended_games_from_db.append(schemas.BoardGame.from_orm(game_obj)) 
                else:
                    logging.warning(f"Board game '{name}' recommended by LLM not found in the main database.")
        
        # 8. Return response
        return RecommendationResponse(
            recommendations=recommended_games_from_db,
            explanation=explanation
        )
        
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logging.error(f"RAG推荐过程中发生未知错误: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"推荐过程中发生内部错误: {str(e)}")
