import { useEffect, useRef, useState } from "react";
import { useI18n } from "../i18n.js";
import PackageCard from "./PackageCard.jsx";

// 번역 키로 저장한 메시지는 지금 화면 언어로 그린다. vars 안의 {key}도 번역한다 (예: 생활불편 유형 이름)
function messageText(m, t) {
  if (!m.key) return m.text;
  const vars = Object.fromEntries(Object.entries(m.vars ?? {}).map(([k, v]) => [k, v && typeof v === "object" ? t(v.key, v.vars) : v]));
  return t(m.key, vars);
}

const PHOTO_TYPES = ["image/jpeg", "image/png", "image/webp"];
const PHOTO_MAX = 15 * 1024 * 1024; // 서버와 같은 한도

function Bubble({ m, canChoose, onSend }) {
  const { t } = useI18n();
  const text = messageText(m, t);
  const photoQuestion = m.optionKind === "photo";
  return (
    <div className={`bubble bubble-${m.role}${m.pkg ? " bubble-wide" : ""}${m.photoUrl && !text ? " bubble-photo-only" : ""}`}>
      {m.photoUrl && <img className="bubble-photo" src={m.photoUrl} alt={t("chat.photoAlt")} />}
      {text && <p>{text}</p>}
      {photoQuestion && m.questions?.map((q) => (
        <p key={q.slot} className="photo-question">
          {q.text}
        </p>
      ))}
      {photoQuestion && m.options?.length > 0 && (
        <div className="row yes-no">
          {m.options.map((o) => (
            <button key={o.value} className="btn btn-ghost btn-sm" disabled={!canChoose} onClick={() => onSend(o.value)}>
              {o.label}
            </button>
          ))}
        </div>
      )}
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
      {m.questions && !photoQuestion && (
        <ol className="questions">
          {m.questions.map((q) => (
            <li key={q.slot}>{q.text}</li>
          ))}
        </ol>
      )}
      {m.options?.length > 0 && !photoQuestion && (
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

export default function Chat({ messages, phase, onSend, onStop, stopping, latestId, calm, canAttach }) {
  const { t } = useI18n();
  const [text, setText] = useState("");
  const [file, setFile] = useState(null); // 첨부한 현장 사진 (새 민원을 시작할 때만)
  const [preview, setPreview] = useState("");
  const [photoError, setPhotoError] = useState("");
  const endRef = useRef(null);
  const fileRef = useRef(null);
  const busy = phase === "running";
  const done = phase === "ready";
  const photo = canAttach ? file : null;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, busy]);

  useEffect(() => {
    if (!file) return undefined;
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const pick = (e) => {
    const chosen = e.target.files?.[0];
    e.target.value = ""; // 같은 사진을 다시 골라도 바뀐 것으로 받도록
    if (!chosen) return;
    if (!PHOTO_TYPES.includes(chosen.type)) return setPhotoError(t("chat.photoType"));
    if (chosen.size > PHOTO_MAX) return setPhotoError(t("chat.photoTooBig"));
    setPhotoError("");
    setFile(chosen);
  };

  const removePhoto = () => {
    setFile(null);
    setPreview("");
    setPhotoError("");
  };

  const submit = (e) => {
    e?.preventDefault();
    const value = text.trim();
    if ((!value && !photo) || busy) return;
    setText("");
    removePhoto();
    onSend(value, photo);
  };

  const placeholder = t(
    photo
      ? "chat.ph.photo"
      : done
        ? "chat.ph.ready"
        : phase === "asking"
          ? "chat.ph.asking"
          : phase === "clarify"
            ? calm
              ? "chat.ph.calm"
              : "chat.ph.clarify"
            : "chat.ph.idle",
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

      {photo && preview && (
        <div className="attached">
          <img src={preview} alt={t("chat.photoAlt")} />
          <span className="small muted attached-name">{photo.name}</span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={removePhoto} disabled={busy}>
            {t("chat.removePhoto")}
          </button>
        </div>
      )}
      {photoError && <p className="small warn attach-error">{photoError}</p>}

      <form className="composer" onSubmit={submit}>
        {canAttach && (
          <>
            <input ref={fileRef} type="file" accept={PHOTO_TYPES.join(",")} onChange={pick} hidden />
            <button
              type="button"
              className="btn btn-ghost btn-attach"
              onClick={() => fileRef.current?.click()}
              disabled={busy}
              title={t("chat.attachHint")}
              aria-label={t("chat.attach")}
            >
              <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
                <path
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinejoin="round"
                  d="M4 8h3l1.5-2h7L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"
                />
                <circle cx="12" cy="13" r="3.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
              </svg>
            </button>
          </>
        )}
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
          <button className="btn btn-primary" type="submit" disabled={!text.trim() && !photo}>
            {t("chat.send")}
          </button>
        )}
      </form>
    </section>
  );
}
