import { useEffect, useRef, useState } from "react";
import { EXAMPLES } from "../labels.js";

function Bubble({ m }) {
  return (
    <div className={`bubble bubble-${m.role}`}>
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
      {m.facts && (
        <ul className="facts-mini">
          {m.facts.map((f) => (
            <li key={f}>{f}</li>
          ))}
          {m.unknown?.length > 0 && <li className="muted">확인 못 한 정보: {m.unknown.join(", ")}</li>}
        </ul>
      )}
      {m.agencies && (
        <div className="agencies">
          {m.agencies.departments.map((d) => (
            <div key={d.agency + d.unit} className="agency">
              <strong>{d.agency}</strong>
              <span>{d.unit}</span>
              <small>
                {d.duty}
                {d.phone && ` · ☎ ${d.phone}`}
              </small>
            </div>
          ))}
          <p className="small">
            제출 창구: {m.agencies.channels.map((c) => c.name + (c.phone ? `(${c.phone})` : "")).join(", ")}
          </p>
        </div>
      )}
      {m.nextStep && <p className="bubble-note">민원 초안 작성과 검증 단계는 개발 중이에요. 부서명은 지자체마다 조금 다를 수 있어요.</p>}
    </div>
  );
}

export default function Chat({ messages, phase, onSend }) {
  const [text, setText] = useState("");
  const endRef = useRef(null);
  const busy = phase === "running";
  const done = phase === "ready";

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  const submit = (e) => {
    e?.preventDefault();
    const value = text.trim();
    if (!value || busy || done) return;
    setText("");
    onSend(value);
  };

  const placeholder = done
    ? "'새 민원'을 눌러 다른 불편을 입력할 수 있어요."
    : phase === "asking"
      ? "질문에 이어서 답해 주세요. 모르는 건 '모름'이라고 적어도 돼요."
      : "예) 학교 앞 횡단보도가 너무 위험해요.";

  return (
    <section className="panel chat" aria-label="대화">
      <div className="chat-log" aria-live="polite">
        {messages.map((m) => (
          <Bubble key={m.id} m={m} />
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
          disabled={busy || done}
          aria-label="메시지 입력"
        />
        <button className="btn btn-primary" type="submit" disabled={busy || done || !text.trim()}>
          보내기
        </button>
      </form>
    </section>
  );
}
