# 系统架构设计

## 🎯 设计目标

解决传统图谱查询的两大痛点：
1. **盲目遍历**：不理解用户意图，暴力遍历所有路径
2. **深度限制**：固定深度导致查不到或查太多

## 🧩 核心思想

**LLM 作为查询规划器，而非数据检索器**

```
传统方法：用户问题 → 固定深度遍历 → 返回大量数据 → LLM 总结

本系统：用户问题 → LLM 理解意图 → 生成精准查询 → 返回相关数据 → LLM 生成答案
```

## 📊 流程对比

### 传统方法

```
Q: "NetJets 使用了哪些飞机?"

Step 1: 查找 NetJets 节点
Step 2: 遍历所有出边关系（3层深度）
  → 找到 50+ 个关联实体
  → 包含：合作伙伴、子公司、投资、位置、事件...
Step 3: 将所有数据传给 LLM
Step 4: LLM 从海量数据中筛选相关信息

问题：
- 查询了大量无关数据
- 浪费数据库资源
- LLM token 消耗大
- 响应速度慢
```

### 本系统

```
Q: "NetJets 使用了哪些飞机?"

Step 1: 实体识别（Haiku，0.1s）
  → 识别：NetJets (Company)
  → 意图：relation_query
  → 关系类型：OPERATES, USES

Step 2: 查询规划（规则引擎，0.05s）
  → 生成：MATCH (c:Company {name: 'NetJets'})-[:OPERATES|USES]->(p:Product)
  → 只查询相关关系，不遍历其他路径

Step 3: 图谱检索（Neo4j，0.1s）
  → 精准返回：5 架飞机

Step 4: 答案生成（Sonnet 流式，0.5s）
  → 生成自然语言答案

优势：
✅ 只查询相关数据
✅ 数据库负载低
✅ Token 消耗小
✅ 响应速度快
```

## 🏗️ 模块设计

### 1. Entity Recognizer（实体识别器）

**职责**：理解用户问题，提取关键信息

**输入**：
```
"Gulfstream 在 2025 年交付了多少架 G650？"
```

**输出**：
```json
{
  "entities": [
    {"name": "Gulfstream", "type": "Company", "confidence": 0.95},
    {"name": "G650", "type": "Product", "confidence": 0.9}
  ],
  "intent": "event_query",
  "relation_types": ["DELIVERED"],
  "time_constraint": {
    "start_date": "2025-01-01",
    "end_date": "2025-12-31"
  }
}
```

**技术**：
- 使用 Haiku 小模型（快速、便宜）
- JSON Schema 约束输出格式
- 支持多实体、多意图

---

### 2. Query Planner（查询规划器）

**职责**：根据意图生成优化的 Cypher 查询

**双模式策略**：

#### 规则模式（快速路径）
适用场景：简单查询（1-2 个实体，明确意图）

```python
if intent == "entity_info" and len(entities) == 1:
    # 直接生成查询
    return {
        "cypher": "MATCH (n:Company {name: $name})-[r]-(m) RETURN ...",
        "strategy": "one_hop"
    }
```

优势：无需调用 LLM，响应极快（<50ms）

#### LLM 模式（复杂路径）
适用场景：复杂查询（多实体、多跳、模式匹配）

```python
# 调用 Haiku 生成查询计划
prompt = """
根据用户意图，生成优化的 Cypher 查询
- 使用 shortestPath() 查找路径
- 限制深度为 2-3 层
- 使用 LIMIT 控制结果数
"""
```

**输出示例**：
```json
{
  "strategy": "path_finding",
  "cypher_queries": [
    {
      "description": "Find supply chain path to NetJets",
      "cypher": "MATCH path = (supplier)-[:SUPPLIES*1..3]->...",
      "priority": 1,
      "params": {"company_name": "NetJets"}
    }
  ],
  "max_results": 20
}
```

---

### 3. KG Retriever（图谱检索器）

**职责**：执行 Cypher 查询，返回结构化数据

**核心功能**：
1. 按优先级执行多个查询
2. 自动序列化 Neo4j 特殊类型
3. 错误处理和重试

**数据转换**：
```python
# Neo4j Node → 可序列化字典
{
  "type": "Node",
  "labels": ["Company"],
  "properties": {"name": "NetJets", "type": "Operator"}
}

# Neo4j Path → 节点和关系列表
{
  "type": "Path",
  "nodes": [...],
  "relationships": [...]
}
```

---

### 4. Answer Generator（答案生成器）

**职责**：将图谱数据转换为自然语言答案

**流式生成**：
```python
for chunk, full_response in llm_client.query_stream(...):
    if chunk:
        yield chunk  # 实时返回文本片段
    elif full_response:
        yield full_response  # 最后返回完整答案
```

**提示词设计**：
```
You are a business aviation knowledge assistant.

Context:
- Question: {question}
- Entities: {entities}
- Graph Results: {results}

Generate a clear answer that:
1. Cites specific entities from graph
2. Uses bullet points for lists
3. Mentions dates if available
4. Acknowledges if data is incomplete
```

---

## 🔄 完整查询流程

### 示例：复杂查询

**用户问题**：
```
"找出从发动机供应商到 NetJets 的供应链路径"
```

**Step 1: 实体识别**
```json
{
  "entities": [{"name": "NetJets", "type": "Company"}],
  "intent": "chain_analysis",
  "relation_types": ["SUPPLIES", "MANUFACTURES"]
}
```

**Step 2: 查询规划（LLM 模式）**
```json
{
  "strategy": "multi_hop",
  "cypher_queries": [
    {
      "description": "Find supply chain paths to NetJets",
      "cypher": "
        MATCH path = (supplier:Company)-[:SUPPLIES*1..3]->(product:Product)
                    <-[:USES|OPERATES]-(netjets:Company {name: $name})
        WHERE supplier.type = 'Manufacturer'
        RETURN path LIMIT 10
      ",
      "priority": 1,
      "params": {"name": "NetJets"}
    }
  ]
}
```

**Step 3: 图谱检索**
```json
{
  "results": [
    {
      "query_description": "Find supply chain paths to NetJets",
      "data": [
        {
          "path": {
            "nodes": [
              {"name": "Pratt & Whitney", "type": "Manufacturer"},
              {"name": "PW800 Engine", "category": "Technology"},
              {"name": "Gulfstream G650", "category": "Business Jet"},
              {"name": "NetJets", "type": "Operator"}
            ],
            "relationships": [
              {"type": "SUPPLIES"},
              {"type": "USES"},
              {"type": "OPERATES"}
            ]
          }
        }
      ],
      "count": 3
    }
  ],
  "total_results": 3
}
```

**Step 4: 答案生成**
```
基于知识图谱，发现以下供应链路径：

1. Pratt & Whitney (制造商)
   → SUPPLIES → PW800 Engine (发动机)
   → USES → Gulfstream G650 (商务机)
   → OPERATES → NetJets (运营商)

2. Rolls-Royce (制造商)
   → SUPPLIES → Tay 611 Engine (发动机)
   → USES → Gulfstream G550 (商务机)
   → OPERATES → NetJets (运营商)

这些路径显示了 NetJets 机队的主要发动机供应链。
```

---

## 🚀 性能优化

### 1. 分层模型策略

| 任务 | 模型 | 成本 | 速度 |
|------|------|------|------|
| 实体识别 | Haiku | $ | ⚡⚡⚡ |
| 查询规划 | 规则/Haiku | $/$ | ⚡⚡⚡ |
| 图谱检索 | Neo4j | - | ⚡⚡ |
| 答案生成 | Sonnet | $$ | ⚡⚡ |

**总成本**：约 $0.005-0.01 / 次查询（比传统方法省 50%）

### 2. 缓存策略（未来）

```python
# 实体识别缓存
cache["NetJets 使用了"] → {"entities": [...], "intent": "relation_query"}

# 查询结果缓存
cache["NetJets OPERATES"] → [G650, Global 7500, ...]

# TTL: 1 小时（实体识别）、5 分钟（查询结果）
```

### 3. 批量查询优化

```python
# 多个查询合并为一个 Cypher
MATCH (c:Company {name: 'NetJets'})-[r:OPERATES|USES|MANAGES]->(target)
RETURN r, target
# 比三个独立查询快 2-3 倍
```

---

## 📈 扩展方向

### 1. 多轮对话
```
User: "NetJets 使用了哪些飞机？"
Bot: "G650, Global 7500, ..."

User: "这些飞机的制造商是谁？"（上下文：指代前面的飞机）
Bot: 识别意图 → 关联前次查询 → 查询制造商
```

### 2. 混合检索
```
知识图谱（结构化） + 向量数据库（FAQ） + SQL（统计数据）

Q: "NetJets 的机队规模趋势？"
→ 图谱查询：当前机队
→ SQL 查询：历史数据
→ 向量检索：行业报告
→ 综合生成答案
```

### 3. 主动洞察
```
# 定时扫描图谱
MATCH (c:Company)-[:ACQUIRES]->(target)
WHERE c.last_acquisition_date > date() - duration('P7D')
RETURN ...

# 触发洞察推送
"NetJets 在过去 7 天内收购了 2 家公司，可能进入新市场..."
```

---

## 🔐 安全与权限

### 1. 数据访问控制
```python
# 根据用户角色限制查询
if user.role == "free":
    max_depth = 1
    max_results = 10
elif user.role == "premium":
    max_depth = 3
    max_results = 50
```

### 2. 敏感数据过滤
```cypher
// 移除敏感属性
MATCH (c:Company)
RETURN c {.name, .type, .country}  // 不返回内部字段
```

### 3. 查询审计
```python
log_query({
    "user_id": user.id,
    "question": question,
    "entities": entities,
    "timestamp": now(),
    "execution_time": elapsed
})
```

---

## 🧪 测试策略

### 1. 单元测试
```python
def test_entity_recognizer():
    result = recognizer.recognize("NetJets 使用了哪些飞机？")
    assert result['intent'] == 'relation_query'
    assert len(result['entities']) == 1
```

### 2. 集成测试
```python
def test_full_pipeline():
    answer = query_kg("Gulfstream 制造了哪些飞机？")
    assert "G650" in answer
    assert "Business Jet" in answer
```

### 3. 性能测试
```python
def test_performance():
    start = time.time()
    query_kg("复杂多跳查询...")
    elapsed = time.time() - start
    assert elapsed < 2.0  # 要求 2 秒内完成
```

---

## 📝 总结

本系统通过 **LLM 驱动的查询规划**，实现了：

✅ **精准查询**：只查相关数据，避免遍历
✅ **智能理解**：理解用户意图，生成优化查询
✅ **流式体验**：答案实时返回，用户体验好
✅ **成本优化**：分层模型策略，省钱省时

核心创新：**让 LLM 做规划，让图数据库做检索**
