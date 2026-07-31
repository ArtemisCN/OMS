#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨院借调自动过期脚本
每天凌晨2:00执行，检查所有active借调记录，将过期的标记为expired
同时清理排班标记并记录操作日志
"""

import sys
import os
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from app import create_app
from models import db, CrossHospitalAssignment, Hospital, User, DutySchedule, CrossAssignmentLog


def expire_assignments():
    app = create_app()
    with app.app_context():
        now = datetime.now()
        # 当日23:00以后才记为过期
        expire_cutoff = now.replace(hour=23, minute=0, second=0, microsecond=0)
        # 查找所有过期的活跃借调
        expired = CrossHospitalAssignment.query.filter(
            CrossHospitalAssignment.status == 'active',
            CrossHospitalAssignment.end_date < expire_cutoff
        ).all()

        count = 0
        for assignment in expired:
            assignment.status = 'expired'
            if assignment.user:
                assignment.user.is_cross_assigned = False

            # 清除排班标记
            tag = f'cross_assignment:{assignment.id}'
            DutySchedule.query.filter(
                DutySchedule.notes == tag
            ).delete(synchronize_session=False)

            # 记录操作日志
            log = CrossAssignmentLog(
                assignment_id=assignment.id,
                action='expire',
                operator_id=0,
                new_value=json.dumps({'status': 'expired'}, ensure_ascii=False),
            )
            db.session.add(log)

            count += 1

        if count > 0:
            db.session.commit()
            print(f"[{now}] ✅ 已过期 {count} 条借调记录，已清除排班标记并记录日志")
            for a in expired:
                src = a.source_hospital.name if a.source_hospital else '?'
                tgt = a.target_hospital.name if a.target_hospital else '?'
                uname = a.user.name if a.user else '?'
                print(f"  - {uname} ({src} → {tgt})")
        else:
            print(f"[{now}] ℹ️ 无过期借调记录")


if __name__ == '__main__':
    expire_assignments()
