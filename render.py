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
SESSION_EN = {"早报": "AM", "午报": "MD", "晚报": "PM"}


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


CHIP_BG = {"#c62828": "#fdecec", "#e57373": "#fdf1f1", "#2e7d32": "#e9f5ea",
           "#66bb6a": "#eef7ef", "#8e8e8e": "#f1f3f5"}


def chip(text, color=None, bg=None):
    """圆角胶囊标签：浅色底 + 同色细边，比纯白底描边更精致。"""
    c = color if (isinstance(color, str) and len(color) == 7 and color.startswith("#")) else "#8e8e8e"
    return ('<span class="chip" style="color:%s;background:%s;border-color:%s33">%s</span>'
            % (c, CHIP_BG.get(c, "#f2f5f8"), c, esc(text)))


def section(num, title, sub=""):
    """板块头：渐变编号徽章 + 主副标题双层 + 右侧渐隐分隔线。"""
    sub_html = ('<span class="sec-sub">%s</span>' % esc(sub)) if sub else ""
    return ('<div class="sec"><div class="sec-head">'
            '<span class="sec-num">%s</span>'
            '<span class="sec-txt"><span class="sec-title">%s</span>%s</span>'
            '<span class="sec-line"></span></div>'
            % (num, esc(title), sub_html))


# ---------------- 全球市场 ----------------
def block_market(m, session="早报"):
    if not m:
        return ""
    cells = []
    up = down = flat = 0
    for x in m:
        chg = x.get("涨跌幅")
        v = chg or 0
        c = up_down_color(chg)
        if v > 0:
            up += 1
        elif v < 0:
            down += 1
        else:
            flat += 1
        arrow = "▲" if v > 0 else ("▼" if v < 0 else "•")
        chg_txt = ("+" if v > 0 else "") + ("%.2f%%" % chg if chg is not None else "—")
        if v > 0:
            bg, bar = "#fdecec", "#e57373"
        elif v < 0:
            bg, bar = "#e8f5e9", "#66bb6a"
        else:
            bg, bar = "#f1f4f8", "#cfd8e3"
        width = min(100, 10 + abs(v) * 12)
        price = x.get("现价")
        cells.append(
            '<div class="mkt" style="border-top-color:%s">'
            '<div class="mkt-name">%s</div>'
            '<div class="mkt-price">%s</div>'
            '<div class="mkt-chg" style="color:%s;background:%s">%s %s</div>'
            '<div class="mkt-bar"><i style="width:%.0f%%;background:%s"></i></div></div>'
            % (bar, esc(x.get("名称")), ("%.2f" % price) if price is not None else "—",
               c, bg, arrow, chg_txt, width, bar))
    title = "隔夜全球市场" if session == "早报" else "全球市场行情"
    hint = "涨 %d · 跌 %d · 平 %d" % (up, down, flat)
    cols = 5 if len(m) >= 10 else 4
    return ('<div class="mkt-wrap"><div class="mkt-head"><div class="mkt-title">%s</div>'
            '<div class="mkt-hint">%s</div></div>'
            '<div class="mkt-grid" style="grid-template-columns:repeat(%d,1fr)">%s</div></div>'
            % (title, hint, cols, "".join(cells)))


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
    out = [section("01", "最新财报", "仅当日新披露 · 业绩预喜 / 爆雷")]
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
    out = [section("02", "限售解禁", "当日解禁")]
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
def block_news(news, session="早报"):
    if not news:
        return ""
    title = "隔夜全球要闻" if session == "早报" else "今日要闻"
    out = [section("03", title, "宏观 · 政策 · 海外动态")]
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


# ---------------- 重点关注 ----------------
def block_focus(focus):
    """重点关注：当日新增的相关公告，中性样式呈现（不特意标红）。"""
    if not focus:
        return ""
    out = [section("重", "重点关注", "仅当日新增")]
    rows = []
    for x in focus:
        role = x.get("角色") or "相关公告"
        rows.append(
            '<div class="focus-row">'
            '<div class="focus-l"><div class="focus-name">%s<span class="arow-code">%s</span></div>'
            '<div class="focus-time">%s</div></div>'
            '<div class="focus-body"><div class="focus-title">%s</div>'
            '<div><span class="focus-tag">重大利好</span>'
            '<span class="focus-role">%s</span>'
            '<span class="focus-note">关注方案进度与监管审核；以公司公告为准</span></div>'
            '</div></div>'
            % (esc(x.get("名称")), esc(x.get("代码")), esc(x.get("公告时间")),
               esc(x.get("公告标题")), esc(role)))
    out.append('<div class="focus-card">%s</div></div>' % "".join(rows))
    return "".join(out)


# ---------------- 公告 ----------------
def block_ann(ann):
    if not ann:
        return ""
    out = [section("04", "公司公告", "仅当日新增 · 按时效排序")]
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
    if day and l.get("是否当日"):
        tag = "当日数据 %s（收盘后披露）" % esc(day)
        note = "交易所盘后披露的当日龙虎榜；机构席位情况以交易所披露为准"
    elif day:
        tag = "当日尚未披露 · 展示最近交易日 %s" % esc(day)
        note = "当日龙虎榜要收盘后才陆续披露，本期生成时尚未入库，故展示最近一个交易日数据；以交易所披露为准"
    else:
        tag = "最近交易日"
        note = "龙虎榜在收盘后才更新；机构席位情况以交易所披露为准"
    out = [section("05", "龙虎榜资金", "%s 主力抢筹 / 资金出逃" % tag)]
    if 买:
        out.append('<div class="subhead up">▲ 主力净买入</div>')
        out.append('<div class="card">%s</div>' % "".join(lhb_row(x) for x in 买))
    if 卖:
        out.append('<div class="subhead down">▼ 资金净卖出</div>')
        out.append('<div class="card">%s</div>' % "".join(lhb_row(x) for x in 卖))
    out.append('<div class="note">%s</div>' % note)
    out.append('</div>')
    return "".join(out)


# ---------------- 微信版（PushPlus / 手机阅读）----------------
# 微信公众号不支持 flex/grid，这里用 table + 内联样式，并控制总长度
WX_LIMITS = [
    {"财报喜": 5, "财报雷": 3, "解禁": 5, "要闻": 5, "公告": 5, "龙虎买": 4, "龙虎卖": 3, "重点": 2},
    {"财报喜": 4, "财报雷": 2, "解禁": 4, "要闻": 4, "公告": 4, "龙虎买": 3, "龙虎卖": 2, "重点": 2},
    {"财报喜": 3, "财报雷": 2, "解禁": 3, "要闻": 3, "公告": 3, "龙虎买": 2, "龙虎卖": 2, "重点": 1},
    {"财报喜": 3, "财报雷": 1, "解禁": 3, "要闻": 3, "公告": 3, "龙虎买": 2, "龙虎卖": 1, "重点": 1},
    {"财报喜": 2, "财报雷": 1, "解禁": 2, "要闻": 2, "公告": 2, "龙虎买": 1, "龙虎卖": 1, "重点": 1},
    {"财报喜": 2, "财报雷": 1, "解禁": 1, "要闻": 1, "公告": 1, "龙虎买": 1, "龙虎卖": 0, "重点": 1},
    {"财报喜": 1, "财报雷": 1, "解禁": 1, "要闻": 1, "公告": 1, "龙虎买": 1, "龙虎卖": 0, "重点": 1},
    {"财报喜": 1, "财报雷": 0, "解禁": 1, "要闻": 1, "公告": 1, "龙虎买": 0, "龙虎卖": 0, "重点": 1},
]
# PushPlus 内容按 UTF-8 字节计（中文 1 字 = 3 字节），必须按字节判定
WX_MAX_BYTES = 3600
WX_FOOT = ('<div style="font-size:12px;color:#999;margin-top:12px;'
           'border-top:1px solid #eee;padding-top:8px">'
           '数据源：东方财富/新浪财经｜解读为程序化规则判断，不构成投资建议</div>')


def _wx_table(headers, rows):
    th = "".join("<th>%s</th>" % h for h in headers)
    trs = []
    for r in rows:
        trs.append("<tr>" + "".join("<td>%s</td>" % c for c in r) + "</tr>")
    return ('<table border="1" cellpadding="5" cellspacing="0" '
            'style="border-collapse:collapse;font-size:13px;width:100%%;'
            'border-color:#e3e9f0">'
            '<tr style="background:#eaf0f6;color:#37474f">%s</tr>%s</table>'
            % (th, "".join(trs)))


def _c(v, txt):
    """红涨绿跌着色。"""
    col = "#c62828" if (v or 0) > 0 else ("#2e7d32" if (v or 0) < 0 else "#666")
    return '<font color="%s">%s</font>' % (col, esc(txt))


def render_wechat(data, session="早报", max_bytes=WX_MAX_BYTES):
    """生成适合微信阅读的紧凑 HTML（自动按 UTF-8 字节降级条数）。"""
    title, theme, _slogan = SESSION_META.get(session, SESSION_META["早报"])

    def build(lim):
        p = []
        p.append('<div style="padding:9px 12px;margin-bottom:8px;border-radius:8px;'
                 'background:%s;color:#fff;font-size:16px;font-weight:bold">'
                 '%s · %s 星期%s</div>'
                 % (theme, esc(title), esc(data.get("日期")), esc(data.get("星期"))))

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
            p.append("<h3>%s</h3>" % ("03 隔夜要闻" if data.get("场次") == "早报" else "03 今日要闻"))
            rows = [[
                esc(x.get("时间")),
                esc(x.get("标题"))[:34],
                '<font color="%s">%s</font>' % (x.get("配色"), esc(x.get("标签"))),
            ] for x in nw]
            p.append(_wx_table(["时间", "标题", "解读"], rows))

        # 重点关注
        focus = (data.get("重点关注") or [])[:lim.get("重点", 2)]
        if focus:
            p.append("<h3>重点关注</h3>")
            frows = [[
                "%s<br><font color=\"#999\">%s</font>" % (esc(x.get("名称")), esc(x.get("代码"))),
                "%s<br><font color=\"#999\">%s</font>" % (
                    esc(x.get("公告标题"))[:30], esc((x.get("角色") or "").split(" / ")[0])),
                '<font color="#666">重大利好</font>',
            ] for x in focus]
            p.append(_wx_table(["公司", "公告 / 角色", "标签"], frows))

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
            d = lhb.get("交易日") or ""
            mark = "当日 %s" % d if lhb.get("是否当日") else ("当日未披露 · %s" % d if d else "最近交易日")
            p.append("<h3>05 龙虎榜资金（%s）</h3>" % esc(mark))
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

        p.append(WX_FOOT)
        return "".join(p)

    for lim in WX_LIMITS:
        html = build(lim)
        if len(html.encode("utf-8")) <= max_bytes:
            return html
    # 兜底：仍超限则按字节硬截断，但预留尾部免责声明，避免整段被截掉
    html = build(WX_LIMITS[-1])
    raw = html.encode("utf-8")
    if len(raw) > max_bytes:
        tail = "</div>"
        reserve = len((tail + WX_FOOT).encode("utf-8"))
        room = max(0, max_bytes - reserve)
        cut = raw[:room].decode("utf-8", errors="ignore")
        cut = cut.rsplit("<", 1)[0]
        return cut + tail + WX_FOOT
    return html


CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Microsoft YaHei','PingFang SC','Noto Sans CJK SC',sans-serif;
       background:#eef2f7; color:#1f2a37; -webkit-font-smoothing:antialiased; width:__IMG_W__px; }
.page { padding:0 0 26px; }
.num, .mkt-price, .mkt-chg, .fstat b, .frow-code, .urow-code, .arow-code,
.nrow-time, .arow-time, .focus-time { font-family:'DIN Alternate','Bahnschrift','Segoe UI',Consolas,sans-serif;
       font-variant-numeric:tabular-nums; letter-spacing:.2px; }

/* ---------- 页头 ---------- */
.top { position:relative; overflow:hidden; padding:26px 36px 30px; color:#fff;
       background:radial-gradient(circle at 86% 8%,rgba(255,255,255,.18) 0,rgba(255,255,255,0) 46%),
                  linear-gradient(118deg,__THEME__ 0%,#1b2b45 58%,#101a2b 100%); }
.top::before { content:""; position:absolute; inset:0; pointer-events:none;
       background-image:linear-gradient(rgba(255,255,255,.045) 1px,transparent 1px),
                        linear-gradient(90deg,rgba(255,255,255,.045) 1px,transparent 1px);
       background-size:30px 30px; }
.top::after { content:""; position:absolute; left:0; right:0; bottom:0; height:4px;
       background:linear-gradient(90deg,#ef5350 0%,#ffa726 34%,#42a5f5 68%,rgba(255,255,255,.9) 100%); }
.top-brand { position:relative; display:flex; align-items:center; justify-content:space-between; }
.brand-l { display:flex; align-items:center; gap:9px; }
.brand-mark { width:23px; height:23px; border-radius:7px; display:flex; align-items:center;
       justify-content:center; font-size:12px; font-weight:800;
       background:rgba(255,255,255,.16); border:1px solid rgba(255,255,255,.38); }
.brand-txt { font-size:10.5px; letter-spacing:2.6px; font-weight:700; opacity:.82; }
.brand-tag { font-size:11px; letter-spacing:1.4px; padding:4px 13px; border-radius:20px;
       background:rgba(255,255,255,.13); border:1px solid rgba(255,255,255,.26); }
.top-wm { position:absolute; right:26px; top:48px; font-size:118px; font-weight:900;
       letter-spacing:4px; line-height:1; color:rgba(255,255,255,.065); pointer-events:none; }
.top-title { position:relative; margin-top:22px; font-size:38px; font-weight:800;
       letter-spacing:3px; text-shadow:0 2px 12px rgba(0,0,0,.18); }
.top-sub { position:relative; margin-top:9px; font-size:13.5px; opacity:.9; letter-spacing:.6px; }
.top-date { position:relative; display:flex; gap:9px; margin-top:17px; }
.top-date span { font-size:12px; padding:5px 11px; border-radius:7px;
       background:rgba(255,255,255,.1); border:1px solid rgba(255,255,255,.17); }

/* ---------- 全球市场 ---------- */
.mkt-wrap { position:relative; overflow:hidden; margin:18px 20px 0; padding:16px 18px 17px;
       background:#fff; border:1px solid #e7edf4; border-radius:16px;
       box-shadow:0 6px 22px rgba(31,45,61,.06); }
.mkt-wrap::before { content:""; position:absolute; left:0; top:0; right:0; height:3px;
       background:linear-gradient(90deg,__THEME__,rgba(255,255,255,0)); }
.mkt-head { display:flex; align-items:baseline; justify-content:space-between; margin-bottom:13px; }
.mkt-title { font-size:15px; font-weight:800; color:#243447; padding-left:11px;
       border-left:4px solid __THEME__; }
.mkt-hint { font-size:11px; color:#a3afbb; letter-spacing:.4px; }
.mkt-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:11px; }
.mkt { position:relative; padding:12px 12px 11px; border-radius:12px; overflow:hidden;
       background:linear-gradient(180deg,#fcfdff 0%,#f5f8fc 100%); border:1px solid #e9eef4;
       border-top:2px solid #dfe6ee; }
.mkt-name { font-size:12px; color:#7b8896; font-weight:600; }
.mkt-price { margin:7px 0 6px; font-size:19px; font-weight:800; color:#1f2a37; }
.mkt-chg { display:inline-block; font-size:12px; font-weight:800; padding:2px 9px; border-radius:6px; }
.mkt-bar { height:3px; margin-top:10px; border-radius:3px; background:#e9eef4; overflow:hidden; }
.mkt-bar i { display:block; height:100%; border-radius:3px; }

/* ---------- 板块 ---------- */
.sec { margin:24px 20px 0; }
.sec-head { display:flex; align-items:center; gap:11px; margin-bottom:12px; }
.sec-num { flex:none; padding:6px 11px; border-radius:9px; color:#fff; font-size:13px;
       font-weight:800; letter-spacing:.6px; background:linear-gradient(135deg,__THEME__,#37474f);
       box-shadow:0 3px 9px rgba(26,35,90,.2); }
.sec-txt { display:flex; flex-direction:column; gap:3px; min-width:0; }
.sec-title { font-size:21px; font-weight:800; color:#1f2a37; letter-spacing:.6px; line-height:1.15; }
.sec-sub { font-size:11.5px; color:#95a2ae; line-height:1.35; }
.sec-line { flex:1; height:1px; align-self:center;
       background:linear-gradient(90deg,#dbe4ee,rgba(219,228,238,0)); }
.card { padding:4px 18px; background:#fff; border:1px solid #e7edf4; border-radius:16px;
       box-shadow:0 6px 20px rgba(31,45,61,.055); }
.subhead { font-size:13.5px; font-weight:800; margin:12px 4px 8px; letter-spacing:.4px; }
.subhead.up { color:#c62828; } .subhead.down { color:#2e7d32; }
.note { margin:9px 4px 2px; font-size:11.5px; color:#95a2ae; line-height:1.6; }
.chip { display:inline-block; padding:3px 10px; border-radius:20px; font-size:11px;
       font-weight:800; border:1px solid; white-space:nowrap; letter-spacing:.2px; margin-right:6px; }
.fstat label { margin-right:5px; font-size:11px; color:#a3afbb; font-weight:400; }
.fstat b { font-size:14px; font-weight:800; color:#33414f; }
.frow,.urow { display:flex; align-items:center; gap:14px; padding:14px 2px;
       border-bottom:1px solid #f0f3f7; }
.frow:last-child,.urow:last-child { border-bottom:none; }
.frow-l,.urow-l { flex:none; width:150px; }
.frow-name,.urow-name,.arow-name,.focus-name { font-size:15px; font-weight:800; color:#1f2a37; }
.frow-code,.urow-code,.arow-code { display:inline-block; margin-left:6px; padding:1px 6px;
       border-radius:5px; background:#f1f4f8; color:#94a1ae; font-size:11px; font-weight:600; }
.frow-sub,.urow-sub { margin-top:5px; font-size:11px; color:#9aa7b4; line-height:1.45;
       display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:2; overflow:hidden; }
.frow-m,.urow-m { flex:1; display:flex; flex-direction:column; gap:5px; }
.frow-r,.urow-r { flex:none; width:300px; display:flex; flex-direction:column;
       gap:6px; align-items:flex-start; }
.frow-exp,.urow-exp { padding:6px 9px; border-left:3px solid; border-radius:0 7px 7px 0;
       background:#f7f9fc; font-size:11.5px; color:#5c6976; line-height:1.55; }

/* ---------- 要闻 / 公告 ---------- */
.nrow { display:flex; gap:14px; padding:14px 2px; border-bottom:1px solid #f0f3f7; }
.nrow:last-child,.arow:last-child { border-bottom:none; }
.nrow-time { position:relative; flex:none; width:70px; padding-left:11px; font-size:12px;
       font-weight:800; color:#7b8896; border-left:2px solid #e3eaf2; }
.nrow-time::before { content:""; position:absolute; left:-4px; top:5px; width:6px; height:6px;
       border-radius:50%; background:__THEME__; box-shadow:0 0 0 3px rgba(26,35,126,.09); }
.nrow-body { flex:1; }
.nrow-title { margin-bottom:5px; font-size:14.5px; font-weight:700; color:#243447; line-height:1.5; }
.nrow-digest { margin-bottom:7px; font-size:12px; color:#788592; line-height:1.6; }
.nrow-meta,.arow-meta { display:inline-block; padding:5px 9px; border-radius:6px;
       background:#f7f9fc; font-size:11px; color:#8b98a5; line-height:1.5; }
.arow { display:flex; gap:14px; padding:14px 2px; border-bottom:1px solid #f0f3f7; align-items:flex-start; }
.arow-l { flex:none; width:126px; }
.arow-time { display:inline-block; margin-top:5px; padding:2px 7px; border-radius:5px;
       background:#f1f4f8; font-size:11px; color:#94a1ae; }
.arow-body { flex:1; }
.arow-title { margin-bottom:6px; font-size:14px; font-weight:700; color:#243447; line-height:1.5; }

/* ---------- 重点关注（中性样式，不标红） ---------- */
.focus-card { padding:4px 18px; background:#fbfcfd; border:1px solid #e5ebf1;
       border-left:4px solid #b0bec5; border-radius:14px; }
.focus-row { display:flex; gap:14px; padding:14px 2px; border-bottom:1px solid #eef1f4; align-items:flex-start; }
.focus-row:last-child { border-bottom:none; }
.focus-l { flex:none; width:126px; }
.focus-time { margin-top:5px; font-size:11px; color:#9aa7b4; }
.focus-body { flex:1; }
.focus-title { margin-bottom:7px; font-size:14px; font-weight:700; color:#243447; line-height:1.5; }
.focus-tag { display:inline-block; margin-right:6px; padding:3px 10px; border-radius:20px;
       font-size:11px; font-weight:800; color:#607d8b; background:#eceff1; border:1px solid #e0e6ea; }
.focus-role { display:inline-block; margin-right:6px; padding:3px 10px; border-radius:20px;
       font-size:11px; font-weight:700; color:#78909c; background:#f4f7f9; border:1px solid #e8edf1; }
.focus-note { font-size:11.5px; color:#9aa7b4; line-height:1.5; }

/* ---------- 页脚 ---------- */
.foot { margin:26px 20px 0; padding:15px 20px; text-align:center; background:#fff;
       border:1px solid #e7edf4; border-radius:14px; color:#8795a3; font-size:11px; line-height:1.85; }
.foot-brand { margin-bottom:6px; font-size:11.5px; font-weight:800; letter-spacing:1.6px; color:#5f6d7c; }
.foot b { color:#667584; }
"""


def render(data, session="早报"):
    title, color, slogan = SESSION_META.get(session, SESSION_META["早报"])
    en = SESSION_EN.get(session, "AM")
    top = ('<div class="top">'
           '<div class="top-brand">'
           '<div class="brand-l"><span class="brand-mark">A</span>'
           '<span class="brand-txt">ASTOCK DAILY</span></div>'
           '<span class="brand-tag">%s EDITION</span></div>'
           '<div class="top-wm">%s</div>'
           '<div class="top-title">%s</div>'
           '<div class="top-sub">%s</div>'
           '<div class="top-date"><span>%s</span><span>星期%s</span><span>生成于 %s</span></div>'
           '</div>'
           % (en, en, esc(title), esc(slogan), esc(data.get("日期")),
              esc(data.get("星期")), esc(data.get("生成时间"))))

    parts = [top, block_market(data.get("全球市场"), session),
             block_finance(data.get("财报") or {}),
             block_unlock(data.get("解禁") or {}),
             block_news(data.get("要闻"), data.get("场次", "早报")),
             block_focus(data.get("重点关注")),
             block_ann(data.get("公告")),
             block_lhb(data.get("龙虎榜") or {})]

    foot = ('<div class="foot"><div class="foot-brand">A股每日财经简报 · 自动生成 · 红涨绿跌</div>'
            '数据源：东方财富 / 新浪财经 ｜ <b>解读为程序化规则判断，仅供研究参考，不构成投资建议</b><br/>'
            '判定口径：按信息对个股基本面 / 股东权益 / 资金供需，或对市场流动性与风险偏好的正向或负面影响定档；'
            'S=已落地强证据、A=方向明确、B=预期性信号，「重大」档须有强证据；个股自身股价涨跌与例行披露不参与判定<br/>'
            '仅展示当日新增数据，当日无数据的板块不展示</div>')

    css = CSS.replace("__IMG_W__", str(IMG_W)).replace("__THEME__", color)
    html = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"/>'
            '<meta name="viewport" content="width=device-width"/>'
            '<style>%s</style></head><body><div class="page">%s</div></body></html>'
            % (css, "".join(parts) + foot))
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
