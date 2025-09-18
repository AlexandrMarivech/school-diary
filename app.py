from flask import Flask, render_template, request, redirect, url_for, session, make_response, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import csv, io, os, sys
import datetime

app = Flask(__name__)

# --- Конфигурация ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-only-CHANGE-ME')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///data.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# =========================
#        МОДЕЛИ
# =========================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'student','teacher','admin'
    fullname = db.Column(db.String(120), nullable=True)

class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)

class Grade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=False)
    value = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    quarter = db.Column(db.Integer, nullable=False)

# =========================
#     ВСПОМОГАТЕЛЬНЫЕ
# =========================
def current_year():
    return datetime.date.today().year

def create_demo_data():
    db.drop_all()
    db.create_all()

    # --- предметы ---
    s1 = Subject(name='Русский')
    s2 = Subject(name='Математика')
    s3 = Subject(name='Физика')
    db.session.add_all([s1, s2, s3])
    db.session.commit()

    # --- пользователи ---
    admin = User(username='admin', password_hash=generate_password_hash('admin123'),
                 role='admin', fullname='Администратор Школы')
    teacher = User(username='teacher', password_hash=generate_password_hash('teach123'),
                   role='teacher', fullname='Иван Иванов (Учитель)')

    students = [
        User(username='student',  password_hash=generate_password_hash('stud123'),
             role='student', fullname='Пётр Петров (Отличник)'),
        User(username='student2', password_hash=generate_password_hash('stud123'),
             role='student', fullname='Анна Смирнова (Хорошистка)'),
        User(username='student3', password_hash=generate_password_hash('stud123'),
             role='student', fullname='Сергей Кузнецов (Троечник)'),
        User(username='student4', password_hash=generate_password_hash('stud123'),
             role='student', fullname='Мария Иванова (Середнячка)'),
        User(username='student5', password_hash=generate_password_hash('stud123'),
             role='student', fullname='Алексей Соколов (Смешанные оценки)'),
        User(username='student6', password_hash=generate_password_hash('stud123'),
             role='student', fullname='Екатерина Попова (Сильна в математике)'),
        User(username='student7', password_hash=generate_password_hash('stud123'),
             role='student', fullname='Дмитрий Волков (Слаб по физике)'),
        User(username='student8', password_hash=generate_password_hash('stud123'),
             role='student', fullname='Ольга Васильева (Хорошистка)'),
    ]

    db.session.add_all([admin, teacher] + students)
    db.session.commit()

    # --- шаблоны оценок для разных «типов» учеников ---
    patterns = {
        'Отличник': [5, 5, 5, 5],
        'Хорошистка': [4, 5, 4, 5],
        'Троечник': [3, 3, 3, 3],
        'Середнячка': [3, 4, 3, 4],
        'Смешанные оценки': [3, 4, 5, 4],
        'Сильна в математике': [3, 4, 5, 4],  # математика будет 5
        'Слаб по физике': [4, 4, 3, 3],       # физика будет 3
        'Ольга Васильева': [4, 5, 4, 5],
    }

    # --- добавляем оценки за 4 четверти по 3 предметам ---
    all_subjects = [s1, s2, s3]
    for st in students:
        label = (st.fullname or "").split("(")[-1].replace(")", "").strip()
        base_pattern = patterns.get(label, [3, 4, 4, 5])

        for subj in all_subjects:
            for q, val in enumerate(base_pattern, start=1):
                if "математике" in label and subj.name == "Математика":
                    val = 5
                if "физике" in label and subj.name == "Физика":
                    val = 3

                g = Grade(student_id=st.id, subject_id=subj.id, value=val,
                          year=current_year(), quarter=q)
                db.session.add(g)

    db.session.commit()
    print("Demo data created. Users: admin/admin123, teacher/teach123, student…student8/stud123")

# =========================
#       АВТОРИЗАЦИЯ
# =========================
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    error = ''
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['role'] = user.role
            session['username'] = user.username
            session['fullname'] = user.fullname
            return redirect(url_for('dashboard'))
        else:
            error = 'Неправильный логин или пароль'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# =========================
#        ГЛАВНАЯ
# =========================
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    role = session.get('role')

    # Админа сразу ведём в отчёты
    if role == 'admin':
        return redirect(url_for('admin_reports'))

    # Новости для студента/учителя
    news = [
        {
            "title": "Запущена новая школьная олимпиада",
            "desc": "Ученики могут принять участие в олимпиаде по математике и русскому языку.",
            "url": "https://edu.gov.ru/",
            "image": "https://picsum.photos/400/200?random=1"
        },
        {
            "title": "Обновления сайта",
            "desc": "Теперь доступен отчёт по ученику и отчёт по классу.",
            "url": "https://github.com/AlexandrMarivech/school-diary",
            "image": "https://picsum.photos/400/200?random=2"
        },
        {
            "title": "Новости науки",
            "desc": "Учёные создали новый материал, который может заменить пластик.",
            "url": "https://nplus1.ru/",
            "image": "https://picsum.photos/400/200?random=3"
        }
    ]
    return render_template("dashboard.html", role=role, news=news)

# =========================
#          УЧЕНИК
# =========================
@app.route('/student')
def student_page():
    if 'user_id' not in session or session.get('role') != 'student':
        return redirect(url_for('login'))
    student_id = session['user_id']
    year = int(request.args.get('year', current_year()))
    quarter = int(request.args.get('quarter', 0))      # 0 = все
    subject_id = int(request.args.get('subject', 0))   # 0 = все

    subjects = Subject.query.all()
    subject_map = {s.id: s.name for s in subjects}

    q = Grade.query.filter_by(student_id=student_id, year=year)
    if quarter != 0:
        q = q.filter_by(quarter=quarter)
    if subject_id != 0:
        q = q.filter_by(subject_id=subject_id)
    grades = q.all()

    # средние по предметам
    avg = {}
    for g in grades:
        subjname = subject_map.get(g.subject_id, '')
        avg.setdefault(subjname, []).append(g.value)
    avg = {k: round(sum(v)/len(v), 2) for k, v in avg.items()}

    return render_template(
        'student.html',
        subjects=subjects,
        subject_map=subject_map,
        grades=grades,
        avg=avg,
        year=year,
        quarter=quarter,
        subject_id=subject_id
    )

@app.route('/student/report')
def student_report():
    if 'user_id' not in session or session.get('role') != 'student':
        return redirect(url_for('login'))

    student_id = session['user_id']
    year = int(request.args.get('year', current_year()))

    subjects = Subject.query.all()
    subject_map = {s.id: s.name for s in subjects}

    q = Grade.query.filter_by(student_id=student_id, year=year)
    grades = q.all()

    # средние по предметам
    subject_avgs = {}
    for g in grades:
        subjname = subject_map.get(g.subject_id, '')
        subject_avgs.setdefault(subjname, []).append(g.value)
    subject_avgs = {k: round(sum(v)/len(v), 2) for k, v in subject_avgs.items()}

    # общий средний
    all_grades = [g.value for g in grades]
    overall_avg = round(sum(all_grades)/len(all_grades), 2) if all_grades else None

    return render_template(
        'student_report.html',
        year=year,
        subject_avgs=subject_avgs,
        overall_avg=overall_avg
    )

# =========================
#          УЧИТЕЛЬ
# =========================
@app.route('/teacher', methods=['GET','POST'])
def teacher_page():
    if 'user_id' not in session or session.get('role') != 'teacher':
        return redirect(url_for('login'))
    subjects = Subject.query.all()
    students = User.query.filter_by(role='student').all()
    message = ''
    if request.method == 'POST':
        subject_id = int(request.form['subject'])
        year = int(request.form['year'])
        quarter = int(request.form['quarter'])
        for student in students:
            key = f'student_{student.id}'
            if key in request.form and request.form[key].strip() != '':
                try:
                    value = int(request.form[key])
                    g = Grade(student_id=student.id, subject_id=subject_id, value=value, year=year, quarter=quarter)
                    db.session.add(g)
                except ValueError:
                    pass
        db.session.commit()
        message = 'Оценки сохранены.'
    return render_template('teacher.html', subjects=subjects, students=students, message=message, current_year=current_year())

@app.route('/export/class')
def export_class():
    if 'user_id' not in session or session.get('role') not in ['teacher','admin']:
        return redirect(url_for('login'))
    subject_id = int(request.args.get('subject', 0))
    year = int(request.args.get('year', current_year()))
    quarter = int(request.args.get('quarter', 0))
    subject = Subject.query.get(subject_id)
    students = User.query.filter_by(role='student').all()

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['ФИО ученика','Предмет','Оценки','Средний балл'])
    for st in students:
        q = Grade.query.filter_by(student_id=st.id, year=year)
        if quarter != 0:
            q = q.filter_by(quarter=quarter)
        if subject_id != 0:
            q = q.filter_by(subject_id=subject_id)
        grades = [g.value for g in q.all()]
        avg = round(sum(grades)/len(grades),2) if grades else ''
        subjname = subject.name if subject else 'Все'
        cw.writerow([st.fullname or st.username, subjname, ";".join(map(str,grades)), avg])

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=class_report_{year}_q{quarter}.csv"
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    return output

@app.route('/teacher/report')
def teacher_report():
    if 'user_id' not in session or session.get('role') != 'teacher':
        return redirect(url_for('login'))

    subject_id = int(request.args.get('subject', 0))
    year = int(request.args.get('year', current_year()))
    period = request.args.get('period', 'year')  # quarter1..4, halfyear1/2, year

    subjects = Subject.query.all()
    students = User.query.filter_by(role='student').all()

    # какие четверти входят
    if period.startswith('quarter'):
        quarters = [int(period[-1])]
    elif period == 'halfyear1':
        quarters = [1, 2]
    elif period == 'halfyear2':
        quarters = [3, 4]
    else:
        quarters = [1, 2, 3, 4]

    report_data = []
    for st in students:
        q = Grade.query.filter_by(student_id=st.id, year=year)
        if subject_id != 0:
            q = q.filter_by(subject_id=subject_id)
        q = q.filter(Grade.quarter.in_(quarters))
        grades = [g.value for g in q.all()]
        avg = round(sum(grades)/len(grades), 2) if grades else None
        report_data.append((st.fullname or st.username, grades, avg))

    return render_template(
        'teacher_report.html',
        subjects=subjects,
        subject_id=subject_id,
        year=year,
        period=period,
        report_data=report_data
    )

# =========================
#           АДМИН
# =========================
@app.route('/admin', methods=['GET','POST'])
def admin_page():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    message = ''
    if request.method == 'POST':
        username = request.form['username'].strip()
        fullname = request.form.get('fullname','').strip()
        password = request.form['password']
        role = request.form['role']
        if username and password and role:
            if User.query.filter_by(username=username).first():
                message = 'Пользователь с таким логином уже существует'
            else:
                u = User(username=username, password_hash=generate_password_hash(password), role=role, fullname=fullname)
                db.session.add(u)
                db.session.commit()
                message = 'Пользователь создан'
    users = User.query.all()
    return render_template('admin.html', users=users, message=message)

@app.route('/admin/delete/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))

    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        flash('Нельзя удалить администратора!')
        return redirect(url_for('admin_page'))

    db.session.delete(user)
    db.session.commit()
    flash(f'Пользователь {user.username} удалён')
    return redirect(url_for('admin_page'))

# ---- АДМИН: ОТЧЁТЫ ----
@app.route('/admin/reports', methods=['GET'])
def admin_reports():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))

    year = int(request.args.get('year', current_year()))
    students = User.query.filter_by(role='student').all()
    subjects = Subject.query.all()
    subject_map = {s.id: s.name for s in subjects}

    report_data = []
    for st in students:
        q = Grade.query.filter_by(student_id=st.id, year=year).all()
        subj_avgs = {}
        for g in q:
            subjname = subject_map.get(g.subject_id, '')
            subj_avgs.setdefault(subjname, []).append(g.value)
        subj_avgs = {k: round(sum(v)/len(v), 2) for k, v in subj_avgs.items()}
        overall_avg = round(sum([g.value for g in q])/len(q), 2) if q else None
        report_data.append({
            "student": st.fullname or st.username,
            "subj_avgs": subj_avgs,
            "overall": overall_avg
        })

    total_students = len(students)

    return render_template(
        "admin_reports.html",
        year=year,
        report_data=report_data,
        total_students=total_students
    )

# inline-редактирование пользователя
@app.route('/admin/edit/<int:user_id>', methods=['POST'])
def edit_user(user_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))

    user = User.query.get_or_404(user_id)
    username = request.form['username'].strip()
    fullname = request.form.get('fullname', '').strip()
    role = request.form['role']
    password = request.form.get('password', '').strip()

    existing = User.query.filter(User.username == username, User.id != user.id).first()
    if existing:
        users = User.query.all()
        return render_template('admin.html', users=users,
                               message='❌ Пользователь с таким логином уже существует')

    user.username = username
    user.fullname = fullname
    user.role = role
    if password:
        user.password_hash = generate_password_hash(password)

    db.session.commit()
    return redirect(url_for('admin_page'))

# =========================
#         CLI
# =========================
if __name__ == '__main__':
    if 'initdb' in sys.argv:
        with app.app_context():
            create_demo_data()
    else:
        app.run(host='0.0.0.0', port=5000)
