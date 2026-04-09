
import csv
import sqlite3
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText

DB_FILE = "hr_payroll.db"


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def to_num(v, d=0):
    t = (v or "").replace(",", "").strip()
    return float(t) if t else float(d)


def money(v):
    return f"{v:,.0f}"


class DB:
    def __init__(self, path=DB_FILE):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.init()

    def init(self):
        c = self.conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS employees(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, dept TEXT, pos TEXT,
            emp_type TEXT NOT NULL, hourly REAL DEFAULT 0, monthly REAL DEFAULT 0,
            start_date TEXT, leave_grant REAL DEFAULT 15, created_at TEXT NOT NULL
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS payroll(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL, pay_month TEXT NOT NULL,
            base_pay REAL, overtime_pay REAL, bonus REAL, allowances REAL,
            np REAL, hi REAL, ei REAL, it REAL, lit REAL,
            other_deduct REAL, total_deduct REAL, gross REAL, net REAL,
            created_at TEXT NOT NULL
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS leave_usage(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL, leave_date TEXT NOT NULL,
            days REAL NOT NULL, note TEXT, created_at TEXT NOT NULL
        )""")
        self.conn.commit()

    def employees(self):
        return self.conn.execute("SELECT * FROM employees ORDER BY id DESC").fetchall()

    def add_employee(self, data):
        self.conn.execute(
            """INSERT INTO employees(name,dept,pos,emp_type,hourly,monthly,start_date,leave_grant,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (data["name"], data["dept"], data["pos"], data["emp_type"], data["hourly"], data["monthly"], data["start_date"], data["leave_grant"], now_text()),
        )
        self.conn.commit()

    def update_employee(self, emp_id, data):
        self.conn.execute(
            """UPDATE employees SET name=?,dept=?,pos=?,emp_type=?,hourly=?,monthly=?,start_date=?,leave_grant=? WHERE id=?""",
            (data["name"], data["dept"], data["pos"], data["emp_type"], data["hourly"], data["monthly"], data["start_date"], data["leave_grant"], emp_id),
        )
        self.conn.commit()

    def delete_employee(self, emp_id):
        self.conn.execute("DELETE FROM payroll WHERE employee_id=?", (emp_id,))
        self.conn.execute("DELETE FROM leave_usage WHERE employee_id=?", (emp_id,))
        self.conn.execute("DELETE FROM employees WHERE id=?", (emp_id,))
        self.conn.commit()

    def save_payroll(self, d):
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO payroll(employee_id,pay_month,base_pay,overtime_pay,bonus,allowances,np,hi,ei,it,lit,other_deduct,total_deduct,gross,net,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (d["employee_id"], d["pay_month"], d["base_pay"], d["overtime_pay"], d["bonus"], d["allowances"], d["np"], d["hi"], d["ei"], d["it"], d["lit"], d["other_deduct"], d["total_deduct"], d["gross"], d["net"], now_text()),
        )
        self.conn.commit()
        return cur.lastrowid
    def payroll_rows(self, month=None):
        q = """SELECT p.*, e.name, e.dept, e.pos, e.emp_type
               FROM payroll p JOIN employees e ON p.employee_id=e.id"""
        if month:
            return self.conn.execute(q + " WHERE p.pay_month=? ORDER BY p.id DESC", (month,)).fetchall()
        return self.conn.execute(q + " ORDER BY p.id DESC").fetchall()

    def payroll_row(self, pid):
        return self.conn.execute(
            """SELECT p.*, e.name, e.dept, e.pos, e.emp_type
               FROM payroll p JOIN employees e ON p.employee_id=e.id WHERE p.id=?""",
            (pid,),
        ).fetchone()

    def add_leave(self, emp_id, leave_date, days, note):
        self.conn.execute(
            "INSERT INTO leave_usage(employee_id,leave_date,days,note,created_at) VALUES(?,?,?,?,?)",
            (emp_id, leave_date, days, note, now_text()),
        )
        self.conn.commit()

    def leave_summary(self):
        return self.conn.execute(
            """SELECT e.id,e.name,e.dept,e.pos,e.leave_grant,
                      COALESCE(SUM(l.days),0) used,
                      e.leave_grant-COALESCE(SUM(l.days),0) remain
               FROM employees e LEFT JOIN leave_usage l ON e.id=l.employee_id
               GROUP BY e.id,e.name,e.dept,e.pos,e.leave_grant ORDER BY e.id DESC"""
        ).fetchall()


def parse_emp_id(text):
    if "|" not in text:
        raise ValueError("근로자를 선택해주세요.")
    return int(text.split("|")[0].strip())


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("사업장 인사/급여 관리")
        self.geometry("1300x820")
        self.db = DB()
        self.sel_emp_id = None
        self.last_pay = None
        self.build_ui()
        self.refresh_all()

    def build_ui(self):
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.t_emp = ttk.Frame(nb)
        self.t_pay = ttk.Frame(nb)
        self.t_led = ttk.Frame(nb)
        self.t_slip = ttk.Frame(nb)
        self.t_leave = ttk.Frame(nb)
        nb.add(self.t_emp, text="근로자")
        nb.add(self.t_pay, text="급여")
        nb.add(self.t_led, text="임금대장")
        nb.add(self.t_slip, text="임금명세서")
        nb.add(self.t_leave, text="연차")
        self.build_emp()
        self.build_pay()
        self.build_ledger()
        self.build_slip()
        self.build_leave()

    def build_emp(self):
        f = ttk.LabelFrame(self.t_emp, text="근로자 정보")
        f.pack(fill=tk.X, padx=8, pady=8)
        self.ev = {k: tk.StringVar() for k in ["name","dept","pos","type","hourly","monthly","start","grant"]}
        self.ev["type"].set("월급제")
        self.ev["grant"].set("15")
        labels = [("성명","name"),("부서","dept"),("직급","pos"),("고용형태","type"),("시급","hourly"),("월급","monthly"),("입사일","start"),("연차부여","grant")]
        for i,(txt,key) in enumerate(labels):
            ttk.Label(f,text=txt).grid(row=i//4,column=(i%4)*2,padx=6,pady=6,sticky="w")
            if key=="type":
                ttk.Combobox(f,textvariable=self.ev[key],state="readonly",values=["월급제","시급제"],width=14).grid(row=i//4,column=(i%4)*2+1,padx=6,pady=6,sticky="w")
            else:
                ttk.Entry(f,textvariable=self.ev[key],width=16).grid(row=i//4,column=(i%4)*2+1,padx=6,pady=6,sticky="w")
        bf = ttk.Frame(f)
        bf.grid(row=3,column=0,columnspan=8,sticky="w",padx=6,pady=8)
        ttk.Button(bf,text="등록",command=self.add_emp).pack(side=tk.LEFT,padx=4)
        ttk.Button(bf,text="수정",command=self.update_emp).pack(side=tk.LEFT,padx=4)
        ttk.Button(bf,text="삭제",command=self.del_emp).pack(side=tk.LEFT,padx=4)
        cols=("id","name","dept","pos","type","hourly","monthly","start","grant")
        self.emp_tree=ttk.Treeview(self.t_emp,columns=cols,show="headings")
        heads=["ID","성명","부서","직급","형태","시급","월급","입사일","연차"]
        widths=[60,120,120,100,90,100,110,110,80]
        for c,h,w in zip(cols,heads,widths):
            self.emp_tree.heading(c,text=h); self.emp_tree.column(c,width=w,anchor="center")
        self.emp_tree.pack(fill=tk.BOTH,expand=True,padx=8,pady=8)
        self.emp_tree.bind("<<TreeviewSelect>>", self.pick_emp)

    def build_pay(self):
        f = ttk.LabelFrame(self.t_pay,text="급여 계산")
        f.pack(fill=tk.X,padx=8,pady=8)
        self.pv={k:tk.StringVar() for k in ["emp","month","hours","ot_hours","ot_mul","bonus","allow","other"]}
        self.pv["month"].set(datetime.now().strftime("%Y-%m"))
        self.pv["hours"].set("209"); self.pv["ot_hours"].set("0"); self.pv["ot_mul"].set("1.5")
        self.pv["bonus"].set("0"); self.pv["allow"].set("0"); self.pv["other"].set("0")
        fields=[("근로자","emp"),("급여월","month"),("소정시간","hours"),("연장시간","ot_hours"),("연장배수","ot_mul"),("상여","bonus"),("수당","allow"),("기타공제","other")]
        for i,(txt,key) in enumerate(fields):
            ttk.Label(f,text=txt).grid(row=i//4,column=(i%4)*2,padx=6,pady=6,sticky="w")
            if key=="emp":
                self.pay_emp=ttk.Combobox(f,textvariable=self.pv[key],state="readonly",width=30)
                self.pay_emp.grid(row=i//4,column=(i%4)*2+1,padx=6,pady=6,sticky="w")
            else:
                ttk.Entry(f,textvariable=self.pv[key],width=16).grid(row=i//4,column=(i%4)*2+1,padx=6,pady=6,sticky="w")
        b=ttk.Frame(f); b.grid(row=3,column=0,columnspan=8,sticky="w",padx=6,pady=8)
        ttk.Button(b,text="계산",command=self.calc_pay).pack(side=tk.LEFT,padx=4)
        ttk.Button(b,text="저장",command=self.save_pay).pack(side=tk.LEFT,padx=4)
        self.pay_text=ScrolledText(self.t_pay,height=22)
        self.pay_text.pack(fill=tk.BOTH,expand=True,padx=8,pady=8)

    def build_ledger(self):
        top=ttk.Frame(self.t_led); top.pack(fill=tk.X,padx=8,pady=8)
        self.month_filter=tk.StringVar()
        ttk.Label(top,text="조회월").pack(side=tk.LEFT,padx=4)
        ttk.Entry(top,textvariable=self.month_filter,width=12).pack(side=tk.LEFT,padx=4)
        ttk.Button(top,text="조회",command=self.refresh_ledger).pack(side=tk.LEFT,padx=4)
        ttk.Button(top,text="CSV",command=self.export_csv).pack(side=tk.LEFT,padx=4)
        cols=("id","month","name","dept","pos","gross","deduct","net","created")
        self.ledger=ttk.Treeview(self.t_led,columns=cols,show="headings")
        heads=["ID","급여월","성명","부서","직급","총지급","총공제","실지급","등록시각"]
        widths=[60,90,120,120,100,110,110,110,150]
        for c,h,w in zip(cols,heads,widths):
            self.ledger.heading(c,text=h); self.ledger.column(c,width=w,anchor="center")
        self.ledger.pack(fill=tk.BOTH,expand=True,padx=8,pady=8)
        self.ledger.bind("<<TreeviewSelect>>", self.pick_ledger)

    def build_slip(self):
        top=ttk.Frame(self.t_slip); top.pack(fill=tk.X,padx=8,pady=8)
        self.slip_id=tk.StringVar()
        ttk.Label(top,text="임금대장 ID").pack(side=tk.LEFT,padx=4)
        ttk.Entry(top,textvariable=self.slip_id,width=10).pack(side=tk.LEFT,padx=4)
        ttk.Button(top,text="불러오기",command=self.load_slip).pack(side=tk.LEFT,padx=4)
        ttk.Button(top,text="텍스트저장",command=self.save_slip_txt).pack(side=tk.LEFT,padx=4)
        self.slip_text=ScrolledText(self.t_slip,height=28)
        self.slip_text.pack(fill=tk.BOTH,expand=True,padx=8,pady=8)

    def build_leave(self):
        top=ttk.LabelFrame(self.t_leave,text="연차 사용")
        top.pack(fill=tk.X,padx=8,pady=8)
        self.lv={k:tk.StringVar() for k in ["emp","date","days","note","u_emp","u_days"]}
        self.lv["date"].set(datetime.now().strftime("%Y-%m-%d")); self.lv["days"].set("1"); self.lv["u_days"].set("15")
        ttk.Label(top,text="근로자").grid(row=0,column=0,padx=6,pady=6,sticky="w")
        self.leave_emp=ttk.Combobox(top,textvariable=self.lv["emp"],state="readonly",width=30)
        self.leave_emp.grid(row=0,column=1,padx=6,pady=6,sticky="w")
        ttk.Label(top,text="일자").grid(row=0,column=2,padx=6,pady=6,sticky="w")
        ttk.Entry(top,textvariable=self.lv["date"],width=14).grid(row=0,column=3,padx=6,pady=6,sticky="w")
        ttk.Label(top,text="일수").grid(row=1,column=0,padx=6,pady=6,sticky="w")
        ttk.Entry(top,textvariable=self.lv["days"],width=14).grid(row=1,column=1,padx=6,pady=6,sticky="w")
        ttk.Label(top,text="사유").grid(row=1,column=2,padx=6,pady=6,sticky="w")
        ttk.Entry(top,textvariable=self.lv["note"],width=35).grid(row=1,column=3,padx=6,pady=6,sticky="w")
        ttk.Button(top,text="연차 사용 등록",command=self.add_leave).grid(row=2,column=0,columnspan=4,padx=6,pady=8,sticky="w")
        mid=ttk.LabelFrame(self.t_leave,text="연차부여 수정")
        mid.pack(fill=tk.X,padx=8,pady=6)
        ttk.Label(mid,text="근로자").grid(row=0,column=0,padx=6,pady=6,sticky="w")
        self.leave_up_emp=ttk.Combobox(mid,textvariable=self.lv["u_emp"],state="readonly",width=30)
        self.leave_up_emp.grid(row=0,column=1,padx=6,pady=6,sticky="w")
        ttk.Label(mid,text="부여일수").grid(row=0,column=2,padx=6,pady=6,sticky="w")
        ttk.Entry(mid,textvariable=self.lv["u_days"],width=14).grid(row=0,column=3,padx=6,pady=6,sticky="w")
        ttk.Button(mid,text="업데이트",command=self.update_grant).grid(row=1,column=0,columnspan=4,padx=6,pady=8,sticky="w")

        cols=("id","name","dept","pos","grant","used","remain")
        self.leave_tree=ttk.Treeview(self.t_leave,columns=cols,show="headings")
        heads=["ID","성명","부서","직급","부여","사용","잔여"]
        widths=[60,120,120,100,90,90,90]
        for c,h,w in zip(cols,heads,widths):
            self.leave_tree.heading(c,text=h); self.leave_tree.column(c,width=w,anchor="center")
        self.leave_tree.pack(fill=tk.BOTH,expand=True,padx=8,pady=8)

    def emp_data(self):
        return {
            "name": self.ev["name"].get().strip(),
            "dept": self.ev["dept"].get().strip(),
            "pos": self.ev["pos"].get().strip(),
            "emp_type": self.ev["type"].get().strip() or "월급제",
            "hourly": to_num(self.ev["hourly"].get()),
            "monthly": to_num(self.ev["monthly"].get()),
            "start_date": self.ev["start"].get().strip(),
            "leave_grant": to_num(self.ev["grant"].get(), 15),
        }

    def add_emp(self):
        d=self.emp_data()
        if not d["name"]:
            messagebox.showwarning("안내","성명을 입력해주세요."); return
        self.db.add_employee(d)
        self.refresh_all()

    def update_emp(self):
        if not self.sel_emp_id:
            messagebox.showwarning("안내","수정할 근로자를 선택해주세요."); return
        self.db.update_employee(self.sel_emp_id, self.emp_data())
        self.refresh_all()

    def del_emp(self):
        if not self.sel_emp_id:
            messagebox.showwarning("안내","삭제할 근로자를 선택해주세요."); return
        if not messagebox.askyesno("확인","근로자 관련 급여/연차 데이터도 함께 삭제됩니다."):
            return
        self.db.delete_employee(self.sel_emp_id)
        self.sel_emp_id=None
        self.refresh_all()

    def pick_emp(self, _=None):
        s=self.emp_tree.selection()
        if not s: return
        v=self.emp_tree.item(s[0],"values")
        self.sel_emp_id=int(v[0])
        self.ev["name"].set(v[1]); self.ev["dept"].set(v[2]); self.ev["pos"].set(v[3]); self.ev["type"].set(v[4])
        self.ev["hourly"].set(str(v[5]).replace(",","")); self.ev["monthly"].set(str(v[6]).replace(",",""))
        self.ev["start"].set(v[7]); self.ev["grant"].set(v[8])

    def calc_pay(self):
        try:
            emp_id=parse_emp_id(self.pv["emp"].get())
            emp=[e for e in self.db.employees() if e["id"]==emp_id][0]
            month=self.pv["month"].get().strip()
            hours=to_num(self.pv["hours"].get(),209)
            ot_h=to_num(self.pv["ot_hours"].get())
            ot_m=to_num(self.pv["ot_mul"].get(),1.5)
            bonus=to_num(self.pv["bonus"].get())
            allow=to_num(self.pv["allow"].get())
            other=to_num(self.pv["other"].get())
            base=(emp["hourly"]*hours) if emp["emp_type"]=="시급제" else (emp["monthly"] or 0)
            ot=(emp["hourly"] or 0)*ot_h*ot_m
            gross=base+ot+bonus+allow
            np=gross*0.045; hi=gross*0.03545; ei=gross*0.009; it=gross*0.03; lit=it*0.1
            ded=np+hi+ei+it+lit+other
            net=gross-ded
            self.last_pay={"employee_id":emp_id,"pay_month":month,"base_pay":base,"overtime_pay":ot,"bonus":bonus,"allowances":allow,"np":np,"hi":hi,"ei":ei,"it":it,"lit":lit,"other_deduct":other,"total_deduct":ded,"gross":gross,"net":net}
            t=[f"[급여 계산] {month}",f"근로자: {emp['name']} ({emp['dept'] or '-'} / {emp['pos'] or '-'})","",f"기본급 {money(base)}",f"연장수당 {money(ot)}",f"상여 {money(bonus)}",f"수당 {money(allow)}",f"총지급 {money(gross)}","",f"국민연금 {money(np)}",f"건강보험 {money(hi)}",f"고용보험 {money(ei)}",f"소득세 {money(it)}",f"지방소득세 {money(lit)}",f"기타공제 {money(other)}",f"총공제 {money(ded)}","",f"실지급 {money(net)}"]
            self.pay_text.delete("1.0",tk.END); self.pay_text.insert(tk.END,"\n".join(t))
        except Exception as e:
            messagebox.showerror("오류", f"급여 계산 실패: {e}")
    def save_pay(self):
        if not self.last_pay:
            messagebox.showwarning("안내","먼저 급여 계산을 실행해주세요."); return
        rid=self.db.save_payroll(self.last_pay)
        self.slip_id.set(str(rid))
        self.refresh_ledger()
        messagebox.showinfo("완료", f"저장 완료 (ID: {rid})")

    def refresh_emp_table(self):
        for i in self.emp_tree.get_children(): self.emp_tree.delete(i)
        emps=self.db.employees()
        for e in emps:
            self.emp_tree.insert("",tk.END,values=(e["id"],e["name"],e["dept"] or "",e["pos"] or "",e["emp_type"],money(e["hourly"]),money(e["monthly"]),e["start_date"] or "",f'{e["leave_grant"]:.1f}'))
        vals=[f'{e["id"]} | {e["name"]} ({e["dept"] or "-"} / {e["pos"] or "-"})' for e in emps]
        self.pay_emp["values"]=vals; self.leave_emp["values"]=vals; self.leave_up_emp["values"]=vals
        if vals:
            if not self.pv["emp"].get(): self.pv["emp"].set(vals[0])
            if not self.lv["emp"].get(): self.lv["emp"].set(vals[0])
            if not self.lv["u_emp"].get(): self.lv["u_emp"].set(vals[0])

    def refresh_ledger(self):
        for i in self.ledger.get_children(): self.ledger.delete(i)
        rows=self.db.payroll_rows(self.month_filter.get().strip() or None)
        for r in rows:
            self.ledger.insert("",tk.END,values=(r["id"],r["pay_month"],r["name"],r["dept"] or "",r["pos"] or "",money(r["gross"]),money(r["total_deduct"]),money(r["net"]),r["created_at"]))

    def pick_ledger(self, _=None):
        s=self.ledger.selection()
        if not s:return
        self.slip_id.set(self.ledger.item(s[0],"values")[0])

    def load_slip(self):
        try:
            r=self.db.payroll_row(int(self.slip_id.get().strip()))
            if not r:
                messagebox.showwarning("안내","대상 급여 데이터가 없습니다."); return
            lines=["========== 임금명세서 ==========" ,f"작성: {r['created_at']}",f"급여월: {r['pay_month']}","",f"성명: {r['name']}",f"부서/직급: {r['dept'] or '-'} / {r['pos'] or '-'}",f"고용형태: {r['emp_type']}","","[지급]",f"기본급: {money(r['base_pay'])}",f"연장수당: {money(r['overtime_pay'])}",f"상여: {money(r['bonus'])}",f"수당: {money(r['allowances'])}",f"총지급: {money(r['gross'])}","","[공제]",f"국민연금: {money(r['np'])}",f"건강보험: {money(r['hi'])}",f"고용보험: {money(r['ei'])}",f"소득세: {money(r['it'])}",f"지방소득세: {money(r['lit'])}",f"기타공제: {money(r['other_deduct'])}",f"총공제: {money(r['total_deduct'])}","",f"실지급: {money(r['net'])}","================================"]
            self.slip_text.delete("1.0",tk.END)
            self.slip_text.insert(tk.END,"\n".join(lines))
        except Exception as e:
            messagebox.showerror("오류", f"명세서 불러오기 실패: {e}")

    def save_slip_txt(self):
        text=self.slip_text.get("1.0",tk.END).strip()
        if not text:
            messagebox.showwarning("안내","저장할 명세서가 없습니다."); return
        p=filedialog.asksaveasfilename(defaultextension=".txt",filetypes=[("Text","*.txt"),("All","*.*")])
        if not p:return
        with open(p,"w",encoding="utf-8") as f: f.write(text)
        messagebox.showinfo("완료",f"저장됨: {p}")

    def export_csv(self):
        rows=self.db.payroll_rows(self.month_filter.get().strip() or None)
        if not rows:
            messagebox.showwarning("안내","내보낼 데이터가 없습니다."); return
        p=filedialog.asksaveasfilename(defaultextension=".csv",filetypes=[("CSV","*.csv"),("All","*.*")])
        if not p:return
        with open(p,"w",newline="",encoding="utf-8-sig") as f:
            w=csv.writer(f)
            w.writerow(["ID","급여월","성명","부서","직급","기본급","연장수당","상여","수당","총지급","총공제","실지급","등록시각"])
            for r in rows:
                w.writerow([r["id"],r["pay_month"],r["name"],r["dept"],r["pos"],r["base_pay"],r["overtime_pay"],r["bonus"],r["allowances"],r["gross"],r["total_deduct"],r["net"],r["created_at"]])
        messagebox.showinfo("완료",f"CSV 저장: {p}")
    def add_leave(self):
        try:
            emp_id=parse_emp_id(self.lv["emp"].get())
            self.db.add_leave(emp_id, self.lv["date"].get().strip(), to_num(self.lv["days"].get(),1), self.lv["note"].get().strip())
            self.refresh_leave()
            messagebox.showinfo("완료","연차 사용 등록 완료")
        except Exception as e:
            messagebox.showerror("오류",f"등록 실패: {e}")

    def update_grant(self):
        try:
            emp_id=parse_emp_id(self.lv["u_emp"].get())
            grant=to_num(self.lv["u_days"].get(),15)
            e=[x for x in self.db.employees() if x["id"]==emp_id][0]
            self.db.update_employee(emp_id, {
                "name":e["name"],"dept":e["dept"] or "","pos":e["pos"] or "","emp_type":e["emp_type"],
                "hourly":e["hourly"],"monthly":e["monthly"],"start_date":e["start_date"] or "","leave_grant":grant
            })
            self.refresh_all()
        except Exception as e:
            messagebox.showerror("오류",f"업데이트 실패: {e}")

    def refresh_leave(self):
        for i in self.leave_tree.get_children(): self.leave_tree.delete(i)
        for r in self.db.leave_summary():
            self.leave_tree.insert("",tk.END,values=(r["id"],r["name"],r["dept"] or "",r["pos"] or "",f'{r["leave_grant"]:.1f}',f'{r["used"]:.1f}',f'{r["remain"]:.1f}'))

    def refresh_all(self):
        self.refresh_emp_table()
        self.refresh_ledger()
        self.refresh_leave()


if __name__ == "__main__":
    App().mainloop()
