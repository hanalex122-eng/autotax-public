import { useState } from 'react';
import { theme, css } from '../theme';
import { Icon, I } from '../components/UI';
import api, { API } from '../api/client';

export default function AccountPage({onLogout}){
  const[loading,setLoading]=useState("");
  const[msg,setMsg]=useState(null);
  const[showDelete,setShowDelete]=useState(false);
  const[deleteConfirm,setDeleteConfirm]=useState("");

  const exportData=async()=>{
    setLoading("export");setMsg(null);
    try{
      const token=localStorage.getItem("atx_token");
      const res=await fetch(`${API}/account/export`,{headers:{"Authorization":`Bearer ${token}`}});
      if(!res.ok) throw new Error("Export failed");
      const blob=await res.blob();
      const url=URL.createObjectURL(blob);
      const a=document.createElement("a");
      a.href=url;a.download="autotax_privacy_export.json";a.click();
      URL.revokeObjectURL(url);
      setMsg({type:"ok",text:"Data exported successfully."});
    }catch(e){setMsg({type:"err",text:e.message});}
    setLoading("");
  };

  const doNotSell=async()=>{
    setLoading("dns");setMsg(null);
    try{
      await api("/account/do-not-sell",{method:"POST",body:JSON.stringify({})});
      setMsg({type:"ok",text:"Confirmed: We do not sell your personal data. Your request has been recorded."});
    }catch(e){setMsg({type:"err",text:e.message});}
    setLoading("");
  };

  const deleteAccount=async()=>{
    if(deleteConfirm!=="DELETE") return;
    setLoading("delete");setMsg(null);
    try{
      await api("/account",{method:"DELETE",body:JSON.stringify({confirm:true})});
      setMsg({type:"ok",text:"Account deleted. Logging out..."});
      setTimeout(()=>onLogout(),2000);
    }catch(e){setMsg({type:"err",text:e.message});}
    setLoading("");
  };

  const s={
    section:{...css.card,marginBottom:20},
    h2:{fontSize:18,fontWeight:700,color:theme.text,margin:"0 0 16px",display:"flex",alignItems:"center",gap:10},
    p:{fontSize:13,color:theme.textMuted,lineHeight:1.7,margin:"0 0 14px"},
    flag:{fontSize:11,padding:"3px 8px",borderRadius:6,fontWeight:600,display:"inline-block",marginRight:6}
  };

  const Badge=({color,bg,text})=><span style={{...s.flag,color,background:bg}}>{text}</span>;

  return(<div style={{maxWidth:700,margin:"0 auto"}}>
    <h1 style={{fontSize:24,fontWeight:700,color:theme.text,marginBottom:4}}>Account & Privacy</h1>
    <p style={{color:theme.textMuted,fontSize:14,marginBottom:8}}>International data protection compliance</p>
    <div style={{display:"flex",gap:6,flexWrap:"wrap",marginBottom:24}}>
      <Badge color="#10b981" bg="rgba(16,185,129,0.12)" text="GDPR / DSGVO"/>
      <Badge color="#3b82f6" bg="rgba(59,130,246,0.12)" text="CCPA (California)"/>
      <Badge color="#8b5cf6" bg="rgba(139,92,246,0.12)" text="KVKK (Turkey)"/>
      <Badge color="#f59e0b" bg="rgba(245,158,11,0.12)" text="RGPD (FR/ES)"/>
      <Badge color="#ef4444" bg="rgba(239,68,68,0.12)" text="UK GDPR"/>
      <Badge color="#64748b" bg="rgba(100,116,139,0.12)" text="PDPL (UAE/SA)"/>
    </div>

    {msg&&<div style={{padding:"12px 16px",borderRadius:10,marginBottom:20,fontSize:13,
      background:msg.type==="ok"?theme.accentSoft:theme.dangerSoft,
      color:msg.type==="ok"?theme.accent:theme.danger}}>{msg.text}</div>}

    {/* Export Data — GDPR Art. 15+20, CCPA, KVKK m.11 */}
    <div style={s.section}>
      <h2 style={s.h2}><Icon d={I.export} size={20} color={theme.blue}/>Export Your Data</h2>
      <p style={s.p}>
        <Badge color="#10b981" bg="rgba(16,185,129,0.08)" text="GDPR Art. 15/20"/>
        <Badge color="#3b82f6" bg="rgba(59,130,246,0.08)" text="CCPA §1798.100"/>
        <Badge color="#8b5cf6" bg="rgba(139,92,246,0.08)" text="KVKK m.11"/>
        <br/>Download a complete copy of all your personal data in machine-readable format (JSON).
        Includes: profile, companies, invoices, cash book entries, and usage data.
      </p>
      <button style={css.btn(theme.blue)} onClick={exportData} disabled={loading==="export"}>
        {loading==="export"?"Exporting...":"Download all data (JSON)"}
      </button>
    </div>

    {/* Do Not Sell — CCPA */}
    <div style={s.section}>
      <h2 style={s.h2}><Icon d={I.check} size={20} color={theme.accent}/>Do Not Sell My Data</h2>
      <p style={s.p}>
        <Badge color="#3b82f6" bg="rgba(59,130,246,0.08)" text="CCPA §1798.120"/>
        <br/><strong style={{color:theme.accent}}>We do not sell your personal data.</strong> AutoTax-HUB does not sell, rent, or trade
        personal information to third parties for monetary or other consideration. Click below to formally record your request.
      </p>
      <button style={css.btn(theme.accent)} onClick={doNotSell} disabled={loading==="dns"}>
        {loading==="dns"?"Recording...":"Confirm: Do Not Sell My Data"}
      </button>
    </div>

    {/* Privacy Policies — multi-language */}
    <div style={s.section}>
      <h2 style={s.h2}><Icon d={I.help} size={20} color={theme.purple}/>Privacy Policy</h2>
      <p style={s.p}>Read our privacy policy in your language:</p>
      <div style={{display:"flex",gap:8,flexWrap:"wrap"}}>
        {[
          {flag:"DE",label:"Deutsch",href:"/datenschutz"},
          {flag:"EN",label:"English",href:"/privacy"},
          {flag:"FR",label:"Français",href:"/confidentialite"},
          {flag:"ES",label:"Español",href:"/privacidad"},
          {flag:"TR",label:"Türkçe",href:"/gizlilik"},
          {flag:"AR",label:"العربية",href:"/khususiyya"},
        ].map(l=>(
          <a key={l.flag} href={l.href} target="_blank" rel="noopener noreferrer"
            style={{padding:"8px 16px",borderRadius:8,border:`1px solid ${theme.border}`,
            color:theme.text,textDecoration:"none",fontSize:13,fontWeight:500,
            display:"flex",alignItems:"center",gap:8,background:theme.surfaceAlt,
            transition:"border-color 0.2s"}}
            onMouseEnter={e=>e.currentTarget.style.borderColor=theme.accent}
            onMouseLeave={e=>e.currentTarget.style.borderColor=theme.border}>
            <span style={{fontWeight:700,fontSize:11,color:theme.accent}}>{l.flag}</span>
            {l.label}
          </a>
        ))}
      </div>
    </div>

    {/* Delete Account — GDPR Art. 17, CCPA, KVKK */}
    <div style={{...s.section,borderColor:theme.danger+"33"}}>
      <h2 style={{...s.h2,color:theme.danger}}><Icon d={I.reset} size={20} color={theme.danger}/>Delete Account</h2>
      <p style={s.p}>
        <Badge color="#ef4444" bg="rgba(239,68,68,0.08)" text="GDPR Art. 17"/>
        <Badge color="#3b82f6" bg="rgba(59,130,246,0.08)" text="CCPA §1798.105"/>
        <Badge color="#8b5cf6" bg="rgba(139,92,246,0.08)" text="KVKK m.11/e"/>
        <br/>Permanently delete your account and ALL personal data: profile, email, invoices, receipts,
        cash book entries, company info, and usage data.
        <br/><strong style={{color:theme.danger}}>This action CANNOT be undone.</strong>
      </p>

      {!showDelete?(
        <button style={css.btn(theme.danger)} onClick={()=>setShowDelete(true)}>
          Delete account and all data
        </button>
      ):(
        <div style={{background:theme.dangerSoft,borderRadius:12,padding:20,border:`1px solid ${theme.danger}33`}}>
          <p style={{color:theme.danger,fontSize:14,fontWeight:600,margin:"0 0 12px"}}>
            Are you sure? All data will be permanently deleted.
          </p>
          <p style={{color:theme.textMuted,fontSize:12,margin:"0 0 12px"}}>
            Type <strong style={{color:theme.danger}}>DELETE</strong> to confirm:
          </p>
          <input
            style={{...css.input,borderColor:deleteConfirm==="DELETE"?theme.danger:theme.border,marginBottom:12}}
            value={deleteConfirm}
            onChange={e=>setDeleteConfirm(e.target.value)}
            placeholder="DELETE"
          />
          <div style={{display:"flex",gap:10}}>
            <button style={css.btn(theme.danger)} onClick={deleteAccount}
              disabled={deleteConfirm!=="DELETE"||loading==="delete"}>
              {loading==="delete"?"Deleting...":"Permanently delete"}
            </button>
            <button style={css.btnOutline} onClick={()=>{setShowDelete(false);setDeleteConfirm("");}}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>

    {/* Legal links */}
    <div style={{display:"flex",gap:16,paddingTop:12,flexWrap:"wrap"}}>
      <a href="/datenschutz" target="_blank" rel="noopener noreferrer" style={{fontSize:12,color:theme.textDim,textDecoration:"underline"}}>Datenschutz</a>
      <a href="/privacy" target="_blank" rel="noopener noreferrer" style={{fontSize:12,color:theme.textDim,textDecoration:"underline"}}>Privacy</a>
      <a href="/agb" target="_blank" rel="noopener noreferrer" style={{fontSize:12,color:theme.textDim,textDecoration:"underline"}}>AGB/Terms</a>
      <span style={{fontSize:12,color:theme.textDim}}>datenschutz@autotaxhub.de</span>
    </div>
  </div>);
}
