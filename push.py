# -*- coding: utf-8 -*-
"""
企业微信群机器人推送。
- 文本：markdown 概要
- 图片：PNG 先转 JPG（白色背景、控制在 1.9MB 内）再 base64 发送
仅依赖标准库 + PIL。
"""
import os
import json
import base64
import hashlib
import ssl
import io
import urllib.request

from PIL import Image

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

MAX_IMG_BYTES = 1900 * 1024  # 企业微信图片消息上限约 2MB，留余量


def _post(url, payload, timeout=25):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json; charset=utf-8",
                                          "User-Agent": "AStockDaily/1.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def png_to_jpg_bytes(png_path, quality=82):
    """把 PNG 铺到白底转 JPG；若超限则逐级降质并缩放。"""
    im = Image.open(png_path).convert("RGB")
    q = quality
    scale = 1.0
    for _ in range(8):
        if scale < 1.0:
            w = max(1, int(im.width * scale))
            h = max(1, int(im.height * scale))
            cur = im.resize((w, h), Image.LANCZOS)
        else:
            cur = im
        buf = io.BytesIO()
        cur.save(buf, "JPEG", quality=q, optimize=True)
        data = buf.getvalue()
        if len(data) <= MAX_IMG_BYTES:
            return data
        if q > 55:
            q -= 8
        else:
            scale *= 0.9
    return buf.getvalue()


def send_text(webhook, content):
    """发送 markdown 文本。"""
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    return _post(webhook, payload)


PUSHPLUS_URL = "https://www.pushplus.plus/send"


def send_pushplus(token, title, content, template="html", channel="wechat"):
    """通过 PushPlus 推送到个人微信（需实名认证）。"""
    payload = {"token": token, "title": title, "content": content,
               "template": template, "channel": channel}
    return _post(PUSHPLUS_URL, payload)


def send_image(webhook, png_path, quality=82):
    """发送图片（自动转 JPG 并压缩到限额内）。"""
    data = png_to_jpg_bytes(png_path, quality)
    b64 = base64.b64encode(data).decode("ascii")
    md5 = hashlib.md5(data).hexdigest()
    payload = {"msgtype": "image", "image": {"base64": b64, "md5": md5}}
    return _post(webhook, payload)


def build_summary(data):
    """拼装 markdown 文本概要。"""
    s = data.get("场次", "早报")
    date = data.get("日期", "")
    lines = ["**%s** · %s 星期%s" % (SESSION_TITLE.get(s, "A股" + s), date, data.get("星期", ""))]

    fin = data.get("财报") or {}
    if fin.get("预喜") or fin.get("爆雷"):
        top = (fin.get("预喜") or [])[:1]
        if top and top[0].get("净利润同比") is not None:
            t = "预喜%d家（最高 %s %+.1f%%）" % (
                len(fin["预喜"]), top[0]["名称"], top[0]["净利润同比"])
        else:
            t = "预喜%d家" % len(fin["预喜"])
        lines.append("**财报**：新披露 %d 家；%s；爆雷 %d 家" % (fin.get("样本数", 0), t, len(fin.get("爆雷") or [])))

    un = data.get("解禁") or {}
    if un.get("今日") or un.get("临近"):
        k = len(un.get("今日") or [])
        tot = (un.get("今日") or []) + (un.get("临近") or [])
        if tot:
            top = tot[0]
            lines.append("**解禁**：今日 %d 家；最大 %s 占总股本 %s" % (
                k, top["名称"], top.get("解禁比例", "—")))

    mkt = data.get("全球市场") or []
    if mkt:
        seg = []
        for x in mkt[:4]:
            c = x.get("涨跌幅")
            seg.append("%s %s%.2f%%" % (x["名称"], "+" if (c or 0) > 0 else "", c or 0))
        lines.append("**海外市场**：" + "；".join(seg))

    lines.append("**要闻 %d 条 · 公告 %d 条**，详见下图。" % (
        len(data.get("要闻") or []), len(data.get("公告") or [])))
    lines.append("> 解读为程序化规则判断，仅供参考，不构成投资建议。")
    return "\n\n".join(lines)


SESSION_TITLE = {"早报": "A股早报", "午报": "A股午报", "晚报": "A股晚报"}


def push(webhook, data, png_path, cfg=None, wechat_html=None):
    """完整推送：企业微信文本+图片，可选 PushPlus 推个人微信。返回 (ok, detail)。"""
    cfg = cfg or {}
    results = []
    if webhook and cfg.get("推送文本摘要", True):
        try:
            r = send_text(webhook, build_summary(data))
            results.append("文本:%s" % (r.get("errmsg") or r.get("errcode")))
        except Exception as e:
            results.append("文本失败:%s" % e)
    if webhook and cfg.get("推送图片", True):
        try:
            r = send_image(webhook, png_path, cfg.get("图片质量", 82))
            results.append("图片:%s" % (r.get("errmsg") or r.get("errcode")))
        except Exception as e:
            results.append("图片失败:%s" % e)
    token = (cfg.get("pushplus_token") or "").strip()
    if token and cfg.get("推送微信", True) and wechat_html:
        try:
            title = "%s · %s" % (SESSION_TITLE.get(data.get("场次"), "A股简报"), data.get("日期", ""))
            r = send_pushplus(token, title[:100], wechat_html)
            results.append("微信:%s(%s)" % (r.get("msg"), r.get("code")))
        except Exception as e:
            results.append("微信失败:%s" % e)
    ok = bool(results) and all("失败" not in x for x in results)
    return ok, " | ".join(results)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("usage: push.py <webhook_url> <png_path> [文本测试]")
        sys.exit(1)
    wh, png = sys.argv[1], sys.argv[2]
    ok, detail = push(wh, {"场次": "早报", "日期": "test", "星期": "一",
                           "财报": {"预喜": [], "爆雷": []}, "解禁": {"今日": [], "临近": []},
                           "全球市场": [], "要闻": [], "公告": []},
                      png, {"推送文本摘要": len(sys.argv) > 3, "推送图片": True})
    print(ok, detail)
