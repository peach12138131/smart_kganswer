"""
JSON Schema 定义
定义各种 LLM 输出的结构化格式
"""

# 实体识别 Schema
entity_recognition_schema = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "实体名称"},
                    "type": {
                        "type": "string",
                        "enum": ["Company", "Product", "Location", "Event", "Person", "Technology"],
                        "description": "实体类型"
                    },
                    "confidence": {"type": "number", "description": "置信度 0-1"}
                },
                "required": ["name", "type"]
            },
            "description": "识别出的所有实体"
        },
        "intent": {
            "type": "string",
            "enum": [
                "entity_info",        # 查询单个实体信息
                "relation_query",     # 查询关系
                "list_query",         # 列举查询
                "count_query",        # 统计查询
                "exploration_query",  # 探索查询
                "comparison",         # 对比分析
                "event_query",        # 事件查询
                "general_question"    # 通用问题
            ],
            "description": "查询意图"
        },
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "提取的关键词（用于list_query等）"
        },
        "relation_types": {
            "type": "array",
            "items": {"type": "string"},
            "description": "涉及的关系类型（可选）"
        },
        "time_constraint": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string"},
                "end_date": {"type": "string"}
            },
            "description": "时间约束（可选）"
        },
        "event_keywords": {
            "type": "object",
            "properties": {
                "event_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "事件类型关键词（中文），如：事故、交付、订单、发布"
                },
                "domain_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "领域关键词（英文），如：private, business jet, charter, aviation"
                }
            },
            "description": "事件查询的关键词（用于文本搜索，仅event_query意图需要）"
        }
    },
    "required": ["intent"]
}


# 查询规划 Schema
query_plan_schema = {
    "type": "object",
    "properties": {
        "strategy": {
            "type": "string",
            "enum": [
                "direct_property",     # 直接查询实体属性
                "one_hop",            # 单跳关系
                "multi_hop",          # 多跳关系
                "path_finding",       # 路径查找
                "subgraph",           # 子图提取
                "pattern_match"       # 模式匹配
            ],
            "description": "查询策略"
        },
        "cypher_queries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "cypher": {"type": "string"},
                    "priority": {"type": "integer"}
                },
                "required": ["description", "cypher", "priority"]
            },
            "description": "生成的 Cypher 查询列表"
        },
        "max_results": {"type": "integer", "description": "最大结果数"},
        "reasoning": {"type": "string", "description": "规划推理过程"}
    },
    "required": ["strategy", "cypher_queries"]
}


# 答案生成的上下文格式（不需要 Schema，仅供参考）
answer_context_format = """
Question: {question}

Entities Identified:
{entities}

Query Strategy: {strategy}

Graph Results:
{graph_results}

Please generate a natural language answer based on the above information.
"""
