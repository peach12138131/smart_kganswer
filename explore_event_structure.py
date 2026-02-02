"""
探索Event节点的结构和内容，为设计泛化查询策略提供依据
"""
from neo4j import GraphDatabase
import json

# Neo4j连接配置
NEO4J_URI = "bolt://47.237.177.27:8304"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "ai_database_vivo50"

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

print("="*80)
print("[1] Event节点的所有属性分析")
print("="*80)
with driver.session() as session:
    # 获取Event节点的所有属性键
    result = session.run('''
        MATCH (e:Event)
        WITH e LIMIT 100
        UNWIND keys(e) as key
        RETURN DISTINCT key
        ORDER BY key
    ''')
    keys = [record['key'] for record in result]
    print(f"  Event节点属性: {keys}")

print()
print("="*80)
print("[2] Event节点样本（包含事故相关的）")
print("="*80)
with driver.session() as session:
    # 搜索描述中包含accident、crash、incident等关键词的事件
    result = session.run('''
        MATCH (e:Event)
        WHERE toLower(e.description) CONTAINS 'accident'
           OR toLower(e.description) CONTAINS 'crash'
           OR toLower(e.description) CONTAINS 'incident'
           OR toLower(e.description) CONTAINS 'emergency'
           OR toLower(e.name) CONTAINS 'accident'
           OR toLower(e.name) CONTAINS 'crash'
        RETURN e.id as id, e.name as name, e.date as date,
               e.description as description, e.event_type as event_type
        ORDER BY e.date DESC
        LIMIT 10
    ''')
    records = list(result)
    if records:
        print(f"  找到 {len(records)} 个事故相关事件：")
        for i, record in enumerate(records, 1):
            print(f"\n  事件 #{i}:")
            print(f"    ID: {record['id']}")
            print(f"    Name: {record['name']}")
            print(f"    Date: {record['date']}")
            print(f"    Type: {record['event_type']}")
            if record['description']:
                desc = record['description'][:200] + "..." if len(record['description']) > 200 else record['description']
                print(f"    Description: {desc}")
    else:
        print("  没有找到包含accident/crash关键词的事件")

print()
print("="*80)
print("[3] Event节点的event_type分布")
print("="*80)
with driver.session() as session:
    result = session.run('''
        MATCH (e:Event)
        WHERE e.event_type IS NOT NULL
        RETURN e.event_type as type, count(*) as count
        ORDER BY count DESC
        LIMIT 20
    ''')
    records = list(result)
    if records:
        print("  Event类型分布:")
        for record in records:
            print(f"    {record['type']}: {record['count']}")
    else:
        print("  没有event_type字段或都为NULL")

print()
print("="*80)
print("[4] 2025年的Event样本（不限类型）")
print("="*80)
with driver.session() as session:
    result = session.run('''
        MATCH (e:Event)
        WHERE e.date >= date('2025-01-01') AND e.date <= date('2025-12-31')
        RETURN e.id as id, e.name as name, e.date as date,
               e.description as description, e.event_type as event_type,
               e.location as location
        ORDER BY e.date DESC
        LIMIT 20
    ''')
    records = list(result)
    print(f"  2025年的Event总数: {len(records)}")
    for i, record in enumerate(records, 1):
        print(f"\n  事件 #{i}:")
        print(f"    Name: {record['name']}")
        print(f"    Date: {record['date']}")
        print(f"    Type: {record['event_type']}")
        print(f"    Location: {record['location']}")
        if record['description']:
            desc = record['description'][:150] + "..." if len(record['description']) > 150 else record['description']
            print(f"    Description: {desc}")

print()
print("="*80)
print("[5] 搜索描述中包含'private', 'aviation'相关的事件")
print("="*80)
with driver.session() as session:
    result = session.run('''
        MATCH (e:Event)
        WHERE (toLower(e.description) CONTAINS 'private' OR toLower(e.description) CONTAINS 'aviation'
               OR toLower(e.description) CONTAINS 'business jet' OR toLower(e.description) CONTAINS 'bizjet')
        AND e.date >= date('2025-01-01') AND e.date <= date('2025-12-31')
        RETURN e.id as id, e.name as name, e.date as date,
               e.description as description, e.event_type as event_type
        ORDER BY e.date DESC
        LIMIT 10
    ''')
    records = list(result)
    if records:
        print(f"  找到 {len(records)} 个私人航空相关事件：")
        for i, record in enumerate(records, 1):
            print(f"\n  事件 #{i}:")
            print(f"    Name: {record['name']}")
            print(f"    Date: {record['date']}")
            print(f"    Type: {record['event_type']}")
            desc = record['description'][:200] + "..." if len(record['description']) > 200 else record['description']
            print(f"    Description: {desc}")
    else:
        print("  没有找到私人航空相关的事件")

print()
print("="*80)
print("[6] 全文搜索：包含'事故'、'accident'等关键词的所有Event")
print("="*80)
with driver.session() as session:
    keywords = ['accident', 'crash', 'incident', 'emergency', 'failure', 'issue', 'problem']
    for keyword in keywords:
        result = session.run(f'''
            MATCH (e:Event)
            WHERE toLower(e.description) CONTAINS toLower($keyword)
               OR toLower(e.name) CONTAINS toLower($keyword)
            RETURN count(*) as count
        ''', keyword=keyword)
        count = result.single()['count']
        print(f"  '{keyword}': {count} 个事件")

print()
print("="*80)
print("[7] 检查是否有event_category或其他分类字段")
print("="*80)
with driver.session() as session:
    result = session.run('''
        MATCH (e:Event)
        RETURN e LIMIT 5
    ''')
    for i, record in enumerate(result, 1):
        event_node = record['e']
        print(f"\n  Event样本 #{i}:")
        for key, value in dict(event_node).items():
            value_str = str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
            print(f"    {key}: {value_str}")

driver.close()
print("\n[DONE] Event结构探索完成")
