# app.py
from flask import Flask, render_template, request, redirect, url_for, session, make_response, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import csv, io, os, datetime
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.utils import get_column_letter

# ───────── Flask & DB config ─────────
app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-CHANGE-ME")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(INSTANCE_DIR, "data.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ───────── Models ─────────
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # student / teacher / admin
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
    week = db.Column(db.Integer, nullable=True)  # 1..10 (необязательное)

# ───────── Helpers ─────────
def current_year():
    return datetime.date.today().year

@app.context_processor
def inject_globals():
    # Позволяет вызывать {{ current_year() }} прямо в шаблонах
    return dict(current_year=current_year)


def create_demo_data():
    db.drop_all()
    db.create_all()

    # Subjects
    s1 = Subject(name="Русский")
    s2 = Subject(name="Математика")
    s3 = Subject(name="Физика")
    db.session.add_all([s1, s2, s3])
    db.session.commit()

    # Users
    admin = User(username="admin", password_hash=generate_password_hash("admin123"),
                 role="admin", fullname="Администратор Школы")
    teacher = User(username="teacher", password_hash=generate_password_hash("teach123"),
                   role="teacher", fullname="Иван Иванов (Учитель)")
    students = [
        User(username="student",  password_hash=generate_password_hash("stud123"),
             role="student", fullname="Пётр Петров (Отличник)"),
        User(username="student2", password_hash=generate_password_hash("stud123"),
             role="student", fullname="Анна Смирнова (Хорошистка)"),
    ]
    db.session.add_all([admin, teacher] + students)
    db.session.commit()

    # Seed grades (по четвертям, без недель)
    patterns = {
        "Отличник": [5, 5, 5, 5],
        "Хорошистка": [4, 5, 4, 5],
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
    print("Demo data created. Users: admin/admin123, teacher/teach123, student*/stud123")

# ───────── Auth ─────────
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session["user_id"] = user.id
            session["role"] = user.role
            session["username"] = user.username
            session["fullname"] = user.fullname
            flash("Вход выполнен", "success")
            return redirect(url_for("dashboard"))
        error = "Неправильный логин или пароль"
        flash(error, "danger")
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    flash("Выход выполнен", "info")
    return redirect(url_for("login"))

# ───────── Dashboard ─────────
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        flash("Требуется вход", "danger")
        return redirect(url_for("login"))

    role = session.get("role")
    # Админа на список пользователей — там есть кнопка в отчёты
    if role == "admin":
        return redirect(url_for("admin_page"))

    news = [
        {"title": "Запущена олимпиада", "desc": "Математика и русский язык.",
         "url": "https://edu.gov.ru/", "image": "https://picsum.photos/400/200?random=1"},
        {"title": "Обновления сайта", "desc": "Добавлены отчёты.",
         "url": "https://github.com/AlexandrMarivech/school-diary", "image": "https://picsum.photos/400/200?random=2"},
    ]
    return render_template("dashboard.html", role=role, news=news)

# ───────── Student ─────────
@app.route("/student")
def student_page():
    if "user_id" not in session or session.get("role") != "student":
        flash("Доступ только для студентов", "danger")
        return redirect(url_for("login"))

    student_id = session["user_id"]
    year = int(request.args.get("year", current_year()))

    subjects = Subject.query.all()
    subject_map = {s.id: s.name for s in subjects}

    grades = Grade.query.filter_by(student_id=student_id, year=year).all()

    avg = {}
    for g in grades:
        subjname = subject_map.get(g.subject_id, "")
        avg.setdefault(subjname, []).append(g.value)
    avg = {k: round(sum(v)/len(v), 2) if v else 0 for k, v in avg.items()}

    return render_template("student.html", grades=grades, avg=avg, year=year, subject_map=subject_map)

@app.route("/student/report")
def student_report():
    if "user_id" not in session or session.get("role") != "student":
        flash("Доступ только для студентов", "danger")
        return redirect(url_for("login"))

    student_id = session["user_id"]
    year = int(request.args.get("year", current_year()))

    subjects = Subject.query.all()
    subject_map = {s.id: s.name for s in subjects}

    grades = Grade.query.filter_by(student_id=student_id, year=year).all()

    subj_avgs = {}
    for g in grades:
        subjname = subject_map.get(g.subject_id, "")
        subj_avgs.setdefault(subjname, []).append(g.value)
    subj_avgs = {k: round(sum(v)/len(v), 2) if v else 0 for k, v in subj_avgs.items()}
    overall = round(sum([g.value for g in grades])/len(grades), 2) if grades else 0

    return render_template("student_report.html", year=year,
                           subject_avgs=subj_avgs, overall_avg=overall, subjects=subjects)

# ───────── Teacher ─────────
@app.route("/teacher", methods=["GET", "POST"])
def teacher_page():
    if "user_id" not in session or session.get("role") != "teacher":
        flash("Доступ только для учителей", "danger")
        return redirect(url_for("login"))

    subjects = Subject.query.all()
    students = User.query.filter_by(role="student").all()
    message = ""

    if request.method == "POST":
        subject_id = int(request.form["subject"])
        year = int(request.form["year"])
        quarter = int(request.form["quarter"])
        week = int(request.form.get("week", 1))

        for st in students:
            key = f"student_{st.id}"
            raw = request.form.get(key, "").strip()
            if not raw:
                continue
            try:
                value = int(raw)
            except ValueError:
                continue
            if value < 2 or value > 5:
                continue

            existing = Grade.query.filter_by(
                student_id=st.id, subject_id=subject_id,
                year=year, quarter=quarter, week=week
            ).first()
            if existing:
                existing.value = value
            else:
                db.session.add(Grade(
                    student_id=st.id, subject_id=subject_id, value=value,
                    year=year, quarter=quarter, week=week
                ))
        db.session.commit()
        message = "Оценки сохранены."

    # ⚡ исправлено: передаём функцию, а не число
    return render_template("teacher.html",
                           subjects=subjects, students=students,
                           message=message, current_year=current_year)


# ⚡ новый алиас для старых ссылок
@app.route("/export/class")
def export_class():
    # просто перенаправляем к export_teacher_xlsx
    return redirect(url_for("export_teacher_xlsx", **request.args))



@app.route("/teacher/report")
def teacher_report():
    if "user_id" not in session or session.get("role") != "teacher":
        flash("Доступ только для учителей", "danger")
        return redirect(url_for("login"))

    subject_id = int(request.args.get("subject", 0))
    year = int(request.args.get("year", current_year()))
    period = request.args.get("period", "year")  # quarter1..4, halfyear1/2, year

    subjects = Subject.query.all()
    students = User.query.filter_by(role="student").all()

    if period.startswith("quarter"):
        quarters = [int(period[-1])]
    elif period == "halfyear1":
        quarters = [1, 2]
    elif period == "halfyear2":
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
        avg = round(sum(grades)/len(grades), 2) if grades else 0
        report_data.append((st.fullname or st.username, grades, avg))

    return render_template("teacher_report.html",
                           subjects=subjects, subject_id=subject_id,
                           year=year, period=period, report_data=report_data)

# ───────── Excel exports ─────────
def autosize_columns(ws):
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                max_len = max(max_len, len(str(cell.value)) if cell.value else 0)
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = max(12, min(40, max_len + 2))

@app.route("/export/teacher_xlsx")
def export_teacher_xlsx():
    # Учитель/Админ: выгрузка по классу (с фильтрами предмет/год/четверть/неделя)
    if "user_id" not in session or session.get("role") not in ["teacher", "admin"]:
        flash("Доступ только для учителей/админов", "danger")
        return redirect(url_for("login"))

    subject_id = int(request.args.get("subject", 0))
    year = int(request.args.get("year", current_year()))
    quarter = int(request.args.get("quarter", 0))
    week = int(request.args.get("week", 0))
    subject = Subject.query.get(subject_id) if subject_id != 0 else None
    students = User.query.filter_by(role="student").all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Отчет класса"

    ws.append(["ФИО ученика", "Предмет", "Период", "Неделя", "Оценки", "Средний балл"])

    for st in students:
        q = Grade.query.filter_by(student_id=st.id, year=year)
        if quarter != 0:
            q = q.filter_by(quarter=quarter)
        if subject_id != 0:
            q = q.filter_by(subject_id=subject_id)
        if week != 0:
            q = q.filter_by(week=week)
        rows = q.all()
        grades = [g.value for g in rows]
        avg = round(sum(grades)/len(grades), 2) if grades else ""
        subjname = subject.name if subject else "Все"
        period_str = f"{year}, Q{quarter if quarter else '1-4'}"
        week_str = week if week else "все"
        ws.append([st.fullname or st.username, subjname, period_str, week_str, ";".join(map(str, grades)), avg])

    autosize_columns(ws)

    # Диаграмма по средним (колонка F)
    data_start = 2
    data_end = ws.max_row
    if data_end >= data_start:
        chart = BarChart()
        chart.title = "Средний балл по ученикам"
        values = Reference(ws, min_col=6, min_row=1, max_row=data_end)  # F1..F*
        cats = Reference(ws, min_col=1, min_row=2, max_row=data_end)    # A2..A*
        chart.add_data(values, titles_from_data=True)
        chart.set_categories(cats)
        chart.y_axis.title = "Средний балл"
        chart.x_axis.title = "Ученик"
        ws.add_chart(chart, "H2")

    filepath = os.path.join(INSTANCE_DIR, f"teacher_report_{year}_q{quarter}_w{week}.xlsx")
    wb.save(filepath)
    return send_file(filepath, as_attachment=True)

@app.route("/export/admin_xlsx")
def export_admin_xlsx():
    # Админ: сводная по ученикам/предметам (средние за год)
    if "user_id" not in session or session.get("role") != "admin":
        flash("Доступ только для админов", "danger")
        return redirect(url_for("login"))

    year = int(request.args.get("year", current_year()))
    students = User.query.filter_by(role="student").all()
    subjects = Subject.query.all()
    subject_map = {s.id: s.name for s in subjects}

    wb = Workbook()
    ws = wb.active
    ws.title = f"Итоги {year}"

    # Заголовки
    headers = ["Ученик"] + [s.name for s in subjects] + ["Общий средний"]
    ws.append(headers)

    # Данные
    for st in students:
        q = Grade.query.filter_by(student_id=st.id, year=year).all()
        subj_avgs = {}
        for g in q:
            name = subject_map.get(g.subject_id, "Неизв.")
            subj_avgs.setdefault(name, []).append(g.value)
        row = [st.fullname or st.username]
        vals_for_mean = []
        for s in subjects:
            vals = subj_avgs.get(s.name, [])
            avg = round(sum(vals)/len(vals), 2) if vals else ""
            row.append(avg)
            if isinstance(avg, (int, float)):
                vals_for_mean.append(avg)
        overall = round(sum(vals_for_mean)/len(vals_for_mean), 2) if vals_for_mean else ""
        row.append(overall)
        ws.append(row)

    autosize_columns(ws)

    # Диаграмма по общему среднему (последняя колонка)
    last_col = ws.max_column
    data_end = ws.max_row
    if data_end >= 2:
        chart = BarChart()
        chart.title = "Общий средний балл (по ученикам)"
        values = Reference(ws, min_col=last_col, min_row=1, max_row=data_end)
        cats = Reference(ws, min_col=1, min_row=2, max_row=data_end)
        chart.add_data(values, titles_from_data=True)
        chart.set_categories(cats)
        chart.y_axis.title = "Средний балл"
        chart.x_axis.title = "Ученик"
        ws.add_chart(chart, f"{get_column_letter(last_col+2)}2")

    filepath = os.path.join(INSTANCE_DIR, f"admin_report_{year}.xlsx")
    wb.save(filepath)
    return send_file(filepath, as_attachment=True)

@app.route("/export/student_xlsx")
def export_student_xlsx():
    # Студент: личный отчёт с диаграммой по предметам
    if "user_id" not in session or session.get("role") != "student":
        flash("Доступ только для студентов", "danger")
        return redirect(url_for("login"))

    student_id = session["user_id"]
    year = int(request.args.get("year", current_year()))
    subjects = Subject.query.all()
    subject_map = {s.id: s.name for s in subjects}

    q = Grade.query.filter_by(student_id=student_id, year=year).all()
    subj_avgs = {}
    for g in q:
        name = subject_map.get(g.subject_id, "Неизв.")
        subj_avgs.setdefault(name, []).append(g.value)

    wb = Workbook()
    ws = wb.active
    ws.title = f"Отчёт {year}"

    ws.append(["Предмет", "Средний балл"])
    for s in subjects:
        vals = subj_avgs.get(s.name, [])
        avg = round(sum(vals)/len(vals), 2) if vals else 0
        ws.append([s.name, avg])

    autosize_columns(ws)

    # Диаграмма по предметам
    data_end = ws.max_row
    if data_end >= 2:
        chart = BarChart()
        chart.title = "Средний балл по предметам"
        values = Reference(ws, min_col=2, min_row=1, max_row=data_end)
        cats = Reference(ws, min_col=1, min_row=2, max_row=data_end)
        chart.add_data(values, titles_from_data=True)
        chart.set_categories(cats)
        chart.y_axis.title = "Средний балл"
        chart.x_axis.title = "Предмет"
        ws.add_chart(chart, "E2")

    filepath = os.path.join(INSTANCE_DIR, f"student_report_{year}.xlsx")
    wb.save(filepath)
    return send_file(filepath, as_attachment=True)

# ───────── Admin ─────────
@app.route("/admin", methods=["GET", "POST"])
def admin_page():
    if "user_id" not in session or session.get("role") != "admin":
        flash("Доступ только для админов", "danger")
        return redirect(url_for("login"))

    message = ""
    if request.method == "POST":
        username = request.form["username"].strip()
        fullname = request.form.get("fullname", "").strip()
        password = request.form["password"].strip()
        role = request.form["role"]
        if username and password and len(password) > 4 and role in ["student", "teacher", "admin"]:
            if User.query.filter_by(username=username).first():
                message = "Пользователь с таким логином уже существует"
                flash(message, "danger")
            else:
                u = User(username=username,
                         password_hash=generate_password_hash(password),
                         role=role, fullname=fullname)
                db.session.add(u)
                db.session.commit()
                message = "Пользователь создан"
                flash(message, "success")
        else:
            message = "Неверные данные (пароль >4 символов, корректная роль)"
            flash(message, "danger")

    users = User.query.all()
    return render_template("admin.html", users=users, message=message)


@app.route("/admin/reports")
def admin_reports():
    if "user_id" not in session or session.get("role") != "admin":
        flash("Доступ только для админов", "danger")
        return redirect(url_for("login"))

    year = int(request.args.get("year", current_year()))
    if year < 2000 or year > current_year() + 1:
        year = current_year()
        flash("Год исправлен на текущий", "info")

    students = User.query.filter_by(role="student").all()
    subjects = Subject.query.all()
    if not subjects:
        flash("Нет предметов в базе. Запустите инициализацию БД.", "danger")
        return redirect(url_for("admin_page"))

    subject_map = {s.id: s.name for s in subjects}
    report_data = []
    for st in students:
        q = Grade.query.filter_by(student_id=st.id, year=year).all()
        subj_avgs = {}
        for g in q:
            subjname = subject_map.get(g.subject_id, "Неизвестный")
            subj_avgs.setdefault(subjname, []).append(g.value)
        subj_avgs = {k: round(sum(v)/len(v), 2) if v else 0 for k, v in subj_avgs.items()}
        overall_avg = round(sum([g.value for g in q])/len(q), 2) if q else 0
        report_data.append({
            "student": st.fullname or st.username,
            "subj_avgs": subj_avgs,
            "overall": overall_avg
        })

    return render_template("admin_reports.html",
                           year=year,
                           report_data=report_data,
                           total_students=len(students),
                           subjects=subjects)


@app.route("/export/admin_xlsx")
def export_admin_xlsx():
    # Админ: сводная по ученикам/предметам (средние за год)
    if "user_id" not in session or session.get("role") != "admin":
        flash("Доступ только для админов", "danger")
        return redirect(url_for("login"))

    year = int(request.args.get("year", current_year()))
    students = User.query.filter_by(role="student").all()
    subjects = Subject.query.all()
    subject_map = {s.id: s.name for s in subjects}

    wb = Workbook()
    ws = wb.active
    ws.title = f"Итоги {year}"

    # Заголовки
    headers = ["Ученик"] + [s.name for s in subjects] + ["Общий средний"]
    ws.append(headers)

    # Данные
    for st in students:
        q = Grade.query.filter_by(student_id=st.id, year=year).all()
        subj_avgs = {}
        for g in q:
            name = subject_map.get(g.subject_id, "Неизв.")
            subj_avgs.setdefault(name, []).append(g.value)
        row = [st.fullname or st.username]
        vals_for_mean = []
        for s in subjects:
            vals = subj_avgs.get(s.name, [])
            avg = round(sum(vals)/len(vals), 2) if vals else ""
            row.append(avg)
            if isinstance(avg, (int, float)):
                vals_for_mean.append(avg)
        overall = round(sum(vals_for_mean)/len(vals_for_mean), 2) if vals_for_mean else ""
        row.append(overall)
        ws.append(row)

    # Автоширина
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            max_len = max(max_len, len(str(cell.value)) if cell.value else 0)
        ws.column_dimensions[col_letter].width = max(12, min(40, max_len + 2))

    # Диаграмма по общему среднему (последняя колонка)
    last_col = ws.max_column
    data_end = ws.max_row
    if data_end >= 2:
        chart = BarChart()
        chart.title = "Общий средний балл (по ученикам)"
        values = Reference(ws, min_col=last_col, min_row=1, max_row=data_end)
        cats = Reference(ws, min_col=1, min_row=2, max_row=data_end)
        chart.add_data(values, titles_from_data=True)
        chart.set_categories(cats)
        chart.y_axis.title = "Средний балл"
        chart.x_axis.title = "Ученик"
        ws.add_chart(chart, f"{get_column_letter(last_col+2)}2")

    filepath = os.path.join(INSTANCE_DIR, f"admin_report_{year}.xlsx")
    wb.save(filepath)
    return send_file(filepath, as_attachment=True)

    
# ───────── Admin Dashboard ─────────
@app.route("/admin/dashboard")
def admin_dashboard():
    if "user_id" not in session or session.get("role") != "admin":
        flash("Доступ только для админов", "danger")
        return redirect(url_for("login"))

    return render_template("admin_dashboard.html")


# ───────── CLI ─────────
if __name__ == "__main__":
    import sys
    with app.app_context():
        db.create_all()
    if "initdb" in sys.argv:
        with app.app_context():
            create_demo_data()
    else:
        app.run(host="0.0.0.0", port=5000, debug=True)
