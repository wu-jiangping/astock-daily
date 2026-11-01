# -*- coding: utf-8 -*-
"""
把密钥加密写入 GitHub Actions Secrets（GitHub 要求用公钥加密后再传）。
用法：
  GH_TOKEN=github令牌 python _set_secret.py GH_TOKEN 新令牌值
  GH_TOKEN=github令牌 python _set_secret.py PUSHPLUS_TOKEN xxxx
需要 pynacl：pip install pynacl
"""
import os
import sys
import json
import ssl
import base64
import urllib.request

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
OWNER = os.environ.get("GH_OWNER", "wu-jiangping")
REPO = os.environ.get("GH_REPO", "astock-daily")


def api(path, method="GET", payload=None):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/%s/%s" % (OWNER, REPO, path), data=data, method=method)
    req.add_header("Authorization", "Bearer " + os.environ["GH_TOKEN"])
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "astock-bot")
    with urllib.request.urlopen(req, timeout=40, context=CTX) as r:
        b = r.read().decode("utf-8", "replace")
    return json.loads(b) if b.strip() else {}


def main():
    if len(sys.argv) < 3:
        print("用法: GH_TOKEN=github令牌 python _set_secret.py <SECRET名> <值>")
        return 2
    name, value = sys.argv[1], sys.argv[2]
    from nacl import encoding, public
    pk = api("actions/secrets/public-key")
    box = public.SealedBox(public.PublicKey(pk["key"].encode("utf-8"), encoding.Base64Encoder()))
    enc = base64.b64encode(box.encrypt(value.encode("utf-8"))).decode("ascii")
    api("actions/secrets/%s" % name, "PUT", {"encrypted_value": enc, "key_id": pk["key_id"]})
    print("已更新 %s" % name)
    print("当前 Secrets:", [s["name"] for s in api("actions/secrets").get("secrets", [])])
    return 0


if __name__ == "__main__":
    sys.exit(main())
