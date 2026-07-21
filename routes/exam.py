"""考试系统路由 — PC端管理 + 移动端API"""
import json
import random
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, g
from flask_login import login_required, current_user
from models import db, Exam, ExamQuestion, ExamSubmission, can_access, get_group_name_by_id, RoleGroup

exam_bp = Blueprint('exam', __name__, url_prefix='/exam')


# ======================== PC端页面路由 ========================

@exam_bp.route('/')
@login_required
def exam_list():
    """考试列表页（含汇总统计）"""
    if not can_access('考试系统'):
        return "无权访问", 403
    exams = Exam.query.order_by(Exam.created_at.desc()).all()
    from sqlalchemy import func

    total_exams = len(exams)
    published_count = sum(1 for e in exams if e.status == 'published')
    draft_count = sum(1 for e in exams if e.status == 'draft')
    closed_count = sum(1 for e in exams if e.status == 'closed')

    # 各考试统计
    for e in exams:
        e._q_count = e.questions.count()
        subs = e.submissions.filter_by(status='submitted')
        e._s_count = subs.count()
        e._avg_score = round(subs.with_entities(func.avg(ExamSubmission.score)).scalar() or 0, 1)
        e._pass_rate = 0
        e._total_questions = 0
        if e._s_count > 0:
            passed = subs.filter(
                ExamSubmission.score >= e.pass_score
            ).count()
            e._pass_rate = round(passed / e._s_count * 100, 1)

    # 总参与人次 / 总题目数
    total_participants = sum(e._s_count for e in exams)
    total_questions_all = sum(e._q_count for e in exams)

    return render_template('exam/list.html', exams=exams,
                           total_exams=total_exams,
                           published_count=published_count,
                           draft_count=draft_count,
                           closed_count=closed_count,
                           total_participants=total_participants,
                           total_questions_all=total_questions_all,
                           now=datetime.now())


@exam_bp.route('/create', methods=['GET', 'POST'])
@login_required
def exam_create():
    """创建考试"""
    if not can_access('考试系统'):
        return "无权访问", 403
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            flash('请输入考试标题', 'danger')
            return render_template('exam/create.html', exam=None, now=datetime.now())
        exam = Exam(
            title=title,
            description=request.form.get('description', ''),
            duration_minutes=request.form.get('duration_minutes', 30, type=int),
            pass_score=request.form.get('pass_score', 60, type=float),
            total_score=request.form.get('total_score', 100, type=float),
            shuffle_questions=request.form.get('shuffle_questions', '1') == '1',
            shuffle_options=request.form.get('shuffle_options', '1') == '1',
            show_result_immediately=request.form.get('show_result_immediately', '1') == '1',
            max_attempts=request.form.get('max_attempts', 0, type=int),
            status=request.form.get('status', 'draft'),
            allowed_groups=json.dumps(request.form.getlist('allowed_groups')),
            allowed_teams=json.dumps(request.form.getlist('allowed_teams')),
            created_by=current_user.display_name or current_user.username,
        )
        db.session.add(exam)
        db.session.flush()

        # 处理题目
        _save_questions(exam.id, request.form)
        db.session.commit()
        flash('考试创建成功', 'success')
        return redirect(url_for('exam.exam_detail', exam_id=exam.id))

    groups = RoleGroup.query.order_by(RoleGroup.name).all()
    # 获取所有人员组别
    from models import Person
    all_teams = [t[0] for t in Person.query.with_entities(Person.team).distinct().order_by(Person.team).all() if t[0]]
    return render_template('exam/create.html', exam=None, groups=groups, teams=all_teams, now=datetime.now())


@exam_bp.route('/<int:exam_id>/edit', methods=['GET', 'POST'])
@login_required
def exam_edit(exam_id):
    """编辑考试"""
    if not can_access('考试系统'):
        return "无权访问", 403
    exam = db.session.get(Exam, exam_id)
    if not exam:
        flash('考试不存在', 'danger')
        return redirect(url_for('exam.exam_list'))
    if request.method == 'POST':
        exam.title = request.form.get('title', '').strip()
        exam.description = request.form.get('description', '')
        exam.duration_minutes = request.form.get('duration_minutes', 30, type=int)
        exam.pass_score = request.form.get('pass_score', 60, type=float)
        exam.total_score = request.form.get('total_score', 100, type=float)
        exam.shuffle_questions = request.form.get('shuffle_questions', '1') == '1'
        exam.shuffle_options = request.form.get('shuffle_options', '1') == '1'
        exam.show_result_immediately = request.form.get('show_result_immediately', '1') == '1'
        exam.max_attempts = request.form.get('max_attempts', 0, type=int)
        exam.status = request.form.get('status', 'draft')
        exam.allowed_groups = json.dumps(request.form.getlist('allowed_groups'))
        exam.allowed_teams = json.dumps(request.form.getlist('allowed_teams'))

        # 删除旧题，重新添加
        ExamQuestion.query.filter_by(exam_id=exam.id).delete()
        _save_questions(exam.id, request.form)
        db.session.commit()
        flash('考试更新成功', 'success')
        return redirect(url_for('exam.exam_detail', exam_id=exam.id))

    groups = RoleGroup.query.order_by(RoleGroup.name).all()
    from models import Person
    all_teams = [t[0] for t in Person.query.with_entities(Person.team).distinct().order_by(Person.team).all() if t[0]]
    questions = ExamQuestion.query.filter_by(exam_id=exam.id).order_by(ExamQuestion.sort_order).all()
    return render_template('exam/create.html', exam=exam, questions=questions, groups=groups, teams=all_teams, now=datetime.now())


@exam_bp.route('/<int:exam_id>/detail')
@login_required
def exam_detail(exam_id):
    """考试详情 — 成绩列表、答案解析"""
    if not can_access('考试系统'):
        return "无权访问", 403
    exam = db.session.get(Exam, exam_id)
    if not exam:
        flash('考试不存在', 'danger')
        return redirect(url_for('exam.exam_list'))
    questions = ExamQuestion.query.filter_by(exam_id=exam.id).order_by(ExamQuestion.sort_order).all()
    submissions = ExamSubmission.query.filter_by(exam_id=exam.id, status='submitted') \
        .order_by(ExamSubmission.score.desc(), ExamSubmission.duration_seconds.asc()).limit(100).all()
    return render_template('exam/detail.html', exam=exam, questions=questions,
                           submissions=submissions, now=datetime.now())


@exam_bp.route('/<int:exam_id>/submission/<int:submission_id>/review')
@login_required
def exam_review_submission(exam_id, submission_id):
    """查看考生答卷详情 — 逐题展示对错"""
    if not can_access('考试系统'):
        return "无权访问", 403
    exam = db.session.get(Exam, exam_id)
    if not exam:
        flash('考试不存在', 'danger')
        return redirect(url_for('exam.exam_list'))
    submission = db.session.get(ExamSubmission, submission_id)
    if not submission or submission.exam_id != exam.id:
        flash('答卷不存在', 'danger')
        return redirect(url_for('exam.exam_detail', exam_id=exam.id))

    questions = ExamQuestion.query.filter_by(exam_id=exam.id).order_by(ExamQuestion.sort_order).all()
    try:
        user_answers = json.loads(submission.answers) if submission.answers else {}
    except (json.JSONDecodeError, TypeError):
        user_answers = {}

    # 构建逐题数据
    review_items = []
    correct_count = 0
    wrong_count = 0
    for q in questions:
        qid_str = str(q.id)
        user_ans = user_answers.get(qid_str, '')
        is_correct = q.check_answer(user_ans) if user_ans else False
        if is_correct:
            correct_count += 1
        else:
            wrong_count += 1
        review_items.append({
            'question': q,
            'user_answer': user_ans,
            'is_correct': is_correct,
        })

    return render_template('exam/review.html',
                           exam=exam,
                           submission=submission,
                           review_items=review_items,
                           correct_count=correct_count,
                           wrong_count=wrong_count,
                           now=datetime.now())


@exam_bp.route('/<int:exam_id>/ranking')
@login_required
def exam_ranking(exam_id):
    """排名页"""
    if not can_access('考试系统'):
        return "无权访问", 403
    exam = db.session.get(Exam, exam_id)
    if not exam:
        flash('考试不存在', 'danger')
        return redirect(url_for('exam.exam_list'))
    submissions = ExamSubmission.query.filter_by(exam_id=exam.id, status='submitted') \
        .order_by(ExamSubmission.score.desc(), ExamSubmission.duration_seconds.asc(), ExamSubmission.submitted_at.asc()).all()
    # 排名
    rank = 0
    prev_score = None
    for i, s in enumerate(submissions):
        if s.score != prev_score:
            rank = i + 1
        s._rank = rank
        prev_score = s.score
    return render_template('exam/ranking.html', exam=exam, submissions=submissions, now=datetime.now())


@exam_bp.route('/<int:exam_id>/delete', methods=['POST'])
@login_required
def exam_delete(exam_id):
    """删除考试"""
    if not can_access('考试系统'):
        return jsonify({'error': '无权访问'}), 403
    exam = db.session.get(Exam, exam_id)
    if not exam:
        return jsonify({'error': '考试不存在'}), 404
    db.session.delete(exam)
    db.session.commit()
    flash('考试已删除', 'success')
    return jsonify({'success': True})


@exam_bp.route('/<int:exam_id>/toggle_status', methods=['POST'])
@login_required
def exam_toggle_status(exam_id):
    """切换考试状态 draft/published/closed"""
    if not can_access('考试系统'):
        return jsonify({'error': '无权访问'}), 403
    exam = db.session.get(Exam, exam_id)
    if not exam:
        return jsonify({'error': '考试不存在'}), 404
    status_map = {'draft': 'published', 'published': 'closed', 'closed': 'draft'}
    exam.status = status_map.get(exam.status, 'draft')
    db.session.commit()
    return jsonify({'success': True, 'status': exam.status})


def _save_questions(exam_id, form):
    """从表单数据保存题目"""
    titles = form.getlist('q_title[]')
    types = form.getlist('q_type[]')
    scores = form.getlist('q_score[]')
    answers = form.getlist('q_answer[]')
    analyses = form.getlist('q_analysis[]')

    for i, title in enumerate(titles):
        if not title.strip():
            continue
        q_type = types[i] if i < len(types) else 'single'
        try:
            score = float(scores[i]) if i < len(scores) else 10.0
        except (ValueError, TypeError):
            score = 10.0
        answer = answers[i] if i < len(answers) else ''
        analysis = analyses[i] if i < len(analyses) else ''

        options_raw = form.get(f'q_options_{i}', '[]')
        try:
            options = json.loads(options_raw) if options_raw else []
        except (json.JSONDecodeError, TypeError):
            options = []

        q = ExamQuestion(
            exam_id=exam_id,
            question_type=q_type,
            question_text=title.strip(),
            options=json.dumps(options),
            answer=answer.strip(),
            score=score,
            analysis=analysis.strip(),
            sort_order=i,
        )
        db.session.add(q)


# ======================== 移动端API（mobile + 小程序共用） ========================

@exam_bp.route('/take')
@login_required
def exam_take():
    """移动端/PC端考试答题页面"""
    if not can_access('考试系统'):
        return "无权访问", 403
    return render_template('exam/take.html', now=datetime.now())


@exam_bp.route('/api/list')
@login_required
def api_exam_list():
    """获取可用考试列表（按权限过滤）"""
    if not can_access('考试系统'):
        return jsonify({'error': '无权访问'}), 403
    exams = Exam.query.filter(
        Exam.status.in_(['published', 'closed'])
    ).order_by(Exam.created_at.desc()).all()

    result = []
    for e in exams:
        if not e.check_access():
            continue
        d = e.to_dict()
        # 检查用户已提交次数
        attempt_count = ExamSubmission.query.filter_by(
            exam_id=e.id, user_id=current_user.id, status='submitted'
        ).count()
        # 检查是否有进行中的考试
        in_progress = ExamSubmission.query.filter_by(
            exam_id=e.id, user_id=current_user.id, status='in_progress'
        ).first()
        d['attempt_count'] = attempt_count
        d['max_attempts'] = e.max_attempts
        d['in_progress_id'] = in_progress.id if in_progress else None
        # 用户最近一次提交
        last_sub = ExamSubmission.query.filter_by(
            exam_id=e.id, user_id=current_user.id, status='submitted'
        ).order_by(ExamSubmission.submitted_at.desc()).first()
        d['last_score'] = last_sub.score if last_sub else None
        d['last_passed'] = last_sub.is_passed(e.pass_score) if last_sub else None
        d['can_start'] = e.status == 'published' and (
            e.max_attempts == 0 or attempt_count < e.max_attempts
        ) and not in_progress
        result.append(d)
    return jsonify({'exams': result})


@exam_bp.route('/api/<int:exam_id>/questions')
@login_required
def api_exam_questions(exam_id):
    """获取考试题目（不含答案，打乱题目和选项）"""
    exam = db.session.get(Exam, exam_id)
    if not exam or exam.status not in ('published', 'closed'):
        return jsonify({'error': '考试不存在或未发布'}), 404
    if not exam.check_access():
        return jsonify({'error': '无权参加此考试'}), 403

    # 检查是否有进行中的答题
    submission = ExamSubmission.query.filter_by(
        exam_id=exam.id, user_id=current_user.id, status='in_progress'
    ).first()

    if not submission:
        # 新建答题
        submission = ExamSubmission(
            exam_id=exam.id,
            user_id=current_user.id,
            total_count=0,
            total_possible=0,
        )
        db.session.add(submission)
        db.session.flush()
        submission_id = submission.id

        # 获取并打乱题目
        questions = ExamQuestion.query.filter_by(exam_id=exam.id).order_by(ExamQuestion.sort_order).all()
        if exam.shuffle_questions:
            random.shuffle(questions)

        # 构建题目数组（不含答案）
        qlist = []
        total_score = 0
        for q in questions:
            opts = q.get_options()
            if exam.shuffle_options and opts:
                random.shuffle(opts)
            qlist.append({
                'id': q.id,
                'sort_order': len(qlist) + 1,
                'question_type': q.question_type,
                'question_text': q.question_text,
                'options': opts,
                'score': q.score,
            })
            total_score += q.score

        submission.total_count = len(qlist)
        submission.total_possible = total_score
        # 存储题目顺序到 answers 字段（初始化空答案）
        submission.set_answers({})
        db.session.commit()
    else:
        submission_id = submission.id
        # 从数据库获取题目（已排序的）
        questions = ExamQuestion.query.filter_by(exam_id=exam.id).order_by(ExamQuestion.sort_order).all()
        qlist = []
        for q in questions:
            opts = q.get_options()
            qlist.append({
                'id': q.id,
                'sort_order': len(qlist) + 1,
                'question_type': q.question_type,
                'question_text': q.question_text,
                'options': opts,
                'score': q.score,
            })

    # 返回已有答案（恢复答题时恢复）
    saved_answers = submission.get_answers()

    # 计算已用时间
    elapsed = 0
    if submission.started_at:
        elapsed = int((datetime.now() - submission.started_at).total_seconds())

    return jsonify({
        'submission_id': submission_id,
        'exam': exam.to_dict(),
        'questions': qlist,
        'saved_answers': saved_answers,
        'time_limit': exam.duration_minutes * 60,
        'started_at': submission.started_at.strftime('%Y-%m-%d %H:%M:%S') if submission.started_at else '',
        'elapsed_seconds': elapsed,
    })


@exam_bp.route('/api/<int:submission_id>/save_answer', methods=['POST'])
@login_required
def api_save_answer(submission_id):
    """保存单题答案（答题过程中）"""
    submission = db.session.get(ExamSubmission, submission_id)
    if not submission or submission.user_id != current_user.id:
        return jsonify({'error': '答卷不存在'}), 404

    data = request.json or {}
    question_id = str(data.get('question_id', ''))
    answer = data.get('answer', '')

    answers = submission.get_answers()
    answers[question_id] = answer
    submission.set_answers(answers)
    db.session.commit()
    return jsonify({'success': True})


@exam_bp.route('/api/submit', methods=['POST'])
@login_required
def api_submit_exam():
    """提交答卷"""
    data = request.json or {}
    submission_id = data.get('submission_id')
    if not submission_id:
        return jsonify({'error': '缺少答卷ID'}), 400
    answers = data.get('answers', {})
    duration_seconds = data.get('duration_seconds', 0)

    submission = db.session.get(ExamSubmission, submission_id)
    if not submission or submission.user_id != current_user.id:
        return jsonify({'error': '答卷不存在'}), 404
    if submission.status != 'in_progress':
        return jsonify({'error': '答卷已提交'}), 400

    submission.set_answers(answers)
    submission.duration_seconds = duration_seconds

    # 自动评分
    exam = submission.exam
    if not exam:
        return jsonify({'error': '考试不存在'}), 404
    questions = ExamQuestion.query.filter_by(exam_id=exam.id).all()
    q_map = {str(q.id): q for q in questions}

    total_score = 0.0
    correct_count = 0
    for qid_str, user_ans in answers.items():
        if not user_ans:
            continue
        q = q_map.get(qid_str)
        if q and q.check_answer(user_ans):
            total_score += q.score
            correct_count += 1

    submission.score = total_score
    submission.correct_count = correct_count
    submission.status = 'submitted'
    submission.submitted_at = datetime.now()
    db.session.commit()

    passed = submission.is_passed(exam.pass_score)
    return jsonify({
        'success': True,
        'submission': submission.to_dict(),
        'passed': passed,
    })


@exam_bp.route('/api/<int:submission_id>/result')
@login_required
def api_exam_result(submission_id):
    """获取考试结果（含答案和解析）"""
    submission = db.session.get(ExamSubmission, submission_id)
    if not submission or submission.user_id != current_user.id:
        return jsonify({'error': '答卷不存在'}), 404
    if submission.status != 'submitted':
        return jsonify({'error': '答卷尚未提交'}), 400

    exam = submission.exam
    questions = ExamQuestion.query.filter_by(exam_id=exam.id).order_by(ExamQuestion.sort_order).all()
    user_answers = submission.get_answers()

    qlist = []
    for q in questions:
        qid_str = str(q.id)
        user_ans = user_answers.get(qid_str, '')
        qlist.append({
            'id': q.id,
            'question_type': q.question_type,
            'question_text': q.question_text,
            'options': q.get_options(),
            'score': q.score,
            'answer': q.answer,
            'analysis': q.analysis,
            'user_answer': user_ans,
            'is_correct': q.check_answer(user_ans) if user_ans else False,
        })

    return jsonify({
        'submission': submission.to_dict(),
        'questions': qlist,
        'passed': submission.is_passed(exam.pass_score),
    })


@exam_bp.route('/api/history')
@login_required
def api_exam_history():
    """我的考试历史"""
    submissions = ExamSubmission.query.filter_by(
        user_id=current_user.id, status='submitted'
    ).order_by(ExamSubmission.submitted_at.desc()).all()

    result = []
    for s in submissions:
        d = s.to_dict()
        d['passed'] = s.is_passed(s.exam.pass_score) if s.exam else False
        result.append(d)
    return jsonify({'submissions': result})
