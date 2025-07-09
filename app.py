from flask import Flask, render_template, request, redirect, url_for, render_template_string, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from pathlib import Path
import sys
from sqlalchemy import or_, and_
from collections import Counter
import re
import pandas as pd
import io

from utils.read_info import read_job_info, read_dungeon_info, read_server_info
from utils.user_settings import load_settings, save_settings

# 若果是打包后的应用，使用 sys.executable 获取可执行文件路径
# 如果是未打包的应用，使用 __file__ 获取当前脚本路径
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

# 实例（数据库 + 用户设置）目录
INSTANCE_DIR = BASE_DIR / 'instance'
if not INSTANCE_DIR.exists():
    INSTANCE_DIR.mkdir(parents=True)
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{INSTANCE_DIR / "database.db"}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

SETTINGS_PATH = INSTANCE_DIR / 'user_settings.json'

# 基本数据目录
DATA_DIR = BASE_DIR / Path('data')

# 数据模型
class Record(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job = db.Column(db.String(50), nullable=False)
    time = db.Column(db.DateTime, default=datetime.now)
    server = db.Column(db.String(50), nullable=False)
    dungeon = db.Column(db.String(100), nullable=False)
    dungeon_level = db.Column(db.String(20), nullable=False)
    dungeon_type = db.Column(db.String(20), nullable=False)
    note = db.Column(db.Text)


@app.route('/')
def index():
    settings = load_settings(SETTINGS_PATH) 
    username = settings.get('username', '<未设置用户名>')
    target_count = settings.get('target_count', 2000)

    total_records = Record.query.count()
    percent = 0
    if target_count:
        percent = f"{min(100, total_records / target_count * 100):.1f}"

    return render_template('index.html',
                           username=username,
                           total_records=total_records,
                           target_count=target_count,
                           percent=percent,
                           active_page='index')


@app.route('/record')
def record():
    # 分页参数
    page = request.args.get('page', 1, type=int)
    per_page = int(request.args.get('per_page', 10))
    order = request.args.get('order', 'desc')
    # 搜索参数
    q_raw = request.args.get('q', '').strip()
    keywords = q_raw.split()

    # 指定字段搜索的正则表达式
    field_patterns = {
        '职业': 'job',
        '大区': 'server',
        '副本名': 'dungeon',
        '副本类型': 'dungeon_type',
        '副本等级': 'dungeon_level',
        '时间': 'time',
        '职能': 'attr'  # 特殊字段，需要通过 job_attr_map 映射判断
    }

    # 副本类型映射
    dungeon_type_map = {
        '迷宫挑战': '0',
        '行会令': '1',
        '讨伐歼灭战': '2',
        '大型任务': '3'
    }

    stmt = db.select(Record)
    filters = []
    general_keywords = []

    # 读取职业信息
    jobs, job_attr_map = read_job_info(DATA_DIR, 'job.txt')
    attr_names = {0: '防护职业', 1: '治疗职业', 2: '输出职业'}
    attr_jobs = {
        name: [job for job, attr in job_attr_map.items() if attr_names[attr] == name]
        for name in attr_names.values()
    }

    # 读取副本和大区信息
    dungeons = read_dungeon_info(DATA_DIR, 'dungeon.txt')
    servers = read_server_info(DATA_DIR, 'server.txt')

    # 颜色映射
    attr_colors = {
        0: "#2f3e75",  # 防护职业（深蓝）
        1: "#364b29",  # 治疗职业（深绿）
        2: "#4e3231"   # 输出职业（深红）
    }
    job_colors = {job: attr_colors.get(job_attr_map.get(job, 0), "#6c757d") for job in jobs}

    # 主随
    special_dungeons = ['神兵要塞帝国南方堡', '最终决战天幕魔导城', '究极神兵破坏作战']

    invalid_query = False
    # 分离字段搜索与普通关键字
    for kw in keywords:
        matched = False
        for prefix, column in field_patterns.items():
            if kw.startswith(f"{prefix}:"):
                value = kw[len(prefix)+1:].strip()
                if not value:
                    continue
                # 时间需特殊处理
                if column == 'time':
                    if re.match(r'^\d{4}-\d{2}-\d{2}$', value):
                        try:
                            dt = datetime.strptime(value, "%Y-%m-%d")
                            next_day = dt.replace(hour=0, minute=0, second=0) + timedelta(days=1)
                            filters.append(and_(Record.time >= dt, Record.time < next_day))
                        except ValueError:
                            invalid_query = True
                    elif re.match(r'^\d{1,2}$', value):
                        hour = int(value)
                        filters.append(db.extract('hour', Record.time) == hour)
                    else:
                        invalid_query = True
                # 职能需特殊处理
                elif column == 'attr':
                    matched_jobs = attr_jobs.get(value, [])
                    if matched_jobs:
                        filters.append(Record.job.in_(matched_jobs))
                    else:
                        invalid_query = True
                # 副本类型需特殊处理
                elif column == 'dungeon_type':
                    type_code = dungeon_type_map.get(value)
                    if type_code is not None:
                        filters.append(Record.dungeon_type == type_code)
                    else:
                        invalid_query = True
                # 为了数据统计页面-主随占比-其他副本而设立的逻辑
                elif column == 'dungeon' and value == '其他副本':
                     print(1)
                     filters.append(~Record.dungeon.in_(special_dungeons))
                # 其它直接搜索对应字段即可
                else:
                    filters.append(getattr(Record, column) == value)

                matched = True
                break

        if not matched:
            general_keywords.append(kw)
    
    if invalid_query is True:
        stmt = db.select(Record).where(False)

    for keyword in general_keywords:
        keyword = keyword.strip()
        if keyword:
            filters.append(or_(
            Record.job.ilike(f'%{keyword}%'),
            Record.server.ilike(f'%{keyword}%'),
            Record.dungeon.ilike(f'%{keyword}%'),
            Record.dungeon_level.ilike(f'%{keyword}%'),
            Record.note.ilike(f'%{keyword}%'),
        ))
        
    if filters:
        stmt = stmt.where(and_(*filters))

    # 查询记录
    stmt = stmt.order_by(Record.time.desc() if order == 'desc' else Record.time.asc())

    records = db.paginate(stmt, page=page, per_page=per_page, error_out=False)

    return render_template('record.html',
                           records=records,
                           jobs=jobs,
                           dungeons=dungeons,
                           servers=servers,
                           job_colors=job_colors,
                           query=q_raw,
                           active_page='record')


@app.route('/add', methods=['POST'])
def add_record():
    job = request.form['job']
    time_str = request.form['time']
    server = request.form['server']
    dungeon = request.form['dungeon']
    note = request.form['note']

    # 在 dungeon.txt 中查找副本等级和类型
    dungeon_info = read_dungeon_info(DATA_DIR, 'dungeon.txt')
    dungeon_level = dungeon_type = ''
    for dungeon_entry in dungeon_info:
        if dungeon_entry[0] == dungeon:
            dungeon_level = dungeon_entry[1]
            dungeon_type = dungeon_entry[2]
            break

    time = datetime.strptime(time_str, '%Y-%m-%dT%H:%M') if time_str else datetime.now()
    record = Record(job=job, time=time, server=server, dungeon=dungeon, dungeon_level=dungeon_level, dungeon_type=dungeon_type, note=note)
    db.session.add(record)
    db.session.commit()
    return redirect(url_for('record'))


@app.route('/update/<int:record_id>', methods=['POST'])
def update_record(record_id):
    record = Record.query.get_or_404(record_id)
    record.job = request.form['job']
    record.time = datetime.strptime(request.form['time'], '%Y-%m-%dT%H:%M')
    record.server = request.form['server']
    record.dungeon = request.form['dungeon']
    record.note = request.form['note']

    # 更新副本等级和类型
    dungeon_info = read_dungeon_info(DATA_DIR, 'dungeon.txt')
    for dungeon_entry in dungeon_info:
        if dungeon_entry[0] == record.dungeon:
            record.dungeon_level = dungeon_entry[1]
            record.dungeon_type = dungeon_entry[2]
            break
    db.session.commit()

    page = request.form.get('page', 1)
    per_page = request.form.get('per_page', 10)
    order = request.form.get('order', 'desc')

    return redirect(url_for('record', page=page, per_page=per_page, order=order))


@app.route('/delete', methods=['POST'])
def delete_records():
    ids = request.form.getlist('record_ids')
    for record_id in ids:
        record = Record.query.get(int(record_id))
        db.session.delete(record)
    db.session.commit()

    page = request.form.get('page', 1)
    per_page = request.form.get('per_page', 10)
    order = request.form.get('order', 'desc')

    return redirect(url_for('record', page=page, per_page=per_page, order=order))


def import_excel_func(file, default_server):
    if not file or not file.filename.endswith('.xlsx'):
        msg = '请上传导入文件！'
        return msg

    try:
        df = pd.read_excel(file)
    except Exception as e:
        msg = f'在读取文件时失败：{e}'
        return msg

    required_cols = ['副本', '职业', '时间']
    if not all(col in df.columns for col in required_cols):
        msg = '缺少必要列！请确认文件至少包含以下列：「副本」、「职业」、「时间」。'
        return msg
    
    # 填补大区、备注列
    if '大区' not in df.columns:
        df['大区'] = default_server
    if '备注' not in df.columns:
        df['备注'] = ''

    # 读取职业、副本、大区信息
    jobs, _ = read_job_info(DATA_DIR, 'job.txt')
    dungeons = read_dungeon_info(DATA_DIR, 'dungeon.txt')
    servers = read_server_info(DATA_DIR, 'server.txt')
    dungeon_map = {d[0]: (d[1], d[2]) for d in dungeons}

    count = 0
    for _, row in df.iterrows():
        try:
            dungeon = str(row['副本']).strip()
            job = str(row['职业']).strip()
            server = str(row['大区']).strip()
            note = str(row['备注']).strip()
            time_raw = row['时间']

            # 处理时间字段
            if isinstance(time_raw, str):
                try:
                    # 若只有年月日
                    time = datetime.strptime(time_raw.strip(), '%Y-%m-%d')
                    time = time.replace(hour=0, minute=0, second=0)
                except:
                    time = datetime.strptime(time_raw.strip(), '%Y-%m-%d %H:%M:%S')
            elif isinstance(time_raw, datetime):
                time = time_raw
            else:
                time = pd.to_datetime(time_raw)
                if time.hour == 0 and time.minute == 0 and time.second == 0:
                    time = time.replace(hour=0, minute=0, second=0)

            # 查询副本等级和类型，确认副本存在
            info = dungeon_map.get(dungeon)
            if info is None:
                raise ValueError(f"不存在名为 {dungeon} 的副本！")
            dungeon_level, dungeon_type = info

            # 确认职业和服务器存在
            if job not in jobs:
                raise ValueError(f"不存在名为 {job} 的职业！")
            
            if server not in servers:
                raise ValueError(f"不存在名为 {server} 的大区！")

            record = Record(
                job=job,
                time=time,
                server=server,
                dungeon=dungeon,
                dungeon_level=dungeon_level,
                dungeon_type=dungeon_type,
                note=note
            )
            db.session.add(record)
            count += 1
        except Exception as e:
            msg = f'在导入第 {count + 1} 条记录时失败：{e}'
            db.session.rollback()
            return msg

    try:
        db.session.commit()
        msg = f'成功导入 {count} 条记录！'
    except Exception as e:
        db.session.rollback()
        msg = f'在提交数据库时失败：{e}'

    return msg

@app.route('/import_excel', methods=['POST'])
def import_excel():
    file = request.files.get('file')
    default_server = request.form.get('default_server', '陆行鸟')

    msg = import_excel_func(file, default_server)

    return render_template_string(f"""
    <script>
        alert("{msg}");
        window.location.href = "{url_for('record')}";
    </script>
    """)


@app.route('/export_excel')
def export_excel():
    records = Record.query.all()

    data = []
    for r in records:
        data.append({
            '副本': r.dungeon,
            '职业': r.job,
            '时间': r.time.strftime('%Y-%m-%d %H:%M:%S'),
            '大区': r.server,
            '备注': r.note or ''
        })

    df = pd.DataFrame(data)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)

    export_name = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

    return send_file(
        output,
        as_attachment=True,
        download_name=f'导随记录_{export_name}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


@app.route('/stats')
def stats():
    records = Record.query.all()

    has_records = len(records) > 0

    _, job_attr_map = read_job_info(DATA_DIR, 'job.txt')
    attr_names = {0: '防护职业', 1: '治疗职业', 2: '输出职业'}

    # 1. 职能分布
    attr_counter = Counter()
    for r in records:
        attr = job_attr_map.get(r.job, 2)
        attr_counter[attr_names[attr]] += 1

    # 2. 职业分布
    job_counter = Counter(r.job for r in records)

    # 3. 大区分布
    server_counter = Counter(r.server for r in records)

    # 4. 副本类型分布
    dungeon_type_counter = Counter(r.dungeon_type for r in records)

    # 5. 主随统计
    special_dungeons = ['神兵要塞帝国南方堡', '最终决战天幕魔导城', '究极神兵破坏作战']
    special_total = Counter()
    special_by_attr = {name: Counter() for name in attr_names.values()}
    attr_all_records = {name: [] for name in attr_names.values()}

    for r in records:
        attr = job_attr_map.get(r.job, 2)
        attr_name = attr_names[attr]
        attr_all_records[attr_name].append(r)
        if r.dungeon in special_dungeons:
            special_total[r.dungeon] += 1
            special_by_attr[attr_name][r.dungeon] += 1

    total_count = len(records)
    special_dungeon_ratio = {
        '所有': {
            k: v for k, v in {
                '神兵要塞帝国南方堡': special_total['神兵要塞帝国南方堡'],
                '最终决战天幕魔导城': special_total['最终决战天幕魔导城'],
                '究极神兵破坏作战': special_total['究极神兵破坏作战'],
                '其他副本': total_count - sum(special_total.values())
            }.items() if v > 0
        }
    }
    for attr, recs in attr_all_records.items():
        counter = Counter()
        for r in recs:
            if r.dungeon in special_dungeons:
                counter[r.dungeon] += 1
        total = len(recs)
        special_dungeon_ratio[attr] = {
            k: v for k, v in {
                '神兵要塞帝国南方堡': counter['神兵要塞帝国南方堡'],
                '最终决战天幕魔导城': counter['最终决战天幕魔导城'],
                '究极神兵破坏作战': counter['究极神兵破坏作战'],
                '其他副本': total - sum(counter.values())
            }.items() if v > 0
        }

    # 6. 最近一周 & 一月每日次数
    now = datetime.now()
    day_counts_week = Counter()
    day_counts_month = Counter()
    for r in records:
        days_ago = (now.date() - r.time.date()).days
        if days_ago < 7:
            day_counts_week[str(r.time.date())] += 1
        if days_ago < 30:
            day_counts_month[str(r.time.date())] += 1

    for i in range(7):
        day = (now - timedelta(days=i)).date().isoformat()
        if day not in day_counts_week:
            day_counts_week[day] = 0

    for i in range(30):
        day = (now - timedelta(days=i)).date().isoformat()
        if day not in day_counts_month:
            day_counts_month[day] = 0

    # 7. 每小时段出现次数
    hour_bucket = Counter()
    for r in records:
        hour = r.time.hour
        hour_bucket[hour] += 1

    for h in range(24):
        if h not in hour_bucket:
            hour_bucket[h] = 0

    return render_template('stats.html',
                           has_records=has_records,
                           attr_data=dict(attr_counter),
                           job_data=dict(job_counter),
                           server_data=dict(server_counter),
                           dungeon_type_data=dict(dungeon_type_counter),
                           special_dungeon_ratio=special_dungeon_ratio,
                           week_data=dict(sorted(day_counts_week.items())),
                           month_data=dict(sorted(day_counts_month.items())),
                           hours_data=dict(sorted(hour_bucket.items())),
                           active_page='stats')


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    error = {}
    success = request.args.get('success') == '1'

    if request.method == 'POST':
        username = request.form['username'].strip()
        target_count_raw = request.form['target_count'].strip()

        if not username:
            error['username'] = '用户名不能为空！'

        try:
            target_count = int(target_count_raw)
            if target_count <= 0:
                error['target_count'] = '期望导随次数必须是正整数！'
        except ValueError:
            error['target_count'] = '请输入一个有效的正整数！'

        if not error:
            settings_data = {
                'username': username,
                'target_count': target_count
            }
            save_settings(SETTINGS_PATH, settings_data)
            return redirect(url_for('settings', success=1))

        settings_data = {
            'username': username,
            'target_count': target_count_raw
        }
        return render_template('settings.html', settings=settings_data, error=error, success=False, active_page='settings')

    settings_data = load_settings(SETTINGS_PATH)
    return render_template('settings.html', settings=settings_data, error=None, success=success, active_page='settings')


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
