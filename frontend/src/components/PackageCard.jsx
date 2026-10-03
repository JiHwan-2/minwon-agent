import { useState } from "react";
import { downloadPdf } from "../api.js";
import { languageName, useI18n } from "../i18n.js";

const EVIDENCE_GROUPS = [
  { level: "required", tone: "danger" },
  { level: "recommended", tone: "primary" },
  { level: "separate", tone: "warn" },
];

function FilesSection({ files, sessionId, title, body, korean }) {
  const { t } = useI18n();
  const [state, setState] = useState("idle"); // idle | saving | error
  const [error, setError] = useState("");
  const { pdf } = files;

  const savePdf = async () => {
    setState("saving");
    try {
      await downloadPdf(sessionId, { title, body }, pdf.name);
      setState("idle");
    } catch (e) {
      setError(e.message);
      setState("error");
    }
  };

  return (
    <section className="pk-section files">
      <h3>
        {t("pkg.files")} <span className="small muted">{t("pkg.filesSub")}</span>
      </h3>
      <div className="file-row">
        {pdf?.name ? (
          <button className="btn btn-primary btn-sm" onClick={savePdf} disabled={state === "saving"}>
            {state === "saving" ? t("pkg.pdfMaking") : t("pkg.pdfGet", { pages: pdf.pages })}
          </button>
        ) : (
          <span className="small warn">{t("pkg.pdfFail")}</span>
        )}
      </div>
      {pdf?.name && <p className="small muted">{t("pkg.pdfNote")}</p>}
      {pdf?.name && korean && <p className="small muted">{t("pkg.pdfKorean")}</p>}
      {state === "error" && <p className="small warn">{t("pkg.pdfError", { error })}</p>}
    </section>
  );
}

function CasesSection({ cases }) {
  const { t, lang } = useI18n();
  return (
    <section className="pk-section">
      <h3>
        {t("pkg.cases")} <span className="small muted">{t("pkg.casesMeta", { query: cases.query, total: cases.total })}</span>
      </h3>
      {lang !== "ko" && <p className="small muted">{t("pkg.casesKorean")}</p>}
      <ul className="cases">
        {cases.items.map((c) => (
          <li key={c.id || c.title}>
            <span>{c.title}</span>
            <small>{[c.agency, c.date].filter(Boolean).join(" · ")}</small>
          </li>
        ))}
      </ul>
      <p className="small muted">{t("pkg.casesSource", { source: cases.source_name })}</p>
    </section>
  );
}

export default function PackageCard({ pkg, decision, review, translation, locationConfirmed = true, cases, files, sessionId }) {
  const { t, lang } = useI18n();
  const [title, setTitle] = useState(pkg.title);
  const [body, setBody] = useState(pkg.body);
  const [checked, setChecked] = useState({});
  const [copied, setCopied] = useState(false);
  // 시민이 외국인이면 번역본을 먼저 보여 주고, 버튼으로 제출용 한국어 원문(검증을 거친 글)으로 바꾼다
  const hasTranslation = Boolean(translation && translation.language !== "ko");
  const [showTranslation, setShowTranslation] = useState(hasTranslation);
  const tr = hasTranslation && showTranslation ? translation : null;
  const trName = hasTranslation ? languageName(translation.language, lang) : "";
  const { agency, channel } = decision;

  const view = {
    reason: tr?.reason ?? decision.reason,
    steps: tr?.steps ?? decision.steps,
    cautions: tr?.cautions ?? decision.cautions,
    issues: tr?.issues ?? review.issues,
    unit: tr?.unit ?? agency.unit,
    duty: tr?.duty ?? agency.duty,
    period: tr?.period ?? decision.period,
    tips: tr?.tips ?? pkg.tips,
    evidence: pkg.evidence.map((e, i) => (tr?.evidence[i] ? { ...e, ...tr.evidence[i] } : e)),
  };

  // '[위치]'처럼 한 줄 전체가 대괄호인 줄은 소제목이라 빈칸으로 세지 않음 (백엔드 export.blanks와 같은 규칙)
  const blanks = body
    .split("\n")
    .filter((line) => !/^\s*\[[^\]]+\]\s*$/.test(line))
    .join("\n")
    .match(/\[[^\]]+\]/g)?.length ?? 0;
  const checkable = view.evidence.map((e, i) => ({ ...e, index: i })).filter((e) => e.level !== "separate");
  const ready = checkable.filter((e) => checked[e.index]).length;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(`${title}\n\n${body}`); // 제출하는 글이므로 언제나 한국어 원문
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="package">
      <div className="package-head">
        <span className="pill">{t("pkg.head", { version: pkg.version })}</span>
        {review.passed ? (
          <span className="pill pill-ok">{t("pkg.passed")}</span>
        ) : (
          <span className="pill pill-warn">{t("pkg.needsCheck", { count: review.issues.length })}</span>
        )}
      </div>

      {!locationConfirmed && <p className="alert small">{t("pkg.locationWarn")}</p>}
      <section className="pk-section">
        <h3>{t("pkg.where")}</h3>
        <div className="agency">
          <strong>{agency.agency}</strong>
          <span>{view.unit}</span>
          <small>
            {view.duty}
            {agency.phone && ` · ☎ ${agency.phone}`}
          </small>
        </div>
        <p className="small">{view.reason}</p>
        {decision.others.length > 0 && (
          <p className="small muted">{t("pkg.related", { items: decision.others.map((o) => `${o.agency}(${o.unit})`).join(", ") })}</p>
        )}
        <div className="row">
          {channel.url ? (
            <a className="btn btn-primary btn-sm" href={channel.url} target="_blank" rel="noopener noreferrer">
              {t("pkg.submitAt", { name: channel.name })}
            </a>
          ) : (
            <span className="pill">{channel.name}</span>
          )}
          {channel.phone && <span className="small muted">{t("pkg.phone", { phone: channel.phone })}</span>}
          <span className="small muted">{t("pkg.period", { period: view.period })}</span>
        </div>
      </section>

      {cases?.items?.length > 0 && <CasesSection cases={cases} />}

      <section className="pk-section">
        <h3>{t("pkg.steps")}</h3>
        <ol className="steps-list">
          {view.steps.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ol>
        {view.cautions.length > 0 && (
          <ul className="cautions">
            {view.cautions.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        )}
      </section>

      <section className="pk-section">
        <h3>
          {t("pkg.draft")}{" "}
          <span className="small muted">{tr ? t("pkg.translatedTag", { language: trName }) : t("pkg.editable")}</span>
        </h3>
        {tr ? (
          <>
            <p className="draft-title">{tr.title}</p>
            <div className="draft-text">{tr.body}</div>
            <p className="small muted">{translation.translated ? t("pkg.translationNote") : t("pkg.notTranslated")}</p>
          </>
        ) : (
          <>
            {hasTranslation && <p className="small muted">{t("pkg.koreanNote")}</p>}
            <input className="field" value={title} onChange={(e) => setTitle(e.target.value)} aria-label={t("pkg.titleLabel")} />
            <textarea className="field" value={body} onChange={(e) => setBody(e.target.value)} rows={12} aria-label={t("pkg.bodyLabel")} />
          </>
        )}
        {blanks > 0 && <p className="small warn">{t("pkg.blanks", { count: blanks })}</p>}
        {!review.passed && (
          <ul className="cautions">
            {view.issues.map((issue, i) => (
              <li key={i}>{issue}</li>
            ))}
          </ul>
        )}
        <div className="row">
          {hasTranslation && (
            <button className="btn btn-primary btn-sm" onClick={() => setShowTranslation((v) => !v)}>
              {showTranslation ? t("pkg.showKorean") : t("pkg.showTranslation", { language: trName })}
            </button>
          )}
          <button className="btn btn-ghost btn-sm" onClick={copy}>
            {copied ? t("pkg.copied") : hasTranslation ? t("pkg.copyKorean") : t("pkg.copy")}
          </button>
          <span className="small muted">{t("pkg.submitSelf")}</span>
        </div>
      </section>

      <section className="pk-section">
        <h3>
          {t("pkg.evidence")} <span className="small muted">{t("pkg.evidenceReady", { ready, total: checkable.length })}</span>
        </h3>
        {EVIDENCE_GROUPS.map((group) => {
          const items = view.evidence.map((e, i) => ({ ...e, index: i })).filter((e) => e.level === group.level);
          if (items.length === 0) return null;
          return (
            <div key={group.level} className={`ev-group ev-${group.tone}`}>
              <p className="ev-head">
                <em className="ev-tag">{t(`ev.${group.level}`)}</em>
                <span className="small muted">{t(`ev.${group.level}Desc`)}</span>
              </p>
              <ul className="checklist">
                {items.map((e) => (
                  <li key={e.index}>
                    {group.level === "separate" ? (
                      <span className="ev-info">
                        {e.item}
                        <small>{e.why}</small>
                      </span>
                    ) : (
                      <label>
                        <input
                          type="checkbox"
                          checked={!!checked[e.index]}
                          onChange={() => setChecked((c) => ({ ...c, [e.index]: !c[e.index] }))}
                        />
                        <span>
                          {e.item}
                          <small>{e.why}</small>
                          {e.basis && <small className="ev-basis">{t("pkg.basis", { basis: e.basis })}</small>}
                        </span>
                      </label>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
        {view.tips.length > 0 && (
          <ul className="tips">
            {view.tips.map((tip, i) => (
              <li key={i}>{tip}</li>
            ))}
          </ul>
        )}
      </section>

      {files && sessionId && <FilesSection files={files} sessionId={sessionId} title={title} body={body} korean={lang !== "ko"} />}
    </div>
  );
}
