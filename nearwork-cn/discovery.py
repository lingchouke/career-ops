"""Search supported employers and summarize job evidence for the Chinese UI."""
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from nearwork import ALIASES, TOOLS, fetch_board, mentions


BOARDS = {
    "sesai": ("SES AI", "新能源与制造"),
    "asteralabs": ("Astera Labs", "芯片与硬件"),
    "anydesk": ("AnyDesk", "软件与技术服务"),
    "miqdigital": ("MiQ", "广告与营销"),
}
ALL = "不限行业"
TITLES = {
    "account management + ad operations executive": "客户管理与广告运营专员",
    "account manager": "客户经理", "miq senior trader": "高级广告投放优化师",
    "miq trader": "广告投放优化师", "product lead": "产品负责人", "product manager": "产品经理",
    "programmatic advertising business development manager": "程序化广告商务拓展经理",
    "programmatic advertising sales manager (growth generalist)": "程序化广告销售经理（业务增长）",
    "sales manager/director": "销售经理／总监", "seo/sem specialist": "搜索营销专员",
    "site hr": "人力资源专员", "principal product applications engineer": "资深产品应用工程师",
    "technical support specialist": "技术支持专员", "inside sales representative": "内勤销售代表",
    "mechanical engineer": "机械工程师", "fixture development engineer": "工装开发工程师",
    "equipment electrical engineer": "设备电气工程师", "equipment development engineer": "设备开发工程师",
    "ev hardware engineer": "电动车硬件工程师",
    "data product manager":"数据产品经理", "battery ai/ml engineer":"电池机器学习工程师",
    "ai/ml engineer for manufacturing large model (downstream)":"制造业大模型应用工程师",
    "bms application software engineer":"电池管理系统应用软件工程师",
    "bms bsw software engineer":"电池管理系统基础软件工程师",
    "cathode electrode engineer":"正极工程师","cell development process engineer":"电芯开发工艺工程师",
    "cell engineer":"电芯工程师","electric aerospace product systems engineer":"电动航空产品系统工程师",
    "process engineer":"工艺工程师","process engineer (senior engineer / engineer)":"工艺工程师（含高级岗）",
    "project quality engineer":"项目质量工程师","quality director":"质量总监",
    "senior battery ai/ml engineer":"高级电池机器学习工程师",
    "senior battery cell modeling scientist - simulation":"高级电芯建模与仿真科学家",
    "senior cell engineer":"高级电芯工程师","senior material engineer":"高级材料工程师",
    "senior material scientist, synthesis":"高级材料合成科学家","senior pack modeling scientist":"高级电池包建模科学家",
    "senior project management engineer":"高级项目管理工程师","senior scientist, material characterization":"高级材料表征科学家",
    "test engineer":"测试工程师","thermal runaway protection engineer":"电池热失控防护工程师",
}
ROLE_GROUPS = {"工程与技术":r"工程|技术|Engineer|Technic|Scientist|Develop|研发|设备",
               "产品与运营":r"产品|运营|Product|Operations|Trader|投放",
               "市场与销售":r"营销|市场|销售|客户经理|Sales|Account|Marketing|商务",
               "人事与支持":r"人力|人事|\bHR\b|Recruit|行政"}


def role_group(title):
    return next((k for k,v in ROLE_GROUPS.items() if re.search(v,title,re.I)), "其他岗位")


def title_cn(title):
    if re.search(r"[一-龥]",title):
        return title
    name = re.sub(r"(?:\s*[-,]\s*|\s+)(?:china|shanghai)$","",title.strip(),flags=re.I)
    return TITLES.get(name.casefold(), role_group(title)+"（职位简称）")


def search_sources(city, industry):
    sources = [s for s,(_,kind) in BOARDS.items() if industry in (ALL,kind)]
    jobs, failed = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch_board,s,city):s for s in sources}
        for future in as_completed(futures):
            source = futures[future]
            company, kind = BOARDS[source]
            try:
                rows = future.result()
            except (OSError, ValueError, KeyError):
                failed.append(company)
                continue
            for row in rows:
                row.update({"公司":company, "行业":kind, "_source":source})
            jobs.extend(rows)
    return jobs, sorted(failed)


EXTRA_TOPICS = {
    "学历":r"bachelor|master.s degree|ph\.?d", "团队协作":r"collaborat|teamwork|team player",
    "沟通协调":r"communicat", "广告投放":r"advertis|campaign|\bads?\b", "产品设计":r"product design",
    "客户关系维护":r"client|customer|account management", "产品开发":r"product development",
    "制造与工艺":r"manufactur|production process", "电路设计":r"circuit|schematic",
    "测试验证":r"\btest|validation|verification", "数据处理":r"analytics|\bdata\b",
    "销售业绩":r"revenue|pipeline|quota", "人事管理":r"human resource|employee|hiring",
    "质量管理":r"quality", "跨部门协作":r"cross.functional", "项目执行":r"deliver|implementation",
    "软件开发":r"software|programming", "供应商管理":r"supplier|vendor",
}


def topic(line):
    if re.search(r"[一-龥]",line):
        return line
    tags = []
    for group in ALIASES:
        if any(mentions(line,t) for t in group):
            cn = next((t for t in group if re.search(r"[一-龥]",t)),group[-1])
            tags.append(cn)
    tags.extend(t for t in TOOLS if mentions(line,t))
    tags.extend(k for k,pattern in EXTRA_TOPICS.items() if re.search(pattern,line,re.I))
    years = re.search(r"(more than |at least |minimum(?: of)? )?(\d+(?:\s*[-–]\s*\d+)?)(\+?)\s*years?",line,re.I)
    if years:
        prefix = {"more than ":"超过","at least ":"至少","minimum ":"至少","minimum of ":"至少"}.get((years[1] or "").lower(),"")
        tags.insert(0,prefix+years[2]+"年"+("以上" if years[3] else "")+"经验")
    degree=next((label for pattern,label in ((r"ph\.?d","博士学历"),(r"master.s degree","硕士学历"),(r"bachelor","本科学历")) if re.search(pattern,line,re.I)),None)
    if degree:
        tags=[degree if t=="学历" else t for t in tags]
    return "、".join(dict.fromkeys(tags)) or None
