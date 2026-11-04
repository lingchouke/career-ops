"""Local matching, document import and public data providers for Nearwork."""
import csv
import html
import json
import math
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def read_resume(path):
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader
        text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    elif suffix == ".docx":
        from docx import Document
        doc = Document(path)
        lines = [p.text for p in doc.paragraphs]
        lines.extend(cell.text for table in doc.tables for row in table.rows for cell in row.cells)
        text = "\n".join(lines)
    else:
        text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        raise ValueError("未提取到文字。扫描件请先做 OCR，或粘贴简历正文。")
    return text


# A related task warrants a question, never an assertion of full proficiency.
FAMILIES = [
    (("会员运营", "社群运营", "用户运营"), ("维护会员群", "微信群", "客户回访", "会员群"), "你服务哪些用户？做了什么维护动作？"),
    (("销售分析", "数据分析", "经营分析"), ("日报", "周报", "销售报表", "销售数据"), "你从哪组数据发现了什么，又做了什么调整？"),
    (("活动策划", "营销活动", "促销策划"), ("促销", "店庆", "活动执行"), "你负责活动的哪个环节？线上还是线下？"),
    (("培训", "带教", "新人培养"), ("带新人", "教新员工", "新人入职"), "你具体教过什么，怎么判断新人能独立操作？"),
    (("库存管理", "供应链"), ("盘点", "补货", "订货"), "你负责哪个环节，如何决定补货？"),
    (("客户服务", "客户支持"), ("处理客诉", "售后", "客户咨询"), "举一次你独立处理客户问题的例子。"),
]
TOOLS = ("Excel", "SQL", "Python", "Power BI", "Photoshop", "电工证", "驾驶证", "健康证")
NEGATIVE = re.compile(r"没有|未曾|缺乏|尚未|不会|未取得|无.{0,4}(经验|证)|不熟悉|没做过")


def clauses(text):
    chunks = re.split(r"[\n。；;]+", text.replace("\xa0"," "))
    return [s.strip().strip("•-").strip() for s in chunks if s.strip().strip("•-").strip()]


SECTION = re.compile(r"(?:job responsibilities|responsibilities|required skills|(?:preferred |minimum |basic )?qualifications|requirements|what you.ll (?:do|bring)|岗位职责|工作职责|岗位要求|任职要求|任职资格|加分项)[:：]?", re.I)
OTHER = re.compile(r"(?:the opportunity|about (?:us|the role|the company)|what we (?:value.*|offer)|benefits|公司介绍|公司福利|福利待遇|申请方式|apply for this job)[:：]?", re.I)
META = re.compile(r"^(?:role|reports? to|location|department|职位名称|汇报对象|工作地点|所属部门)\s*[:：]", re.I)


def requirements(jd):
    lines = clauses(jd)
    active = not any(SECTION.fullmatch(line) for line in lines)
    for line in lines:
        if SECTION.fullmatch(line):
            active = True
        elif OTHER.fullmatch(line):
            active = False
        elif active and not META.match(line):
            yield line


ALIASES = (
    ("mechanical design", "机械设计", "机械产品设计"), ("structural design", "结构设计"),
    ("mechanical engineering", "机械工程"), ("3d modeling", "三维建模", "3D建模"),
    ("solidworks", "SolidWorks"), ("pro-e", "pro/e", "ProE", "Creo"),
    ("AutoCAD", "CAD"), ("fixture design", "夹具设计", "工装设计"),
    ("automation", "自动化"), ("metal processing", "金属加工"), ("battery", "电池"),
    ("sales", "销售"), ("business development","商务拓展"), ("recruitment","招聘"),
    ("product manager", "产品经理"), ("product management", "产品管理"),
    ("data analysis", "数据分析"), ("project management", "项目管理"),
    ("cross-team communication", "跨团队沟通", "跨部门沟通"),
    ("programmatic advertising", "程序化广告"), ("technical support", "技术支持"),
    ("troubleshooting", "故障排查"), ("english", "英语", "英文"),
    ("customer service", "客户服务", "客服"), ("account management", "客户管理"),
    ("DSP",), ("ADX",), ("SSP",), ("DV360",), ("RTB",),
)


def mentions(text, term):
    if term.isascii():
        return bool(re.search(r"(?<![a-z0-9])"+re.escape(term)+r"(?![a-z0-9])", text, re.I))
    return term in text


def compare(resume, jd):
    sentences = clauses(resume)
    evidence = [x for x in sentences if not NEGATIVE.search(x)]
    result = []
    for demand in requirements(jd):
        family = next((f for f in FAMILIES if any(k in demand for k in f[0])), None)
        terms = [t for t in TOOLS if mentions(demand,t)]
        for group in ALIASES:
            if any(mentions(demand,t) for t in group):
                terms.extend(group)
        if family:
            terms.extend(k for k in family[0] if k in demand)
        exact = next((s for s in evidence if demand.casefold() in s.casefold()), "")
        hit = next((s for s in evidence if any(mentions(s,t) for t in terms)), "")
        related = next((s for s in evidence if family and any(k in s for k in family[1])), "")
        hard = bool(re.search(r"必须|须持|持有|必备|硬性|must have|required certification", demand, re.I))
        denial = next((s for s in sentences if NEGATIVE.search(s) and
                       (demand.casefold() in s.casefold() or any(re.search(
                           r"(?:没有|未曾|缺乏|尚未|不会|未取得|不熟悉|没做过|无)(?:使用|操作|取得|具备|相关)?\s*"
                           + re.escape(t), s, re.I) for t in terms))), "")
        if denial:
            state, quote, tip = "简历注明差距", denial, "保留事实。可向招聘方确认是否接受入职后学习或补证。"
        elif exact or hit:
            state, quote, tip = "简历有相关原文", exact or hit, "保留原文，核对要求中的年限、职责范围和熟练程度。"
        elif related:
            state, quote, tip = "可能迁移", related, family[2]
        else:
            state, quote, tip = "待确认", "", "有实际经历可补充具体例子；确实没做过，就保留为差距。"
        if hard:
            tip = "逐项核实硬性条件后再决定投递。" + tip
        result.append((demand, state, quote, tip, hard))
    return result


def read_jobs(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = csv.DictReader(f)
        required = {"岗位", "公司", "城市", "岗位要求"}
        if not required.issubset(rows.fieldnames or []):
            raise ValueError("表头至少需要 岗位、公司、城市、岗位要求。")
        jobs = []
        for i, row in enumerate(rows, 2):
            if not all((row[k] or "").strip() for k in required):
                raise ValueError(f"第 {i} 行缺少必填字段。")
            jobs.append({k: (v or "").strip() for k, v in row.items() if k})
        return jobs


def get_json(url, params):
    request = Request(url + "?" + urlencode(params), headers={"User-Agent": "Nearwork/1.0"})
    with urlopen(request, timeout=12) as response:
        return json.load(response)


def fetch_board(board, city):
    if not re.fullmatch("[a-zA-Z0-9_-]{1,80}", board):
        raise ValueError("请输入企业招聘板标识，例如 miqdigital。")
    locations = {"上海": "shanghai", "北京": "beijing", "深圳": "shenzhen", "广州": "guangzhou",
                 "杭州": "hangzhou", "成都": "chengdu", "苏州": "suzhou", "香港": "hong kong"}
    name = city.strip().removesuffix("市")
    if not name:
        raise ValueError("请填写目标城市。")
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", {"content": "true"})
    jobs = []
    for row in data["jobs"]:
        location = (row.get("location") or {}).get("name", "")
        if not any(word.casefold() in location.casefold() for word in [name, locations.get(name, name)]):
            continue
        markup = html.unescape(row.get("content") or "")
        body = re.sub("<[^>]*>", "", re.sub(r"</(?:li|p|div|h\d)>|<br\s*/?>", "\n", markup, flags=re.I))
        jobs.append({"岗位": row["title"], "公司": board, "城市": name, "岗位要求": html.unescape(body).strip(),
                     "来源": row["absolute_url"], "地点说明": location, "读取时间": datetime.now().strftime("%Y-%m-%d %H:%M")})
    return jobs


def amap(endpoint, key, **params):
    data = get_json("https://restapi.amap.com/v3/" + endpoint, {"key": key, **params})
    if data.get("status") != "1":
        raise ValueError("高德未返回结果：" + str(data.get("info", "请检查服务密钥和配额")))
    return data


def locate(key, city, address):
    data = amap("geocode/geo", key, address=address, city=city)
    matches = [x for x in data.get("geocodes", []) if x.get("level") in
               {"门牌号", "兴趣点", "地铁站", "公交站台", "单元号", "楼层", "门址", "住宅区", "商务住宅", "建筑物"}
               and city.removesuffix("市") in str(x.get("city") or x.get("province"))]
    if len(matches) != 1:
        raise ValueError("地址无法唯一定位到站点或建筑，请填写同城的街道和门牌号。")
    return matches[0]["location"]


def transit(key, city, origin, address, date, time):
    if not address or re.search("就近分配|待确认|多门店|就近安排", address):
        raise ValueError("请先向招聘方确认实际工作地址。")
    start, end = locate(key, city, origin), locate(key, city, address)
    data = amap("direction/transit/integrated", key, origin=start, destination=end, city=city,
                date=date, time=time, strategy="0", extensions="base", nightflag="1")
    plans = [p for p in data.get("route", {}).get("transits", []) if str(p.get("duration","")).isdigit() and int(p["duration"]) > 0]
    if not plans:
        raise ValueError("该出发时刻没有可用公共交通方案。")
    best = min(plans, key=lambda p: int(p["duration"]))
    lines = [s["bus"]["buslines"][0]["name"] for s in best.get("segments", []) if (s.get("bus") or {}).get("buslines")]
    return math.ceil(int(best["duration"]) / 60), "高德规划 · " + (" → ".join(lines) or "公共交通")
