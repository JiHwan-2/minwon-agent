import { useState } from "react";

export default function PackageCard({ pkg, decision, review }) {
  const [title, setTitle] = useState(pkg.title);
  const [body, setBody] = useState(pkg.body);
  const [checked, setChecked] = useState({});
  const [copied, setCopied] = useState(false);

  const blanks = (body.match(/\[[^\]]+\]/g) || []).length;
  const required = pkg.evidence.filter((e) => e.required);
  const ready = required.filter((e) => checked[e.item]).length;
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
          증빙자료 체크리스트 <span className="small muted">필수 {ready}/{required.length}</span>
        </h3>
        <ul className="checklist">
          {pkg.evidence.map((e) => (
            <li key={e.item}>
              <label>
                <input
                  type="checkbox"
                  checked={!!checked[e.item]}
                  onChange={() => setChecked((c) => ({ ...c, [e.item]: !c[e.item] }))}
                />
                <span>
                  {e.item} {e.required && <em className="req">필수</em>}
                  <small>{e.why}</small>
                </span>
              </label>
            </li>
          ))}
        </ul>
        {pkg.tips.length > 0 && (
          <ul className="tips">
            {pkg.tips.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
