"""电子表单蓝图 - 模板驱动表单系统"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import current_user
from models import db, PaperForm, FormTemplate, WorkOrder, RepairOrder
from datetime import datetime
import json

forms_bp = Blueprint('forms', __name__, url_prefix='/forms')


def login_required_forms(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return wrapper


# 已废弃：自定义渲染模板功能合并到统一A4画布
CUSTOM_RENDER_TEMPLATES = {}


def _get_render_template(form):
    """根据表单关联的模板名称决定渲染哪个 Jinja2 模板"""
    if form.template and form.template.name in CUSTOM_RENDER_TEMPLATES:
        return CUSTOM_RENDER_TEMPLATES[form.template.name]
    # 向后兼容：旧记录仍有 form_type 但没有 template_id
    if form.form_type == 'equipment_distribution':
        return CUSTOM_RENDER_TEMPLATES['设备发放-替换表']
    if form.form_type == 'repair_acceptance':
        return CUSTOM_RENDER_TEMPLATES['维修申请-验收表']
    return 'forms/form_view.html'


# ============ 模板管理 ============

@forms_bp.route('/templates')
@login_required_forms
def template_list():
    templates = FormTemplate.query.order_by(FormTemplate.updated_at.desc()).all()
    return render_template('forms/templates.html', templates=templates)


@forms_bp.route('/templates/create', methods=['GET', 'POST'])
@login_required_forms
def template_create():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        page_size = request.form.get('page_size', 'A4').strip()
        orientation = request.form.get('orientation', 'portrait').strip()
        fields_raw = request.form.get('fields_json', '[]')
        try:
            fields = json.loads(fields_raw)
        except:
            fields = []
        if not name:
            flash('请输入模板名称', 'danger')
            return render_template('forms/template_edit.html', template=None)
        t = FormTemplate(name=name, description=description, fields_json=fields,
                         page_size=page_size, orientation=orientation)
        db.session.add(t)
        db.session.commit()
        flash('✅ 模板已创建', 'success')
        return redirect(url_for('forms.template_list'))
    return render_template('forms/template_edit.html', template=None)


@forms_bp.route('/templates/<int:tid>/edit', methods=['GET', 'POST'])
@login_required_forms
def template_edit(tid):
    t = db.session.get(FormTemplate, tid)
    if not t:
        flash('模板不存在', 'danger')
        return redirect(url_for('forms.template_list'))
    if request.method == 'POST':
        t.name = request.form.get('name', '').strip()
        t.description = request.form.get('description', '').strip()
        t.page_size = request.form.get('page_size', 'A4').strip()
        t.orientation = request.form.get('orientation', 'portrait').strip()
        fields_raw = request.form.get('fields_json', '[]')
        try:
            t.fields_json = json.loads(fields_raw)
        except:
            pass
        db.session.commit()
        flash('✅ 模板已更新', 'success')
        return redirect(url_for('forms.template_list'))
    return render_template('forms/template_edit.html', template=t)


@forms_bp.route('/templates/import-excel', methods=['POST'])
@login_required_forms
def template_import_excel():
    """导入Excel模板，返回解析后的字段列表"""
    import openpyxl
    file = request.files.get('file')
    if not file:
        return jsonify({'error': '请上传文件'}), 400
    if not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({'error': '仅支持 .xlsx / .xls 文件'}), 400
    try:
        wb = openpyxl.load_workbook(file, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return jsonify({'error': '文件为空'}), 400
        # 识别表头行：第一行包含字段含义的关键词
        header_row = rows[0]
        headers = []
        for cell in header_row:
            if cell is None:
                headers.append('')
            else:
                headers.append(str(cell).strip().lower())
        # 判断是否有表头，通过关键词匹配
        has_header = any(k in str(h).lower() for h in headers for k in
                         ['字段名', 'field_label', '标签', 'label', '字段标签', '字段名称',
                          '类型', 'field_type', '字段类型',
                          '必填', 'required',
                          '选项', 'options', 'option'])

        data_rows = rows[1:] if has_header else rows
        field_type_map = {
            '文本': 'text', '单行文本': 'text', '单行': 'text', 'text': 'text',
            '多行文本': 'textarea', '多行': 'textarea', 'textarea': 'textarea',
            '数字': 'number', 'number': 'number', '整数': 'number',
            '下拉': 'select', '下拉选择': 'select', '选择': 'select', 'select': 'select',
            '单选': 'radio', 'radio': 'radio',
            '多选': 'checkbox', 'checkbox': 'checkbox',
            '日期': 'date', 'date': 'date',
            '签名': 'signature', 'signature': 'signature',
            '文件': 'file', '上传': 'file', 'file': 'file',
            '富文本': 'richtext', 'richtext': 'richtext', 'html': 'richtext',
        }

        fields = []
        seen_labels = set()
        # Auto-layout: vertical stack
        cur_y = 3.0   # start top
        gap = 1.2     # gap between rows
        margin = 5.0  # left/right margin %
        for row_idx, row in enumerate(data_rows):
            if not any(cell is not None and str(cell).strip() for cell in row):
                continue  # 跳过空行
            values = [str(cell).strip() if cell is not None else '' for cell in row]

            label = values[0] if len(values) > 0 else ''
            if not label:
                continue
            if label in seen_labels:
                continue
            seen_labels.add(label)

            raw_type = values[1] if len(values) > 1 else 'text'
            field_type = field_type_map.get(raw_type.lower(), 'text')

            raw_required = values[2] if len(values) > 2 else '否'
            required = raw_required.lower() in ('是', 'yes', 'true', '1', '必须', '必填')

            raw_options = values[3] if len(values) > 3 else ''
            # 支持逗号、分号、换行分割
            options = []
            if raw_options:
                for sep in ('\n', ';', '；', ',', '，'):
                    if sep in raw_options:
                        options = [o.strip() for o in raw_options.split(sep) if o.strip()]
                        break
                if not options:
                    options = [raw_options]

            placeholder = values[4] if len(values) > 4 else ''

            default_value = values[5] if len(values) > 5 else ''

            # Auto-detect multi-line content → switch to richtext
            has_newline = '\n' in label or '\\n' in label
            if has_newline and field_type == 'text':
                field_type = 'richtext'

            # Auto-calculate layout: vertical stack, full-width
            field_width = 90.0
            if field_type in ('title', 'header'):
                field_height = 5.0
            elif field_type == 'richtext':
                line_count = label.count('\n') + 1
                field_height = max(5.5, min(18, line_count * 1.5 + 2))
            elif field_type == 'textarea':
                field_height = 8.0
            elif field_type == 'divider':
                field_height = 3.0
            elif field_type == 'signature':
                field_height = 8.0
            elif field_type in ('radio', 'checkbox'):
                opt_count = len(options) if options else 1
                field_height = max(5.5, min(14, opt_count * 2.0 + 2))
            else:
                field_height = 5.5

            # Two-column layout: narrow fields (label-only, checkbox) on left, value on right
            use_two_column = field_type in ('text', 'number', 'date', 'datetime', 'select') and len(label) < 20

            field = {
                'id': 'fld_import_' + str(row_idx + 1),
                'label': label,
                'type': field_type,
                'required': required,
                'placeholder': placeholder,
                'defaultValue': default_value,
                'options': options,
                'fontSize': 16 if field_type == 'title' else (12 if field_type == 'richtext' else None),
                'textAlign': 'center' if field_type in ('title', 'header') else ('left' if field_type == 'richtext' else None),
                'x': margin,
                'y': round(cur_y, 1),
                'w': field_width,
                'h': field_height,
            }
            fields.append(field)
            cur_y += field_height + gap

        if not fields:
            return jsonify({'error': '未能从文件中解析出有效字段，请检查格式'}), 400

        return jsonify({'fields': fields, 'count': len(fields)})

    except Exception as e:
        return jsonify({'error': f'解析失败：{str(e)}'}), 400


@forms_bp.route('/templates/<int:tid>/delete', methods=['POST'])
@login_required_forms
def template_delete(tid):
    t = db.session.get(FormTemplate, tid)
    if not t:
        flash('模板不存在', 'danger')
        return redirect(url_for('forms.template_list'))
    # 检查是否有表单或维修单引用此模板
    ref_forms = PaperForm.query.filter_by(template_id=tid).count()
    ref_repairs = RepairOrder.query.filter_by(template_id=tid).count()
    if ref_forms > 0 or ref_repairs > 0:
        flash(f'❌ 该模板被 {ref_forms} 个表单和 {ref_repairs} 个维修单引用，无法删除。请先删除关联记录', 'danger')
        return redirect(url_for('forms.template_list'))
    try:
        db.session.delete(t)
        db.session.commit()
        flash('✅ 模板已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ 删除失败: {str(e)}', 'danger')
    return redirect(url_for('forms.template_list'))


# ============ 动态表单创建 ============

@forms_bp.route('/create', methods=['GET', 'POST'])
@login_required_forms
def form_create():
    """使用模板创建新表单"""
    if request.method == 'POST':
        template_id = request.form.get('template_id', type=int)
        name = request.form.get('name', '').strip()
        work_order_id = request.form.get('work_order_id', type=int)
        if not name:
            flash('请填写表单名称', 'danger')
            templates = FormTemplate.query.order_by(FormTemplate.updated_at.desc()).all()
            return render_template('forms/form_create.html', templates=templates)
        if not template_id:
            flash('请选择模板', 'danger')
            templates = FormTemplate.query.order_by(FormTemplate.updated_at.desc()).all()
            return render_template('forms/form_create.html', templates=templates)
        form = PaperForm(
            name=name,
            form_type='template',
            template_id=template_id,
            form_data={},
            created_by=current_user.display_name or current_user.username,
        )
        db.session.add(form)
        db.session.flush()

        # 自动创建关联的维修单，同步到维修管理流程
        date_str = datetime.now().strftime('%Y%m%d')
        rep_count = RepairOrder.query.filter(
            RepairOrder.created_at >= datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        ).count()
        # 读取编号前缀（按医院独立配置）
        from models import SystemSetting
        from flask import g
        hid = getattr(g, 'hospital_id', None)
        if hid:
            prefix_setting = SystemSetting.query.filter_by(key='order_prefix', hospital_id=hid).first()
        else:
            prefix_setting = None
        # 降级：读取全局前缀
        if not prefix_setting:
            prefix_setting = SystemSetting.query.filter_by(key='order_prefix').first()
        prefix = (prefix_setting.value or '').strip() if prefix_setting else ''
        order_no = f'{prefix}FS{date_str}-{rep_count + 1:03d}'
        repair_order = RepairOrder(
            template_id=template_id,
            paper_form_id=form.id,
            work_order_id=work_order_id,
            order_no=order_no,
            title=f'【{form.name}】',
            status='draft',
            created_by=current_user.display_name or current_user.username,
        )
        db.session.add(repair_order)
        db.session.commit()
        flash('✅ 表单已创建', 'success')
        return redirect(url_for('forms.form_view', fid=form.id))
    templates = FormTemplate.query.order_by(FormTemplate.updated_at.desc()).all()
    work_order_id = request.args.get('work_order_id', type=int)
    wo = db.session.get(WorkOrder, work_order_id) if work_order_id else None
    return render_template('forms/form_create.html', templates=templates, wo=wo)


# ============ 动态表单查看/编辑 ============

@forms_bp.route('/<int:fid>')
@login_required_forms
def form_view(fid):
    form = db.session.get(PaperForm, fid)
    if not form:
        flash('表单不存在', 'danger')
        return redirect(url_for('forms.form_list'))
    tmpl_name = _get_render_template(form)
    if tmpl_name == 'forms/form_view.html':
        template = form.template
        if not template:
            flash('关联模板不存在', 'danger')
            return redirect(url_for('forms.form_list'))
        return render_template(tmpl_name, form=form, template=template)
    return render_template(tmpl_name, form=form)


@forms_bp.route('/<int:fid>/edit', methods=['POST'])
@login_required_forms
def form_save_fields(fid):
    """保存表单字段值（PC端编辑）"""
    import logging, json, os, sqlite3
    log = logging.getLogger(__name__)
    
    # 直接用 sqlite3 更新（避免 ORM 提交问题）
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'instance', 'workorders.db')
    db_path = os.path.abspath(db_path)
    
    conn = sqlite3.connect(db_path)
    c = conn.execute("SELECT form_data FROM paper_forms WHERE id=?", (fid,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'not found'}), 404
    
    data = request.get_json(silent=True) or {}
    field_values = data.get('field_values', {})
    if not field_values:
        conn.close()
        return jsonify({'error': 'empty data'}), 400
    
    current = json.loads(row[0]) if row[0] else {}
    current.update(field_values)
    conn.execute("UPDATE paper_forms SET form_data=? WHERE id=?", (json.dumps(current, ensure_ascii=False), fid))
    conn.commit()
    conn.close()
    
    log.info('form_save_fields: form=%s saved keys=%s', fid, list(field_values.keys()))
    return jsonify({'message': '已保存', 'saved_keys': list(field_values.keys())})


@forms_bp.route('/<int:fid>/sign', methods=['POST'])
@login_required_forms
def form_field_sign(fid):
    """保存签名"""
    import logging, json, os, sqlite3
    log = logging.getLogger(__name__)
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'instance', 'workorders.db')
    db_path = os.path.abspath(db_path)
    
    conn = sqlite3.connect(db_path)
    c = conn.execute("SELECT form_data FROM paper_forms WHERE id=?", (fid,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'not found'}), 404
    
    data = request.get_json(silent=True) or {}
    field_id = data.get('field_id', '')
    sig_data = data.get('signature', '')
    if not field_id or not sig_data:
        conn.close()
        return jsonify({'error': '参数不完整'}), 400
    
    current = json.loads(row[0]) if row[0] else {}
    current[field_id] = sig_data
    conn.execute("UPDATE paper_forms SET form_data=? WHERE id=?", (json.dumps(current, ensure_ascii=False), fid))
    conn.commit()
    conn.close()
    
    log.info('form_field_sign: form=%s field=%s saved', fid, field_id)
    return jsonify({'message': '签名已保存'})


@forms_bp.route('/<int:fid>/print')
@login_required_forms
def form_print(fid):
    """打印动态表单"""
    form = db.session.get(PaperForm, fid)
    if not form:
        flash('表单不存在', 'danger')
        return redirect(url_for('forms.form_list'))
    tmpl_name = _get_render_template(form)
    if tmpl_name == 'forms/form_view.html':
        template = form.template
        if not template:
            flash('关联模板不存在', 'danger')
            return redirect(url_for('forms.form_list'))
        return render_template('forms/form_print.html', form=form, template=template)
    # 自定义模板的表单打印（已废弃）
    print_map = {}
    print_tmpl = print_map.get(tmpl_name)
    if print_tmpl:
        return render_template(print_tmpl, form=form)
    return render_template('forms/form_print.html', form=form, template=form.template)


# ============ 兼容旧路由（跳转到表单列表）============

@forms_bp.route('/equipment-distribution', methods=['GET'])
@login_required_forms
def equipment_distribution():
    return redirect(url_for('forms.form_list', form_type='equipment_distribution'))


# ============ 列表 ============

@forms_bp.route('/')
@login_required_forms
def form_list():
    form_type = request.args.get('form_type', '')
    query = PaperForm.query
    if form_type:
        query = query.filter(PaperForm.form_type == form_type)
    records = query.order_by(PaperForm.updated_at.desc()).all()
    # 收集所有不重复的表单类型
    distinct_types = db.session.query(PaperForm.form_type).distinct().all()
    type_names = {}
    for (ft,) in distinct_types:
        if ft == 'template':
            type_names[ft] = '模板表单'
        else:
            type_names[ft] = ft
    # 加上模板名称
    for r in records:
        if r.form_type == 'template' and r.template:
            type_names['template'] = r.template.name
    return render_template('forms/list.html', records=records, form_types={}, active_filter=form_type, type_names=type_names)


# ============ 发布 ============

@forms_bp.route('/<int:fid>/publish', methods=['POST'])
@login_required_forms
def form_publish(fid):
    """发布表单：draft → active，创建关联工单"""
    form = db.session.get(PaperForm, fid)
    if not form:
        flash('表单不存在', 'danger')
        return redirect(url_for('forms.form_list'))
    if form.status != 'draft':
        flash('只有草稿状态才能发布', 'danger')
        return redirect(url_for('forms.form_list'))

    fd = form.form_data or {}
    form_type_name = form.template.name if form.template else form.form_type
    wo = WorkOrder(
        title=f'【{form_type_name}】{form.name}',
        description=form.name,
        device_type='其他',
        fault_type='其他',
        building=fd.get('current_location', fd.get('department', '')),
        department=fd.get('department', ''),
        location=fd.get('current_location', ''),
        status='pending',
        person='',
        work_type='form',
        created_by=current_user.display_name or current_user.username,
    )
    db.session.add(wo)
    db.session.flush()

    form.status = 'active'
    form.work_order_id = wo.id
    db.session.commit()

    flash(f'✅ 已发布，生成工单 #{wo.id}', 'success')
    return redirect(url_for('orders.detail', order_id=wo.id))


# ============ 审批 ============

@forms_bp.route('/<int:fid>/approve', methods=['POST'])
@login_required_forms
def form_approve(fid):
    """审批通过表单：submitted → completed，同时完结关联工单"""
    form = db.session.get(PaperForm, fid)
    if not form:
        flash('表单不存在', 'danger')
        return redirect(url_for('forms.form_list'))
    if form.status != 'submitted':
        flash(f'当前状态({form.status})不允许审批', 'danger')
        return redirect(url_for('forms.form_view', fid=fid))

    form.status = 'completed'
    form.updated_at = datetime.now()

    if form.work_order_id:
        wo = db.session.get(WorkOrder, form.work_order_id)
        if wo and wo.status in ('in_progress', 'submitted'):
            wo.status = 'completed'
            wo.completed_at = datetime.now()
            wo.solution = f'电子表单已审批通过: {form.name}'
    db.session.commit()
    flash('✅ 审批通过，表单和工单已完结', 'success')
    return redirect(url_for('forms.form_view', fid=fid))


# ============ 手机端API ============

@forms_bp.route('/api/templates')
@login_required_forms
def api_template_list():
    """返回所有模板的JSON列表（供前端/维修管理下拉选择使用）"""
    templates = FormTemplate.query.order_by(FormTemplate.name).all()
    return jsonify([t.to_dict() for t in templates])


@forms_bp.route('/api/<int:fid>')
@login_required_forms
def form_api_detail(fid):
    form = db.session.get(PaperForm, fid)
    if not form:
        return jsonify({'error': 'not found'}), 404
    return jsonify(form.to_dict())


@forms_bp.route('/api/<int:fid>/save', methods=['POST'])
@login_required_forms
def form_api_save(fid):
    form = db.session.get(PaperForm, fid)
    if not form:
        return jsonify({'error': 'not found'}), 404
    if form.status != 'active':
        return jsonify({'error': '当前状态不允许修改'}), 400
    data = request.get_json(silent=True) or {}
    field_data = data.get('form_data', {})
    current = form.form_data or {}
    current.update(field_data)
    form.form_data = current
    db.session.commit()
    return jsonify({'message': '已保存'})


@forms_bp.route('/api/<int:fid>/sign', methods=['POST'])
@login_required_forms
def form_api_sign(fid):
    form = db.session.get(PaperForm, fid)
    if not form:
        return jsonify({'error': 'not found'}), 404
    data = request.get_json(silent=True) or {}
    field_id = data.get('field_id', '')
    sig_data = data.get('signature', '')
    if not field_id or not sig_data:
        return jsonify({'error': '参数不完整'}), 400
    fd = form.form_data or {}
    fd[field_id] = sig_data
    form.form_data = fd
    db.session.commit()
    return jsonify({'message': '签名已保存'})

@forms_bp.route('/api/<int:fid>/submit', methods=['POST'])
@login_required_forms
def form_api_submit(fid):
    """提交表单待审批：active → submitted"""
    form = db.session.get(PaperForm, fid)
    if not form:
        return jsonify({'error': 'not found'}), 404
    if form.status not in ('active', 'submitted'):
        return jsonify({'error': f'当前状态({form.status})不允许提交'}), 400
    form.status = 'submitted'
    form.updated_at = datetime.now()
    db.session.commit()
    return jsonify({'message': '已提交审批', 'status': 'submitted'})


# ============ 数据源API ============

@forms_bp.route('/api/data-sources')
@login_required_forms
def form_data_sources():
    """返回所有可用数据源的选项列表"""
    from models import User, WorkOrder, Asset, FaultType, Supplier
    from services.keyword_config import get_device_keywords
    from datetime import datetime

    dk = get_device_keywords()
    if dk and isinstance(dk[0], (list, tuple)):
        device_types = [d[0] for d in dk]
    elif isinstance(dk, dict):
        device_types = dk.get('device_types', [])
    else:
        device_types = []

    users = User.query.order_by(User.display_name).all()
    personnel = [{'value': u.display_name or u.username, 'label': f"{u.display_name or u.username}"} for u in users]

    dept_q = db.session.query(WorkOrder.department).distinct().filter(WorkOrder.department != '', WorkOrder.department.isnot(None)).all()
    departments = sorted(set(d[0] for d in dept_q if d[0]))

    loc_q = db.session.query(WorkOrder.building).distinct().filter(WorkOrder.building != '', WorkOrder.building.isnot(None)).all()
    locations = sorted(set(l[0] for l in loc_q if l[0]))
    
    bld_q = db.session.query(Asset.building).distinct().filter(Asset.building != '', Asset.building.isnot(None)).all()
    buildings = sorted(set(b[0] for b in bld_q if b[0]))
    
    assets = Asset.query.order_by(Asset.asset_no).all()
    asset_codes = [{'value': a.asset_no, 'label': f"{a.asset_no} - {a.model_no or a.device_type or ''}"} for a in assets]
    
    suppliers = []
    try:
        supps = Supplier.query.order_by(Supplier.name).all()
        suppliers = [{'value': s.name, 'label': s.name} for s in supps]
    except:
        pass
    
    fault_types = []
    try:
        fts = FaultType.query.order_by(FaultType.name).all()
        fault_types = [{'value': ft.name, 'label': ft.name} for ft in fts]
    except:
        pass
    
    now = datetime.now()
    
    return jsonify({
        'current_user': {'value': name, 'label': name or '未登录'},
        'current_date': {'value': now.strftime('%Y-%m-%d'), 'label': now.strftime('%Y-%m-%d')},
        'current_time': {'value': now.strftime('%Y-%m-%d %H:%M'), 'label': now.strftime('%Y-%m-%d %H:%M')},
        'personnel': [{'value': p['value'], 'label': p['label']} for p in personnel],
        'department': [{'value': d, 'label': d} for d in departments],
        'device_type': [{'value': d, 'label': d} for d in device_types],
        'location': [{'value': l, 'label': l} for l in locations],
        'building': [{'value': b, 'label': b} for b in buildings],
        'asset_code': [{'value': a['value'], 'label': a['label']} for a in asset_codes],
        'supplier': [{'value': s['value'], 'label': s['label']} for s in suppliers],
        'fault_type': [{'value': f['value'], 'label': f['label']} for f in fault_types],
        'order_no': {'value': '', 'label': 'WX' + now.strftime('%Y%m%d%H%M%S')},
        'repair_order_no': {'value': '', 'label': 'WX' + now.strftime('%Y%m%d%H%M%S')},
    })


# ============ 删除 ============

@forms_bp.route('/<int:fid>/delete', methods=['POST'])
@login_required_forms
def form_delete(fid):
    form = db.session.get(PaperForm, fid)
    if form:
        db.session.delete(form)
        db.session.commit()
        flash('✅ 已删除', 'success')
    return redirect(url_for('forms.form_list'))


# ============ 扫码签名 ============

@forms_bp.route('/sign/<token>')
def mobile_sign_page(token):
    """手机签名页面（无需登录）"""
    try:
        parts = token.split('-')
        form_id = int(parts[0])
        field_id = '-'.join(parts[1:])
    except (ValueError, IndexError):
        return '无效的签名链接', 400
    form = db.session.get(PaperForm, form_id)
    if not form:
        return '表单不存在', 404
    return render_template('forms/sign_page.html',
                           form=form, field_id=field_id, token=token)


@forms_bp.route('/api/check-signature/<token>')
def check_signature(token):
    """检查签名状态"""
    try:
        parts = token.split('-')
        form_id = int(parts[0])
        field_id = '-'.join(parts[1:])
    except (ValueError, IndexError):
        return jsonify({'signed': False}), 400
    import json
    form = db.session.get(PaperForm, form_id)
    if not form:
        return jsonify({'signed': False}), 404
    field_sig = (form.form_data or {}).get(field_id, '')
    signed = bool(field_sig and field_sig.startswith('data:image'))
    return jsonify({
        'signed': signed,
        'signature': field_sig if signed else '',
    })


# ============ 出库扫码签名 ============

@forms_bp.route('/sign-stock/<token>')
def mobile_sign_stock_page(token):
    """手机端出库签名页面（无需登录）"""
    from models import StockSignRequest
    req = StockSignRequest.query.filter_by(token=token).first()
    if not req:
        return '签名链接已失效', 400
    return render_template('forms/sign_stock_page.html', token=token)


@forms_bp.route('/api/check-stock-sign/<token>')
def check_stock_sign(token):
    """检查出库签名状态"""
    from models import StockSignRequest
    req = StockSignRequest.query.filter_by(token=token).first()
    if not req:
        return jsonify({'signed': False}), 404
    signed = req.status == 'signed'
    return jsonify({
        'signed': signed,
        'signature': req.signature if signed else '',
    })


@forms_bp.route('/api/submit-stock-sign', methods=['POST'])
def submit_stock_sign():
    """手机端提交出库签名"""
    from models import StockSignRequest, db
    from datetime import datetime
    token = request.form.get('token', '')
    signature = request.form.get('signature', '')
    if not token or not signature:
        return jsonify({'ok': False, 'msg': '参数不完整'}), 400
    req = StockSignRequest.query.filter_by(token=token).first()
    if not req:
        return jsonify({'ok': False, 'msg': '签名请求不存在'}), 404
    if req.status != 'pending':
        return jsonify({'ok': False, 'msg': '已签名，请勿重复提交'}), 400
    req.signature = signature
    req.status = 'signed'
    req.signed_at = datetime.now()
    db.session.commit()
    return jsonify({'ok': True})


# ==================== 耗材签名 ====================

@forms_bp.route('/sign-consumable/<token>')
def mobile_sign_consumable_page(token):
    """手机端耗材出库签名页面（无需登录）"""
    from models import ConsumableSignRequest
    req = ConsumableSignRequest.query.filter_by(token=token).first()
    if not req:
        return '签名链接已失效', 400
    return render_template('forms/sign_consumable_page.html', token=token)


@forms_bp.route('/api/check-consumable-sign/<token>')
def check_consumable_sign(token):
    """检查耗材出库签名状态"""
    from models import ConsumableSignRequest
    req = ConsumableSignRequest.query.filter_by(token=token).first()
    if not req:
        return jsonify({'signed': False}), 404
    signed = req.status == 'signed'
    return jsonify({
        'signed': signed,
        'signature': req.signature if signed else '',
    })


@forms_bp.route('/api/submit-consumable-sign', methods=['POST'])
def submit_consumable_sign():
    """手机端提交耗材出库签名"""
    from models import ConsumableSignRequest, db
    from datetime import datetime
    token = request.form.get('token', '')
    signature = request.form.get('signature', '')
    if not token or not signature:
        return jsonify({'ok': False, 'msg': '参数不完整'}), 400
    req = ConsumableSignRequest.query.filter_by(token=token).first()
    if not req:
        return jsonify({'ok': False, 'msg': '签名请求不存在'}), 404
    if req.status != 'pending':
        return jsonify({'ok': False, 'msg': '已签名，请勿重复提交'}), 400
    req.signature = signature
    req.status = 'signed'
    req.signed_at = datetime.now()
    db.session.commit()
    return jsonify({'ok': True})
