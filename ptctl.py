"""PT 桥驱动 v6。

    python ptctl.py status                 # 桥目录里各产物的字节/时间概览
    python ptctl.py selftest               # 让 PT 用 5 种写签名各写一份，我比字节
    python ptctl.py bytes <文件名>          # 十六进制+解码尝试地看某个产物
    python ptctl.py readtest               # 读通道探测（先写 inbox.txt）
    python ptctl.py risky <net|getd|enter|con|out|run>   # 单条危险调用，崩了即定位
    python ptctl.py setcfg write t2        # 把写签名定成实测可用的那个
    python ptctl.py js "<表达式>"           # 直接投任意 ECMAScript
    python ptctl.py ping

前提：PT 里模块在 Start 状态。所有 IPC 调用都由这里投出去，模块自己不动。
"""
import json
import os
import re
import sys
import time

BRIDGE = os.environ.get("PT_BRIDGE_DIR", r"C:\pt_bridge")
CMD = os.path.join(BRIDGE, "cmd.txt")
RESP = os.path.join(BRIDGE, "resp.txt")
ALIVE = os.path.join(BRIDGE, "alive.txt")
TOKEN = os.environ.get("PT_BRIDGE_TOKEN", "CHANGE_ME")
FILES = ["cmd.txt", "resp.txt", "alive.txt", "inbox.txt",
         "t_t2.txt", "t_t3.txt", "t_p2.txt", "t_p3.txt", "t_b.txt",
         "r_t2.txt", "r_t3.txt", "r_p2.txt", "r_p3.txt", "r_b.txt"]


def read_raw(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def decode(raw):
    if raw is None:
        return None, "不存在"
    for enc in ("utf-8", "utf-16", "gbk"):
        try:
            return enc, raw.decode(enc)
        except Exception:
            continue
    return None, "三种编码都解不出"


def send(code, timeout=12.0):
    cid = str(int(time.time() * 1000))
    payload = json.dumps({"id": cid, "token": TOKEN, "code": code})
    tmp = CMD + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, CMD)
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = read_raw(RESP)
        if raw and raw.strip():
            enc, txt = decode(raw)
            try:
                obj = json.loads(txt)
                if str(obj.get("id")) == cid:
                    return obj
            except Exception:
                pass
        time.sleep(0.15)
    raw = read_raw(RESP)
    hint = "resp.txt 不存在" if raw is None else ("resp.txt 内容非 JSON：%r" % raw[:60])
    return {"id": cid, "ok": False, "error": "超时（%s）" % hint}


def js_expr(expr):
    return "(function(){try{return String(eval(%s))}catch(e){return 'ERR:'+e}})()" % json.dumps(expr)


# ---------- CLI 通道：处理 PT 的 --More-- 分页器 ----------
# 实测：--More-- 挂着时下一条输入的首字符会被分页器吃掉，
#       所以必须先发空格翻到干净，再发命令。enterChar 两种形态都是 invalid args。

def _tl(device):
    return 'ipc.network().getDevice(%s).getConsoleLine()' % json.dumps(device)


def cli_read(device, timeout=10.0):
    js = ("(function(){var tl=%s;var o=String(tl.getOutput());"
          "return JSON.stringify({prompt:tl.getPrompt(),mode:tl.getMode(),len:o.length,"
          "more:o.slice(-60).indexOf('--More--')>=0,text:o});})()" % _tl(device))
    r = send(js, timeout)
    if not r.get("ok"):
        return None
    try:
        return json.loads(r["result"])
    except Exception:
        return None


def cli_send(device, text, timeout=10.0):
    r = send("(function(){var tl=%s;tl.enterCommand(%s);return 'sent'})()" % (_tl(device), json.dumps(text)), timeout)
    return r.get("ok", False)


def cli_clear_pager(device, max_pages=12):
    for _ in range(max_pages):
        st = cli_read(device)
        if st is None or not st.get("more"):
            return True
        cli_send(device, " ")
    return False


def cli_run(device, command, wait=0.35, max_pages=12):
    """发一条命令，自动翻页到结束，返回这段新增输出。

    判据是"尾部回到提示符"，不是"输出变长"——配置类命令本来就没回显，
    用输出变长当条件会让每条静默命令空转到超时。
    """
    if not cli_clear_pager(device):
        return {"ok": False, "error": "分页器清不完"}
    before = cli_read(device)
    if before is None:
        return {"ok": False, "error": "读不到设备终端"}
    if not cli_send(device, command):
        return {"ok": False, "error": "命令投递失败"}
    time.sleep(wait)
    PROMPT_RE = r"[A-Za-z0-9_.\-]+(?:\([^\)]*\))?[#>]\s*$"
    last = None
    resent = False
    for i in range(max_pages):
        st = cli_read(device, 12.0)
        if st is None:
            return {"ok": False, "error": "读输出失败"}
        last = st
        if st.get("more"):
            cli_send(device, " ")
            time.sleep(0.25)
            continue
        added = st["text"][before["len"]:]
        # 设备刚被访问时第一条命令常被吞掉（回显里看不到命令本身），重发一次
        if (command and not resent and i >= 2 and command.strip() not in added):
            cli_send(device, command)
            resent = True
            time.sleep(wait)
            continue
        if re.search(PROMPT_RE, st["text"].rstrip()):
            return {"ok": True, "prompt": st["prompt"], "mode": st["mode"],
                    "added": added, "resent": resent}
        time.sleep(0.25)
    return {"ok": True, "prompt": (last or {}).get("prompt"), "mode": (last or {}).get("mode"),
            "added": (last or {}).get("text", "")[before["len"]:], "note": "没等到提示符，按已读内容返回"}


def do_status():
    # 控制台可能是 cp936，产物里带 U+FFFD 会直接抛 UnicodeEncodeError，先转义
    safe = lambda s: s.encode("ascii", "backslashreplace").decode("ascii")
    for n in FILES:
        p = os.path.join(BRIDGE, n)
        raw = read_raw(p)
        if raw is None:
            continue
        enc, txt = decode(raw)
        info = "解码=%s 内容=%r" % (enc, txt[:70]) if enc else txt
        print(safe("%-12s %5d 字节  %s" % (n, len(raw), info)))
    if not any(os.path.exists(os.path.join(BRIDGE, x)) for x in FILES[1:]):
        print("除 cmd.txt 外没有产物：模块没在轮询")


def main():
    a = sys.argv[1] if len(sys.argv) > 1 else "status"

    if a == "status":
        do_status()
        return 0
    if a == "bytes":
        raw = read_raw(os.path.join(BRIDGE, sys.argv[2]))
        if raw is None:
            print("不存在")
            return 1
        print("hex:", raw[:80].hex(" "))
        enc, txt = decode(raw)
        print("decode[%s]: %r" % (enc, txt if enc else txt))
        return 0
    if a == "ping":
        print(json.dumps(send("1+1"), ensure_ascii=True))
        return 0
    if a == "selftest":
        print(json.dumps(send("PT.selfTest()"), ensure_ascii=True))
        return 0
    if a == "readtest":
        with open(os.path.join(BRIDGE, "inbox.txt"), "w", encoding="utf-8") as f:
            f.write("READPROBE-0123456789-OK")
        print(json.dumps(send("PT.readTest()"), ensure_ascii=True))
        return 0
    if a == "risky":
        which = sys.argv[2]
        print(json.dumps(send("PT.risky(%s)" % json.dumps(which), 20.0), ensure_ascii=True))
        return 0
    if a == "setcfg":
        print(json.dumps(send('PT.setCfg(%s, %s)' % (json.dumps(sys.argv[2]), json.dumps(sys.argv[3]))),
                         ensure_ascii=True))
        return 0
    if a == "cli":
        dev = sys.argv[2]
        cmd = " ".join(sys.argv[3:])
        print(json.dumps(cli_run(dev, cmd), ensure_ascii=True, indent=2))
        return 0
    if a == "runconf":
        print(json.dumps(cli_run(sys.argv[2], "show running-config"), ensure_ascii=True, indent=2))
        return 0
    if a == "js":
        print(json.dumps(send(js_expr(sys.argv[2]),
                             float(sys.argv[3]) if len(sys.argv) > 3 else 12.0),
                         ensure_ascii=True, indent=2))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
