from flask import Flask, render_template, request, redirect, url_for, session, make_response, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import csv, io, os, datetime

app = Flask(__name__)

# --- Конфигурация ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-only-CHANGE-ME')  # поменяй в продакшене!
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
    week = db.Column(db.Integer, nullable=True)  # Добавлено для учителя

    __table_args__ = (
        db.UniqueConstraint('student_id', 'subject_id', 'year', 'quarter', 'week', name='unique_grade'),
    )

# =========================
#     ВСПОМОГАТЕЛЬНЫЕ
# =========================
def current_year:
    return datetime.date.today().year

def create_demo_data():
    try:
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
            User(username='student', password_hash=generate_password_hash('stud123'),
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
                    if val < 2 or val > 5:
                        val = 3  # Валидация
                    g = Grade(student_id=st.id, subject_id=subj.id, value=val,
                              year=current_year, quarter=q, week=1)
                    db.session.add(g)

        db.session.commit()
        print("Demo data created successfully. Users: admin/admin123, teacher/teach123, student/stud123")
    except Exception as e:
        print(f"Error creating demo data: {str(e)}")
        db.session.rollback()

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
            print(f"Login successful: username={username}, role={user.role}")
            flash('Вход выполнен', 'success')
            return redirect(url_for('dashboard'))
        else:
            error = 'Неправильный логин или пароль'
            print(f"Login failed: username={username}")
            flash(error, 'danger')
    return render_template('login.html', error=error, current_year=current_year)

@app.route('/logout')
def logout():
    session.clear()
    flash('Выход выполнен', 'info')
    return redirect(url_for('login'))

# =========================
#        ГЛАВНАЯ
# =========================
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash('Требуется вход', 'danger')
        return redirect(url_for('login'))

    role = session.get('role')
    print(f"Dashboard accessed: role={role}, user_id={session.get('user_id')}")
    if role == 'admin':
        print("Redirecting admin to /admin")
        return redirect(url_for('admin_page'))

    news = [
        {"title": "Запущена олимпиада", "desc": "Математика и русский язык.", "url": "https://edu.gov.ru/", "image": "https://picsum.photos/400/200?random=1"},
        {"title": "Обновления сайта", "desc": "Добавлены отчёты.", "url": "https://github.com/AlexandrMarivech/school-diary", "image": "https://picsum.photos/400/200?random=2"},
    ]
    return render_template("dashboard.html", role=role, news=news, current_year=current_year)

# =========================
#          УЧЕНИК
# =========================
@app.route('/student')
def student_page():
    if 'user_id' not in session or session.get('role') != 'student':
        flash('Доступ только для студентов', 'danger')
        return redirect(url_for('login'))
    student_id = session['user_id']
    year = int(request.args.get('year', current_year))
    quarter = int(request.args.get('quarter', 0))
    subject_id = int(request.args.get('subject', 0))

    if not os.path.exists('data.db'):
        flash('База данных не найдена. Обратитесь к администратору', 'danger')
        print("Error: data.db not found")
        return redirect(url_for('dashboard'))

    subjects = Subject.query.all()
    if not subjects:
        flash('Нет предметов в базе. Обратитесь к администратору', 'danger')
        print("Error: No subjects found")
        return redirect(url_for('dashboard'))

    subject_map = {s.id: s.name for s in subjects}
    q = Grade.query.filter_by(student_id=student_id, year=year)
    if quarter != 0:
        q = q.filter_by(quarter=quarter)
    if subject_id != 0:
        q = q.filter_by(subject_id=subject_id)
    grades = q.all()

    avg = {}
    for g in grades:
        subjname = subject_map.get(g.subject_id, 'Неизвестный')
        avg.setdefault(subjname, []).append(g.value)
    avg = {k: round(sum(v)/len(v), 2) if v else 0 for k, v in avg.items()}

    return render_template('student.html', grades=grades, avg=avg, year=year,
                          quarter=quarter, subject_id=subject_id, subjects=subjects,
                          subject_map=subject_map, current_year=current_year)

@app.route('/student/report')
def student_report():
    if 'user_id' not in session or session.get('role') != 'student':
        flash('Доступ только для студентов', 'danger')
        return redirect(url_for('login'))

    student_id = session['user_id']
    year = int(request.args.get('year', current_year))

    if not os.path.exists('data.db'):
        flash('База данных не найдена. Обратитесь к администратору', 'danger')
        print("Error: data.db not found")
        return redirect(url_for('dashboard'))

    subjects = Subject.query.all()
    if not subjects:
        flash('Нет предметов в базе. Обратитесь к администратору', 'danger')
        print("Error: No subjects found")
        return redirect(url_for('dashboard'))

    subject_map = {s.id: s.name for s in subjects}
    grades = Grade.query.filter_by(student_id=student_id, year=year).all()

    subj_avgs = {}
    for g in grades:
        subjname = subject_map.get(g.subject_id, 'Неизвестный')
        subj_avgs.setdefault(subjname, []).append(g.value)
    subj_avgs = {k: round(sum(v)/len(v), 2) if v else 0 for k, v in subj_avgs.items()}
    overall = round(sum([g.value for g in grades])/len(grades), 2) if grades else 0

    return render_template('student_report.html', year=year,
                           subject_avgs=subj_avgs, overall_avg=overall, current_year=current_year)

# =========================
#           УЧИТЕЛЬ
# =========================
@app.route('/teacher', methods=['GET', 'POST'])
def teacher_page():
    if 'user_id' not in session or session.get('role') != 'teacher':
        flash('Доступ только для учителей', 'danger')
        return redirect(url_for('login'))

    if not os.path.exists('data.db'):
        flash('База данных не найдена. Обратитесь к администратору', 'danger')
        print("Error: data.db not found")
        return redirect(url_for('dashboard'))

    students = User.query.filter_by(role='student').all()
    subjects = Subject.query.all()
    if not subjects or not students:
        flash('Нет студентов или предметов в базе. Обратитесь к администратору', 'danger')
        print(f"Error: students={len(students)}, subjects={len(subjects)}")
        return redirect(url_for('dashboard'))

    message = ''
    if request.method == 'POST':
        subject_id = int(request.form.get('subject_id', 0))
        year = int(request.form.get('year', current_year))
        quarter = int(request.form.get('quarter', 0))
        week = int(request.form.get('week', 0))
        if quarter not in [1, 2, 3, 4] or week < 0 or week > 52 or not subject_id:
            flash('Неверные данные: проверьте четверть, неделю и предмет', 'danger')
            print(f"Invalid input: subject_id={subject_id}, quarter={quarter}, week={week}")
            return redirect(url_for('teacher_page'))

        for student in students:
            grade_value = request.form.get(f'grade_{student.id}')
            if grade_value:
                try:
                    value = int(grade_value)
                    if value < 2 or value > 5:
                        flash(f'Оценка для {student.fullname or student.username} должна быть от 2 до 5', 'danger')
                        continue
                    existing_grade = Grade.query.filter_by(
                        student_id=student.id, subject_id=subject_id, year=year, quarter=quarter, week=week
                    ).first()
                    if existing_grade:
                        existing_grade.value = value
                    else:
                        new_grade = Grade(student_id=student.id, subject_id=subject_id, value=value,
                                        year=year, quarter=quarter, week=week)
                        db.session.add(new_grade)
                except ValueError:
                    flash(f'Неверная оценка для {student.fullname or student.username}', 'danger')
                    continue
        db.session.commit()
        flash('Оценки сохранены', 'success')
        print(f"Grades saved: subject_id={subject_id}, year={year}, quarter={quarter}, week={week}")

    return render_template('teacher.html', students=students, subjects=subjects, message=message, current_year=current_year)

@app.route('/teacher/report')
def teacher_report():
    if 'user_id' not in session or session.get('role') != 'teacher':
        flash('Доступ только для учителей', 'danger')
        return redirect(url_for('login'))

    year = int(request.args.get('year', current_year))
    subject_id = int(request.args.get('subject', 0))
    period = request.args.get('period', 'year')

    if not os.path.exists('data.db'):
        flash('База данных не найдена. Обратитесь к администратору', 'danger')
        print("Error: data.db not found")
        return redirect(url_for('dashboard'))

    students = User.query.filter_by(role='student').all()
    subjects = Subject.query.all()
    if not subjects or not students:
        flash('Нет студентов или предметов в базе. Обратитесь к администратору', 'danger')
        print(f"Error: students={len(students)}, subjects={len(subjects)}")
        return redirect(url_for('dashboard'))

    subject_map = {s.id: s.name for s in subjects}
    report_data = []
    for st in students:
        q = Grade.query.filter_by(student_id=st.id, year=year)
        if subject_id != 0:
            q = q.filter_by(subject_id=subject_id)
        if period == 'q1':
            q = q.filter(Grade.quarter.in_([1, 2]))
        elif period == 'q2':
            q = q.filter(Grade.quarter.in_([3, 4]))
        elif period in ['1', '2', '3', '4']:
            q = q.filter_by(quarter=int(period))
        grades = [g.value for g in q.all()]
        avg = round(sum(grades)/len(grades), 2) if grades else 0
        report_data.append((st.fullname or st.username, grades, avg))

    return render_template('teacher_report.html', report_data=report_data, year=year,
                          subjects=subjects, period=period, subject_id=subject_id, current_year=current_year)

# =========================
#           АДМИН
# =========================
@app.route('/admin', methods=['GET','POST'])
def admin_page():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ только для админов', 'danger')
        return redirect(url_for('login'))
    message = ''
    if request.method == 'POST':
        username = request.form['username'].strip()
        fullname = request.form.get('fullname','').strip()
        password = request.form['password'].strip()
        role = request.form['role']
        if username and password and len(password) > 4 and role in ['student','teacher','admin']:
            if User.query.filter_by(username=username).first():
                message = 'Пользователь с таким логином уже существует'
                flash(message, 'danger')
            else:
                u = User(username=username, password_hash=generate_password_hash(password), role=role, fullname=fullname)
                db.session.add(u)
                db.session.commit()
                message = 'Пользователь создан'
                flash(message, 'success')
        else:
            message = 'Неверные данные (пароль >4 символов, роль корректна)'
            flash(message, 'danger')
    users = User.query.all()
    print(f"Admin page accessed: users found={len(users)}")
    return render_template('admin.html', users=users, message=message, current_year=current_year)

@app.route('/admin/reports')
def admin_reports():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ только для админов', 'danger')
        return redirect(url_for('login'))

    try:
        year = int(request.args.get('year', current_year))
        if year < 2000 or year > current_year + 1:
            year = current_year
            flash('Год исправлен на текущий', 'info')

        if not os.path.exists('data.db'):
            flash('База данных не найдена. Запустите python app.py initdb', 'danger')
            print("Error: data.db not found")
            return redirect(url_for('admin_page'))

        students = User.query.filter_by(role='student').all()
        subjects = Subject.query.all()
        print(f"Reports accessed: year={year}, students={len(students)}, subjects={len(subjects)}")

        if not subjects:
            flash('Нет предметов в базе. Запустите python app.py initdb', 'danger')
            print("Error: No subjects found")
            return redirect(url_for('admin_page'))
        if not students:
            flash('Нет студентов в базе. Добавьте пользователей', 'danger')
            print("Error: No students found")
            return redirect(url_for('admin_page'))

        subject_map = {s.id: s.name for s in subjects}
        report_data = []
        for st in students:
            q = Grade.query.filter_by(student_id=st.id, year=year).all()
            subj_avgs = {}
            for g in q:
                subjname = subject_map.get(g.subject_id, 'Неизвестный')
                subj_avgs.setdefault(subjname, []).append(g.value)
            subj_avgs = {k: round(sum(v)/len(v), 2) if len(v) > 0 else 0 for k, v in subj_avgs.items()}
            overall_avg = round(sum([g.value for g in q])/len(q), 2) if len(q) > 0 else 0
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
            subjects=subjects,
            current_year=current_year
        )
    except ZeroDivisionError:
        print("ZeroDivisionError: No grades for selected year")
        flash('Ошибка: нет оценок для выбранного года', 'danger')
        return redirect(url_for('admin_page'))
    except Exception as e:
        print(f"Reports error: {str(e)}")
        flash(f'Ошибка отчёта: {str(e)}', 'danger')
        return redirect(url_for('admin_page'))

@app.route('/admin/edit/<int:user_id>', methods=['GET', 'POST'])
def edit_user(user_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ только для админов', 'danger')
        return redirect(url_for('login'))

    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        try:
            username = request.form['username'].strip()
            fullname = request.form.get('fullname', '').strip()
            role = request.form['role']
            password = request.form.get('password', '').strip()

            if username != user.username:
                existing = User.query.filter(User.username == username, User.id != user.id).first()
                if existing:
                    flash('Логин уже существует', 'danger')
                    return redirect(url_for('admin_page'))

            if password and len(password) <= 4:
                flash('Пароль слишком короткий (>4 символов)', 'danger')
                return redirect(url_for('admin_page'))

            user.username = username
            user.fullname = fullname
            user.role = role
            if password:
                user.password_hash = generate_password_hash(password)

            db.session.commit()
            flash('Пользователь обновлён', 'success')
        except Exception as e:
            print(f"Edit user error: {str(e)}")
            flash(f'Ошибка редактирования: {str(e)}', 'danger')
        return redirect(url_for('admin_page'))

    return render_template('edit_user.html', user=user, current_year=current_year)

@app.route('/admin/delete/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ только для админов', 'danger')
        return redirect(url_for('login'))

    try:
        user = User.query.get_or_404(user_id)
        if user.role == 'admin':
            flash('Нельзя удалить админа', 'danger')
            return redirect(url_for('admin_page'))

        db.session.delete(user)
        db.session.commit()
        flash('Пользователь удалён', 'success')
    except Exception as e:
        print(f"Delete user error: {str(e)}")
        flash(f'Ошибка удаления: {str(e)}', 'danger')
    return redirect(url_for('admin_page'))

@app.route('/admin/test_dashboard')
def test_dashboard():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ только для админов', 'danger')
        return redirect(url_for('login'))
    message = f'Тестовый дашборд работает! Роль: {session.get("role")}, Пользователь: {session.get("username")}'
    print("Test dashboard accessed")
    return render_template('test_dashboard.html', message=message, current_year=current_year)

@app.route('/export/class')
def export_class():
    if 'user_id' not in session or session.get('role') not in ['teacher','admin']:
        flash('Доступ только для учителей/админов', 'danger')
        return redirect(url_for('login'))
    try:
        subject_id = int(request.args.get('subject', 0))
        year = int(request.args.get('year', current_year))
        quarter = int(request.args.get('quarter', 0))
        subject = Subject.query.get(subject_id) if subject_id else None
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
            avg = round(sum(grades)/len(grades),2) if len(grades) > 0 else ''
            subjname = subject.name if subject else 'Все'
            cw.writerow([st.fullname or st.username, subjname, ";".join(map(str,grades)), avg])

        output = make_response(si.getvalue())
        output.headers["Content-Disposition"] = f"attachment; filename=class_report_{year}_q{quarter}.csv"
        output.headers["Content-type"] = "text/csv; charset=utf-8"
        return output
    except Exception as e:
        print(f"Export error: {str(e)}")
        flash(f'Ошибка экспорта: {str(e)}', 'danger')
        return redirect(url_for('teacher_report' if session.get('role') == 'teacher' else 'admin_reports'))

# =========================
# CLI
# =========================
if __name__ == '__main__':
    import sys
    if 'initdb' in sys.argv:
        with app.app_context():
            create_demo_data()
    else:
        app.run(host='0.0.0.0', port=5000, debug=True)