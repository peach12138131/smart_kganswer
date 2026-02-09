"""
公共工具函数
提取常用的查询构建、参数处理等功能
"""

from typing import Dict, List, Optional


def build_time_filter(time_constraint: Dict) -> str:
    """
    构建Cypher时间过滤条件

    Args:
        time_constraint: {"start_date": "2025-01-01", "end_date": "2025-12-31"}

    Returns:
        Cypher时间过滤片段，如 "AND e.date >= date($start_date) AND e.date <= date($end_date)"
    """
    # 支持多种键名
    start_date = time_constraint.get('start') or time_constraint.get('start_date')
    end_date = time_constraint.get('end') or time_constraint.get('end_date')

    if start_date and end_date:
        return "AND e.date >= date($start_date) AND e.date <= date($end_date)"
    elif start_date:
        return "AND e.date >= date($start_date)"
    elif end_date:
        return "AND e.date <= date($end_date)"
    return ""


def extract_time_params(time_constraint: Dict) -> Dict:
    """
    提取时间参数

    Args:
        time_constraint: 时间约束字典

    Returns:
        参数字典，如 {"start_date": "2025-01-01", "end_date": "2025-12-31"}
    """
    params = {}
    start_date = time_constraint.get('start') or time_constraint.get('start_date')
    end_date = time_constraint.get('end') or time_constraint.get('end_date')

    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    return params


def build_keyword_filter(keywords: List[str], field_name: str = "e.description", max_keywords: int = 10) -> tuple:
    """
    构建关键词搜索过滤条件

    Args:
        keywords: 关键词列表
        field_name: 要搜索的字段名
        max_keywords: 最大关键词数量

    Returns:
        (过滤条件字符串, 参数字典)
        例如: ("toLower(e.description) CONTAINS toLower($kw_0) OR ...", {"kw_0": "keyword1", ...})
    """
    if not keywords:
        return "", {}

    conditions = []
    params = {}

    for i, kw in enumerate(keywords[:max_keywords]):
        param_name = f"kw_{i}"
        conditions.append(f"toLower({field_name}) CONTAINS toLower(${param_name})")
        params[param_name] = kw

    filter_str = " OR ".join(conditions)
    return filter_str, params


def merge_params(*param_dicts: Dict) -> Dict:
    """
    合并多个参数字典

    Args:
        *param_dicts: 多个参数字典

    Returns:
        合并后的参数字典
    """
    result = {}
    for params in param_dicts:
        if params:
            result.update(params)
    return result


def truncate_text(text: str, max_length: int = 200) -> str:
    """
    截断文本

    Args:
        text: 原文本
        max_length: 最大长度

    Returns:
        截断后的文本
    """
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


def format_cypher_query(cypher: str) -> str:
    """
    格式化Cypher查询（移除多余空白）

    Args:
        cypher: 原始Cypher查询

    Returns:
        格式化后的查询
    """
    lines = [line.strip() for line in cypher.split('\n') if line.strip()]
    return '\n'.join(lines)
