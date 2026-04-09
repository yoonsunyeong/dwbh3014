import csv
import io
import os
import sqlite3
from datetime import datetime

from flask import Flask, flash, redirect, render_template, request, send_file, url_for


if os.getenv("VERCEL"):
    DB_FILE = "/tmp/hr_payroll_web.db"
else:
    DB_FILE = "hr_payroll_web.db"

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-secret-key")


def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_month():
    return datetime.now().strftime("%Y-%m")


def today_date():
    return datetime.now().strftime("%Y-%m-%d")


def to_num(text, default=0.0):
    t = (text or "").replace(",", "").strip()
    if not t:
        return float(default)
    return float(t)


def money(v):
    return f"{float(v):,.0f}"


def ensure_column(conn, table, column, col_def):
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column in cols:
        return
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
    except sqlite3.OperationalError as e:
        # Concurrent cold starts can race while adding a new column.
        if "duplicate column name" not in str(e).lower():
            raise


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            department TEXT,
            position TEXT,
            emp_type TEXT NOT NULL,
            hourly REAL DEFAULT 0,
            monthly REAL DEFAULT 0,
            start_date TEXT,
            leave_grant REAL DEFAULT 15,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS payroll (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            pay_month TEXT NOT NULL,
            base_pay REAL NOT NULL,
            overtime_pay REAL NOT NULL,
            bonus REAL NOT NULL,
            allowances REAL NOT NULL,
            np REAL NOT NULL,
            hi REAL NOT NULL,
            ei REAL NOT NULL,
            it REAL NOT NULL,
            lit REAL NOT NULL,
            other_deduct REAL NOT NULL,
            total_deduct REAL NOT NULL,
            gross REAL NOT NULL,
            net REAL NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(employee_id) REFERENCES employees(id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            leave_date TEXT NOT NULL,
            days REAL NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(employee_id) REFERENCES employees(id)
        )
        """
    )

    ensure_column(conn, "employees", "daily_wage", "REAL DEFAULT 0")
    ensure_column(conn, "employees", "weekly_hours", "REAL DEFAULT 40")
    ensure_column(conn, "employees", "employment_status", "TEXT DEFAULT '재직'")
    ensure_column(conn, "employees", "resigned_date", "TEXT")

    conn.commit()
    conn.close()


def list_employees():
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT * FROM employees
        ORDER BY CASE employment_status WHEN '재직' THEN 0 ELSE 1 END, id DESC
        """
    ).fetchall()
    conn.close()
    return rows


def get_employee(employee_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
    conn.close()
    return row


def list_payroll(month=None):
    conn = get_conn()
    if month:
        rows = conn.execute(
            """
            SELECT p.*, e.name, e.department, e.position, e.emp_type
            FROM payroll p JOIN employees e ON p.employee_id = e.id
            WHERE p.pay_month=?
            ORDER BY p.id DESC
            """,
            (month,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT p.*, e.name, e.department, e.position, e.emp_type
            FROM payroll p JOIN employees e ON p.employee_id = e.id
            ORDER BY p.id DESC
            """
        ).fetchall()
    conn.close()
    return rows


def list_pay_months():
    conn = get_conn()
    months = [r["pay_month"] for r in conn.execute("SELECT DISTINCT pay_month FROM payroll ORDER BY pay_month DESC").fetchall()]
    conn.close()
    if today_month() not in months:
        months.insert(0, today_month())
    return months


def list_ledger_rows(pay_month):
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT
            e.id AS employee_id,
            e.name,
            e.department,
            e.position,
            e.employment_status,
            e.resigned_date,
            p.id AS payroll_id,
            p.pay_month,
            p.base_pay,
            p.overtime_pay,
            p.gross,
            p.total_deduct,
            p.net,
            p.created_at
        FROM employees e
        LEFT JOIN (
            SELECT p1.*
            FROM payroll p1
            JOIN (
                SELECT employee_id, MAX(id) AS max_id
                FROM payroll
                WHERE pay_month=?
                GROUP BY employee_id
            ) m ON p1.id = m.max_id
        ) p ON e.id = p.employee_id
        ORDER BY CASE e.employment_status WHEN '재직' THEN 0 ELSE 1 END, e.id DESC
        """,
        (pay_month,),
    ).fetchall()
    conn.close()
    return rows


def get_payroll_by_id(payroll_id):
    conn = get_conn()
    row = conn.execute(
        """
        SELECT p.*, e.name, e.department, e.position, e.emp_type
        FROM payroll p JOIN employees e ON p.employee_id=e.id
        WHERE p.id=?
        """,
        (payroll_id,),
    ).fetchone()
    conn.close()
    return row


def get_latest_payroll_by_employee_month(employee_id, pay_month):
    conn = get_conn()
    row = conn.execute(
        """
        SELECT p.*, e.name, e.department, e.position, e.emp_type
        FROM payroll p
        JOIN employees e ON p.employee_id=e.id
        WHERE p.employee_id=? AND p.pay_month=?
        ORDER BY p.id DESC
        LIMIT 1
        """,
        (employee_id, pay_month),
    ).fetchone()
    conn.close()
    return row


def leave_summary():
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT e.id, e.name, e.department, e.position, e.leave_grant,
               COALESCE(SUM(l.days), 0) AS used_days,
               e.leave_grant - COALESCE(SUM(l.days), 0) AS remain_days,
               e.employment_status
        FROM employees e
        LEFT JOIN leave_usage l ON e.id = l.employee_id
        GROUP BY e.id, e.name, e.department, e.position, e.leave_grant, e.employment_status
        ORDER BY CASE e.employment_status WHEN '재직' THEN 0 ELSE 1 END, e.id DESC
        """
    ).fetchall()
    conn.close()
    return rows


def get_effective_hourly(employee):
    hourly = to_num(employee["hourly"], 0)
    daily = to_num(employee["daily_wage"], 0)
    if hourly > 0:
        return hourly
    if daily > 0:
        return daily / 8.0
    return 0.0


def calculate(employee, form):
    hours = to_num(form.get("hours"), 209)
    ot_hours = to_num(form.get("ot_hours"), 0)
    ot_mul = to_num(form.get("ot_mul"), 1.5)
    bonus = to_num(form.get("bonus"), 0)
    allowances = to_num(form.get("allowances"), 0)
    other = to_num(form.get("other_deduct"), 0)

    effective_hourly = get_effective_hourly(employee)
    monthly = to_num(employee["monthly"], 0)
    emp_type = (employee["emp_type"] or "월급제").strip()

    if emp_type == "월급제" and monthly > 0:
        base_pay = monthly
    else:
        base_pay = effective_hourly * hours

    overtime_pay = effective_hourly * ot_hours * ot_mul
    gross = base_pay + overtime_pay + bonus + allowances
    np = gross * 0.045
    hi = gross * 0.03545
    ei = gross * 0.009
    it = gross * 0.03
    lit = it * 0.1
    total_deduct = np + hi + ei + it + lit + other
    net = gross - total_deduct

    return {
        "base_pay": base_pay,
        "overtime_pay": overtime_pay,
        "bonus": bonus,
        "allowances": allowances,
        "np": np,
        "hi": hi,
        "ei": ei,
        "it": it,
        "lit": lit,
        "other_deduct": other,
        "total_deduct": total_deduct,
        "gross": gross,
        "net": net,
        "effective_hourly": effective_hourly,
    }


def build_payslip_text(row):
    if not row:
        return ""
    return "\n".join(
        [
            "========== 임금명세서 ==========",
            f"작성: {row['created_at']}",
            f"급여월: {row['pay_month']}",
            "",
            f"성명: {row['name']}",
            f"부서/직급: {row['department'] or '-'} / {row['position'] or '-'}",
            f"고용형태: {row['emp_type']}",
            "",
            "[지급]",
            f"기본급: {money(row['base_pay'])}",
            f"연장수당: {money(row['overtime_pay'])}",
            f"상여: {money(row['bonus'])}",
            f"수당: {money(row['allowances'])}",
            f"총지급: {money(row['gross'])}",
            "",
            "[공제]",
            f"국민연금: {money(row['np'])}",
            f"건강보험: {money(row['hi'])}",
            f"고용보험: {money(row['ei'])}",
            f"소득세: {money(row['it'])}",
            f"지방소득세: {money(row['lit'])}",
            f"기타공제: {money(row['other_deduct'])}",
            f"총공제: {money(row['total_deduct'])}",
            "",
            f"실지급: {money(row['net'])}",
            "================================",
        ]
    )


@app.context_processor
def inject_helpers():
    return {
        "money": money,
        "today_month": today_month(),
        "today_date": today_date(),
    }


@app.before_request
def _before_request():
    init_db()


@app.get("/")
def dashboard():
    init_db()
    tab = request.args.get("tab", "employees")
    month = request.args.get("month", "").strip() or today_month()

    payslip_id = request.args.get("payslip_id", "").strip()
    payslip_employee_id = request.args.get("payslip_employee_id", "").strip()
    payslip_month = request.args.get("payslip_month", "").strip() or month

    payslip_row = None
    if payslip_id.isdigit():
        payslip_row = get_payroll_by_id(int(payslip_id))
    elif payslip_employee_id.isdigit() and payslip_month:
        payslip_row = get_latest_payroll_by_employee_month(int(payslip_employee_id), payslip_month)

    employees = list_employees()
    return render_template(
        "dashboard.html",
        active_tab=tab,
        employees=employees,
        payroll_rows=list_payroll(month),
        ledger_rows=list_ledger_rows(month),
        leave_rows=leave_summary(),
        month_filter=month,
        pay_months=list_pay_months(),
        payslip_id=payslip_id,
        payslip_employee_id=payslip_employee_id,
        payslip_month=payslip_month,
        payslip_text=build_payslip_text(payslip_row),
        payroll_preview=None,
        payroll_form={},
    )


@app.post("/employee/add")
def employee_add():
    name = request.form.get("name", "").strip()
    if not name:
        flash("성명을 입력해주세요.", "error")
        return redirect(url_for("dashboard", tab="employees"))

    conn = get_conn()
    conn.execute(
        """
        INSERT INTO employees
        (name, department, position, emp_type, hourly, daily_wage, weekly_hours, monthly, start_date, leave_grant, employment_status, resigned_date, created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            name,
            request.form.get("department", "").strip(),
            request.form.get("position", "").strip(),
            request.form.get("emp_type", "월급제").strip(),
            to_num(request.form.get("hourly"), 0),
            to_num(request.form.get("daily_wage"), 0),
            to_num(request.form.get("weekly_hours"), 40),
            to_num(request.form.get("monthly"), 0),
            request.form.get("start_date", "").strip(),
            to_num(request.form.get("leave_grant"), 15),
            "재직",
            "",
            now_text(),
        ),
    )
    conn.commit()
    conn.close()
    flash("근로자를 등록했습니다.", "ok")
    return redirect(url_for("dashboard", tab="employees"))


@app.post("/employee/update")
def employee_update():
    employee_id = request.form.get("employee_id", "").strip()
    if not employee_id.isdigit():
        flash("수정할 근로자 ID를 입력해주세요.", "error")
        return redirect(url_for("dashboard", tab="employees"))
    conn = get_conn()
    conn.execute(
        """
        UPDATE employees
        SET name=?, department=?, position=?, emp_type=?, hourly=?, daily_wage=?, weekly_hours=?, monthly=?, start_date=?, leave_grant=?
        WHERE id=?
        """,
        (
            request.form.get("name", "").strip(),
            request.form.get("department", "").strip(),
            request.form.get("position", "").strip(),
            request.form.get("emp_type", "월급제").strip(),
            to_num(request.form.get("hourly"), 0),
            to_num(request.form.get("daily_wage"), 0),
            to_num(request.form.get("weekly_hours"), 40),
            to_num(request.form.get("monthly"), 0),
            request.form.get("start_date", "").strip(),
            to_num(request.form.get("leave_grant"), 15),
            int(employee_id),
        ),
    )
    conn.commit()
    conn.close()
    flash("근로자 정보를 수정했습니다.", "ok")
    return redirect(url_for("dashboard", tab="employees"))


@app.post("/employee/update-inline")
def employee_update_inline():
    selected_ids = [x for x in request.form.getlist("selected_ids") if x.isdigit()]
    if not selected_ids:
        flash("수정할 행을 체크해주세요.", "error")
        return redirect(url_for("dashboard", tab="employees"))

    conn = get_conn()
    for sid in selected_ids:
        emp_id = int(sid)
        name = request.form.get(f"name_{sid}", "").strip()
        if not name:
            continue
        status = request.form.get(f"employment_status_{sid}", "재직").strip()
        resigned_date = request.form.get(f"resigned_date_{sid}", "").strip()
        if status == "재직":
            resigned_date = ""

        conn.execute(
            """
            UPDATE employees
            SET name=?, department=?, position=?, emp_type=?, hourly=?, daily_wage=?, weekly_hours=?, monthly=?,
                start_date=?, leave_grant=?, employment_status=?, resigned_date=?
            WHERE id=?
            """,
            (
                name,
                request.form.get(f"department_{sid}", "").strip(),
                request.form.get(f"position_{sid}", "").strip(),
                request.form.get(f"emp_type_{sid}", "월급제").strip(),
                to_num(request.form.get(f"hourly_{sid}"), 0),
                to_num(request.form.get(f"daily_wage_{sid}"), 0),
                to_num(request.form.get(f"weekly_hours_{sid}"), 40),
                to_num(request.form.get(f"monthly_{sid}"), 0),
                request.form.get(f"start_date_{sid}", "").strip(),
                to_num(request.form.get(f"leave_grant_{sid}"), 15),
                status,
                resigned_date,
                emp_id,
            ),
        )
    conn.commit()
    conn.close()
    flash("체크한 근로자 정보를 목록에서 바로 수정했습니다.", "ok")
    return redirect(url_for("dashboard", tab="employees"))


@app.post("/employee/retire")
def employee_retire():
    employee_id = request.form.get("employee_id", "").strip()
    resigned_date = request.form.get("resigned_date", "").strip() or today_date()
    if not employee_id.isdigit():
        flash("퇴사 처리할 근로자 ID를 입력해주세요.", "error")
        return redirect(url_for("dashboard", tab="employees"))
    conn = get_conn()
    conn.execute(
        "UPDATE employees SET employment_status='퇴사', resigned_date=? WHERE id=?",
        (resigned_date, int(employee_id)),
    )
    conn.commit()
    conn.close()
    flash("퇴사 처리했습니다.", "ok")
    return redirect(url_for("dashboard", tab="employees"))


@app.post("/employee/reactivate")
def employee_reactivate():
    employee_id = request.form.get("employee_id", "").strip()
    if not employee_id.isdigit():
        flash("재직 전환할 근로자 ID를 입력해주세요.", "error")
        return redirect(url_for("dashboard", tab="employees"))
    conn = get_conn()
    conn.execute(
        "UPDATE employees SET employment_status='재직', resigned_date='' WHERE id=?",
        (int(employee_id),),
    )
    conn.commit()
    conn.close()
    flash("재직 상태로 변경했습니다.", "ok")
    return redirect(url_for("dashboard", tab="employees"))


@app.post("/employee/delete")
def employee_delete():
    employee_id = request.form.get("employee_id", "").strip()
    if not employee_id.isdigit():
        flash("삭제할 근로자 ID를 입력해주세요.", "error")
        return redirect(url_for("dashboard", tab="employees"))
    emp_id = int(employee_id)
    conn = get_conn()
    conn.execute("DELETE FROM payroll WHERE employee_id=?", (emp_id,))
    conn.execute("DELETE FROM leave_usage WHERE employee_id=?", (emp_id,))
    conn.execute("DELETE FROM employees WHERE id=?", (emp_id,))
    conn.commit()
    conn.close()
    flash("근로자를 삭제했습니다.", "ok")
    return redirect(url_for("dashboard", tab="employees"))


def build_dashboard_context_for_payroll(form, preview):
    month = form.get("pay_month", today_month()).strip() or today_month()
    employees = list_employees()
    return {
        "active_tab": "payroll",
        "employees": employees,
        "payroll_rows": list_payroll(month),
        "ledger_rows": list_ledger_rows(month),
        "leave_rows": leave_summary(),
        "month_filter": month,
        "pay_months": list_pay_months(),
        "payslip_id": "",
        "payslip_employee_id": "",
        "payslip_month": month,
        "payslip_text": "",
        "payroll_preview": preview,
        "payroll_form": dict(form),
    }


@app.post("/payroll/calculate")
def payroll_calculate():
    try:
        employee_id = request.form.get("employee_id", "").strip()
        if not employee_id.isdigit():
            flash("근로자를 선택해주세요.", "error")
            return redirect(url_for("dashboard", tab="payroll"))
        employee = get_employee(int(employee_id))
        if not employee:
            flash("근로자를 찾을 수 없습니다.", "error")
            return redirect(url_for("dashboard", tab="payroll"))
        preview = calculate(employee, request.form)
        return render_template("dashboard.html", **build_dashboard_context_for_payroll(request.form, preview))
    except Exception as e:
        flash(f"급여 계산 중 오류가 발생했습니다: {e}", "error")
        return redirect(url_for("dashboard", tab="payroll"))


@app.post("/payroll/save")
def payroll_save():
    try:
        employee_id = request.form.get("employee_id", "").strip()
        pay_month = request.form.get("pay_month", "").strip()
        if not employee_id.isdigit() or not pay_month:
            flash("근로자와 급여월을 확인해주세요.", "error")
            return redirect(url_for("dashboard", tab="payroll"))
        employee = get_employee(int(employee_id))
        if not employee:
            flash("근로자를 찾을 수 없습니다.", "error")
            return redirect(url_for("dashboard", tab="payroll"))
        calc = calculate(employee, request.form)

        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO payroll(employee_id, pay_month, base_pay, overtime_pay, bonus, allowances,
                                np, hi, ei, it, lit, other_deduct, total_deduct, gross, net, created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                int(employee_id),
                pay_month,
                calc["base_pay"],
                calc["overtime_pay"],
                calc["bonus"],
                calc["allowances"],
                calc["np"],
                calc["hi"],
                calc["ei"],
                calc["it"],
                calc["lit"],
                calc["other_deduct"],
                calc["total_deduct"],
                calc["gross"],
                calc["net"],
                now_text(),
            ),
        )
        conn.commit()
        payroll_id = cur.lastrowid
        conn.close()

        flash(f"급여 데이터를 저장했습니다. ID: {payroll_id}", "ok")
        return redirect(url_for("dashboard", tab="ledger", month=pay_month, payslip_id=payroll_id))
    except Exception as e:
        flash(f"급여 저장 중 오류가 발생했습니다: {e}", "error")
        return redirect(url_for("dashboard", tab="payroll"))


@app.get("/ledger/export")
def ledger_export():
    month = request.args.get("month", "").strip() or today_month()
    rows = list_ledger_rows(month)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["직원ID", "성명", "상태", "급여월", "기본급", "연장수당", "총지급", "총공제", "실지급", "작성상태", "등록시각"]
    )
    for r in rows:
        writer.writerow(
            [
                r["employee_id"],
                r["name"],
                r["employment_status"],
                month,
                r["base_pay"] or 0,
                r["overtime_pay"] or 0,
                r["gross"] or 0,
                r["total_deduct"] or 0,
                r["net"] or 0,
                "작성완료" if r["payroll_id"] else "미작성",
                r["created_at"] or "",
            ]
        )
    mem = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    filename = f"ledger_{month}.csv"
    return send_file(mem, as_attachment=True, download_name=filename, mimetype="text/csv")


@app.post("/leave/add")
def leave_add():
    employee_id = request.form.get("employee_id", "").strip()
    if not employee_id.isdigit():
        flash("연차 등록할 근로자를 선택해주세요.", "error")
        return redirect(url_for("dashboard", tab="leave"))
    conn = get_conn()
    conn.execute(
        "INSERT INTO leave_usage(employee_id, leave_date, days, note, created_at) VALUES(?,?,?,?,?)",
        (
            int(employee_id),
            request.form.get("leave_date", "").strip(),
            to_num(request.form.get("days"), 1),
            request.form.get("note", "").strip(),
            now_text(),
        ),
    )
    conn.commit()
    conn.close()
    flash("연차 사용을 등록했습니다.", "ok")
    return redirect(url_for("dashboard", tab="leave"))


@app.post("/leave/update-grant")
def leave_update_grant():
    employee_id = request.form.get("employee_id", "").strip()
    if not employee_id.isdigit():
        flash("연차 부여일수 수정 대상 근로자를 선택해주세요.", "error")
        return redirect(url_for("dashboard", tab="leave"))
    conn = get_conn()
    conn.execute(
        "UPDATE employees SET leave_grant=? WHERE id=?",
        (to_num(request.form.get("leave_grant"), 15), int(employee_id)),
    )
    conn.commit()
    conn.close()
    flash("연차 부여일수를 수정했습니다.", "ok")
    return redirect(url_for("dashboard", tab="leave"))


init_db()


if __name__ == "__main__":
    app.run(debug=True)
