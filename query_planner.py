"""
查询规划器 - 锚点定位 + 拓扑扩展策略

对任意意图，优先用关键词扫描节点属性定位锚点，再按实际图结构拓展。
不依赖预设图结构，有数据就能找到。
"""

from typing import Dict, List
from utils import build_time_filter, extract_time_params, build_keyword_filter, merge_params


class QueryPlanner:

    def plan(self, question: str, recognition_result: Dict) -> Dict:
        intent = recognition_result.get('intent', 'general_question')
        entities = recognition_result.get('entities', [])
        time_constraint = recognition_result.get('time_constraint', {})
        event_keywords = recognition_result.get('event_keywords', {})
        keywords = recognition_result.get('keywords', [])

        dispatch = {
            'event_query':      lambda: self._plan_event(entities, event_keywords, time_constraint),
            'entity_info':      lambda: self._plan_entity(entities),
            'relation_query':   lambda: self._plan_entity(entities),
            'comparison':       lambda: self._plan_comparison(entities),
            'list_query':       lambda: self._plan_list(keywords, question),
            'count_query':      lambda: self._plan_count(keywords),
            'exploration_query': lambda: self._plan_exploration(),
        }

        build = dispatch.get(intent, lambda: self._plan_entity(entities) or self._plan_exploration())
        queries = build()

        return {
            "strategy": "anchor_expand",
            "cypher_queries": [q for q in queries if q],
            "max_results": 100,
            "reasoning": f"anchor+expand for intent={intent}"
        }

    # ── 工具方法 ────────────────────────────────────────────────────────────

    def _all_terms(self, entities: List[Dict]) -> List[str]:
        """提取所有搜索词（实体名称 + 别名），去重保序"""
        terms, seen = [], set()
        for e in entities:
            for t in e.get('aliases', [e['name']]):
                if t and t.lower() not in seen:
                    seen.add(t.lower())
                    terms.append(t)
        return terms

    # ── event_query ──────────────────────────────────────────────────────────

    def _plan_event(self, entities, event_keywords, time_constraint):
        """
        三层策略：
          1. 实体词在 Event.description / Event.location 字段关键词锚点（最重要）
          2. 领域关键词搜索 event_keywords.domain_keywords
          3. 图谱拓展：实体节点 -[PARTICIPATED_IN|IMPACTED_BY]-> Event
        """
        queries = []
        time_filter = build_time_filter(time_constraint)
        time_params = extract_time_params(time_constraint)

        # 策略1：实体词锚点
        terms = self._all_terms(entities)
        if terms:
            conds, params = [], dict(time_params)
            for i, t in enumerate(terms[:6]):
                p = f"t{i}"
                conds.append(
                    f"(toLower(e.description) CONTAINS toLower(${p})"
                    f" OR toLower(coalesce(e.location,'')) CONTAINS toLower(${p}))"
                )
                params[p] = t
            where = "(" + " OR ".join(conds) + ")"
            if time_filter:
                where += f" {time_filter}"
            queries.append({
                "description": f"Keyword anchor in Event: {', '.join(terms[:3])}",
                "cypher": (
                    "MATCH (e:Event)\n"
                    f"WHERE {where}\n"
                    "RETURN e.id as event_id, e.description as description,\n"
                    "       e.date as date, e.location as location, e.type as event_type\n"
                    "ORDER BY e.date DESC\n"
                    "LIMIT 50"
                ),
                "priority": 1,
                "params": params
            })

        # 策略2：领域关键词
        domain_kws = (event_keywords or {}).get('domain_keywords', [])
        if domain_kws:
            kw_filter, kw_params = build_keyword_filter(domain_kws, "e.description")
            if kw_filter:
                where = f"({kw_filter})"
                if time_filter:
                    where += f" {time_filter}"
                queries.append({
                    "description": f"Domain keywords: {', '.join(domain_kws[:3])}",
                    "cypher": (
                        "MATCH (e:Event)\n"
                        f"WHERE {where}\n"
                        "RETURN e.id as event_id, e.description as description,\n"
                        "       e.date as date, e.location as location, e.type as event_type\n"
                        "ORDER BY e.date DESC\n"
                        "LIMIT 50"
                    ),
                    "priority": 2,
                    "params": merge_params(kw_params, time_params)
                })

        # 策略3：图谱拓展
        for entity in entities:
            etype = entity.get('type', '')
            if etype not in ('Location', 'Company', 'Person', 'Product'):
                continue
            names = entity.get('aliases', [entity['name']])
            where = "n.name IN $entity_names"
            if time_filter:
                where += f" {time_filter}"
            queries.append({
                "description": f"Graph expand: {entity['name']} → Event",
                "cypher": (
                    f"MATCH (n:{etype})-[r:PARTICIPATED_IN|IMPACTED_BY]->(e:Event)\n"
                    f"WHERE {where}\n"
                    "RETURN e.id as event_id, e.description as description,\n"
                    "       e.date as date, e.location as location, type(r) as relation_type\n"
                    "ORDER BY e.date DESC\n"
                    "LIMIT 50"
                ),
                "priority": 3,
                "params": merge_params({"entity_names": names}, time_params)
            })

        # 兜底：时间范围内所有事件
        if not queries:
            start = time_params.get('start_date', '')
            end = time_params.get('end_date', '')
            if start and end:
                queries.append({
                    "description": "All events in time range",
                    "cypher": (
                        "MATCH (e:Event)\n"
                        "WHERE e.date >= date($start_date) AND e.date <= date($end_date)\n"
                        "RETURN e.id as event_id, e.description as description,\n"
                        "       e.date as date, e.location as location, e.type as event_type\n"
                        "ORDER BY e.date DESC\n"
                        "LIMIT 50"
                    ),
                    "priority": 4,
                    "params": time_params
                })
            else:
                return self._plan_exploration()

        return queries

    # ── entity_info / relation_query ─────────────────────────────────────────

    def _plan_entity(self, entities):
        if not entities:
            return self._plan_exploration()
        queries = []
        for idx, entity in enumerate(entities):
            names = entity.get('aliases', [entity['name']])
            label = f":{entity['type']}" if entity.get('type') else ""
            queries.append({
                "description": f"Entity: {entity['name']}",
                "cypher": (
                    f"MATCH (n{label})\n"
                    "WHERE n.name IN $entity_names\n"
                    "OPTIONAL MATCH (n)-[r]-(m)\n"
                    "RETURN n, type(r) as relation_type, labels(m)[0] as related_type,\n"
                    "       coalesce(m.name, m.id) as related_name, properties(m) as related_props\n"
                    "LIMIT 50"
                ),
                "priority": idx + 1,
                "params": {"entity_names": names}
            })
        return queries

    # ── comparison ───────────────────────────────────────────────────────────

    def _plan_comparison(self, entities):
        queries = self._plan_entity(entities)
        if len(entities) >= 2:
            n1 = self._all_terms([entities[0]])[0]
            n2 = self._all_terms([entities[1]])[0]
            queries.append({
                "description": f"Shortest path: {entities[0]['name']} <-> {entities[1]['name']}",
                "cypher": (
                    "MATCH path = shortestPath((n1 {name: $name1})-[*..4]-(n2 {name: $name2}))\n"
                    "RETURN path LIMIT 5"
                ),
                "priority": len(queries) + 1,
                "params": {"name1": n1, "name2": n2}
            })
        return queries

    # ── list_query ───────────────────────────────────────────────────────────

    _LABEL_MAP = {
        "机场": "Location", "airport": "Location",
        "公司": "Company", "企业": "Company", "company": "Company",
        "运营商": "Company", "operator": "Company",
        "飞机": "Product", "aircraft": "Product", "plane": "Product",
        "航线": "Route", "route": "Route",
        "事件": "Event", "event": "Event",
        "城市": "Location", "国家": "Location", "地区": "Location",
    }

    def _plan_list(self, keywords, question):
        kws = keywords or [k for k in self._LABEL_MAP if k in question.lower()]
        queries = []
        for kw in kws[:2]:
            label = next((v for k, v in self._LABEL_MAP.items() if k in kw.lower()), None)
            if label:
                queries.append({
                    "description": f"List {label}",
                    "cypher": (
                        f"MATCH (n:{label})\n"
                        "RETURN n.name as name, n.type as entity_type\n"
                        "ORDER BY n.name LIMIT 100"
                    ),
                    "priority": 1,
                    "params": {}
                })
            queries.append({
                "description": f"Fuzzy list: {kw}",
                "cypher": (
                    "MATCH (n)\n"
                    "WHERE toLower(n.name) CONTAINS toLower($kw)\n"
                    "   OR toLower(coalesce(n.type,'')) CONTAINS toLower($kw)\n"
                    "RETURN DISTINCT n.name as name, labels(n)[0] as label, n.type as entity_type\n"
                    "ORDER BY n.name LIMIT 100"
                ),
                "priority": 2,
                "params": {"kw": kw}
            })
        return queries or self._plan_exploration()

    # ── count_query ──────────────────────────────────────────────────────────

    def _plan_count(self, keywords):
        if not keywords:
            return [{
                "description": "Count all by type",
                "cypher": (
                    "MATCH (n)\n"
                    "RETURN labels(n)[0] as node_type, count(n) as total\n"
                    "ORDER BY total DESC"
                ),
                "priority": 1,
                "params": {}
            }]
        return [{
            "description": f"Count: {kw}",
            "cypher": (
                "MATCH (n)\n"
                "WHERE toLower(n.name) CONTAINS toLower($kw)\n"
                "   OR toLower(coalesce(n.type,'')) CONTAINS toLower($kw)\n"
                "   OR ANY(l IN labels(n) WHERE toLower(l) CONTAINS toLower($kw))\n"
                "RETURN labels(n)[0] as node_type, count(n) as total\n"
                "ORDER BY total DESC"
            ),
            "priority": i + 1,
            "params": {"kw": kw}
        } for i, kw in enumerate(keywords[:2])]

    # ── exploration_query ────────────────────────────────────────────────────

    def _plan_exploration(self):
        return [{
            "description": "Database schema overview",
            "cypher": (
                "MATCH (n)\n"
                "RETURN labels(n)[0] as node_type, count(n) as count,\n"
                "       collect(DISTINCT n.type)[0..3] as sample_types\n"
                "ORDER BY count DESC LIMIT 20"
            ),
            "priority": 1,
            "params": {}
        }]
