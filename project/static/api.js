/**
 * api.js — single source of truth for the backend URL.
 *
 * To point this UI at a non-local backend later, change the one line below.
 * No other file references the backend host.
 */
const BASE_URL = "http://localhost:5000";

const api = {
  // ---- Config -------------------------------------------------------------
  async getConfig() {
    const r = await fetch(`${BASE_URL}/api/config`);
    if (!r.ok) throw new Error(`GET /api/config → HTTP ${r.status}`);
    return r.json();
  },
  async saveConfig(data) {
    const r = await fetch(`${BASE_URL}/api/config`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(`POST /api/config → HTTP ${r.status}`);
    return r.json();
  },

  // ---- Pipeline -----------------------------------------------------------
  async generateExcel() {
    const r = await fetch(`${BASE_URL}/api/generate-excel`, { method: "POST" });
    const j = await r.json();
    if (!r.ok || j.ok === false) throw new Error(j.error || `HTTP ${r.status}`);
    return j;
  },

  /**
   * SSE-style streaming solver. Calls onMessage(line) for every `data: …`
   * line received, onDone() when the server closes the stream, and onError()
   * on transport failure. Uses fetch+ReadableStream because /api/solve is
   * POST (the EventSource API only supports GET).
   */
  async solve({ onMessage, onDone, onError }) {
    try {
      const resp = await fetch(`${BASE_URL}/api/solve`, { method: "POST" });
      if (!resp.ok || !resp.body) {
        throw new Error(`POST /api/solve → HTTP ${resp.status}`);
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // SSE events are separated by a blank line (\n\n).
        const events = buffer.split("\n\n");
        buffer = events.pop(); // possibly partial
        for (const evt of events) {
          for (const line of evt.split("\n")) {
            if (line.startsWith("data: ")) onMessage(line.slice(6));
          }
        }
      }
      onDone && onDone();
    } catch (err) {
      onError && onError(err);
    }
  },

  // ---- Results / downloads ------------------------------------------------
  async getResults() {
    const r = await fetch(`${BASE_URL}/api/results`);
    if (!r.ok) throw new Error(`GET /api/results → HTTP ${r.status}`);
    return r.json();
  },
  downloadZipUrl()   { return `${BASE_URL}/api/download/zip`; },
  downloadExcelUrl() { return `${BASE_URL}/api/download/excel`; },
};

window.api = api; // make it available to app.js without ES modules
