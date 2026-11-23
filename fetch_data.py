# -*- coding: utf-8 -*-
"""
A股每日财经简报 —— 数据抓取与解读引擎
数据源：东方财富（财报 / 解禁 / 公告 / 快讯 / 全球指数行情）
输出：结构化 JSON，供 render.py 渲染成图
仅依赖 Python 标准库，无需 pip 安装任何包。
"""
import sys
import os
import json
import ssl
import gzip
import random
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "out")
os.makedirs(OUT_DIR, exist_ok=True)

CN_TZ = timezone(timedelta(hours=8))

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------- HTTP
def http_get(url, referer="https://data.eastmoney.com/", timeout=25, retry=3, raw=False):
    """带重试的 GET。raw=True 时返回 bytes（用于非 UTF-8 的接口）。"""
    headers = {
        "User-Agent": random.choice(UA_LIST),
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Referer": referer,
        "Connection": "keep-alive",
    }
    last_err = None
    for i in range(retry):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    try:
                        data = gzip.decompress(data)
                    except Exception:
                        pass
                if raw:
                    return data
                return data.decode("utf-8", errors="replace")
        except Exception as e:
            last_err = e
    raise RuntimeError("GET failed: %s | %s" % (url[:110], last_err))


def em_dc(report_name, columns="ALL", page_number=1, page_size=50,
          sort_columns=None, sort_types=None, filter_str=None):
    """东方财富数据中心 datacenter-web 通用查询。"""
    params = {
        "reportName": report_name,
        "columns": columns,
        "pageNumber": page_number,
        "pageSize": page_size,
        "source": "WEB",
        "client": "WEB",
    }
    if sort_columns:
        params["sortColumns"] = sort_columns
        params["sortTypes"] = sort_types if sort_types else -1
    if filter_str:
        params["filter"] = filter_str
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get?" + urllib.parse.urlencode(params)
    txt = http_get(url, referer="https://data.eastmoney.com/")
    js = json.loads(txt)
    if not js.get("success"):
        return []
    res = js.get("result") or {}
    return res.get("data") or []


# ---------------------------------------------------------------- 工具
def now_cn():
    return datetime.now(CN_TZ)


def day_start():
    """当天 00:00（北京时间）。推送只取当天数据，不跨自然日。"""
    return now_cn().replace(hour=0, minute=0, second=0, microsecond=0)


def day_cutoff(hours=0):
    """数据起始时间：不早于当天 00:00；hours 只能更严格，不能放宽到昨天。"""
    ds = day_start()
    if hours and hours > 0:
        return max(ds, now_cn() - timedelta(hours=hours))
    return ds


def fmt_num(v, unit="", digits=2):
    """数字格式化：亿/万 自动换算。"""
    if v is None:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1e8:
        return "%s%.2f亿%s" % (sign, a / 1e8, unit)
    if a >= 1e4:
        return "%s%.2f万%s" % (sign, a / 1e4, unit)
    return "%s%.*f%s" % (sign, digits, v, unit)


def pct(v, digits=2):
    if v is None:
        return "—"
    try:
        return "%.*f%%" % (digits, float(v))
    except (TypeError, ValueError):
        return "—"


def safe_round(v, digits=2):
    if v is None:
        return None
    try:
        return round(float(v), digits)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 解读引擎
# 判定体系（2026-11-23 按用户要求重定）
#
# 唯一判据：这条信息对「个股基本面 / 股东权益 / 资金供需」或对「市场整体
# 流动性与风险偏好」，究竟是正向还是负面。不按字面情绪，不按词频堆分。
#
# 七条原则：
#  1 只判影响原因。已发生的涨跌（大涨/跌停/创新高）、例行披露不参与打分。
#  2 白名单制：只有规则表里的词才计分，其余一律不计，避免泛词误判。
#  3 证据分级 S=±4（已落地、直接、可量化）/ A=±2（方向明确待落地）
#    / B=±1（预期性、间接、情绪面）。
#  4 「重大利好/重大利空」必须有 S 级证据或 ≥2 条 A 级证据，弱信号堆不出来。
#  5 否定与反转用前置短语规则优先处理，匹配后从文本屏蔽，避免裸词二次计分
#    （典型：「终止减持」是正向，不是「减持」利空）。
#  6 同一语义组只计一次，抑制词频放大。
#  7 多空并存不简单相抵：净影响 |s|<=1 时归中性；否则按净方向并标注交织。
#
# 配色沿用红涨绿跌（中国习惯）；中性灰。


def _pre(keys, score, level, why):
    return {"keys": keys, "score": score, "level": level, "why": why}


def _grp(keys, score, level, scope, why):
    return {"keys": keys, "score": score, "level": level, "scope": scope, "why": why}


# 前置短语：带否定 / 反转 / 例行性质的组合，优先匹配并屏蔽
PRE_RULES = [
    # —— 反转向正：负向事项被终止，实为解除压力 ——
    _pre(["终止减持", "提前终止减持", "承诺不减持", "不减持", "放弃减持", "减持计划到期未实施"],
         +2, "A", "股东终止或放弃减持，抛压解除"),
    _pre(["不向下修正", "不下修", "不修正转股价格", "不行使下修权利"],
         0, "-", "不下修转股价，避免股本摊薄"),
    # —— 反转向负：正向事项落空 ——
    _pre(["终止重大资产重组", "重大资产重组终止", "终止筹划重大资产重组", "撤回重组申请",
          "重组被否", "重大资产重组未获通过"],
         -4, "S", "重组预期落空"),
    _pre(["终止实施股权激励", "终止股权激励", "终止回购", "终止增持", "撤销激励计划"],
         -2, "A", "正向事项终止"),
    _pre(["未通过", "审核未通过", "复审未通过", "未获通过", "不予核准", "申请被否", "否决"],
         -2, "A", "审批或复审未获通过"),
    # —— 强监管 / 强落地事件 ——
    _pre(["重大资产重组事项获得审核通过", "获得核准", "获得批复", "重组过会",
          "并购重组审核通过", "注册生效"],
         +4, "S", "重组或发行获监管核准"),
    _pre(["签订日常经营重大合同", "签订重大合同", "重大合同", "重大订单",
          "中标通知书", "收到中标通知书", "中标金额"],
         +4, "S", "订单落地，直接增厚收入"),
    _pre(["预中标", "预中标公示", "拟中标"], +2, "A", "预中标，订单待落地"),
    _pre(["撤销退市风险警示", "撤销其他风险警示", "摘帽", "撤销风险警示", "撤销ST"],
         +4, "S", "风险警示解除"),
    _pre(["违规担保", "逾期担保", "资金占用", "非经营性占用", "司法冻结", "股份冻结",
          "平仓风险", "强制平仓"],
         -2, "A", "股东或资金链风险"),
    # —— 例行 / 方向不定的中性事项（命中后屏蔽裸词）——
    _pre(["因工作调整辞职", "因工作调整", "工作调整", "正常退休", "岗位调整"],
         0, "-", "正常人事变动"),
    _pre(["股票交易异常波动", "异常波动", "风险提示", "风险提示公告"],
         0, "-", "例行风险提示"),
    _pre(["提供担保", "为全资子公司提供担保", "为子公司提供担保", "担保进展", "对外担保"],
         0, "-", "例行担保"),
    _pre(["办理质押", "股份质押", "质押式回购", "解除质押"],
         0, "-", "常规质押或解押"),
    _pre(["重大资产出售", "出售子公司股权", "出售资产", "剥离资产"],
         0, "-", "资产剥离，方向视对价与用途而定"),
    _pre(["向下修正", "转股价格修正", "修正转股价格"],
         0, "-", "转债条款调整，方向不定"),
    _pre(["修订通过", "审议通过", "表决通过", "管理制度", "工作细则", "管理办法",
          "公司章程", "议事规则", "翌日披露报表", "H股公告", "会议决议", "董事会决议",
          "股东大会通知", "召开股东会", "会计师事务所"],
         0, "-", "例行治理或披露文件"),
]

# 分组证据规则：只有这些词参与计分，同组只计一次
# scope: stock=个股类文本 / market=宏观市场类文本 / both=通用
IMPACT_GROUPS = [
    # ---------- 正向 S：已落地、直接改变盈利、权益或控制权 ----------
    _grp(["回购注销", "注销回购股份", "注销部分限制性股票"], 4, "S", "stock",
         "回购注销减少股本，直接增厚每股收益"),
    _grp(["重大资产重组", "发行股份购买资产", "发行股份及支付现金购买资产", "资产注入",
          "整体上市", "重大资产置换", "要约收购", "全面要约", "被吸收合并",
          "吸收合并本公司", "控制权变更", "实际控制人变更", "控股股东变更", "易主",
          "借壳", "重组上市", "私有化"], 4, "S", "stock",
         "控制权或优质资产注入预期，上市平台价值重估"),
    _grp(["业绩预增", "扭亏为盈", "业绩大幅预增", "净利润预增"], 4, "S", "stock",
         "盈利大幅改善或扭亏"),
    _grp(["大额增持完成", "增持完成", "回购完成"], 4, "S", "stock",
         "真金白银增持或回购已完成"),
    # ---------- 正向 A：方向明确，幅度或落地待定 ----------
    _grp(["回购", "提议回购", "拟回购", "增持", "增持计划", "拟增持", "增持股份"],
         2, "A", "stock", "回购或增持，彰显信心、减少流通盘"),
    _grp(["股权激励", "员工持股", "限制性股票激励", "股票期权激励"],
         2, "A", "stock", "绑定核心团队，中长期激励"),
    _grp(["现金分红", "分红预案", "利润分配预案", "提高分红比例", "中期分红"],
         2, "A", "stock", "现金回报股东"),
    _grp(["战略合作", "签署战略合作", "框架合作协议", "产业合作"],
         2, "A", "stock", "业务协同预期"),
    _grp(["涨价", "提价", "价格上调", "产品提价", "售价上调"],
         2, "A", "stock", "毛利改善预期"),
    _grp(["政府补助", "获得补助", "收到补助", "财政补贴"],
         2, "A", "stock", "补助计入当期损益"),
    _grp(["获批注册", "获得注册批件", "药品注册证书", "生产批件", "获得专利",
          "新产品获批", "临床试验获批"],
         2, "A", "stock", "产品或资质落地"),
    # ---------- 正向 B：预期性、间接、情绪面 ----------
    _grp(["降准", "降息", "释放流动性", "流动性宽松", "政策刺激", "财政刺激",
          "稳增长政策", "下调LPR", "下调MLF"], 2, "A", "market",
         "货币或财政宽松，直接改善市场流动性"),
    _grp(["逆回购投放", "风险偏好回升", "外资净流入", "PMI回升", "经济回暖", "复苏",
          "股市稳定基金", "稳定基金", "平准基金", "政策托底", "维稳", "救市",
          "产业扶持", "补贴政策"], 1, "B", "market",
         "政策托底或预期性改善，提振市场风险偏好"),
    _grp(["超预期", "产能扩张", "投产", "量产", "放量", "订单增长", "需求回暖",
          "行业复苏", "新产品", "新签合同", "产能利用率提升", "批量交付",
          "批量供货", "批量出货", "开始交付", "实现量产", "放量阶段"], 1, "B", "stock",
         "经营改善或订单落地的预期性信号"),
    # ---------- 负向 S：已落地、直接冲击盈利、监管状态或偿债能力 ----------
    _grp(["立案告知书", "立案调查", "被立案", "涉嫌违法违规", "行政处罚决定书"],
         -4, "S", "stock", "监管立案或处罚，重大不确定性"),
    _grp(["退市风险警示", "被实施其他风险警示", "可能终止上市", "终止上市",
          "面值退市", "强制退市", "实施ST"], -4, "S", "stock",
         "退市或风险警示"),
    _grp(["业绩首亏", "业绩预亏", "由盈转亏", "巨额亏损", "大额计提减值",
          "计提大额减值", "商誉暴雷"], -4, "S", "stock",
         "盈利大幅恶化或巨额减值"),
    _grp(["破产重整", "被申请重整", "清算", "债务违约", "未能按期兑付", "债券违约"],
         -4, "S", "stock", "偿债风险"),
    _grp(["大额减持完成", "清仓式减持", "减持完成"], -4, "S", "stock",
         "大额减持已实施，供给冲击"),
    # ---------- 负向 A：方向明确，幅度或落地待定 ----------
    _grp(["减持", "拟减持", "减持计划", "减持股份", "大宗减持", "减持预披露"],
         -2, "A", "stock", "流通盘供给增加"),
    _grp(["问询函", "关注函", "警示函", "监管函", "监管措施", "通报批评", "责令改正"],
         -2, "A", "stock", "监管问询或警示"),
    _grp(["诉讼", "仲裁", "涉案", "被起诉", "败诉"],
         -2, "A", "stock", "或有负债与经营不确定性"),
    _grp(["辞职", "离任", "辞任", "高管变动", "董事长变更"],
         -2, "A", "stock", "治理层面的不确定性"),
    _grp(["业绩预减", "业绩下滑", "净利润下降", "净利润同比减少", "亏损扩大",
          "由盈转亏预计"], -2, "A", "stock", "盈利走弱"),
    _grp(["计提减值", "资产减值", "商誉减值", "存货跌价"],
         -2, "A", "stock", "资产质量下修"),
    # ---------- 负向 B：预期性、间接、情绪面 ----------
    _grp(["加息", "通胀", "关税", "制裁", "衰退", "流动性收紧", "经济下行",
          "地缘冲突"], -2, "A", "market",
         "货币收紧或外部冲击，直接压制市场风险偏好"),
    _grp(["风险偏好下降", "外资净流出", "PMI回落", "收紧监管", "承压",
          "指数下跌", "指数大跌", "美股狂跌", "股市暴跌", "全球股市下挫",
          "熔断", "暂停程序化卖出", "SIDECAR", "跌破每吨",
          "跌幅扩大", "指数跌幅", "全线走低", "收跌"],
         -1, "B", "market",
         "外围市场、指数或商品价格走弱，压制风险偏好（作为其他标的的输入变量）"),
    _grp(["砍单", "需求下修", "订单下修", "停工", "延误", "产能过剩",
          "小幅下滑", "裁员", "不及预期", "需求走弱", "业绩承压",
          "大跳水", "遭吐槽", "不适配", "召回", "质量问题", "退货潮", "需求疲软",
          "变现受阻", "增速放缓", "增长放缓", "收入放缓"],
         -1, "B", "stock", "经营或产品口碑走弱的预期性信号"),
]


def analyze_impact(text, scope="stock"):
    """判定信息对个股 / 市场的影响方向。

    返回 (score, hits, whys, both, major_ok, obj_label)
      score    净影响分数（正=正向，负=负面）
      hits     命中的证据词
      whys     对应的判定依据
      both     是否多空证据并存
      major_ok 是否具备升到「重大」档的强证据
      obj_label 作用对象：个股 / 市场 / 市场与个股
    """
    import re as _re
    t = str(text or "")
    # 公司主动澄清「不存在…负面情形」时，整段是否定式表述，不应把里面的
    # 负面词当成真实利空（例：「不存在需求预期下修或砍单情形…已进入放量阶段」）
    t, _neg_clarify = _re.subn(r"不存在[^，。；、\s]{0,24}(情形|情况|风险|压力)", " ", t)
    ev_hits, whys, neutral_hits = [], [], []
    if _neg_clarify:
        neutral_hits.append("公司澄清无该负面情形")
    score = pos_sum = neg_sum = 0
    s_cnt = a_cnt = 0
    stock_hit = market_hit = False

    def add(sc, lv, why, kw, scp):
        nonlocal score, pos_sum, neg_sum, s_cnt, a_cnt, stock_hit, market_hit
        score += sc
        if sc > 0:
            pos_sum += sc
        elif sc < 0:
            neg_sum += sc
        if lv == "S":
            s_cnt += 1
        elif lv == "A":
            a_cnt += 1
        if scp == "market":
            market_hit = True
        elif scp == "stock":
            stock_hit = True
        ev_hits.append(kw)
        whys.append(why)

    # 1) 前置短语：优先匹配，同一规则内所有命中词都屏蔽，防裸词二次计分
    #    （例：「终止减持计划暨承诺不减持」里的两处「减持」都要清掉）
    for rule in PRE_RULES:
        matched = [kw for kw in rule["keys"] if kw in t]
        if not matched:
            continue
        for kw in matched:
            t = t.replace(kw, " ")
        if rule["score"]:
            add(rule["score"], rule["level"], rule["why"], matched[0], "stock")
        else:
            # 同义短语只展示最长的一条，避免「异常波动、股票交易异常波动」重复
            neutral_hits.append(max(matched, key=len))
    # 2) 分组证据：同组只计一次
    for g in IMPACT_GROUPS:
        if scope != "both" and g["scope"] not in (scope, "both"):
            continue
        for kw in g["keys"]:
            if kw in t:
                t = t.replace(kw, " ")
                add(g["score"], g["level"], g["why"], kw, g["scope"])
                break
    # 3) 多空交织且净影响很弱 → 归中性
    both = pos_sum > 0 and neg_sum > 0
    if both and abs(score) <= 1:
        score = 0
    major_ok = (s_cnt >= 1) or (a_cnt >= 2)
    if market_hit and stock_hit:
        obj = "市场与个股"
    elif market_hit:
        obj = "市场"
    else:
        obj = "个股"
    return score, ev_hits, whys, both, major_ok, obj, neutral_hits


def score_text(text, scope="stock"):
    """兼容旧调用：返回 (score, hits)。"""
    s, hits, _w, _b, _m, _o, _n = analyze_impact(text, scope)
    return s, hits


def judge(score, strong=2, weak=1, major_ok=True):
    """分数 → 档位 / 文案 / 颜色。

    major_ok：是否允许升到「重大」。文本类由调用方按证据等级传入；
    数值类（财报/解禁/龙虎榜）自带量级，默认允许。
    """
    if score >= 4 and major_ok:
        return "利好", "重大利好", "#c62828"
    if score >= strong:
        return "利好", "利好", "#c62828"
    if score >= weak:
        return "偏多", "小幅利好", "#e57373"
    if score <= -4 and major_ok:
        return "利空", "重大利空", "#2e7d32"
    if score <= -strong:
        return "利空", "利空", "#2e7d32"
    if score <= -weak:
        return "偏空", "小幅利空", "#66bb6a"
    return "中性", "中性", "#8e8e8e"


def impact_text(label, obj, hits, whys, both, neutral=None, fallback="例行披露"):
    """生成带判定依据的解读文案，让「为什么是这个方向」在推送里可见。"""
    neutral = neutral or []
    if label == "中性":
        ev = "、".join(list(dict.fromkeys(neutral))[:2]) or fallback
        if both:
            return "中性：多空证据交织、净影响接近零｜%s" % ev
        return "中性：%s｜无明确方向性信号" % ev
    direction = "正向" if ("利好" in label) else "负面"
    ev = "、".join(list(dict.fromkeys(hits))[:2]) or fallback
    return "%s：对%s%s｜依据 %s%s" % (label, obj, direction, ev,
                                    "，多空交织取净方向" if both else "")


def explain_finance(item):
    """财报解读：以净利润同比为主，营收同比与是否亏损为辅。"""
    np_yoy = item.get("净利润同比")
    rev_yoy = item.get("营收同比")
    profit = item.get("净利润")
    name = item.get("名称")
    period = item.get("报告期标签", "")

    s = 0
    if np_yoy is not None:
        if np_yoy >= 200:
            s += 4
        elif np_yoy >= 50:
            s += 3
        elif np_yoy >= 20:
            s += 2
        elif np_yoy > 0:
            s += 1
        elif np_yoy > -20:
            s -= 1
        elif np_yoy > -50:
            s -= 2
        elif np_yoy > -100:
            s -= 3
        else:
            s -= 4
    if profit is not None and profit < 0:
        s -= 2
    # 营收与利润背离：利润涨但营收跌，质量存疑
    diverge = False
    if np_yoy is not None and rev_yoy is not None and np_yoy > 0 and rev_yoy < 0:
        s -= 1
        diverge = True

    tag, label, color = judge(s)

    parts = []
    if np_yoy is not None:
        parts.append("净利同比 %s" % pct(np_yoy))
    if rev_yoy is not None:
        parts.append("营收同比 %s" % pct(rev_yoy))
    if profit is not None and profit < 0:
        parts.append("当期亏损 %s" % fmt_num(abs(profit)))
    if diverge:
        parts.append("利润增但营收降，增长质量待观察")
    基础 = "；".join(parts) if parts else "数据披露"

    if s >= 2:
        txt = "%s：对个股正向｜业绩大幅改善，%s" % (label, 基础)
    elif s >= 1:
        txt = "%s：对个股正向｜业绩稳中有进，%s" % (label, 基础)
    elif s <= -2:
        txt = "%s：对个股负面｜业绩承压，%s" % (label, 基础)
    elif s <= -1:
        txt = "%s：对个股负面｜业绩小幅走弱，%s" % (label, 基础)
    else:
        txt = "中性：业绩变动平缓｜%s" % 基础
    return tag, label, color, txt


def explain_unlock(ratio_pct, cap_yi):
    """解禁解读：核心看解禁市值/占总股本比例。"""
    if ratio_pct is None:
        ratio_pct = 0
    if ratio_pct >= 20:
        s = -4
    elif ratio_pct >= 10:
        s = -3
    elif ratio_pct >= 5:
        s = -2
    elif ratio_pct >= 1:
        s = -1
    else:
        s = 0
    tag, label, color = judge(s)
    if s <= -3:
        txt = "%s：对个股负面｜解禁占总股本 %s，规模大，抛压预期强" % (label, pct(ratio_pct))
    elif s <= -2:
        txt = "%s：对个股负面｜解禁占总股本 %s，有一定减持压力" % (label, pct(ratio_pct))
    elif s == -1:
        txt = "%s：对个股负面｜解禁占总股本 %s，压力有限但需留意" % (label, pct(ratio_pct))
    else:
        txt = "中性：对个股影响可忽略｜解禁占总股本 %s，占比很小" % pct(ratio_pct)
    if cap_yi and cap_yi >= 50:
        txt += "；解禁市值约 %.1f 亿元，体量偏大" % cap_yi
    return tag, label, color, txt


def explain_news(title, digest):
    """要闻：作用对象可能是市场整体，也可能是某只个股，故用 both 口径。

    摘要不参与方向打分（长摘要堆词会把「风险」放大成重大利空）；
    仅当标题没有证据时作弱补充，且最高只到「小幅」，不升重大档。
    """
    s, hits, whys, both, major_ok, obj, neutral = analyze_impact(title, "both")
    if not hits and not neutral:
        s2, h2, w2, _b2, _m2, o2, n2 = analyze_impact(digest or "", "both")
        if h2:
            s = 1 if s2 > 0 else (-1 if s2 < 0 else 0)
            hits, whys, obj, neutral = h2[:2], w2[:2], o2, n2
            both, major_ok = False, False
    tag, label, color = judge(s, major_ok=major_ok)
    market_result = ["指数", "下跌", "上涨", "跌破", "跳水", "狂跌", "暴跌", "价格", "交付"]
    fb = ("行情或数据结果" if any(w in title for w in market_result)
          else "宏观或行业信息")
    txt = impact_text(label, obj, hits, whys, both, neutral, fallback=fb)
    return tag, label, color, txt


def explain_announce(title):
    # 被重组 / 易主的一方：用户明确指定按「重大利好」重点关注，保持该口径
    hit, role = merger_role(title)
    if hit:
        return ("利好", "重大利好", "#c62828",
                "重大利好：对个股正向｜依据 %s(S)：上市平台自身被重组或易主" % role)
    s, hits, whys, both, major_ok, obj, neutral = analyze_impact(title, "stock")
    tag, label, color = judge(s, major_ok=major_ok)
    txt = impact_text(label, obj, hits, whys, both, neutral, fallback="常规披露")
    return tag, label, color, txt


# ---------------------------------------------------------------- 1. 最新财报
def fetch_financials(days_back=7, top_n=10, bottom_n=5):
    """抓取最近 days_back 天内新披露的财报（业绩报表 RPT_LICO_FN_CPD）。
    返回：业绩预喜 Top + 业绩爆雷 Bottom。"""
    today = now_cn().date()
    # 只取当天新披露的财报，不回看历史（用户要求：推送只更新当天信息）
    since = today
    filt = "(NOTICE_DATE>='%s')" % since.isoformat()
    rows = []
    for pg in (1, 2, 3):
        try:
            data = em_dc("RPT_LICO_FN_CPD", page_number=pg, page_size=100,
                         sort_columns="NOTICE_DATE,REPORTDATE", sort_types="-1,-1",
                         filter_str=filt)
        except Exception:
            data = []
        if not data:
            break
        rows.extend(data)
        if len(data) < 100:
            break

    items = []
    seen = set()
    for r in rows:
        code = r.get("SECURITY_CODE")
        if not code:
            continue
        key = (code, (r.get("REPORTDATE") or "")[:10])
        if key in seen:
            continue
        seen.add(key)
        rd = (r.get("REPORTDATE") or "")[:10]
        items.append({
            "代码": code,
            "名称": r.get("SECURITY_NAME_ABBR"),
            "报告期": rd,
            "报告期标签": r.get("DATATYPE") or (r.get("QDATE") or ""),
            "净利润": safe_round(r.get("PARENT_NETPROFIT"), 2),
            "净利润同比": safe_round(r.get("SJLTZ"), 2),
            "营业收入": safe_round(r.get("TOTAL_OPERATE_INCOME"), 2),
            "营收同比": safe_round(r.get("YSTZ"), 2),
            "每股收益": safe_round(r.get("BASIC_EPS"), 4),
            "净资产收益率": safe_round(r.get("WEIGHTAVG_ROE"), 2),
            "毛利率": safe_round(r.get("XSMLL"), 2),
            "每股净资产": safe_round(r.get("BPS"), 4),
            "所属行业": r.get("PUBLISHNAME") or r.get("BOARD_NAME"),
            "披露日": (r.get("NOTICE_DATE") or "")[:10],
        })

    # 排序：按净利润同比
    with_yoy = [x for x in items if x.get("净利润同比") is not None]
    with_yoy.sort(key=lambda x: x["净利润同比"], reverse=True)
    喜 = with_yoy[:top_n]
    雷 = [x for x in with_yoy[-bottom_n:] if x["净利润同比"] < 0][::-1]

    # 若新披露不足，用亏损榜补足
    亏损 = [x for x in items if (x.get("净利润") or 0) < 0]
    亏损.sort(key=lambda x: x.get("净利润") or 0)
    if len(雷) < 3:
        for x in 亏损:
            if x not in 雷:
                雷.append(x)
            if len(雷) >= bottom_n:
                break

    def attach(lst, kind):
        out = []
        for x in lst:
            tag, label, color, txt = explain_finance(x)
            y = dict(x)
            y.update({"类型": kind, "档位": tag, "标签": label, "配色": color, "解读": txt})
            out.append(y)
        return out

    return {
        "预喜": attach(喜, "业绩预喜"),
        "爆雷": attach(雷[:bottom_n], "业绩爆雷"),
        "样本数": len(items),
    }


# ---------------------------------------------------------------- 2. 今日解禁
def fetch_unlocks(span_days=7, top_n=10):
    """抓取今日（及未来 span_days 天内）限售股解禁。"""
    today = now_cn().date()
    # 只看当日解禁，不再前瞻未来（用户要求：当天没有就不展示该板块）
    end = today
    filt = "(FREE_DATE>='%s')(FREE_DATE<='%s')" % (today.isoformat(), end.isoformat())
    rows = []
    for pg in (1, 2, 3):
        try:
            data = em_dc("RPT_LIFT_STAGE", page_number=pg, page_size=100,
                         sort_columns="FREE_DATE", sort_types=1, filter_str=filt)
        except Exception:
            data = []
        if not data:
            break
        rows.extend(data)
        if len(data) < 100:
            break

    items = []
    for r in rows:
        code = r.get("SECURITY_CODE")
        if not code:
            continue
        # 解禁数量：CURRENT_FREE_SHARES 单位为万股
        shares_wan = r.get("CURRENT_FREE_SHARES")
        # 解禁市值：LIFT_MARKET_CAP 单位为万元
        cap_wan = r.get("LIFT_MARKET_CAP")
        ratio_total = r.get("TOTALSHARES_RATIO") or r.get("TOTAL_RATIO") or 0
        ratio_pct = safe_round(float(ratio_total) * 100, 3) if ratio_total is not None else None
        cap_yi = safe_round(float(cap_wan) / 10000.0, 2) if cap_wan is not None else None
        fd = (r.get("FREE_DATE") or "")[:10]
        tag, label, color, txt = explain_unlock(ratio_pct or 0, cap_yi or 0)
        items.append({
            "代码": code,
            "名称": r.get("SECURITY_NAME_ABBR"),
            "解禁日期": fd,
            "解禁数量": fmt_num((float(shares_wan) * 10000) if shares_wan is not None else None, "股"),
            "解禁数量万股": safe_round(shares_wan, 2),
            "解禁市值": ("%.2f亿" % cap_yi) if cap_yi is not None else "—",
            "解禁市值亿": cap_yi,
            "解禁比例": pct(ratio_pct) if ratio_pct is not None else "—",
            "解禁比例数值": ratio_pct,
            "解禁类型": r.get("FREE_SHARES_TYPE"),
            "档位": tag, "标签": label, "配色": color, "解读": txt,
        })
    # 按解禁规模排序（市值优先，其次比例）
    items.sort(key=lambda x: (x.get("解禁市值亿") or 0), reverse=True)
    今日 = [x for x in items if x["解禁日期"] == today.isoformat()]
    临近 = [x for x in items if x["解禁日期"] != today.isoformat()]
    return {
        "今日": 今日[:top_n],
        "临近": [],
        "样本数": len(今日),
    }


# ---------------------------------------------------------------- 3. 隔夜全球要闻 + 全球市场
GLOBAL_MARKETS = [
    ("100.DJIA", "道琼斯"), ("100.SPX", "标普500"), ("100.NDX", "纳斯达克100"),
    ("100.HSI", "恒生指数"), ("100.N225", "日经225"), ("100.GDAXI", "德国DAX"),
    ("100.FTSE", "英国富时100"), ("100.UDI", "美元指数"),
    ("101.GC00Y", "COMEX黄金"), ("101.CL00Y", "WTI原油"), ("101.SI00Y", "COMEX白银"),
]


def _market_from_sina():
    """备用源：新浪财经（东方财富限流时兜底）。"""
    pairs = [("gb_dji", "道琼斯"), ("gb_ixic", "纳斯达克"), ("gb_inx", "标普500"),
             ("int_hangseng", "恒生指数")]
    url = "https://hq.sinajs.cn/list=" + ",".join(p[0] for p in pairs)
    try:
        raw = http_get(url, referer="https://finance.sina.com.cn", retry=2, raw=True)
        txt = raw.decode("gbk", errors="replace")
    except Exception as e:
        print("[WARN] 新浪行情备用源失败: %s" % e)
        return []
    out = []
    for code, name in pairs:
        key = 'hq_str_%s="' % code
        i = txt.find(key)
        if i < 0:
            continue
        seg = txt[i + len(key):]
        seg = seg[:seg.find('"')]
        f = seg.split(",")
        if len(f) < 4:
            continue
        try:
            # int_hangseng: 名称,现价,涨跌额,涨跌幅 | gb_*: 名称,现价,涨跌幅,...
            chg_idx = 3 if code.startswith("int_") else 2
            price, chg = float(f[1]), float(f[chg_idx])
        except (ValueError, IndexError):
            continue
        out.append({"名称": name, "现价": safe_round(price, 2), "涨跌幅": safe_round(chg, 2)})
    return out


def fetch_global_market():
    """隔夜全球主要股指 / 商品 / 汇率行情（东方财富主源，新浪兜底）。"""
    secids = ",".join(x[0] for x in GLOBAL_MARKETS)
    name_map = {k: v for k, v in GLOBAL_MARKETS}
    url = ("https://push2.eastmoney.com/api/qt/ulist.np/get?fields=f1,f2,f3,f4,f12,f13,f14"
           "&secids=%s&ut=fa5fd1943c7b386f172d6893dbfba10b" % secids)
    diff = []
    import time as _t
    for attempt in range(3):
        try:
            js = json.loads(http_get(url, referer="https://quote.eastmoney.com/", retry=1))
            diff = ((js.get("data") or {}).get("diff")) or []
            if diff:
                break
        except Exception:
            diff = []
        _t.sleep(1.2 * (attempt + 1))
    if not diff:
        back = _market_from_sina()
        if back:
            print("[INFO] 全球行情走新浪备用源")
        return back
    out = []
    for d in diff:
        code = d.get("f12")
        if not code:
            continue
        dec = d.get("f1")
        try:
            dec = int(dec) if dec is not None else 2
        except (TypeError, ValueError):
            dec = 2
        price = d.get("f2")
        chg = d.get("f3")
        try:
            price = float(price) / (10 ** dec) if price not in (None, "-") else None
        except (TypeError, ValueError):
            price = None
        try:
            chg = float(chg) / 100.0 if chg not in (None, "-") else None
        except (TypeError, ValueError):
            chg = None
        secid = ("100." if d.get("f13") == 100 else "101.") + str(code)
        out.append({
            "名称": d.get("f14") or name_map.get(secid, code),
            "现价": safe_round(price, 2),
            "涨跌幅": safe_round(chg, 2),
        })
    return out


def fetch_news(limit=12, hours=18):
    """抓取东方财富 7x24 全球财经快讯（覆盖隔夜时段）。"""
    url = "https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_100_1_.html"
    try:
        txt = http_get(url, referer="https://kuaixun.eastmoney.com/")
    except Exception:
        return []
    start = txt.find("=")
    if start < 0:
        return []
    try:
        js = json.loads(txt[start + 1:].strip().rstrip(";"))
    except Exception:
        return []
    lst = js.get("LivesList") or []

    def collect(hrs):
        cutoff = day_cutoff(hrs)
        buf = []
        for n in lst:
            t = n.get("showtime") or ""
            try:
                dt = datetime.strptime(t, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CN_TZ)
            except Exception:
                dt = now_cn()
            if dt < cutoff:
                continue
            title = (n.get("title") or n.get("simtitle") or "").strip()
            digest = (n.get("digest") or "").strip()
            if not title:
                continue
            tag, label, color, txt2 = explain_news(title, digest)
            buf.append({
                "时间": t[5:16] if len(t) >= 16 else t,
                "标题": title[:60],
                "来源": "东方财富",
                "摘要": digest[:120].replace("\n", " "),
                "链接": n.get("url_unique") or n.get("url_w"),
                "档位": tag, "标签": label, "配色": color, "解读": txt2,
                "_ts": dt.timestamp(),
            })
        return buf

    # 先按设定窗口取；条数不足（非交易日/凌晨时段）则自动放宽，保证内容饱满
    out = collect(hours)
    if len(out) < max(6, int(limit * 0.6)):
        out = collect(hours * 2)
    if len(out) < max(6, int(limit * 0.6)):
        out = collect(hours * 4)
    for x in out[:limit]:
        x.pop("_ts", None)
    return out[:limit]


# ---------------------------------------------------------------- 4. 公司公告
# 高价值公告关键词（命中优先展示）
ANN_IMPORTANT = ["业绩预告", "业绩快报", "业绩预增", "业绩预减", "增持", "回购", "减持",
                 "中标", "重大合同", "重组", "收购", "要约", "股权激励", "分红", "派息",
                 "诉讼", "仲裁", "问询函", "关注函", "立案", "质押", "冻结", "退市",
                 "停牌", "担保", "对外投资", "控制权", "股权转让", "定增", "募资",
                 "异动", "亏损", "计提", "减值", "高管", "核心技术人员",
                 "产销快报", "经营数据", "员工持股", "订单", "涨价", "提价"]
# 低价值例行公告（命中后排）
ANN_TRIVIAL = ["投资者关系", "调研", "接待机构", "活动记录", "董事会决议", "监事会决议",
               "股东大会", "公司章程", "管理制度", "独立董事", "募集资金", "提示性",
               "法律意见", "审计报告", "更正", "补充", "制度", "细则", "工作制度"]

# ---------------------------------------------------------------- 重点关注：被收购的一方
# 用户口径（2026-11-18）：只关注「上市公司自身作为被收购 / 被注入资产 / 易主 /
# 被重组主体」的公告，也就是"被收购的一方公司"，而不是出钱买别人或卖自己资产的一方。
#   正例：国投中鲁 2025-06-24《关于筹划重大资产重组的停牌公告》
#         （控股股东把电子院资产注入上市平台，公司自身被重组、主业将变更）
#   反例：*ST闻泰《关于重大资产出售的进展公告》（本公司是卖方，不是被收购方）
#         芳源转债《关于向下修正转股价格暨转股停牌的公告》（含"停牌"但纯属噪声）
# 仅凭标题判断角色，不读正文，保证云端自动化稳定零成本。

# 明确不是「被收购的一方」：本公司是卖方 / 纯买方 / 可转债噪声
ANN_NOT_TARGET = [
    # 本公司卖资产（卖方）
    "重大资产出售", "出售资产", "出售股权", "出售子公司", "资产剥离", "剥离资产",
    "转让子公司", "挂牌转让", "公开挂牌", "转让所持",
    # 本公司出钱买别人（纯买方对外投资）
    "对外投资", "增资", "竞买", "竞拍", "摘牌", "设立子公司", "共同投资",
    "收购少数股权", "增持计划", "增持股份计划",
    # 可转债 / 例行停牌噪声
    "向下修正", "转股价格", "可转债", "转债", "回售", "赎回", "本息兑付",
]
# 「被收购的一方」关键词，按角色分组（越靠前优先级越高）
ANN_TARGET_GROUPS = [
    (["控制权变更", "控制权拟", "控制权发生", "实控人变更", "实控人拟变更",
      "实际控制人变更", "实际控制人发生变更", "实际控制人拟变更",
      "控股股东变更", "控股股东拟变更", "易主", "被收购", "收购本公司", "收购公司股份"],
     "易主 / 控制权变更"),
    (["要约收购", "全面要约", "被吸收合并", "吸收合并本公司",
      "换股吸收合并本公司", "被合并", "私有化"],
     "被要约 / 被合并"),
    (["重组上市", "借壳"], "被借壳 / 重组上市"),
    (["资产注入", "整体上市", "重大资产置换", "资产置换", "筹划重大资产重组",
      "重大资产重组", "发行股份购买资产", "发行股份及支付现金购买资产",
      "购买资产暨关联交易", "与公司有关的重大资产重组", "重大资产购买"],
     "资产注入 / 自身重组"),
]
# 明确终止/否决的除外，避免把「终止重组」误标成利好
ANN_MERGER_NEG = ["终止", "中止", "撤回", "否决", "未获通过", "失败", "暂停"]


def merger_role(title):
    """判断是否为「被收购的一方」公告，返回 (是否命中, 角色标签)。

    先排除明确属于买方 / 卖方 / 噪声的标题，再按角色分组匹配。
    """
    import re
    t = str(title or "").strip()
    # 公告附件（如 "2-1重大资产重组报告书(注册稿)"）不是正文公告，标题也不规范
    if re.match(r"^\d+\s*[-－]\s*\d+", t):
        return False, ""
    if any(w in t for w in ANN_MERGER_NEG):
        return False, ""
    if any(w in t for w in ANN_NOT_TARGET):
        return False, ""
    for kws, role in ANN_TARGET_GROUPS:
        if any(w in t for w in kws):
            return True, role
    return False, ""


def is_merger_ann(title):
    """兼容旧调用：是否属于重点关注的「被收购的一方」公告。"""
    return merger_role(title)[0]


def ann_weight(title, col_name=""):
    """公告重要性权重：2=重要, 1=普通, 0=例行。"""
    t = str(title or "")
    if any(w in t for w in ANN_IMPORTANT):
        return 2
    if any(w in t for w in ANN_TRIVIAL):
        return 0
    return 1


def fetch_announcements(limit=12, hours=24):
    """抓取最新上市公司公告（时效优先：按发布时间倒序，例行调研类过滤掉）。"""
    url = ("https://np-anotice-stock.eastmoney.com/api/security/ann"
           "?sr=-1&page_size=150&page_index=1&ann_type=A&client_source=web&f_node=0&s_node=0")
    try:
        js = json.loads(http_get(url, referer="https://data.eastmoney.com/notices/"))
    except Exception:
        return []
    lst = ((js.get("data") or {}).get("list")) or []

    def collect(hrs, drop=True):
        cutoff = day_cutoff(hrs)
        buf = []
        for a in lst:
            dt_s = (a.get("display_time") or a.get("notice_date") or "").replace(":000", "").strip()
            try:
                dt = datetime.strptime(dt_s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=CN_TZ)
            except Exception:
                dt = now_cn()
            if dt < cutoff:
                continue
            codes = a.get("codes") or []
            if not codes:
                continue
            c0 = codes[0]
            title = (a.get("title_ch") or a.get("title") or "").strip()
            sn = c0.get("short_name") or ""
            if sn and title.startswith(sn):
                rest = title[len(sn):]
                if rest[:1] in (":", "："):
                    title = rest[1:].strip()
            cols = a.get("columns") or []
            col_name = cols[0].get("column_name") if cols else ""
            w = ann_weight(title, col_name)
            if drop and w == 0:
                continue  # 例行调研/活动记录类直接过滤，避免挤占最新公告
            tag, label, color, txt2 = explain_announce(title)
            buf.append({
                "代码": c0.get("stock_code"),
                "名称": sn,
                "公告标题": title[:56],
                "公告时间": dt_s[5:16] if len(dt_s) >= 16 else dt_s,
                "公告类型": col_name,
                "链接": "https://data.eastmoney.com/notices/detail/%s/%s.html" % (
                    c0.get("stock_code"), a.get("art_code")),
                "档位": tag, "标签": label, "配色": color, "解读": txt2,
                "_w": w,
                "_ts": dt.timestamp(),
            })
        # 最新发布在前
        buf.sort(key=lambda x: -x["_ts"])
        return buf

    # 先取「设定窗口内、已过滤例行公告」的；不足则依次放宽，保证内容不空
    need = max(6, int(limit * 0.6))
    out = collect(hours, drop=True)
    if len(out) < need:
        out = collect(hours, drop=False)
    if len(out) < need:
        out = collect(hours * 2, drop=False)
    if len(out) < need:
        out = collect(hours * 4, drop=False)
    out = out[:limit]
    for x in out:
        x.pop("_w", None)
        x.pop("_ts", None)
    return out


def fetch_merger_announcements(limit=3, hours=24, pages=20):
    """定向抓取「被收购的一方」公告（重点关注，按重大利好处理）。

    只收录上市公司自身作为被收购 / 被注入资产 / 易主 / 被重组主体的一方，
    排除本公司卖资产（重大资产出售）、纯买方对外投资及可转债停牌噪声。
    单独翻多页抓取：常规公告接口只给最近 100 条，盘后公告密集时
    这类公告会被挤出前 100 条，故不能只从常规公告列表里筛。
    """
    cutoff = day_cutoff(hours)
    seen = set()
    out = []
    base = ("https://np-anotice-stock.eastmoney.com/api/security/ann"
            "?sr=-1&page_size=100&page_index=%d&ann_type=A&client_source=web&f_node=0&s_node=0")
    for pi in range(1, pages + 1):
        try:
            js = json.loads(http_get(base % pi, referer="https://data.eastmoney.com/notices/"))
        except Exception:
            continue
        lst = ((js.get("data") or {}).get("list")) or []
        if not lst:
            break
        for a in lst:
            dt_s = (a.get("display_time") or a.get("notice_date") or "").replace(":000", "").strip()
            try:
                dt = datetime.strptime(dt_s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=CN_TZ)
            except Exception:
                continue
            if dt < cutoff:
                continue
            title = (a.get("title_ch") or a.get("title") or "").strip()
            hit, role = merger_role(title)
            if not hit:
                continue
            codes = a.get("codes") or []
            if not codes:
                continue
            # 优先取 A 股股票代码，避免公告 codes[0] 是可转债（如 110081 闻泰转债）
            c0 = codes[0]
            for c in codes:
                sc = str(c.get("stock_code") or "")
                if len(sc) == 6 and sc[:1] in ("0", "3", "6", "8", "4"):
                    c0 = c
                    break
            sn = c0.get("short_name") or ""
            if sn and title.startswith(sn):
                rest = title[len(sn):]
                if rest[:1] in (":", "："):
                    title = rest[1:].strip()
            # 以公司全称开头时（"XX股份有限公司关于…"）截掉全称，只留"关于…"
            import re as _re
            _m = _re.search(r"(?:股份有限公司|有限责任公司|有限公司)关于", title)
            if _m and _m.start() < 20:
                title = title[_m.end() - 2:].strip()
            key = a.get("art_code") or (c0.get("stock_code"), title)
            if key in seen:
                continue
            seen.add(key)
            cols = a.get("columns") or []
            col_name = cols[0].get("column_name") if cols else ""
            tag, label, color, txt = explain_announce(title)
            out.append({
                "代码": c0.get("stock_code"),
                "名称": sn,
                "公告标题": title[:56],
                "公告时间": dt_s[5:16] if len(dt_s) >= 16 else dt_s,
                "公告类型": col_name,
                "链接": "https://data.eastmoney.com/notices/detail/%s/%s.html" % (
                    c0.get("stock_code"), a.get("art_code")),
                "档位": tag, "标签": label, "配色": color, "解读": txt,
                "角色": role,                 "重点关注": True,
                "_ts": dt.timestamp(),
            })
        # 列表按时间倒序：本页末尾（最早一条）已早于当日起点，后面只会更早，停止翻页
        tail_s = (lst[-1].get("display_time") or lst[-1].get("notice_date") or "").replace(":000", "").strip()
        try:
            if datetime.strptime(tail_s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=CN_TZ) < cutoff:
                break
        except Exception:
            pass
    out.sort(key=lambda x: -x["_ts"])
    # 同一家公司只保留最新一条：同一重组事项常连发数条进展公告，避免刷屏
    seen_code = set()
    uniq = []
    for x in out:
        code = x.get("代码") or ""
        if code and code in seen_code:
            continue
        seen_code.add(code)
        uniq.append(x)
    out = uniq[:limit]
    for x in out:
        x.pop("_ts", None)
    return out


# ---------------------------------------------------------------- 5. 龙虎榜
def _inst_count(txt):
    """从席位说明里解析机构家数，如 '4家机构买入' → 4。"""
    import re
    m = re.search(r"(\d+)\s*家机构买入", str(txt or ""))
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*家机构卖出", str(txt or ""))
    if m:
        return -int(m.group(1))
    return 0


def explain_lhb(x):
    """龙虎榜解读：净买卖方向 + 机构席位参与情况。"""
    net = x.get("净买入") or 0
    inst = x.get("机构家数") or 0
    chg = x.get("涨跌幅") or 0
    s = 0
    if net > 0:
        s += 2
    elif net < 0:
        s -= 2
    if inst >= 2:
        s += 2
    elif inst == 1:
        s += 1
    elif inst <= -2:
        s -= 2
    elif inst == -1:
        s -= 1
    # 大涨却净卖出：高位派发嫌疑
    if chg >= 9 and net < 0:
        s -= 1
    tag, label, color = judge(s)

    parts = []
    if net > 0:
        parts.append("龙虎榜净买入 %s" % fmt_num(net))
    elif net < 0:
        parts.append("龙虎榜净卖出 %s" % fmt_num(abs(net)))
    if inst > 0:
        parts.append("%d家机构买入" % inst)
    elif inst < 0:
        parts.append("%d家机构卖出" % abs(inst))
    if chg:
        parts.append("当日 %+.2f%%" % chg)
    detail = "，".join(parts) or "席位资金博弈"

    if s >= 3:
        txt = "%s：对个股正向｜%s，机构资金介入明显" % (label, detail)
    elif s >= 1:
        txt = "%s：对个股正向｜%s，买方占优" % (label, detail)
    elif s <= -3:
        txt = "%s：对个股负面｜%s，资金出逃明显" % (label, detail)
    elif s <= -1:
        txt = "%s：对个股负面｜%s，卖方占优" % (label, detail)
    else:
        txt = "中性：%s，多空均衡" % detail
    return tag, label, color, txt


def fetch_lhb(top_n=6, bottom_n=4, days_back=5):
    """抓取最近交易日的龙虎榜：主力抢筹 / 资金出逃。"""
    today = now_cn().date()
    since = today - timedelta(days=days_back)
    filt = "(TRADE_DATE>='%s')" % since.isoformat()
    rows = []
    for pg in (1, 2):
        try:
            data = em_dc("RPT_DAILYBILLBOARD_DETAILSNEW", page_number=pg, page_size=100,
                         sort_columns="TRADE_DATE,BILLBOARD_NET_AMT", sort_types="-1,-1",
                         filter_str=filt)
        except Exception:
            data = []
        if not data:
            break
        rows.extend(data)
        if len(data) < 100:
            break
    if not rows:
        return {"买入": [], "卖出": [], "交易日": "", "样本数": 0}

    # 取最近一个交易日
    latest = max((r.get("TRADE_DATE") or "")[:10] for r in rows)
    day_rows = [r for r in rows if (r.get("TRADE_DATE") or "")[:10] == latest]

    def mk(r):
        net = r.get("BILLBOARD_NET_AMT")
        try:
            net = float(net) if net is not None else None
        except (TypeError, ValueError):
            net = None
        seat = r.get("EXPLAIN") or ""
        return {
            "代码": r.get("SECURITY_CODE"),
            "名称": r.get("SECURITY_NAME_ABBR"),
            "交易日": latest,
            "收盘价": safe_round(r.get("CLOSE_PRICE"), 2),
            "涨跌幅": safe_round(r.get("CHANGE_RATE"), 2),
            "净买入": safe_round(net, 2),
            "买入额": safe_round(r.get("BILLBOARD_BUY_AMT"), 2),
            "卖出额": safe_round(r.get("BILLBOARD_SELL_AMT"), 2),
            "上榜原因": (r.get("EXPLANATION") or "")[:26],
            "席位说明": seat[:30],
            "机构家数": _inst_count(seat),
        }

    items = [mk(r) for r in day_rows]
    for x in items:
        tag, label, color, txt = explain_lhb(x)
        x.update({"档位": tag, "标签": label, "配色": color, "解读": txt})

    with_net = [x for x in items if x.get("净买入") is not None]
    with_net.sort(key=lambda x: x["净买入"], reverse=True)
    买入 = [x for x in with_net if x["净买入"] > 0][:top_n]
    卖出 = [x for x in with_net if x["净买入"] < 0]
    卖出.sort(key=lambda x: x["净买入"])
    卖出 = 卖出[:bottom_n]
    if latest != today.isoformat():
        # 用户要求：只展示当天数据；当日龙虎榜未披露时整块不展示（不再回退上一交易日）
        return {"买入": [], "卖出": [], "交易日": latest, "样本数": 0, "是否当日": False}
    return {"买入": 买入, "卖出": 卖出, "交易日": latest, "样本数": len(items),
            "是否当日": True}


# ---------------------------------------------------------------- 汇总
def build(session="早报", cfg=None):
    cfg = cfg or {}
    now = now_cn()
    result = {
        "生成时间": now.strftime("%Y-%m-%d %H:%M:%S"),
        "场次": session,
        "日期": now.strftime("%Y-%m-%d"),
        "星期": "一二三四五六日"[now.weekday()],
    }

    def safe(label, fn, default):
        try:
            return fn()
        except Exception as e:
            print("[WARN] %s 抓取失败: %s" % (label, e))
            return default

    result["财报"] = safe("财报", lambda: fetch_financials(
        days_back=cfg.get("财报回溯天数", 7),
        top_n=cfg.get("财报预喜条数", 10),
        bottom_n=cfg.get("财报爆雷条数", 5)), {"预喜": [], "爆雷": [], "样本数": 0})
    result["解禁"] = safe("解禁", lambda: fetch_unlocks(
        span_days=cfg.get("解禁前瞻天数", 7),
        top_n=cfg.get("解禁条数", 10)), {"今日": [], "临近": [], "样本数": 0})
    result["全球市场"] = safe("全球市场", fetch_global_market, [])
    result["要闻"] = safe("要闻", lambda: fetch_news(
        limit=cfg.get("要闻条数", 12),
        hours=cfg.get("要闻回溯小时", 18)), [])
    result["公告"] = safe("公告", lambda: fetch_announcements(
        limit=cfg.get("公告条数", 12),
        hours=cfg.get("公告回溯小时", 24)), [])
    result["重点关注"] = safe("重点关注", lambda: fetch_merger_announcements(
        limit=cfg.get("重点关注条数", 3),
        hours=cfg.get("重点关注回溯小时", 24),
        pages=cfg.get("重点关注回溯页数", 20)), [])
    result["龙虎榜"] = safe("龙虎榜", lambda: fetch_lhb(
        top_n=cfg.get("龙虎榜买入条数", 6),
        bottom_n=cfg.get("龙虎榜卖出条数", 4),
        days_back=cfg.get("龙虎榜回溯天数", 5)), {"买入": [], "卖出": [], "交易日": "", "样本数": 0})
    return result


if __name__ == "__main__":
    session = sys.argv[1] if len(sys.argv) > 1 else "早报"
    data = build(session)
    path = os.path.join(OUT_DIR, "data_%s_%s.json" % (
        now_cn().strftime("%Y%m%d"), {"早报": "am", "午报": "noon", "晚报": "pm"}.get(session, "am")))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("已写入: %s" % path)
    print("财报: 预喜%d / 爆雷%d (样本%d)" % (
        len(data["财报"]["预喜"]), len(data["财报"]["爆雷"]), data["财报"]["样本数"]))
    print("解禁: 今日%d / 临近%d" % (len(data["解禁"]["今日"]), len(data["解禁"]["临近"])))
    print("全球市场: %d" % len(data["全球市场"]))
    print("要闻: %d | 公告: %d" % (len(data["要闻"]), len(data["公告"])))
