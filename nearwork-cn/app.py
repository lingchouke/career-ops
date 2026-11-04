import os
import json
import subprocess
import queue
import threading
import time as clock
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from nearwork import compare, fetch_board, read_jobs, read_resume, transit


def career_ops(action, payload=None):
    command = ["node", str(Path(__file__).with_name("bridge.mjs")), action]
    run = subprocess.run(command, input=json.dumps(payload,ensure_ascii=False),
                         capture_output=True, encoding="utf-8", timeout=30, shell=False)
    if run.returncode:
        raise ValueError(run.stderr.strip() or "Career-Ops 调用失败")
    return json.loads(run.stdout)


DEMO_CV = "负责门店销售周报，汇总每日客流和销售额。\n维护会员群，解答顾客咨询。\n参与两次线下促销。"
DEMO_JOBS = [
    ("会员运营助理", "示例门店 A", "上海市静安区南京西路 1000 号", "维护会员运营活动\n参与销售分析\n整理 Excel 周报", 32),
    ("门店活动专员", "示例门店 B", "上海市浦东新区世纪大道 100 号", "参与活动策划\n负责客户服务", 58),
    ("区域储备店长", "示例门店 C", "", "负责库存管理\n负责新人培训\n必须持有健康证", None),
]


def save_text(name, content):
    path = filedialog.asksaveasfilename(initialfile=name, defaultextension=".md", filetypes=[("Markdown", "*.md")])
    if path:
        Path(path).write_text(content, encoding="utf-8")


class Nearwork:
    def __init__(self, root):
        self.root = root
        root.title("近职 · 本地求职助手")
        root.geometry("1080x760")
        root.minsize(800, 560)
        style = ttk.Style()
        style.configure("TLabel", font=("Microsoft YaHei UI", 10))
        style.configure("TButton", padding=(9, 5))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 19, "bold"), foreground="#16564e")
        self.jobs, self.routes = [], {}
        self.events = queue.Queue()
        self.busy = False
        self.status = tk.StringVar(value="选择「载入示例」体验，或先在「简历与通勤」中设置自己的条件。")
        outer = ttk.Frame(root, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="近职   /   本地求职助手", style="Title.TLabel").pack(anchor="w")
        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill="both", expand=True, pady=10)
        self.search, self.profile = [ttk.Frame(self.tabs, padding=12) for _ in range(2)]
        self.tabs.add(self.search, text="  工作机会  ")
        self.tabs.add(self.profile, text="  简历与通勤  ")
        self.inputs = {}
        for i, (label, default) in enumerate([
            ("城市", "上海"), ("出发站点或门牌号", ""), ("出发日期", str(date.today()+timedelta(days=1))),
            ("出发时间", "08:00"), ("最长分钟数", "45"), ("高德 Web 服务 Key", os.getenv("AMAP_WEB_KEY", ""))]):
            ttk.Label(self.profile, text=label).grid(row=i//2, column=(i%2)*2, sticky="w", pady=5)
            var = self.inputs[label] = tk.StringVar(value=default)
            ttk.Entry(self.profile, textvariable=var, show="*" if "Key" in label else "").grid(
                row=i//2, column=(i%2)*2+1, sticky="ew", padx=8)
        self.profile.columnconfigure(1, weight=1)
        self.profile.columnconfigure(3, weight=1)
        ttk.Label(self.profile, text="简历正文   ·   可直接粘贴；仅在本机处理").grid(row=3,columnspan=4,sticky="w",pady=8)
        self.cv = ScrolledText(self.profile, height=12, wrap="word", font=("Microsoft YaHei UI", 11))
        self.cv.grid(row=4,columnspan=4,sticky="nsew")
        self.profile.rowconfigure(4,weight=1)
        controls = ttk.Frame(self.profile)
        controls.grid(row=5,columnspan=4,sticky="w",pady=8)
        self.button(controls, "导入简历文件", self.import_cv)
        self.button(controls, "读取 Career-Ops 主简历", self.load_master)
        self.button(controls, "应用条件，查看岗位", self.apply_profile)
        bar = ttk.Frame(self.search)
        bar.pack(fill="x")
        for label, fn in [("载入示例",self.demo),("导入岗位 CSV",self.import_jobs),("粘贴一个岗位",self.add_job),
                          ("读取企业招聘页",self.board),("清空列表",self.clear)]:
            self.button(bar,label,fn)
        filters = ttk.Frame(self.search)
        filters.pack(fill="x",pady=8)
        ttk.Label(filters,text="通勤范围").pack(side="left")
        self.filter = tk.StringVar(value="全部")
        menu = ttk.Combobox(filters,textvariable=self.filter,values=("全部","范围内","待确认","超范围"),state="readonly",width=10)
        menu.pack(side="left", padx=6)
        menu.bind("<<ComboboxSelected>>",lambda e:self.refresh())
        ttk.Label(filters,text="岗位或公司").pack(side="left")
        self.query = tk.StringVar()
        ttk.Entry(filters,textvariable=self.query,width=20).pack(side="left",padx=6)
        self.query.trace_add("write",lambda *_: self.refresh())
        self.button(filters,"批量查同城通勤",self.batch_routes)
        self.button(filters,"加入 Career-Ops 评估",self.enqueue)
        pane = ttk.Panedwindow(self.search,orient="horizontal")
        pane.pack(fill="both",expand=True)
        left, right = ttk.Frame(pane), ttk.Frame(pane)
        pane.add(left,weight=2)
        pane.add(right,weight=3)
        self.list = tk.Listbox(left,activestyle="none",exportselection=False,width=31,font=("Microsoft YaHei UI",10))
        self.list.pack(fill="both",expand=True)
        self.list.bind("<<ListboxSelect>>",lambda e:self.detail())
        self.output = ScrolledText(right,wrap="word",font=("Microsoft YaHei UI",10),padx=10,pady=8,state="disabled")
        self.output.pack(fill="both",expand=True)
        actions = ttk.Frame(self.search)
        actions.pack(fill="x",pady=(8,0))
        for label, fn in [("确认门店地址", self.address),("查公交通勤",self.route),("记录已核实分钟数",self.manual),
                          ("补充简历事实",self.add_fact),("导出岗位对照",self.export)]:
            self.button(actions,label,fn)
        ttk.Label(outer,textvariable=self.status,wraplength=900).pack(anchor="w")
        self.visible = []
        self.root.after(150,self.poll)

    def button(self, parent, label, action):
        def guarded():
            try:
                action()
            except Exception as exc:
                messagebox.showerror("未完成",str(exc),parent=self.root)
        ttk.Button(parent,text=label,command=guarded).pack(side="left",padx=(0,4))

    def scope(self):
        return tuple(self.inputs[k].get().strip() for k in ("城市","出发站点或门牌号","出发日期","出发时间"))

    def valid_scope(self):
        city,origin,day,time = self.scope()
        if not city or not origin:
            raise ValueError("请先在「简历与通勤」填写城市和出发地点。")
        datetime.strptime(day+" "+time,"%Y-%m-%d %H:%M")
        return city,origin,day,time

    def limit(self):
        val = self.inputs["最长分钟数"].get()
        if not val.isdigit() or not 1 <= int(val) <= 600:
            raise ValueError("最长通勤时间应为 1 到 600 分钟。")
        return int(val)

    def apply_profile(self):
        self.limit()
        self.refresh()
        self.tabs.select(self.search)
        self.status.set("已按当前城市、简历和通勤条件重新匹配。")

    def import_cv(self):
        path = filedialog.askopenfilename(filetypes=[("简历","*.pdf *.docx *.md *.txt")])
        if path:
            text = read_resume(path)
            self.cv.delete("1.0","end")
            self.cv.insert("1.0",text)
            self.status.set("简历已读取，请检查正文，再应用条件。")

    def load_master(self):
        text = career_ops("profile")["cv"]
        if text is None:
            raise ValueError("当前 Career-Ops 数据目录还没有 cv.md，可先导入自己的简历。")
        self.cv.delete("1.0","end")
        self.cv.insert("1.0",text)
        self.status.set("已读取 Career-Ops 当前数据目录的 cv.md。")

    def enqueue(self):
        job = self.selected()
        if job.get("来源") == "虚构演示，非招聘信息":
            raise ValueError("示例岗位仅供体验。请选自己的真实岗位，再加入评估。")
        resume = self.cv.get("1.0","end").strip()
        if not resume:
            raise ValueError("请先导入或读取主简历。")
        create = career_ops("profile")["cv"] is None
        if create and not messagebox.askyesno("建立主简历","将当前正文保存为 Career-Ops 的 cv.md，用于后续岗位评估？"):
            return
        route = self.routes.get(self.route_id(job))
        commute = {"city":job["城市"], "maxMinutes":self.limit(),
                   "minutes":route[0] if route else None, "evidence":route[1] if route else None}
        result = career_ops("enqueue",{"job":job,"resume":resume,"createCV":create,"commute":commute})
        note = "技能提取不完整，需结合原文评估。" if result["warning"] else ""
        self.status.set("已加入 Career-Ops 原生收件箱。"+note+"在本仓库的 AI 会话运行 /career-ops agent-inbox 继续。")

    def demo(self):
        if self.jobs or self.cv.get("1.0","end").strip():
            if not messagebox.askyesno("载入示例","替换当前窗口中的简历、岗位和通勤记录？"):
                return
        self.jobs, self.routes = [], {}
        self.cv.delete("1.0","end")
        self.cv.insert("1.0",DEMO_CV)
        self.inputs["城市"].set("上海")
        self.inputs["出发站点或门牌号"].set("静安寺地铁站")
        self.inputs["最长分钟数"].set("45")
        self.query.set("")
        self.filter.set("全部")
        for title,company,address,jd,minutes in DEMO_JOBS:
            job = {"岗位":title,"公司":company,"城市":"上海","地址":address,"岗位要求":jd,"来源":"虚构演示，非招聘信息"}
            self.jobs.append(job)
            if minutes:
                self.routes[self.route_id(job)] = (minutes,"示例耗时，非地图实测")
        self.refresh()
        self.status.set("示例包含范围内、超范围和门店待确认各一个岗位。")

    def clear(self):
        if self.jobs and messagebox.askyesno("清空列表","清空当前窗口中的岗位和路线？"):
            self.jobs.clear()
            self.routes.clear()
            self.refresh()

    def route_id(self, job):
        return (id(job),job.get("地址",""),*self.scope())

    def import_jobs(self):
        path = filedialog.askopenfilename(filetypes=[("岗位表","*.csv")])
        if path:
            rows = read_jobs(path)
            self.jobs.extend(rows)
            self.refresh()
            self.status.set(f"已导入 {len(rows)} 条岗位，列表只显示当前城市。")

    def add_job(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("加入一个岗位")
        entries = {}
        for k in ("岗位","公司","城市","地址","来源"):
            ttk.Label(dialog,text=k).pack(anchor="w",padx=12)
            entries[k] = ttk.Entry(dialog,width=64)
            entries[k].pack(fill="x",padx=12)
        entries["城市"].insert(0,self.scope()[0])
        ttk.Label(dialog,text="岗位要求（每项一行）").pack(anchor="w",padx=12)
        jd = ScrolledText(dialog,width=60,height=10)
        jd.pack(padx=12)
        def add():
            job = {k:e.get().strip() for k,e in entries.items()}
            job["岗位要求"] = jd.get("1.0","end").strip()
            if not all(job[k] for k in ("岗位","公司","城市","岗位要求")):
                raise ValueError("请填写岗位、公司、城市和岗位要求。")
            self.jobs.append(job)
            dialog.destroy()
            self.refresh()
        self.button(dialog,"加入列表",add)

    def run_network(self, label, work, done):
        if self.busy:
            raise ValueError("请等待当前查询完成。")
        self.busy = True
        self.status.set(label)
        def worker():
            try:
                self.events.put((done,work(),None))
            except Exception as exc:
                self.events.put((done,None,str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def poll(self):
        try:
            done,value,error = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            if error:
                self.status.set("查询未完成 · "+error)
            else:
                done(value)
        self.root.after(150,self.poll)

    def board(self):
        token = simpledialog.askstring("企业公开招聘页","Greenhouse 企业标识；将读取该企业发布的岗位并按当前城市筛选。",initialvalue="miqdigital")
        if not token:
            return
        city = self.scope()[0]
        def done(rows):
            # Replace this board's city snapshot so closed jobs disappear on refresh.
            removed = {id(j) for j in self.jobs if j.get("_board") == (token,city)}
            self.routes = {k:v for k,v in self.routes.items() if k[0] not in removed}
            self.jobs[:] = [j for j in self.jobs if id(j) not in removed]
            for j in rows:
                j["_board"] = (token,city)
            self.jobs.extend(rows)
            self.refresh()
            self.status.set(f"已刷新 {token} 在 {city} 的 {len(rows)} 条职位。具体办公地点请核实。")
        self.run_network("正在读取企业公开职位…",lambda:fetch_board(token.strip(),city),done)

    def selected(self):
        index = self.list.curselection()
        if not index:
            raise ValueError("请先选择一个岗位。")
        return self.visible[index[0]]

    def summary(self,job,limit):
        route = self.routes.get(self.route_id(job))
        if not route:
            return "待确认","通勤待确认"
        return ("范围内" if route[0]<=limit else "超范围"),f"{route[0]} 分钟"

    def refresh(self,prefer=None):
        try:
            limit = self.limit()
        except ValueError:
            self.status.set("请在简历与通勤中设置有效的分钟数。")
            return
        city = self.scope()[0].removesuffix("市")
        cv = self.cv.get("1.0","end")
        ranked = []
        for job in self.jobs:
            if city and city.casefold()!=job["城市"].removesuffix("市").casefold():
                continue
            if self.query.get().casefold() not in (job["岗位"]+" "+job["公司"]).casefold():
                continue
            group,label = self.summary(job,limit)
            if self.filter.get() not in ("全部",group):
                continue
            result = compare(cv,job["岗位要求"])
            evidence = sum(r[1] in ("简历有相关原文","可能迁移") for r in result)
            blocked = any(r[4] and r[1]=="简历注明差距" for r in result)
            ranked.append((("范围内","待确认","超范围").index(group),blocked,-evidence/max(1,len(result)),job,label))
        ranked.sort(key=lambda r:r[:3])
        self.visible = [r[3] for r in ranked]
        self.list.delete(0,"end")
        for _,__,___,j,label in ranked:
            self.list.insert("end",f"{label}  ·  {j['岗位']}")
        if self.visible:
            idx = next((i for i,j in enumerate(self.visible) if j is prefer),0)
            self.list.selection_set(idx)
            self.list.see(idx)
        self.detail()

    def report(self,job):
        route = self.routes.get(self.route_id(job))
        where = job.get("地址") or "实际工作地址待确认"
        lines = [job["岗位"]+"  /  "+job["公司"],job["城市"]+" · "+where,
                 "来源："+(job.get("来源") or "手动录入，状态待核实")]
        if job.get("读取时间"):
            lines.append("招聘页读取于 "+job["读取时间"])
        if route:
            lines.append(f"从 {self.scope()[1]} 出发 · {self.scope()[2]} {self.scope()[3]} · {route[0]} 分钟 · {route[1]}")
        else:
            lines.append("通勤待确认。核实上班地址后可查路线或记录实测耗时。")
        cv = self.cv.get("1.0","end").strip()
        lines.extend(["","岗位要求与简历对照" if cv else "请先导入简历。以下是原始岗位描述。"])
        if cv:
            for need,state,quote,tip,hard in compare(cv,job["岗位要求"]):
                lines.extend(["",("【硬性条件】" if hard else "")+need,state+(" · “"+quote+"”" if quote else ""),tip])
        else:
            lines.append(job["岗位要求"])
        return "\n".join(lines)

    def detail(self):
        content = self.report(self.selected()) if self.list.curselection() else "当前条件下没有岗位。可调整筛选、导入岗位，或载入示例。"
        self.output.configure(state="normal")
        self.output.delete("1.0","end")
        self.output.insert("1.0",content)
        self.output.configure(state="disabled")

    def address(self):
        job = self.selected()
        val = simpledialog.askstring("确认实际工作地址","填写已核实的实际门店或办公地址",initialvalue=job.get("地址",""))
        if val is not None:
            job["地址"] = val.strip()
            self.refresh(job)

    def route(self):
        job = self.selected()
        scope = self.valid_scope()
        key = self.inputs["高德 Web 服务 Key"].get().strip()
        if not key:
            raise ValueError("请在「简历与通勤」填写高德 Web 服务 Key，或手动记录已核实的分钟数。")
        ident = self.route_id(job)
        address = job.get("地址","")
        def done(value):
            if job in self.jobs:
                self.routes[ident] = value
            self.refresh(job)
            self.status.set("公交方案已返回；耗时为该日期与时刻的规划估算。")
        city,origin,day,time = scope
        self.run_network("正在向高德查询起终点和出发时刻…",lambda:transit(key,city,origin,address,day,time),done)

    def manual(self):
        job = self.selected()
        city,origin,day,time = self.valid_scope()
        if not job.get("地址"):
            raise ValueError("请先确认具体工作地址。")
        mins = simpledialog.askinteger("记录通勤",f"{day} {time}\n{origin} → {job['地址']}\n输入地图或实测的单程分钟数",minvalue=1,maxvalue=600)
        if mins:
            self.routes[self.route_id(job)] = (mins,"用户核实")
            self.refresh(job)

    def batch_routes(self):
        city, origin, day, time = self.valid_scope()
        key = self.inputs["高德 Web 服务 Key"].get().strip()
        if not key:
            raise ValueError("请先在「简历与通勤」填写高德 Web 服务 Key。")
        targets = [(self.route_id(j),j["地址"]) for j in self.jobs
                   if j["城市"].removesuffix("市")==city.removesuffix("市") and j.get("地址")
                   and self.route_id(j) not in self.routes]
        if not targets:
            self.status.set("没有待查询的同城地址。仅标注城市的岗位需要先确认门店。")
            return
        addresses = list(dict.fromkeys(a for _,a in targets))[:20]
        def work():
            results,errors = {},[]
            for addr in addresses:
                try:
                    results[addr] = transit(key,city,origin,addr,day,time)
                except Exception as exc:
                    errors.append(str(exc))
                clock.sleep(0.4)
            return results,errors
        def done(value):
            results,errors = value
            valid = {id(j) for j in self.jobs}
            for ident,addr in targets:
                if ident[0] in valid and addr in results:
                    self.routes[ident] = results[addr]
            self.refresh()
            self.status.set(f"已查询 {len(addresses)} 个地址，得到 {len(results)} 条路线。"+
                            ("未确认示例："+errors[0] if errors else ""))
        self.run_network(f"正在查询 {len(addresses)} 个地址（每批最多 20 个）…",work,done)

    def add_fact(self):
        job = self.selected()
        fact = simpledialog.askstring("补充简历事实","根据右侧追问，补充你本人做过的事情。将加入本次简历重新比对。")
        if fact and fact.strip():
            self.cv.insert("end","\n"+fact.strip())
            self.refresh(job)

    def export(self):
        job = self.selected()
        save_text("岗位与简历对照.md",self.report(job)+"\n\n## 原始 JD\n"+job["岗位要求"]+"\n")


if __name__ == "__main__":
    root = tk.Tk()
    Nearwork(root)
    root.mainloop()
