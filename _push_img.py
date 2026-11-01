# -*- coding: utf-8 -*-
"""
把当日报图上传到公开图仓（GitHub Pages 托管），供微信 ClawBot 点链接看原图。
用法：GH_TOKEN=xxx python _push_img.py [png_path]
仅依赖标准库 + PIL；云端/本地通用。
"""
import os
import sys
import json
import ssl
import base64
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OWNER = os.environ.get("GH_OWNER", "wu-jiangping")
REPO = os.environ.get("IMG_REPO", "astock-daily-img")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def api(path, method="GET", payload=None, timeout=120):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request("https://api.github.com/%s" % path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + os.environ["GH_TOKEN"])
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "astock-bot")
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        b = r.read().decode("utf-8", "replace")
    return json.loads(b) if b.strip() else {}


def put_file(path, content_bytes, msg):
    """创建或更新文件（自动带 sha）。"""
    sha = None
    try:
        sha = api("repos/%s/%s/contents/%s" % (OWNER, REPO, path)).get("sha")
    except Exception:
        sha = None
    payload = {"message": msg, "content": base64.b64encode(content_bytes).decode("ascii")}
    if sha:
        payload["sha"] = sha
    return api("repos/%s/%s/contents/%s" % (OWNER, REPO, path), "PUT", payload)


def main():
    if not os.environ.get("GH_TOKEN"):
        print("缺少 GH_TOKEN，跳过图片上传")
        return 1
    png = sys.argv[1] if len(sys.argv) > 1 else None
    if not png or not os.path.exists(png):
        import glob
        cands = sorted(glob.glob(os.path.join(BASE_DIR, "out", "report_*.png")))
        if not cands:
            print("未找到报告 PNG")
            return 1
        png = cands[-1]

    from push import png_to_jpg_bytes
    jpg = png_to_jpg_bytes(png, 82)
    print("JPG %.0f KB" % (len(jpg) / 1024))

    stamp = os.path.basename(png)
    r = put_file("latest.jpg", jpg, "update latest %s" % stamp)
    print("latest.jpg ->", "ok" if r.get("content") else r)

    idx = ("<!doctype html><meta charset='utf-8'>"
           "<meta name='viewport' content='width=device-width,initial-scale=1'>"
           "<title>A股日报长图</title>"
           "<body style='margin:0;background:#f5f6f8;font-family:sans-serif'>"
           "<div style='padding:10px;text-align:center;font-size:14px;color:#666'>A股日报 · 最新一期长图</div>"
           "<img src='latest.jpg' style='width:100%%;display:block'>"
           "</body>")
    r2 = put_file("index.html", idx.encode("utf-8"), "update index")
    print("index.html ->", "ok" if r2.get("content") else r2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
