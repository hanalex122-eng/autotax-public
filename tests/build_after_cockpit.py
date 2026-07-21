"""AFTER mockup — redesigned cockpit (design artifact only, NOT app code).
Renders a premium 'German SaaS' restyle of the cockpit for before/after compare."""
html = r"""<!doctype html><html><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#0b0f1a; --surface:#0f1626; --card:#131c30; --card2:#18233b; --line:#243049;
  --txt:#eef2f8; --mut:#9aa7bd; --dim:#5f6e88;
  --accent:#10b981; --amber:#f59e0b; --red:#f43f5e; --blue:#3b82f6;
  --sp1:4px; --sp2:8px; --sp3:12px; --sp4:16px; --sp5:24px; --sp6:32px;
}
*{box-sizing:border-box;font-feature-settings:"tnum" 1,"cv01" 1;}
body{margin:0;background:var(--bg);font-family:Inter,system-ui,sans-serif;color:var(--txt);}
.wrap{max-width:880px;margin:0 auto;padding:var(--sp5);}
.h-disp{font-size:24px;font-weight:800;letter-spacing:-0.02em;margin:0;}
.h-sec{font-size:13px;font-weight:600;color:var(--mut);text-transform:uppercase;letter-spacing:0.06em;margin:0 0 var(--sp3);}
.num{font-variant-numeric:tabular-nums;letter-spacing:-0.01em;}
.card{background:linear-gradient(180deg,var(--card2),var(--card));border:1px solid var(--line);border-radius:16px;padding:var(--sp5);box-shadow:0 1px 0 rgba(255,255,255,0.03) inset,0 8px 24px -12px rgba(0,0,0,0.6);}
.seg{display:inline-flex;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:3px;}
.seg button{border:none;background:transparent;color:var(--mut);font:inherit;font-size:13px;font-weight:600;padding:6px 14px;border-radius:7px;cursor:pointer;}
.seg button.on{background:var(--card2);color:var(--txt);box-shadow:0 1px 2px rgba(0,0,0,0.4);}
.row{display:flex;align-items:center;}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;padding:4px 10px;border-radius:999px;}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:var(--sp4);position:relative;overflow:hidden;}
.kpi .lab{display:flex;align-items:center;gap:8px;color:var(--mut);font-size:12px;font-weight:600;}
.kpi .val{font-size:26px;font-weight:800;letter-spacing:-0.02em;margin-top:6px;}
.kpi .sub{font-size:12px;color:var(--dim);margin-top:2px;}
.kpi .strip{position:absolute;left:0;top:0;bottom:0;width:3px;}
.ic{width:18px;height:18px;stroke-width:1.8;fill:none;stroke:currentColor;vertical-align:middle;}
.bar{height:7px;background:var(--surface);border-radius:99px;overflow:hidden;}
.bar>i{display:block;height:100%;border-radius:99px;}
.act{display:flex;align-items:center;gap:12px;padding:12px 0;border-top:1px solid var(--line);}
.act:first-child{border-top:none;}
.dot{width:8px;height:8px;border-radius:99px;flex:0 0 auto;}
.muted{color:var(--mut);} .dim{color:var(--dim);}
.grid-kpi{display:grid;grid-template-columns:repeat(4,1fr);gap:var(--sp3);}
.two{display:grid;grid-template-columns:1.1fr 1.4fr;gap:var(--sp4);}
@media(max-width:640px){.grid-kpi{grid-template-columns:repeat(2,1fr);}.two{grid-template-columns:1fr;}}
</style></head><body><div class="wrap">

<div class="row" style="justify-content:space-between;margin-bottom:24px;">
  <div><div class="h-disp">Immobilien Cockpit</div><div class="dim" style="font-size:13px;margin-top:4px;">Stand: Juni 2026 · 2 Objekte · 6 Einheiten</div></div>
  <div class="seg"><button>2025</button><button class="on">2026</button><button>2027</button></div>
</div>

<!-- HERO: score gauge + priority -->
<div class="two" style="margin-bottom:16px;">
  <div class="card" style="display:flex;align-items:center;gap:20px;">
    <svg width="92" height="92" viewBox="0 0 92 92"><circle cx="46" cy="46" r="40" stroke="#243049" stroke-width="8" fill="none"/>
      <circle cx="46" cy="46" r="40" stroke="#f59e0b" stroke-width="8" fill="none" stroke-linecap="round" stroke-dasharray="251" stroke-dashoffset="55" transform="rotate(-90 46 46)"/>
      <text x="46" y="44" text-anchor="middle" font-size="26" font-weight="800" fill="#eef2f8" class="num">78</text>
      <text x="46" y="60" text-anchor="middle" font-size="9" fill="#5f6e88" letter-spacing="1.5">SCORE</text></svg>
    <div style="flex:1;">
      <div class="h-sec" style="margin-bottom:8px;">Portfolio-Score</div>
      <div style="display:flex;flex-direction:column;gap:7px;">
        <div class="row" style="gap:10px;"><span class="dim" style="width:74px;font-size:12px;">Belegung</span><div class="bar" style="flex:1;"><i style="width:83%;background:#10b981;"></i></div><span class="num" style="font-size:12px;width:24px;text-align:right;">83</span></div>
        <div class="row" style="gap:10px;"><span class="dim" style="width:74px;font-size:12px;">Inkasso</span><div class="bar" style="flex:1;"><i style="width:72%;background:#f59e0b;"></i></div><span class="num" style="font-size:12px;width:24px;text-align:right;">72</span></div>
        <div class="row" style="gap:10px;"><span class="dim" style="width:74px;font-size:12px;">Rendite</span><div class="bar" style="flex:1;"><i style="width:88%;background:#10b981;"></i></div><span class="num" style="font-size:12px;width:24px;text-align:right;">88</span></div>
      </div>
    </div>
  </div>
  <div class="card">
    <div class="row" style="justify-content:space-between;margin-bottom:4px;"><div class="h-sec" style="margin:0;">Heute wichtig</div><span class="chip" style="background:rgba(244,63,94,0.12);color:#f43f5e;">3 offen</span></div>
    <div class="act"><span class="dot" style="background:#f43f5e;"></span><div style="flex:1;"><div style="font-weight:600;font-size:14px;">Mietrückstand · Müller</div><div class="dim" style="font-size:12px;">3 Monate offen</div></div><div class="num" style="color:#f43f5e;font-weight:700;">2.550 €</div></div>
    <div class="act"><span class="dot" style="background:#f59e0b;"></span><div style="flex:1;"><div style="font-weight:600;font-size:14px;">Leerstand · WHG-03</div><div class="dim" style="font-size:12px;">seit 127 Tagen</div></div><div class="num" style="color:#f59e0b;font-weight:700;">−3.810 €</div></div>
    <div class="act"><span class="dot" style="background:#3b82f6;"></span><div style="flex:1;"><div style="font-weight:600;font-size:14px;">Vertrag endet · WHG-05</div><div class="dim" style="font-size:12px;">Schmidt · in 30 Tagen</div></div><span class="ic" style="color:#5f6e88;">›</span></div>
  </div>
</div>

<!-- KPI cards -->
<div class="grid-kpi" style="margin-bottom:24px;">
  <div class="kpi"><div class="strip" style="background:#10b981;"></div><div class="lab"><svg class="ic" style="color:#10b981;" viewBox="0 0 24 24"><path d="M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>Gewinn</div><div class="val num" style="color:#10b981;">12.400 €</div><div class="sub">Rendite 4,1 %</div></div>
  <div class="kpi"><div class="strip" style="background:#f59e0b;"></div><div class="lab"><svg class="ic" style="color:#f59e0b;" viewBox="0 0 24 24"><path d="M3 21h18M5 21V7l7-4 7 4v14M9 9h0M9 13h0M9 17h0"/></svg>Leerstand</div><div class="val num" style="color:#f59e0b;">3.810 €</div><div class="sub">1 Einheit · 127 Tage</div></div>
  <div class="kpi"><div class="strip" style="background:#f43f5e;"></div><div class="lab"><svg class="ic" style="color:#f43f5e;" viewBox="0 0 24 24"><path d="M12 9v4M12 17h0M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>Rückstand</div><div class="val num" style="color:#f43f5e;">2.550 €</div><div class="sub">1 Mieter</div></div>
  <div class="kpi"><div class="strip" style="background:#3b82f6;"></div><div class="lab"><svg class="ic" style="color:#3b82f6;" viewBox="0 0 24 24"><path d="M3 13h8V3H3zM13 21h8V3h-8zM3 21h8v-4H3z"/></svg>Belegung</div><div class="val num">83 %</div><div class="sub">5 von 6 belegt</div></div>
</div>

<!-- ranking + vacancy -->
<div class="two" style="margin-bottom:24px;">
  <div class="card"><div class="h-sec">Objekt-Ranking</div>
    <div class="act"><span class="num dim" style="width:18px;">1</span><span class="dot" style="background:#10b981;"></span><div style="flex:1;font-weight:600;font-size:14px;">Musterstr. 12</div><div class="num" style="font-weight:700;">8.200 €</div><span style="color:#10b981;">▲</span></div>
    <div class="act"><span class="num dim" style="width:18px;">2</span><span class="dot" style="background:#f59e0b;"></span><div style="flex:1;font-weight:600;font-size:14px;">Hauptweg 3</div><div class="num" style="font-weight:700;">4.200 €</div><span class="dim">▬</span></div>
  </div>
  <div class="card"><div class="h-sec">Leerstand-Zentrale</div>
    <div class="row" style="justify-content:space-between;"><div><div style="font-weight:700;font-size:15px;">WHG-03</div><div class="dim" style="font-size:12px;">leer seit 01.08.2025 · 127 Tage</div><div class="num" style="color:#f59e0b;font-weight:700;margin-top:4px;">Verlust 3.810 €</div></div><span class="chip" style="background:rgba(244,63,94,0.12);color:#f43f5e;height:fit-content;">HOCH</span></div>
  </div>
</div>

<div class="row" style="gap:8px;color:#5f6e88;font-size:13px;cursor:pointer;"><span>▸</span> Verlauf &amp; Charts (3) — einblenden</div>
</div></body></html>"""
open("tests/_after_cockpit.html", "w", encoding="utf-8").write(html)
print("after cockpit mockup written")
