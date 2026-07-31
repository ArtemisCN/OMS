"""迁移脚本：duty_schedules 表增加 user_id 列（借调排班联动使用）

用法:
    python scripts/migrate_duty_schedule_user_id.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3


def migrate(db_path=None):
    if db_path is None:
        # 默认使用 instance/workorders.db（与 config.py 一致）
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db_path = os.path.join(base, 'instance', 'workorders.db')
        if not os.path.exists(db_path):
            print(f'未找到数据库: {db_path}')
            return False

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 检查列是否存在
    cur.execute("PRAGMA table_info(duty_schedules)")
    cols = [row[1] for row in cur.fetchall()]
    if 'user_id' not in cols:
        cur.execute("ALTER TABLE duty_schedules ADD COLUMN user_id INTEGER REFERENCES users(id)")
        conn.commit()
        print('✓ duty_schedules.user_id 列已添加')
    else:
        print('· duty_schedules.user_id 列已存在，跳过')

    # 检查索引
    cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='ix_duty_schedules_user_id'")
    if not cur.fetchone():
        cur.execute("CREATE INDEX ix_duty_schedules_user_id ON duty_schedules(user_id)")
        conn.commit()
        print('✓ ix_duty_schedules_user_id 索引已创建')
    else:
        print('· ix_duty_schedules_user_id 索引已存在，跳过')

    conn.close()
    print('迁移完成')
    return True


if __name__ == '__main__':
    migrate()
