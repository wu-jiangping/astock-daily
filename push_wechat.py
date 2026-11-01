# -*- coding: utf-8 -*-
"""
把「原图长图」推送到个人微信（PushPlus）。
前提：run_report.py 已把最新长图写入 site\\latest.jpg，且该目录已发布为在线链接。
用法：
  python push_wechat.py 早报
  python push_wechat.py 早报 --text    # 降级为文字表格版（图片外链不可用时）
仅依赖标准库 + PIL。
"""
import sys
import os
import json
import time
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
OUT_DIR = os.path.join(BASE_DIR, "out")
CN_TZ = timezone(timedelta(hours=8))

SESSION_TAG = {"早报": "am", "午报": "noon", "晚报": "pm"}
SESSION_TITLE = {"早报": "A股早报", "午报": "A股午报", "晚报": "A股晚报"}


def load_cfg():
    cfg = {}
    p = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    # 云端（GitHub Actions）用环境变量注入密钥
    if os.environ.get("PUSHPLUS_TOKEN"):
        cfg["pushplus_token"] = os.environ["PUSHPLUS_TOKEN"]
    if os.environ.get("WX_CHANNEL"):
        cfg["微信渠道"] = os.environ["WX_CHANNEL"]
    if os.environ.get("IMAGE_URL") is not None:
        cfg["图片外链"] = os.environ["IMAGE_URL"]
    # 云端开关：ClawBot 之外是否再用服务号补发一张原图（"0"/"false"/"no" 关闭）
    if os.environ.get("WX_DUP_IMAGE") is not None:
        cfg["微信双推图片"] = os.environ["WX_DUP_IMAGE"].strip().lower() not in (
            "0", "false", "no", "off", "")
    return cfg


def build_text(data, img_url):
    """ClawBot / 纯文字版：聊天气泡里直接读完要点，末尾给长图链接。"""
    s = data.get("场次", "早报")
    title = SESSION_TITLE.get(s, "A股简报")
    L = ["%s · %s 星期%s" % (title, data.get("日期", ""), data.get("星期", "")), "———————"]

    mkt = data.get("全球市场") or []
    if mkt:
        seg = []
        for x in mkt[:5]:
            c = x.get("涨跌幅") or 0
            seg.append("%s %+.2f%%" % (x["名称"], c))
        L.append("隔夜海外：" + " ｜ ".join(seg))

    fin = data.get("财报") or {}
    if fin.get("预喜") or fin.get("爆雷"):
        top = (fin.get("预喜") or [])[:1]
        if top and top[0].get("净利润同比") is not None:
            L.append("财报：新披露 %d 家，预喜 %d / 爆雷 %d；最高 %s %+.1f%%" % (
                fin.get("样本数", 0), len(fin["预喜"]), len(fin.get("爆雷") or []),
                top[0]["名称"], top[0]["净利润同比"]))
        else:
            L.append("财报：新披露 %d 家，预喜 %d / 爆雷 %d" % (
                fin.get("样本数", 0), len(fin["预喜"]), len(fin.get("爆雷") or [])))
    for x in (fin.get("爆雷") or [])[:2]:
        yoy = x.get("净利润同比")
        L.append("  ⚠ %s 净利同比 %s" % (x.get("名称"), "%+.1f%%" % yoy if yoy is not None else "—"))

    un = data.get("解禁") or {}
    tot = (un.get("今日") or []) + (un.get("临近") or [])
    if tot:
        L.append("解禁：今日 %d 家，7 日内 %d 家；最大 %s 占总股本 %s（%s）" % (
            len(un.get("今日") or []), len(tot), tot[0].get("名称"),
            tot[0].get("解禁比例") or "—", tot[0].get("解禁日期", "")[5:]))

    lhb = data.get("龙虎榜") or {}
    if lhb.get("买入") or lhb.get("卖出"):
        b = (lhb.get("买入") or [])[:1]
        sl = (lhb.get("卖出") or [])[:1]
        seg = []
        if b:
            seg.append("净买 %s %.2f亿" % (b[0]["名称"], (b[0].get("净买入") or 0) / 1e8))
        if sl:
            seg.append("净卖 %s %.2f亿" % (sl[0]["名称"], (sl[0].get("净买入") or 0) / 1e8))
        L.append("龙虎榜（%s）：%s" % (lhb.get("交易日", "")[5:], " ｜ ".join(seg)))

    nw = data.get("要闻") or []
    if nw:
        L.append("要闻 %d 条 · 公告 %d 条" % (len(nw), len(data.get("公告") or [])))
        for x in nw[:3]:
            L.append("  · %s %s" % (x.get("时间"), (x.get("标题") or "")[:28]))

    L.append("———————")
    if img_url:
        L.append("完整长图（含全部明细与解读）：")
        L.append(img_url)
    else:
        L.append("完整长图见企业微信（含全部明细与逐条解读）")

    L.append("解读为程序化规则判断，不构成投资建议。")
    return "\n".join(L)


def build_image_html(data, img_url):
    """图片版：内容极小，绝不会触发长度限制。"""
    s = data.get("场次", "早报")
    title = SESSION_TITLE.get(s, "A股简报")
    date = data.get("日期", "")
    return ('<div style="font-size:16px;font-weight:bold;margin-bottom:6px">'
            '%s · %s 星期%s</div>'
            '<img src="%s" style="width:100%%;display:block" />'
            '<div style="font-size:12px;color:#999;margin-top:8px">'
            '点击查看大图｜数据源：东方财富/新浪财经｜解读为程序化规则判断，不构成投资建议</div>'
            % (title, date, data.get("星期", ""), img_url))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    session = args[0] if args else "早报"

    cfg = load_cfg()
    token = (cfg.get("pushplus_token") or "").strip()
    if not token:
        print("未配置 pushplus_token，跳过微信推送")
        return 1
    if not cfg.get("推送微信", True):
        print("config.json 中 推送微信=false，跳过")
        return 0

    now = datetime.now(CN_TZ)
    tag = SESSION_TAG.get(session, "am")
    data_path = os.path.join(OUT_DIR, "data_%s_%s.json" % (now.strftime("%Y%m%d"), tag))
    data = {}
    if os.path.exists(data_path):
        try:
            with open(data_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    data.setdefault("场次", session)
    data.setdefault("日期", now.strftime("%Y-%m-%d"))

    title = "%s · %s" % (SESSION_TITLE.get(session, "A股简报"), now.strftime("%m-%d"))

    img_url = (cfg.get("图片外链") or "").strip()
    use_text = "--text" in flags

    import push
    channel = (cfg.get("微信渠道") or "wechat").strip() or "wechat"
    if "--wechat" in flags:
        channel = "wechat"

    sep = "&" if "?" in img_url else "?"
    stamp = now.strftime("%Y%m%d%H%M")
    real_url = ("%s%s_v=%s" % (img_url, sep, stamp)) if img_url else ""

    def fallback(reason):
        """ClawBot 不可用 / 未激活时的兜底：走服务号。"""
        print("%s，降级为服务号图文 ..." % reason)
        if img_url and not use_text:
            c = build_image_html(data, real_url)
            kind2 = "图片"
        else:
            import render
            c = render.render_wechat(data, session)
            kind2 = "文字表格"
        r2 = push.send_pushplus(token, title, c, template="html", channel="wechat")
        print("降级结果(%s) code=%s msg=%s" % (kind2, r2.get("code"), r2.get("msg")))
        return 0 if r2.get("code") == 200 else 2

    if channel == "clawbot":
        # 微信 ClawBot 只下发文字 → 正文给摘要，末尾给长图链接
        content = build_text(data, real_url)
        print("微信渠道: ClawBot  模式: 文字+图链  内容字节: %d" % len(content.encode("utf-8")))
        r = push.send_pushplus(token, title, content, template="txt", channel="clawbot")
        print("ClawBot code=%s msg=%s" % (r.get("code"), r.get("msg")))

        if r.get("code") != 200:
            return fallback("ClawBot 未激活或已达频控（每 10 条 / 每 24 小时需主动发起一次对话）")

        # 双推：ClawBot 不支持图片，再走服务号发一张原图，保证微信里能直接看到图
        if cfg.get("微信双推图片", True) and real_url:
            c2 = build_image_html(data, real_url)
            r3 = push.send_pushplus(token, title, c2, template="html", channel="wechat")
            print("双推原图(服务号) code=%s msg=%s" % (r3.get("code"), r3.get("msg")))
        return 0

    if img_url and not use_text:
        content = build_image_html(data, real_url)
        kind = "图片"
    else:
        import render
        content = render.render_wechat(data, session)
        kind = "文字表格"

    print("微信渠道: 服务号  模式: %s  内容字节: %d" % (
        kind, len(content.encode("utf-8"))))
    r = push.send_pushplus(token, title, content, template="html", channel="wechat")
    print("code=%s msg=%s" % (r.get("code"), r.get("msg")))
    return 0 if r.get("code") == 200 else 2


if __name__ == "__main__":
    sys.exit(main())
