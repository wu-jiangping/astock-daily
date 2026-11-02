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
POS_WORDS = ["增持", "回购", "中标", "分红", "预增", "扭亏", "股权激励", "战略合作",
             "获批", "通过", "签署", "突破", "创新高", "超额", "涨价", "产能扩张",
             "大涨", "上涨", "降息", "降准", "刺激", "超预期", "增长", "回暖", "复苏",
             "新高", "利好", "扩张", "投产", "增持计划", "回购注销", "订单", "提价"]
NEG_WORDS = ["减持", "预亏", "亏损", "诉讼", "问询", "警示", "质押", "冻结", "退市",
             "立案", "辞职", "减值", "违规", "担保", "处罚", "终止", "下修", "跌停",
             "大跌", "下跌", "暴跌", "加息", "通胀", "衰退", "制裁", "关税", "冲突",
             "不及预期", "裁员", "风险", "下滑", "回落", "承压", "爆雷", "商誉", "占用"]


def score_text(text):
    """文本利好/利空打分。返回 (score, hits)"""
    t = str(text or "")
    pos = [(w, t.count(w)) for w in POS_WORDS if w in t]
    neg = [(w, t.count(w)) for w in NEG_WORDS if w in t]
    s = sum(c for _, c in pos) - sum(c for _, c in neg)
    hits = [w for w, _ in pos][:3] + [w for w, _ in neg][:3]
    return s, hits


def judge(score, strong=2, weak=1):
    """把分数映射成 档位 / 文案 / 颜色。文案为纯文字，不带星号等装饰符号。"""
    if score >= strong + 1:
        return "利好", "重大利好", "#c62828"
    if score >= strong:
        return "利好", "利好", "#c62828"
    if score >= weak:
        return "偏多", "小幅利好", "#e57373"
    if score <= -(strong + 1):
        return "利空", "重大利空", "#2e7d32"
    if score <= -strong:
        return "利空", "利空", "#2e7d32"
    if score <= -weak:
        return "偏空", "小幅利空", "#66bb6a"
    return "中性", "中性，影响有限", "#8e8e8e"


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
        txt = "%s：业绩大幅改善，%s，短线资金关注度高。" % (label, 基础)
    elif s >= 1:
        txt = "%s：业绩稳中有进，%s。" % (label, 基础)
    elif s <= -2:
        txt = "%s：业绩承压，%s，注意回避。" % (label, 基础)
    elif s <= -1:
        txt = "%s：业绩小幅走弱，%s。" % (label, 基础)
    else:
        txt = "%s：%s。" % (label, 基础)
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
        txt = "%s：解禁占总股本 %s，规模大，抛压预期强，短期回避。" % (label, pct(ratio_pct))
    elif s <= -2:
        txt = "%s：解禁占总股本 %s，有一定减持压力。" % (label, pct(ratio_pct))
    elif s == -1:
        txt = "%s：解禁占总股本 %s，压力有限但需留意。" % (label, pct(ratio_pct))
    else:
        txt = "%s：解禁占总股本 %s，占比很小，影响基本可忽略。" % (label, pct(ratio_pct))
    if cap_yi and cap_yi >= 50:
        txt += " 解禁市值约 %.1f 亿元，体量偏大。" % cap_yi
    return tag, label, color, txt


def explain_news(title, digest):
    s, hits = score_text(title)
    s2, hits2 = score_text(digest or "")
    s = s + (s2 * 1 if s2 else 0)
    tag, label, color = judge(s)
    hint = ("关键词：" + "、".join(list(dict.fromkeys(hits + hits2))[:4])) if (hits or hits2) else "暂无明显多空信号"
    txt = "%s，%s" % (label, hint)
    return tag, label, color, txt


def explain_announce(title):
    s, hits = score_text(title)
    tag, label, color = judge(s)
    hint = ("关键词：" + "、".join(list(dict.fromkeys(hits))[:4])) if hits else "常规披露，无显著多空信号"
    txt = "%s，%s" % (label, hint)
    return tag, label, color, txt


# ---------------------------------------------------------------- 1. 最新财报
def fetch_financials(days_back=7, top_n=10, bottom_n=5):
    """抓取最近 days_back 天内新披露的财报（业绩报表 RPT_LICO_FN_CPD）。
    返回：业绩预喜 Top + 业绩爆雷 Bottom。"""
    today = now_cn().date()
    since = today - timedelta(days=days_back)
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
    end = today + timedelta(days=span_days)
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
        "临近": 临近[:max(0, top_n - len(今日))],
        "样本数": len(items),
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
        cutoff = now_cn() - timedelta(hours=hrs)
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
        cutoff = now_cn() - timedelta(hours=hrs)
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
        txt = "%s：%s，机构资金介入明显，短线可跟踪。" % (label, detail)
    elif s >= 1:
        txt = "%s：%s，买方占优。" % (label, detail)
    elif s <= -3:
        txt = "%s：%s，资金出逃明显，注意风险。" % (label, detail)
    elif s <= -1:
        txt = "%s：%s，卖方占优。" % (label, detail)
    else:
        txt = "%s：%s，多空均衡。" % (label, detail)
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
    return {"买入": 买入, "卖出": 卖出, "交易日": latest, "样本数": len(items),
            "是否当日": latest == today.isoformat()}


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
