from flask import Flask, render_template, request, redirect, url_for, session, make_response, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import csv, io, os, datetime

app = Flask(__name__)

# --- Конфигурация ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-only-CHANGE-ME')  # замени в проде!
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

    __table_args__ = (
        db.UniqueConstraint('student_id', 'subject_id', 'year', 'quarter', name='unique_grade'),
    )

# =========================
#     ВСПОМОГАТЕЛЬНЫЕ
# =========================
def current_year():
    return datetime.date.today().year

@app.context_processor
def inject_helpers():
    return {"current_year": current_year}

def create_demo_data():
    db.drop_all()
    db.create_all()

    # предметы
    s1 = Subject(name='Русский')
    s2 = Subject(name='Математика')
    s3 = Subject(name='Физика')
    db.session.add_all([s1, s2, s3])
    db.session.commit()

    # пользователи
    admin = User(username='admin', password_hash=generate_password_hash('admin123'),
                 role='admin', fullname='Администратор Школы')
    teacher = User(username='teacher', password_hash=generate_password_hash('teach123'),
                   role='teacher', fullname='Иван Иванов (Учитель)')
    students = [
        User(username='student',  password_hash=generate_password_hash('stud123'),
             role='student', fullname='Пётр Петров (Отличник)'),
        User(username='student2', password_hash=generate_password_hash('stud123'),
             role='student', fullname='Анна Смирнова (Хорошистка)'),
    ]

    db.session.add_all([admin, teacher] + students)
    db.session.commit()

    # шаблонные оценки
    patterns = {
        'Отличник': [5, 5, 5, 5],
        'Хорошистка': [4, 5, 4, 5],
    }

    for st in students:
        label = (st.fullname or "").split("(")[-1].replace(")", "").strip()
        base_pattern = patterns.get(label, [3, 4, 4, 5])

        for subj in [s1, s2, s3]:
            for q, val in enumerate(base_pattern, start=1):
                if not (2 <= val <= 5):
                    val = 3
                g = Grade(student_id=st.id, subject_id=subj.id, value=val,
                          year=current_year(), quarter=q)
                db.session.add(g)

    db.session.commit()
    print("Demo data created. Users: admin/admin123, teacher/teach123, student/stud123")

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
        password = request.form['password'].strip()
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
    if role == 'admin':
        return redirect(url_for('admin_page'))

    news = [
        {"title": "Запущена олимпиада", "desc": "Математика и русский язык.", "url": "https://edu.gov.ru/", "image": "https://picsum.photos/400/200?random=1"},
        {"title": "Обновления сайта", "desc": "Добавлены отчёты.", "url": "https://github.com/AlexandrMarivech/school-diary", "image": "https://picsum.photos/400/200?random=2"},
        {"title": "Новости науки", "desc": "Свежие открытия и исследования.", "url": "https://nplus1.ru/", "image": "https://picsum.photos/400/200?random=3"},
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

    subject_avgs = {}
    for g in grades:
        subjname = subject_map.get(g.subject_id, '')
        subject_avgs.setdefault(subjname, []).append(g.value)
    subject_avgs = {k: round(sum(v)/len(v), 2) for k, v in subject_avgs.items()}

    all_grades = [g.value for g in grades]
    overall_avg = round(sum(all_grades)/len(all_grades), 2) if all_grades else 0

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
                    if not (2 <= value <= 5):
                        flash(f'Оценка {value} для {student.fullname} должна быть в диапазоне 2..5')
                        continue
                    grade = Grade.query.filter_by(
                        student_id=student.id, subject_id=subject_id, year=year, quarter=quarter
                    ).first()
                    if grade:
                        grade.value = value
                    else:
                        db.session.add(Grade(
                            student_id=student.id, subject_id=subject_id, value=value, year=year, quarter=quarter
                        ))
                except ValueError:
                    flash(f'Неверный формат оценки для {student.fullname}')
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
    subject = Subject.query.get(subject_id) if subject_id != 0 else None
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
        password = request.form['password'].strip()
        role = request.form['role']
        if username and password and len(password) > 4 and role:
            if User.query.filter_by(username=username).first():
                message = 'Пользователь с таким логином уже существует'
            else:
                u = User(username=username, password_hash=generate_password_hash(password),
                         role=role, fullname=fullname)
                db.session.add(u)
                db.session.commit()
                message = 'Пользователь создан'
        else:
            message = 'Неверные данные (пароль должен быть > 4 символов)'
    users = User.query.all()
    return render_template('admin.html', users=users, message=message)

@app.route('/admin/reports')
def admin_reports():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))

    year = int(request.args.get('year', current_year()))
    if year < 2000 or year > current_year() + 1:
        year = current_year()
        flash('⚠️ Некорректный год — показан текущий', 'warning')

    students = User.query.filter_by(role='student').all()
    subjects = Subject.query.all()
    subject_map = {s.id: s.name for s in subjects}

    report_data = []
    for st in students:
        gr = Grade.query.filter_by(student_id=st.id, year=year).all()
        subj_avgs = {}
        for g in gr:
            subjname = subject_map.get(g.subject_id, 'Неизвестный предмет')
            subj_avgs.setdefault(subjname, []).append(g.value)
        subj_avgs = {k: round(sum(v)/len(v), 2) for k, v in subj_avgs.items()} if subj_avgs else {}
        overall_avg = round(sum([g.value for g in gr])/len(gr), 2) if gr else 0
        report_data.append({
            "student": st.fullname or st.username,
            "subj_avgs": subj_avgs,
            "overall": overall_avg
        })

    return render_template(
        "admin_reports.html",
        year=year,
        report_data=report_data,
        total_students=len(students),
        subjects=subjects
    )

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
        flash('❌ Пользователь с таким логином уже существует', 'danger')
        return redirect(url_for('admin_page'))

    if password and len(password) <= 4:
        flash('❌ Пароль должен быть длиннее 4 символов', 'danger')
        return redirect(url_for('admin_page'))

    user.username = username
    user.fullname = fullname
    user.role = role
    if password:
        user.password_hash = generate_password_hash(password)

    db.session.commit()
    flash(f'✅ Пользователь {user.username} обновлён', 'success')
    return redirect(url_for('admin_page'))

@app.route('/admin/delete/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))

    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        flash('Нельзя удалить администратора', 'warning')
        return redirect(url_for('admin_page'))

    db.session.delete(user)
    db.session.commit()
    flash(f'🗑 Пользователь {user.username} удалён', 'info')
    return redirect(url_for('admin_page'))

# =========================
#         CLI
# =========================
if __name__ == '__main__':
    import sys
    if 'initdb' in sys.argv:
        with app.app_context():
            create_demo_data()
    else:
        app.run(host='0.0.0.0', port=5000, debug=True)
