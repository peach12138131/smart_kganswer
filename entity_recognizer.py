"""
实体识别器
使用小模型（Haiku）快速识别用户问题中的实体和意图
"""

import json
from typing import Dict, List, Optional
from llm_client import LLMClient
from schemas import entity_recognition_schema


class EntityRecognizer:
    """实体识别和意图理解"""

    def __init__(self, llm_client: LLMClient, query_rewriter=None):
        self.llm_client = llm_client
        self.query_rewriter = query_rewriter

    def recognize(self, question: str) -> Optional[Dict]:
        """
        识别问题中的实体和意图（带查询改写）

        Args:
            question: 用户问题

        Returns:
            {
                "entities": [{"name": "NetJets", "type": "Company", "confidence": 0.95, "aliases": [...]}],
                "intent": "relation_query",
                "relation_types": ["MANUFACTURES", "USES"],
                "time_constraint": {"start_date": "2025-01-01", "end_date": "2025-12-31"},
                "rewrite_notes": ["查询扩展：Global 7500"]
            }
        """
        prompt = self._build_prompt()

        response = self.llm_client.query_sync(
            prompt=prompt,
            context=question,
            model="claude-haiku-4-5-20251001",  # 使用小模型
            temperature=0.0,
            json_schema=entity_recognition_schema
        )

        if not response:
            return None

        try:
            result = json.loads(response)

            # 使用QueryRewriter进行查询改写和实体扩展
            if self.query_rewriter:
                result, rewrite_notes = self.query_rewriter.rewrite_query(question, result)
                if rewrite_notes:
                    result['rewrite_notes'] = rewrite_notes
                    print(f"[*] 查询改写: {', '.join(rewrite_notes)}")

            return result
        except json.JSONDecodeError as e:
            print(f"[X] 实体识别 JSON 解析失败: {e}")
            print(f"原始响应: {response[:200]}")
            return None

    def _build_prompt(self) -> str:
        """构建实体识别提示词"""
        from datetime import datetime
        current_date = datetime.now().strftime("%Y-%m-%d")

        prompt_base = """You are an entity recognizer for the business aviation industry knowledge graph.

IMPORTANT: Today's date is {date_placeholder}. Use this to correctly interpret relative time expressions like "last year", "去年", "this year", "今年", etc.

Your task:"""
        return prompt_base.replace("{date_placeholder}", current_date) + """
1. Identify all entities in the user's question
2. Classify each entity type (Company, Product, Location, Event, Person, Technology)
3. Determine the user's intent
4. Extract relevant relation types (if any)
5. Extract time constraints (if any)

Entity Types:
- Company: Airlines, Operators, Manufacturers (e.g., NetJets, Gulfstream, Boeing)
- Product: Aircraft models, Technologies (e.g., G650, Global 7500, Starlink)
- Location: Airports, Cities, Countries (e.g., LAX, New York, US)
- Event: Deliveries, Accidents, Regulatory changes
- Person: CEOs, Executives
- Technology: SAF, Connectivity systems, Autonomous tech

Intent Types:
- entity_info: Query info about a single entity (e.g., "What is NetJets?")
- relation_query: Query relationships (e.g., "What aircraft does NetJets operate?")
- list_query: List/enumerate entities (e.g., "有哪些机场？", "What airports are in the database?")
- count_query: Count/statistics (e.g., "有多少航线？", "How many routes?")
- exploration_query: Explore database (e.g., "数据库里有什么数据？", "What data do you have?")
- comparison: Compare entities (e.g., "Compare G650 and Global 7500")
- event_query: Query events (e.g., "What deliveries happened in 2025?")
- general_question: General questions

IMPORTANT for event_query:
When the intent is event_query, you MUST extract event_keywords to enable text-based search in Event descriptions.
- event_types: Chinese event type keywords (事故/accident, 交付/delivery, 订单/order, 发布/launch, etc.)
- domain_keywords: English domain keywords for filtering (private, business jet, bizjet, charter, aviation, commercial, etc.)

Event Type Keyword Mappings:
- 事故/故障 → ["accident", "crash", "incident", "emergency", "fatal", "failure"]
- 交付 → ["delivery", "delivered", "deliveries"]
- 订单 → ["order", "ordered", "purchase"]
- 发布/推出 → ["launch", "unveiled", "introduced", "announced"]
- 增长/下降 → ["growth", "increase", "decline", "decrease", "surge"]
- 监管/禁令 → ["regulatory", "ban", "restriction", "compliance"]

Relation Types (common ones):
MANUFACTURES, OPERATES, OWNS, PARTNERS_WITH, USES, SUPPLIES, DELIVERS, LOCATED_IN, WORKS_FOR, etc.

Examples:

Q: "NetJets 使用了哪些飞机？"
A: {
  "entities": [
    {"name": "NetJets", "type": "Company", "confidence": 0.95}
  ],
  "intent": "relation_query",
  "relation_types": ["OPERATES", "USES"]
}

Q: "庞巴迪 Global 7500最火的几条航线记录"
A: {
  "entities": [
    {"name": "Bombardier", "type": "Company", "confidence": 0.95},
    {"name": "Global 7500", "type": "Product", "confidence": 0.95}
  ],
  "intent": "relation_query",
  "relation_types": ["HAS_ROUTE", "OPERATES_ON"]
}

Q: "Gulfstream 在 2025 年交付了多少架 G650？"
A: {
  "entities": [
    {"name": "Gulfstream", "type": "Company", "confidence": 0.95},
    {"name": "G650", "type": "Product", "confidence": 0.9}
  ],
  "intent": "event_query",
  "relation_types": ["DELIVERED"],
  "time_constraint": {"start_date": "2025-01-01", "end_date": "2025-12-31"}
}

Q: "Compare NetJets and Flexjet"
A: {
  "entities": [
    {"name": "NetJets", "type": "Company", "confidence": 0.95},
    {"name": "Flexjet", "type": "Company", "confidence": 0.95}
  ],
  "intent": "comparison"
}

Q: "中东地区去年发生了哪些事件？" (Today is 2026-01-30)
A: {
  "entities": [
    {"name": "Middle East", "type": "Location", "confidence": 0.95}
  ],
  "intent": "event_query",
  "time_constraint": {"start_date": "2025-01-01", "end_date": "2025-12-31"}
}

Q: "去年有哪些私人包机航空事故？" (Today is 2026-01-30)
A: {
  "entities": [],
  "intent": "event_query",
  "time_constraint": {"start_date": "2025-01-01", "end_date": "2025-12-31"},
  "event_keywords": {
    "event_types": ["事故", "故障"],
    "domain_keywords": ["private", "business jet", "bizjet", "charter", "aviation", "accident", "crash", "incident", "fatal", "emergency"]
  }
}

Q: "2025年Gulfstream交付了多少架飞机？" (Today is 2026-01-30)
A: {
  "entities": [
    {"name": "Gulfstream", "type": "Company", "confidence": 0.95}
  ],
  "intent": "event_query",
  "time_constraint": {"start_date": "2025-01-01", "end_date": "2025-12-31"},
  "event_keywords": {
    "event_types": ["交付"],
    "domain_keywords": ["delivery", "delivered"]
  }
}

Q: "最近有哪些航空监管政策变化？" (Today is 2026-01-30)
A: {
  "entities": [],
  "intent": "event_query",
  "event_keywords": {
    "event_types": ["监管", "政策"],
    "domain_keywords": ["regulatory", "regulation", "policy", "compliance", "FAA", "aviation"]
  }
}

Q: "数据库中有哪些机场？"
A: {
  "entities": [],
  "intent": "list_query",
  "keywords": ["机场"]
}

Q: "有多少航线数据？"
A: {
  "entities": [],
  "intent": "count_query",
  "keywords": ["航线"]
}

Q: "数据库里都有什么数据？"
A: {
  "entities": [],
  "intent": "exploration_query"
}

Now analyze the following question:
"""
