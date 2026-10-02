import { ACTION_LABEL, NODE_LABEL, SLOT_LABEL, SOURCE_LABEL, TOOL_SOURCE_LABEL, URGENCY_LABEL } from "../labels.js";

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
      {safety.crisis && <p className="alert">위기 표현 감지 → 자살예방 상담전화 109 안내</p>}
      {safety.injection && <p className="alert">AI 지시 변경 시도 감지 → 자료로만 처리</p>}
    </div>
  );
}

const INTENT_TAG = { referral: "다른 창구 안내", unclear: "불분명한 입력", not_complaint: "민원이 아닌 입력" };

function UnderstandBody({ u }) {
  if (u.intent && u.intent !== "complaint") {
    return (
      <div className="body">
        <div className="row">
          <span className="tag urgency-medium">{INTENT_TAG[u.intent]}</span>
        </div>
        <p className="small">민원 흐름을 시작하지 않고 안내했어요.</p>
        <p className="muted small">안내: {u.reply}</p>
      </div>
    );
  }
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

function ToolCall({ call }) {
  const r = call.result;
  const state = call.status === "running" ? "running" : r.ok ? (r.source === "text_fallback" ? "fallback" : "ok") : "fail";
  const icon = { running: null, ok: "✓", fallback: "↪", fail: "!" }[state];
  return (
    <li className={`tool tool-${state}`}>
      <span className="tool-icon">{icon ?? <span className="spinner" />}</span>
      <div className="tool-main">
        <div className="row">
          <strong>{call.title}</strong>
          {r && <span className={`badge ${state === "ok" ? "" : "badge-warn"}`}>{TOOL_SOURCE_LABEL[r.source] ?? r.source}</span>}
          {r?.retries > 0 && <span className="small warn">재시도 {r.retries}회</span>}
        </div>
        <p className="small muted">입력: {call.input || "-"}</p>
        {r ? <p className="small">→ {r.summary}</p> : <p className="small muted">호출 중…</p>}
        {r?.error && <p className="small warn">{r.error}</p>}
      </div>
    </li>
  );
}

function ActBody({ entry }) {
  const tools = entry.tools ?? (entry.data?.tool_calls ?? []).map((result, i) => ({ id: i, title: result.title, input: result.input, status: "done", result }));
  return (
    <div className="body">
      <ol className="tools">
        {tools.map((call) => (
          <ToolCall key={call.id} call={call} />
        ))}
      </ol>
    </div>
  );
}

function DecideBody({ decision }) {
  return (
    <div className="body">
      <p>
        <strong>{decision.agency.agency}</strong> {decision.agency.unit}
      </p>
      <p className="small">제출 창구: {decision.channel.name}</p>
      <p className="small muted">{decision.reason}</p>
      {decision.fixes?.length > 0 && <p className="small warn">판단 보정: {decision.fixes.join(", ")}</p>}
    </div>
  );
}

function DraftBody({ entry }) {
  const pkg = entry.data.package;
  return (
    <div className="body">
      <p className="strong">{pkg.title}</p>
      <p className="small muted">
        {pkg.version}번째 초안 · 본문 {pkg.body.length}자 · 증빙 {pkg.evidence.length}개
      </p>
      {entry.log?.title?.includes("다시") && <p className="small warn">{entry.log.detail.split(" → ")[0]}</p>}
    </div>
  );
}

function ReviewBody({ review }) {
  return (
    <div className="body">
      <ul className="checks">
        {review.checks.map((c) => (
          <li key={c.name} className={c.ok ? "check-ok" : "check-fail"}>
            <span className="check-icon">{c.ok ? "✓" : "✗"}</span>
            <strong>{c.name}</strong>
            <span className="small muted">{c.detail}</span>
          </li>
        ))}
      </ul>
      {review.passed ? (
        <p className="small ok">→ 검증 통과. 사용자에게 전달합니다.</p>
      ) : review.retry ? (
        <p className="small warn">→ 문제 {review.issues.length}건을 고치도록 다시 작성합니다.</p>
      ) : (
        <p className="small alert">→ 최대 횟수에 도달해 남은 문제를 사용자에게 알립니다.</p>
      )}
    </div>
  );
}

function ConfirmBody({ entry }) {
  if (entry.status === "waiting") {
    return (
      <div className="body">
        <p className="muted">후보 {entry.data?.options?.length ?? 0}곳 중 사용자가 고르기를 기다리는 중</p>
      </div>
    );
  }
  return (
    <div className="body">
      <p className="small">{entry.log?.detail}</p>
      {entry.tools?.length > 0 && <ActBody entry={entry} />}
    </div>
  );
}

function Body({ entry }) {
  const d = entry.data ?? {};
  if (entry.node === "switch" || entry.node === "stop" || entry.node === "off_topic") {
    return (
      <div className="body">
        <p className="small">{entry.log?.detail}</p>
      </div>
    );
  }
  if (entry.node === "ask") return <AskBody entry={entry} />;
  if (entry.node === "confirm_location") return <ConfirmBody entry={entry} />;
  if (entry.node === "act" || entry.node === "locate" || entry.node === "deliver") return <ActBody entry={entry} />;
  if (entry.status !== "done") return null;
  if (entry.node === "decide") return <DecideBody decision={d.decision} />;
  if (entry.node === "draft") return <DraftBody entry={entry} />;
  if (entry.node === "review") return <ReviewBody review={d.review} />;
  if (entry.status !== "done") return null;
  if (entry.node === "guard") return <GuardBody safety={d.safety} />;
  if (entry.node === "understand") return <UnderstandBody u={d.understanding} />;
  if (entry.node === "plan") return <PlanBody plan={d.plan} />;
  if (entry.node === "check") return <CheckBody info={d.info} />;
  return null;
}

const STATUS_TEXT = { running: "실행 중", waiting: "대기", done: "완료", error: "오류", cancelled: "중단" };

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
            <li>Tool 실행: 위치 확인 · 관할 기관 검색 · 담당 부서 조회 · 비슷한 민원 사례 조회(공공데이터)</li>
            <li>담당 기관 판단</li>
            <li>민원 초안 작성 ⇄ 초안 검증 (문제가 있으면 다시 작성)</li>
            <li>결과물 만들기: 민원 패키지 PDF</li>
          </ol>
        </div>
      ) : (
        <ol className="timeline">
          {timeline.map((entry, i) => (
            <li key={entry.id} className={`entry entry-${entry.status}`}>
              <div className="entry-marker">{entry.status === "running" ? <span className="spinner" /> : i + 1}</div>
              <div className="entry-card">
                <div className="entry-head">
                  <strong>{(entry.node === "draft" || entry.node === "understand") && entry.log ? entry.log.title : (NODE_LABEL[entry.node] ?? entry.node)}</strong>
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
