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
  const revisingRef = useRef(false);

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
      case "tool_start":
        setTimeline((t) => {
          const idx = t.findLastIndex((e) => e.node === ev.node && e.status !== "done");
          const call = { id: nextId(), tool: ev.tool, title: ev.title, input: ev.input, status: "running" };
          return t.map((e, i) => (i === idx ? { ...e, tools: [...(e.tools ?? []), call] } : e));
        });
        break;
      case "tool_end":
        setTimeline((t) =>
          t.map((e) => {
            if (e.node !== ev.node || !e.tools) return e;
            const idx = e.tools.findLastIndex((x) => x.tool === ev.result.tool && x.status === "running");
            if (idx === -1) return e;
            const tools = e.tools.map((x, i) => (i === idx ? { ...x, status: "done", result: ev.result } : x));
            return { ...e, tools };
          }),
        );
        break;
      case "node_end": {
        const { log = [], ...data } = ev.data;
        finishEntry(ev.node, { data, log: log[0], logs: log });
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
      case "ask": {
        setPhase("asking");
        const choosing = ev.options.length > 0;
        const node = choosing ? "confirm_location" : "ask";
        setTimeline((t) => [...t, { id: nextId(), node, status: "waiting", data: { questions: ev.questions, options: ev.options } }]);
        addMessage(
          "agent",
          choosing ? "위치를 정확히 하려고 해요." : "정확히 안내하려면 몇 가지가 더 필요해요. 한 번에 이어서 답해 주세요.",
          { questions: ev.questions, options: ev.options },
        );
        break;
      }
      case "ready": {
        setPhase("ready");
        const result = { pkg: ev.package, decision: ev.decision, review: ev.review, locationConfirmed: ev.location_confirmed !== false };
        if (revisingRef.current) {
          addMessage("agent", `요청하신 내용을 반영해 다시 썼어요. (${ev.package.version}번째 초안)`, result);
          break;
        }
        const loc = ev.location ?? {};
        const confirmedPlace = loc.address ? `${loc.place_name ? `${loc.place_name} · ` : ""}${loc.address}` : "";
        const facts = ev.info.facts.map((f) =>
          f.slot === "location" && confirmedPlace
            ? `${SLOT_LABEL.location}: ${confirmedPlace}`
            : `${SLOT_LABEL[f.slot] ?? f.slot}: ${f.value}`,
        );
        if (confirmedPlace && !ev.info.facts.some((f) => f.slot === "location")) facts.unshift(`${SLOT_LABEL.location}: ${confirmedPlace}`);
        const unknown = ev.info.unknown.map((s) => SLOT_LABEL[s] ?? s);
        addMessage("agent", "필요한 정보를 정리했어요.", { facts, unknown });
        const where = ev.location?.address ? `${ev.location.address} 기준으로 ` : "";
        addMessage("agent", `${where}담당 기관을 찾고 민원 초안을 준비했어요. 내용을 확인한 뒤 직접 제출해 주세요.`, result);
        addMessage("agent", "고칠 점이 있으면 말씀해 주세요. 예: '더 짧게', '요청사항에 CCTV 설치도 넣어 줘'");
        break;
      }
      case "error":
        addMessage("error", ev.message);
        setTimeline((t) => t.map((e) => (e.status === "running" ? { ...e, status: "error" } : e)));
        break;
      default:
        break;
    }
  };

  const send = async (text) => {
    const continuing = phase === "asking" || phase === "ready";
    revisingRef.current = phase === "ready";
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
      setPhase((p) => (p === "running" ? (revisingRef.current ? "ready" : "idle") : p));
    }
  };

  const reset = () => {
    sessionRef.current = null;
    revisingRef.current = false;
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
        <Chat messages={messages} phase={phase} onSend={send} latestId={messages[messages.length - 1]?.id} />
        <AgentLog timeline={timeline} running={phase === "running"} />
      </main>
    </div>
  );
}
