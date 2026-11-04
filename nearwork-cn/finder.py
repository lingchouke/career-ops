"""Three screens: search preferences, openings, and evidence for one opening."""
import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText

from assessment import assess, suggestion
from discovery import ALL, title_cn
from job_store import search, status
from sync_jobs import synchronize
from nearwork import read_resume


class JobFinder:
    def __init__(self,root):
        self.root=root
        root.title("近职 · 找工作")
        root.geometry("960x710")
        root.minsize(710,560)
        self.resume=""
        self.results=[]
        self.selected=None
        self.messages=queue.Queue()
        self.busy=False
        style=ttk.Style()
        style.theme_use("clam")
        style.configure(".",font=("Microsoft YaHei UI",10),background="#f5f7f6",foreground="#233d39")
        style.configure("TButton",padding=(14,8))
        style.configure("Go.TButton",font=("Microsoft YaHei UI",12,"bold"),background="#126653",foreground="white")
        style.map("Go.TButton",background=[("disabled","#708c85"),("active","#115647")])
        style.configure("Title.TLabel",font=("Microsoft YaHei UI",21,"bold"))
        style.configure("Field.TLabel",font=("Microsoft YaHei UI",11,"bold"))
        style.configure("Muted.TLabel",foreground="#516b64")
        style.configure("Treeview",background="white",fieldbackground="white",rowheight=37)
        style.configure("Treeview.Heading",font=("Microsoft YaHei UI",10,"bold"),padding=7)
        style.map("Treeview",background=[("selected","#d3e9df")],foreground=[("selected","#143a30")])
        outer=ttk.Frame(root,padding=(26,16))
        outer.pack(fill="both",expand=True)
        self.trail=tk.StringVar()
        ttk.Label(outer,textvariable=self.trail,style="Muted.TLabel").pack(anchor="w",pady=(0,12))
        self.body=ttk.Frame(outer)
        self.body.pack(fill="both",expand=True)
        self.body.rowconfigure(0,weight=1)
        self.body.columnconfigure(0,weight=1)
        self.pages=[ttk.Frame(self.body) for _ in range(3)]
        for page in self.pages:
            page.grid(row=0,column=0,sticky="nsew")
        self.city=tk.StringVar(value="上海")
        self.kind=tk.StringVar(value=ALL)
        self.keyword=tk.StringVar()
        self.file=tk.StringVar(value="可选择文字版 PDF、Word 或文本文件")
        self.notice=tk.StringVar()
        self.library=tk.StringVar()
        self.create_form()
        self.create_list()
        self.create_analysis()
        self.refresh_library()
        self.show(0)

    def show(self,index):
        self.trail.set("近职     /     "+("第 1 步  填写求职条件","第 2 步  选择岗位","第 3 步  查看分析")[index])
        self.pages[index].tkraise()
        if index==1:
            self.table.focus_set()

    def create_form(self):
        page=self.pages[0]
        ttk.Label(page,text="你想找什么工作？",style="Title.TLabel").pack(anchor="w",pady=(6,8))
        ttk.Label(page,text="选一份简历，再告诉我们你想去哪里工作。",style="Muted.TLabel").pack(anchor="w")
        row=ttk.Frame(page)
        row.pack(anchor="w",pady=(18,12))
        self.upload=ttk.Button(row,text="上传简历",command=self.choose_file)
        self.upload.pack(side="left")
        ttk.Label(row,textvariable=self.file,style="Muted.TLabel",wraplength=460).pack(side="left",padx=12)
        form=ttk.Frame(page)
        form.pack(fill="x",pady=4)
        form.columnconfigure(1,weight=1)
        for i,label in enumerate(("工作城市","公司类型","岗位关键词")):
            ttk.Label(form,text=label,style="Field.TLabel").grid(row=i,column=0,padx=(0,18),pady=9,sticky="w")
        self.citybox=ttk.Combobox(form,textvariable=self.city,values=("上海","北京","深圳","广州","杭州","成都","苏州","香港"),width=24)
        self.citybox.grid(row=0,column=1,sticky="w")
        self.kinds=ttk.Combobox(form,textvariable=self.kind,values=[ALL],state="readonly",width=24)
        self.kinds.grid(row=1,column=1,sticky="w")
        self.words=ttk.Entry(form,textvariable=self.keyword,width=27)
        self.words.grid(row=2,column=1,sticky="w")
        ttk.Label(form,text="如「机械工程师」。留空可看所有岗位。",style="Muted.TLabel").grid(row=3,column=1,sticky="w")
        actions=ttk.Frame(page)
        actions.pack(anchor="w",pady=(18,8))
        self.go=ttk.Button(actions,text="查找岗位",style="Go.TButton",command=self.find)
        self.go.pack(side="left",ipadx=18)
        self.paste=ttk.Button(actions,text="粘贴岗位描述",command=self.paste_job)
        self.paste.pack(side="left",padx=10)
        data=ttk.Frame(page)
        data.pack(anchor="w",pady=5)
        self.update_jobs=ttk.Button(data,text="更新岗位数据",command=self.update_library)
        self.update_jobs.pack(side="left")
        ttk.Label(data,textvariable=self.library,style="Muted.TLabel",wraplength=430).pack(side="left",padx=10)
        ttk.Label(page,textvariable=self.notice,wraplength=620,style="Muted.TLabel").pack(anchor="w",pady=5)
        self.words.bind("<Return>",lambda _:self.find())

    def choose_file(self):
        path=filedialog.askopenfilename(title="选择你的简历",filetypes=[("简历","*.pdf *.docx *.txt *.md")])
        if not path:
            return
        try:
            text=read_resume(path)
        except Exception:
            self.resume=""
            self.file.set("请重新选择简历")
            self.notice.set("没能读出简历文字，请选择可以复制文字的 PDF、Word 或文本文件。")
            return
        self.resume=text
        self.file.set("已选择  "+Path(path).name)
        self.notice.set("简历已就绪。")

    def refresh_library(self):
        try:
            count, updated, kinds=status()
        except Exception:
            self.library.set("暂时无法读取本机的岗位。仍可粘贴岗位描述进行分析。")
            return
        self.kinds.configure(values=[ALL]+kinds)
        if self.kind.get() not in [ALL]+kinds:
            self.kind.set(ALL)
        self.library.set(f"本机有 {count} 个岗位 · 最近更新 {updated[:16].replace('T',' ')}"
                         if updated else "首次使用请点「更新岗位数据」。之后可以离线查找。")

    def set_busy(self, busy):
        self.busy=busy
        for w in (self.upload,self.go,self.citybox,self.kinds,self.words,self.update_jobs,self.paste):
            w.state(["disabled" if busy else "!disabled"])

    def update_library(self):
        if self.busy:
            return
        self.set_busy(True)
        self.notice.set("正在从企业招聘页下载岗位，请稍候…")
        def work():
            try:
                updated,failed=synchronize()
                message=f"已更新 {len(updated)} 家公司的岗位。"
                if failed:
                    message+=" 未能更新："+"、".join(failed)+"。如有上次的岗位，仍可查找。"
            except Exception:
                message="未能完成更新，请检查公司清单和本机岗位文件后重试。"
            self.messages.put(message)
        threading.Thread(target=work,daemon=True).start()
        self.root.after(100,self.finish_update)

    def finish_update(self):
        try:
            message=self.messages.get_nowait()
        except queue.Empty:
            self.root.after(100,self.finish_update)
            return
        self.set_busy(False)
        self.refresh_library()
        self.notice.set(message)

    def paste_job(self):
        if not self.resume:
            self.notice.set("请先上传简历，再粘贴岗位描述。")
            return
        window=tk.Toplevel(self.root)
        window.title("粘贴岗位描述")
        window.transient(self.root)
        form=ttk.Frame(window,padding=16)
        form.pack(fill="both",expand=True)
        ttk.Label(form,text="岗位名称（选填）").pack(anchor="w")
        name=ttk.Entry(form)
        name.pack(fill="x",pady=(3,10))
        ttk.Label(form,text="粘贴招聘信息，尽量包含岗位职责和任职要求。").pack(anchor="w")
        body=ScrolledText(form,width=58,height=12,wrap="word",font=("Microsoft YaHei UI",11))
        body.pack(fill="both",expand=True,pady=6)
        hint=ttk.Label(form,text="只用于本次分析，不会加入岗位库。")
        hint.pack(anchor="w")
        def submit():
            desc=body.get("1.0","end").strip()
            if not desc:
                hint.configure(text="请先粘贴岗位描述。")
                return
            title=name.get().strip() or "粘贴的岗位"
            job={"岗位":title,"岗位要求":desc,"公司":"","城市":"","来源":""}
            result=assess(self.resume,job)
            window.destroy()
            self.display_analysis(job,title,result,manual=True)
        ttk.Button(form,text="对照我的简历",command=submit).pack(anchor="e",pady=(8,0))
        window.grab_set()
        body.focus_set()

    def create_list(self):
        page=self.pages[1]
        head=ttk.Frame(page)
        head.pack(fill="x")
        self.list_title=tk.StringVar()
        ttk.Label(head,textvariable=self.list_title,style="Title.TLabel").pack(side="left")
        ttk.Button(head,text="返回修改条件",command=lambda:self.show(0)).pack(side="right")
        self.info=tk.StringVar()
        ttk.Label(page,textvariable=self.info,wraplength=650,style="Muted.TLabel").pack(anchor="w",pady=(7,10))
        container=ttk.Frame(page)
        container.pack(fill="both",expand=True)
        self.table=ttk.Treeview(container,show="headings",columns=("job","company","place","grade"),selectmode="browse")
        for k,n,w in (("job","岗位",290),("company","公司",145),("place","地点",105),("grade","匹配度",80)):
            self.table.heading(k,text=n)
            self.table.column(k,width=w,minwidth=65,stretch=True)
        scroll=ttk.Scrollbar(container,command=self.table.yview)
        scroll.pack(side="right",fill="y")
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(fill="both",expand=True)
        self.table.bind("<ButtonRelease-1>",self.click_row)
        self.table.bind("<Return>",lambda _:self.open_selected())

    def find(self):
        if self.busy:
            return
        city=self.city.get().strip().removesuffix("市")
        if not self.resume or not city:
            self.notice.set("请先上传简历。" if not self.resume else "请填写想工作的城市。")
            return
        kind,word,resume=self.kind.get(),self.keyword.get().strip(),self.resume
        self.set_busy(True)
        self.notice.set("正在查找本机岗位，并逐个对照你的简历…")
        def work():
            try:
                jobs=search(city,kind,word)
                entries=[]
                for j in jobs:
                    label=title_cn(j["岗位"])
                    entries.append((j,label,assess(resume,j)))
                entries.sort(key=lambda e:(("高","中","低").index(e[2]["grade"]),not bool(e[2]["facts"]),e[1],e[0]["公司"]))
                self.messages.put((entries,None))
            except Exception:
                self.messages.put(([],"未能读取本机岗位，请返回重试。"))
        threading.Thread(target=work,daemon=True).start()
        self.root.after(100,lambda:self.finish(city,kind,word))

    def finish(self,city,kind,word):
        try:
            entries,error=self.messages.get_nowait()
        except queue.Empty:
            self.root.after(100,lambda:self.finish(city,kind,word))
            return
        self.set_busy(False)
        if error:
            self.notice.set(error)
            return
        self.notice.set("")
        self.results=entries
        self.table.delete(*self.table.get_children())
        for i,(j,label,r) in enumerate(entries):
            self.table.insert("","end",iid=str(i),values=(label,j["公司"],j.get("地址") or j["城市"],r["grade"]))
        self.list_title.set(f"找到 {len(entries)} 个岗位")
        scope=" · ".join(x for x in (city,kind,word) if x)
        note="点一个岗位查看分析。" if entries else "本机没有符合条件的岗位。可以返回修改条件、更新岗位数据，或粘贴岗位描述。"
        self.info.set(scope+"\n"+note)
        self.show(1)

    def click_row(self,event):
        row=self.table.identify_row(event.y)
        if row and self.table.identify_region(event.x,event.y) in ("tree","cell"):
            self.table.selection_set(row)
            self.open_selected()

    def create_analysis(self):
        page=self.pages[2]
        row=ttk.Frame(page)
        row.pack(fill="x",pady=(0,8))
        self.back=ttk.Button(row)
        self.back.pack(side="left")
        self.source_button=ttk.Button(row,text="查看招聘方原文",command=self.original)
        self.detail=ScrolledText(page,wrap="word",relief="flat",font=("Microsoft YaHei UI",11),foreground="#273f39",
                                 padx=18,pady=12,background="white",state="disabled",cursor="arrow")
        self.detail.pack(fill="both",expand=True)
        for tag,size,color in (("高",20,"#12644e"),("中",20,"#786017"),("低",20,"#a33b28"),
                               ("heading",13,"#184d40"),("item",11,"#273f39")):
            self.detail.tag_configure(tag,font=("Microsoft YaHei UI",size,"bold"),foreground=color,spacing1=7,spacing3=4)
        self.detail.tag_configure("proof",foreground="#49675e",lmargin1=14,lmargin2=14,spacing3=6)

    def open_selected(self):
        selection=self.table.selection()
        if not selection:
            return
        j,label,r=self.results[int(selection[0])]
        self.display_analysis(j,label,r)

    def display_analysis(self,j,label,r,manual=False):
        self.back.configure(text="‹ 返回求职条件" if manual else "‹ 返回岗位列表",
                            command=lambda:self.show(0 if manual else 1))
        if manual:
            self.source_button.pack_forget()
        else:
            self.source_button.pack(side="right")
        self.selected=j
        box=self.detail
        box.configure(state="normal")
        box.delete("1.0","end")
        box.insert("end","匹配度"+r["grade"]+"\n",r["grade"])
        box.insert("end","  ·  ".join(filter(None,(label,j['公司'],j['城市'])))+"\n","item")
        box.insert("end",r["reason"]+"\n")
        box.insert("end","已满足项\n","heading")
        if not r["facts"]:
            box.insert("end","暂未找到足以支持这个岗位的简历原文。\n")
        for fact,quote in r["facts"]:
            box.insert("end","• "+fact+"\n","item")
            box.insert("end","简历原文：“"+quote+"”\n","proof")
        box.insert("end","欠缺项与建议\n","heading")
        box.insert("end","下列项目是简历里尚未证实的部分，也可能是你做过但没写清楚。\n")
        for key,heading in (("必须","必须具备"),("加分","加分条件"),("其他","岗位还提到（未说明是否必须）")):
            items=r["missing"][key]
            if key=="其他" and not items:
                continue
            box.insert("end",heading+"\n","heading")
            if not items:
                box.insert("end","没有识别到尚待补充的此类条件。\n")
            for item in items:
                box.insert("end","• "+item+"\n","item")
                box.insert("end","建议："+suggestion(item)+"\n","proof")
        box.configure(state="disabled")
        box.yview_moveto(0)
        self.show(2)

    def original(self):
        if self.selected:
            url=self.selected.get("来源","")
            if url.startswith("https://"):
                webbrowser.open(url)
