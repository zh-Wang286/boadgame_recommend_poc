"""
桌游模型模块，定义桌游数据模型。

该模块定义了桌游表的结构和关系。
"""
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base_class import Base

# 桌游状态常量
BOARD_GAME_STATUS = {
    "PENDING": "pending",  # 待审核
    "APPROVED": "approved",  # 已批准
    "REJECTED": "rejected"  # 已拒绝
}


class BoardGame(Base):
    """
    桌游模型，对应数据库中的 board_games 表。
    
    存储桌游的基本信息，包括名称、描述、玩家人数、游戏时长、配件列表、教程链接等。
    """
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    description = Column(Text, nullable=True)
    min_players = Column(Integer, nullable=True)
    max_players = Column(Integer, nullable=True)
    play_time_min = Column(Integer, nullable=True)
    play_time_max = Column(Integer, nullable=True)
    complexity = Column(Float, nullable=True)
    image_url = Column(String(255), nullable=True)
    accessories = Column(Text, nullable=True)  # 配件列表，支持markdown格式
    tutorials = Column(Text, nullable=True)  # 教程URL链接，以JSON格式存储
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    status = Column(String(20), nullable=False, default=BOARD_GAME_STATUS["PENDING"])
    
    # 关系定义
    creator = relationship("User", back_populates="board_games")
    categories = relationship("BoardGameCategory", back_populates="board_game")
    tags = relationship("BoardGameTag", back_populates="board_game")
    favorites = relationship("Favorite", back_populates="board_game")
    reviews = relationship("BoardGameReview", back_populates="board_game")
    changes = relationship("BoardGameChange", back_populates="board_game")
