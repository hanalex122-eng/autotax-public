const API = import.meta.env.VITE_API_URL || "https://web-production-cd76.up.railway.app";

export { API };

let _refreshing = null;

async function tryRefresh() {
  const refresh = localStorage.getItem("atx_refresh");
  if (!refresh) return false;
  if (_refreshing) return _refreshing;
  _refreshing = (async () => {
    try {
      const res = await fetch(`${API}/auth/refresh`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({refresh_token: refresh}),
      });
      if (!res.ok) return false;
      const data = await res.json();
      if (data.token) {
        localStorage.setItem("atx_token", data.token);
        if (data.refresh_token) localStorage.setItem("atx_refresh", data.refresh_token);
        return true;
      }
      return false;
    } catch { return false; }
    finally { _refreshing = null; }
  })();
  return _refreshing;
}

export default async function api(path, opts={}) {
  const token = localStorage.getItem("atx_token");
  const headers = {"Content-Type":"application/json",...opts.headers};
  if(token) headers["Authorization"]=`Bearer ${token}`;
  let res = await fetch(`${API}${path}`,{...opts,headers});
  // On 401, try refresh before giving up
  if(res.status===401){
    const refreshed = await tryRefresh();
    if(refreshed){
      const newToken = localStorage.getItem("atx_token");
      headers["Authorization"]=`Bearer ${newToken}`;
      res = await fetch(`${API}${path}`,{...opts,headers});
    }
    if(res.status===401){
      localStorage.removeItem("atx_token");
      localStorage.removeItem("atx_refresh");
      window.dispatchEvent(new Event('atx-logout'));
      throw new Error("unauthorized");
    }
  }
  if(!res.ok){const e=await res.json().catch(()=>({}));const msg=typeof e.detail==="string"?e.detail:typeof e.detail==="object"?JSON.stringify(e.detail):e.message||"Error";throw new Error(msg);}
  if(res.status===204) return null;
  return res.json();
}
