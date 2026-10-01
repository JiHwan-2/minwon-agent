import { ACTION_LABEL, NODE_LABEL, SLOT_LABEL, SOURCE_LABEL, URGENCY_LABEL } from "../labels.js";

function SourceBadge({ log }) {
  if (!log) return null;
  const cls = log.source === "rule_fallback" ? "badge badge-warn" : "badge";
  return (
    <span className={cls} title={log.error || undefined}>
      {SOURCE_LABEL[log.source] ?? log.source}
    </span>
  );
}

function GuardBody({ safety }) {
  return (
    <div className="body">
      {safety.pii.length > 0 ? (
        <p>🔒 {safety.pii.map((f) => `${f.label} ${f.count}건`).join(", ")} 가림 (원문은 저장하지 않음)</p>
      ) : (
        <p className="muted">개인정보 없음</p>
      )}
      {safety.emergency && <p className="alert">긴급상황 표현 감지 → 112·119 신고 안내</p>}
      {safety.injection && <p className="alert">AI 지시 변경 시도 감지 → 자료로만 처리</p>}
    </div>
  );
}

function UnderstandBody({ u }) {
  return (
    <div className="body">
      <div className="row">
        <span className="tag">{u.category_label}</span>
        <span className={`tag urgency-${u.urgency}`}>긴급도 {URGENCY_LABEL[u.urgency]}</span>
      </div>
      <p className="strong">{u.title}</p>
      <p>{u.summary}</p>
      <p className="muted small">핵심어: {u.keywords.join(", ")}</p>
    </div>
  );
}

function PlanBody({ plan }) {
  return (
    <div className="body">
      <p className="strong">🎯 {plan.goal}</p>
      <ol className="plan-steps">
        {plan.steps.map((s, i) => (
          <li key={i}>
            <span className="chip">{ACTION_LABEL[s.action] ?? s.action}</span>
            <div>
              <strong>{s.title}</strong>
              <p className="muted small">{s.reason}</p>
            </div>
          </li>
        ))}
      </ol>
      <p className="small">
        필수 정보: {plan.required_info.map((s) => SLOT_LABEL[s] ?? s).join(", ")}
      </p>
      {plan.fixes?.length > 0 && <p className="small warn">계획 보정: {plan.fixes.join(", ")}</p>}
    </div>
  );
}

function CheckBody({ info }) {
  return (
    <div className="body">
      {info.facts.length > 0 && (
        <dl className="facts">
          {info.facts.map((f) => (
            <div key={f.slot}>
              <dt>{SLOT_LABEL[f.slot] ?? f.slot}</dt>
              <dd>{f.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {info.questions.length > 0 ? (
        <p className="small">→ 부족한 정보 {info.questions.length}개를 질문합니다.</p>
      ) : (
        <p className="small ok">→ 다음 단계로 진행합니다.{info.location_query && ` (위치 검색어: ${info.location_query})`}</p>
      )}
    </div>
  );
}

function AskBody({ entry }) {
  if (entry.status === "waiting") {
    return (
      <div className="body">
        <p className="muted">사용자 답변을 기다리는 중 (대화 상태 저장됨)</p>
      </div>
    );
  }
  return (
    <div className="body">
      <p className="muted small">{entry.log?.detail}</p>
    </div>
  );
}

function Body({ entry }) {
  const d = entry.data ?? {};
  if (entry.node === "ask") return <AskBody entry={entry} />;
  if (entry.status !== "done") return null;
  if (entry.node === "guard") return <GuardBody safety={d.safety} />;
  if (entry.node === "understand") return <UnderstandBody u={d.understanding} />;
  if (entry.node === "plan") return <PlanBody plan={d.plan} />;
  if (entry.node === "check") return <CheckBody info={d.info} />;
  return null;
}

const STATUS_TEXT = { running: "실행 중", waiting: "대기", done: "완료", error: "오류" };

export default function AgentLog({ timeline, running }) {
  return (
    <section className="panel log" aria-label="Agent 작업 기록">
      <header className="log-head">
        <h2>Agent 작업 기록</h2>
        <span className="muted small">각 단계의 판단과 근거가 순서대로 남아요</span>
      </header>
      {timeline.length === 0 ? (
        <div className="empty">
          <p>민원을 입력하면 Agent가 일하는 과정이 여기에 표시돼요.</p>
          <ol className="flow">
            <li>입력 안전 점검</li>
            <li>문제 분석</li>
            <li>처리 계획</li>
            <li>정보 판단 · 추가 질문</li>
            <li className="muted">위치·기관 검색 (개발 중)</li>
            <li className="muted">민원 작성 · 검증 (개발 중)</li>
          </ol>
        </div>
      ) : (
        <ol className="timeline">
          {timeline.map((entry, i) => (
            <li key={entry.id} className={`entry entry-${entry.status}`}>
              <div className="entry-marker">{entry.status === "running" ? <span className="spinner" /> : i + 1}</div>
              <div className="entry-card">
                <div className="entry-head">
                  <strong>{NODE_LABEL[entry.node] ?? entry.node}</strong>
                  <div className="row">
                    <SourceBadge log={entry.log} />
                    <span className={`status status-${entry.status}`}>{STATUS_TEXT[entry.status]}</span>
                    {entry.log?.at && <span className="muted small">{entry.log.at}</span>}
                  </div>
                </div>
                <Body entry={entry} />
              </div>
            </li>
          ))}
          {running && timeline.every((e) => e.status !== "running") && (
            <li className="entry entry-running">
              <div className="entry-marker">
                <span className="spinner" />
              </div>
              <div className="entry-card muted">다음 단계 준비 중…</div>
            </li>
          )}
        </ol>
      )}
    </section>
  );
}
