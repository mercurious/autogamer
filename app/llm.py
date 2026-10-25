#!/usr/bin/env python3
# Streaming chat with llama-server (OpenAI API + return_progress) that shows the model's work live on MangoHud:
# prompt reading progress, then tokens written and the generation rate. Returns (text, timings).
import json, threading, time, urllib.request
import hud
_read_tps = [0.0]      # the last prompt read speed (llama-server timings): the next read's bar is time / its estimate

def chat(url, messages, max_tokens=48, temperature=0.7, timeout=300, cache=False):
    """cache=True: llama-server keeps the prompt's KV and reads only what differs from the last request (keep the
    fixed text first: the system prompt and anything that never changes)"""
    body = {"messages": messages, "max_tokens": max_tokens, "temperature": temperature, "cache_prompt": cache,
            "stream": True, "return_progress": True, "timings_per_token": True}
    req = urllib.request.Request(url + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    t0 = time.time(); text = ""; ntok = 0; t_first = None; timings = {}; shown = 0; total = [0]
    hud.state("read")      # the speedo keeps the last writing speed while the prompt is read
    reading = threading.Event(); reading.set()
    def tick():          # the prompt is read in one batch (one progress event): a bar from the last read speed
        while reading.is_set():
            el = time.time() - t0
            if total[0] and _read_tps[0]: s = "read " + hud.bar(min(el * _read_tps[0] / total[0], 0.9), 6)
            else: s = "read %s%ds" % ("%d tok " % total[0] if total[0] else "", el)
            if reading.is_set(): hud.state(s)      # not over "write 1" when the first token came meanwhile
            time.sleep(0.25)
    threading.Thread(target=tick, daemon=True).start()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode(errors="replace").strip()
            if not line.startswith("data: ") or line == "data: [DONE]": continue
            ev = json.loads(line[6:]); now = time.time()
            p = ev.get("prompt_progress")
            if p: total[0] = p.get("total", 0) - p.get("cache", 0)      # cache_prompt: only the rest is read
            for c in ev.get("choices", []):
                d = (c.get("delta") or {}).get("content")
                if d:
                    if reading.is_set(): reading.clear(); t_first = now
                    text += d; ntok += 1
                    if now - shown > 0.25 or ntok == 1:
                        if ntok > 1: hud.rate((ntok - 1) / max(now - t_first, 1e-3))
                        hud.state("write %d" % ntok); shown = now
            if ev.get("timings"): timings = ev["timings"]
    reading.clear()
    tps = timings.get("predicted_per_second") or ((ntok - 1) / max(time.time() - t_first, 1e-3) if t_first and ntok > 1 else 0)
    if timings.get("prompt_n", 0) > 8: _read_tps[0] = timings.get("prompt_per_second") or _read_tps[0]
    if tps: hud.rate(tps)
    hud.state("think %.1fs" % (time.time() - t0))
    return text.strip(), timings
