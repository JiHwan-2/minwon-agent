async function readJson(res) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const error = new Error(typeof body.detail === "string" ? body.detail : `서버 오류 (${res.status})`);
    error.status = res.status;
    throw error;
  }
  return res.json();
}

// 사진 파일 원본을 base64로 (줄이거나 다시 그리면 촬영 위치·시각 정보(EXIF)가 사라지므로 원본 그대로 보낸다)
export function readPhoto(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve({ name: file.name, data: String(reader.result).split(",", 2)[1] ?? "" });
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export const getHealth = () => fetch("/api/health").then(readJson);

export const createSession = () =>
  fetch("/api/sessions", { method: "POST" }).then(readJson).then((b) => b.session_id);

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

export const cancelRun = (sessionId) =>
  fetch(`/api/sessions/${sessionId}/cancel`, { method: "POST" }).then(readJson);

export async function sendMessage(sessionId, text, onEvent, signal, lang = "", photo = null) {
  const res = await fetch(`/api/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // lang: 화면 언어 (서버가 시민의 언어를 판단하지 못할 때 대체), photo: 새 민원과 함께 올린 현장 사진 {name, data}
    body: JSON.stringify(photo ? { text, lang, photo } : { text, lang }),
    signal,
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
