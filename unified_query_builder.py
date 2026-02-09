"""
统一查询构建器
基于意图动态生成所有类型的Cypher查询
"""

from typing import Dict, List, Optional
from kg_retriever import KGRetriever
import re


class UnifiedQueryBuilder:
    """统一查询构建器 - 处理所有类型的查询"""

    def __init__(self, kg_retriever: KGRetriever):
        self.kg_retriever = kg_retriever

        # 关键词到类别的映射（泛化设计）
        self.keyword_category_map = {
            # 航空基础设施
            "机场": ["Airport", "Airport Operator", "Location"],
            "airport": ["Airport", "Airport Operator", "Location"],

            # 商业实体
            "公司": ["Company"],
            "企业": ["Company"],
            "运营商": ["Company"],
            "company": ["Company"],
            "operator": ["Company"],

            # 产品
            "飞机": ["Product"],
            "aircraft": ["Product"],
            "plane": ["Product"],
            "型号": ["Product"],

            # 路线
            "航线": ["Route"],
            "路线": ["Route"],
            "route": ["Route"],

            # 地点
            "城市": ["Location"],
            "国家": ["Location"],
            "地区": ["Location"],
            "location": ["Location"],
            "city": ["Location"],

            # 事件
            "事故": ["Event"],
            "事件": ["Event"],
            "交付": ["Event"],
            "event": ["Event"],
        }

        # 排序关键词
        self.ranking_keywords = [
            "最火", "热门", "最多", "最受欢迎", "排名", "top", "前几",
            "最大", "主要", "最常", "最频繁"
        ]

    def build_query(self, intent_result: Dict, question: str) -> List[Dict]:
        """
        统一查询构建入口

        Args:
            intent_result: 意图分析结果
            question: 原始问题

        Returns:
            查询列表
        """
        intent = intent_result.get('intent')

        # 根据意图路由到不同的构建方法
        if intent == 'list_query':
            return self._build_list_query(intent_result, question)
        elif intent == 'count_query':
            return self._build_count_query(intent_result, question)
        elif intent == 'exploration_query':
            return self._build_exploration_query(intent_result, question)
        elif intent in ['entity_info', 'relation_query']:
            return self._build_entity_query(intent_result, question)
        else:
            # 默认：尝试智能推断
            return self._build_smart_query(intent_result, question)

    def _build_list_query(self, intent_result: Dict, question: str) -> List[Dict]:
        """
        构建列举查询

        示例："数据库中有哪些机场？"
        """
        keywords = intent_result.get('keywords', [])

        if not keywords:
            # 没有关键词，返回所有节点类型
            return self._build_schema_query()

        keyword = keywords[0]
        categories = self._map_keyword_to_categories(keyword)

        queries = []

        # 策略1：按类别精确查询
        if categories:
            for category in categories:
                cypher = """
                MATCH (n)
                WHERE $category IN labels(n)
                   OR n.type = $category
                RETURN DISTINCT n.name as name,
                       labels(n)[0] as label,
                       n.type as entity_type,
                       n.country as country
                ORDER BY n.name
                LIMIT 100
                """
                queries.append({
                    "cypher": cypher,
                    "params": {"category": category},
                    "description": f"List all {category} entities",
                    "priority": 1
                })

        # 策略2：模糊搜索（后备）
        cypher_fuzzy = """
        MATCH (n)
        WHERE toLower(n.name) CONTAINS toLower($keyword)
           OR toLower(coalesce(n.type, '')) CONTAINS toLower($keyword)
           OR ANY(label IN labels(n) WHERE toLower(label) CONTAINS toLower($keyword))
        RETURN DISTINCT n.name as name,
               labels(n)[0] as label,
               n.type as entity_type
        ORDER BY n.name
        LIMIT 100
        """
        queries.append({
            "cypher": cypher_fuzzy,
            "params": {"keyword": keyword},
            "description": f"Fuzzy search for '{keyword}'",
            "priority": 2
        })

        return queries

    def _build_count_query(self, intent_result: Dict, question: str) -> List[Dict]:
        """
        构建统计查询

        示例："有多少航线数据？"
        """
        keywords = intent_result.get('keywords', [])

        if not keywords:
            # 统计所有节点
            cypher = """
            MATCH (n)
            RETURN labels(n)[0] as node_type, count(n) as total
            ORDER BY total DESC
            """
            return [{
                "cypher": cypher,
                "params": {},
                "description": "Count all nodes by type",
                "priority": 1
            }]

        keyword = keywords[0]
        categories = self._map_keyword_to_categories(keyword)

        # 按类别统计
        cypher = """
        MATCH (n)
        WHERE $category IN labels(n)
           OR n.type = $category
           OR toLower(n.name) CONTAINS toLower($keyword)
        RETURN count(DISTINCT n) as total,
               labels(n)[0] as node_type
        """

        params = {
            "category": categories[0] if categories else "",
            "keyword": keyword
        }

        return [{
            "cypher": cypher,
            "params": params,
            "description": f"Count entities related to '{keyword}'",
            "priority": 1
        }]

    def _build_exploration_query(self, intent_result: Dict, question: str) -> List[Dict]:
        """
        构建探索查询

        示例："数据库里有什么数据？"
        """
        # 返回Schema概览
        cypher = """
        MATCH (n)
        RETURN labels(n)[0] as node_type,
               count(n) as count,
               collect(DISTINCT n.type)[0..3] as sample_types
        ORDER BY count DESC
        LIMIT 20
        """

        return [{
            "cypher": cypher,
            "params": {},
            "description": "Explore database schema and content",
            "priority": 1
        }]

    def _build_entity_query(self, intent_result: Dict, question: str) -> List[Dict]:
        """
        构建实体查询（有具体实体的情况）
        """
        entities = intent_result.get('entities', [])

        if not entities:
            # 没有实体，尝试提取关键词
            keywords = self._extract_keywords(question)
            if keywords:
                # 转换为list_query
                return self._build_list_query(
                    {"keywords": keywords, "intent": "list_query"},
                    question
                )
            return []

        queries = []

        for entity in entities:
            entity_name = entity['name']
            entity_type = entity.get('type', '')
            entity_aliases = entity.get('aliases', [entity_name])

            # 检查是否是排序查询
            is_ranking = self._is_ranking_query(question)

            # 预查询节点信息
            node_info = self._pre_query_node(entity_name, entity_aliases)

            if not node_info['exists']:
                print(f"[!] 实体 {entity_name} 不存在，尝试模糊搜索")
                # 模糊搜索
                queries.extend(self._build_fuzzy_entity_query(entity_name))
                continue

            # 生成智能查询
            if is_ranking:
                query = self._build_ranking_query(
                    entity_name, entity_aliases, node_info, question
                )
            else:
                query = self._build_standard_entity_query(
                    entity_name, entity_aliases, node_info
                )

            if query:
                queries.append(query)

        return queries

    def _build_ranking_query(
        self,
        entity_name: str,
        entity_aliases: List[str],
        node_info: Dict,
        question: str
    ) -> Optional[Dict]:
        """
        构建排序查询（如"最火的航线"）
        """
        # 从问题中推断关系类型
        relation_types = self._infer_relation_types(question, node_info)

        if not relation_types:
            return None

        # 选择最佳关系
        best_relation = relation_types[0]
        rel_type = best_relation['type']
        target_type = best_relation.get('target_type', '')

        # 查找排序字段
        sort_field = None
        if 'count' in best_relation.get('properties', []):
            sort_field = 'r.count'
        elif 'frequency' in best_relation.get('properties', []):
            sort_field = 'r.frequency'

        # 构建查询
        if sort_field:
            cypher = f"""
            MATCH (p {{name: $entity_name}})-[r:{rel_type}]->(t)
            RETURN t.name as name,
                   {sort_field} as frequency,
                   labels(t)[0] as type
            ORDER BY frequency DESC
            LIMIT 20
            """
        else:
            cypher = f"""
            MATCH (p {{name: $entity_name}})-[r:{rel_type}]->(t)
            RETURN t.name as name,
                   labels(t)[0] as type,
                   count(r) as frequency
            ORDER BY frequency DESC
            LIMIT 20
            """

        return {
            "cypher": cypher,
            "params": {"entity_name": entity_name},
            "description": f"Ranking query for {entity_name} - {rel_type}",
            "priority": 1
        }

    def _build_standard_entity_query(
        self,
        entity_name: str,
        entity_aliases: List[str],
        node_info: Dict
    ) -> Dict:
        """构建标准实体查询"""
        cypher = """
        MATCH (n {name: $entity_name})
        OPTIONAL MATCH (n)-[r]-(m)
        RETURN n,
               type(r) as relation_type,
               labels(m)[0] as target_type,
               m.name as target_name,
               properties(m) as target_props
        LIMIT 100
        """

        return {
            "cypher": cypher,
            "params": {"entity_name": entity_name},
            "description": f"Standard query for {entity_name}",
            "priority": 1
        }

    def _build_fuzzy_entity_query(self, entity_name: str) -> List[Dict]:
        """模糊实体查询"""
        cypher = """
        MATCH (n)
        WHERE toLower(n.name) CONTAINS toLower($search_term)
        OPTIONAL MATCH (n)-[r]-(m)
        RETURN n.name as name,
               labels(n)[0] as type,
               count(r) as relation_count
        ORDER BY relation_count DESC
        LIMIT 10
        """

        return [{
            "cypher": cypher,
            "params": {"search_term": entity_name},
            "description": f"Fuzzy search for '{entity_name}'",
            "priority": 1
        }]

    def _build_schema_query(self) -> List[Dict]:
        """构建Schema查询"""
        cypher = """
        MATCH (n)
        RETURN labels(n)[0] as node_type,
               count(n) as count
        ORDER BY count DESC
        """

        return [{
            "cypher": cypher,
            "params": {},
            "description": "Database schema overview",
            "priority": 1
        }]

    def _build_smart_query(self, intent_result: Dict, question: str) -> List[Dict]:
        """智能查询（当其他方法都不适用时）"""
        # 提取关键词
        keywords = self._extract_keywords(question)

        if keywords:
            return self._build_list_query(
                {"keywords": keywords, "intent": "list_query"},
                question
            )

        # 默认：探索查询
        return self._build_exploration_query(intent_result, question)

    # ========== 辅助方法 ==========

    def _map_keyword_to_categories(self, keyword: str) -> List[str]:
        """关键词映射到类别"""
        keyword_lower = keyword.lower()

        for key, categories in self.keyword_category_map.items():
            if key in keyword_lower or keyword_lower in key:
                return categories

        return []

    def _is_ranking_query(self, question: str) -> bool:
        """判断是否是排序查询"""
        question_lower = question.lower()
        return any(kw in question_lower for kw in self.ranking_keywords)

    def _extract_keywords(self, question: str) -> List[str]:
        """从问题中提取关键词"""
        keywords = []

        for keyword in self.keyword_category_map.keys():
            if keyword in question.lower():
                keywords.append(keyword)

        return keywords

    def _pre_query_node(self, entity_name: str, entity_aliases: List[str]) -> Dict:
        """预查询节点（检查存在性和关系）"""
        try:
            with self.kg_retriever.driver.session() as session:
                # 检查节点是否存在（不限类型）
                result = session.run("""
                    MATCH (n)
                    WHERE n.name IN $entity_names
                    RETURN n.name as name, labels(n)[0] as type
                    LIMIT 1
                """, entity_names=entity_aliases)

                record = result.single()
                if not record:
                    return {"exists": False}

                # 查询关系信息
                actual_name = record['name']
                result = session.run("""
                    MATCH (n {name: $entity_name})-[r]->(m)
                    RETURN type(r) as rel_type,
                           labels(m)[0] as target_type,
                           count(r) as count
                """, entity_name=actual_name)

                relations = {}
                for rec in result:
                    rel_type = rec['rel_type']
                    relations[rel_type] = {
                        'target_type': rec['target_type'],
                        'count': rec['count']
                    }

                    # 获取关系属性
                    props = self._get_relation_properties(actual_name, rel_type)
                    relations[rel_type]['properties'] = props

                return {
                    "exists": True,
                    "name": actual_name,
                    "relations": relations
                }

        except Exception as e:
            print(f"[X] 预查询失败: {e}")
            return {"exists": False}

    def _get_relation_properties(self, entity_name: str, rel_type: str) -> List[str]:
        """获取关系属性"""
        try:
            with self.kg_retriever.driver.session() as session:
                result = session.run(f"""
                    MATCH (n {{name: $entity_name}})-[r:{rel_type}]->()
                    RETURN properties(r) as props
                    LIMIT 1
                """, entity_name=entity_name)

                record = result.single()
                if record and record['props']:
                    return list(record['props'].keys())
        except:
            pass

        return []

    def _infer_relation_types(self, question: str, node_info: Dict) -> List[Dict]:
        """从问题推断相关的关系类型"""
        relations = node_info.get('relations', {})

        # 关键词到关系类型的映射
        keyword_relation_map = {
            "航线": ["FLEW", "HAS_ROUTE"],
            "route": ["FLEW", "HAS_ROUTE"],
            "供应商": ["SUPPLIES"],
            "supplier": ["SUPPLIES"],
            "制造": ["MANUFACTURES"],
        }

        # 匹配关键词
        relevant_relations = []
        question_lower = question.lower()

        for keyword, rel_types in keyword_relation_map.items():
            if keyword in question_lower:
                for rel_type in rel_types:
                    if rel_type in relations:
                        relevant_relations.append({
                            "type": rel_type,
                            **relations[rel_type]
                        })

        # 如果没有匹配，返回所有关系（按数量排序）
        if not relevant_relations:
            relevant_relations = [
                {"type": rel_type, **info}
                for rel_type, info in relations.items()
            ]
            relevant_relations.sort(key=lambda x: x.get('count', 0), reverse=True)

        return relevant_relations
