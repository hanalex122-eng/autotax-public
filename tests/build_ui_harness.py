"""Build a standalone harness that renders the REAL P1 Immobilien components
(extracted verbatim from index.html) with mock data, so Chrome headless can
screenshot them without backend/auth. Dev-only; not part of the app.
"""
import re

src = open("index.html", encoding="utf-8").read()
# Extract the component block: useIsMobile + forms, up to (not incl.) ImmobilienView
a = src.index("// Reactive viewport hook")
b = src.index("function ImmobilienView({refreshKey")
block = src[a:b].strip()

STUBS = r"""
const theme = { bg:"#0a0e17",surface:"#111827",surfaceAlt:"#1a2234",card:"#1e293b",
  border:"#2a3548",accent:"#10b981",accentSoft:"rgba(16,185,129,0.12)",danger:"#ef4444",
  dangerSoft:"rgba(239,68,68,0.12)",warn:"#f59e0b",blue:"#3b82f6",blueSoft:"rgba(59,130,246,0.12)",
  purple:"#8b5cf6",text:"#f1f5f9",textMuted:"#94a3b8",textDim:"#64748b" };
const font="'DM Sans',system-ui,sans-serif"; const mono="'JetBrains Mono',monospace";
const css = {
  input:{width:"100%",padding:"11px 14px",background:theme.surfaceAlt,border:"1.5px solid "+theme.border,borderRadius:10,color:theme.text,fontSize:14,fontFamily:font,outline:"none",boxSizing:"border-box"},
  btn:(c=theme.accent)=>({padding:"10px 22px",background:c,color:"#fff",border:"none",borderRadius:10,fontSize:14,fontWeight:600,cursor:"pointer",fontFamily:font,display:"inline-flex",alignItems:"center",gap:8}),
  btnOutline:{padding:"10px 20px",background:"transparent",border:"1.5px solid "+theme.border,borderRadius:10,color:theme.textMuted,fontSize:13,fontWeight:500,cursor:"pointer",fontFamily:font},
  card:{background:theme.card,borderRadius:14,border:"1px solid "+theme.border,padding:24,boxShadow:"0 1px 3px rgba(0,0,0,0.2)"},
  badge:(bg,c)=>({padding:"4px 10px",borderRadius:20,fontSize:11,fontWeight:600,background:bg,color:c,display:"inline-block"}),
};
const getLang=()=>"de";
const _e=n=>"€"+(Number(n)||0).toLocaleString("de-DE",{maximumFractionDigits:0});
"""

DEMO = r"""
function Demo(){
  const isMob=useIsMobile();
  const _L=(de,tr,en)=>de;
  // cockpit accordion demo (matches implemented structure)
  const [exp,setExp]=React.useState("rueckstand");
  const cards=[
    {k:"gewinn",icon:"💰",label:"Gewinn",val:_e(12400),col:theme.accent,items:[["Musterstr. 12",_e(8200)],["Hauptweg 3",_e(4200)]]},
    {k:"leerstand",icon:"🕳️",label:"Leerstand",val:_e(3810),col:"#f59e0b",items:[["WHG-03 · 127T",_e(3810)]]},
    {k:"rueckstand",icon:"⚠",label:"Rückstand",val:_e(2550),col:theme.danger,items:[["Müller · 3M",_e(2550)]]},
    {k:"belegung",icon:"📊",label:"Belegung",val:"83%",col:theme.text,items:[["Belegt",5],["Vacant",1]]},
  ];
  // mietenkonto demo
  const tncs=[{tenancy_id:1,mieter_name:"Test Mieter 1",von:"2025-01-01",bis:null,monate:12,soll:9600,ist:9600,rueckstand:0},
              {tenancy_id:2,mieter_name:"Test Mieter 2",von:"2025-01-01",bis:null,monate:12,soll:8400,ist:3500,rueckstand:4900}];
  const H=(t)=>(<div style={{color:theme.accent,fontWeight:700,fontSize:13,margin:"18px 0 6px"}}>{t}</div>);
  return(<div style={{maxWidth:900,margin:"0 auto",padding:16,fontFamily:font,color:theme.text}}>
    <div style={{fontSize:11,color:theme.textDim}}>viewport: {isMob?"MOBILE (card-stack)":"DESKTOP (table)"}</div>

    {H("1) ImmoPropForm (Bearbeiten — prefilled + Abbrechen)")}
    <ImmoPropForm initial={{name:"Musterstr. 12",adresse:"12345 Berlin",kaufpreis:300000}} onSave={()=>{}} onCancel={()=>{}}/>

    {H("2) ImmoUnitForm — Wohnfläche (m²) + validation (Name leer = Pflichtfeld)")}
    <ImmoUnitForm initial={{name:"",wohnflaeche:65,soll_miete:850}} onSave={()=>{}} onCancel={()=>{}}/>

    {H("3) ImmoTenancyForm — NK-Vorauszahlung")}
    <ImmoTenancyForm initial={{mieter_name:"Müller",von:"2025-01-01",bis:"",kaltmiete:850,kaution:1700,nk_voraus:180}} onSave={()=>{}} onCancel={()=>{}}/>

    {H("4) Cockpit KPI — per-card accordion (detail inside clicked card)")}
    <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(150px,1fr))",gap:10,alignItems:"start"}}>
      {cards.map(c=><div key={c.k} onClick={()=>setExp(exp===c.k?null:c.k)} style={{...css.card,cursor:"pointer",minWidth:0,borderBottom:exp===c.k?"2px solid "+c.col:"2px solid transparent"}}>
        <div style={{fontSize:12,color:theme.textMuted}}>{c.icon} {c.label}</div>
        <div style={{fontSize:20,fontWeight:700,color:c.col,fontFamily:mono}}>{c.val}</div>
        <div style={{fontSize:10,color:theme.textDim}}>{exp===c.k?"▲ schließen":"▼ Details"}</div>
        {exp===c.k&&<div style={{marginTop:8,paddingTop:8,borderTop:"1px solid "+theme.border}}>
          {c.items.map(([n,v],i)=><div key={i} style={{display:"flex",justifyContent:"space-between",gap:8,fontSize:12,padding:"3px 0",borderTop:i?"1px solid "+theme.border:"none"}}><span>{n}</span><b style={{color:c.col}}>{v}</b></div>)}
        </div>}
      </div>)}
    </div>

    {H("5) Mietenkonto — table (desktop) / card-stack (mobile)")}
    <div style={css.card}>
      {isMob
        ? <div style={{display:"flex",flexDirection:"column",gap:8}}>{tncs.map(t=><div key={t.tenancy_id} style={{padding:"8px 10px",background:theme.surfaceAlt,borderRadius:8}}>
            <div style={{display:"flex",justifyContent:"space-between",gap:8,flexWrap:"wrap"}}><b style={{fontSize:13}}>{t.mieter_name}</b><span style={{fontSize:11,color:theme.textMuted}}>{t.von}→{t.bis||"läuft"} · {t.monate} Mon.</span></div>
            <div style={{display:"flex",justifyContent:"space-between",gap:8,marginTop:6,fontSize:12,flexWrap:"wrap"}}><span style={{color:theme.textDim}}>Soll <b style={{color:theme.text}}>{_e(t.soll)}</b></span><span style={{color:theme.textDim}}>Ist <b style={{color:theme.accent}}>{_e(t.ist)}</b></span><span style={{color:theme.textDim}}>Rückstand <b style={{color:t.rueckstand>0?theme.danger:theme.textMuted}}>{_e(t.rueckstand)}</b></span></div>
          </div>)}</div>
        : <table style={{width:"100%",fontSize:12,borderCollapse:"collapse"}}><thead><tr style={{color:theme.textDim,textAlign:"left"}}><th style={{padding:4}}>Mieter</th><th>Zeitraum</th><th>Mon.</th><th>Soll</th><th>Ist</th><th>Rückstand</th></tr></thead><tbody>
            {tncs.map(t=><tr key={t.tenancy_id} style={{borderTop:"1px solid "+theme.border}}><td style={{padding:4,fontWeight:600}}>{t.mieter_name}</td><td style={{fontSize:11}}>{t.von}→{t.bis||"läuft"}</td><td>{t.monate}</td><td>{_e(t.soll)}</td><td style={{color:theme.accent}}>{_e(t.ist)}</td><td style={{color:t.rueckstand>0?theme.danger:theme.textMuted}}>{_e(t.rueckstand)}</td></tr>)}
          </tbody></table>}
    </div>
  </div>);
}
ReactDOM.createRoot(document.getElementById("root")).render(<Demo/>);
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
%s
</script></body></html>""" % (STUBS, block, DEMO)

open("tests/_ui_harness.html", "w", encoding="utf-8").write(html)
print("harness written: tests/_ui_harness.html (", len(html), "bytes )")
