"""
Embedder —— 本地 BGE 句向量编码器
===================================
封装 sentence-transformers 加载本地 bge-base-zh-v1.5 模型，
把文本编码成稠密向量，供 Qdrant 向量检索使用。

为什么单独抽一层：
  - 模型加载慢（首次几秒），全局只加载一次，多处复用。
  - BGE 系列有个**必须做对**的检索细节：
      · query（用户问题）要加指令前缀 "为这个句子生成表示以用于检索相关文章："
      · document（FAQ/商品文本）不加前缀
    做反了召回质量会明显下降。这里用 encode_query / encode_documents 两个方法分开处理，
    调用方不用关心前缀细节。
  - 向量统一做 L2 归一化 → 余弦相似度等价于点积，Qdrant 用 COSINE 距离即可。

模型路径解析顺序：
  1. 环境变量 BGE_MODEL_PATH
  2. 项目内 CustomSystem/models/bge-base-zh-v1.5（自包含，推荐）
  3. 回退到模型名 "BAAI/bge-base-zh-v1.5"（走 HuggingFace 缓存）
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

# BGE 中文模型的检索指令前缀（官方推荐，仅加在 query 上）
BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

# 默认模型名（HuggingFace 仓库 id）
DEFAULT_MODEL_NAME = "BAAI/bge-base-zh-v1.5"

# 项目内模型目录（自包含部署：模型随项目走）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent  # CustomSystem/
_LOCAL_MODEL_DIR = _PROJECT_ROOT / "models" / "bge-base-zh-v1.5"


def resolve_model_path() -> str:
    """按优先级解析模型路径：环境变量 → 项目内目录 → HF 模型名。"""
    env_path = os.getenv("BGE_MODEL_PATH")
    if env_path and Path(env_path).exists():
        return env_path
    if _LOCAL_MODEL_DIR.exists():
        return str(_LOCAL_MODEL_DIR)
    return DEFAULT_MODEL_NAME


class Embedder:
    """本地 BGE 句向量编码器（单例式，进程内复用一个模型实例）。"""

    _instance: "Embedder | None" = None

    def __init__(self, model_path: str | None = None):
        # 延迟导入：sentence-transformers 加载较重，且让没装的环境能给出清晰报错
        from sentence_transformers import SentenceTransformer

        self.model_path = model_path or resolve_model_path()
        print(f"  [embedder] 加载模型: {self.model_path}")
        self._model = SentenceTransformer(self.model_path)
        # 探测向量维度（bge-base = 768），供 Qdrant 建集合时使用
        # 新版 sentence-transformers 用 get_embedding_dimension，旧版回退
        if hasattr(self._model, "get_embedding_dimension"):
            self._dim = self._model.get_embedding_dimension()
        else:
            self._dim = self._model.get_sentence_embedding_dimension()
        print(f"  [embedder] 模型就绪，向量维度 {self._dim}")

    # ── 单例获取 ──────────────────────────────────────────────────────

    @classmethod
    def get(cls, model_path: str | None = None) -> "Embedder":
        """获取全局单例。首次调用时加载模型（慢），之后直接复用。"""
        if cls._instance is None:
            cls._instance = cls(model_path)
        return cls._instance

    # ── 属性 ──────────────────────────────────────────────────────────

    @property
    def dim(self) -> int:
        """向量维度（Qdrant 建集合需要）。"""
        return self._dim

    # ── 编码 ──────────────────────────────────────────────────────────

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """编码文档（FAQ/商品），不加指令前缀。返回 L2 归一化后的向量列表。"""
        if not texts:
            return []
        vecs = self._model.encode(
            list(texts),
            normalize_embeddings=True,   # L2 归一化 → 余弦=点积
            show_progress_bar=False,
        )
        return vecs.tolist()

    def encode_query(self, query: str) -> list[float]:
        """编码单条 query，加 BGE 检索指令前缀。返回 L2 归一化后的向量。"""
        vec = self._model.encode(
            BGE_QUERY_INSTRUCTION + query,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vec.tolist()
