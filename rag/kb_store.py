"""
KnowledgeBase — 语义知识库（Qdrant 向量检索 + 本地 BGE 编码）
================================================================
中文语义检索：用本地 bge-base-zh-v1.5 把文本编码成 768 维稠密向量，
存进 Qdrant（嵌入式本地模式，数据落地到 workspace/qdrant_data），
查询时编码 query 做向量近邻检索（余弦距离）。

为什么是真·语义检索（区别于旧版 TF-IDF）：
  - TF-IDF 靠字面字符重叠："退钱"匹配"退款"只因共享"退"字，
    "我想把钱要回来"匹配不到"退款政策"（无共享字符）。
  - BGE 编码后向量空间里语义相近的句子距离也近，
    "我想把钱要回来" 和 "退款政策" 的余弦相似度依然高。

设计要点：
  - FAQ 和商品用两个独立 collection（faq / product），向量空间隔离。
  - add_faq/add_product 只往内存缓冲攒数据并置脏标记；
    首次 search 时惰性批量编码 + 写库（批量编码远快于逐条）。
  - 所有向量都做 L2 归一化，Qdrant 用 COSINE 距离。
    因为同一个模型、同一种归一化，FAQ 和商品的分数**可以跨库公平比较**，
    顺手修掉了旧 TF-IDF 版本里跨库分数不可比的缺陷。
  - 对外接口（add_faq/add_product/clear_all/search_faq/search_products/search_all）
    与旧版完全一致，router 和 rag_search 工具无需改动。

嵌入式模式说明：
  QdrantClient(path=...) 会独占该目录的文件锁，单进程内只应有一个实例。
  本类持有唯一的 client，全局复用。
"""

from __future__ import annotations

from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

from core.embedder import Embedder

# 两个 collection 名
_FAQ_COLLECTION = "faq"
_PRODUCT_COLLECTION = "product"

# 默认向量库落地目录（嵌入式本地模式）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent  # CustomSystem/
_DEFAULT_QDRANT_DIR = _PROJECT_ROOT / "workspace" / "qdrant_data"


class KnowledgeBase:
    """Qdrant 向量检索知识库。接口与旧 TF-IDF 版本兼容。"""

    def __init__(self, persist_dir: str | None = None):
        """
        Args:
            persist_dir: Qdrant 数据落地目录。None 时用 workspace/qdrant_data。
        """
        self._qdrant_dir = Path(persist_dir) if persist_dir else _DEFAULT_QDRANT_DIR
        self._qdrant_dir.mkdir(parents=True, exist_ok=True)

        # 嵌入式本地模式：数据存本地文件，无需起服务
        self._client = QdrantClient(path=str(self._qdrant_dir))

        # embedding 模型延迟加载（首次 build 时才真正加载，避免无谓的启动开销）
        self._embedder: Embedder | None = None

        # 内存缓冲：add_* 先攒在这里，build() 时批量编码写库
        self._faq_texts: list[str] = []
        self._faq_meta: list[dict] = []
        self._product_texts: list[str] = []
        self._product_meta: list[dict] = []

        # 脏标记：有新数据未写入 Qdrant 时为 True，下次 search 触发 build
        self._faq_dirty = False
        self._product_dirty = False

    # ── embedding 模型（惰性加载，全局单例）─────────────────────────────

    def _get_embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = Embedder.get()
        return self._embedder

    def close(self) -> None:
        """Release the embedded Qdrant file lock deterministically."""
        self._client.close()

    # ====================================================================
    # 写入
    # ====================================================================

    def add_faq(self, faq_id: str, question: str, answer: str, category: str = ""):
        """添加一条 FAQ（仅入缓冲，置脏标记，首次查询时批量写库）。"""
        text = f"问题: {question} 答案: {answer}"
        self._faq_texts.append(text)
        self._faq_meta.append({"faq_id": faq_id, "question": question, "category": category})
        self._faq_dirty = True

    def add_product(self, product_id: str, name: str, description: str, category: str = ""):
        """添加一个商品（仅入缓冲，置脏标记，首次查询时批量写库）。"""
        text = f"商品: {name} 描述: {description} 分类: {category}"
        self._product_texts.append(text)
        self._product_meta.append({"product_id": product_id, "name": name, "category": category})
        self._product_dirty = True

    def clear_all(self):
        """清空所有数据（内存缓冲 + Qdrant collection）。"""
        self._faq_texts.clear()
        self._faq_meta.clear()
        self._product_texts.clear()
        self._product_meta.clear()
        self._faq_dirty = False
        self._product_dirty = False
        for name in (_FAQ_COLLECTION, _PRODUCT_COLLECTION):
            if self._client.collection_exists(name):
                self._client.delete_collection(name)

    def build(self):
        """把缓冲区的数据批量编码并写入 Qdrant。幂等：无脏数据时跳过。"""
        if self._faq_dirty:
            self._build_collection(_FAQ_COLLECTION, self._faq_texts, self._faq_meta)
            self._faq_dirty = False
        if self._product_dirty:
            self._build_collection(_PRODUCT_COLLECTION, self._product_texts, self._product_meta)
            self._product_dirty = False

    def _build_collection(self, name: str, texts: list[str], metas: list[dict]):
        """（重）建一个 collection：批量编码文本并写入向量点。"""
        if not texts:
            return

        embedder = self._get_embedder()
        vectors = embedder.encode_documents(texts)  # 文档不加指令前缀

        # 重建 collection（数据量小，全量重建最简单可靠）
        # 用 delete + create 替代已弃用的 recreate_collection
        if self._client.collection_exists(name):
            self._client.delete_collection(name)
        self._client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=embedder.dim, distance=Distance.COSINE),
        )

        points = [
            PointStruct(
                id=i,
                vector=vectors[i],
                payload={"content": texts[i], **metas[i]},
            )
            for i in range(len(texts))
        ]
        self._client.upsert(collection_name=name, points=points)
        print(f"  [kb] collection '{name}' 写入 {len(points)} 条向量")

    # ====================================================================
    # 查询
    # ====================================================================

    def search_faq(self, query: str, n_results: int = 3) -> list[dict]:
        """在 FAQ 中做向量语义检索。"""
        if self._faq_dirty:
            self.build()
        return self._search(_FAQ_COLLECTION, query, n_results)

    def search_products(self, query: str, n_results: int = 3) -> list[dict]:
        """在商品中做向量语义检索。"""
        if self._product_dirty:
            self.build()
        return self._search(_PRODUCT_COLLECTION, query, n_results)

    def search_all(self, query: str, n_results: int = 5) -> list[dict]:
        """同时搜 FAQ 和商品，合并按相似度降序。

        因为两库共用同一 BGE 模型 + 归一化余弦分数，跨库分数可公平比较。
        """
        faq_hits = self.search_faq(query, n_results)
        product_hits = self.search_products(query, n_results)

        all_hits = faq_hits + product_hits
        all_hits.sort(key=lambda x: x["score"], reverse=True)
        return all_hits[:n_results]

    def _search(self, collection: str, query: str, n: int) -> list[dict]:
        """核心检索：编码 query（加指令前缀）→ Qdrant 近邻检索 → 整理结果。"""
        if not self._client.collection_exists(collection):
            return []

        query_vec = self._get_embedder().encode_query(query)  # query 加指令前缀

        results = self._client.query_points(
            collection_name=collection,
            query=query_vec,
            limit=n,
            with_payload=True,
        ).points

        hits: list[dict] = []
        for r in results:
            payload = dict(r.payload or {})
            content = payload.pop("content", "")
            hits.append({
                "content": content,
                "score": round(float(r.score), 3),
                **payload,  # faq_id/question/category 或 product_id/name/category
            })
        return hits
