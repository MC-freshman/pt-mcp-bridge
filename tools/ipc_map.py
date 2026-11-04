"""PT 内部接口地图 + 全设备服务扫描。

两步：
  1) build_map(strings_path)  从 exe 串表还原 {类名: [方法]}
  2) sweep(device)            对某台设备逐个 getProcess(类名)，存在就调它的零参 get*/is* 收数据

用法：
    python tools/ipc_map.py map      <pt_strings.txt>
    python tools/ipc_map.py sweep    <pt_strings.txt> Server0 [Server1 ...]
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import ptctl

MARKERS = ("getClassName", "getObjectUuid", "registerObjectEvent", "unregisterObjectEvent")
NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9_]{2,40}$")
PROC_RE = re.compile(r"^[A-Z][A-Za-z0-9]{3,40}Process$")
SAFE_RE = re.compile(r"^(get|is|has)[A-Z]")


CONST_RE = re.compile(r"^[A-Z][A-Z0-9_]{3,}$")   # 全大写是常量名，不是类名
# 串表里每个块紧邻 marker 的常常是裸通用词 Process/Device/Port，会把真类名挤掉
GENERIC = {"Process", "Device", "Port", "Node", "Object", "Item", "Data", "Entry",
           "Table", "Pool", "Manager", "Server", "Client", "Interface", "Component",
           "Module", "Service", "Session", "Connection", "Record", "Instance", "Packet"}


def build_map(strings_path):
    """块名要往前多找几行：真类名（如 AcsServerProcess）离 registerObjectEvent
    往往隔着十几条常量串，只看 8 行会误取成通用的 Process。"""
    lines = io.open(strings_path, encoding="utf-8", errors="ignore").read().split("\n")
    out, i, n = {}, 0, len(lines)
    while i < n:
        if lines[i] == "registerObjectEvent":
            cands = []
            for j in range(i, max(0, i - 45), -1):
                t = lines[j]
                if t in MARKERS or t in GENERIC or CONST_RE.match(t) or not NAME_RE.match(t):
                    continue
                cands.append(t)
            name = None
            for t in cands:                      # 优先带后缀的真类名，裸通用词已在候选里排除
                m = re.search(r"(Process|Manager|Server|Client|Table|Pool|Device|Port)$", t)
                if m and len(t) > len(m.group(1)):
                    name = t
                    break
            if name is None and cands:
                name = cands[0]
            methods, k = [], i + 1
            while k < n and k < i + 140:
                t = lines[k]
                if t == "registerObjectEvent":
                    break
                if re.match(r"^[a-zA-Z_][A-Za-z0-9_]{2,60}$", t) and not CONST_RE.match(t):
                    methods.append(t)
                k += 1
            if name:
                out.setdefault(name, set()).update(m for m in methods if SAFE_RE.match(m))
            i = k if k > i else i + 1
        else:
            i += 1
    return {k: sorted(v) for k, v in out.items()}


def process_names(ifmap, strings_path=None):
    """进程名全集：映射表里的 Process 类 ∪ 串表里所有 *Process 字面量。
    只靠映射表会漏（很多块名被归成通用 Process），所以必须并上原始名单。"""
    names = set(k for k in ifmap if PROC_RE.match(k))
    if strings_path and os.path.exists(strings_path):
        for l in io.open(strings_path, encoding="utf-8", errors="ignore"):
            t = l.strip()
            if PROC_RE.match(t):
                names.add(t)
    return sorted(names)


def exists_map(devs, procs):
    """每台设备装了哪些进程——只调 getProcess，不调任何方法，最省也最安全。"""
    js = ("(function(){var ps=[%s];var ds=[%s];var out={};"
          "for(var i=0;i<ds.length;i++){var d=ipc.network().getDevice(ds[i]);var hit=[];"
          "if(!d){out[ds[i]]='设备不存在';continue}"
          "for(var j=0;j<ps.length;j++){var p=null;"
          "try{p=d.getProcess(ps[j])}catch(e){}"
          "if(p)hit.push(ps[j])}out[ds[i]]=hit}"
          "return JSON.stringify(out)})()"
          % (",".join(json.dumps(p) for p in procs),
             ",".join(json.dumps(d) for d in devs)))
    r = ptctl.send(js, 90.0)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}
    try:
        return {"ok": True, "map": json.loads(r["result"])}
    except Exception:
        return {"ok": False, "raw": str(r.get("result"))[:300]}


def sweep_device(dev, ifmap, procs, max_methods=6):
    """对一台设备扫所有进程；只调零参 get*/is*，异常全吞。"""
    js_parts = []
    names = ",".join(json.dumps(p) for p in procs)
    body = (
        "var d=ipc.network().getDevice(%s);var ps=[%s];var out=[];"
        "for(var i=0;i<ps.length;i++){var p=null;"
        "try{p=d.getProcess(ps[i])}catch(e){}"
        "if(!p)continue;var rec={proc:ps[i],data:{}};"
        "var ms=METHODS[ps[i]]||[];"
        "for(var j=0;j<ms.length&&j<%d;j++){var m=ms[j];"
        "try{var v=p[m]();if(typeof v!=='object')rec.data[m]=String(v).slice(0,120)}"
        "catch(e){}}"
        "out.push(rec)}"
        "return JSON.stringify(out)"
    ) % (json.dumps(dev), names, max_methods)
    methods_json = json.dumps(ifmap)
    js = "(function(){var METHODS=%s;%s})()" % (methods_json, body)
    r = ptctl.send(js, 60.0)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}
    try:
        return {"ok": True, "found": json.loads(r["result"])}
    except Exception:
        return {"ok": False, "raw": str(r.get("result"))[:400]}


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "map"
    # 串表由 tools/strings_probe.py 生成，默认放在仓库根的上一级之外自行指定
    strings_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pt_strings.txt")
    ifmap = build_map(strings_path)
    procs = process_names(ifmap, strings_path)

    if mode == "map":
        print("接口类 %d 个，进程名全集 %d 个" % (len(ifmap), len(procs)))
        for p in procs[:10]:
            print("   %-28s 可读方法: %s" % (p, ", ".join(ifmap.get(p, [])[:6])))
        out = os.path.join(os.path.dirname(strings_path), "pt_ipc_map.json")
        io.open(out, "w", encoding="utf-8").write(json.dumps(ifmap, ensure_ascii=False, indent=1))
        print("已写出", out)

    elif mode == "exists":
        devs = sys.argv[3:] or None
        if devs is None:
            r = ptctl.send("(function(){var n=ipc.network(),a=[];"
                           "for(var i=0;i<n.getDeviceCount();i++)a.push(n.getDeviceAt(i).getName());"
                           "return a.join('\\n')})()", 20.0)
            devs = [x for x in str(r.get("result", "")).split("\n") if x]
        res = exists_map(devs, procs)
        if not res.get("ok"):
            print("失败:", str(res)[:200])
            sys.exit(1)
        for d, hit in res["map"].items():
            print("%-26s %s" % (d, hit if isinstance(hit, str) else ", ".join(hit) or "(无)"))
        io.open(os.path.join(os.path.dirname(strings_path), "pt_processes.json"),
                "w", encoding="utf-8").write(json.dumps(res["map"], ensure_ascii=False, indent=1))
        print("已写出 pt_processes.json")
    else:
        devs = sys.argv[3:] or ["Server0"]
        for d in devs:
            res = sweep_device(d, ifmap, procs)
            print("=== %s ===" % d)
            if not res.get("ok"):
                print("   失败:", str(res)[:200])
                continue
            for rec in res["found"]:
                if rec["data"]:
                    print("   %-28s %s" % (rec["proc"], json.dumps(rec["data"], ensure_ascii=False)[:220]))
                else:
                    print("   %-28s (存在，但零参方法没取到数据)" % rec["proc"])
