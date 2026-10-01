import { useEffect, useRef, useState } from "react";
import { createSession, getHealth, sendMessage } from "./api.js";
import { SLOT_LABEL } from "./labels.js";
import Chat from "./components/Chat.jsx";
import AgentLog from "./components/AgentLog.jsx";

let seq = 0;
const nextId = () => ++seq;

const GREETING = {
  id: nextId(),
  role: "agent",
  text: "안녕하세요, AI민원길잡이입니다. 생활하면서 불편했던 일을 평소 말투로 적어 주세요. 담당 기관과 해결 방법을 찾아 민원 준비를 도와드릴게요.",
};

const EMERGENCY_TEXT =
  "긴급 상황이라면 지금 바로 112(범죄·사고) 또는 119(화재·구조·응급)에 먼저 신고하세요. 민원 준비는 그다음에 도와드릴게요.";

export default function App() {
  const [health, setHealth] = useState(null);
  const [messages, setMessages] = useState([GREETING]);
  const [timeline, setTimeline] = useState([]);
  const [phase, setPhase] = useState("idle"); // idle | running | asking | ready
  const sessionRef = useRef(null);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth({ status: "down" }));
  }, []);

  const addMessage = (role, text, extra = {}) =>
    setMessages((m) => [...m, { id: nextId(), role, text, ...extra }]);

  const finishEntry = (node, patch) =>
    setTimeline((t) => {
      const idx = t.findLastIndex((e) => e.node === node && e.status !== "done");
      if (idx === -1) return [...t, { id: nextId(), node, status: "done", ...patch }];
      return t.map((e, i) => (i === idx ? { ...e, status: "done", ...patch } : e));
    });

  const onEvent = (ev) => {
    switch (ev.type) {
      case "masked":
        setMessages((m) => {
          const last = m.findLastIndex((x) => x.role === "user");
          return m.map((x, i) => (i === last ? { ...x, text: ev.text, masked: ev.findings } : x));
        });
        break;
      case "node_start":
        setTimeline((t) => [...t, { id: nextId(), node: ev.node, status: "running" }]);
        break;
      case "node_end": {
        const { log = [], ...data } = ev.data;
        finishEntry(ev.node, { data, log: log[0] });
        if (ev.node === "guard" && data.safety?.emergency) addMessage("alert", EMERGENCY_TEXT);
        if (ev.node === "understand") {
          const u = data.understanding;
          addMessage("agent", `'${u.title}' 문제로 이해했어요. (${u.category_label})`);
        }
        if (ev.node === "plan") {
          addMessage("agent", "처리 계획을 세웠어요.", { plan: data.plan });
        }
        break;
      }
      case "ask":
        setPhase("asking");
        setTimeline((t) => [...t, { id: nextId(), node: "ask", status: "waiting", data: { questions: ev.questions } }]);
        addMessage("agent", "정확히 안내하려면 몇 가지가 더 필요해요. 한 번에 이어서 답해 주세요.", { questions: ev.questions });
        break;
      case "ready": {
        setPhase("ready");
        const facts = ev.info.facts.map((f) => `${SLOT_LABEL[f.slot] ?? f.slot}: ${f.value}`);
        const unknown = ev.info.unknown.map((s) => SLOT_LABEL[s] ?? s);
        addMessage("agent", "필요한 정보를 정리했어요.", { facts, unknown, nextStep: true });
        break;
      }
      case "error":
        addMessage("error", ev.message);
        setTimeline((t) => t.map((e) => (e.status === "running" ? { ...e, status: "error" } : e)));
        if (ev.code === "session_done") setPhase("ready");
        break;
      default:
        break;
    }
  };

  const send = async (text) => {
    const continuing = phase === "asking";
    if (!continuing) setTimeline([]);
    addMessage("user", text);
    setPhase("running");
    try {
      if (!continuing || !sessionRef.current) sessionRef.current = await createSession();
      await sendMessage(sessionRef.current, text, onEvent);
    } catch (e) {
      addMessage("error", `서버에 연결하지 못했어요. 백엔드가 켜져 있는지 확인해 주세요. (${e.message})`);
      setTimeline((t) => t.map((x) => (x.status === "running" ? { ...x, status: "error" } : x)));
    } finally {
      setPhase((p) => (p === "running" ? "idle" : p));
    }
  };

  const reset = () => {
    sessionRef.current = null;
    setMessages([GREETING]);
    setTimeline([]);
    setPhase("idle");
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">길</div>
          <div>
            <h1>AI민원길잡이</h1>
            <p>생활불편을 말하면, 담당 기관과 민원을 준비해 드려요</p>
          </div>
        </div>
        <div className="topbar-actions">
          {health && (
            <span className={`pill ${health.status === "ok" ? "" : "pill-danger"}`} title="현재 판단 엔진">
              {health.status === "ok" ? `판단 엔진 · ${health.model}` : "서버 연결 안 됨"}
            </span>
          )}
          <button className="btn btn-ghost" onClick={reset} disabled={phase === "running"}>
            새 민원
          </button>
        </div>
      </header>

      <main className="layout">
        <Chat messages={messages} phase={phase} onSend={send} />
        <AgentLog timeline={timeline} running={phase === "running"} />
      </main>
    </div>
  );
}
