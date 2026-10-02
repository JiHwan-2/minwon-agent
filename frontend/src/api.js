async function readJson(res) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `서버 오류 (${res.status})`);
  }
  return res.json();
}

export const getHealth = () => fetch("/api/health").then(readJson);

export const createSession = () =>
  fetch("/api/sessions", { method: "POST" }).then(readJson).then((b) => b.session_id);

export const followupUrl = (sessionId) => `/api/sessions/${sessionId}/files/followup.ics`;

export async function downloadPdf(sessionId, edits, filename) {
  const res = await fetch(`/api/sessions/${sessionId}/files/package.pdf`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(edits),
  });
  if (!res.ok) await readJson(res);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function sendMessage(sessionId, text, onEvent) {
  const res = await fetch(`/api/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) await readJson(res);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = done ? "" : lines.pop();
    for (const line of lines) if (line.trim()) onEvent(JSON.parse(line));
    if (done) break;
  }
}
