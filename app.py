"""
智能知识图谱检索 API
结合 LLM 的高效图谱查询服务
"""

from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import json
import time

from llm_client import LLMClient
from entity_recognizer import EntityRecognizer
from query_planner import QueryPlanner
from kg_retriever import KGRetriever
from answer_generator import AnswerGenerator


# ========== 配置 ==========
NEO4J_URI = 
NEO4J_USER = 
NEO4J_PASSWORD = 

# ========== 初始化 ==========
app = Flask(__name__)
CORS(app)

# 全局单例
llm_client = None
kg_retriever = None
entity_recognizer = None
query_planner = None
answer_generator = None


def get_services():
    """获取或创建服务实例（单例模式）"""
    global llm_client, kg_retriever, entity_recognizer, query_planner, answer_generator

    # 初始化基础服务
    if llm_client is None:
        llm_client = LLMClient()
    if kg_retriever is None:
        kg_retriever = KGRetriever(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)

    # 初始化依赖LLM的服务
    services = [
        ('entity_recognizer', EntityRecognizer),
        ('query_planner', QueryPlanner),
        ('answer_generator', AnswerGenerator)
    ]

    for var_name, ServiceClass in services:
        if globals()[var_name] is None:
            globals()[var_name] = ServiceClass(llm_client)

    return llm_client, kg_retriever, entity_recognizer, query_planner, answer_generator


# ========== API 路由 ==========

@app.route('/api/kg/query', methods=['POST'])
def intelligent_query():
    """
    智能知识图谱查询接口

    请求参数:
    {
        "question": "NetJets 使用了哪些飞机？",
        "stream": true,  # 是否流式返回
        "include_debug": false  # 是否包含调试信息
    }

    返回格式（非流式）:
    {
        "success": true,
        "answer": "...",
        "debug": {
            "recognition": {...},
            "query_plan": {...},
            "graph_results": {...},
            "execution_time": 1.23
        }
    }
    """
    try:
        # 获取服务
        _, kg_ret, entity_rec, query_plan, answer_gen = get_services()

        # 解析请求
        data = request.get_json()
        question = data.get('question', '').strip()
        stream = data.get('stream', False)
        include_debug = data.get('include_debug', False)

        if not question:
            return jsonify({
                "success": False,
                "error": "问题不能为空"
            }), 400

        start_time = time.time()

        # Step 1: 实体识别
        print(f"\n[?] 问题: {question}")
        print("[-] Step 1: 实体识别...")
        recognition_result = entity_rec.recognize(question)

        if not recognition_result:
            return jsonify({
                "success": False,
                "error": "实体识别失败"
            }), 500

        print(f"[V] 识别到实体: {len(recognition_result.get('entities', []))} 个")
        print(f"   意图: {recognition_result.get('intent')}")

        # Step 2: 查询规划
        print("[-] Step 2: 查询规划...")
        query_plan_result = query_plan.plan(question, recognition_result)

        if not query_plan_result:
            return jsonify({
                "success": False,
                "error": "查询规划失败"
            }), 500

        print(f"[V] 生成查询: {len(query_plan_result.get('cypher_queries', []))} 个")
        print(f"   策略: {query_plan_result.get('strategy')}")

        # Step 3: 图谱检索
        print("[-] Step 3: 图谱检索...")
        graph_results = kg_ret.execute_query_plan(query_plan_result)

        print(f"[V] 检索结果: {graph_results.get('total_results')} 条")

        # Step 4: 答案生成
        print("[-] Step 4: 答案生成...")

        if stream:
            # 流式返回
            return Response(
                stream_with_context(
                    stream_answer_generator(
                        question,
                        recognition_result,
                        query_plan_result,
                        graph_results,
                        answer_gen,
                        include_debug,
                        start_time
                    )
                ),
                content_type='text/event-stream'
            )
        else:
            # 非流式返回
            full_answer = ""
            for chunk, full_response in answer_gen.generate_stream(
                question,
                recognition_result,
                query_plan_result,
                graph_results
            ):
                if full_response:
                    full_answer = full_response
                    break

            execution_time = time.time() - start_time
            print(f"[V] 完成，耗时: {execution_time:.2f}s\n")

            response = {
                "success": True,
                "answer": full_answer
            }

            if include_debug:
                response["debug"] = {
                    "recognition": recognition_result,
                    "query_plan": query_plan_result,
                    "graph_results": graph_results,
                    "execution_time": execution_time
                }

            return jsonify(response), 200

    except Exception as e:
        print(f"[X] 查询出错: {str(e)}")
        import traceback
        traceback.print_exc()

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


def stream_answer_generator(
    question, recognition_result, query_plan_result, graph_results,
    answer_gen, include_debug, start_time
):
    """流式答案生成器"""
    def send_sse(event_type: str, data: dict) -> str:
        """发送SSE格式数据"""
        return f"data: {json.dumps({'type': event_type, **data})}\n\n"

    # 先发送调试信息（如果需要）
    if include_debug:
        # 构建详细的图谱结果摘要
        graph_debug = {
            'total_results': graph_results.get('total_results', 0),
            'queries_executed': len(graph_results.get('results', [])),
            'results_by_query': []
        }

        # 为每个查询添加详细信息
        for result in graph_results.get('results', []):
            query_info = {
                'description': result.get('query_description', ''),
                'count': result.get('count', 0),
                'cypher': result.get('cypher', ''),  # 添加Cypher查询
                'sample_data': []
            }

            # 按类型统计并取样
            if result.get('data'):
                type_counts = {}
                for item in result['data']:
                    t = item.get('target_type', 'Unknown')
                    type_counts[t] = type_counts.get(t, 0) + 1

                query_info['by_type'] = type_counts
                query_info['sample_data'] = result['data'][:10]  # 显示前10条

            graph_debug['results_by_query'].append(query_info)

        debug_data = [
            ('debug', {'data': {'recognition': recognition_result}}),
            ('debug', {'data': {'query_plan': query_plan_result}}),
            ('debug', {'data': {'graph_results': graph_debug}})
        ]
        for event_type, data in debug_data:
            yield send_sse(event_type, data)

    # 流式发送答案
    for chunk, full_response in answer_gen.generate_stream(
        question, recognition_result, query_plan_result, graph_results
    ):
        if chunk:
            yield send_sse('chunk', {'content': chunk})
        elif full_response:
            execution_time = time.time() - start_time
            yield send_sse('complete', {'content': full_response, 'execution_time': execution_time})
            break

    yield "data: [DONE]\n\n"


@app.route('/api/kg/fuzzy_search', methods=['POST'])
def fuzzy_search():
    """
    模糊搜索实体

    请求参数:
    {
        "query": "Gulf",
        "limit": 5
    }
    """
    try:
        _, kg_ret, _, _, _ = get_services()

        data = request.get_json()
        query = data.get('query', '').strip()
        limit = data.get('limit', 5)

        if not query:
            return jsonify({
                "success": False,
                "error": "搜索内容不能为空"
            }), 400

        entities = kg_ret.fuzzy_search_entity(query, limit)

        return jsonify({
            "success": True,
            "entities": entities,
            "count": len(entities)
        }), 200

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/kg/entity/<entity_name>', methods=['GET'])
def get_entity_info(entity_name):
    """
    获取实体信息

    路径参数:
        entity_name: 实体名称

    查询参数:
        relations: 关系类型（逗号分隔，可选）
        limit: 最大结果数（默认20）
    """
    try:
        _, kg_ret, _, _, _ = get_services()

        relations = request.args.get('relations', '')
        limit = int(request.args.get('limit', 20))

        relation_types = [r.strip() for r in relations.split(',') if r.strip()] if relations else None

        result = kg_ret.get_entity_neighbors(entity_name, relation_types, limit)

        return jsonify({
            "success": True,
            "data": result
        }), 200

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/kg/health', methods=['GET'])
def health_check():
    """健康检查"""
    try:
        _, kg_ret, _, _, _ = get_services()

        return jsonify({
            "success": True,
            "message": "服务运行正常",
            "neo4j_connected": kg_ret.driver is not None
        }), 200

    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"服务异常: {str(e)}"
        }), 500


@app.teardown_appcontext
def cleanup(error):
    """应用关闭时清理资源"""
    global kg_retriever
    if kg_retriever:
        kg_retriever.close()
        kg_retriever = None


if __name__ == "__main__":
    print("=" * 60)
    print("[*] 智能知识图谱检索服务启动中...")
    print("=" * 60)
    print(f"[>] 服务地址: http://localhost:8309")
    print(f"[>] 智能查询: POST http://localhost:8309/api/kg/query")
    print(f"[>] 模糊搜索: POST http://localhost:8309/api/kg/fuzzy_search")
    print(f"[>] 实体信息: GET  http://localhost:8309/api/kg/entity/<name>")
    print(f"[>] 健康检查: GET  http://localhost:8309/api/kg/health")
    print("=" * 60)
    print()

    app.run(host='0.0.0.0', port=8309, debug=True)
