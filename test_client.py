"""
测试客户端
用于测试智能知识图谱检索 API
"""

import requests
import json
import time


API_BASE = "http://localhost:8309/api/kg"


def test_intelligent_query(question: str, stream: bool = False, debug: bool = False):
    """测试智能查询"""
    print("\n" + "=" * 80)
    print(f"[?] 问题: {question}")
    print("=" * 80)

    url = f"{API_BASE}/query"
    payload = {
        "question": question,
        "stream": stream,
        "include_debug": debug
    }

    start_time = time.time()

    if stream:
        # 流式请求
        response = requests.post(url, json=payload, stream=True)

        print("\n[+] 答案（流式）:")
        print("-" * 80)

        full_answer = ""
        for line in response.iter_lines():
            if line:
                line_text = line.decode('utf-8')

                if line_text.startswith('data: '):
                    data_str = line_text[6:]

                    if data_str == '[DONE]':
                        break

                    try:
                        data = json.loads(data_str)

                        if data['type'] == 'chunk':
                            print(data['content'], end='', flush=True)

                        elif data['type'] == 'complete':
                            full_answer = data['content']
                            exec_time = data.get('execution_time', 0)
                            print(f"\n\n[T] 执行时间: {exec_time:.2f}s")

                        elif data['type'] == 'debug' and debug:
                            debug_data = data['data']

                            # 识别debug数据类型并格式化显示
                            if 'recognition' in debug_data:
                                print(f"\n[D] 实体识别结果:")
                                print(json.dumps(debug_data['recognition'], indent=2, ensure_ascii=False))

                            elif 'query_plan' in debug_data:
                                print(f"\n[D] 查询计划:")
                                plan = debug_data['query_plan']
                                print(f"  策略: {plan.get('strategy')}")
                                print(f"  查询数量: {len(plan.get('cypher_queries', []))}")
                                for i, q in enumerate(plan.get('cypher_queries', []), 1):
                                    print(f"\n  查询 #{i}:")
                                    print(f"    描述: {q.get('description')}")
                                    print(f"    Cypher:\n{q.get('cypher')}")
                                    if q.get('params'):
                                        print(f"    参数: {q.get('params')}")

                            elif 'graph_results' in debug_data:
                                print(f"\n[D] 图谱查询结果:")
                                gr = debug_data['graph_results']
                                print(f"  总结果数: {gr.get('total_results')}")
                                print(f"  执行查询数: {gr.get('queries_executed')}")

                                for i, qr in enumerate(gr.get('results_by_query', []), 1):
                                    print(f"\n  查询 #{i}: {qr.get('description')}")
                                    print(f"    返回数量: {qr.get('count')}")
                                    if qr.get('by_type'):
                                        print(f"    按类型统计: {qr.get('by_type')}")
                                    print(f"    Cypher: {qr.get('cypher', 'N/A')[:100]}...")

                                    # 显示样本数据
                                    if qr.get('sample_data'):
                                        print(f"    样本数据（前5条）:")
                                        for j, item in enumerate(qr['sample_data'][:5], 1):
                                            print(f"      {j}. {item.get('target_type')}: {item.get('target_name')}")

                    except json.JSONDecodeError:
                        pass

        print("-" * 80)

    else:
        # 非流式请求
        response = requests.post(url, json=payload)
        result = response.json()

        elapsed = time.time() - start_time

        if result.get('success'):
            print("\n[+] 答案:")
            print("-" * 80)
            print(result['answer'])
            print("-" * 80)
            print(f"\n[T] 总耗时: {elapsed:.2f}s")

            if debug and 'debug' in result:
                print("\n[D] 调试信息:")
                print("=" * 80)

                # 1. 实体识别
                print("\n[1] 实体识别结果:")
                print(json.dumps(result['debug']['recognition'], indent=2, ensure_ascii=False))

                # 2. 查询计划
                print("\n[2] 查询计划:")
                plan = result['debug']['query_plan']
                print(f"  策略: {plan.get('strategy')}")
                print(f"  查询数量: {len(plan.get('cypher_queries', []))}")

                for i, q in enumerate(plan.get('cypher_queries', []), 1):
                    print(f"\n  查询 #{i}:")
                    print(f"    描述: {q.get('description')}")
                    print(f"    Cypher:")
                    for line in q.get('cypher', '').split('\n'):
                        print(f"      {line}")
                    if q.get('params'):
                        print(f"    参数: {q.get('params')}")

                # 3. 图谱查询结果
                print("\n[3] 图谱查询结果:")
                gr = result['debug']['graph_results']
                print(f"  总结果数: {gr.get('total_results')}")

                for i, qr in enumerate(gr.get('results', []), 1):
                    print(f"\n  查询 #{i}: {qr.get('query_description', qr.get('description', 'N/A'))}")
                    print(f"    返回数量: {qr.get('count')}")

                    # 按类型统计
                    if qr.get('data'):
                        type_counts = {}
                        for item in qr['data']:
                            t = item.get('target_type', 'Unknown')
                            type_counts[t] = type_counts.get(t, 0) + 1
                        print(f"    按类型统计: {type_counts}")

                    # 显示Cypher
                    if qr.get('cypher'):
                        print(f"    Cypher: {qr.get('cypher')[:80]}...")

                    # 显示样本数据
                    if qr.get('data'):
                        print(f"    样本数据（前5条）:")
                        for j, item in enumerate(qr['data'][:5], 1):
                            target_name = item.get('target_name', 'N/A')
                            target_type = item.get('target_type', 'N/A')
                            print(f"      {j}. [{target_type}] {target_name}")

                print("=" * 80)
        else:
            print(f"\n[X] 错误: {result.get('error')}")


def test_fuzzy_search(query: str, limit: int = 5):
    """测试模糊搜索"""
    print("\n" + "=" * 80)
    print(f"[S] 模糊搜索: {query}")
    print("=" * 80)

    url = f"{API_BASE}/fuzzy_search"
    payload = {"query": query, "limit": limit}

    response = requests.post(url, json=payload)
    result = response.json()

    if result.get('success'):
        print(f"\n找到 {result['count']} 个匹配实体:")
        for i, entity in enumerate(result['entities'], 1):
            print(f"  {i}. {entity['name']} ({', '.join(entity['labels'])})")
    else:
        print(f"\n[X] 错误: {result.get('error')}")


def test_entity_info(entity_name: str, relations: str = "", limit: int = 10):
    """测试实体信息查询"""
    print("\n" + "=" * 80)
    print(f"[E] 实体信息: {entity_name}")
    print("=" * 80)

    url = f"{API_BASE}/entity/{entity_name}"
    params = {"limit": limit}
    if relations:
        params["relations"] = relations

    response = requests.get(url, params=params)
    result = response.json()

    if result.get('success'):
        data = result['data']
        neighbors = data['neighbors']
        print(f"\n找到 {len(neighbors)} 个关联实体:")

        for i, neighbor in enumerate(neighbors[:10], 1):  # 只显示前10个
            rel_type = neighbor.get('relation_type', 'UNKNOWN')
            target_type = neighbor.get('target_type', 'Unknown')
            target_name = neighbor.get('target_name', 'Unknown')
            print(f"  {i}. {entity_name} --[{rel_type}]--> {target_name} ({target_type})")
    else:
        print(f"\n[X] 错误: {result.get('error')}")


def test_health():
    """测试健康检查"""
    print("\n" + "=" * 80)
    print("[H] 健康检查")
    print("=" * 80)

    url = f"{API_BASE}/health"
    response = requests.get(url)
    result = response.json()

    if result.get('success'):
        print("[V] 服务正常运行")
        print(f"   Neo4j 连接: {'+' if result.get('neo4j_connected') else '-'}")
    else:
        print(f"[X] 服务异常: {result.get('message')}")


def main():
    """主测试流程"""
   
    # test_intelligent_query(
    #     "你现在数据库中存有哪些机场",
    #     stream=True,
    #     debug=True,
    # )
    test_intelligent_query(
        "Abu Dhabi International Airport FBO供应商有哪些",
        stream=True,
        debug=True,
    )

    print("\n" + "=" * 80)
    print("[V] 所有测试完成")
    print("=" * 80)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[!] 测试中断")
    except requests.exceptions.ConnectionError:
        print("\n\n[X] 无法连接到服务器，请确保服务已启动:")
        print("   python app.py")
    except Exception as e:
        print(f"\n\n[X] 测试出错: {str(e)}")
        import traceback
        traceback.print_exc()
