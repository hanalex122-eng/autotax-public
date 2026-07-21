"""Render the REAL deployed Immobilien LIST view (what the user sees first) with
mock data, to ground the 'live screen vs report' analysis. Dev-only artifact."""
src = open("index.html", encoding="utf-8").read()
a = src.index("// Reactive viewport hook")
b = src.index("function BookkeepingView")
block = src[a:b].strip()

STUBS = r"""
const theme = { bg:"#0a0e17",surface:"#111827",surfaceAlt:"#1a2234",card:"#1e293b",
  border:"#2a3548",accent:"#10b981",accentSoft:"rgba(16,185,129,0.12)",danger:"#ef4444",
  dangerSoft:"rgba(239,68,68,0.12)",warn:"#f59e0b",blue:"#3b82f6",blueSoft:"rgba(59,130,246,0.12)",
  purple:"#8b5cf6",text:"#f1f5f9",textMuted:"#94a3b8",textDim:"#64748b" };
const font="'DM Sans',system-ui,sans-serif"; const mono="'JetBrains Mono',monospace";
const css = { input:{width:"100%",padding:"11px 14px",background:theme.surfaceAlt,border:"1.5px solid "+theme.border,borderRadius:10,color:theme.text,fontSize:14,fontFamily:font,outline:"none",boxSizing:"border-box"},
  btn:(c=theme.accent)=>({padding:"10px 22px",background:c,color:"#fff",border:"none",borderRadius:10,fontSize:14,fontWeight:600,cursor:"pointer",fontFamily:font,display:"inline-flex",alignItems:"center",gap:8}),
  btnOutline:{padding:"10px 20px",background:"transparent",border:"1.5px solid "+theme.border,borderRadius:10,color:theme.textMuted,fontSize:13,fontWeight:500,cursor:"pointer",fontFamily:font},
  card:{background:theme.card,borderRadius:14,border:"1px solid "+theme.border,padding:24,boxShadow:"0 1px 3px rgba(0,0,0,0.2)"},
  badge:(bg,c)=>({padding:"4px 10px",borderRadius:20,fontSize:11,fontWeight:600,background:bg,color:c,display:"inline-block"}) };
const getLang=()=>"de"; const showToast=()=>{};
function api(p){
  if(p.endsWith("/properties")) return Promise.resolve({properties:[{id:1,name:"Musterstr. 12",adresse:"12345 Berlin"},{id:2,name:"Hauptweg 3",adresse:"54321 Hamburg"}]});
  if(p.indexOf("/accounting")>=0){var id=p.indexOf("/1/")>=0?1:2;return Promise.resolve(id==1?{summe:{einheiten:3,belegungsquote:100,ist_miete:8200,zahlungsausfall:0},tenancies:[{},{},{}]}:{summe:{einheiten:4,belegungsquote:75,ist_miete:4200,zahlungsausfall:2550},tenancies:[{},{},{}]});}
  return Promise.resolve({});
}
"""

html = """<!doctype html><html><head><meta charset="utf-8">
<style>body{margin:0;background:#0a0e17;}</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.23.9/babel.min.js"></script>
</head><body><div id="root"></div>
<script type="text/babel">
const { useState } = React;
%s
%s
ReactDOM.createRoot(document.getElementById("root")).render(<div style={{maxWidth:760,margin:"0 auto",padding:16}}><ImmobilienView onNav={()=>{}}/></div>);
</script></body></html>""" % (STUBS, block)

open("tests/_immo_list_harness.html", "w", encoding="utf-8").write(html)
print("immo list harness written")
