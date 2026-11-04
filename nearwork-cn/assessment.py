"""Conservative, local screening. Each positive finding quotes the candidate."""
import re
from nearwork import ALIASES, META, NEGATIVE, OTHER, clauses, mentions
from discovery import topic

SOFTWARE = ("SolidWorks","Creo","ProE","CAD","AutoCAD","Excel","SQL","Python","Power BI","Photoshop")


FIELDS = {
    "机械与设备": ("mechanical","fixture","equipment","结构设计","机械","夹具","工装","设备设计","solidworks","proe","设备开发"),
    "电池与材料": ("battery","cell","cathode","material engineer","电池","电芯","电极","材料工程"),
    "芯片与电子": ("hardware","semiconductor","circuit","pcb","electrical","芯片","硬件","电路","电气"),
    "软件开发": ("software engineer","software development","软件开发","软件工程","程序开发"),
    "广告营销": ("programmatic","advertising","ad operations","seo","sem","trader","广告","投放","搜索营销"),
    "产品管理": ("product manager","product lead","产品经理","产品负责人","产品管理"),
    "销售与客户": ("account manager","sales","business development","销售","商务拓展","客户经理"),
    "人力资源": ("site hr","human resources","recruitment","人力资源","招聘专员"),
    "技术支持": ("technical support","applications engineer","技术支持","应用工程师"),
}
OPTIONAL = re.compile(r"优先|加分|更佳|preferred|nice[- ]to[- ]have|a plus|desirable|bonus",re.I)
MANDATORY = re.compile(r"必须|须持|必备|硬性|至少|must\b|required\b|at least",re.I)
REQ_HEAD = re.compile(r"required skills|requirements|qualifications|minimum qualifications|what you.ll bring|岗位要求|任职要求|任职资格|必备条件|必须项",re.I)
OPT_HEAD = re.compile(r"加分(?:项|条件)?|优先条件|preferred qualifications|nice[- ]to[- ]have|bonus(?: points)?",re.I)
DUTY_HEAD = re.compile(r"(?:job )?responsibilities|what you.ll do|岗位职责|工作职责|工作内容",re.I)
DENY = re.compile(r"没有|未曾|未取得|不会|缺乏|不具备|无.{0,6}(?:经验|基础)|无.{0,5}证|尚未|未使用|不熟练|\bno experience|\bnever\b|\bnot (?:yet |proficient|familiar)|\bunfamiliar",re.I)
ASPIRATION = re.compile(r"求职意向|目标岗位|希望从事|想转|正在学|计划学习|想学")


def conditions(jd):
    entries = clauses(re.sub(r"(岗位要求|任职要求|任职资格|加分项|岗位职责|工作职责)[:：]",r"\n\1\n",jd))
    section = None if any(REQ_HEAD.fullmatch(x.rstrip(":：")) or DUTY_HEAD.fullmatch(x.rstrip(":："))
                          or OPT_HEAD.fullmatch(x.rstrip(":：")) for x in entries) else "未注明"
    for text in entries:
        h = text.strip("*# :：")
        if REQ_HEAD.fullmatch(h):
            section = "必须"
        elif OPT_HEAD.fullmatch(h):
            section = "加分"
        elif DUTY_HEAD.fullmatch(h):
            section = "职责"
        elif OTHER.fullmatch(h):
            section = None
        elif section and not META.match(text):
            priority = "加分" if OPTIONAL.search(text) else "必须" if MANDATORY.search(text) else section
            yield text, priority


def field_hits(text):
    return {name for name,terms in FIELDS.items() if any(mentions(text,t) for t in terms)}


def evidence_for(need, lines):
    # Only call the entire requirement satisfied on a literal statement.
    # Otherwise report the narrower skill that was actually evidenced.
    core=re.sub(r"^(?:必须|须|要求|加分项)[：:\s]*","",need).strip()
    for line in lines:
        if len(core)>1 and mentions(line,core):
            return [(topic(need) or "岗位要求",line)],True
    facts=[]
    for group in ALIASES+tuple((t,) for t in ("Excel","SQL","Python","电工证","健康证","驾驶证")):
        if not any(mentions(need,t) for t in group):
            continue
        proof=next((s for s in lines if any(mentions(s,t) for t in group)),None)
        if proof:
            label=next((t for t in group if re.search("[一-龥]",t)),group[-1])
            # A skill mention is not evidence for years, seniority or proficiency.
            facts.append(("简历提及"+label,proof))
    simple=re.fullmatch(r"(?:有|会用|使用过|使用|experience (?:with|in)\s+)?([\w /.-]+?)(?:经验)?[.。]?",core,re.I)
    atomic=bool(simple and any(simple[1].strip().casefold()==t.casefold() for g in ALIASES for t in g))
    return facts,bool(facts and atomic)


def suggestion(label):
    if re.search("年|经历|经验",label):
        return "列出对应工作的起止时间、负责的任务和结果，再核对年限。"
    if re.search("证|学历|学位",label):
        return "核对证书或学历要求；已经取得的，可补上名称和取得时间。"
    if re.search("广告|投放",label):
        return "先练习做一份投放计划，写清预算、目标和复盘方法；练习应注明是个人项目。"
    if re.search("设计|制图|建模|CAD|olid|Creo",label,re.I):
        return "挑一个自己画过的零件，整理图纸、设计取舍和验证结果；还没做过可先从练习件开始。"
    return "如果做过，补上一例，写清你负责什么、怎么做、结果如何；没有经历可先做一个相关练习。"


def assess(resume,job):
    lines=[s for s in clauses(resume) if not DENY.search(s) and not NEGATIVE.search(s) and not ASPIRATION.search(s)]
    needs=list(conditions(job["岗位要求"]))
    candidate=field_hits(" ".join(lines))
    target=field_hits(job["岗位"])
    if not target:
        target=field_hits(" ".join(n for n,_ in needs))
    mismatch=bool(target and candidate and target.isdisjoint(candidate))
    facts, missing, resolved_core = [], {"必须":[],"加分":[],"其他":[]}, 0
    partial_professional=False
    for need,priority in needs:
        hits,complete=evidence_for(need,lines)
        if not mismatch and complete:
            for item in hits:
                if item not in facts:
                    facts.append(item)
        elif not mismatch:
            for tool in SOFTWARE:
                if mentions(need,tool):
                    quote=next((s for s in lines if mentions(s,tool) and re.search(
                        r"使用|运用|熟练|掌握|完成|编写|建模|制图|设计|开发|分析|\b(?:used|built|developed)\b",s,re.I)),None)
                    item=("使用过 "+tool,quote)
                    if quote and item not in facts:
                        facts.append(item)
        if hits and not complete and any(not any(t in label for t in ("英语","跨团队","跨部门","项目管理")) for label,_ in hits):
            partial_professional=True
        if complete and not mismatch:
            if priority!="加分":
                resolved_core+=1
            continue
        label=topic(need)
        dest=missing.get(priority,missing["其他"])
        if label and label not in dest:
            dest.append(label)
        elif not label and "另有要求需要核对招聘原文" not in dest:
            dest.append("另有要求需要核对招聘原文")
    core_overlap=bool(target & candidate)
    required_count=sum(p!="加分" for _,p in needs)
    high=bool(required_count and resolved_core>=required_count*.6 and not missing["必须"])
    # Generic English/teamwork evidence alone cannot raise an unrelated job.
    professional=any(not any(t in label for t in ("英语","跨团队","跨部门","项目管理")) for label,_ in facts)
    if mismatch:
        grade="低"
    elif high and (core_overlap or professional):
        grade="高"
    elif core_overlap or professional or partial_professional:
        grade="中"
    else:
        grade="低"
    if mismatch:
        reason="简历主要体现"+ "、".join(sorted(candidate)) +"，这个岗位侧重"+ "、".join(sorted(target)) +"。目前没有找到对应方向的工作经历。"
    elif not needs:
        reason="招聘页提供的要求不足，暂时无法充分判断。"
        grade="低"
    elif grade=="高":
        reason="简历有直接证据支持主要岗位要求。"
    elif grade=="中":
        reason="有相关工作方向或技能，仍有要求需要核实。"
    else:
        reason="简历里还没有找到足够的岗位核心经历。"
    return {"grade":grade,"reason":reason,"facts":facts,"missing":missing,"mismatch":mismatch}
