"""
查询改写模块 - 实体别名扩展

从知识库动态发现别名 + 静态别名库补充。
删除了 LLM 扩展实体步骤（减少延迟，别名发现已足够）。
"""

import re
from typing import Dict, List, Tuple
from llm_client import LLMClient


class QueryRewriter:

    def __init__(self, llm_client: LLMClient, kg_retriever=None):
        self.llm_client = llm_client
        self.kg_retriever = kg_retriever

        self.product_aliases = {
            'Global 7500': ['Global 7500', 'G7500', '7500', 'Bombardier Global 7500'],
            'Global 8000': ['Global 8000', 'G8000', '8000', 'Bombardier Global 8000'],
            'Global 6500': ['Global 6500', 'G6500', '6500', 'Bombardier Global 6500'],
            'Global 5500': ['Global 5500', 'G5500', '5500', 'Bombardier Global 5500'],
            'Challenger 350': ['Challenger 350', 'CL350', 'Bombardier Challenger 350'],
            'Challenger 650': ['Challenger 650', 'CL650', 'Bombardier Challenger 650'],
            'G650':   ['G650', 'Gulfstream G650', 'GVI'],
            'G650ER': ['G650ER', 'Gulfstream G650ER'],
            'G700':   ['G700', 'Gulfstream G700'],
            'G800':   ['G800', 'Gulfstream G800'],
            'G500':   ['G500', 'Gulfstream G500'],
            'G600':   ['G600', 'Gulfstream G600'],
            'Falcon 8X':   ['Falcon 8X',   'F8X',   'Dassault Falcon 8X'],
            'Falcon 7X':   ['Falcon 7X',   'F7X',   'Dassault Falcon 7X'],
            'Falcon 6X':   ['Falcon 6X',   'F6X',   'Dassault Falcon 6X'],
            'Falcon 2000': ['Falcon 2000', 'F2000', 'Dassault Falcon 2000'],
        }

        self.company_aliases = {
            'Bombardier': ['Bombardier', 'Bombardier Aerospace', '庞巴迪'],
            'Gulfstream': ['Gulfstream', 'Gulfstream Aerospace', '湾流'],
            'Dassault':   ['Dassault', 'Dassault Aviation', '达索'],
            'NetJets':    ['NetJets', 'Net Jets'],
            'Flexjet':    ['Flexjet', 'Flex Jet'],
        }

    def rewrite_query(self, question: str, recognition_result: Dict) -> Tuple[Dict, List[str]]:
        """为每个实体扩展别名（KG动态发现 + 静态库补充）"""
        entities = recognition_result.get('entities', [])
        rewrite_notes = []

        for entity in entities:
            kg_aliases = self._discover_aliases_from_kg(entity['name'], entity['type'])
            static_aliases = self._get_entity_aliases(entity['name'], entity['type'])
            all_aliases = list(set(kg_aliases + static_aliases))

            if len(all_aliases) > 1:
                entity['aliases'] = all_aliases
                rewrite_notes.append(f"{entity['name']} 别名：{', '.join(all_aliases[:3])}")

        return recognition_result, rewrite_notes

    def _get_entity_aliases(self, name: str, entity_type: str) -> List[str]:
        """静态别名库查找"""
        if entity_type == 'Product':
            if name in self.product_aliases:
                return self.product_aliases[name]
            for canonical, aliases in self.product_aliases.items():
                if name in aliases or name.lower() in canonical.lower():
                    return aliases
        elif entity_type == 'Company':
            if name in self.company_aliases:
                return self.company_aliases[name]
            for canonical, aliases in self.company_aliases.items():
                if name in aliases:
                    return aliases
        return [name]

    def _discover_aliases_from_kg(self, entity_name: str, entity_type: str) -> List[str]:
        """从知识库动态发现别名"""
        if not self.kg_retriever:
            return [entity_name]
        try:
            similar = self.kg_retriever.fuzzy_search_entity(entity_name, limit=5)
            aliases = [entity_name]
            for e in similar:
                n = e.get('name', '')
                labels = e.get('labels', [])
                if labels and entity_type not in labels:
                    continue
                if n and n not in aliases and self._is_likely_alias(entity_name, n):
                    aliases.append(n)
            if len(aliases) == 1:
                aliases.extend(self._query_entity_alias_property(entity_name, entity_type))
            return list(set(aliases))
        except Exception as ex:
            print(f"[!] 别名发现失败: {ex}")
            return [entity_name]

    def _is_likely_alias(self, name1: str, name2: str) -> bool:
        n1, n2 = name1.lower(), name2.lower()
        if n1 in n2 or n2 in n1:
            return True
        nums1 = re.findall(r'\d+', name1)
        nums2 = re.findall(r'\d+', name2)
        return bool(nums1 and nums2 and nums1 == nums2)

    def _query_entity_alias_property(self, entity_name: str, entity_type: str) -> List[str]:
        """查询节点的 alias/aliases 属性"""
        if not self.kg_retriever:
            return []
        try:
            with self.kg_retriever.driver.session() as session:
                result = session.run(
                    f"MATCH (n:{entity_type}) WHERE n.name = $name "
                    "RETURN properties(n) as props LIMIT 1",
                    name=entity_name
                )
                record = result.single()
                if record:
                    props = record['props']
                    aliases = []
                    for field in ['alias', 'aliases', 'alternate_name', 'alternate_names', 'aka']:
                        v = props.get(field)
                        if v:
                            aliases.extend([v] if isinstance(v, str) else v)
                    return aliases
        except Exception as ex:
            print(f"[!] 查询别名属性失败: {ex}")
        return []
