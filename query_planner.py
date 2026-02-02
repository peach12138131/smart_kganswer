"""
查询规划器
根据实体识别结果，智能生成 Cypher 查询
"""

import json
from typing import Dict, List, Optional
from llm_client import LLMClient
from schemas import query_plan_schema


class QueryPlanner:
    """智能查询规划器"""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        # 实体别名映射（用于处理同一实体的不同名称）
        self.entity_aliases = {
            'Gulfstream': ['Gulfstream', 'Gulfstream Aerospace'],
            'Gulfstream Aerospace': ['Gulfstream', 'Gulfstream Aerospace'],
            'NetJets': ['NetJets'],  # 可以继续扩展
        }

    def _expand_entity_names(self, entity_name: str) -> list:
        """扩展实体名称，包括其可能的别名"""
        # 如果在别名映射中，返回所有别名
        if entity_name in self.entity_aliases:
            return self.entity_aliases[entity_name]
        # 否则只返回原名称
        return [entity_name]

    def plan(
        self,
        question: str,
        recognition_result: Dict
    ) -> Optional[Dict]:
        """
        生成查询计划

        Args:
            question: 原始问题
            recognition_result: 实体识别结果

        Returns:
            {
                "strategy": "multi_hop",
                "cypher_queries": [
                    {
                        "description": "Find all products manufactured by Gulfstream",
                        "cypher": "MATCH (c:Company {name: 'Gulfstream'})-[:MANUFACTURES]->(p:Product) RETURN p",
                        "priority": 1
                    }
                ],
                "max_results": 20,
                "reasoning": "..."
            }
        """
        # 根据意图选择策略
        intent = recognition_result.get('intent', 'entity_info')

        # 简单意图使用规则生成
        if intent in ['entity_info', 'relation_query', 'event_query'] and len(recognition_result.get('entities', [])) <= 2:
            return self._rule_based_plan(question, recognition_result)

        # 复杂意图使用 LLM 生成
        return self._llm_based_plan(question, recognition_result)

    def _rule_based_plan(self, question: str, recognition_result: Dict) -> Dict:
        """基于规则的查询规划（快速路径）"""
        entities = recognition_result.get('entities', [])
        intent = recognition_result.get('intent')
        relation_types = recognition_result.get('relation_types', [])

        cypher_queries = []

        # entity_info: 查询单个实体
        if intent == 'entity_info' and len(entities) == 1:
            entity = entities[0]

            # 扩展实体名称（包括别名）
            entity_names = self._expand_entity_names(entity['name'])

            cypher = f"""
MATCH (n:{entity['type']})
WHERE n.name IN $entity_names
OPTIONAL MATCH (n)-[r]-(m)
RETURN n, type(r) as relation_type, labels(m)[0] as related_type,
       coalesce(m.name, m.id) as related_name, properties(m) as related_props
LIMIT 50
            """.strip()
            cypher_queries.append({
                "description": f"Query entity info for {entity['name']} (including aliases)",
                "cypher": cypher,
                "priority": 1,
                "params": {"entity_names": entity_names}
            })

        # relation_query: 查询关系
        elif intent == 'relation_query' and len(entities) >= 1:
            entity = entities[0]

            # 扩展实体名称（包括别名）
            entity_names = self._expand_entity_names(entity['name'])

            # 如果指定了关系类型
            if relation_types:
                for rel_type in relation_types[:3]:  # 最多3个
                    # 双向查询：既查"A->B"也查"B->A"，同时匹配所有可能的实体名称
                    cypher = f"""
MATCH (n)-[r:{rel_type}]-(m)
WHERE n.name IN $entity_names
RETURN type(r) as relation_type, labels(m)[0] as target_type,
       coalesce(m.name, m.id) as target_name, properties(m) as target_props,
       startNode(r).name IN $entity_names as is_outgoing
LIMIT 30
                    """.strip()
                    cypher_queries.append({
                        "description": f"Query {rel_type} relations for {entity['name']} (including aliases)",
                        "cypher": cypher,
                        "priority": 1,
                        "params": {"entity_names": entity_names}
                    })
            else:
                # 查询所有双向关系
                cypher = f"""
MATCH (n)-[r]-(m)
WHERE n.name IN $entity_names
RETURN type(r) as relation_type, labels(m)[0] as target_type,
       coalesce(m.name, m.id) as target_name, properties(m) as target_props,
       startNode(r).name IN $entity_names as is_outgoing
LIMIT 50
                """.strip()
                cypher_queries.append({
                    "description": f"Query all relations for {entity['name']} (including aliases)",
                    "cypher": cypher,
                    "priority": 1,
                    "params": {"entity_names": entity_names}
                })

        # comparison: 对比两个实体
        elif intent == 'comparison' and len(entities) == 2:
            entity1, entity2 = entities[0], entities[1]

            # 分别查询两个实体（包括别名）
            for entity in [entity1, entity2]:
                entity_names = self._expand_entity_names(entity['name'])

                cypher = f"""
MATCH (n:{entity['type']})
WHERE n.name IN $entity_names
OPTIONAL MATCH (n)-[r]->(m)
RETURN n, type(r) as relation_type, labels(m)[0] as related_type,
       coalesce(m.name, m.id) as related_name, properties(m) as related_props
LIMIT 30
                """.strip()
                cypher_queries.append({
                    "description": f"Query {entity['name']} for comparison (including aliases)",
                    "cypher": cypher,
                    "priority": 1,
                    "params": {"entity_names": entity_names}
                })

            # 查询两者之间的路径
            cypher = f"""
MATCH path = shortestPath((n1 {{name: $entity1_name}})-[*..4]-(n2 {{name: $entity2_name}}))
RETURN path
LIMIT 5
            """.strip()
            cypher_queries.append({
                "description": f"Find connection between {entity1['name']} and {entity2['name']}",
                "cypher": cypher,
                "priority": 2,
                "params": {
                    "entity1_name": entity1['name'],
                    "entity2_name": entity2['name']
                }
            })

        # event_query: 查询事件
        # 策略：优先使用文本搜索（event_keywords），其次使用实体关系
        elif intent == 'event_query':
            time_constraint = recognition_result.get('time_constraint', {})
            event_keywords = recognition_result.get('event_keywords', {})

            # 提取时间约束（支持多种键名）
            start_date = time_constraint.get('start') or time_constraint.get('start_date')
            end_date = time_constraint.get('end') or time_constraint.get('end_date')

            # 构建时间过滤条件
            def build_time_filter():
                if start_date and end_date:
                    return f"AND e.date >= date($start_date) AND e.date <= date($end_date)"
                elif start_date:
                    return f"AND e.date >= date($start_date)"
                elif end_date:
                    return f"AND e.date <= date($end_date)"
                return ""

            time_filter = build_time_filter()

            # 策略A：如果有event_keywords，使用文本搜索（泛化策略）
            if event_keywords and event_keywords.get('domain_keywords'):
                domain_keywords = event_keywords['domain_keywords']

                # 构建关键词搜索条件（使用OR连接多个CONTAINS）
                keyword_conditions = []
                for i, kw in enumerate(domain_keywords[:10]):  # 限制最多10个关键词避免查询过长
                    param_name = f"kw_{i}"
                    keyword_conditions.append(f"toLower(e.description) CONTAINS toLower(${param_name})")

                keyword_filter = " OR ".join(keyword_conditions)

                cypher = f"""
MATCH (e:Event)
WHERE ({keyword_filter}) {time_filter}
RETURN e.id as event_id, e.description as description, e.date as date,
       e.location as location, e.type as event_type
ORDER BY e.date DESC
LIMIT 100
                """.strip()

                # 构建参数
                params = {}
                for i, kw in enumerate(domain_keywords[:10]):
                    params[f"kw_{i}"] = kw
                if start_date:
                    params["start_date"] = start_date
                if end_date:
                    params["end_date"] = end_date

                event_types_str = ", ".join(event_keywords.get('event_types', []))
                cypher_queries.append({
                    "description": f"Text search for events matching keywords: {event_types_str}",
                    "cypher": cypher,
                    "priority": 1,
                    "params": params
                })

            # 策略B：如果有实体，使用实体关系查询（保留原有功能）
            if entities and len(entities) >= 1:
                entity = entities[0]
                entity_names = self._expand_entity_names(entity['name'])
                entity_type = entity['type']

                # 根据实体类型构建正确的查询方向
                # Event节点的关系是incoming：Company/Location/etc -> Event
                if entity_type in ['Location', 'Company', 'Product', 'Person']:
                    cypher = f"""
MATCH (n:{entity_type})-[r:PARTICIPATED_IN|IMPACTED_BY]->(e:Event)
WHERE n.name IN $entity_names {time_filter}
RETURN e.id as event_id, e.description as description, e.date as date,
       e.location as location, type(r) as relation_type
ORDER BY e.date DESC
LIMIT 50
                    """.strip()

                    params = {"entity_names": entity_names}
                    if start_date:
                        params["start_date"] = start_date
                    if end_date:
                        params["end_date"] = end_date

                    # 如果同时有event_keywords，这个查询优先级降低
                    priority = 2 if event_keywords else 1

                    cypher_queries.append({
                        "description": f"Query events related to {entity['name']} via relationships",
                        "cypher": cypher,
                        "priority": priority,
                        "params": params
                    })

        return {
            "strategy": "rule_based",
            "cypher_queries": cypher_queries,
            "max_results": 50,
            "reasoning": f"Using rule-based planning for {intent}"
        }

    def _llm_based_plan(self, question: str, recognition_result: Dict) -> Optional[Dict]:
        """基于 LLM 的查询规划（复杂场景）"""
        prompt = self._build_planning_prompt()

        context = f"""
Question: {question}

Recognition Result:
{json.dumps(recognition_result, indent=2, ensure_ascii=False)}
"""

        response = self.llm_client.query_sync(
            prompt=prompt,
            context=context,
            model="claude-haiku-4-5-20251001",
            temperature=0.0,
            json_schema=query_plan_schema
        )

        if not response:
            return None

        try:
            result = json.loads(response)
            return result
        except json.JSONDecodeError as e:
            print(f"[X] 查询规划 JSON 解析失败: {e}")
            return None

    def _build_planning_prompt(self) -> str:
        """构建查询规划提示词"""
        return """You are a Cypher query planner for Neo4j knowledge graph.

Your task:
1. Analyze the question and entity recognition result
2. Choose an appropriate query strategy
3. Generate optimized Cypher queries
4. Return queries with priority (1=highest)

Available Strategies:
- direct_property: Query node properties directly
- one_hop: Query direct neighbors (1 hop)
- multi_hop: Query multi-hop relationships (2-3 hops)
- path_finding: Find paths between entities
- subgraph: Extract a subgraph around entities
- pattern_match: Complex pattern matching

Node Labels:
Company, Product, Location, Event, Person, Technology, News

Relation Types:
OWNS, PARTNERS_WITH, ACQUIRES, ORDERS, INVESTS_IN, SUPPLIES, MANUFACTURES,
DEVELOPS, MANAGES, DELIVERED, LOCATED_IN, WORKS_FOR, PARTICIPATED_IN,
IMPLEMENTED, IMPACTED_BY, BANS, USES

CRITICAL - Event Relationship Directions:
Event nodes have INCOMING relationships (other entities point TO events):
- Company -[:PARTICIPATED_IN]-> Event
- Company -[:IMPACTED_BY]-> Event
- Location -[:PARTICIPATED_IN]-> Event
- Location -[:IMPACTED_BY]-> Event
- Product -[:PARTICIPATED_IN]-> Event
- Person -[:PARTICIPATED_IN]-> Event
NEVER use Event-[:SOMETHING]->Other pattern. Always use Other-[:SOMETHING]->Event.

Best Practices:
1. Use parameters ($param_name) for entity names
2. Limit results (LIMIT 20-50)
3. Use OPTIONAL MATCH for optional relations
4. Avoid expensive operations (e.g., cartesian products)
5. For multi-hop, limit depth to 2-3
6. For path finding, use shortestPath() with max depth 4

Examples:

Q: "What events impacted NetJets in 2025?"
A: {
  "strategy": "one_hop",
  "cypher_queries": [
    {
      "description": "Find events that impacted NetJets in 2025",
      "cypher": "MATCH (c:Company {name: $company_name})-[:IMPACTED_BY]->(e:Event) WHERE e.date >= date('2025-01-01') AND e.date <= date('2025-12-31') RETURN e, e.date, e.description LIMIT 20",
      "priority": 1,
      "params": {"company_name": "NetJets"}
    }
  ],
  "max_results": 20,
  "reasoning": "Query direct IMPACTED_BY relations filtered by date"
}

Q: "Find the supply chain from engine suppliers to NetJets"
A: {
  "strategy": "multi_hop",
  "cypher_queries": [
    {
      "description": "Find supply chain path to NetJets",
      "cypher": "MATCH path = (supplier:Company)-[:SUPPLIES*1..3]->(product:Product)<-[:USES|OPERATES]-(netjets:Company {name: $company_name}) WHERE supplier.type = 'Manufacturer' RETURN path LIMIT 10",
      "priority": 1,
      "params": {"company_name": "NetJets"}
    }
  ],
  "max_results": 10,
  "reasoning": "Multi-hop traversal to find supply chain connections"
}

Q: "What events happened in Middle East last year?"
A: {
  "strategy": "one_hop",
  "cypher_queries": [
    {
      "description": "Find events in Middle East in 2025",
      "cypher": "MATCH (loc:Location)-[:PARTICIPATED_IN|IMPACTED_BY]->(e:Event) WHERE loc.name = $location_name AND e.date >= date($start_date) AND e.date <= date($end_date) RETURN e.id, e.description, e.date, e.location ORDER BY e.date DESC LIMIT 30",
      "priority": 1,
      "params": {"location_name": "Middle East", "start_date": "2025-01-01", "end_date": "2025-12-31"}
    }
  ],
  "max_results": 30,
  "reasoning": "Query Location->Event relationships (correct direction) with time filter"
}

Now generate a query plan for the following:
"""
