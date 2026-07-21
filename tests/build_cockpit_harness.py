"""Render the REAL current ImmoDashboardView (cockpit) with mock data so Chrome
headless can screenshot it (no backend/auth). Dev-only design artifact."""
src = open("index.html", encoding="utf-8").read()
a = src.index("function ImmoDashboardView({onNav}){")
b = src.index("// Reactive viewport hook")
cockpit = src[a:b].strip()

STUBS = r"""
const theme = { bg:"#0a0e17",surface:"#111827",surfaceAlt:"#1a2234",card:"#1e293b",
  border:"#2a3548",accent:"#10b981",accentSoft:"rgba(16,185,129,0.12)",danger:"#ef4444",
  dangerSoft:"rgba(239,68,68,0.12)",warn:"#f59e0b",blue:"#3b82f6",blueSoft:"rgba(59,130,246,0.12)",
  purple:"#8b5cf6",text:"#f1f5f9",textMuted:"#94a3b8",textDim:"#64748b" };
const font="'DM Sans',system-ui,sans-serif"; const mono="'JetBrains Mono',monospace";
const css = { card:{background:theme.card,borderRadius:14,border:"1px solid "+theme.border,padding:24,boxShadow:"0 1px 3px rgba(0,0,0,0.2)"},
  btn:(c=theme.accent)=>({padding:"10px 22px",background:c,color:"#fff",border:"none",borderRadius:10,fontSize:14,fontWeight:600,cursor:"pointer",fontFamily:font,display:"inline-flex",alignItems:"center",gap:8}),
  btnOutline:{padding:"10px 20px",background:"transparent",border:"1.5px solid "+theme.border,borderRadius:10,color:theme.textMuted,fontSize:13,fontWeight:500,cursor:"pointer",fontFamily:font} };
const getLang=()=>"de";
const MOCK={year:2026,score:{total:78,color:"orange",components:{belegung:83,inkasso:72,leerstand:60,schulden:74,rendite:88}},
  portfolio:{occupancy_rate:83,occupied:5,vacant:1},
  financial:{gewinn:12400,leerstandsverlust:3810,rueckstand:2550},
  actions:[{severity:"red",typ:"debt",text:"Müller schuldet 2.550€ · 3 Mon"},{severity:"orange",typ:"vacancy",text:"WHG-03 · 127 Tage leer · −3.810€"},{severity:"orange",typ:"contract_ending",text:"Vertrag WHG-05 (Schmidt) endet in 30 Tagen"}],
  kpi:{gewinn:{items:[{name:"Musterstr. 12",value:8200},{name:"Hauptweg 3",value:4200}]},leerstand:{items:[{unit:"WHG-03",days_vacant:127,loss:3810}]},rueckstand:{items:[{tenant:"Müller",months_overdue:3,debt:2550}]}},
  ranking:[{property_id:1,name:"Musterstr. 12",gewinn:8200,trend:"up",color:"green",belegung:100},{property_id:2,name:"Hauptweg 3",gewinn:4200,trend:"flat",color:"orange",belegung:75}],
  vacancy:[{unit:"WHG-03",risk:"high",empty_since:"2025-08-01",days_vacant:127,loss:3810}],
  tenant_risk:[{tenant:"Müller",risk:"high",months_overdue:3,debt:2550}],
  charts:{monthly_income:[4200,4200,4200,3400,3400,3400,3400,3400,4200,4200,4200,4200],monthly_expenses:[800,300,1200,400,900,300,2100,300,800,400,600,300],vacancy_trend:[0,0,0,1,1,1,1,1,1,1,1,1]}};
function api(p){return Promise.resolve(MOCK);}
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
ReactDOM.createRoot(document.getElementById("root")).render(<div style={{maxWidth:760,margin:"0 auto",padding:16}}><ImmoDashboardView onNav={()=>{}}/></div>);
</script></body></html>""" % (STUBS, cockpit)

open("tests/_cockpit_harness.html", "w", encoding="utf-8").write(html)
print("cockpit harness written")
