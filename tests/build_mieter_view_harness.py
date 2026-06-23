"""Render the REAL MieterView (extracted from index.html) with mock /immo/mieter
data for desktop+mobile screenshots. Dev-only artifact."""
src = open("index.html", encoding="utf-8").read()
a = src.index("// ── MIETER (tenant-centric main view)")
b = src.index("\nfunction ImmobilienView({refreshKey")
block = src[a:b].strip()

STUBS = r"""
const theme = { bg:"#0a0e17",surface:"#111827",surfaceAlt:"#1a2234",card:"#1e293b",
  border:"#2a3548",accent:"#10b981",danger:"#ef4444",blue:"#3b82f6",
  text:"#f1f5f9",textMuted:"#94a3b8",textDim:"#64748b" };
const font="'DM Sans',system-ui,sans-serif";
const css = { card:{background:theme.card,borderRadius:14,border:"1px solid "+theme.border,padding:18,boxShadow:"0 1px 3px rgba(0,0,0,0.2)"},
  btnOutline:{padding:"10px 20px",background:"transparent",border:"1.5px solid "+theme.border,borderRadius:10,color:theme.textMuted,fontSize:13,fontWeight:500,cursor:"pointer",fontFamily:font},
  badge:(bg,c)=>({padding:"4px 10px",borderRadius:20,fontSize:11,fontWeight:600,background:bg,color:c,display:"inline-block"}) };
const getLang=()=>"de"; const API="";
function useIsMobile(bp){const[m,setM]=React.useState(window.innerWidth<(bp||768));return m;}
const MOCK={mieter:[
  {tenancy_id:1,mieter_name:"Ahmet Yilmaz",property_name:"Musterstr. 12",unit_name:"EG Links",wohnflaeche:57,kaltmiete:330,nk_vorauszahlung:70,gesamtmiete:400,einzug:"2026-01-01",auszug:null,offene_forderung:0,debtor:false,this_month_status:"paid",last_payment_date:"2026-06-03",anmeldung_done:true,wgb_done:true,letzte_mahnung:null},
  {tenancy_id:2,mieter_name:"Maria Müller",property_name:"Hauptweg 3",unit_name:"OG Rechts",wohnflaeche:72,kaltmiete:500,nk_vorauszahlung:40,gesamtmiete:540,einzug:"2026-06-15",auszug:null,offene_forderung:540,debtor:true,this_month_status:"open",last_payment_date:null,anmeldung_done:true,wgb_done:false,letzte_mahnung:{stufe:1,stufe_text:"Zahlungserinnerung",datum:"2026-06-12"}},
  {tenancy_id:3,mieter_name:"Hans Schmidt",property_name:"Hauptweg 3",unit_name:"DG",wohnflaeche:45,kaltmiete:600,nk_vorauszahlung:90,gesamtmiete:690,einzug:"2025-03-01",auszug:"2026-07-31",offene_forderung:0,debtor:false,this_month_status:"paid",last_payment_date:"2026-06-01",anmeldung_done:true,wgb_done:true,letzte_mahnung:null},
]};
function api(p){return Promise.resolve(MOCK);}
"""

html = """<!doctype html><html><head><meta charset="utf-8">
<style>body{margin:0;background:#0a0e17;padding:16px;}</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.23.9/babel.min.js"></script>
</head><body><div id="root"></div>
<script type="text/babel">
const { useState } = React;
%s
%s
ReactDOM.createRoot(document.getElementById("root")).render(<MieterView onNav={()=>{}}/>);
</script></body></html>""" % (STUBS, block)

open("tests/_mieter_view_harness.html", "w", encoding="utf-8").write(html)
print("mieter view harness written (", len(block), "chars block )")
