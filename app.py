from flask import Flask, render_template, request, redirect, url_for, session, make_response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import csv, io, os, sys
import datetime

app = Flask(__name__)

app.config['SECRET_KEY'] = os.environ.get(
    'SECRET_KEY',
    'dev-only-CHANGE-ME'
)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///data.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)   # <-- теперь есть!

# ----- МОДЕЛИ -----
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

# ----- ВСПОМОГАТЕЛЬНЫЕ -----
def current_year():
    return datetime.date.today().year

def create_demo_data():
    db.drop_all()
    db.create_all()
    # subjects
    s1 = Subject(name='Русский')
    s2 = Subject(name='Математика')
    s3 = Subject(name='Физика')
    db.session.add_all([s1,s2,s3])
    db.session.commit()

    # users: admin, teacher, student
    admin = User(username='admin', password_hash=generate_password_hash('admin123'), role='admin', fullname='Администратор Школы')
    teacher = User(username='teacher', password_hash=generate_password_hash('teach123'), role='teacher', fullname='Иван Иванов (Учитель)')
    student = User(username='student', password_hash=generate_password_hash('stud123'), role='student', fullname='Пётр Петров (Ученик)')
    db.session.add_all([admin, teacher, student])
    db.session.commit()

    # sample grades (student has a few grades)
    g1 = Grade(student_id=student.id, subject_id=s1.id, value=4, year=current_year(), quarter=1)
    g2 = Grade(student_id=student.id, subject_id=s2.id, value=5, year=current_year(), quarter=1)
    g3 = Grade(student_id=student.id, subject_id=s3.id, value=3, year=current_year(), quarter=2)
    db.session.add_all([g1,g2,g3])
    db.session.commit()
    print("Demo data created. Users: admin/admin123, teacher/teach123, student/stud123")

# ----- МАРШРУТЫ -----
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

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    role = session.get('role')
    if role == 'student':
        return redirect(url_for('student_page'))
    elif role == 'teacher':
        return redirect(url_for('teacher_page'))
    elif role == 'admin':
        return redirect(url_for('admin_page'))
    else:
        return "Unknown role", 403

# ---------- УЧЕНИК ----------
@app.route('/student')
def student_page():
    if 'user_id' not in session or session.get('role') != 'student':
        return redirect(url_for('login'))
    student_id = session['user_id']
    year = int(request.args.get('year', current_year()))
    quarter = int(request.args.get('quarter', 0))      # 0 = все
    subject_id = int(request.args.get('subject', 0))   # 0 = все

    subjects = Subject.query.all()
    # Словарь id -> название предмета (чтобы не дёргать БД из шаблона)
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
        subject_map=subject_map,   # <-- добавили
        grades=grades,
        avg=avg,
        year=year,
        quarter=quarter,
        subject_id=subject_id
    )


# ---------- УЧИТЕЛЬ ----------
@app.route('/teacher', methods=['GET','POST'])
def teacher_page():
    if 'user_id' not in session or session.get('role') != 'teacher':
        return redirect(url_for('login'))
    subjects = Subject.query.all()
    students = User.query.filter_by(role='student').all()
    message = ''
    if request.method == 'POST':
        # params: subject, year, quarter, then grades as student_<id>
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

# ---------- ЭКСПОРТ (CSV, открывается в Excel) ----------
@app.route('/export/class')
def export_class():
    if 'user_id' not in session or session.get('role') not in ['teacher','admin']:
        return redirect(url_for('login'))
    subject_id = int(request.args.get('subject', 0))
    year = int(request.args.get('year', current_year()))
    quarter = int(request.args.get('quarter', 0))
    subject = Subject.query.get(subject_id)
    students = User.query.filter_by(role='student').all()
    # build CSV in memory
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['ФИО ученика','Предмет', 'Оценки (список)','Средний балл'])
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

# ---------- АДМИН: управление пользователями ----------
@app.route('/admin', methods=['GET','POST'])
def admin_page():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    message = ''
    if request.method == 'POST':
        # add user
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

# ----- CLI: initdb -----
if __name__ == '__main__':
    if 'initdb' in sys.argv:
        with app.app_context():
            create_demo_data()
    else:
        app.run(host='0.0.0.0', port=5000)
