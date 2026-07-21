"""财务资产路由——固定资产入库单/出库单管理"""
import math
from datetime import date, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_required, current_user
from sqlalchemy import func

from models import db, FinanceReceipt, FinanceReceiptItem, FinanceDelivery, FinanceDeliveryItem, Supplier, SystemSetting

fin_bp = Blueprint('finance_asset', __name__, url_prefix='/finasset')


# ==================== 工具函数 ====================

def _num_to_cny(n):
    """数字转大写人民币金额"""
    if n is None:
        return '零圆整'
    n = round(float(n), 2)
    digits = '零壹贰叁肆伍陆柒捌玖'
    units = ['', '拾', '佰', '仟', '万', '拾', '佰', '仟', '亿']
    integer_part = int(math.floor(n))
    decimal_part = round((n - integer_part) * 100)

    def _convert_int(num):
        if num == 0:
            return '零'
        s = ''
        i = 0
        zero_flag = False
        while num > 0:
            digit = num % 10
            if digit == 0:
                if not zero_flag and i > 0 and (i % 4) != 0:
                    s = '零' + s
                    zero_flag = True
            else:
                s = digits[digit] + units[i] + s
                zero_flag = False
            num //= 10
            i += 1
        return s

    result = ''
    if integer_part > 0:
        result += _convert_int(integer_part) + '圆'
    if decimal_part == 0:
        result += '整'
    else:
        if integer_part > 0 and decimal_part < 10:
            result += '零'
        jiao = decimal_part // 10
        fen = decimal_part % 10
        if jiao > 0:
            result += digits[jiao] + '角'
        if fen > 0:
            result += digits[fen] + '分'
    return result if result else '零圆整'


def _next_doc_no(prefix='ZJCD'):
    """生成单据编号：前缀 + 日期(8位) + 当日序号(3位)"""
    today_str = date.today().strftime('%Y%m%d')
    prefix_full = prefix + today_str
    # 查询今日最大序号
    last = FinanceReceipt.query.filter(
        FinanceReceipt.doc_no.like(prefix_full + '%')
    ).order_by(FinanceReceipt.doc_no.desc()).first()
    if last:
        seq = int(last.doc_no[-3:]) + 1
    else:
        seq = 1
    return f'{prefix_full}{seq:03d}'


def _next_delivery_no():
    """生成出库单编号：KSCK + 日期 + 序号"""
    today_str = date.today().strftime('%Y%m%d')
    prefix_full = 'KSCK' + today_str
    last = FinanceDelivery.query.filter(
        FinanceDelivery.doc_no.like(prefix_full + '%')
    ).order_by(FinanceDelivery.doc_no.desc()).first()
    if last:
        seq = int(last.doc_no[-3:]) + 1
    else:
        seq = 1
    return f'{prefix_full}{seq:03d}'


# ==================== 统一资产管理页面 ====================

@fin_bp.route('/')
@login_required
def index():
    """统一固定资产管理：全部 / 入库 / 出库 三Tab"""
    tab = request.args.get('tab', 'all')
    page = request.args.get('page', 1, type=int)
    per_page = 20
    kw = request.args.get('keyword', '').strip()
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    # 解析日期
    def _parse_date(s):
        try:
            return datetime.strptime(s, '%Y-%m-%d')
        except:
            return None
    dt_from = _parse_date(date_from)
    dt_to = _parse_date(date_to)

    if tab == 'receipt':
        # 入库列表
        query = FinanceReceipt.query
        if kw:
            query = query.filter(
                FinanceReceipt.doc_no.contains(kw) |
                FinanceReceipt.warehouse.contains(kw) |
                FinanceReceipt.operator.contains(kw)
            )
        if dt_from:
            query = query.filter(FinanceReceipt.receipt_date >= dt_from)
        if dt_to:
            query = query.filter(FinanceReceipt.receipt_date <= dt_to)
        query = query.order_by(FinanceReceipt.created_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        items = pagination.items
        page_obj = pagination
        endpoint_for_page = 'finance_asset.index'

    elif tab == 'delivery':
        # 出库列表
        query = FinanceDelivery.query
        if kw:
            query = query.filter(
                FinanceDelivery.doc_no.contains(kw) |
                FinanceDelivery.warehouse.contains(kw) |
                FinanceDelivery.recipient.contains(kw)
            )
        if dt_from:
            query = query.filter(FinanceDelivery.delivery_date >= dt_from)
        if dt_to:
            query = query.filter(FinanceDelivery.delivery_date <= dt_to)
        query = query.order_by(FinanceDelivery.created_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        items = pagination.items
        page_obj = pagination
        endpoint_for_page = 'finance_asset.index'

    else:
        # 全部：合并入库+出库，按创建时间排序
        receipts = FinanceReceipt.query
        deliveries = FinanceDelivery.query
        if kw:
            receipts = receipts.filter(
                FinanceReceipt.doc_no.contains(kw) |
                FinanceReceipt.warehouse.contains(kw) |
                FinanceReceipt.operator.contains(kw)
            )
            deliveries = deliveries.filter(
                FinanceDelivery.doc_no.contains(kw) |
                FinanceDelivery.warehouse.contains(kw) |
                FinanceDelivery.recipient.contains(kw)
            )
        if dt_from:
            receipts = receipts.filter(FinanceReceipt.receipt_date >= dt_from)
            deliveries = deliveries.filter(FinanceDelivery.delivery_date >= dt_from)
        if dt_to:
            receipts = receipts.filter(FinanceReceipt.receipt_date <= dt_to)
            deliveries = deliveries.filter(FinanceDelivery.delivery_date <= dt_to)

        receipts = receipts.order_by(FinanceReceipt.created_at.desc()).all()
        deliveries = deliveries.order_by(FinanceDelivery.created_at.desc()).all()

        # 合并成统一列表
        combined = []
        for r in receipts:
            combined.append({
                'type': 'receipt',
                'id': r.id,
                'doc_no': r.doc_no,
                'title': r.title or '',
                'warehouse': r.warehouse or '',
                'supplier_name': r.supplier.name if r.supplier else '-',
                'amount': float(r.total_amount or 0),
                'date': r.receipt_date,
                'date_str': r.receipt_date.strftime('%Y-%m-%d') if r.receipt_date else '-',
                'operator': r.operator or '',
                'created_at': r.created_at,
                'recipient': '',
                'detail_url': url_for('finance_asset.receipt_detail', receipt_id=r.id),
                'edit_url': url_for('finance_asset.receipt_edit', receipt_id=r.id),
                'print_url': url_for('finance_asset.receipt_print', receipt_id=r.id),
                'delete_url': url_for('finance_asset.receipt_delete', receipt_id=r.id),
            })
        for d in deliveries:
            combined.append({
                'type': 'delivery',
                'id': d.id,
                'doc_no': d.doc_no,
                'title': d.title or '',
                'warehouse': d.warehouse or '',
                'supplier_name': d.supplier.name if d.supplier else '-',
                'amount': float(d.total_amount or 0),
                'date': d.delivery_date,
                'date_str': d.delivery_date.strftime('%Y-%m-%d') if d.delivery_date else '-',
                'operator': d.recipient or '',
                'created_at': d.created_at,
                'recipient': d.recipient or '',
                'detail_url': url_for('finance_asset.delivery_detail', delivery_id=d.id),
                'edit_url': url_for('finance_asset.delivery_edit', delivery_id=d.id),
                'print_url': url_for('finance_asset.delivery_print', delivery_id=d.id),
                'delete_url': url_for('finance_asset.delivery_delete', delivery_id=d.id),
            })

        # 按创建时间倒序
        combined.sort(key=lambda x: x['created_at'] or datetime.min, reverse=True)
        # 全量总数+当前页切片
        total_all = len(combined)
        start = (page - 1) * per_page
        end = start + per_page
        items = combined[start:end]
        page_obj = None  # 非SQL分页，手工分
        endpoint_for_page = 'finance_asset.index'

    return render_template('finance/asset_list.html',
                           tab=tab, items=items, page_obj=page_obj,
                           total_all=total_all if tab == 'all' else (page_obj.total if page_obj else 0),
                           page=page, per_page=per_page,
                           keyword=kw, date_from=date_from, date_to=date_to,
                           endpoint_for_page=endpoint_for_page,
                           now=datetime.now())


# ==================== 入库单列表 ====================

@fin_bp.route('/receipts/')
@login_required
def receipt_list():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    kw = request.args.get('keyword', '').strip()
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    query = FinanceReceipt.query
    if kw:
        query = query.filter(
            FinanceReceipt.doc_no.contains(kw) |
            FinanceReceipt.warehouse.contains(kw) |
            FinanceReceipt.operator.contains(kw)
        )
    if date_from:
        try:
            dt = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(FinanceReceipt.receipt_date >= dt)
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.strptime(date_to, '%Y-%m-%d')
            query = query.filter(FinanceReceipt.receipt_date <= dt)
        except ValueError:
            pass

    query = query.order_by(FinanceReceipt.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template('finance/receipt_list.html',
                           pagination=pagination,
                           receipts=pagination.items,
                           keyword=kw, date_from=date_from, date_to=date_to,
                           now=datetime.now())


# ==================== 入库单创建/编辑 ====================

@fin_bp.route('/receipts/create', methods=['GET', 'POST'])
@login_required
def receipt_create():
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.sort_order, Supplier.name).all()
    doc_no = _next_doc_no()

    if request.method == 'POST':
        try:
            receipt = FinanceReceipt(
                doc_no=request.form.get('doc_no', doc_no),
                title=request.form.get('title', '固定资产入库单'),
                supplier_id=request.form.get('supplier_id', type=int) or None,
                receipt_date=datetime.strptime(request.form['receipt_date'], '%Y-%m-%d').date() if request.form.get('receipt_date') else date.today(),
                operator=request.form.get('operator', current_user.username or ''),
                warehouse=request.form.get('warehouse', ''),
                invoice_date=datetime.strptime(request.form['invoice_date'], '%Y-%m-%d').date() if request.form.get('invoice_date') else None,
                invoice_no=request.form.get('invoice_no', ''),
                manager=request.form.get('manager', ''),
                inspector=request.form.get('inspector', ''),
                purchaser=request.form.get('purchaser', ''),
                remark=request.form.get('remark', ''),
            )
            db.session.add(receipt)
            db.session.flush()

            total = 0
            items_data = request.form.getlist('item_name[]')
            for i, name in enumerate(items_data):
                if not name.strip():
                    continue
                qty = int(request.form.getlist('quantity[]')[i] or 1)
                price = float(request.form.getlist('unit_price[]')[i] or 0)
                amt = float(request.form.getlist('amount[]')[i] or 0)
                item = FinanceReceiptItem(
                    receipt_id=receipt.id,
                    sort_order=i + 1,
                    department=request.form.getlist('department[]')[i] or '',
                    item_name=name.strip(),
                    model_spec=request.form.getlist('model_spec[]')[i] or '',
                    unit=request.form.getlist('unit[]')[i] or '台',
                    quantity=qty,
                    unit_price=price,
                    amount=amt,
                )
                db.session.add(item)
                total += amt

            receipt.total_amount = total
            receipt.amount_words = _num_to_cny(total)
            db.session.commit()
            flash(f'入库单 {receipt.doc_no} 创建成功', 'success')
            return redirect(url_for('finance_asset.receipt_detail', receipt_id=receipt.id))
        except Exception as e:
            db.session.rollback()
            flash(f'创建失败: {str(e)}', 'danger')

    return render_template('finance/receipt_form.html',
                           receipt=None, suppliers=suppliers,
                           doc_no=doc_no, now=datetime.now())


@fin_bp.route('/receipts/<int:receipt_id>/edit', methods=['GET', 'POST'])
@login_required
def receipt_edit(receipt_id):
    receipt = FinanceReceipt.query.get_or_404(receipt_id)
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.sort_order, Supplier.name).all()

    if request.method == 'POST':
        try:
            receipt.title = request.form.get('title', '固定资产入库单')
            receipt.supplier_id = request.form.get('supplier_id', type=int) or None
            if request.form.get('receipt_date'):
                receipt.receipt_date = datetime.strptime(request.form['receipt_date'], '%Y-%m-%d').date()
            receipt.operator = request.form.get('operator', receipt.operator)
            receipt.warehouse = request.form.get('warehouse', '')
            if request.form.get('invoice_date'):
                receipt.invoice_date = datetime.strptime(request.form['invoice_date'], '%Y-%m-%d').date()
            else:
                receipt.invoice_date = None
            receipt.invoice_no = request.form.get('invoice_no', '')
            receipt.manager = request.form.get('manager', '')
            receipt.inspector = request.form.get('inspector', '')
            receipt.purchaser = request.form.get('purchaser', '')
            receipt.remark = request.form.get('remark', '')

            # 删除旧明细重新添加
            FinanceReceiptItem.query.filter_by(receipt_id=receipt.id).delete()
            total = 0
            items_data = request.form.getlist('item_name[]')
            for i, name in enumerate(items_data):
                if not name.strip():
                    continue
                qty = int(request.form.getlist('quantity[]')[i] or 1)
                price = float(request.form.getlist('unit_price[]')[i] or 0)
                amt = float(request.form.getlist('amount[]')[i] or 0)
                item = FinanceReceiptItem(
                    receipt_id=receipt.id,
                    sort_order=i + 1,
                    department=request.form.getlist('department[]')[i] or '',
                    item_name=name.strip(),
                    model_spec=request.form.getlist('model_spec[]')[i] or '',
                    unit=request.form.getlist('unit[]')[i] or '台',
                    quantity=qty,
                    unit_price=price,
                    amount=amt,
                )
                db.session.add(item)
                total += amt

            receipt.total_amount = total
            receipt.amount_words = _num_to_cny(total)
            db.session.commit()
            flash('入库单已更新', 'success')
            return redirect(url_for('finance_asset.receipt_detail', receipt_id=receipt.id))
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败: {str(e)}', 'danger')

    return render_template('finance/receipt_form.html',
                           receipt=receipt, suppliers=suppliers,
                           doc_no=receipt.doc_no, now=datetime.now())


# ==================== 入库单详情/删除/打印 ====================

@fin_bp.route('/receipts/<int:receipt_id>')
@login_required
def receipt_detail(receipt_id):
    receipt = FinanceReceipt.query.get_or_404(receipt_id)
    items = FinanceReceiptItem.query.filter_by(receipt_id=receipt_id).order_by(FinanceReceiptItem.sort_order).all()
    return render_template('finance/receipt_detail.html', receipt=receipt, items=items)


@fin_bp.route('/receipts/<int:receipt_id>/delete', methods=['POST'])
@login_required
def receipt_delete(receipt_id):
    receipt = FinanceReceipt.query.get_or_404(receipt_id)
    doc_no = receipt.doc_no
    FinanceReceiptItem.query.filter_by(receipt_id=receipt_id).delete()
    db.session.delete(receipt)
    db.session.commit()
    flash(f'入库单 {doc_no} 已删除', 'success')
    return redirect(url_for('finance_asset.receipt_list'))


@fin_bp.route('/receipts/<int:receipt_id>/print')
@login_required
def receipt_print(receipt_id):
    receipt = FinanceReceipt.query.get_or_404(receipt_id)
    items = FinanceReceiptItem.query.filter_by(receipt_id=receipt_id).order_by(FinanceReceiptItem.sort_order).all()
    # 发票类型映射
    inv_types = {'0001': '增值税发票'}
    inv_type_label = inv_types.get('0001', '')
    return render_template('finance/receipt_print.html',
                           receipt=receipt, items=items, inv_type_label=inv_type_label)


@fin_bp.route('/receipts/<int:receipt_id>/pdf')
@login_required
def receipt_pdf(receipt_id):
    """通过Puppeteer生成240×140mm横向PDF，直接匹配纸张尺寸"""
    receipt = FinanceReceipt.query.get_or_404(receipt_id)
    items = FinanceReceiptItem.query.filter_by(receipt_id=receipt_id).order_by(FinanceReceiptItem.sort_order).all()
    inv_types = {'0001': '增值税发票'}
    inv_type_label = inv_types.get('0001', '')
    
    html = render_template('finance/receipt_print.html',
                           receipt=receipt, items=items, inv_type_label=inv_type_label)
    
    import tempfile, subprocess, os
    tmp_in = tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False)
    tmp_out = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    tmp_in.write(html)
    tmp_in.close()
    tmp_out.close()
    
    script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'generate_pdf.js')
    try:
        result = subprocess.run(
            ['/usr/bin/node', script_path, '240mm', '140mm', tmp_out.name],
            stdin=open(tmp_in.name),
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            current_app.logger.error(f'PDF生成失败: {result.stderr}')
            return f'PDF生成失败: {result.stderr}', 500
        with open(tmp_out.name, 'rb') as f:
            pdf_data = f.read()
    except Exception as e:
        current_app.logger.error(f'PDF生成失败: {e}')
        return f'PDF生成失败: {e}', 500
    finally:
        os.unlink(tmp_in.name)
        os.unlink(tmp_out.name)
    
    from flask import Response
    return Response(pdf_data, mimetype='application/pdf',
                    headers={'Content-Disposition': f'inline; filename="receipt_{receipt_id}.pdf"'})


# ==================== 出库单列表 ====================

@fin_bp.route('/deliveries/')
@login_required
def delivery_list():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    kw = request.args.get('keyword', '').strip()
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    query = FinanceDelivery.query
    if kw:
        query = query.filter(
            FinanceDelivery.doc_no.contains(kw) |
            FinanceDelivery.warehouse.contains(kw) |
            FinanceDelivery.recipient.contains(kw)
        )
    if date_from:
        try:
            dt = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(FinanceDelivery.delivery_date >= dt)
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.strptime(date_to, '%Y-%m-%d')
            query = query.filter(FinanceDelivery.delivery_date <= dt)
        except ValueError:
            pass

    query = query.order_by(FinanceDelivery.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template('finance/delivery_list.html',
                           pagination=pagination,
                           deliveries=pagination.items,
                           keyword=kw, date_from=date_from, date_to=date_to,
                           now=datetime.now())


# ==================== 出库单创建/编辑 ====================

@fin_bp.route('/deliveries/create', methods=['GET', 'POST'])
@login_required
def delivery_create():
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.sort_order, Supplier.name).all()
    doc_no = _next_delivery_no()

    if request.method == 'POST':
        try:
            delivery = FinanceDelivery(
                doc_no=request.form.get('doc_no', doc_no),
                title=request.form.get('title', '固定资产出库单'),
                supplier_id=request.form.get('supplier_id', type=int) or None,
                delivery_date=datetime.strptime(request.form['delivery_date'], '%Y-%m-%d').date() if request.form.get('delivery_date') else date.today(),
                recipient=request.form.get('recipient', ''),
                warehouse=request.form.get('warehouse', ''),
                invoice_type=request.form.get('invoice_type', '0001'),
                sender=request.form.get('sender', ''),
                receiver=request.form.get('receiver', ''),
                remark=request.form.get('remark', ''),
            )
            db.session.add(delivery)
            db.session.flush()

            total = 0
            items_data = request.form.getlist('item_name[]')
            for i, name in enumerate(items_data):
                if not name.strip():
                    continue
                qty = int(request.form.getlist('quantity[]')[i] or 1)
                price = float(request.form.getlist('unit_price[]')[i] or 0)
                amt = float(request.form.getlist('amount[]')[i] or 0)
                item = FinanceDeliveryItem(
                    delivery_id=delivery.id,
                    sort_order=i + 1,
                    item_name=name.strip(),
                    unit=request.form.getlist('unit[]')[i] or '台',
                    quantity=qty,
                    unit_price=price,
                    amount=amt,
                    invoice_no=request.form.getlist('invoice_no[]')[i] or '',
                )
                db.session.add(item)
                total += amt

            delivery.total_amount = total
            delivery.amount_words = _num_to_cny(total)
            db.session.commit()
            flash(f'出库单 {delivery.doc_no} 创建成功', 'success')
            return redirect(url_for('finance_asset.delivery_detail', delivery_id=delivery.id))
        except Exception as e:
            db.session.rollback()
            flash(f'创建失败: {str(e)}', 'danger')

    return render_template('finance/delivery_form.html',
                           delivery=None, suppliers=suppliers,
                           doc_no=doc_no, now=datetime.now())


@fin_bp.route('/deliveries/<int:delivery_id>/edit', methods=['GET', 'POST'])
@login_required
def delivery_edit(delivery_id):
    delivery = FinanceDelivery.query.get_or_404(delivery_id)
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.sort_order, Supplier.name).all()

    if request.method == 'POST':
        try:
            delivery.title = request.form.get('title', '固定资产出库单')
            delivery.supplier_id = request.form.get('supplier_id', type=int) or None
            if request.form.get('delivery_date'):
                delivery.delivery_date = datetime.strptime(request.form['delivery_date'], '%Y-%m-%d').date()
            delivery.recipient = request.form.get('recipient', '')
            delivery.warehouse = request.form.get('warehouse', '')
            delivery.invoice_type = request.form.get('invoice_type', '0001')
            delivery.sender = request.form.get('sender', '')
            delivery.receiver = request.form.get('receiver', '')
            delivery.remark = request.form.get('remark', '')

            FinanceDeliveryItem.query.filter_by(delivery_id=delivery.id).delete()
            total = 0
            items_data = request.form.getlist('item_name[]')
            for i, name in enumerate(items_data):
                if not name.strip():
                    continue
                qty = int(request.form.getlist('quantity[]')[i] or 1)
                price = float(request.form.getlist('unit_price[]')[i] or 0)
                amt = float(request.form.getlist('amount[]')[i] or 0)
                item = FinanceDeliveryItem(
                    delivery_id=delivery.id,
                    sort_order=i + 1,
                    item_name=name.strip(),
                    unit=request.form.getlist('unit[]')[i] or '台',
                    quantity=qty,
                    unit_price=price,
                    amount=amt,
                    invoice_no=request.form.getlist('invoice_no[]')[i] or '',
                )
                db.session.add(item)
                total += amt

            delivery.total_amount = total
            delivery.amount_words = _num_to_cny(total)
            db.session.commit()
            flash('出库单已更新', 'success')
            return redirect(url_for('finance_asset.delivery_detail', delivery_id=delivery.id))
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败: {str(e)}', 'danger')

    return render_template('finance/delivery_form.html',
                           delivery=delivery, suppliers=suppliers,
                           doc_no=delivery.doc_no, now=datetime.now())


# ==================== 出库单详情/删除/打印 ====================

@fin_bp.route('/deliveries/<int:delivery_id>')
@login_required
def delivery_detail(delivery_id):
    delivery = FinanceDelivery.query.get_or_404(delivery_id)
    items = FinanceDeliveryItem.query.filter_by(delivery_id=delivery_id).order_by(FinanceDeliveryItem.sort_order).all()
    return render_template('finance/delivery_detail.html', delivery=delivery, items=items)


@fin_bp.route('/deliveries/<int:delivery_id>/delete', methods=['POST'])
@login_required
def delivery_delete(delivery_id):
    delivery = FinanceDelivery.query.get_or_404(delivery_id)
    doc_no = delivery.doc_no
    FinanceDeliveryItem.query.filter_by(delivery_id=delivery_id).delete()
    db.session.delete(delivery)
    db.session.commit()
    flash(f'出库单 {doc_no} 已删除', 'success')
    return redirect(url_for('finance_asset.delivery_list'))


@fin_bp.route('/deliveries/<int:delivery_id>/print')
@login_required
def delivery_print(delivery_id):
    delivery = FinanceDelivery.query.get_or_404(delivery_id)
    items = FinanceDeliveryItem.query.filter_by(delivery_id=delivery_id).order_by(FinanceDeliveryItem.sort_order).all()
    # 从系统设置获取发票类型映射
    inv_type_map = SystemSetting.get('finance_invoice_types') or '{"0001":"增值税发票"}'
    import json
    try:
        inv_types = json.loads(inv_type_map)
    except:
        inv_types = {'0001': '增值税发票'}
    invoice_type_label = inv_types.get(delivery.invoice_type, delivery.invoice_type)
    return render_template('finance/delivery_print.html',
                           delivery=delivery, items=items,
                           invoice_type_label=invoice_type_label)


