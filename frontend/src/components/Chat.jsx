import { useEffect, useRef, useState } from "react";
import { useI18n } from "../i18n.js";
import PackageCard from "./PackageCard.jsx";

// 번역 키로 저장한 메시지는 지금 화면 언어로 그린다. vars 안의 {key}도 번역한다 (예: 생활불편 유형 이름)
function messageText(m, t) {
  if (!m.key) return m.text;
  const vars = Object.fromEntries(Object.entries(m.vars ?? {}).map(([k, v]) => [k, v && typeof v === "object" ? t(v.key, v.vars) : v]));
  return t(m.key, vars);
}

function Bubble({ m, canChoose, onSend }) {
  const { t } = useI18n();
  return (
    <div className={`bubble bubble-${m.role}${m.pkg ? " bubble-wide" : ""}`}>
      <p>{messageText(m, t)}</p>
      {m.stopped && <p className="bubble-note">{t("chat.stopped")}</p>}
      {m.masked && (
        <p className="bubble-note">
          {t("chat.masked", { items: m.masked.map((f) => t("chat.count", { label: t(`pii.${f.kind}`), count: f.count })).join(", ") })}
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
      {m.referral && (
        <div className="referral">
          <strong>{m.referral.agency}</strong>
          <span className="small muted">{m.referral.operator}</span>
          <div className="row">
            <a className="btn btn-primary btn-sm" href={m.referral.url} target="_blank" rel="noopener noreferrer">
              {t("chat.homepage")}
            </a>
            <span className="small">☎ {m.referral.phone}</span>
            <span className="small muted">{m.referral.hours}</span>
          </div>
        </div>
      )}
      {m.facts && (
        <ul className="facts-mini">
          {m.facts.map((f) => (
            <li key={f.slot}>
              {t(`slot.${f.slot}`)}: {f.value}
            </li>
          ))}
          {m.unknown?.length > 0 && <li className="muted">{t("chat.unknown", { items: m.unknown.map((s) => t(`slot.${s}`)).join(", ") })}</li>}
        </ul>
      )}
      {m.pkg && (
        <>
          <PackageCard
            pkg={m.pkg}
            decision={m.decision}
            review={m.review}
            translation={m.translation}
            locationConfirmed={m.locationConfirmed}
            cases={m.cases}
            files={m.files}
            sessionId={m.sessionId}
          />
          <p className="bubble-note">{t("chat.disclaimer")}</p>
        </>
      )}
    </div>
  );
}

export default function Chat({ messages, phase, onSend, onStop, stopping, latestId, calm }) {
  const { t } = useI18n();
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

  const placeholder = t(
    done ? "chat.ph.ready" : phase === "asking" ? "chat.ph.asking" : phase === "clarify" ? (calm ? "chat.ph.calm" : "chat.ph.clarify") : "chat.ph.idle",
  );

  return (
    <section className="panel chat" aria-label={t("chat.region")}>
      <div className="chat-log" aria-live="polite">
        {messages.map((m) => (
          <Bubble key={m.id} m={m} onSend={onSend} canChoose={phase === "asking" && m.id === latestId} />
        ))}
        {busy && (
          <div className="bubble bubble-agent bubble-busy">
            <span className="spinner" aria-hidden="true" />
            <p>{stopping ? t("chat.stopping") : t("chat.working")}</p>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {((phase === "idle" && messages.length === 1) || (phase === "clarify" && !calm)) && (
        <div className="examples">
          {t("examples").map((ex) => (
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
          aria-label={t("chat.input")}
        />
        {busy ? (
          <button className="btn btn-stop" type="button" onClick={onStop} disabled={stopping} aria-label={t("chat.stopLabel")}>
            {stopping ? t("chat.stoppingBtn") : t("chat.stopBtn")}
          </button>
        ) : (
          <button className="btn btn-primary" type="submit" disabled={!text.trim()}>
            {t("chat.send")}
          </button>
        )}
      </form>
    </section>
  );
}
