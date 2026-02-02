"""
LLM 客户端封装
支持流式和非流式调用
"""

import requests
import json
import re
from typing import Generator, Tuple, Optional, Dict, Any
from config import claude_key


class LLMClient:
    """统一的 LLM 调用客户端"""

    def __init__(
        self,
        api_key: str = claude_key,
        base_url: str = "https://api.anthropic.com/v1"
    ):
        self.api_key = api_key
        self.base_url = base_url

    def _build_headers(self) -> Dict[str, str]:
        """构建API请求头"""
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01"
        }

    def _build_user_content(self, prompt: str, context: str, json_schema: Optional[Dict]) -> str:
        """构建用户消息内容"""
        if json_schema:
            return (
                f"{prompt}\n\n"
                f"IMPORTANT: Output ONLY valid JSON in this exact format, "
                f"with no markdown code blocks, no explanations, no extra text:\n"
                f"{json.dumps(json_schema, indent=2)}\n\n"
                f"Data to process:\n{context}"
            )
        return f"{prompt}\n\n{context}" if context else prompt

    def _build_payload(self, user_content: str, model: str, max_tokens: int,
                       temperature: float, stream: bool = False) -> Dict[str, Any]:
        """构建API请求体"""
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": user_content}],
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        if stream:
            payload["stream"] = True
        return payload

    def query_stream(
        self,
        prompt: str,
        context: str = "",
        model: str = "claude-sonnet-4-5-20250929",
        max_tokens: int = 4096,
        temperature: float = 0.0,
        json_schema: Optional[Dict] = None
    ) -> Generator[Tuple[str, Optional[str]], None, None]:
        """
        流式查询 LLM

        Args:
            prompt: 提示词
            context: 上下文内容
            model: 模型名称
            max_tokens: 最大token数
            temperature: 温度
            json_schema: JSON Schema（如果需要结构化输出）

        Yields:
            (chunk, full_response):
                - 流式阶段: (文本片段, None)
                - 最后一次: ("", 完整内容)
        """
        url = f"{self.base_url}/messages"
        headers = self._build_headers()
        user_content = self._build_user_content(prompt, context, json_schema)
        payload = self._build_payload(user_content, model, max_tokens, temperature, stream=True)

        full_response = ""

        try:
            response = requests.post(url, headers=headers, json=payload, stream=True)
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    line_text = line.decode('utf-8')

                    if not line_text.startswith('data: '):
                        continue

                    json_str = line_text[6:]

                    if json_str == '[DONE]':
                        break

                    try:
                        event_data = json.loads(json_str)

                        if event_data.get('type') == 'content_block_delta':
                            delta = event_data.get('delta', {})
                            if delta.get('type') == 'text_delta':
                                text_chunk = delta.get('text', '')
                                if text_chunk:
                                    full_response += text_chunk
                                    yield (text_chunk, None)

                    except json.JSONDecodeError:
                        continue

            # 最后返回完整内容
            if full_response:
                if json_schema:
                    # 清理 JSON
                    cleaned_json = self._clean_json_response(full_response)
                    yield ("", cleaned_json)
                else:
                    yield ("", full_response)
            else:
                yield ("", None)

        except requests.exceptions.RequestException as e:
            print(f"[X] LLM API 请求失败: {e}")
            yield ("", None)

    def query_sync(
        self,
        prompt: str,
        context: str = "",
        model: str = "claude-haiku-4-5-20251001",  # 默认用小模型
        max_tokens: int = 4096,
        temperature: float = 0.0,
        json_schema: Optional[Dict] = None
    ) -> Optional[str]:
        """
        同步查询 LLM（用于快速的结构化任务）

        Returns:
            完整响应内容（字符串或JSON字符串）
        """
        url = f"{self.base_url}/messages"
        headers = self._build_headers()
        user_content = self._build_user_content(prompt, context, json_schema)
        payload = self._build_payload(user_content, model, max_tokens, temperature, stream=False)

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()

            result = response.json()

            if result.get('content') and len(result['content']) > 0:
                full_response = result['content'][0].get('text', '')

                if json_schema:
                    return self._clean_json_response(full_response)
                else:
                    return full_response

            return None

        except requests.exceptions.RequestException as e:
            print(f"[X] LLM API request failed: {e}")
            import traceback
            traceback.print_exc()
            return None
        except Exception as e:
            print(f"[X] Unexpected error: {e}")
            import traceback
            traceback.print_exc()
            return None

    @staticmethod
    def _clean_json_response(text: str) -> str:
        """清理 JSON 响应（移除 markdown 标记等）"""
        # 尝试提取 ```json ... ``` 代码块
        json_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
        if json_match:
            json_text = json_match.group(1).strip()
        else:
            json_text = text.strip()

        # 修复转义字符
        json_text = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', json_text)

        return json_text
