#!/usr/bin/env python3
"""
Récepteur de webhooks Documenso pour la démonstration.

Rôle : montrer, pendant la démo, qu'un système tiers (demain Zoho CRM) est
informé en temps réel du cycle de vie d'un document. Il ne fait qu'écouter et
tenir un journal lisible. Il n'appelle aucun service externe, et ne connaît
aucun secret.

Écoute sur le réseau Docker interne (port 9000). Jamais publié sur l'hôte :
Caddy l'expose derrière Basic Auth sur demo.<hostname>/webhooks.

  POST /            réception d'un événement Documenso
  GET  /events      les 100 derniers événements, en JSON
  GET  /            page de suivi, rafraîchie toute seule

Stdlib uniquement : aucune dépendance à installer, aucune image à construire.
"""

import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STORE = "/data/events.jsonl"
MAX_RENDER = 100
LOCK = threading.Lock()

PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Triactis - flux d'evenements Documenso</title>
<style>
 :root{color-scheme:light dark}
 body{margin:0;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
      background:#faf9f7;color:#1c1b19}
 main{max-width:960px;margin:0 auto;padding:24px 16px}
 h1{font-size:20px;margin:0 0 4px}
 p.lead{color:#6b6862;margin:0 0 20px}
 table{width:100%;border-collapse:collapse;font-size:14px}
 th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #e6e3dd;vertical-align:top}
 th{font-weight:600;color:#6b6862;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
 td.ev{font-weight:600}
 .empty{padding:32px;text-align:center;color:#6b6862;border:1px dashed #d8d4cc;border-radius:8px}
 .wrap{overflow-x:auto}
 @media (prefers-color-scheme: dark){
  body{background:#16150f;color:#f0eee9}
  th,td{border-bottom-color:#33302a} p.lead,th{color:#a8a49c}
  .empty{border-color:#33302a;color:#a8a49c}
 }
</style></head><body><main>
<h1>Flux d'evenements Documenso</h1>
<p class="lead">Ce que le CRM recevrait en temps reel. Rafraichissement automatique toutes les 3 secondes.</p>
<div class="wrap"><table><thead><tr>
<th>Heure</th><th>Evenement</th><th>Document</th><th>External ID</th><th>Statut</th>
</tr></thead><tbody id="rows"></tbody></table></div>
<div id="empty" class="empty" hidden>Aucun evenement recu pour l'instant.</div>
<script>
async function tick(){
  try{
    const r = await fetch('events', {cache:'no-store'});
    const events = await r.json();
    const body = document.getElementById('rows');
    document.getElementById('empty').hidden = events.length > 0;
    body.innerHTML = '';
    for (const e of events.slice().reverse()){
      const tr = document.createElement('tr');
      for (const [cls, val] of [['t', e.at], ['ev', e.event], ['', e.title],
                                ['', e.externalId], ['', e.status]]){
        const td = document.createElement('td');
        td.className = cls; td.textContent = val || '-';
        tr.appendChild(td);
      }
      body.appendChild(tr);
    }
  }catch(_){}
}
tick(); setInterval(tick, 3000);
</script>
</main></body></html>
"""


def summarise(payload):
    """Extrait les quelques champs utiles à la démonstration."""
    data = payload.get("payload") or {}
    return {
        "at": datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S"),
        "event": payload.get("event") or "?",
        "title": data.get("title") or "",
        "externalId": data.get("externalId") or "",
        "status": data.get("status") or "",
    }


def read_events():
    try:
        with open(STORE, "r", encoding="utf-8") as handle:
            lines = handle.readlines()[-MAX_RENDER:]
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body, ctype):
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path in ("/events", "/events/"):
            self._send(200, json.dumps(read_events()), "application/json; charset=utf-8")
        elif path == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
        else:
            self._send(404, "not found", "text/plain; charset=utf-8")

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {"event": "UNPARSEABLE"}

        record = summarise(payload)
        with LOCK:
            os.makedirs(os.path.dirname(STORE), exist_ok=True)
            with open(STORE, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

        self._send(200, '{"ok":true}', "application/json")

    def log_message(self, fmt, *args):
        """Journalise l'évènement, jamais l'URL complète ni la query string."""
        print(f"[webhook-sink] {self.command} {self.path.split('?', 1)[0]}", flush=True)


if __name__ == "__main__":
    os.makedirs("/data", exist_ok=True)
    print("[webhook-sink] écoute sur 0.0.0.0:9000 (réseau Docker interne)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 9000), Handler).serve_forever()
