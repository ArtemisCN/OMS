"""Direct insert into production DB"""
import sqlite3, json

DB_PATH = '/var/www/hospital-workorder/instance/workorders.db'

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Check existing
cur.execute("SELECT title FROM knowledge_base")
existing = set(row[0] for row in cur.fetchall())

data = json.load(open('/home/ubuntu/hospital-workorder/scripts/knowledge_data.json', 'r', encoding='utf-8'))

added = 0
for item in data:
    if item['title'] in existing:
        continue
    cur.execute(
        "INSERT INTO knowledge_base (title, category, content, is_pinned, created_at, updated_at) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
        (item['title'], item['category'], item['content'], 1 if item.get('pinned') else 0)
    )
    added += 1

conn.commit()
total = cur.execute("SELECT count(*) FROM knowledge_base").fetchone()[0]
print(f'✅ 新增 {added} 条, 总计 {total} 条')
cur.execute("SELECT category, count(*) FROM knowledge_base GROUP BY category")
for row in cur.fetchall():
    print(f'   {row[0]}: {row[1]} 篇')
conn.close()
