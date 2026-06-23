"""Render the REAL MieterView (extracted from index.html) with mock data for
desktop+mobile screenshots. AUTO_OPEN=1 clicks the first 'Mietkonto' button to
show the Tenancy Detail panel. Dev-only artifact."""
import os
src = open("index.html", encoding="utf-8").read()
a = src.index("// ── MIETER (tenant-centric main view)")
b = src.index("\nfunction ImmobilienView({refreshKey")
block = src[a:b].strip()
AUTO = os.environ.get("AUTO_OPEN") == "1"

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
  {tenancy_id:1,mieter_name:"Ahmet Yilmaz",property_name:"Musterstr. 12",unit_name:"EG Links",wohnflaeche:57,kaltmiete:330,nk_vorauszahlung:70,gesamtmiete:400,einzug:"2026-01-01",auszug:null,offene_forderung:400,debtor:true,this_month_status:"open",last_payment_date:"2026-05-03",anmeldung_done:true,wgb_done:true,letzte_mahnung:null},
  {tenancy_id:2,mieter_name:"Maria Müller",property_name:"Hauptweg 3",unit_name:"OG Rechts",wohnflaeche:72,kaltmiete:500,nk_vorauszahlung:40,gesamtmiete:540,einzug:"2026-06-15",auszug:null,offene_forderung:540,debtor:true,this_month_status:"open",last_payment_date:null,anmeldung_done:true,wgb_done:false,letzte_mahnung:{stufe:1,stufe_text:"Zahlungserinnerung",datum:"2026-06-12"}},
]};
const MK={tenancy_id:1,year:2026,rows:[
  {monat:1,soll:330,bezahlt:330,status:"paid"},{monat:2,soll:330,bezahlt:330,status:"paid"},
  {monat:3,soll:330,bezahlt:330,status:"paid"},{monat:4,soll:330,bezahlt:330,status:"paid"},
  {monat:5,soll:330,bezahlt:330,status:"paid"},{monat:6,soll:330,bezahlt:0,status:"open"},
  {monat:7,soll:330,bezahlt:0,status:"future"},{monat:8,soll:330,bezahlt:0,status:"future"},
  {monat:9,soll:330,bezahlt:0,status:"future"},{monat:10,soll:330,bezahlt:0,status:"future"},
  {monat:11,soll:330,bezahlt:0,status:"future"},{monat:12,soll:330,bezahlt:0,status:"future"}],
  summe:{soll_faellig:1980,bezahlt:1650,offen:330}};
function api(p){if(String(p).indexOf("/mietkonto")>=0)return Promise.resolve(MK);return Promise.resolve(MOCK);}
"""

CLICK = """
setTimeout(function(){var bs=[].slice.call(document.querySelectorAll('button'));var b=bs.filter(function(x){return x.textContent.indexOf('Mietkonto')>=0;})[0];if(b)b.click();},1600);
""" if AUTO else ""

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
</script>
<script>%s</script>
</body></html>""" % (STUBS, block, CLICK)

open("tests/_mieter_view_harness.html", "w", encoding="utf-8").write(html)
print("mieter view harness written (auto_open=%s)" % AUTO)
