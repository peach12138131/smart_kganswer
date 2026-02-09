"""
知识图谱检索器
执行 Cypher 查询并返回结构化结果
"""

from neo4j import GraphDatabase
from typing import List, Dict, Any, Optional
import json


class KGRetriever:
    """Neo4j 知识图谱检索器"""

    def __init__(self, uri: str, username: str, password: str):
        """
        初始化 Neo4j 连接

        Args:
            uri: Neo4j URI 
            username: 用户名
            password: 密码
        """
        self.driver = GraphDatabase.driver(uri, auth=(username, password))
        print(f"[V] 已连接到 Neo4j: {uri}")

    def close(self):
        """关闭连接"""
        if self.driver:
            self.driver.close()

    def execute_query_plan(self, query_plan: Dict) -> Dict[str, Any]:
        """
        执行查询计划

        Args:
            query_plan: 查询计划（来自 QueryPlanner）

        Returns:
            {
                "strategy": "multi_hop",
                "results": [
                    {
                        "query_description": "...",
                        "data": [...],
                        "count": 10
                    }
                ],
                "total_results": 25
            }
        """
        cypher_queries = query_plan.get('cypher_queries', [])

        # 按优先级排序
        cypher_queries.sort(key=lambda x: x.get('priority', 999))

        results = []
        total_count = 0

        with self.driver.session() as session:
            for query_info in cypher_queries:
                cypher = query_info['cypher']
                description = query_info['description']
                params = query_info.get('params', {})

                try:
                    # 执行查询
                    result = session.run(cypher, params)
                    records = list(result)

                    # 转换为可序列化格式
                    data = self._serialize_records(records)

                    results.append({
                        "query_description": description,
                        "cypher": cypher,  # 添加Cypher查询语句
                        "params": params,  # 添加查询参数
                        "data": data,
                        "count": len(data)
                    })

                    total_count += len(data)

                except Exception as e:
                    print(f"[X] 查询执行失败: {description}")
                    print(f"   Cypher: {cypher}")
                    print(f"   错误: {str(e)}")
                    results.append({
                        "query_description": description,
                        "cypher": cypher,  # 添加Cypher查询语句
                        "params": params,  # 添加查询参数
                        "data": [],
                        "count": 0,
                        "error": str(e)
                    })

        return {
            "strategy": query_plan.get('strategy', 'unknown'),
            "results": results,
            "total_results": total_count
        }

    def _serialize_records(self, records: List) -> List[Dict]:
        """
        将 Neo4j 记录序列化为字典列表

        Args:
            records: Neo4j 查询结果

        Returns:
            可序列化的字典列表
        """
        serialized = []

        for record in records:
            row = {}

            for key in record.keys():
                value = record[key]
                row[key] = self._serialize_value(value)

            serialized.append(row)

        return serialized

    def _serialize_value(self, value: Any) -> Any:
        """
        序列化单个值（包括 Neo4j 特殊类型）

        Args:
            value: Neo4j 返回的值

        Returns:
            可序列化的值
        """
        # Neo4j Node
        if hasattr(value, 'labels') and hasattr(value, 'items'):
            return {
                "type": "Node",
                "labels": list(value.labels),
                "properties": {k: self._serialize_value(v) for k, v in value.items()}
            }

        # Neo4j Relationship
        if hasattr(value, 'type') and hasattr(value, 'start_node'):
            return {
                "type": "Relationship",
                "rel_type": value.type,
                "properties": {k: self._serialize_value(v) for k, v in value.items()}
            }

        # Neo4j Path
        if hasattr(value, 'nodes') and hasattr(value, 'relationships'):
            return {
                "type": "Path",
                "nodes": [self._serialize_value(n) for n in value.nodes],
                "relationships": [self._serialize_value(r) for r in value.relationships]
            }

        # List
        if isinstance(value, list):
            return [self._serialize_value(v) for v in value]

        # Dict
        if isinstance(value, dict):
            return {k: self._serialize_value(v) for k, v in value.items()}

        # Date/DateTime
        if hasattr(value, 'isoformat'):
            return value.isoformat()

        # 其他类型直接返回
        return value

    def fuzzy_search_entity(self, query_text: str, limit: int = 5) -> List[str]:
        """
        模糊搜索实体名称

        Args:
            query_text: 搜索文本
            limit: 返回数量

        Returns:
            匹配的实体名称列表
        """
        with self.driver.session() as session:
            result = session.run("""
                MATCH (n)
                WHERE toLower(coalesce(n.name, n.id)) CONTAINS toLower($search_text)
                RETURN DISTINCT coalesce(n.name, n.id) as identifier, labels(n) as labels
                LIMIT $limit
            """, search_text=query_text, limit=limit)

            entities = []
            for record in result:
                entities.append({
                    "name": record['identifier'],
                    "labels": list(record['labels'])
                })

            return entities

    def get_entity_neighbors(
        self,
        entity_name: str,
        relation_types: Optional[List[str]] = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """
        获取实体的邻居节点（通用方法）

        Args:
            entity_name: 实体名称
            relation_types: 关系类型列表（可选）
            limit: 最大结果数

        Returns:
            邻居节点信息
        """
        with self.driver.session() as session:
            if relation_types:
                rel_filter = "|".join(relation_types)
                cypher = f"""
                    MATCH (n {{name: $entity_name}})-[r:{rel_filter}]->(m)
                    RETURN type(r) as relation_type, labels(m)[0] as target_type,
                           coalesce(m.name, m.id) as target_name, properties(m) as target_props
                    LIMIT $limit
                """
            else:
                cypher = """
                    MATCH (n {name: $entity_name})-[r]->(m)
                    RETURN type(r) as relation_type, labels(m)[0] as target_type,
                           coalesce(m.name, m.id) as target_name, properties(m) as target_props
                    LIMIT $limit
                """

            result = session.run(cypher, entity_name=entity_name, limit=limit)
            records = list(result)

            return {
                "entity": entity_name,
                "neighbors": self._serialize_records(records)
            }
