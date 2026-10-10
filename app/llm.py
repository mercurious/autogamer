#!/usr/bin/env python3
# Streaming chat with llama-server (OpenAI API + return_progress) that shows the model's work live on MangoHud:
# prompt reading progress, then tokens written and the generation rate. Returns (text, timings).
import json, threading, time, urllib.request
import hud

def chat(url, messages, max_tokens=48, temperature=0.7, timeout=300, cache=False):
    """cache=True: llama-server keeps the prompt's KV and reads only what differs from the last request (keep the
    fixed text first: the system prompt and anything that never changes)"""
    body = {"messages": messages, "max_tokens": max_tokens, "temperature": temperature, "cache_prompt": cache,
            "stream": True, "return_progress": True, "timings_per_token": True}
    req = urllib.request.Request(url + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    t0 = time.time(); text = ""; ntok = 0; t_first = None; timings = {}; shown = 0; total = [0]
    hud.state("reading"); hud.rate("")
    reading = threading.Event(); reading.set()
    def tick():          # the prompt is read in one batch (one progress event): show the seconds while it reads
        while reading.is_set():
            hud.state("reading %s%d s" % ("%d tok " % total[0] if total[0] else "", time.time() - t0)); time.sleep(0.5)
    threading.Thread(target=tick, daemon=True).start()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode(errors="replace").strip()
            if not line.startswith("data: ") or line == "data: [DONE]": continue
            ev = json.loads(line[6:]); now = time.time()
            p = ev.get("prompt_progress")
            if p: total[0] = p.get("total", 0)
            for c in ev.get("choices", []):
                d = (c.get("delta") or {}).get("content")
                if d:
                    if reading.is_set():
                        reading.clear(); t_first = now
                        hud.rate("%.0f tok/s read" % (total[0] / max(now - t0, 1e-3)) if total[0] else "")
                    text += d; ntok += 1
                    if now - shown > 0.25 or ntok == 1:
                        if ntok > 1: hud.rate("%.1f tok/s" % ((ntok - 1) / max(now - t_first, 1e-3)))
                        hud.state("writing %d tok" % ntok); shown = now
            if ev.get("timings"): timings = ev["timings"]
    reading.clear()
    tps = timings.get("predicted_per_second") or ((ntok - 1) / max(time.time() - t_first, 1e-3) if t_first and ntok > 1 else 0)
    if tps: hud.rate("%.1f tok/s" % tps)
    hud.state("think %.1f s" % (time.time() - t0))
    return text.strip(), timings
