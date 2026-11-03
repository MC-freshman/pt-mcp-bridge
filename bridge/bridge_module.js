/* ============================================================
   PT 桥模块 v6
   设计原则：main() 里绝不做任何危险调用，只挂轮询。
   所有 ipc 调用都由外部投进来的命令触发，这样哪一条会把 PT 搞崩
   能精确定位；写文件的 4 种签名也先各写一份，由外部比对字节再定日用哪个。
   改这个文件后：PT 里 Stop -> Start 即生效（导出时 inline 要选 No）。
   ============================================================ */

var CFG = {
    bridge: "C:/Users/wk/pt_bridge",
    token:  "ptb-7c1f4d9a2e6b",
    pollMs: 400,
    write:  "p2"       // 实测唯一干净的签名 = writePlainTextToFile(path, text)；"auto" 会选中乱码的 t2
};

var lastCmdId = "0";
var pollHandle = null;

function p(name) { return CFG.bridge + "/" + name; }

/* ---------- 写：4 种签名 + 二进制，各自可选 ---------- */
function W(sig, path, text) {
    var f = ipc.systemFileManager();
    if (sig === "t2")   { f.writeTextToFile(path, text); return; }
    if (sig === "t3")   { f.writeTextToFile(path, text, false); return; }
    if (sig === "p2")   { f.writePlainTextToFile(path, text); return; }
    if (sig === "p3")   { f.writePlainTextToFile(path, text, false); return; }
    if (sig === "b")    { f.writeBinaryToFile(path, text); return; }
    throw new Error("unknown sig " + sig);
}

function writeOut(path, text) {
    var order = (CFG.write === "auto")
        ? ["t2", "t3", "p2", "p3", "b"]
        : [CFG.write];
    var lastErr = null;
    for (var i = 0; i < order.length; i++) {
        try { W(order[i], path, text); return order[i]; } catch (e) { lastErr = e; }
    }
    return "WRITEFAIL:" + lastErr;
}

function readIn(path) {
    var f = ipc.systemFileManager();
    try { return String(f.getFileContents(path)); } catch (e) {}
    try { return String(f.getFileBinaryContents(path)); } catch (e2) {}
    return null;
}

/* ---------- 供外部调用的操作表 ---------- */
var PT = {

    /* 写探测：同一串 ASCII 用 5 种签名各写一份，外部比字节 */
    selfTest: function () {
        var s = "ASCII-0123456789-OK";
        var rec = [];
        var sigs = ["t2", "t3", "p2", "p3", "b"];
        for (var i = 0; i < sigs.length; i++) {
            try { W(sigs[i], p("t_" + sigs[i] + ".txt"), s); rec.push(sigs[i] + "=ok"); }
            catch (e) { rec.push(sigs[i] + "=err"); }
        }
        return rec.join(" ");
    },

    /* 读探测：外部先写一个已知内容的文件，模块原样读出来再各签名写回，比字节 */
    readTest: function () {
        var got = readIn(p("inbox.txt"));
        if (got === null) return "READ=err";
        var rec = ["len=" + got.length];
        var sigs = ["t2", "t3", "p2", "p3", "b"];
        for (var i = 0; i < sigs.length; i++) {
            try { W(sigs[i], p("r_" + sigs[i] + ".txt"), got); rec.push(sigs[i] + "=ok"); }
            catch (e) { rec.push(sigs[i] + "=err"); }
        }
        return rec.join(" ");
    },

    /* 单条危险调用，一条一条投，崩了就锁定这一条 */
    risky: function (which) {
        if (which === "net")   { return "count=" + ipc.network().getDeviceCount(); }
        if (which === "getd")  { return String(ipc.network().getDevice("Router0")); }
        if (which === "enter") { ipc.network().getDevice("Router0").enterCommand("show version"); return "enterCommand done"; }
        if (which === "con")   { return "has=" + String(ipc.network().getDevice("Router0").getConsoleLine()); }
        if (which === "out")   { return "len=" + String(ipc.network().getDevice("Router0").getConsoleLine().getOutput()).length; }
        if (which === "run")   { return "len=" + String(AssessmentModel.getRunningConfig("Router0")).length; }
        return "unknown which";
    },

    /* 心跳：外部据此判断轮询活着 */
    beat: function () { writeOut(p("alive.txt"), "alive"); return "ok"; },

    /* 改运行时配置（比如把 write 定成实测可用的签名） */
    setCfg: function (k, v) { CFG[k] = v; return k + "=" + v; }
};

/* ---------- 轮询：唯一在启动时就跑的东西 ---------- */
function pollOnce() {
    var raw;
    try { raw = readIn(p("cmd.txt")); } catch (e) { return; }
    if (raw === null) return;
    raw = raw.replace(/^\s+|\s+$/g, "");
    if (raw === "") return;
    var obj;
    try { obj = JSON.parse(raw); } catch (e) { return; }
    if (!obj || !obj.code || obj.id === lastCmdId) return;
    if (obj.token !== CFG.token) { writeOut(p("resp.txt"), '{"id":"' + obj.id + '","ok":false,"error":"bad token"}'); lastCmdId = obj.id; writeOut(p("cmd.txt"), ""); return; }
    lastCmdId = obj.id;
    writeOut(p("cmd.txt"), "");
    var out;
    try {
        var v = eval(obj.code);
        out = { id: obj.id, ok: true, result: (typeof v === "object" ? "<object>" : String(v)) };
    } catch (e) {
        out = { id: obj.id, ok: false, error: String(e) };
    }
    var txt;
    try { txt = JSON.stringify(out); } catch (e2) { txt = '{"id":"' + obj.id + '","ok":false,"error":"stringify fail"}'; }
    writeOut(p("resp.txt"), txt);
}

function main() {
    try { pollHandle = setInterval("pollTick()", CFG.pollMs); } catch (e) {
        try { pollHandle = setInterval(pollOnce, CFG.pollMs); } catch (e2) {}
    }
}

/* 轮询入口：任何异常都不许冒出去，避免拖垮引擎 */
function pollTick() { try { pollOnce(); } catch (e) {} }

function cleanUp() {
    try { if (pollHandle) clearInterval(pollHandle); } catch (e) {}
}
