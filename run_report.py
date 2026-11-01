# -*- coding: utf-8 -*-
"""
一键运行入口：抓取 → 渲染 → （可选）推送企业微信。
用法：
  python run_report.py 早报          # 生成并推送（若已配置 webhook）
  python run_report.py 午报 --no-push   # 只生成本地图，不推送
  python run_report.py --auto        # 按当前北京时间自动判断场次
"""
import sys
import os
import json
import time
import traceback
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
OUT_DIR = os.path.join(BASE_DIR, "out")
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

CN_TZ = timezone(timedelta(hours=8))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

LOG_FH = None


def log(msg):
    line = "[%s] %s" % (datetime.now(CN_TZ).strftime("%H:%M:%S"), msg)
    print(line)
    if LOG_FH:
        try:
            LOG_FH.write(line + "\n")
            LOG_FH.flush()
        except Exception:
            pass


def load_cfg():
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    # 云端（GitHub Actions）用环境变量注入密钥，避免写进仓库
    if os.environ.get("WECOM_WEBHOOK"):
        cfg["webhook"] = os.environ["WECOM_WEBHOOK"]
    if os.environ.get("PUSHPLUS_TOKEN"):
        cfg["pushplus_token"] = os.environ["PUSHPLUS_TOKEN"]
    if os.environ.get("WX_CHANNEL"):
        cfg["微信渠道"] = os.environ["WX_CHANNEL"]
    if os.environ.get("IMAGE_URL") is not None:
        cfg["图片外链"] = os.environ["IMAGE_URL"]
    return cfg


def detect_session():
    h = datetime.now(CN_TZ).hour + datetime.now(CN_TZ).minute / 60.0
    if h < 10:
        return "早报"
    if h < 15:
        return "午报"
    return "晚报"


def run(session, do_push=True):
    global LOG_FH
    now = datetime.now(CN_TZ)
    LOG_FH = open(os.path.join(LOG_DIR, now.strftime("%Y%m%d") + ".log"), "a", encoding="utf-8")

    import fetch_data
    import render

    cfg = load_cfg()
    webhook = (cfg.get("webhook") or "").strip()
    token = (cfg.get("pushplus_token") or "").strip()
    if do_push and not webhook and not token:
        log("未配置 webhook / pushplus_token，仅生成本地文件（不推送）")
        do_push = False

    log("==== 开始生成 %s ====" % session)

    log("1/3 抓取数据 ...")
    t0 = time.time()
    data = fetch_data.build(session, cfg)
    lhb = data.get("龙虎榜") or {}
    log("    财报 预喜%d/爆雷%d；解禁 今%d/临%d；市场%d；要闻%d；公告%d；龙虎榜 买%d/卖%d(%s) (%.1fs)" % (
        len(data["财报"]["预喜"]), len(data["财报"]["爆雷"]),
        len(data["解禁"]["今日"]), len(data["解禁"]["临近"]),
        len(data["全球市场"]), len(data["要闻"]), len(data["公告"]),
        len(lhb.get("买入") or []), len(lhb.get("卖出") or []), lhb.get("交易日", "-"),
        time.time() - t0))

    # 落盘结构化数据，便于排查
    try:
        import render as _r
        tag = _r.SESSION_TAG.get(session, "am")
        data_path = os.path.join(OUT_DIR, "data_%s_%s.json" % (now.strftime("%Y%m%d"), tag))
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log("    数据已存 %s" % data_path)
    except Exception as e:
        log("    数据落盘失败: %s" % e)

    log("2/3 渲染长图 ...")
    t0 = time.time()
    html_path, png_path = render.build_image(data, session)
    size_kb = os.path.getsize(png_path) / 1024
    log("    PNG 生成 %.0f KB (%.1fs)" % (size_kb, time.time() - t0))

    # 同步到托管目录 site\latest.jpg（更新在线图片外链用）
    try:
        from push import png_to_jpg_bytes
        site_dir = os.path.join(BASE_DIR, "site")
        os.makedirs(site_dir, exist_ok=True)
        jpg = png_to_jpg_bytes(png_path, cfg.get("图片质量", 82))
        with open(os.path.join(site_dir, "latest.jpg"), "wb") as f:
            f.write(jpg)
        log("    托管图已更新 site\\latest.jpg (%.0f KB)" % (len(jpg) / 1024))
    except Exception as e:
        log("    托管图更新失败: %s" % e)

    # 生成微信版（手机阅读）
    wx_html = None
    try:
        wx_html = render.render_wechat(data, session)
        import render as _rr
        tag = _rr.SESSION_TAG.get(session, "am")
        wx_path = os.path.join(OUT_DIR, "wechat_%s_%s.html" % (now.strftime("%Y%m%d"), tag))
        with open(wx_path, "w", encoding="utf-8") as f:
            f.write(wx_html)
        log("    微信版 %d 字符 → %s" % (len(wx_html), wx_path))
    except Exception as e:
        log("    微信版渲染失败: %s" % e)

    push_result = "未推送"
    if do_push:
        log("3/3 推送 ...")
        import push
        # 微信走图片模式时，文字版改由 push_wechat.py 在图片更新上线后再发
        wx_mode = (cfg.get("微信推送模式") or "图片").strip()
        if wx_mode != "文字":
            wx_html = None
        try:
            ok, detail = push.push(webhook, data, png_path, cfg, wechat_html=wx_html)
            push_result = detail
            log("    推送结果: %s" % detail)
        except Exception as e:
            push_result = "异常: %s" % e
            log("    推送异常: %s" % e)
            traceback.print_exc()
    else:
        log("3/3 跳过推送")

    log("==== 完成 ==== PNG=%s" % png_path)
    try:
        LOG_FH.close()
    except Exception:
        pass
    LOG_FH = None
    return {"html": html_path, "png": png_path, "push": push_result, "data": data}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    session = args[0] if args else None
    if not session or session == "--auto" or "--auto" in flags:
        session = detect_session()
    no_push = "--no-push" in flags
    try:
        res = run(session, do_push=not no_push)
        print("RESULT_JSON=" + json.dumps(
            {"png": res["png"], "html": res["html"], "push": res["push"]}, ensure_ascii=False))
    except Exception as e:
        log("运行失败: %s" % e)
        traceback.print_exc()
        sys.exit(1)
