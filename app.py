import csv
import io
import sqlite3
from datetime import datetime

from flask import Flask, flash, redirect, render_template, request, send_file, url_for


DB_FILE = "hr_payroll_web.db"

app = Flask(__name__)
app.secret_key = "change-this-secret-key"


def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def to_num(text, default=0.0):
    t = (text or "").replace(",", "").strip()
    if not t:
        return float(default)
    return float(t)


def money(v):
    return f"{float(v):,.0f}"


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
    conn.commit()
    conn.close()


def list_employees():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM employees ORDER BY id DESC").fetchall()
    conn.close()
    return rows


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


def leave_summary():
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT e.id, e.name, e.department, e.position, e.leave_grant,
               COALESCE(SUM(l.days), 0) AS used_days,
               e.leave_grant - COALESCE(SUM(l.days), 0) AS remain_days
        FROM employees e
        LEFT JOIN leave_usage l ON e.id = l.employee_id
        GROUP BY e.id, e.name, e.department, e.position, e.leave_grant
        ORDER BY e.id DESC
        """
    ).fetchall()
    conn.close()
    return rows


def get_employee(employee_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
    conn.close()
    return row


def get_payroll(payroll_id):
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


def build_payslip_text(row):
    if not row:
        return ""
    lines = [
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
    return "\n".join(lines)


def calculate(employee, form):
    hours = to_num(form.get("hours"), 209)
    ot_hours = to_num(form.get("ot_hours"), 0)
    ot_mul = to_num(form.get("ot_mul"), 1.5)
    bonus = to_num(form.get("bonus"), 0)
    allowances = to_num(form.get("allowances"), 0)
    other = to_num(form.get("other_deduct"), 0)

    if employee["emp_type"] == "시급제":
        base_pay = (employee["hourly"] or 0) * hours
    else:
        base_pay = employee["monthly"] or 0

    overtime_pay = (employee["hourly"] or 0) * ot_hours * ot_mul
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
    }


@app.context_processor
def inject_helpers():
    return {"money": money, "today_month": datetime.now().strftime("%Y-%m"), "today_date": datetime.now().strftime("%Y-%m-%d")}


@app.get("/")
def dashboard():
    init_db()
    tab = request.args.get("tab", "employees")
    month = request.args.get("month", "").strip()
    payslip_id = request.args.get("payslip_id", "").strip()
    payslip_row = get_payroll(int(payslip_id)) if payslip_id.isdigit() else None
    return render_template(
        "dashboard.html",
        active_tab=tab,
        employees=list_employees(),
        payroll_rows=list_payroll(month or None),
        leave_rows=leave_summary(),
        month_filter=month,
        payslip_id=payslip_id,
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
        INSERT INTO employees(name, department, position, emp_type, hourly, monthly, start_date, leave_grant, created_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            name,
            request.form.get("department", "").strip(),
            request.form.get("position", "").strip(),
            request.form.get("emp_type", "월급제").strip(),
            to_num(request.form.get("hourly"), 0),
            to_num(request.form.get("monthly"), 0),
            request.form.get("start_date", "").strip(),
            to_num(request.form.get("leave_grant"), 15),
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
        SET name=?, department=?, position=?, emp_type=?, hourly=?, monthly=?, start_date=?, leave_grant=?
        WHERE id=?
        """,
        (
            request.form.get("name", "").strip(),
            request.form.get("department", "").strip(),
            request.form.get("position", "").strip(),
            request.form.get("emp_type", "월급제").strip(),
            to_num(request.form.get("hourly"), 0),
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


@app.post("/payroll/calculate")
def payroll_calculate():
    employee_id = request.form.get("employee_id", "").strip()
    if not employee_id.isdigit():
        flash("근로자를 선택해주세요.", "error")
        return redirect(url_for("dashboard", tab="payroll"))
    employee = get_employee(int(employee_id))
    if not employee:
        flash("근로자를 찾을 수 없습니다.", "error")
        return redirect(url_for("dashboard", tab="payroll"))
    preview = calculate(employee, request.form)
    return render_template(
        "dashboard.html",
        active_tab="payroll",
        employees=list_employees(),
        payroll_rows=list_payroll(None),
        leave_rows=leave_summary(),
        month_filter="",
        payslip_id="",
        payslip_text="",
        payroll_preview=preview,
        payroll_form=request.form,
    )


@app.post("/payroll/save")
def payroll_save():
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
    return redirect(url_for("dashboard", tab="ledger", payslip_id=payroll_id))


@app.get("/ledger/export")
def ledger_export():
    month = request.args.get("month", "").strip()
    rows = list_payroll(month or None)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["ID", "급여월", "성명", "부서", "직급", "기본급", "연장수당", "상여", "수당", "총지급", "총공제", "실지급", "등록시각"]
    )
    for r in rows:
        writer.writerow(
            [
                r["id"],
                r["pay_month"],
                r["name"],
                r["department"] or "",
                r["position"] or "",
                r["base_pay"],
                r["overtime_pay"],
                r["bonus"],
                r["allowances"],
                r["gross"],
                r["total_deduct"],
                r["net"],
                r["created_at"],
            ]
        )
    mem = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    filename = f"ledger_{month or 'all'}.csv"
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


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
