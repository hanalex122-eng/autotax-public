/* autotax-public auth guard
   Global window.fetch interceptor: 401 yakalayinca tek refresh denemesi yapar,
   basarisizsa localStorage temizlenir ve / sayfasina redirect olur.
   - Token storage keys: atx_token (access), atx_refresh (refresh)
   - Auth endpoint'leri (login/register/refresh/...) intercept'ten muaf tutulur.
   - Replay edilemez body'li request'lerde (FormData/Blob) refresh denenmez, direkt logout. */
(function(){
  var _origFetch = window.fetch.bind(window);
  window._origFetch = _origFetch;
  var _refreshInflight = null;

  function _urlOf(input){
    if (typeof input === "string") return input;
    try { return (input && input.url) || ""; } catch(e){ return ""; }
  }
  function _isOwnApi(url){
    if (!url) return false;
    if (url.charAt(0) === "/") return true;
    return url.indexOf(window.location.origin) === 0;
  }
  function _isAuthEndpoint(url){
    return /\/auth\/(login|register|refresh|forgot-password|reset-password|verify-email|resend-verification)\b/.test(url);
  }
  function _isReplayable(init){
    if (!init || !init.body) return true;
    var b = init.body;
    if (typeof b === "string") return true;
    if (typeof URLSearchParams !== "undefined" && b instanceof URLSearchParams) return true;
    return false;
  }

  window.apiLogout = function(reason){
    try { localStorage.removeItem("atx_token"); } catch(e){}
    try { localStorage.removeItem("atx_refresh"); } catch(e){}
    try { sessionStorage.setItem("atx_session_expired", reason || "expired"); } catch(e){}
    var hasFlag = (window.location.search || "").indexOf("session_expired") >= 0;
    if (hasFlag) { window.location.reload(); }
    else { window.location.replace("/?session_expired=1"); }
  };

  window.apiRefreshOnce = function(){
    if (_refreshInflight) return _refreshInflight;
    _refreshInflight = (async function(){
      var refresh = null;
      try { refresh = localStorage.getItem("atx_refresh"); } catch(e){}
      if (!refresh) return null;
      try {
        var r = await _origFetch("/auth/refresh", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refresh })
        });
        if (!r.ok) return null;
        var d = await r.json();
        if (d && d.token) {
          try {
            localStorage.setItem("atx_token", d.token);
            if (d.refresh_token) localStorage.setItem("atx_refresh", d.refresh_token);
          } catch(e){}
          return d.token;
        }
      } catch(e){}
      return null;
    })();
    _refreshInflight.finally(function(){ setTimeout(function(){ _refreshInflight = null; }, 0); });
    return _refreshInflight;
  };

  window.fetch = async function(input, init){
    var url = _urlOf(input);
    var r1 = await _origFetch(input, init);
    if (r1.status !== 401) return r1;
    if (!_isOwnApi(url) || _isAuthEndpoint(url)) return r1;

    if (!_isReplayable(init)) { window.apiLogout("non_replayable_401"); return r1; }

    var newToken = await window.apiRefreshOnce();
    if (!newToken) { window.apiLogout("refresh_failed"); return r1; }

    var newInit = Object.assign({}, init || {});
    var headers = new Headers((init && init.headers) || {});
    headers.set("Authorization", "Bearer " + newToken);
    newInit.headers = headers;
    var r2 = await _origFetch(input, newInit);
    if (r2.status === 401) { window.apiLogout("retry_401"); }
    return r2;
  };
})();
