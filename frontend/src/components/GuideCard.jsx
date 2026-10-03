import { useI18n } from "../i18n.js";

// 민원 서비스 안내 카드: 지금 추천 → 받는 방법(온라인·발급기·방문·전화) → 가까운 곳(운영 여부) → 준비물·할 일·주의
// 수수료·연락처·주소는 지식베이스와 검색 결과 그대로, 안내 문장(추천·할 일)은 Claude가 시민의 언어로 쓴 것

const TYPE_ICON = { online: "🌐", kiosk: "🖨️", visit: "🏢", phone: "☎" };

function weekdayName(date, lang) {
  try {
    return new Intl.DateTimeFormat(lang, { weekday: "short" }).format(new Date(`${date}T12:00:00+09:00`));
  } catch {
    return "";
  }
}

function StateBadge({ place }) {
  const { t } = useI18n();
  const cls = { open: "badge badge-ok", closed: "badge badge-warn", unknown: "badge" }[place.state] ?? "badge";
  return <span className={cls}>{t(`guide.state.${place.state}`)}</span>;
}

function Place({ place }) {
  const { t } = useI18n();
  const hours = place.today === "휴무" ? t("guide.closedToday") : place.today ? t("guide.today", { hours: place.today }) : place.hours_note;
  return (
    <li className="place">
      <div className="row">
        <strong>{place.name}</strong>
        {place.distance_m != null && <span className="small muted">{place.distance_m.toLocaleString()}m</span>}
        <StateBadge place={place} />
      </div>
      {place.spot && <p className="small muted">{place.spot}</p>}
      <p className="small muted">{place.address}</p>
      <div className="row small">
        {hours && <span>{hours}</span>}
        {place.phone && <span>☎ {place.phone}</span>}
        {place.url && (
          <a href={place.url} target="_blank" rel="noopener noreferrer">
            {t("guide.map")} ↗
          </a>
        )}
      </div>
    </li>
  );
}

export default function GuideCard({ guide }) {
  const { t, lang } = useI18n();
  const g = guide;
  const now = g.now;
  const dayType = now.holiday ? ` · ${t("guide.holiday")}` : now.weekend ? ` · ${t("guide.weekend")}` : "";
  const officeGroups = Object.entries(g.offices ?? {});
  const hasPlaces = officeGroups.some(([, places]) => places.length > 0) || g.kiosks?.length > 0;
  const kioskFromData = g.kiosks?.some((k) => k.hours_source === "data_go_kr");
  // 알아 둘 점: Claude가 지식베이스의 주의할 점을 이 시민의 상황·언어에 맞춰 쓴 것. 없으면 지식베이스 문장 그대로
  const notes = g.tips?.length > 0 ? g.tips : g.cautions ?? [];

  return (
    <div className="guide-card">
      <div className="row">
        <span className="tag">{t(`group.${g.group}`)}</span>
        <strong className="guide-title">{t(`service.${g.code}`)}</strong>
      </div>
      <p>{g.summary}</p>
      {g.recommendation && (
        <div className="guide-recommend">
          <span className="small strong">{t("guide.recommend")}</span>
          <p>{g.recommendation}</p>
        </div>
      )}
      {g.deadline && (
        <p className="small warn">
          {t("guide.deadline")}: {g.deadline}
        </p>
      )}

      <section>
        <h4>{t("guide.ways")}</h4>
        <ul className="ways">
          {g.channels.map((c) => (
            <li key={`${c.type}-${c.name}`}>
              <span className="way-type">
                {TYPE_ICON[c.type]} {t(`guide.type.${c.type}`)}
              </span>
              <div>
                <div className="row">
                  <strong>{c.name}</strong>
                  {c.fee && <span className="chip">{c.fee}</span>}
                  {c.hours && <span className="small muted">{c.hours}</span>}
                </div>
                <p className="small muted">{c.how}</p>
                <div className="row small">
                  {c.phone && <span>☎ {c.phone}</span>}
                  {c.url && (
                    <a href={c.url} target="_blank" rel="noopener noreferrer">
                      {t("guide.go")}
                    </a>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h4>
          {t("guide.nearby")}{" "}
          <span className="small muted">
            {t("guide.now", { date: now.date, weekday: weekdayName(now.date, lang), time: now.time })}
            {dayType}
          </span>
        </h4>
        {!g.location && <p className="small muted">{t("guide.noLocation")}</p>}
        {g.location && !hasPlaces && <p className="small muted">{t("guide.noPlaces")}</p>}
        {officeGroups.map(([kind, places]) =>
          places.length > 0 ? (
            <div key={kind} className="place-group">
              <p className="small strong">{t(`office.${kind}`)}</p>
              <ul className="places">
                {places.map((p) => (
                  <Place key={`${p.name}-${p.address}`} place={p} />
                ))}
              </ul>
            </div>
          ) : null,
        )}
        {g.kiosks?.length > 0 && (
          <div className="place-group">
            <p className="small strong">{t("guide.kiosks")}</p>
            <ul className="places">
              {g.kiosks.map((p) => (
                <Place key={`${p.name}-${p.address}`} place={p} />
              ))}
            </ul>
            {kioskFromData && <p className="small muted">{t("guide.hoursFromData")}</p>}
          </div>
        )}
      </section>

      {g.prepare?.length > 0 && (
        <section>
          <h4>{t("guide.prepare")}</h4>
          <ul className="bullets">
            {g.prepare.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </section>
      )}
      {g.steps?.length > 0 && (
        <section>
          <h4>{t("guide.steps")}</h4>
          <ol className="bullets">
            {g.steps.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ol>
        </section>
      )}
      {notes.length > 0 && (
        <section>
          <h4>{t("guide.tips")}</h4>
          <ul className="bullets">
            {notes.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </section>
      )}
      {g.guarded && <p className="small warn">{t("guide.guarded")}</p>}
      <p className="small muted">{t("guide.disclaimer")}</p>
      <p className="small muted">{t("guide.basis", { basis: g.basis, checked: g.checked })}</p>
    </div>
  );
}
