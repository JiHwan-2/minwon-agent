import { useState } from "react";
import { downloadPdf, followupUrl } from "../api.js";

const EVIDENCE_GROUPS = [
  { level: "required", label: "필수", desc: "지키지 않으면 처리되지 않는 공식 요건이에요.", tone: "danger" },
  { level: "recommended", label: "권장", desc: "있으면 처리에 도움이 돼요. 대부분의 민원은 증빙 없이도 접수할 수 있어요.", tone: "primary" },
  { level: "separate", label: "별도 절차", desc: "민원과 따로 신청할 때 필요해요 (예: 피해 보상).", tone: "warn" },
];

function shortDate(iso, weekday) {
  const [, m, d] = iso.split("-").map(Number);
  return `${m}월 ${d}일(${weekday})`;
}

function FilesSection({ files, sessionId, title, body }) {
  const [state, setState] = useState("idle"); // idle | saving | error
  const [error, setError] = useState("");
  const { pdf, ics } = files;

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
        완성된 결과물 <span className="small muted">Agent가 만든 파일</span>
      </h3>
      <div className="file-row">
        {pdf?.name ? (
          <button className="btn btn-primary btn-sm" onClick={savePdf} disabled={state === "saving"}>
            {state === "saving" ? "PDF 만드는 중…" : `📄 민원 패키지 PDF 받기 (${pdf.pages}쪽)`}
          </button>
        ) : (
          <span className="small warn">PDF를 만들지 못했어요. 아래 복사 버튼을 이용해 주세요.</span>
        )}
        {ics && (
          <a className="btn btn-ghost btn-sm" href={followupUrl(sessionId)} download={ics.name}>
            📅 {shortDate(ics.date, ics.weekday)} 처리 확인 일정 추가
          </a>
        )}
      </div>
      {ics && (
        <p className="small muted">
          처리 기간 '{ics.period}'를 기준으로 {ics.days}일 뒤{ics.shifted ? "(주말이라 다음 월요일)" : ""}에 결과를 확인하도록 일정을 잡았어요. 휴대폰·PC 캘린더에서 열면 추가돼요.
        </p>
      )}
      {pdf?.name && <p className="small muted">PDF에는 위에서 직접 고친 제목·본문이 그대로 들어가요.</p>}
      {state === "error" && <p className="small warn">PDF를 받지 못했어요. ({error})</p>}
    </section>
  );
}

function CasesSection({ cases }) {
  return (
    <section className="pk-section">
      <h3>
        비슷한 민원 사례 <span className="small muted">공공데이터 '{cases.query}' 검색 {cases.total}건 중</span>
      </h3>
      <ul className="cases">
        {cases.items.map((c) => (
          <li key={c.id || c.title}>
            <span>{c.title}</span>
            <small>{[c.agency, c.date].filter(Boolean).join(" · ")}</small>
          </li>
        ))}
      </ul>
      <p className="small muted">출처: {cases.source_name}. 참고용이며 처리 결과는 기관·지역마다 다를 수 있어요.</p>
    </section>
  );
}

export default function PackageCard({ pkg, decision, review, locationConfirmed = true, cases, files, sessionId }) {
  const [title, setTitle] = useState(pkg.title);
  const [body, setBody] = useState(pkg.body);
  const [checked, setChecked] = useState({});
  const [copied, setCopied] = useState(false);

  // '[위치]'처럼 한 줄 전체가 대괄호인 줄은 소제목이라 빈칸으로 세지 않음 (백엔드 export.blanks와 같은 규칙)
  const blanks = body
    .split("\n")
    .filter((line) => !/^\s*\[[^\]]+\]\s*$/.test(line))
    .join("\n")
    .match(/\[[^\]]+\]/g)?.length ?? 0;
  const checkable = pkg.evidence.filter((e) => e.level !== "separate");
  const ready = checkable.filter((e) => checked[e.item]).length;
  const { agency, channel } = decision;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(`${title}\n\n${body}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="package">
      <div className="package-head">
        <span className="pill">민원 패키지 · {pkg.version}번째 초안</span>
        {review.passed ? (
          <span className="pill pill-ok">✓ 검증 통과</span>
        ) : (
          <span className="pill pill-warn">확인 필요 {review.issues.length}건</span>
        )}
      </div>

      {!locationConfirmed && (
        <p className="alert small">⚠ 위치 후보가 여러 곳이어서 1순위 후보로 안내했어요. 제출 전에 위치와 담당 기관이 맞는지 꼭 확인해 주세요.</p>
      )}
      <section className="pk-section">
        <h3>제출할 곳</h3>
        <div className="agency">
          <strong>{agency.agency}</strong>
          <span>{agency.unit}</span>
          <small>
            {agency.duty}
            {agency.phone && ` · ☎ ${agency.phone}`}
          </small>
        </div>
        <p className="small">{decision.reason}</p>
        {decision.others.length > 0 && (
          <p className="small muted">함께 관련된 기관: {decision.others.map((o) => `${o.agency}(${o.unit})`).join(", ")}</p>
        )}
        <div className="row">
          {channel.url ? (
            <a className="btn btn-primary btn-sm" href={channel.url} target="_blank" rel="noopener noreferrer">
              {channel.name}에서 제출하기 ↗
            </a>
          ) : (
            <span className="pill">{channel.name}</span>
          )}
          {channel.phone && <span className="small muted">전화 {channel.phone}</span>}
          <span className="small muted">처리 기간: {decision.period}</span>
        </div>
      </section>

      {cases?.items?.length > 0 && <CasesSection cases={cases} />}

      <section className="pk-section">
        <h3>이렇게 진행하세요</h3>
        <ol className="steps-list">
          {decision.steps.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ol>
        {decision.cautions.length > 0 && (
          <ul className="cautions">
            {decision.cautions.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        )}
      </section>

      <section className="pk-section">
        <h3>민원 초안 <span className="small muted">직접 고칠 수 있어요</span></h3>
        <input className="field" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="민원 제목" />
        <textarea className="field" value={body} onChange={(e) => setBody(e.target.value)} rows={12} aria-label="민원 본문" />
        {blanks > 0 && <p className="small warn">[ ] 표시된 빈칸 {blanks}곳을 채운 뒤 제출해 주세요.</p>}
        {!review.passed && (
          <ul className="cautions">
            {review.issues.map((issue, i) => (
              <li key={i}>{issue}</li>
            ))}
          </ul>
        )}
        <div className="row">
          <button className="btn btn-ghost btn-sm" onClick={copy}>
            {copied ? "복사했어요 ✓" : "제목·본문 복사"}
          </button>
          <span className="small muted">제출은 직접 해 주세요. 이름·연락처는 제출 사이트에서 입력합니다.</span>
        </div>
      </section>

      <section className="pk-section">
        <h3>
          증빙자료 <span className="small muted">준비 {ready}/{checkable.length}</span>
        </h3>
        {EVIDENCE_GROUPS.map((group) => {
          const items = pkg.evidence.filter((e) => e.level === group.level);
          if (items.length === 0) return null;
          return (
            <div key={group.level} className={`ev-group ev-${group.tone}`}>
              <p className="ev-head">
                <em className="ev-tag">{group.label}</em>
                <span className="small muted">{group.desc}</span>
              </p>
              <ul className="checklist">
                {items.map((e) => (
                  <li key={e.item}>
                    {group.level === "separate" ? (
                      <span className="ev-info">
                        {e.item}
                        <small>{e.why}</small>
                      </span>
                    ) : (
                      <label>
                        <input
                          type="checkbox"
                          checked={!!checked[e.item]}
                          onChange={() => setChecked((c) => ({ ...c, [e.item]: !c[e.item] }))}
                        />
                        <span>
                          {e.item}
                          <small>{e.why}</small>
                          {e.basis && <small className="ev-basis">근거: {e.basis}</small>}
                        </span>
                      </label>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
        {pkg.tips.length > 0 && (
          <ul className="tips">
            {pkg.tips.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        )}
      </section>

      {files && sessionId && <FilesSection files={files} sessionId={sessionId} title={title} body={body} />}
    </div>
  );
}
