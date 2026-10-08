// Cache the built app shell so a previously visited app opens without a network.
// Notes and recordings live in IndexedDB; API requests always go to the server.
const CACHE = "secretary-shell-v1";

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    const response = await fetch("/", { cache: "reload" });
    if (!response.ok) throw new Error("Unable to cache Secretary");
    const html = await response.clone().text();
    const assets = [...html.matchAll(/(?:src|href)="(\/assets\/[^\"]+)"/g)].map((match) => match[1]);
    await cache.addAll(assets);
    await cache.put("/", response);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || event.request.method !== "GET" || url.pathname.startsWith("/api/") || url.pathname === "/ws") return;
  if (event.request.mode === "navigate") {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE);
      try {
        const response = await fetch(event.request);
        if (!response.ok) throw new Error("Offline");
        const html = await response.clone().text();
        const assets = [...html.matchAll(/(?:src|href)="(\/assets\/[^\"]+)"/g)].map((match) => match[1]);
        // Keep the cached shell and its assets together across future builds.
        await cache.addAll(assets);
        await cache.put("/", response.clone());
        return response;
      } catch { return (await cache.match("/")) || Response.error(); }
    })());
  } else if (url.pathname.startsWith("/assets/")) {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE);
      const cached = await cache.match(event.request);
      if (cached) return cached;
      const response = await fetch(event.request);
      if (response.ok) await cache.put(event.request, response.clone());
      return response;
    })());
  }
});

// Background Sync is optional (not supported by all browsers). The foreground
// controller also retries on online events and while the app is open.
self.addEventListener("sync", (event) => {
  if (event.tag === "secretary-recordings") event.waitUntil(syncRecordings());
});

async function syncRecordings() {
  const run = async () => {
    const db = await new Promise((resolve, reject) => {
      const request = indexedDB.open("secretary-offline", 1);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    const all = (store) => new Promise((resolve, reject) => {
      const request = db.transaction(store).objectStore(store).getAll();
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    const put = (store, value) => new Promise((resolve, reject) => {
      const transaction = db.transaction(store, "readwrite");
      transaction.objectStore(store).put(value);
      transaction.oncomplete = resolve;
      transaction.onabort = () => reject(transaction.error);
    });
    try {
      for (const note of await all("notes")) {
        if (!note.localOnly) continue;
        const response = await fetch("/api/notes", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: note.id, title: note.title, directory: note.directory || "", body: note.body }),
        });
        if (!response.ok) {
          if (response.status >= 500 || response.status === 408 || response.status === 429) throw new Error("Note sync failed");
          const error = await response.json();
          for (const job of await all("recordings")) {
            if (job.note_id === note.id && !job.accepted && job.status !== "succeeded") {
              await put("recordings", { ...job, status: "failed", error: `Cannot create target note: ${error.detail || "Note sync failed"}` });
            }
          }
          continue;
        }
        await put("notes", { ...note, ...await response.json(), localOnly: false });
      }
      const jobs = (await all("recordings")).sort((a, b) => a.created.localeCompare(b.created));
      const notes = await all("notes");
      for (const job of jobs) {
        if (job.accepted || job.status === "failed" || job.status === "succeeded") continue;
        if (notes.some((note) => note.id === job.note_id && note.localOnly)) continue;
        const data = new FormData();
        data.set("id", job.id);
        data.set("mode", job.mode);
        if (job.note_id) data.set("note_id", job.note_id);
        data.set("audio", job.audio, "recording.webm");
        const response = await fetch("/api/recordings", { method: "POST", body: data });
        if (!response.ok) {
          if (response.status >= 500 || response.status === 408 || response.status === 429) throw new Error("Upload failed");
          const error = await response.json();
          await put("recordings", { ...job, status: "failed", error: error.detail || "Upload failed" });
          continue;
        }
        const remote = await response.json();
        await put("recordings", { ...job, status: remote.status, accepted: true, audio: remote.status === "succeeded" ? undefined : job.audio, error: remote.error || undefined, nextAttempt: undefined });
      }
      for (const client of await self.clients.matchAll()) client.postMessage({ type: "recording-sync" });
    } finally { db.close(); }
  };
  if (self.navigator.locks) await self.navigator.locks.request("secretary-recording-sync", run);
  else await run();
}
