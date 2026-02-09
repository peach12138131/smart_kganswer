"""
查询改写模块
使用 LLM 智能扩展和规范化实体名称
"""

import json
from typing import Dict, List, Optional, Tuple
from llm_client import LLMClient


class QueryRewriter:
    """智能查询改写器"""

    def __init__(self, llm_client: LLMClient, kg_retriever=None):
        self.llm_client = llm_client
        self.kg_retriever = kg_retriever

        # 产品型号别名库（静态映射 + 动态扩展）
        self.product_aliases = {
            # Bombardier产品线
            'Global 7500': ['Global 7500', 'G7500', '7500', 'Bombardier Global 7500'],
            'Global 8000': ['Global 8000', 'G8000', '8000', 'Bombardier Global 8000'],
            'Global 6500': ['Global 6500', 'G6500', '6500', 'Bombardier Global 6500'],
            'Global 5500': ['Global 5500', 'G5500', '5500', 'Bombardier Global 5500'],
            'Challenger 350': ['Challenger 350', 'CL350', 'Bombardier Challenger 350'],
            'Challenger 650': ['Challenger 650', 'CL650', 'Bombardier Challenger 650'],

            # Gulfstream产品线
            'G650': ['G650', 'Gulfstream G650', 'GVI'],
            'G650ER': ['G650ER', 'Gulfstream G650ER'],
            'G700': ['G700', 'Gulfstream G700'],
            'G800': ['G800', 'Gulfstream G800'],
            'G500': ['G500', 'Gulfstream G500'],
            'G600': ['G600', 'Gulfstream G600'],

            # Dassault产品线
            'Falcon 8X': ['Falcon 8X', 'F8X', 'Dassault Falcon 8X'],
            'Falcon 7X': ['Falcon 7X', 'F7X', 'Dassault Falcon 7X'],
            'Falcon 6X': ['Falcon 6X', 'F6X', 'Dassault Falcon 6X'],
            'Falcon 2000': ['Falcon 2000', 'F2000', 'Dassault Falcon 2000'],
        }

        # 公司别名库
        self.company_aliases = {
            'Bombardier': ['Bombardier', 'Bombardier Aerospace', '庞巴迪'],
            'Gulfstream': ['Gulfstream', 'Gulfstream Aerospace', '湾流'],
            'Dassault': ['Dassault', 'Dassault Aviation', '达索'],
            'NetJets': ['NetJets', 'Net Jets'],
            'Flexjet': ['Flexjet', 'Flex Jet'],
        }

    def rewrite_query(
        self,
        question: str,
        recognition_result: Dict
    ) -> Tuple[Dict, List[str]]:
        """
        改写查询，扩展和规范化实体（动态+智能）

        Args:
            question: 原始问题
            recognition_result: 实体识别结果

        Returns:
            (扩展后的识别结果, 改写说明列表)
        """
        entities = recognition_result.get('entities', [])
        rewrite_notes = []

        # 使用LLM进行智能扩展
        expanded_entities = self._llm_expand_entities(question, entities)

        if expanded_entities:
            # 合并原实体和扩展实体，去重
            all_entities = entities + expanded_entities
            unique_entities = self._deduplicate_entities(all_entities)

            # 更新识别结果
            recognition_result['entities'] = unique_entities

            # 记录扩展信息
            new_entity_names = [e['name'] for e in expanded_entities]
            if new_entity_names:
                rewrite_notes.append(
                    f"查询扩展：{', '.join(new_entity_names)}"
                )

        # 为每个实体动态发现别名（优先使用知识库）
        for entity in recognition_result['entities']:
            # 1. 先尝试从知识库动态发现别名
            kg_aliases = self._discover_aliases_from_kg(entity['name'], entity['type'])

            # 2. 再使用静态别名库作为补充
            static_aliases = self._get_entity_aliases(entity['name'], entity['type'])

            # 3. 合并并去重
            all_aliases = list(set(kg_aliases + static_aliases))

            if all_aliases and len(all_aliases) > 1:
                entity['aliases'] = all_aliases
                # 只显示前3个别名
                display_aliases = all_aliases[:3]
                if len(all_aliases) > 3:
                    display_aliases.append(f"等{len(all_aliases)}个")
                rewrite_notes.append(
                    f"{entity['name']} 别名：{', '.join(display_aliases)}"
                )

        return recognition_result, rewrite_notes

    def _llm_expand_entities(
        self,
        question: str,
        entities: List[Dict]
    ) -> List[Dict]:
        """
        使用LLM智能扩展实体

        例如："庞巴迪 7500" → 识别出需要添加 "Global 7500" 实体
        """
        if not entities:
            return []

        prompt = self._build_expansion_prompt()

        context = f"""
Question: {question}

Recognized Entities:
{json.dumps(entities, indent=2, ensure_ascii=False)}

Product Aliases Knowledge:
{self._get_product_aliases_summary()}

Company Aliases Knowledge:
{self._get_company_aliases_summary()}
"""

        try:
            response = self.llm_client.query_sync(
                prompt=prompt,
                context=context,
                model="claude-haiku-4-5-20251001",
                temperature=0.0,
                json_schema={
                    "type": "object",
                    "properties": {
                        "additional_entities": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "type": {"type": "string"},
                                    "confidence": {"type": "number"},
                                    "reason": {"type": "string"}
                                },
                                "required": ["name", "type", "confidence"]
                            }
                        },
                        "reasoning": {"type": "string"}
                    },
                    "required": ["additional_entities"]
                }
            )

            if response:
                result = json.loads(response)
                additional = result.get('additional_entities', [])

                # 过滤低置信度的实体
                return [e for e in additional if e.get('confidence', 0) >= 0.7]

        except Exception as e:
            print(f"[!] 实体扩展失败: {e}")

        return []

    def _get_entity_aliases(self, entity_name: str, entity_type: str) -> List[str]:
        """获取实体的所有别名"""
        aliases = []

        if entity_type == 'Product':
            # 先查找完全匹配
            if entity_name in self.product_aliases:
                return self.product_aliases[entity_name]

            # 再查找部分匹配（如 "7500" 匹配 "Global 7500"）
            for canonical_name, alias_list in self.product_aliases.items():
                if entity_name in alias_list:
                    return alias_list
                # 模糊匹配（如 "7500" 在 "Global 7500" 中）
                if entity_name.lower() in canonical_name.lower():
                    return alias_list

        elif entity_type == 'Company':
            if entity_name in self.company_aliases:
                return self.company_aliases[entity_name]

            # 部分匹配
            for canonical_name, alias_list in self.company_aliases.items():
                if entity_name in alias_list:
                    return alias_list

        # 如果没有找到别名，至少返回自己
        return [entity_name]

    def _deduplicate_entities(self, entities: List[Dict]) -> List[Dict]:
        """去重实体列表（基于名称和类型）"""
        seen = set()
        unique = []

        for entity in entities:
            key = (entity['name'].lower(), entity['type'])
            if key not in seen:
                seen.add(key)
                unique.append(entity)

        return unique

    def _build_expansion_prompt(self) -> str:
        """构建实体扩展提示词"""
        return """You are an entity expansion expert for business aviation queries.

Your task:
Analyze the user's question and the recognized entities, then determine if additional entities should be added to improve query accuracy.

Common expansion scenarios:

1. **Product Model Expansion**:
   - "庞巴迪 7500" or "Bombardier 7500" → ADD "Global 7500" (Product)
   - User mentions company + model number → ADD full product name
   - User mentions short model name → ADD company + full product name

2. **Company Expansion**:
   - "庞巴迪" (Chinese) → Already recognized as "Bombardier" (Company)
   - Short name → ADD full company name if needed

3. **Related Entity Expansion**:
   - User asks about "航线" (routes) → Keep existing entities, query will find routes via relationships

Important Rules:
- Only add entities that are DIRECTLY mentioned or strongly implied in the question
- Do NOT add entities based on speculation or general knowledge
- If the question is "庞巴迪 global 7500最火的几条航线", and entities are ["Bombardier", "Global 7500"], NO NEED to add more entities
- If the question is "庞巴迪 7500最火的几条航线", and entities are ["Bombardier"], MUST add "Global 7500" (Product)
- Confidence should be 0.9+ for direct mentions, 0.7-0.9 for strong implications

Examples:

Q: "庞巴迪 7500最火的几条航线"
Entities: [{"name": "Bombardier", "type": "Company"}]
A: {
  "additional_entities": [
    {"name": "Global 7500", "type": "Product", "confidence": 0.95, "reason": "7500 refers to Global 7500, Bombardier's flagship model"}
  ],
  "reasoning": "User mentions '庞巴迪 7500' which is short for 'Bombardier Global 7500'. Added full product name."
}

Q: "湾流 G650 和 达索 Falcon 8X 对比"
Entities: [{"name": "Gulfstream", "type": "Company"}, {"name": "G650", "type": "Product"}, {"name": "Dassault", "type": "Company"}, {"name": "Falcon 8X", "type": "Product"}]
A: {
  "additional_entities": [],
  "reasoning": "All necessary entities already recognized. No expansion needed."
}

Q: "NetJets 用的最多的飞机"
Entities: [{"name": "NetJets", "type": "Company"}]
A: {
  "additional_entities": [],
  "reasoning": "User asks about aircraft used by NetJets. The query will find related products via relationships. No specific product name mentioned."
}

Now analyze the following:
"""

    def _get_product_aliases_summary(self) -> str:
        """获取产品别名摘要（用于LLM上下文）"""
        summary = []
        for canonical, aliases in list(self.product_aliases.items())[:10]:
            summary.append(f"  - {canonical}: {', '.join(aliases[:3])}")
        return "\n".join(summary)

    def _get_company_aliases_summary(self) -> str:
        """获取公司别名摘要（用于LLM上下文）"""
        summary = []
        for canonical, aliases in self.company_aliases.items():
            summary.append(f"  - {canonical}: {', '.join(aliases)}")
        return "\n".join(summary)

    def _discover_aliases_from_kg(self, entity_name: str, entity_type: str) -> List[str]:
        """
        从知识库动态发现实体别名（智能方法）

        策略：
        1. 使用模糊搜索找到相似实体
        2. 查询实体的所有属性（name, alias, alternate_name等）
        3. 返回所有可能的别名

        Args:
            entity_name: 实体名称
            entity_type: 实体类型

        Returns:
            别名列表
        """
        if not self.kg_retriever:
            return [entity_name]

        try:
            # 1. 模糊搜索相关实体
            similar_entities = self.kg_retriever.fuzzy_search_entity(entity_name, limit=5)

            aliases = [entity_name]  # 至少包含自己

            # 2. 从搜索结果中提取别名
            for entity in similar_entities:
                entity_labels = entity.get('labels', [])
                entity_entity_name = entity.get('name', '')

                # 只考虑同类型的实体
                if entity_type in entity_labels or not entity_labels:
                    if entity_entity_name and entity_entity_name not in aliases:
                        # 判断是否是真正的别名（简单相似度检查）
                        if self._is_likely_alias(entity_name, entity_entity_name):
                            aliases.append(entity_entity_name)

            # 3. 尝试查询该实体的直接属性（如果存在alias字段）
            if len(aliases) == 1:  # 如果还没找到别名
                aliases.extend(self._query_entity_alias_property(entity_name, entity_type))

            return list(set(aliases))  # 去重

        except Exception as e:
            print(f"[!] 从知识库发现别名失败: {e}")
            return [entity_name]

    def _is_likely_alias(self, name1: str, name2: str) -> bool:
        """
        判断两个名称是否可能是别名

        简单规则：
        1. 包含关系（Global 7500 vs Bombardier Global 7500）
        2. 数字型号匹配（7500 vs Global 7500）
        3. 公司名称匹配（Bombardier vs Bombardier Aerospace）
        """
        name1_lower = name1.lower()
        name2_lower = name2.lower()

        # 包含关系
        if name1_lower in name2_lower or name2_lower in name1_lower:
            return True

        # 提取数字
        import re
        numbers1 = re.findall(r'\d+', name1)
        numbers2 = re.findall(r'\d+', name2)

        # 数字匹配
        if numbers1 and numbers2 and numbers1 == numbers2:
            return True

        return False

    def _query_entity_alias_property(self, entity_name: str, entity_type: str) -> List[str]:
        """
        查询实体的alias属性（如果知识库中有的话）

        Args:
            entity_name: 实体名称
            entity_type: 实体类型

        Returns:
            别名列表
        """
        if not self.kg_retriever:
            return []

        try:
            with self.kg_retriever.driver.session() as session:
                # 查询实体的所有属性，寻找可能的别名字段
                result = session.run(f"""
                    MATCH (n:{entity_type})
                    WHERE n.name = $entity_name
                    RETURN properties(n) as props
                    LIMIT 1
                """, entity_name=entity_name)

                record = result.single()
                if record:
                    props = record['props']
                    aliases = []

                    # 常见的别名字段名
                    alias_fields = ['alias', 'aliases', 'alternate_name', 'alternate_names',
                                   'aka', 'also_known_as', 'short_name']

                    for field in alias_fields:
                        if field in props and props[field]:
                            value = props[field]
                            # 处理字符串或列表
                            if isinstance(value, str):
                                aliases.append(value)
                            elif isinstance(value, list):
                                aliases.extend(value)

                    return aliases

        except Exception as e:
            print(f"[!] 查询实体属性失败: {e}")

        return []
