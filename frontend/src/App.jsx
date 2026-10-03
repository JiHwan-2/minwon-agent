import { useEffect, useMemo, useRef, useState } from "react";
import { cancelRun, createSession, getHealth, sendMessage } from "./api.js";
import { I18nContext, LANGS, makeT, uiLang } from "./i18n.js";
import Chat from "./components/Chat.jsx";
import AgentLog from "./components/AgentLog.jsx";

let seq = 0;
const nextId = () => ++seq;
const now = () => new Date().toTimeString().slice(0, 8);

// 정해진 안내 문장은 번역 키로 저장해 두고 화면에 그릴 때 번역한다 (언어를 바꾸면 지난 메시지도 따라 바뀜)
const greeting = () => ({ id: nextId(), role: "agent", key: "msg.greeting" });

function initialLang() {
  try {
    const saved = localStorage.getItem("lang");
    if (saved) return uiLang(saved);
  } catch {
    // 저장소를 쓸 수 없으면 브라우저 언어로
  }
  return uiLang(navigator.language);
}

export default function App() {
  const [lang, setLangState] = useState(initialLang);
  const [health, setHealth] = useState(null);
  const [messages, setMessages] = useState(() => [greeting()]);
  const [timeline, setTimeline] = useState([]);
  const [phase, setPhase] = useState("idle"); // idle | running | asking | ready | clarify(민원이 아니거나 불분명해 다시 말해 주길 기다림)
  const [stopping, setStopping] = useState(false);
  const [crisis, setCrisis] = useState(false); // 이번 메시지에 위기 표현이 있었으면 민원 예시 버튼을 내밀지 않는다
  const sessionRef = useRef(null);
  const revisingRef = useRef(false);
  const abortRef = useRef(null);
  const langRef = useRef(lang);
  const i18n = useMemo(() => ({ lang, t: makeT(lang) }), [lang]);
  const { t } = i18n;

  const setLang = (code) => {
    const next = uiLang(code);
    langRef.current = next;
    setLangState(next);
    try {
      localStorage.setItem("lang", next);
    } catch {
      // 저장하지 못해도 이번 화면에서는 바뀐 언어로 보인다
    }
  };

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth({ status: "down" }));
  }, []);

  const addMessage = (role, text, extra = {}) =>
    setMessages((m) => [...m, { id: nextId(), role, text, ...extra }]);
  const addKey = (role, key, vars, extra = {}) => addMessage(role, "", { key, vars, ...extra });

  const finishEntry = (node, patch) =>
    setTimeline((t) => {
      const idx = t.findLastIndex((e) => e.node === node && e.status !== "done");
      if (idx === -1) return [...t, { id: nextId(), node, status: "done", ...patch }];
      return t.map((e, i) => (i === idx ? { ...e, status: "done", ...patch } : e));
    });

  const onEvent = (ev) => {
    switch (ev.type) {
      case "crisis":
        // 위기 표현: AI 판단과 관계없이 서버가 정해 둔 문장(109 안내)을 그대로 보여 준다
        addMessage("alert", ev.message);
        setCrisis(true);
        break;
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
        if (ev.node === "guard" && data.safety?.emergency) addKey("alert", "msg.emergency");
        if (ev.node === "understand") {
          const u = data.understanding;
          setLang(u.language); // 시민이 쓴 언어로 화면을 바꾼다 (지원하지 않는 언어면 영어)
          if (u.intent === "complaint") addKey("agent", "msg.understood", { title: u.title, category: { key: `category.${u.category}` } });
        }
        if (ev.node === "plan") addKey("agent", "msg.planned", {}, { plan: data.plan });
        break;
      }
      case "ask": {
        setPhase("asking");
        const choosing = ev.options.length > 0;
        const node = choosing ? "confirm_location" : "ask";
        setTimeline((t) => [...t, { id: nextId(), node, status: "waiting", data: { questions: ev.questions, options: ev.options } }]);
        addKey("agent", choosing ? "msg.askLocation" : "msg.askMore", {}, { questions: ev.questions, options: ev.options });
        break;
      }
      case "ready": {
        setPhase("ready");
        const result = {
          pkg: ev.package,
          decision: ev.decision,
          review: ev.review,
          translation: ev.translation,
          locationConfirmed: ev.location_confirmed !== false,
          cases: ev.cases,
          files: ev.files,
          sessionId: sessionRef.current,
        };
        if (revisingRef.current) {
          addKey("agent", "msg.revised", { version: ev.package.version }, result);
          break;
        }
        const loc = ev.location ?? {};
        const confirmedPlace = loc.address ? `${loc.place_name ? `${loc.place_name} · ` : ""}${loc.address}` : "";
        const facts = ev.info.facts.map((f) => (f.slot === "location" && confirmedPlace ? { slot: f.slot, value: confirmedPlace } : f));
        if (confirmedPlace && !ev.info.facts.some((f) => f.slot === "location")) facts.unshift({ slot: "location", value: confirmedPlace });
        addKey("agent", "msg.facts", {}, { facts, unknown: ev.info.unknown });
        if (loc.address) addKey("agent", "msg.readyAt", { address: loc.address }, result);
        else addKey("agent", "msg.ready", {}, result);
        addKey("agent", "msg.reviseHint");
        break;
      }
      case "redirect":
        // 민원이 아니거나 불분명한 입력: 안내만 하고 같은 대화에서 이어서 말하길 기다린다
        addMessage("agent", ev.message, ev.referral ? { referral: ev.referral } : {});
        setPhase("clarify");
        break;
      case "off_topic": {
        // 대화 도중 관계없는 말: 진행하지 않고 그대로 둔다 (질문 중이면 같은 질문을 다시 보여 줌)
        const asking = ev.stage === "asking";
        const entry = {
          id: nextId(),
          node: "off_topic",
          status: "done",
          log: {
            detailKey: ev.crisis ? "log.offCrisis" : asking ? "log.offAsking" : "log.offReady",
            reason: ev.reason,
            source: ev.source,
            error: ev.error,
            at: now(),
          },
        };
        // 답을 기다리는 '추가 질문' 카드는 계속 맨 아래에 둔다
        setTimeline((t) => {
          const waiting = t.findLastIndex((e) => e.status === "waiting");
          return waiting === -1 ? [...t, entry] : [...t.slice(0, waiting), entry, ...t.slice(waiting)];
        });
        addMessage("agent", ev.message, ev.questions.length > 0 ? { questions: ev.questions, options: ev.options } : {});
        setPhase(ev.stage);
        break;
      }
      case "answer": {
        // 진행 중인 민원에 대한 질문: Claude가 확인된 정보로 답하고, 진행은 그대로 둔다 (질문 중이면 같은 질문을 다시 보여 줌)
        const entry = {
          id: nextId(),
          node: "answer",
          status: "done",
          log: { detailKey: "log.answered", guarded: ev.guarded, reason: ev.reason, source: ev.source, error: ev.error, at: now() },
        };
        setTimeline((t) => {
          const waiting = t.findLastIndex((e) => e.status === "waiting");
          return waiting === -1 ? [...t, entry] : [...t.slice(0, waiting), entry, ...t.slice(waiting)];
        });
        addMessage("agent", ev.message, ev.questions.length > 0 ? { questions: ev.questions, options: ev.options } : {});
        setPhase(ev.stage);
        break;
      }
      case "topic_changed": {
        // 대화 중 다른 종류의 민원 → 새 민원으로 처음부터 (작업 기록도 새로 시작)
        revisingRef.current = false;
        const from = { key: `category.${ev.from_category}` };
        const to = { key: `category.${ev.to_category}` };
        setTimeline([
          { id: nextId(), node: "switch", status: "done", log: { from, to, reason: ev.reason, source: ev.source, error: ev.error, at: now() } },
        ]);
        addKey("agent", "msg.switched", { from, to });
        break;
      }
      case "cancelled": {
        const restored = { asking: "asking", ready: "ready" }[ev.restored] ?? "idle";
        setTimeline((t) => [
          ...t.map((e) => (e.status === "running" ? { ...e, status: "cancelled" } : e)),
          { id: nextId(), node: "stop", status: "cancelled", log: { detailKey: "log.stopDetail", source: "system", at: now() } },
        ]);
        setMessages((m) => {
          const last = m.findLastIndex((x) => x.role === "user");
          return m.map((x, i) => (i === last ? { ...x, stopped: true } : x));
        });
        addMessage("agent", ev.message);
        revisingRef.current = restored === "ready";
        setPhase(restored);
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
    const continuing = phase === "asking" || phase === "ready" || phase === "clarify";
    revisingRef.current = phase === "ready";
    if (!continuing) setTimeline([]);
    setCrisis(false);
    addMessage("user", text);
    setPhase("running");
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      if (!continuing || !sessionRef.current) sessionRef.current = await createSession();
      await sendMessage(sessionRef.current, text, onEvent, controller.signal, langRef.current);
    } catch (e) {
      if (e.name === "AbortError") {
        // 서버가 중단 응답을 못 보낸 경우: 연결만 끊고 처음부터 다시 시작하게 한다
        sessionRef.current = null;
        revisingRef.current = false;
        addKey("error", "msg.abortStopped");
        setTimeline((t) => t.map((x) => (x.status === "running" ? { ...x, status: "cancelled" } : x)));
        setPhase("idle");
      } else {
        addKey("error", "msg.serverDown", { error: e.message });
        setTimeline((t) => t.map((x) => (x.status === "running" ? { ...x, status: "error" } : x)));
      }
    } finally {
      abortRef.current = null;
      setStopping(false);
      setPhase((p) => (p === "running" ? (revisingRef.current ? "ready" : "idle") : p));
    }
  };

  const stop = async () => {
    if (stopping) return;
    setStopping(true);
    const controller = abortRef.current;
    try {
      if (sessionRef.current) await cancelRun(sessionRef.current);
    } catch {
      controller?.abort();
    }
    // 서버가 몇 초 안에 '중단됨'을 보내지 않으면 연결을 끊는다
    setTimeout(() => controller?.abort(), 8000);
  };

  const reset = () => {
    sessionRef.current = null;
    revisingRef.current = false;
    setMessages([greeting()]);
    setTimeline([]);
    setCrisis(false);
    setPhase("idle");
  };

  return (
    <I18nContext.Provider value={i18n}>
      <div className="app">
        <header className="topbar">
          <div className="brand">
            <div className="brand-mark" aria-hidden="true">길</div>
            <div>
              <h1>AI민원길잡이</h1>
              <p>{t("app.tagline")}</p>
            </div>
          </div>
          <div className="topbar-actions">
            {health && (
              <span className={`pill ${health.status === "ok" ? "" : "pill-danger"}`} title={t("app.engineTitle")}>
                {health.status === "ok" ? t("app.engine", { model: health.model }) : t("app.down")}
              </span>
            )}
            <select className="lang-select" value={lang} onChange={(e) => setLang(e.target.value)} aria-label={t("app.language")}>
              {LANGS.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.name}
                </option>
              ))}
            </select>
            <button className="btn btn-ghost" onClick={reset} disabled={phase === "running"}>
              {t("app.new")}
            </button>
          </div>
        </header>

        <main className="layout">
          <Chat
            messages={messages}
            phase={phase}
            onSend={send}
            onStop={stop}
            stopping={stopping}
            calm={crisis}
            latestId={messages[messages.length - 1]?.id}
          />
          <AgentLog timeline={timeline} running={phase === "running"} />
        </main>
      </div>
    </I18nContext.Provider>
  );
}
