"""Sprint 2.1 — görsel doğrulama harness'i (dev artifact).

Gerçek index.html'den ÇIKARILAN kodu render eder (kopya değil):
  * Form A = ImmoTenancyForm (+ _ImmoField/_ImmoActions yardımcıları)
  * Form B = MieterView satır-içi düzenleme + kiracı kartı rozeti
Mock veri: aynı binada Hauptmieter (EG) + Untermieter (2.OG) + başka binada 1 kiracı
(aday filtresinin binayı da dikkate aldığını görmek için).

Doğrulanan (2026-07-21, Chrome): aday listesi tek kişi ("Ahmet Yilmaz · EG links" — başka
binadaki kiracı ve Untermieter'in kendisi elendi), rozet 1 kez "🔗 Untermieter → Ahmet Yilmaz",
Form B kaydı `typ:"unter",parent_tenancy_id:1`, kutu kaldırılınca `typ:"haupt",parent:-1`.

Run: python tests/build_untermieter_visual.py  → tests/_untermieter_visual.html (untracked)
"""
src = open("index.html", encoding="utf-8").read()

# --- gerçek koddan blokları çıkar ---
a = src.index("function _ImmoField({label,required,error,children}){")
b = src.index("// ── BU AY (this-month digest")
form_block = src[a:b].strip()          # _ImmoField.._ImmoActions..ImmoUnitForm..ImmoTenancyForm

c = src.index("// ── MIETER (tenant-centric main view)")
d = src.index("\nfunction ImmobilienView({refreshKey")
mieter_block = src[c:d].strip()

STUBS = r"""
const theme = { bg:"#0a0e17",surface:"#111827",surfaceAlt:"#1a2234",card:"#1e293b",
  border:"#2a3548",accent:"#10b981",accentSoft:"rgba(16,185,129,0.12)",danger:"#ef4444",
  blue:"#3b82f6",blueSoft:"rgba(59,130,246,0.12)",text:"#f1f5f9",textMuted:"#94a3b8",textDim:"#64748b" };
const font="'DM Sans',system-ui,sans-serif";
const css = { card:{background:theme.card,borderRadius:14,border:"1px solid "+theme.border,padding:18},
  input:{width:"100%",boxSizing:"border-box",padding:"10px 12px",background:theme.surfaceAlt,
         border:"1px solid "+theme.border,borderRadius:8,color:theme.text,fontSize:13,marginBottom:8},
  btn:(c)=>({padding:"10px 20px",background:c,color:"#fff",border:"none",borderRadius:10,fontSize:13,fontWeight:700,cursor:"pointer"}),
  btnOutline:{padding:"10px 20px",background:"transparent",border:"1.5px solid "+theme.border,borderRadius:10,color:theme.textMuted,fontSize:13,cursor:"pointer",fontFamily:font},
  badge:(bg,c)=>({padding:"4px 10px",borderRadius:20,fontSize:11,fontWeight:600,background:bg,color:c,display:"inline-block"}) };
const getLang=()=>"de"; const API="";
function useIsMobile(bp){const[m,setM]=React.useState(window.innerWidth<(bp||768));return m;}

// ── MOCK: aynı bina = Musterstr. 12 (unit 1 Hauptmieter, unit 2 Untermieter) + başka bina ──
const MOCK={mieter:[
  {tenancy_id:1,unit_id:1,mieter_name:"Ahmet Yilmaz",property_name:"Musterstr. 12",property_address:"Musterstr. 12, Krefeld",
   unit_name:"EG links",wohnflaeche:80,kaltmiete:600,nk_vorauszahlung:80,heizkosten_vorauszahlung:0,gesamtmiete:680,
   einzug:"2026-01-01",auszug:null,offene_forderung:680,debtor:true,this_month_status:"open",rueckstand_monate:[{ym:"2026-03",offen:680,typ:"open"}],
   last_payment_date:"2026-05-03",anmeldung_done:true,wgb_done:true,letzte_mahnung:null,telefon:"0176 1234567",email:"ahmet@mail.de",
   kaution:1200,typ:null,parent_tenancy_id:null,zahler_typ:"mieter",zahler_name:null,erstmonat_betrag:null,personenzahl:2,miete_historie:null},
  {tenancy_id:2,unit_id:2,mieter_name:"Maria Müller",property_name:"Musterstr. 12",property_address:"Musterstr. 12, Krefeld",
   unit_name:"2.OG",wohnflaeche:45,kaltmiete:300,nk_vorauszahlung:40,heizkosten_vorauszahlung:30,gesamtmiete:370,
   einzug:"2026-04-01",auszug:null,offene_forderung:370,debtor:true,this_month_status:"open",rueckstand_monate:[{ym:"2026-06",offen:370,typ:"open"}],
   last_payment_date:null,anmeldung_done:true,wgb_done:false,letzte_mahnung:null,telefon:null,email:null,
   kaution:600,typ:"unter",parent_tenancy_id:1,zahler_typ:"mieter",zahler_name:null,erstmonat_betrag:null,personenzahl:1,miete_historie:null},
  {tenancy_id:3,unit_id:9,mieter_name:"Klaus Weber (anderes Haus)",property_name:"Hauptweg 3",property_address:"Hauptweg 3, Krefeld",
   unit_name:"OG",wohnflaeche:60,kaltmiete:500,nk_vorauszahlung:60,heizkosten_vorauszahlung:0,gesamtmiete:560,
   einzug:"2025-01-01",auszug:null,offene_forderung:0,debtor:false,this_month_status:"paid",rueckstand_monate:[],
   last_payment_date:"2026-06-01",anmeldung_done:true,wgb_done:true,letzte_mahnung:null,telefon:null,email:null,
   kaution:1000,typ:null,parent_tenancy_id:null,zahler_typ:"mieter",zahler_name:null,erstmonat_betrag:null,personenzahl:1,miete_historie:null},
],eigennutzer:[],summe:{aktiv:3,sorgenfrei:1,schuldner:2,teilzahlung:0}};
const MK={tenancy_id:1,year:2026,rows:[{monat:6,soll:680,bezahlt:0,status:"open"}],summe:{soll_faellig:680,bezahlt:0,offen:680}};
const PROPS={properties:[{id:10,name:"Musterstr. 12",adresse:"Musterstr. 12, Krefeld"},
                         {id:11,name:"Hauptweg 3",adresse:"Hauptweg 3, Krefeld"}]};
const UNITS={units:[{id:1,name:"EG links"},{id:2,name:"2.OG"}]};
function api(p,o){const s=String(p);
  if(o&&(o.method==="POST"||o.method==="PATCH")){console.log("API "+o.method+" "+s+" -> "+o.body);return Promise.resolve({success:true,id:99});}
  if(s.indexOf("/mietkonto")>=0)return Promise.resolve(MK);
  if(s.indexOf("/units")>=0)return Promise.resolve(UNITS);
  if(s.indexOf("/immo/properties")>=0)return Promise.resolve(PROPS);
  return Promise.resolve(MOCK);}

// Form A demo: gerçek ImmoTenancyForm, aday listesi = ImmobilienView'daki hmCands ile aynı şekil
function FormADemo(){
  const cands=[{tenancy_id:1,mieter_name:"Ahmet Yilmaz",unit_name:"EG links"}];
  return(<div style={{maxWidth:520}}>
    <ImmoTenancyForm hauptmieter={cands} onSave={(b)=>console.log("FORM A SAVE",JSON.stringify(b))} onCancel={()=>{}}/>
  </div>);
}
"""

CLICK = """
setTimeout(function(){
  // Sihirbaz (Neuer Mieter) açılsın — Sprint 2.2 Untermieter desteği görünsün
  var nb=[].slice.call(document.querySelectorAll('button')).filter(function(x){return x.textContent.indexOf('Neuer Mieter')>=0;})[0];
  if(nb)nb.click();
  // Form B: Maria'nın kartındaki 'Bearbeiten' -> satır-içi form açılsın
  var bs=[].slice.call(document.querySelectorAll('button'));
  var b=bs.filter(function(x){return x.textContent.indexOf('Bearbeiten')>=0;})[1];
  if(b)b.click();
  // Form A: Untermieter kutusunu işaretle (dropdown + uyarı görünür olsun)
  setTimeout(function(){
    var sp=[].slice.call(document.querySelectorAll('span')).filter(function(x){return x.textContent.indexOf('Untermieter (in anderer Einheit)')>=0;});
    if(sp[0])sp[0].click();
  },300);
},1200);
"""

html = """<!doctype html><html><head><meta charset="utf-8">
<style>body{margin:0;background:#0a0e17;padding:16px;font-family:system-ui,sans-serif;color:#f1f5f9}
h2{color:#10b981;font-size:15px;margin:18px 0 8px;border-bottom:1px solid #2a3548;padding-bottom:6px}</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.23.9/babel.min.js"></script>
</head><body>
<h2>FORM A — ImmoTenancyForm (Immobilien görünümü)</h2><div id="formA"></div>
<h2>FORM B + ROZET — MieterView</h2><div id="mieter"></div>
<script type="text/babel">
const { useState } = React;
%s
%s
%s
ReactDOM.createRoot(document.getElementById("formA")).render(<FormADemo/>);
ReactDOM.createRoot(document.getElementById("mieter")).render(<MieterView onNav={()=>{}} showToast={()=>{}}/>);
</script>
<script>%s</script>
</body></html>""" % (STUBS, form_block, mieter_block, CLICK)

open("tests/_untermieter_visual.html", "w", encoding="utf-8").write(html)
print("written: tests/_untermieter_visual.html (%d chars)" % len(html))
