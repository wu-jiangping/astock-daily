# -*- coding: utf-8 -*-
"""
把 fetch_data.py 产出的 JSON 渲染成美观的 HTML 财经简报，
再调用 shot.js 截成 PNG 长图（浅色主题、红涨绿跌、含解读）。
"""
import sys
import os
import json
import subprocess

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "out")
IMG_W = 900

SESSION_META = {
    "早报": ("A股早报", "#b71c1c", "开盘前瞻 · 把握隔夜变量"),
    "午报": ("A股午报", "#e65100", "午间复盘 · 跟踪盘中异动"),
    "晚报": ("A股晚报", "#1a237e", "收盘总结 · 展望明日"),
}
SESSION_TAG = {"早报": "am", "午报": "noon", "晚报": "pm"}


def esc(s):
    return ("" if s is None else str(s)).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def up_down_color(v):
    """红涨绿跌（中国习惯）。"""
    if v is None:
        return "#9e9e9e"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "#9e9e9e"
    if v > 0:
        return "#c62828"
    if v < 0:
        return "#2e7d32"
    return "#666"


def chip(text, color, bg):
    return ('<span class="chip" style="color:%s;background:%s;border-color:%s">%s</span>'
            % (color, bg, color, esc(text)))


def section(num, title, sub=""):
    return ('<div class="sec"><div class="sec-head"><span class="sec-num">%s</span>'
            '<span class="sec-title">%s</span><span class="sec-sub">%s</span></div>'
            % (num, esc(title), esc(sub)))


# ---------------- 全球市场 ----------------
def block_market(m):
    if not m:
        return ""
    cells = []
    for x in m:
        chg = x.get("涨跌幅")
        c = up_down_color(chg)
        arrow = "▲" if (chg or 0) > 0 else ("▼" if (chg or 0) < 0 else "•")
        chg_txt = ("+" if (chg or 0) > 0 else "") + ("%.2f%%" % chg if chg is not None else "—")
        price = x.get("现价")
        cells.append(
            '<div class="mkt"><div class="mkt-name">%s</div>'
            '<div class="mkt-price">%s</div>'
            '<div class="mkt-chg" style="color:%s">%s %s</div></div>'
            % (esc(x.get("名称")), ("%.2f" % price) if price is not None else "—", c, arrow, chg_txt))
    return ('<div class="mkt-wrap"><div class="mkt-title">隔夜全球市场</div>'
            '<div class="mkt-grid">%s</div></div>' % "".join(cells))


# ---------------- 财报 ----------------
def fin_row(x, hot=True):
    np_yoy = x.get("净利润同比")
    rev_yoy = x.get("营收同比")
    eps = x.get("每股收益")
    profit = x.get("净利润")
    rev = x.get("营业收入")
    yoy_c = up_down_color(np_yoy)
    pct_txt = ("+" if (np_yoy or 0) > 0 else "") + ("%.1f%%" % np_yoy if np_yoy is not None else "—")
    profit_txt = money(profit)
    rev_txt = money(rev)
    return ('<div class="frow">'
            '<div class="frow-l"><div class="frow-name">%s<span class="frow-code">%s</span></div>'
            '<div class="frow-sub">%s</div></div>'
            '<div class="frow-m">'
            '<span class="fstat"><label>净利润</label><b>%s</b></span>'
            '<span class="fstat"><label>同比</label><b style="color:%s">%s</b></span>'
            '<span class="fstat"><label>营收</label><b>%s</b></span>'
            '<span class="fstat"><label>EPS</label><b>%s</b></span>'
            '</div>'
            '<div class="frow-r">%s<div class="frow-exp" style="border-left-color:%s">%s</div></div>'
            '</div>'
            % (esc(x.get("名称")), esc(x.get("代码")), esc(x.get("报告期标签") or x.get("报告期") or ""),
               profit_txt, yoy_c, pct_txt, rev_txt,
               ("%.2f" % eps if eps is not None else "—"),
               chip(x.get("标签"), x.get("配色"), "#fff"), x.get("配色"), esc(x.get("解读"))))


def money(v):
    if v is None:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    a = abs(v)
    if a >= 1e8:
        return "%.2f亿" % (v / 1e8)
    if a >= 1e4:
        return "%.2f万" % (v / 1e4)
    return "%.2f" % v


def block_finance(fin):
    喜 = fin.get("预喜") or []
    雷 = fin.get("爆雷") or []
    if not 喜 and not 雷:
        return ""
    out = [section("01", "最新财报", "近7日新披露 · 业绩预喜 / 爆雷")]
    if 喜:
        out.append('<div class="subhead up">▲ 业绩预喜</div>')
        out.append('<div class="card">%s</div>' % "".join(fin_row(x) for x in 喜))
    if 雷:
        out.append('<div class="subhead down">▼ 业绩爆雷 / 亏损</div>')
        out.append('<div class="card">%s</div>' % "".join(fin_row(x, hot=False) for x in 雷))
    out.append('</div>')
    return "".join(out)


# ---------------- 解禁 ----------------
def block_unlock(u):
    今日 = u.get("今日") or []
    临近 = u.get("临近") or []
    allx = 今日 + 临近
    if not allx:
        return ""
    out = [section("02", "限售解禁", "今日 / 未来7日解禁压力")]
    if not 今日:
        out.append('<div class="note">今日无解禁，以下为未来 7 日内临近解禁（按解禁市值排序）</div>')
    rows = []
    for x in allx:
        rows.append(
            '<div class="urow">'
            '<div class="urow-l"><div class="urow-name">%s<span class="urow-code">%s</span></div>'
            '<div class="urow-sub">%s 解禁</div></div>'
            '<div class="urow-m">'
            '<span class="fstat"><label>解禁数量</label><b>%s</b></span>'
            '<span class="fstat"><label>占总股本</label><b>%s</b></span>'
            '<span class="fstat"><label>解禁市值</label><b>%s</b></span>'
            '</div>'
            '<div class="urow-r">%s<div class="urow-exp" style="border-left-color:%s">%s</div></div>'
            '</div>'
            % (esc(x.get("名称")), esc(x.get("代码")), esc(x.get("解禁日期")),
               esc(x.get("解禁数量")), esc(x.get("解禁比例")), esc(x.get("解禁市值")),
               chip(x.get("标签"), x.get("配色"), "#fff"), x.get("配色"), esc(x.get("解读"))))
    out.append('<div class="card">%s</div></div>' % "".join(rows))
    return "".join(out)


# ---------------- 要闻 ----------------
def block_news(news):
    if not news:
        return ""
    out = [section("03", "隔夜全球要闻", "宏观 · 政策 · 海外动态")]
    rows = []
    for x in news:
        rows.append(
            '<div class="nrow">'
            '<div class="nrow-time">%s</div>'
            '<div class="nrow-body">'
            '<div class="nrow-title">%s %s</div>'
            '<div class="nrow-digest">%s</div>'
            '<div class="nrow-meta">%s ｜ <span style="color:%s">%s</span></div>'
            '</div></div>'
            % (esc(x.get("时间")),
               chip(x.get("标签"), x.get("配色"), "#fff"), esc(x.get("标题")),
               esc(x.get("摘要") or ""),
               esc(x.get("来源")), x.get("配色"), esc(x.get("解读"))))
    out.append('<div class="card">%s</div></div>' % "".join(rows))
    return "".join(out)


# ---------------- 公告 ----------------
def block_ann(ann):
    if not ann:
        return ""
    out = [section("04", "公司公告", "重要公告优先")]
    rows = []
    for x in ann:
        rows.append(
            '<div class="arow">'
            '<div class="arow-l"><div class="arow-name">%s<span class="arow-code">%s</span></div>'
            '<div class="arow-time">%s</div></div>'
            '<div class="arow-body">'
            '<div class="arow-title">%s %s</div>'
            '<div class="arow-meta">%s ｜ <span style="color:%s">%s</span></div>'
            '</div></div>'
            % (esc(x.get("名称")), esc(x.get("代码")), esc(x.get("公告时间")),
               chip(x.get("标签"), x.get("配色"), "#fff"), esc(x.get("公告标题")),
               esc(x.get("公告类型") or ""), x.get("配色"), esc(x.get("解读"))))
    out.append('<div class="card">%s</div></div>' % "".join(rows))
    return "".join(out)


def lhb_row(x):
    chg = x.get("涨跌幅")
    net = x.get("净买入")
    seat = x.get("机构家数")
    seat_txt = ("%d家机构买入" % seat) if (seat or 0) > 0 else (
        ("%d家机构卖出" % abs(seat)) if (seat or 0) < 0 else (x.get("席位说明") or "—"))
    net_txt = ("净买入 %s" % money(net)) if (net or 0) > 0 else ("净卖出 %s" % money(abs(net or 0)))
    net_c = up_down_color(net) if net is not None else "#666"
    return ('<div class="frow">'
            '<div class="frow-l"><div class="frow-name">%s<span class="frow-code">%s</span></div>'
            '<div class="frow-sub">%s</div></div>'
            '<div class="frow-m">'
            '<span class="fstat"><label>收盘</label><b>%s</b></span>'
            '<span class="fstat"><label>涨跌</label><b style="color:%s">%s</b></span>'
            '<span class="fstat"><label>资金</label><b style="color:%s">%s</b></span>'
            '<span class="fstat"><label>席位</label><b>%s</b></span>'
            '</div>'
            '<div class="frow-r">%s<div class="frow-exp" style="border-left-color:%s">%s</div></div>'
            '</div>'
            % (esc(x.get("名称")), esc(x.get("代码")), esc(x.get("上榜原因") or ""),
               ("%.2f" % x["收盘价"]) if x.get("收盘价") is not None else "—",
               up_down_color(chg), ("%+.2f%%" % chg) if chg is not None else "—",
               net_c, net_txt, esc(seat_txt),
               chip(x.get("标签"), x.get("配色"), "#fff"), x.get("配色"), esc(x.get("解读"))))


def block_lhb(l):
    买 = l.get("买入") or []
    卖 = l.get("卖出") or []
    if not 买 and not 卖:
        return ""
    day = l.get("交易日") or ""
    out = [section("05", "龙虎榜资金", "%s 主力抢筹 / 资金出逃" % esc(day))]
    if 买:
        out.append('<div class="subhead up">▲ 主力净买入</div>')
        out.append('<div class="card">%s</div>' % "".join(lhb_row(x) for x in 买))
    if 卖:
        out.append('<div class="subhead down">▼ 资金净卖出</div>')
        out.append('<div class="card">%s</div>' % "".join(lhb_row(x) for x in 卖))
    out.append('<div class="note">数据为最近交易日龙虎榜，机构席位参与情况以交易所披露为准</div>')
    out.append('</div>')
    return "".join(out)


# ---------------- 微信版（PushPlus / 手机阅读）----------------
# 微信公众号不支持 flex/grid，这里用 table + 内联样式，并控制总长度
WX_LIMITS = [
    {"财报喜": 5, "财报雷": 3, "解禁": 5, "要闻": 5, "公告": 5, "龙虎买": 4, "龙虎卖": 3},
    {"财报喜": 4, "财报雷": 2, "解禁": 4, "要闻": 4, "公告": 4, "龙虎买": 3, "龙虎卖": 2},
    {"财报喜": 3, "财报雷": 2, "解禁": 3, "要闻": 3, "公告": 3, "龙虎买": 2, "龙虎卖": 2},
    {"财报喜": 3, "财报雷": 1, "解禁": 3, "要闻": 3, "公告": 3, "龙虎买": 2, "龙虎卖": 1},
    {"财报喜": 2, "财报雷": 1, "解禁": 2, "要闻": 2, "公告": 2, "龙虎买": 1, "龙虎卖": 1},
]
# PushPlus 内容按 UTF-8 字节计（中文 1 字 = 3 字节），必须按字节判定
WX_MAX_BYTES = 3600


def _wx_table(headers, rows):
    th = "".join("<th>%s</th>" % h for h in headers)
    trs = []
    for r in rows:
        trs.append("<tr>" + "".join("<td>%s</td>" % c for c in r) + "</tr>")
    return ('<table border="1" cellpadding="3" cellspacing="0" '
            'style="border-collapse:collapse;font-size:13px;width:100%%;'
            'border-color:#ddd">'
            '<tr style="background:#f5f7fa">%s</tr>%s</table>' % (th, "".join(trs)))


def _c(v, txt):
    """红涨绿跌着色。"""
    col = "#c62828" if (v or 0) > 0 else ("#2e7d32" if (v or 0) < 0 else "#666")
    return '<font color="%s">%s</font>' % (col, esc(txt))


def render_wechat(data, session="早报", max_bytes=WX_MAX_BYTES):
    """生成适合微信阅读的紧凑 HTML（自动按 UTF-8 字节降级条数）。"""
    title = SESSION_META.get(session, SESSION_META["早报"])[0]

    def build(lim):
        p = []
        p.append('<div style="font-size:17px;font-weight:bold">%s · %s 星期%s</div>'
                 % (esc(title), esc(data.get("日期")), esc(data.get("星期"))))

        mkt = data.get("全球市场") or []
        if mkt:
            seg = []
            for x in mkt[:6]:
                c = x.get("涨跌幅")
                col = "#c62828" if (c or 0) > 0 else ("#2e7d32" if (c or 0) < 0 else "#666")
                seg.append('%s <font color="%s">%+.2f%%</font>' % (esc(x["名称"]), col, c or 0))
            p.append('<div style="font-size:13px;color:#555;margin:6px 0">'
                     '<b>隔夜海外</b>：%s</div>' % " ｜ ".join(seg))

        # 财报
        fin = data.get("财报") or {}
        喜 = (fin.get("预喜") or [])[:lim["财报喜"]]
        雷 = (fin.get("爆雷") or [])[:lim["财报雷"]]
        if 喜 or 雷:
            p.append("<h3>01 最新财报</h3>")
            rows = []
            for x in 喜 + 雷:
                rows.append([
                    "%s<br><font color=\"#999\">%s</font>" % (esc(x.get("名称")), esc(x.get("代码"))),
                    _c(x.get("净利润同比"), "%+.1f%%" % x["净利润同比"] if x.get("净利润同比") is not None else "—"),
                    '<font color="%s"><b>%s</b></font>' % (x.get("配色"), esc(x.get("标签"))),
                ])
            p.append(_wx_table(["名称", "净利同比", "解读"], rows))

        # 解禁
        un = data.get("解禁") or {}
        ul = ((un.get("今日") or []) + (un.get("临近") or []))[:lim["解禁"]]
        if ul:
            p.append("<h3>02 限售解禁</h3>")
            rows = [[
                "%s<br><font color=\"#999\">%s</font>" % (esc(x.get("名称")), esc(x.get("代码"))),
                esc(x.get("解禁日期") or "")[5:],
                esc(x.get("解禁比例") or "—"),
                '<font color="%s"><b>%s</b></font>' % (x.get("配色"), esc(x.get("标签"))),
            ] for x in ul]
            p.append(_wx_table(["名称", "日期", "占总股本", "解读"], rows))

        # 要闻
        nw = (data.get("要闻") or [])[:lim["要闻"]]
        if nw:
            p.append("<h3>03 隔夜要闻</h3>")
            rows = [[
                esc(x.get("时间")),
                esc(x.get("标题"))[:34],
                '<font color="%s">%s</font>' % (x.get("配色"), esc(x.get("标签"))),
            ] for x in nw]
            p.append(_wx_table(["时间", "标题", "解读"], rows))

        # 公告
        an = (data.get("公告") or [])[:lim["公告"]]
        if an:
            p.append("<h3>04 公司公告</h3>")
            rows = [[
                "%s<br><font color=\"#999\">%s</font>" % (esc(x.get("名称")), esc(x.get("代码"))),
                esc(x.get("公告标题"))[:30],
                '<font color="%s">%s</font>' % (x.get("配色"), esc(x.get("标签"))),
            ] for x in an]
            p.append(_wx_table(["公司", "公告", "解读"], rows))

        # 龙虎榜
        lhb = data.get("龙虎榜") or {}
        买 = (lhb.get("买入") or [])[:lim["龙虎买"]]
        卖 = (lhb.get("卖出") or [])[:lim["龙虎卖"]]
        if 买 or 卖:
            p.append("<h3>05 龙虎榜资金</h3>")
            rows = []
            for x in 买 + 卖:
                net = x.get("净买入") or 0
                rows.append([
                    "%s<br><font color=\"#999\">%s</font>" % (esc(x.get("名称")), esc(x.get("代码"))),
                    _c(net, money(net)),
                    _c(x.get("涨跌幅"), "%+.2f%%" % x["涨跌幅"] if x.get("涨跌幅") is not None else "—"),
                    '<font color="%s">%s</font>' % (x.get("配色"), esc(x.get("标签"))),
                ])
            p.append(_wx_table(["名称", "净买入", "涨跌", "解读"], rows))

        p.append('<div style="font-size:12px;color:#999;margin-top:10px">'
                 '数据源：东方财富/新浪财经｜解读为程序化规则判断，不构成投资建议</div>')
        return "".join(p)

    for lim in WX_LIMITS:
        html = build(lim)
        if len(html.encode("utf-8")) <= max_bytes:
            return html
    # 兜底：仍超限则按字节硬截断（保证不破坏标签结构地丢尾部）
    html = build(WX_LIMITS[-1])
    raw = html.encode("utf-8")
    if len(raw) > max_bytes:
        cut = raw[:max_bytes].decode("utf-8", errors="ignore")
        cut = cut.rsplit("<", 1)[0] + "</div>"
        return cut
    return html


CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Microsoft YaHei','PingFang SC',sans-serif; background:#eef1f5;
       color:#26292e; -webkit-font-smoothing:antialiased; width:%dpx; }
.page { padding:0 0 24px 0; }
.top { background:linear-gradient(135deg,%s 0%%,#37474f 100%%); color:#fff; padding:30px 34px 26px; }
.top-title { font-size:34px; font-weight:800; letter-spacing:1px; }
.top-sub { margin-top:8px; font-size:14px; opacity:.92; }
.top-date { margin-top:14px; font-size:13px; opacity:.85; display:flex; gap:14px; }
.mkt-wrap { margin:16px 20px 0; background:#fff; border-radius:14px; padding:16px 18px;
            box-shadow:0 2px 10px rgba(0,0,0,.05); }
.mkt-title { font-size:15px; font-weight:700; color:#37474f; margin-bottom:12px;
             padding-left:9px; border-left:4px solid %s; }
.mkt-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }
.mkt { background:#f7f9fb; border-radius:10px; padding:12px 10px; text-align:center;
       border:1px solid #eef2f6; }
.mkt-name { font-size:12px; color:#7a8694; }
.mkt-price { font-size:17px; font-weight:800; margin:6px 0 4px; color:#222; }
.mkt-chg { font-size:13px; font-weight:700; }
.sec { margin:20px 20px 0; }
.sec-head { display:flex; align-items:center; margin-bottom:12px; }
.sec-num { background:%s; color:#fff; font-weight:800; font-size:14px; border-radius:8px;
           padding:4px 10px; margin-right:10px; }
.sec-title { font-size:20px; font-weight:800; color:#263238; }
.sec-sub { margin-left:12px; font-size:12px; color:#9aa5af; }
.card { background:#fff; border-radius:14px; padding:6px 18px;
        box-shadow:0 2px 10px rgba(0,0,0,.05); }
.subhead { font-size:14px; font-weight:700; margin:6px 4px 10px; }
.subhead.up { color:#c62828; } .subhead.down { color:#2e7d32; }
.note { font-size:12px; color:#8a939c; margin:0 4px 10px; }
.chip { display:inline-block; font-size:11px; font-weight:700; padding:2px 8px;
        border-radius:6px; border:1px solid; margin-right:6px; white-space:nowrap; }
.fstat label { color:#9aa5af; font-size:11px; font-weight:400; margin-right:4px; }
.fstat b { font-weight:700; font-size:14px; }
.frow,.urow { display:flex; align-items:center; gap:12px; padding:13px 0; border-bottom:1px dashed #edf0f3; }
.frow:last-child,.urow:last-child { border-bottom:none; }
.frow-l,.urow-l { width:150px; flex:none; }
.frow-name,.urow-name { font-size:15px; font-weight:800; color:#263238; }
.frow-code,.urow-code { color:#b0b8c1; font-size:12px; margin-left:6px; font-weight:400; }
.frow-sub,.urow-sub { font-size:11px; color:#9aa5af; margin-top:3px; }
.frow-m,.urow-m { flex:1; display:flex; flex-direction:column; gap:4px; }
.frow-r,.urow-r { width:300px; flex:none; display:flex; flex-direction:column; gap:5px; align-items:flex-start; }
.frow-exp,.urow-exp { font-size:11.5px; color:#5b6470; line-height:1.5;
                      border-left:3px solid; padding-left:8px; }
.nrow { display:flex; gap:12px; padding:12px 0; border-bottom:1px dashed #edf0f3; }
.nrow:last-child { border-bottom:none; }
.nrow-time { flex:none; width:64px; color:#9aa5af; font-size:12px; font-weight:700; padding-top:2px; }
.nrow-body { flex:1; }
.nrow-title { font-size:14.5px; font-weight:700; color:#263238; line-height:1.4; margin-bottom:4px; }
.nrow-digest { font-size:12px; color:#707b86; line-height:1.5; margin-bottom:5px; }
.nrow-meta { font-size:11px; color:#a2acb6; }
.arow { display:flex; gap:12px; padding:12px 0; border-bottom:1px dashed #edf0f3; align-items:flex-start; }
.arow:last-child { border-bottom:none; }
.arow-l { flex:none; width:120px; }
.arow-name { font-size:14.5px; font-weight:800; color:#263238; }
.arow-code { color:#b0b8c1; font-size:11px; margin-left:5px; font-weight:400; }
.arow-time { font-size:11px; color:#9aa5af; margin-top:3px; }
.arow-body { flex:1; }
.arow-title { font-size:14px; font-weight:700; color:#263238; line-height:1.4; margin-bottom:4px; }
.arow-meta { font-size:11px; color:#a2acb6; }
.foot { margin:22px 20px 0; text-align:center; color:#a8b2bb; font-size:11px; line-height:1.7; }
.foot b { color:#8a939c; }
"""


def render(data, session="早报"):
    title, color, slogan = SESSION_META.get(session, SESSION_META["早报"])
    top = ('<div class="top"><div class="top-title">%s</div>'
           '<div class="top-sub">%s</div>'
           '<div class="top-date"><span>%s</span><span>星期%s</span><span>生成于 %s</span></div></div>'
           % (title, slogan, esc(data.get("日期")), esc(data.get("星期")), esc(data.get("生成时间"))))

    parts = [top, block_market(data.get("全球市场")),
             block_finance(data.get("财报") or {}),
             block_unlock(data.get("解禁") or {}),
             block_news(data.get("要闻")),
             block_ann(data.get("公告")),
             block_lhb(data.get("龙虎榜") or {})]

    foot = ('<div class="foot">数据源：东方财富 / 新浪财经 ｜ <b>解读为程序化规则判断，仅供研究参考，不构成投资建议</b><br/>'
            'A股每日财经简报 · 自动生成 · 红涨绿跌</div>')

    html = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"/>'
            '<meta name="viewport" content="width=device-width"/>'
            '<style>%s</style></head><body><div class="page">%s</div></body></html>'
            % (CSS % (IMG_W, color, color, color), "".join(parts) + foot))
    return html


def build_image(data, session="早报", out_png=None):
    tag = SESSION_TAG.get(session, "am")
    day = (data.get("日期") or "unknown").replace("-", "")
    html_path = os.path.join(OUT_DIR, "report_%s_%s.html" % (day, tag))
    if out_png is None:
        out_png = os.path.join(OUT_DIR, "report_%s_%s.png" % (day, tag))
    html = render(data, session)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    shot = os.path.join(BASE_DIR, "shot.js")
    r = subprocess.run(["node", shot, html_path, out_png, str(IMG_W)],
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    if r.returncode != 0 or not os.path.exists(out_png):
        raise RuntimeError("截图失败: %s %s" % (r.stdout.strip(), r.stderr.strip()))
    return html_path, out_png


if __name__ == "__main__":
    session = sys.argv[1] if len(sys.argv) > 1 else "早报"
    tag = SESSION_TAG.get(session, "am")
    data_path = os.path.join(OUT_DIR, "data_%s_%s.json" % (
        __import__("datetime").datetime.now().strftime("%Y%m%d"), tag))
    with open(data_path, encoding="utf-8") as f:
        d = json.load(f)
    h, p = build_image(d, session)
    print("HTML:", h)
    print("PNG :", p)
