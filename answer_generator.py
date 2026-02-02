"""
答案生成器
基于图谱检索结果生成自然语言答案
"""

import json
from typing import Dict, Any, Generator, Tuple
from llm_client import LLMClient


class AnswerGenerator:
    """答案生成器"""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def generate_stream(
        self,
        question: str,
        recognition_result: Dict,
        query_plan: Dict,
        graph_results: Dict
    ) -> Generator[Tuple[str, str], None, None]:
        """
        流式生成答案

        Args:
            question: 原始问题
            recognition_result: 实体识别结果
            query_plan: 查询计划
            graph_results: 图谱检索结果

        Yields:
            (chunk, full_answer):
                - 流式阶段: (文本片段, "")
                - 最后一次: ("", 完整答案)
        """
        prompt = self._build_answer_prompt()
        context = self._build_context(
            question,
            recognition_result,
            query_plan,
            graph_results
        )

        for chunk, full_response in self.llm_client.query_stream(
            prompt=prompt,
            context=context,
            model="claude-sonnet-4-5-20250929",  # 使用大模型生成答案
            temperature=0.3,
            max_tokens=4096
        ):
            yield (chunk, full_response)

    def _build_context(
        self,
        question: str,
        recognition_result: Dict,
        query_plan: Dict,
        graph_results: Dict
    ) -> str:
        """
        构建上下文

        Returns:
            格式化的上下文字符串
        """
        # 简化实体信息
        entities_str = ", ".join([
            f"{e['name']} ({e['type']})"
            for e in recognition_result.get('entities', [])
        ])

        # 简化图谱结果（按类型分组，确保公司数据完整）
        results_summary = []
        for result in graph_results.get('results', []):
            if result['count'] > 0:
                # 按target_type分组
                grouped_data = {}
                for item in result['data']:
                    target_type = item.get('target_type', 'Unknown')
                    if target_type not in grouped_data:
                        grouped_data[target_type] = []
                    grouped_data[target_type].append(item)

                # 为每个类型取样本（公司类型全部保留，其他类型取前3个）
                sampled_data = []
                for target_type, items in grouped_data.items():
                    if target_type == 'Company':
                        sampled_data.extend(items)  # 公司全部保留
                    else:
                        sampled_data.extend(items)  # 其他类型取前3个
                print(f"优化后实体的结果 {sampled_data}")
                results_summary.append({
                    "description": result['query_description'],
                    "total_count": result['count'],
                    "by_type": {k: len(v) for k, v in grouped_data.items()},
                    "data": sampled_data
                })

        context = f"""
Question: {question}

Identified Entities: {entities_str}
Query Intent: {recognition_result.get('intent', 'unknown')}

Query Strategy: {query_plan.get('strategy', 'unknown')}

Graph Query Results:
{json.dumps(results_summary, indent=2, ensure_ascii=False)}

Total Results Found: {graph_results.get('total_results', 0)}
"""
        return context

    def _build_answer_prompt(self) -> str:
        """构建答案生成提示词"""
        return """You are a professional business aviation knowledge assistant.

Your task:
1. Analyze the user's question and the graph query results
2. Generate a clear, accurate, and professional answer
3. Cite specific entities and relationships from the graph results
4. If no relevant data found, honestly say so
5. Use proper formatting (bullet points, numbers when appropriate)

CRITICAL Guidelines:
- **ALWAYS list ALL companies/entities found in the data - do NOT omit any**
- When the question asks "which companies", list EVERY company in the results
- Group results by type (Company, Product, Technology, etc.)
- Be concise but comprehensive - include all relevant entities
- Use data from graph results to support your answer
- Mention entity types and relationships clearly (e.g., "NetJets (Company) OPERATES...")
- If multiple results, organize them logically by type
- For comparisons, use side-by-side format
- For events, mention dates if available
- If data is incomplete, acknowledge limitations

Example 1:
Q: "What aircraft does NetJets operate?"
Context: [Graph shows NetJets OPERATES G650, Global 7500...]
A: Based on the knowledge graph, NetJets operates the following aircraft:
   - Gulfstream G650 (Business Jet)
   - Bombardier Global 7500 (Business Jet)
   - ...

Example 2:
Q: "Who manufactures the G650?"
Context: [Graph shows Gulfstream MANUFACTURES G650]
A: The Gulfstream G650 is manufactured by Gulfstream Aerospace (Manufacturer).

Example 3:
Q: "Find connection between NetJets and Starlink"
Context: [Graph shows NetJets USES Starlink Aviation]
A: NetJets has a connection to Starlink through technology adoption:
   - NetJets (Operator) USES Starlink Aviation (Technology)

   This indicates that NetJets has implemented Starlink's satellite connectivity service in their fleet.

Now generate an answer based on the provided context:
"""
