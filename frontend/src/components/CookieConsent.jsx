import { useState } from 'react';
import { theme, css, font } from '../theme';

const texts = {
  de: { title:"Datenschutz & Cookies", desc:"Nur technisch notwendige Cookies. Kein Tracking. DSGVO-konform.", reject:"Nur notwendige", accept:"Akzeptieren", more:"Datenschutzerklärung" },
  en: { title:"Privacy & Cookies", desc:"Only essential cookies. No tracking. GDPR compliant.", reject:"Essential only", accept:"Accept", more:"Privacy Policy" },
  fr: { title:"Confidentialité & Cookies", desc:"Uniquement cookies essentiels. Aucun suivi. Conforme RGPD.", reject:"Essentiels uniquement", accept:"Accepter", more:"Politique de confidentialité" },
  es: { title:"Privacidad & Cookies", desc:"Solo cookies esenciales. Sin seguimiento. Conforme RGPD.", reject:"Solo esenciales", accept:"Aceptar", more:"Política de privacidad" },
  tr: { title:"Gizlilik & Cerezler", desc:"Sadece teknik cerezler. Izleme yok. KVKK uyumlu.", reject:"Sadece gerekli", accept:"Kabul et", more:"Gizlilik politikasi" },
  ar: { title:"الخصوصية وملفات تعريف الارتباط", desc:"ملفات تعريف ارتباط أساسية فقط. بدون تتبع.", reject:"الأساسية فقط", accept:"قبول", more:"سياسة الخصوصية" },
};

const privacyUrls = { de:"/datenschutz", en:"/privacy", fr:"/confidentialite", es:"/privacidad", tr:"/gizlilik", ar:"/khususiyya" };

function detectLang(){
  const n = (navigator.language||"").toLowerCase();
  if(n.startsWith("de")) return "de";
  if(n.startsWith("fr")) return "fr";
  if(n.startsWith("es")) return "es";
  if(n.startsWith("tr")) return "tr";
  if(n.startsWith("ar")) return "ar";
  return "en";
}

export default function CookieConsent(){
  const[visible,setVisible]=useState(!localStorage.getItem("atx_cookie_consent"));
  const lang = detectLang();
  const t = texts[lang] || texts.en;
  const privacyUrl = privacyUrls[lang] || "/privacy";

  if(!visible) return null;

  const dismiss=(val)=>{
    localStorage.setItem("atx_cookie_consent", val);
    localStorage.setItem("atx_cookie_consent_date", new Date().toISOString());
    localStorage.setItem("atx_cookie_consent_lang", lang);
    setVisible(false);
  };

  return(<div style={{position:"fixed",bottom:0,left:0,right:0,zIndex:2000,background:theme.surface,borderTop:"1px solid "+theme.border,padding:"16px 24px",display:"flex",alignItems:"center",justifyContent:"space-between",gap:16,flexWrap:"wrap",fontFamily:font,direction:lang==="ar"?"rtl":"ltr"}}>
    <div style={{flex:1,minWidth:280}}>
      <div style={{fontSize:14,fontWeight:600,color:theme.text,marginBottom:4}}>{t.title}</div>
      <div style={{fontSize:12,color:theme.textMuted,lineHeight:1.5}}>
        {t.desc}{" "}
        <a href={privacyUrl} target="_blank" rel="noopener noreferrer" style={{color:theme.accent,textDecoration:"underline"}}>{t.more}</a>
      </div>
    </div>
    <div style={{display:"flex",gap:10}}>
      <button style={css.btnOutline} onClick={()=>dismiss("essential")}>{t.reject}</button>
      <button style={css.btn()} onClick={()=>dismiss("accepted")}>{t.accept}</button>
    </div>
  </div>);
}
