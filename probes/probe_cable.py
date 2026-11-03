"""5 参形式已对，换真实线型名试，找出能建成的那个。"""
import sys

sys.path.insert(0, r"C:\Users\wk\pt_bridge")
import ptctl

LW = 'ipc.appWindow().getActiveWorkspace().getLogicalWorkspace()'
P1 = 'ipc.network().getDevice("Router0").getPort("FastEthernet0/0")'
P2 = 'ipc.network().getDevice("Switch6").getPort("FastEthernet0/1")'
W = ('(function(){try{var v=%s;return "ret="+String(v).slice(0,40)}'
     'catch(e){return "NO:"+String(e).slice(0,55)}})()')
CK = ('(function(){var d=ipc.network().getDevice("Router0"),a=[];'
      'for(var i=0;i<d.getPortCount();i++){var p=d.getPortAt(i);'
      'a.push(p.getName()+"="+(p.getLink()?"LINK":"none"))}return a.join(",")})()')

for cable in ["Copper Straight-Through", "Copper Cross-Over", "Automatic", "Coaxial",
              "Fiber", "Serial DCE", "CopperStraightThrough", "Straight-Through", "STP"]:
    js = '%s.createLink(%s,%s,"%s",0,0)' % (LW, P1, P2, cable)
    r = ptctl.send(W % js, 12.0)
    got = ptctl.send(CK, 10.0).get("result")
    hit = "LINK" in str(got)
    print("%-24s %-32s %s%s" % (cable, str(r.get("result", r.get("error")))[:32], got, "   <<< 建成" if hit else ""))
    if hit:
        break
