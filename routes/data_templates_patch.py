# ==================== 统一模板管理 ====================

@data_bp.route('/templates')
@permission_required("system:config")
def list_templates():
    """统一模板管理页面（按组查看故障模板组+方案模板）"""
    from models import FaultTemplateGroup, SolutionTemplate, FaultTemplateItem
    all_teams = data_service.get_team_options()

    # 所有故障模板组
    fault_groups = FaultTemplateGroup.query.order_by(FaultTemplateGroup.id).all()
    for g in fault_groups:
        g.items = FaultTemplateItem.query.filter_by(
            group_id=g.id
        ).order_by(FaultTemplateItem.sort_order).all()

    # 按组分
    fault_group_map = {'': []}
    for g in fault_groups:
        if g.teams:
            for t in g.teams.split(','):
                t = t.strip()
                if t not in fault_group_map:
                    fault_group_map[t] = []
                fault_group_map[t].append(g)
        else:
            fault_group_map[''].append(g)

    # 所有方案模板
    solutions = SolutionTemplate.query.order_by(SolutionTemplate.title).all()
    solution_map = {'': []}
    for s in solutions:
        if s.teams:
            for t in s.teams.split(','):
                t = t.strip()
                if t not in solution_map:
                    solution_map[t] = []
                solution_map[t].append(s)
        else:
            solution_map[''].append(s)

    return render_template('data/templates.html', all_teams=all_teams,
                           fault_groups=fault_groups, fault_group_map=fault_group_map,
                           solutions=solutions, solution_map=solution_map)


@data_bp.route('/templates/copy-to/<target_team>', methods=['POST'])
@permission_required("system:config")
def copy_templates_to_team(target_team):
    """从华博复制模板到目标组"""
    from models import FaultTemplateGroup, FaultTemplateItem, SolutionTemplate, db
    from urllib.parse import unquote
    target_team = unquote(target_team)
    source_team = '华博'
    template_type = request.args.get('template_type', 'fault')

    imported = 0
    try:
        if template_type == 'fault':
            source_groups = FaultTemplateGroup.query.filter(
                FaultTemplateGroup.teams.contains(source_team)
            ).all()
            for g in source_groups:
                existing = FaultTemplateGroup.query.filter(
                    FaultTemplateGroup.name == g.name,
                    FaultTemplateGroup.teams.contains(target_team)
                ).first()
                if existing:
                    continue
                new_g = FaultTemplateGroup(
                    name=g.name,
                    teams=target_team,
                )
                db.session.add(new_g)
                db.session.flush()
                for item in FaultTemplateItem.query.filter_by(group_id=g.id).all():
                    new_item = FaultTemplateItem(
                        group_id=new_g.id,
                        fault_type=item.fault_type,
                        display_name=item.display_name,
                        default_count=item.default_count,
                        sort_order=item.sort_order,
                    )
                    db.session.add(new_item)
                    imported += 1
        else:
            source_solutions = SolutionTemplate.query.filter(
                SolutionTemplate.teams.contains(source_team)
            ).all()
            for s in source_solutions:
                existing = SolutionTemplate.query.filter(
                    SolutionTemplate.title == s.title,
                    SolutionTemplate.teams.contains(target_team)
                ).first()
                if existing:
                    continue
                new_s = SolutionTemplate(
                    title=s.title, content=s.content,
                    keywords=s.keywords, device_type=s.device_type,
                    fault_type=s.fault_type, fault_subcategory=s.fault_subcategory,
                    teams=target_team,
                )
                db.session.add(new_s)
                imported += 1

        db.session.commit()
        flash(f'已从「{source_team}」复制 {imported} 条{"故障项" if template_type=="fault" else "方案"}到「{target_team}」', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'复制失败：{str(e)}', 'danger')

    return redirect(url_for('data.list_templates'))
