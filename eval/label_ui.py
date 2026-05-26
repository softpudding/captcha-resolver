"""Browser UI to hand-label tile selections for image-grid eval cases.

Run it, open the printed URL, and for every grid round in cases.jsonl you get the
captured grid.png with a clickable NxM overlay. Click a tile to cycle its label:

    optional (grey, don't-care)  ->  required (green)  ->  forbidden (red)  -> ...

"Save" writes the three index lists straight back into that round in cases.jsonl
(the source of truth the replay oracle reads). It also mirrors them into the
fixture's answer_key.json when the round's target matches the fixture's object,
so the per-fixture docs stay in sync.

    PYTHONPATH=. .venv/bin/python eval/label_ui.py            # http://127.0.0.1:8765
    PYTHONPATH=. .venv/bin/python eval/label_ui.py --port 9000

Labels follow reCAPTCHA tolerance (see DESIGN.md): the oracle passes a round when
every `required` tile is selected and no `forbidden` tile is; `optional` is
ignored. So mark clear object tiles required, clearly-empty tiles forbidden, and
leave genuinely ambiguous edge tiles optional.
"""
from __future__ import annotations

import argparse
import json
import http.server
import socketserver
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases.jsonl"
GRID_KINDS = {"grid", "dynamic", "retry", "multiround", "skip"}

PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>tile labeler</title>
<style>
  :root{--bg:#0f1115;--panel:#171a21;--ink:#e6e8ee;--muted:#8b93a7;--line:#262b36;
        --req:#1fb866;--forb:#e23b3b;--accent:#4c8bf5;}
  *{box-sizing:border-box}
  body{margin:0;font:14px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink);display:flex;height:100vh}
  #side{width:280px;flex:none;border-right:1px solid var(--line);overflow:auto;background:var(--panel)}
  #side h1{font-size:13px;letter-spacing:.5px;text-transform:uppercase;color:var(--muted);padding:14px 14px 6px}
  .item{padding:9px 14px;border-bottom:1px solid var(--line);cursor:pointer}
  .item:hover{background:#1d212b}
  .item.active{background:#222838;border-left:3px solid var(--accent);padding-left:11px}
  .item .id{font-weight:600}
  .item .meta{color:var(--muted);font-size:12px}
  .item .dirty{color:#f1c40f}
  #main{flex:1;overflow:auto;padding:24px;display:flex;flex-direction:column;align-items:center}
  #instr{font-size:18px;margin-bottom:4px;text-align:center}
  #instr b{color:#fff}
  #sub{color:var(--muted);margin-bottom:16px;text-align:center}
  #wrap{position:relative;display:inline-block;line-height:0;box-shadow:0 6px 30px rgba(0,0,0,.5)}
  #wrap img{display:block;width:560px;height:auto;user-select:none;-webkit-user-drag:none}
  #grid{position:absolute;inset:0;display:grid}
  .cell{position:relative;border:1px solid rgba(255,255,255,.35);cursor:pointer;
        display:flex;align-items:flex-start;justify-content:flex-start}
  .cell .n{font:700 13px/1 monospace;color:#fff;background:rgba(0,0,0,.55);padding:2px 4px;border-radius:0 0 4px 0}
  .cell.req{background:rgba(31,184,102,.45);border-color:var(--req)}
  .cell.forb{background:rgba(226,59,59,.42);border-color:var(--forb)}
  .cell.opt{background:rgba(255,255,255,.04)}
  #bar{margin-top:18px;display:flex;gap:10px;align-items:center}
  button{font:600 14px inherit;color:#fff;background:#2a3140;border:1px solid var(--line);border-radius:8px;padding:9px 16px;cursor:pointer}
  button:hover{background:#333c4e}
  button.primary{background:var(--accent);border-color:var(--accent)}
  button.primary:hover{filter:brightness(1.08)}
  #legend{display:flex;gap:18px;color:var(--muted);margin-top:14px;font-size:13px}
  .sw{display:inline-block;width:13px;height:13px;border-radius:3px;vertical-align:-2px;margin-right:5px}
  #status{color:var(--muted);min-height:18px;margin-top:10px}
  kbd{background:#2a3140;border:1px solid var(--line);border-radius:4px;padding:1px 6px;font-size:12px}
</style></head>
<body>
  <div id="side"><h1>cases.jsonl · grid rounds</h1><div id="list"></div></div>
  <div id="main">
    <div id="instr"></div>
    <div id="sub"></div>
    <div id="wrap"><img id="img" alt=""><div id="grid"></div></div>
    <div id="legend">
      <span><span class="sw" style="background:rgba(31,184,102,.6)"></span>required</span>
      <span><span class="sw" style="background:rgba(226,59,59,.6)"></span>forbidden</span>
      <span><span class="sw" style="background:rgba(255,255,255,.12);border:1px solid #555"></span>optional</span>
      <span>click a tile to cycle</span>
    </div>
    <div id="bar">
      <button id="save" class="primary">Save</button>
      <button id="saveNext">Save &amp; next ▸</button>
      <button id="allOpt">Clear → all optional</button>
      <button id="allForb">All forbidden</button>
    </div>
    <div id="status"></div>
    <div style="color:var(--muted);font-size:12px;margin-top:8px">
      keys: <kbd>S</kbd> save · <kbd>→</kbd>/<kbd>←</kbd> next/prev round</div>
  </div>
<script>
let ROUNDS=[], cur=-1, states=[], dirty={};
const $=s=>document.querySelector(s);
const CYCLE=["opt","req","forb"];

async function load(){
  ROUNDS=await (await fetch("/api/cases")).json();
  renderList(); if(ROUNDS.length) select(0);
}
function key(r){return r.case_id+"#"+r.round_index;}
function renderList(){
  $("#list").innerHTML=ROUNDS.map((r,i)=>{
    const d=dirty[key(r)]?' <span class="dirty">●</span>':'';
    const rd=r.n_rounds>1?` r${r.round_index+1}/${r.n_rounds}`:'';
    return `<div class="item ${i===cur?'active':''}" data-i="${i}">
      <div class="id">${r.case_id}${d}</div>
      <div class="meta">${r.kind} · ${r.rows}×${r.cols} · <b style="color:#cdd3e0">${r.target||'—'}</b>${rd}</div></div>`;
  }).join("");
  document.querySelectorAll(".item").forEach(el=>el.onclick=()=>select(+el.dataset.i));
}
function select(i){
  cur=i; const r=ROUNDS[i];
  states=new Array(r.rows*r.cols).fill("opt");
  (r.required||[]).forEach(k=>states[k]="req");
  (r.forbidden||[]).forEach(k=>states[k]="forb");
  $("#instr").innerHTML=r.instruction.replace(new RegExp("("+(r.target||"")+")","i"),"<b>$1</b>");
  $("#sub").textContent=`${r.case_id} · ${r.fixture} · round ${r.round_index+1}/${r.n_rounds}`;
  const img=$("#img"); img.src="/tasks/"+r.fixture+"/grid.png?"+Date.now();
  const g=$("#grid"); g.style.gridTemplateColumns=`repeat(${r.cols},1fr)`;
  g.style.gridTemplateRows=`repeat(${r.rows},1fr)`;
  g.innerHTML=states.map((s,k)=>`<div class="cell ${s}" data-k="${k}"><span class="n">${k}</span></div>`).join("");
  g.querySelectorAll(".cell").forEach(c=>c.onclick=()=>{
    const k=+c.dataset.k, ni=(CYCLE.indexOf(states[k])+1)%3;
    states[k]=CYCLE[ni]; c.className="cell "+states[k];
  });
  renderList(); $("#status").textContent="";
}
function setAll(s){states=states.map(()=>s);
  document.querySelectorAll(".cell").forEach((c,k)=>c.className="cell "+states[k]);}
async function save(){
  const r=ROUNDS[cur];
  const required=[],forbidden=[],optional=[];
  states.forEach((s,k)=>{(s==="req"?required:s==="forb"?forbidden:optional).push(k);});
  const body={case_id:r.case_id,round_index:r.round_index,required,forbidden,optional};
  const res=await fetch("/api/save",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(body)});
  if(res.ok){r.required=required;r.forbidden=forbidden;r.optional=optional;
    delete dirty[key(r)];
    const j=await res.json();
    $("#status").textContent=`saved ✓  required=[${required}]  forbidden=${forbidden.length} tiles`
      +(j.answer_key?`  · answer_key.json updated`:"")
      +(j.synced&&j.synced.length?`  · synced → ${j.synced.join(", ")}`:"");
    renderList();return true;}
  $("#status").textContent="SAVE FAILED: "+await res.text();return false;
}
$("#save").onclick=save;
$("#saveNext").onclick=async()=>{ if(await save() && cur<ROUNDS.length-1) select(cur+1); };
$("#allOpt").onclick=()=>setAll("opt");
$("#allForb").onclick=()=>setAll("forb");
document.addEventListener("keydown",e=>{
  if(e.target.tagName==="INPUT")return;
  if(e.key==="s"||e.key==="S"){e.preventDefault();save();}
  if(e.key==="ArrowRight"&&cur<ROUNDS.length-1)select(cur+1);
  if(e.key==="ArrowLeft"&&cur>0)select(cur-1);
});
// mark dirty when a tile changes (after a click, before save)
document.addEventListener("click",e=>{ if(e.target.closest(".cell")){ dirty[key(ROUNDS[cur])]=true; renderList(); }});
load();
</script>
</body></html>"""


def grid_rounds() -> list[dict]:
    """Flatten cases.jsonl into one entry per labelable grid round."""
    out = []
    for line in CASES.read_text().splitlines():
        if not line.strip():
            continue
        c = json.loads(line)
        if c.get("kind") not in GRID_KINDS:
            continue
        rounds = c.get("rounds") or []
        for ri, rd in enumerate(rounds):
            out.append({
                "case_id": c["id"], "kind": c["kind"], "round_index": ri,
                "n_rounds": len(rounds), "fixture": rd.get("fixture"),
                "rows": rd.get("rows", 3), "cols": rd.get("cols", 3),
                "instruction": rd.get("instruction", ""), "target": rd.get("target", ""),
                "required": rd.get("required", []), "forbidden": rd.get("forbidden", []),
                "optional": rd.get("optional", []),
            })
    return out


def save_round(payload: dict) -> dict:
    cid, ri = payload["case_id"], int(payload["round_index"])
    req = sorted(set(map(int, payload["required"])))
    forb = sorted(set(map(int, payload["forbidden"])))
    opt = sorted(set(map(int, payload["optional"])))

    objs = [json.loads(ln) for ln in CASES.read_text().splitlines() if ln.strip()]
    target, fixture = None, None
    for c in objs:
        if c["id"] == cid:
            rd = c["rounds"][ri]
            rd["required"], rd["forbidden"], rd["optional"] = req, forb, opt
            target, fixture = rd.get("target"), rd.get("fixture")
            break
    else:
        raise KeyError(f"case {cid} not found")

    # Auto-sync: the same photo can appear in several rounds (e.g. a static grid
    # also chained inside a multiround case). Keep every round that shows the
    # SAME fixture for the SAME target object in lockstep, so they never drift.
    synced = []
    tlow = (target or "").strip().lower()
    for c in objs:
        for j, rd in enumerate(c.get("rounds", [])):
            if (c["id"], j) == (cid, ri):
                continue
            if rd.get("fixture") == fixture and (rd.get("target") or "").strip().lower() == tlow:
                rd["required"], rd["forbidden"], rd["optional"] = req, forb, opt
                synced.append(f"{c['id']}#r{j}")
    CASES.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in objs) + "\n",
                     encoding="utf-8")

    # Mirror into the fixture's answer_key.json when it documents the same object.
    ak_updated = False
    if fixture:
        akp = HERE / "tasks" / fixture / "answer_key.json"
        metap = HERE / "tasks" / fixture / "meta.json"
        if akp.exists() and metap.exists():
            meta = json.loads(metap.read_text())
            if (meta.get("target_word") or "").strip().lower() == (target or "").strip().lower():
                akp.write_text(json.dumps({
                    "correct_tiles": req, "forbidden_tiles": forb, "optional_tiles": opt,
                    "labeled": True,
                    "_note": f"0-based row-major. Labeled via label_ui.py for {target!r}.",
                }, indent=2, ensure_ascii=False))
                ak_updated = True
    return {"ok": True, "answer_key": ak_updated, "synced": synced}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if path == "/api/cases":
            return self._send(200, json.dumps(grid_rounds()))
        if path.startswith("/tasks/"):
            f = (HERE / path.lstrip("/")).resolve()
            if HERE in f.parents and f.exists() and f.suffix == ".png":
                return self._send(200, f.read_bytes(), "image/png")
            return self._send(404, b"not found", "text/plain")
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/save":
            return self._send(404, b"not found", "text/plain")
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n) or b"{}")
            return self._send(200, json.dumps(save_round(payload)))
        except Exception as e:  # noqa: BLE001
            return self._send(500, str(e), "text/plain")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8777,
                    help="Preferred port; the next free one is used if it's taken.")
    args = ap.parse_args()
    n = len(grid_rounds())

    socketserver.ThreadingTCPServer.allow_reuse_address = True
    httpd = None
    for port in range(args.port, args.port + 20):
        try:
            httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if httpd is None:
        print(f"no free port in {args.port}..{args.port + 19}", flush=True)
        return 1

    with httpd:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/"
        print(f"Tile labeler on {url}  ({n} grid rounds from cases.jsonl)", flush=True)
        print("Click tiles to cycle required/forbidden/optional. Ctrl+C to stop.", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
