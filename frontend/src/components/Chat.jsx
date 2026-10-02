import { useEffect, useRef, useState } from "react";
import { EXAMPLES } from "../labels.js";
import PackageCard from "./PackageCard.jsx";

function Bubble({ m, canChoose, onSend }) {
  return (
    <div className={`bubble bubble-${m.role}${m.pkg ? " bubble-wide" : ""}`}>
      <p>{m.text}</p>
      {m.masked && (
        <p className="bubble-note">
          🔒 {m.masked.map((f) => `${f.label} ${f.count}건`).join(", ")}을 가린 뒤 처리했어요.
        </p>
      )}
      {m.plan && (
        <ol className="plan-mini">
          {m.plan.steps.map((s, i) => (
            <li key={i}>{s.title}</li>
          ))}
        </ol>
      )}
      {m.questions && (
        <ol className="questions">
          {m.questions.map((q) => (
            <li key={q.slot}>{q.text}</li>
          ))}
        </ol>
      )}
      {m.options?.length > 0 && (
        <div className="options">
          {m.options.map((o) => (
            <button key={o.value} className="option-btn" disabled={!canChoose} onClick={() => onSend(o.value)}>
              <span className="option-no">{o.value}</span>
              {o.label}
            </button>
          ))}
        </div>
      )}
      {m.facts && (
        <ul className="facts-mini">
          {m.facts.map((f) => (
            <li key={f}>{f}</li>
          ))}
          {m.unknown?.length > 0 && <li className="muted">확인 못 한 정보: {m.unknown.join(", ")}</li>}
        </ul>
      )}
      {m.pkg && (
        <>
          <PackageCard
            pkg={m.pkg}
            decision={m.decision}
            review={m.review}
            locationConfirmed={m.locationConfirmed}
            cases={m.cases}
            files={m.files}
            sessionId={m.sessionId}
          />
          <p className="bubble-note">안내 정보는 참고용이에요. 부서 이름은 지자체마다 조금 다를 수 있어요.</p>
        </>
      )}
    </div>
  );
}

export default function Chat({ messages, phase, onSend, latestId }) {
  const [text, setText] = useState("");
  const endRef = useRef(null);
  const busy = phase === "running";
  const done = phase === "ready";

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, busy]);

  const submit = (e) => {
    e?.preventDefault();
    const value = text.trim();
    if (!value || busy) return;
    setText("");
    onSend(value);
  };

  const placeholder = done
    ? "고칠 점을 말해 주세요. 예) 더 짧게 / 요청사항에 CCTV 설치도 넣어 줘 (다른 불편은 '새 민원')"
    : phase === "asking"
      ? "질문에 이어서 답해 주세요. 모르는 건 '모름'이라고 적어도 돼요."
      : "예) 학교 앞 횡단보도가 너무 위험해요.";

  return (
    <section className="panel chat" aria-label="대화">
      <div className="chat-log" aria-live="polite">
        {messages.map((m) => (
          <Bubble key={m.id} m={m} onSend={onSend} canChoose={phase === "asking" && m.id === latestId} />
        ))}
        {busy && (
          <div className="bubble bubble-agent bubble-busy">
            <span className="spinner" aria-hidden="true" />
            <p>Agent가 작업하고 있어요…</p>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {phase === "idle" && messages.length === 1 && (
        <div className="examples">
          {EXAMPLES.map((ex) => (
            <button key={ex} className="chip-btn" onClick={() => onSend(ex)}>
              {ex}
            </button>
          ))}
        </div>
      )}

      <form className="composer" onSubmit={submit}>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) submit(e);
          }}
          placeholder={placeholder}
          rows={2}
          maxLength={2000}
          disabled={busy}
          aria-label="메시지 입력"
        />
        <button className="btn btn-primary" type="submit" disabled={busy || !text.trim()}>
          {done ? "수정 요청" : "보내기"}
        </button>
      </form>
    </section>
  );
}
