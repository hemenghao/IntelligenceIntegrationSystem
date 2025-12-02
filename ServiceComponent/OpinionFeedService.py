import json
import logging
import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ServiceComponent.IntelligenceHubDefines import APPENDIX_TIME_ARCHIVED

logger = logging.getLogger(__name__)


class OpinionFeedService:
    def __init__(self,
                 intelligence_hub,
                 topics_path: str = "static/data/opinion_topics.json",
                 demo_feed_path: str = "static/data/opinion_demo_feed.json"):
        self.intelligence_hub = intelligence_hub
        self.topics_path = Path(topics_path)
        self.demo_feed_path = Path(demo_feed_path)
        self._topics = self._load_topics()

    def _load_topics(self) -> Dict[str, Dict[str, Any]]:
        """从本地 JSON 文件读取 Opinion 市场元数据，读取失败时返回空字典。"""
        try:
            if not self.topics_path.exists():
                logger.warning("Opinion topics file not found: %s", self.topics_path)
                return {}
            data = json.loads(self.topics_path.read_text(encoding="utf-8"))
            mapping = {str(item.get("topic_id") or item.get("market_id")): item for item in data}
            return mapping
        except Exception:
            logger.exception("Failed to load opinion topics from %s", self.topics_path)
            return {}

    def get_categories(self) -> List[str]:
        """整理可用的 UI 分类标签，缺省包含 All。"""
        categories = {"All"}
        for topic in self._topics.values():
            for category in topic.get("ui_categories", []):
                if category:
                    categories.add(category)
        ordered = ["All"] + sorted(categories - {"All"})
        return ordered

    def get_feed(self, category: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """优先尝试从归档中查询情报，失败则使用打包的演示数据。"""
        category = category or "All"
        feed = self._query_from_archive(category=category, limit=limit)
        if feed:
            return feed
        return self._load_demo_feed(category=category, limit=limit)

    def get_topic(self, topic_id: str) -> Optional[Dict[str, Any]]:
        """根据 topic_id 获取市场信息。"""
        return self._topics.get(str(topic_id))

    def list_markets(self, category: Optional[str] = None, sample_limit: int = 200) -> List[Dict[str, Any]]:
        """返回市场卡片列表，并附带最新情报计数/标题。"""
        category = category or "All"
        topics = [
            topic for topic in self._topics.values()
            if category in (None, "All") or category in topic.get("ui_categories", [])
        ]

        feed_items = self.get_feed(category=category, limit=sample_limit)
        by_topic: Dict[str, Dict[str, Any]] = {}
        for item in feed_items:
            for ann in item.get("opinion_annotations", []):
                topic_id = str(ann.get("topic_id"))
                if topic_id not in by_topic:
                    by_topic[topic_id] = {
                        "recent_count": 0,
                        "latest_headline": None,
                        "latest_published_at": None,
                    }
                by_topic[topic_id]["recent_count"] += 1
                if by_topic[topic_id]["latest_published_at"] is None:
                    by_topic[topic_id]["latest_headline"] = item.get("title")
                    by_topic[topic_id]["latest_published_at"] = item.get("published_at")

        market_cards: List[Dict[str, Any]] = []
        for topic in topics:
            topic_id = str(topic.get("topic_id") or topic.get("market_id"))
            stats = by_topic.get(topic_id, {})
            market_cards.append({
                "topic_id": topic_id,
                "market_title": topic.get("market_title") or topic.get("title"),
                "event_archetype": topic.get("event_archetype", ""),
                "opinion_market_url": topic.get("opinion_market_url"),
                "ui_categories": topic.get("ui_categories", []),
                "domains": topic.get("domains", []),
                "recent_count": stats.get("recent_count", 0),
                "latest_headline": stats.get("latest_headline"),
                "latest_published_at": stats.get("latest_published_at"),
            })

        return market_cards

    def get_topic_feed(self, topic_id: str, limit: int = 50) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """获取单个市场的详情和时间线情报，优先读取归档。"""
        topic = self.get_topic(topic_id)
        feed = self._query_from_archive(category=None, limit=limit, topic_filter=topic_id)
        if not feed:
            feed = self._load_demo_feed(category=None, limit=limit, topic_filter=topic_id)
        return topic or {}, feed

    # -------------------------- Private helpers --------------------------

    def _query_from_archive(self, category: Optional[str], limit: int, topic_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """调用 IntelligenceHub 查询归档情报，并按分类/Topic 过滤。"""
        try:
            docs, _ = self.intelligence_hub.query_intelligence(threshold=0, skip=0, limit=limit * 3)
        except Exception:
            logger.exception("Opinion feed query failed")
            return []

        feed_items: List[Dict[str, Any]] = []
        for doc in docs:
            item = self._build_feed_item(doc, category=category, topic_filter=topic_filter)
            if item:
                feed_items.append(item)
            if len(feed_items) >= limit:
                break
        return sorted(feed_items, key=lambda x: x.get("published_at", ""), reverse=True)

    def _build_feed_item(self, doc: Dict[str, Any], category: Optional[str], topic_filter: Optional[str]) -> Optional[Dict[str, Any]]:
        """把原始情报记录转换为前端需要的格式，并附带相关市场标注。"""
        annotations = self._extract_annotations(doc, category=category, topic_filter=topic_filter)
        if not annotations:
            return None

        published_at = self._parse_time(
            doc.get("PUB_TIME") or doc.get("TIME") or doc.get("APPENDIX", {}).get(APPENDIX_TIME_ARCHIVED)
        )

        return {
            "uuid": doc.get("UUID"),
            "title": doc.get("TITLE") or doc.get("EVENT_TITLE") or "Untitled intel",
            "source": doc.get("INFORMANT") or doc.get("SOURCE") or "Unknown",
            "summary": doc.get("SUMMARY") or doc.get("EVENT_BRIEF") or doc.get("EVENT_TEXT") or "",
            "published_at": self._format_time(published_at),
            "opinion_annotations": annotations,
            "link": doc.get("URL") or doc.get("INFORMANT") or "",
        }

    def _extract_annotations(self, doc: Dict[str, Any], category: Optional[str], topic_filter: Optional[str]) -> List[Dict[str, Any]]:
        """解析预测市场相关的标注，兼容多种字段格式。"""
        appendix = doc.get("APPENDIX", {}) or {}
        raw_annotations = appendix.get("prediction_annotations") or doc.get("prediction_annotations")

        if isinstance(raw_annotations, dict):
            raw_annotations = raw_annotations.get("topics") or raw_annotations.get("markets")

        annotations: List[Dict[str, Any]] = []
        for annotation in raw_annotations or []:
            topic_id = str(annotation.get("topic_id") or annotation.get("market_id") or "")
            if not topic_id:
                continue
            if topic_filter and topic_id != str(topic_filter):
                continue
            topic = self._topics.get(topic_id)
            if not topic:
                continue
            if category not in (None, "All") and category not in topic.get("ui_categories", []):
                continue

            annotations.append({
                "topic_id": topic_id,
                "market_title": topic.get("market_title") or topic.get("title") or "Opinion market",
                "sentiment_for_yes": annotation.get("sentiment_for_yes") or annotation.get("verdict"),
                "impact_level": annotation.get("impact_level") or annotation.get("impact") or "unknown",
                "reason": annotation.get("reason") or annotation.get("note") or "",
                "opinion_market_url": annotation.get("opinion_market_url") or topic.get("opinion_market_url"),
                "ui_categories": topic.get("ui_categories", []),
            })

        return annotations

    def _load_demo_feed(self, category: Optional[str], limit: int, topic_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """读取打包的演示情报，用于离线或缺少归档时的兜底展示。"""
        try:
            if not self.demo_feed_path.exists():
                logger.warning("Opinion demo feed missing: %s", self.demo_feed_path)
                return []
            feed = json.loads(self.demo_feed_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to load demo feed from %s", self.demo_feed_path)
            return []

        filtered: List[Dict[str, Any]] = []
        for item in feed:
            annotations = []
            for ann in item.get("opinion_annotations", []):
                topic_id = str(ann.get("topic_id"))
                topic = self._topics.get(topic_id)
                if not topic:
                    continue
                if topic_filter and topic_id != str(topic_filter):
                    continue
                if category not in (None, "All") and category not in topic.get("ui_categories", []):
                    continue
                annotations.append({**ann, "market_title": topic.get("market_title"), "ui_categories": topic.get("ui_categories", [])})
            if not annotations:
                continue
            filtered.append({
                "uuid": item.get("uuid"),
                "title": item.get("title"),
                "source": item.get("source", "Demo source"),
                "summary": item.get("summary", ""),
                "published_at": item.get("published_at"),
                "opinion_annotations": annotations,
                "link": item.get("link", ""),
            })
            if len(filtered) >= limit:
                break
        return filtered

    @staticmethod
    def _parse_time(value: Any) -> Optional[datetime.datetime]:
        if isinstance(value, datetime.datetime):
            return value
        if isinstance(value, (int, float)):
            return datetime.datetime.fromtimestamp(value, tz=datetime.timezone.utc)
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
                try:
                    return datetime.datetime.strptime(value, fmt)
                except ValueError:
                    continue
        return None

    @staticmethod
    def _format_time(value: Optional[datetime.datetime]) -> str:
        if not value:
            return ""
        if not value.tzinfo:
            value = value.replace(tzinfo=datetime.timezone.utc)
        return value.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
