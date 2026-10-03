import { languageName, useI18n } from "../i18n.js";

// 화면 글자(제목·표시·안내)는 화면 언어로, AI가 쓴 판단 내용과 Tool 결과 요약은 받은 그대로 보여 준다

function SourceBadge({ log }) {
  const { t } = useI18n();
  if (!log) return null;
  const cls = log.source === "rule_fallback" ? "badge badge-warn" : "badge";
  return (
    <span className={cls} title={log.error || undefined}>
      {t(`source.${log.source}`)}
    </span>
  );
}

function GuardBody({ safety }) {
  const { t } = useI18n();
  return (
    <div className="body">
      {safety.pii.length > 0 ? (
        <p>{t("log.pii", { items: safety.pii.map((f) => t("chat.count", { label: t(`pii.${f.kind}`), count: f.count })).join(", ") })}</p>
      ) : (
        <p className="muted">{t("log.noPii")}</p>
      )}
      {safety.emergency && <p className="alert">{t("log.emergency")}</p>}
      {safety.crisis && <p className="alert">{t("log.crisis")}</p>}
      {safety.injection && <p className="alert">{t("log.injection")}</p>}
    </div>
  );
}

function UnderstandBody({ u, chatted }) {
  const { t } = useI18n();
  if (u.intent === "service") {
    return (
      <div className="body">
        <div className="row">
          <span className="tag">{t("intent.service")}</span>
          <span className="tag">{t(`group.${u.service_group}`)}</span>
        </div>
        <p className="strong">{t(`service.${u.service}`)}</p>
        <p>{u.summary}</p>
      </div>
    );
  }
  if (u.intent && u.intent !== "complaint") {
    return (
      <div className="body">
        <div className="row">
          <span className="tag urgency-medium">{t(`intent.${u.intent}`)}</span>
        </div>
        <p className="small">{t("log.notStarted")}</p>
        {/* 다음 '대화' 단계가 실제로 보낸 답을 보여 주므로, 여기서는 대화로 넘기지 않은 경우(다른 창구·위기)만 안내를 보인다 */}
        {!chatted && <p className="muted small">{t("log.reply", { reply: u.reply })}</p>}
      </div>
    );
  }
  return (
    <div className="body">
      <div className="row">
        <span className="tag">{t(`category.${u.category}`)}</span>
        <span className={`tag urgency-${u.urgency}`}>{t("log.urgency", { level: t(`urgency.${u.urgency}`) })}</span>
      </div>
      <p className="strong">{u.title}</p>
      <p>{u.summary}</p>
      <p className="muted small">{t("log.keywords", { items: u.keywords.join(", ") })}</p>
    </div>
  );
}

function PlanBody({ plan }) {
  const { t } = useI18n();
  return (
    <div className="body">
      <p className="strong">🎯 {plan.goal}</p>
      <ol className="plan-steps">
        {plan.steps.map((s, i) => (
          <li key={i}>
            <span className="chip">{t(`action.${s.action}`)}</span>
            <div>
              <strong>{s.title}</strong>
              <p className="muted small">{s.reason}</p>
            </div>
          </li>
        ))}
      </ol>
      <p className="small">{t("log.required", { items: plan.required_info.map((s) => t(`slot.${s}`)).join(", ") })}</p>
      {plan.fixes?.length > 0 && <p className="small warn">{t("log.planFixes", { items: plan.fixes.join(", ") })}</p>}
    </div>
  );
}

function CheckBody({ info }) {
  const { t } = useI18n();
  return (
    <div className="body">
      {info.facts.length > 0 && (
        <dl className="facts">
          {info.facts.map((f) => (
            <div key={f.slot}>
              <dt>{t(`slot.${f.slot}`)}</dt>
              <dd>{f.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {info.questions.length > 0 ? (
        <p className="small">{t("log.askCount", { count: info.questions.length })}</p>
      ) : (
        <p className="small ok">
          {t("log.proceed")}
          {info.location_query && t("log.query", { query: info.location_query })}
        </p>
      )}
    </div>
  );
}

function AskBody({ entry }) {
  const { t } = useI18n();
  if (entry.status === "waiting") {
    return (
      <div className="body">
        <p className="muted">{t("log.waiting")}</p>
      </div>
    );
  }
  return (
    <div className="body">
      <p className="muted small">{entry.log?.detail}</p>
    </div>
  );
}

function toolTitle(tool, t) {
  const [name, kind] = tool.split(":");
  if (name === "find_nearby") return t("tool.find_nearby", { kind: t(`nearby.${kind}`) });
  if (name === "find_offices") return t("tool.find_offices", { kind: t(`office.${kind}`) });
  return t(`tool.${name}`);
}

function ToolCall({ call }) {
  const { t } = useI18n();
  const r = call.result;
  const state = call.status === "running" ? "running" : r.ok ? (r.source === "text_fallback" ? "fallback" : "ok") : "fail";
  const icon = { running: null, ok: "✓", fallback: "↪", fail: "!" }[state];
  return (
    <li className={`tool tool-${state}`}>
      <span className="tool-icon">{icon ?? <span className="spinner" />}</span>
      <div className="tool-main">
        <div className="row">
          <strong>{call.tool ? toolTitle(call.tool, t) : call.title}</strong>
          {r && <span className={`badge ${state === "ok" ? "" : "badge-warn"}`}>{t(`toolsrc.${r.source}`)}</span>}
          {r?.retries > 0 && <span className="small warn">{t("log.retries", { count: r.retries })}</span>}
        </div>
        <p className="small muted">{t("log.input", { input: call.input || "-" })}</p>
        {r ? <p className="small">→ {r.summary}</p> : <p className="small muted">{t("log.calling")}</p>}
        {r?.error && <p className="small warn">{r.error}</p>}
      </div>
    </li>
  );
}

function ActBody({ entry }) {
  const tools =
    entry.tools ?? (entry.data?.tool_calls ?? []).map((result, i) => ({ id: i, tool: result.tool, title: result.title, input: result.input, status: "done", result }));
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
  const { t } = useI18n();
  return (
    <div className="body">
      <p>
        <strong>{decision.agency.agency}</strong> {decision.agency.unit}
      </p>
      <p className="small">{t("log.channel", { name: decision.channel.name })}</p>
      <p className="small muted">{decision.reason}</p>
      {decision.fixes?.length > 0 && <p className="small warn">{t("log.decideFixes", { items: decision.fixes.join(", ") })}</p>}
    </div>
  );
}

function DraftBody({ entry }) {
  const { t } = useI18n();
  const pkg = entry.data.package;
  return (
    <div className="body">
      <p className="strong">{pkg.title}</p>
      <p className="small muted">{t("log.draftMeta", { version: pkg.version, chars: pkg.body.length, count: pkg.evidence.length })}</p>
      {entry.log?.title?.includes("다시") && <p className="small warn">{entry.log.detail.split(" → ")[0]}</p>}
    </div>
  );
}

function ReviewBody({ review }) {
  const { t } = useI18n();
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
        <p className="small ok">{t("log.reviewPassed")}</p>
      ) : review.retry ? (
        <p className="small warn">{t("log.reviewRetry", { count: review.issues.length })}</p>
      ) : (
        <p className="small alert">{t("log.reviewMax")}</p>
      )}
    </div>
  );
}

function TranslateBody({ translation }) {
  const { t, lang } = useI18n();
  return (
    <div className="body">
      <p className="small">
        {translation.translated ? t("log.translated", { language: languageName(translation.language, lang) }) : t("log.translateFailed")}
      </p>
      <p className="muted small">{translation.title}</p>
    </div>
  );
}

function ConfirmBody({ entry }) {
  const { t } = useI18n();
  if (entry.status === "waiting") {
    return (
      <div className="body">
        <p className="muted">{t("log.confirmWaiting", { count: entry.data?.options?.length ?? 0 })}</p>
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

// 민원 서비스 안내 정리: Claude가 쓴 바로 답과 지금 추천
function GuideLogBody({ guide }) {
  const { t } = useI18n();
  return (
    <div className="body">
      <p className="strong">{t(`service.${guide.code}`)}</p>
      <p className="small">{guide.summary}</p>
      {guide.recommendation && <p className="small muted">→ {guide.recommendation}</p>}
      {guide.guarded && <p className="small warn">{t("guide.guarded")}</p>}
    </div>
  );
}

// 사진 분석: Tool(사진 정보 읽기·좌표→주소)과 Claude가 사진에서 찾은 장면·불편
function LookBody({ entry }) {
  const { t } = useI18n();
  const a = entry.data?.photo?.analysis;
  return (
    <div className="body">
      <ActBody entry={entry} />
      {entry.status === "done" && a && (
        <>
          {a.scene && <p className="small">{t("log.photoScene", { scene: a.scene })}</p>}
          {a.relevant && a.issue ? <p className="strong">{t("log.photoIssue", { issue: a.issue })}</p> : <p className="small muted">{t("log.photoNone")}</p>}
          {a.location_clues && <p className="small muted">{t("log.photoClues", { clues: a.location_clues })}</p>}
          {entry.data?.safety?.emergency && <p className="alert small">{t("log.emergency")}</p>}
        </>
      )}
    </div>
  );
}

function PhotoAnswerBody({ entry }) {
  const { t } = useI18n();
  if (entry.status === "waiting") {
    return (
      <div className="body">
        <p className="small">{entry.data?.questions?.[0]?.text}</p>
        <p className="muted small">{t("log.photoWaiting")}</p>
      </div>
    );
  }
  return (
    <div className="body">
      <p className="small">{entry.log?.detail}</p>
    </div>
  );
}

// 화면에서 만든 기록(민원 종류 변경·중단·관계없는 말)은 번역 키로 저장해 두고 지금 화면 언어로 그린다
function NoteBody({ log }) {
  const { t } = useI18n();
  let text = log?.detail ?? "";
  if (log?.from && log?.to) text = `${t(log.from.key)} → ${t(log.to.key)}`;
  else if (log?.detailKey) text = t(log.detailKey);
  return (
    <div className="body">
      <p className="small">
        {text}
        {log?.reason ? ` · ${log.reason}` : ""}
      </p>
      {log?.guarded && <p className="small warn">{t("log.contactGuarded")}</p>}
    </div>
  );
}

function ChatBody({ chat, reply }) {
  const { t } = useI18n();
  return (
    <div className="body">
      <p className="small">{chat.turns > 1 ? t("log.chatTurn", { turns: chat.turns }) : t("log.chatFirst")}</p>
      {chat.guarded && <p className="small warn">{t("log.contactGuarded")}</p>}
      <p className="muted small">{t("log.reply", { reply })}</p>
    </div>
  );
}

function Body({ entry, next }) {
  const d = entry.data ?? {};
  if (["switch", "stop", "off_topic", "answer"].includes(entry.node)) return <NoteBody log={entry.log} />;
  if (entry.node === "ask") return <AskBody entry={entry} />;
  if (entry.node === "confirm_location") return <ConfirmBody entry={entry} />;
  if (entry.node === "look") return <LookBody entry={entry} />;
  if (entry.node === "confirm_photo") return <PhotoAnswerBody entry={entry} />;
  if (["act", "locate", "deliver", "svc_act"].includes(entry.node)) return <ActBody entry={entry} />;
  if (entry.status !== "done") return null;
  if (entry.node === "svc_plan") return <PlanBody plan={d.plan} />;
  if (entry.node === "svc_check") return <CheckBody info={d.info} />;
  if (entry.node === "svc_answer") return <GuideLogBody guide={d.guide} />;
  if (entry.node === "decide") return <DecideBody decision={d.decision} />;
  if (entry.node === "draft") return <DraftBody entry={entry} />;
  if (entry.node === "review") return <ReviewBody review={d.review} />;
  if (entry.node === "translate") return <TranslateBody translation={d.translation} />;
  if (entry.node === "chat") return <ChatBody chat={d.chat} reply={d.understanding?.reply} />;
  if (entry.node === "guard") return <GuardBody safety={d.safety} />;
  if (entry.node === "understand") return <UnderstandBody u={d.understanding} chatted={next?.node === "chat"} />;
  if (entry.node === "plan") return <PlanBody plan={d.plan} />;
  if (entry.node === "check") return <CheckBody info={d.info} />;
  return null;
}

function entryTitle(entry, t) {
  if (entry.node === "understand" && entry.log && !["complaint", "service"].includes(entry.data?.understanding?.intent)) return t("log.inputCheck");
  if (entry.node === "draft" && entry.log?.title?.includes("사용자")) return t("log.draftRevision");
  if (entry.node === "draft" && entry.log?.title?.includes("검증")) return t("log.draftReview");
  return t(`node.${entry.node}`);
}

export default function AgentLog({ timeline, running }) {
  const { t } = useI18n();
  return (
    <section className="panel log" aria-label={t("log.title")}>
      <header className="log-head">
        <h2>{t("log.title")}</h2>
        <span className="muted small">{t("log.sub")}</span>
      </header>
      {timeline.length === 0 ? (
        <div className="empty">
          <p>{t("log.empty")}</p>
          <ol className="flow">
            {t("log.flow").map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </div>
      ) : (
        <ol className="timeline">
          {timeline.map((entry, i) => (
            <li key={entry.id} className={`entry entry-${entry.status}`}>
              <div className="entry-marker">{entry.status === "running" ? <span className="spinner" /> : i + 1}</div>
              <div className="entry-card">
                <div className="entry-head">
                  <strong>{entryTitle(entry, t)}</strong>
                  <div className="row">
                    <SourceBadge log={entry.log} />
                    <span className={`status status-${entry.status}`}>{t(`status.${entry.status}`)}</span>
                    {entry.log?.at && <span className="muted small">{entry.log.at}</span>}
                  </div>
                </div>
                <Body entry={entry} next={timeline[i + 1]} />
              </div>
            </li>
          ))}
          {running && timeline.every((e) => e.status !== "running") && (
            <li className="entry entry-running">
              <div className="entry-marker">
                <span className="spinner" />
              </div>
              <div className="entry-card muted">{t("log.next")}</div>
            </li>
          )}
        </ol>
      )}
    </section>
  );
}
