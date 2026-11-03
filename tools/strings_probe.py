"""从 PacketTracer.exe 抽字符串表，用来还原它内部那套 IPC 接口声明。

思路（这套方法产出了本仓库 90% 的 API 结论）：
  1. PT 把 .pki 接口声明编译进 exe，每个接口的字符串块都以
     getClassName / getObjectUuid / registerObjectEvent / unregisterObjectEvent
     这四个固定方法开头，后面紧跟该接口的全部方法名。
  2. 所以只要用 registerObjectEvent 当锚点，向前找类名、向后收方法名，
     就能把整张接口表还原出来（本机实测还原出 201 个接口块）。
  3. 再拿方法名去桥里做 typeof 扫描，区分"存在但参数不对"和"根本不存在"。

用法：
    python tools/strings_probe.py "D:/路径/PacketTracer.exe" out_strings.txt
"""
import io
import os
import re
import sys


def extract(exe_path, out_path):
    data = open(exe_path, "rb").read()
    ascii_runs = re.findall(rb"[\x20-\x7e]{6,}", data)
    utf16_runs = re.findall(rb"(?:[\x20-\x7e]\x00){6,}", data)
    with io.open(out_path, "w", encoding="utf-8", errors="ignore") as f:
        for r in ascii_runs:
            f.write(r.decode("ascii", "ignore") + "\n")
        for r in utf16_runs:
            f.write(r.decode("utf-16le", "ignore") + "\n")
    return len(data), len(ascii_runs), len(utf16_runs)


MARKERS = ("getClassName", "getObjectUuid", "registerObjectEvent", "unregisterObjectEvent")
NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9_]{2,40}$")


def parse_interfaces(strings_path):
    """按 registerObjectEvent 锚点切出接口块 -> [(接口名, [方法...])]"""
    lines = io.open(strings_path, encoding="utf-8", errors="ignore").read().split("\n")
    out, i, n = [], 0, len(lines)
    while i < n:
        if lines[i] == "registerObjectEvent":
            name = None
            for j in range(i, max(0, i - 8), -1):
                t = lines[j]
                if t in MARKERS or not NAME_RE.match(t):
                    continue
                name = t
                break
            methods, k = [], i + 1
            while k < n and k < i + 130:
                t = lines[k]
                if t == "registerObjectEvent":
                    break
                if re.match(r"^[a-zA-Z_][A-Za-z0-9_]{2,60}$", t):
                    methods.append(t)
                k += 1
            if name:
                out.append((name, methods))
            i = k if k > i else i + 1
        else:
            i += 1
    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    exe, out = sys.argv[1], sys.argv[2]
    size, a, u = extract(exe, out)
    print("exe=%d 字节  ascii串=%d  utf16串=%d  -> %s (%d 字节)"
          % (size, a, u, out, os.path.getsize(out)))
    ifs = parse_interfaces(out)
    print("还原出接口块 %d 个" % len(ifs))
    for name, ms in ifs[:12]:
        print("  %-22s %d 个方法: %s" % (name, len(ms), " ".join(ms[:12])))
