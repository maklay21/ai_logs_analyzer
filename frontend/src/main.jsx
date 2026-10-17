import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

const api = async (path, options = {}) => {
  const response = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `Request failed (${response.status})`);
  }
  if (response.status === 204) return null;
  return response.json();
};

const fmtTime = (value) => value
  ? new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
  : '—';
const fmtBytes = (value = 0) => {
  if (value < 1024) return `${value} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let amount = value / 1024;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
  return `${amount.toFixed(1)} ${units[unit]}`;
};

function Metric({ label, value, detail, tone = '' }) {
  return <article className={`metric-card ${tone}`}><span>{label}</span><strong>{value ?? '—'}</strong>{detail && <small>{detail}</small>}</article>;
}

function App() {
  const [overview, setOverview] = useState({ sources: [], latest_resource: null });
  const [resources, setResources] = useState([]);
  const [selectedId, setSelectedId] = useState('');
  const [events, setEvents] = useState([]);
  const [report, setReport] = useState(null);
  const [path, setPath] = useState('');
  const [sourceName, setSourceName] = useState('');
  const [agentStatus, setAgentStatus] = useState({ running: false, last_error: null });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const selected = useMemo(() => overview.sources.find((item) => item.id === selectedId), [overview, selectedId]);
  const refresh = useCallback(async () => {
    try {
      const [nextOverview, nextResources, nextAgentStatus] = await Promise.all([
        api('/overview'), api('/resources?limit=36'), api('/agent/status'),
      ]);
      setOverview(nextOverview);
      setResources(nextResources.samples || []);
      setAgentStatus(nextAgentStatus);
      setSelectedId((current) => current || nextOverview.sources[0]?.id || '');
      setError('');
    } catch (err) { setError(err.message); }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 10000);
    return () => clearInterval(timer);
  }, [refresh]);

  const loadSourceData = useCallback(async (sourceId) => {
    if (!sourceId) { setEvents([]); setReport(null); return; }
    try {
      const [eventData, reportData] = await Promise.all([
        api(`/sources/${sourceId}/events?limit=80`),
        api(`/sources/${sourceId}/reports/latest`).catch(() => null),
      ]);
      setEvents(eventData.events || []);
      setReport(reportData);
    } catch (err) { setError(err.message); }
  }, []);

  useEffect(() => { loadSourceData(selectedId); }, [selectedId, loadSourceData]);

  useEffect(() => {
    const timer = setInterval(() => {
      if (selectedId) loadSourceData(selectedId);
    }, 15000);
    return () => clearInterval(timer);
  }, [selectedId, loadSourceData]);

  const addSource = async (event) => {
    event.preventDefault();
    setBusy(true); setError(''); setNotice('');
    try {
      const source = await api('/sources', {
        method: 'POST', body: JSON.stringify({ path, name: sourceName || null }),
      });
      setPath(''); setSourceName(''); setSelectedId(source.id);
      await refresh(); setNotice('Папка логов подключена.');
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  const removeSource = async () => {
    if (!selectedId || !window.confirm(`Удалить источник «${selected?.name}» и его отчёты?`)) return;
    try {
      await api(`/sources/${selectedId}`, { method: 'DELETE' });
      setSelectedId(''); setReport(null); setEvents([]); await refresh();
    } catch (err) { setError(err.message); }
  };

  const latest = overview.latest_resource;
  const dockerMetric = latest?.docker_containers?.[0];
  const series = resources.slice(-24);

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#top"><span className="brand-mark">S</span><span><b>SIGNAL</b><small>AI OBSERVABILITY</small></span></a>
      <div className="side-label">WORKSPACE</div>
      <button className="side-link active"><span>◫</span> Overview</button>
      <button className="side-link" onClick={() => document.getElementById('logs-panel')?.scrollIntoView({ behavior: 'smooth' })}><span>⌁</span> Log explorer</button>
      <button className="side-link" onClick={() => document.getElementById('resources-panel')?.scrollIntoView({ behavior: 'smooth' })}><span>◉</span> Resources</button>
      <div className="sidebar-footer"><i className="pulse" /> Autonomous agent<small>MCP tools · bounded analysis</small></div>
    </aside>

    <main id="top" className="main-content">
      <header className="topbar">
        <div><div className="eyebrow">OBSERVABILITY / APPLICATION HEALTH</div><h1>Log intelligence</h1><p>Correlate incidents, traces and resource pressure.</p></div>
        <div className="top-actions"><span className="live-pill"><i /> LIVE TELEMETRY</span><button className="icon-button" title="Обновить данные" onClick={refresh}>↻</button></div>
      </header>

      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert success">{notice}</div>}

      <section className="metrics-grid">
        <Metric label="LOG SOURCES" value={overview.sources.length} detail="подключённых директорий" />
        <Metric label="HOST CPU" value={`${latest?.host_cpu_percent?.toFixed(1) ?? '—'}%`} detail="средняя нагрузка хоста" tone="violet" />
        <Metric label="HOST MEMORY" value={`${latest?.host_memory_percent?.toFixed(1) ?? '—'}%`} detail="использовано" tone="blue" />
        <Metric label="APP CONTAINER" value={dockerMetric ? `${dockerMetric.cpu_percent.toFixed(1)}%` : '—'} detail={dockerMetric ? `${fmtBytes(dockerMetric.memory_usage_bytes)} / ${fmtBytes(dockerMetric.memory_limit_bytes)} RAM` : 'Docker container не настроен'} tone="amber" />
      </section>

      <section className="content-grid">
        <article className="panel source-panel">
          <div className="panel-heading"><div><div className="eyebrow">LOG PIPELINES</div><h2>Sources</h2></div><span className="count-badge">{overview.sources.length}</span></div>
          <form className="source-form" onSubmit={addSource}>
            <label>Путь к папке логов<input required value={path} onChange={(e) => setPath(e.target.value)} placeholder="/logs/payments" /></label>
            <label>Название источника<input value={sourceName} onChange={(e) => setSourceName(e.target.value)} placeholder="Payments API" /></label>
            <button className="primary-button" disabled={busy}>{busy ? 'Обработка…' : '＋ Подключить папку'}</button>
            <small className="field-hint">Папка должна находиться внутри LOG_ALLOWED_ROOTS. Не добавляйте вложенные или пересекающиеся источники.</small>
          </form>
          <div className="source-list">
            {overview.sources.map((source) => <button key={source.id} className={`source-row ${selectedId === source.id ? 'selected' : ''}`} onClick={() => setSelectedId(source.id)}>
              <span className="source-icon">▤</span><span className="source-info"><b>{source.name}</b><small>{source.path}</small></span><span className="source-count">{source.events_count.toLocaleString()}<small>events</small></span>
            </button>)}
            {!overview.sources.length && <div className="empty-state">Проверьте LOG_ALLOWED_ROOTS и подключение папки логов к контейнеру. Разрешённый корень появится автоматически.</div>}
          </div>
          {selected && <div className="source-actions"><span>Scan: {fmtTime(selected.last_scan_at)}</span><button className="quiet-button danger-text" onClick={removeSource}>Удалить источник</button></div>}
        </article>

        <article id="resources-panel" className="panel resource-panel">
          <div className="panel-heading"><div><div className="eyebrow">SYSTEM TELEMETRY</div><h2>Resource consumption</h2></div><span className="refresh-state"><i /> каждые 15 сек</span></div>
          <div className="resource-chart">
            <div className="chart-title"><span>CPU LOAD</span><b>{latest?.host_cpu_percent?.toFixed(1) ?? '—'}%</b></div>
            <div className="bar-chart">{series.map((sample, index) => <div className="bar-column" key={`${sample.sampled_at}-cpu`} title={`${fmtTime(sample.sampled_at)} · CPU ${sample.host_cpu_percent.toFixed(1)}%`}><i style={{ height: `${Math.max(3, sample.host_cpu_percent)}%` }} /><span>{index % 6 === 0 ? new Date(sample.sampled_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</span></div>)}</div>
          </div>
          <div className="resource-chart memory-chart">
            <div className="chart-title"><span>MEMORY PRESSURE</span><b>{latest?.host_memory_percent?.toFixed(1) ?? '—'}%</b></div>
            <div className="bar-chart">{series.map((sample, index) => <div className="bar-column" key={`${sample.sampled_at}-mem`} title={`${fmtTime(sample.sampled_at)} · RAM ${sample.host_memory_percent.toFixed(1)}%`}><i style={{ height: `${Math.max(3, sample.host_memory_percent)}%` }} /><span>{index % 6 === 0 ? new Date(sample.sampled_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</span></div>)}</div>
          </div>
          <div className="resource-foot"><span>Process RAM <b>{fmtBytes(latest?.process_memory_bytes)}</b></span><span>Root disk <b>{latest?.host_disk_percent?.toFixed(1) ?? '—'}%</b></span><span>Container RAM <b>{dockerMetric ? `${dockerMetric.memory_percent.toFixed(1)}%` : '—'}</b></span></div>
          {latest?.docker_error && <div className="inline-warning">Docker metrics unavailable: {latest.docker_error}</div>}
        </article>
      </section>

      <section id="logs-panel" className="panel analysis-panel">
        <div className="panel-heading analysis-heading"><div><div className="eyebrow">АВТОНОМНОЕ РАССЛЕДОВАНИЕ</div><h2>{selected?.name || 'Ожидание источника логов'}</h2><p>{selected?.path || 'Агент автоматически подключит разрешённую папку логов при запуске.'}</p></div>
          <div className="agent-status"><span className={agentStatus.running ? 'status-dot running' : 'status-dot'} /><b>{agentStatus.running ? 'Агент работает' : 'Агент запускается'}</b><small>{agentStatus.last_error ? `Ошибка: ${agentStatus.last_error}` : `Модель: ${agentStatus.provider || '—'} · проверка каждые ${agentStatus.poll_seconds || 60} сек`}</small></div>
        </div>
        <div className="analysis-layout">
          <div className="report-column">
            {report ? <>
              <div className="report-meta"><span className="provider-tag">{report.provider}</span><span>Generated {fmtTime(report.created_at)}</span></div>
              <div className="report-markdown">{report.summary.split('\n').map((line, index) => line.startsWith('#') ? <h3 key={index}>{line.replace(/^#+\s*/, '')}</h3> : line ? <p key={index}>{line}</p> : null)}</div>
              <h3 className="subheading">Recurring error signatures</h3>
              <div className="finding-list">{report.findings?.length ? report.findings.map((finding) => <div className="finding" key={finding.fingerprint}><span className="severity-dot" /><div><b>{finding.logger || 'unknown logger'}</b><p>{finding.message}</p></div><strong>{finding.count}×</strong></div>) : <div className="empty-state">Ошибки не обнаружены.</div>}</div>
            </> : <div className="empty-report"><span>✳</span><h3>Ожидание первого отчёта</h3><p>Фоновый агент сканирует источник и автоматически запускает расследование при запуске приложения и при изменении логов.</p></div>}
          </div>
          <aside className="dependency-column">
            <div className="eyebrow">DEPENDENCY TRACE</div><h3>Observed call flow</h3>
            {report?.dependency_graph?.edges?.length ? <div className="dependency-list">{report.dependency_graph.edges.map((edge, index) => <div className="dependency-edge" key={`${edge.from}-${edge.to}-${index}`}><span>{edge.from}</span><i>→</i><span>{edge.to}</span><small>{edge.weight}</small></div>)}</div> : <div className="dependency-empty">Сервисные связи появятся, когда в логах найдутся общие trace_id или request_id.</div>}
            {report && <div className="severity-summary">{Object.entries(report.severity_counts || {}).sort(([a], [b]) => a.localeCompare(b)).map(([level, count]) => <div key={level}><span className={`level-chip ${level.toLowerCase()}`}>{level}</span><b>{count}</b></div>)}</div>}
          </aside>
        </div>
      </section>

      <section className="panel events-panel">
        <div className="panel-heading"><div><div className="eyebrow">RECENT SIGNALS</div><h2>Log events</h2></div><span className="count-badge">{events.length} shown</span></div>
        <div className="event-table-wrap"><table><thead><tr><th>TIME</th><th>LEVEL</th><th>SERVICE</th><th>MESSAGE</th></tr></thead><tbody>
          {events.map((event) => <tr key={event.id}><td className="event-time">{fmtTime(event.timestamp)}</td><td><span className={`level-chip ${event.level.toLowerCase()}`}>{event.level}</span></td><td className="logger-cell">{event.logger}</td><td className="message-cell" title={`${event.file}:${event.line}`}>{event.message}</td></tr>)}
          {!events.length && <tr><td colSpan="4" className="empty-cell">Агент покажет события после первого сканирования источника.</td></tr>}
        </tbody></table></div>
      </section>
      <footer>AI LOGS ANALYZER <span>·</span> autonomous, evidence first</footer>
    </main>
  </div>;
}

createRoot(document.getElementById('root')).render(<App />);
