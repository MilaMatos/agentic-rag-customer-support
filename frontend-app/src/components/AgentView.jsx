import { useCallback, useEffect, useRef, useState } from 'react';
import { api, DEFAULT_TENANT, formatTime, getInitials } from '../services/api';

const FILTER_MAP = {
  Open: (s) => s.status !== 'ESCALADA_N2' && s.status !== 'ENCERRADA',
  Escalated: (s) => s.status === 'ESCALADA_N2',
  Closed: (s) => s.status === 'ENCERRADA',
};

function statusBadge(status) {
  if (status === 'ESCALADA_N2') return 'bg-warning-container text-on-warning-container';
  if (status === 'ENCERRADA') return 'bg-light-surface-container text-light-on-surface-variant';
  return 'bg-light-tertiary-container text-light-on-tertiary-container';
}

export default function AgentView() {
  const [sessions, setSessions] = useState([]);
  const [activeFilter, setActiveFilter] = useState('Open');
  const [searchQuery, setSearchQuery] = useState('');
  const [activeId, setActiveId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [draft, setDraft] = useState('');
  const [originalDraft, setOriginalDraft] = useState('');
  const [rightTab, setRightTab] = useState('copilot');
  const [clientTypingMap, setClientTypingMap] = useState({});
  const [processingMap, setProcessingMap] = useState({});
  const [liveSuggestionMap, setLiveSuggestionMap] = useState({});
  const [liveClientMsgMap, setLiveClientMsgMap] = useState({});
  const [busy, setBusy] = useState(false);

  const wsRef = useRef(null);
  const typingTimerRef = useRef(null);
  const activeIdRef = useRef(null);
  activeIdRef.current = activeId;

  const loadSessions = useCallback(async () => {
    try {
      const res = await api.listSessions();
      setSessions(res.items || []);
    } catch {
      // ignora erro transitório
    }
  }, []);

  const loadDetail = useCallback(async (sessionId) => {
    if (!sessionId) return;
    try {
      const data = await api.getMessages(sessionId, 'agent');
      setDetail(data);
      const ps = data?.pending_suggestion;
      const pendingText =
        ps?.ai_suggested_text ||
        ps?.mensagem_sugerida ||
        ps?.resposta_sugerida ||
        '';
      setDraft(pendingText);
      setOriginalDraft(pendingText);
    } catch {
      // ignora erro transitório
    }
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  useEffect(() => {
    if (activeId) loadDetail(activeId);
  }, [activeId, loadDetail]);

  useEffect(() => {
    const ws = new WebSocket(api.wsAgentUrl(DEFAULT_TENANT));
    wsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const { type, data } = JSON.parse(event.data);
        const sid = data?.session_id;

        if (type === 'client.typing' && sid) {
          setClientTypingMap((prev) => ({ ...prev, [sid]: Boolean(data.is_typing) }));
        } else if (type === 'copilot.processing' && sid) {
          setProcessingMap((prev) => ({ ...prev, [sid]: true }));
        } else if (type === 'copilot.suggestion_ready' && sid) {
          setProcessingMap((prev) => ({ ...prev, [sid]: false }));
          setLiveSuggestionMap((prev) => ({ ...prev, [sid]: data }));
          loadSessions();
          if (activeIdRef.current === sid) {
            if (data.ai_suggested_text) {
              setDraft(data.ai_suggested_text);
              setOriginalDraft(data.ai_suggested_text);
            }
            loadDetail(sid);
          }
        } else if (type === 'copilot.error' && sid) {
          setProcessingMap((prev) => ({ ...prev, [sid]: false }));
        } else if (type === 'client.message_received' && sid) {
          setClientTypingMap((prev) => ({ ...prev, [sid]: false }));
          if (data?.content) {
            setLiveClientMsgMap((prev) => ({ ...prev, [sid]: data.content }));
          }
          loadSessions();
          if (activeIdRef.current === sid) {
            loadDetail(sid);
          }
        } else if (
          type === 'agent.message_sent' ||
          type === 'specialist.message_sent' ||
          type === 'session.escalated' ||
          type === 'session.closed'
        ) {
          if (sid) {
            setClientTypingMap((prev) => ({ ...prev, [sid]: false }));
            setLiveClientMsgMap((prev) => {
              const next = { ...prev };
              delete next[sid];
              return next;
            });
          }
          loadSessions();
          if (activeIdRef.current === sid) {
            loadDetail(sid);
          }
        }
      } catch {
        // ignora payload inválido
      }
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [loadDetail, loadSessions]);

  const sendTyping = (isTyping) => {
    if (!activeId || wsRef.current?.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: 'typing', session_id: activeId, is_typing: isTyping }));
  };

  const filteredSessions = sessions.filter((s) => {
    const matchesStatus = FILTER_MAP[activeFilter](s);
    const q = searchQuery.trim().toLowerCase();
    const matchesSearch =
      !q ||
      (s.customer_name || '').toLowerCase().includes(q) ||
      (s.categoria_atual || '').toLowerCase().includes(q) ||
      s.session_id.toLowerCase().includes(q);
    return matchesStatus && matchesSearch;
  });

  const activeSession = sessions.find((s) => s.session_id === activeId) || null;
  const currentStatus = detail?.status || activeSession?.status || '';
  const isLocked = currentStatus === 'ESCALADA_N2' || currentStatus === 'ENCERRADA';
  const pending = detail?.pending_suggestion || null;
  const liveMeta = (activeId && liveSuggestionMap[activeId]) || null;

  const auditorReason =
    liveMeta?.auditoria?.analise_raciocinio ||
    pending?.auditoria_raciocinio ||
    'Aguardando análise do auditor para o turno atual.';
  const ragChunk = liveMeta?.rag_contexto?.chunk_id || pending?.chunk_id || '—';
  const cacheHit = liveMeta?.rag_contexto?.reutilizado_do_cache ?? false;
  const escalationAlert = Boolean(
    liveMeta?.auditoria?.requer_escalonamento || pending?.alerta_escalonamento
  );

  const pendingQuestion =
    pending?.client_message ||
    pending?.pergunta_cliente ||
    (activeId ? liveClientMsgMap[activeId] : null);

  const handleConfirm = async (escalate = false) => {
    if (!activeId || !pending?.suggestion_id || isLocked || busy) return;
    const text = draft.trim();
    if (!escalate && !text) return;

    setBusy(true);
    sendTyping(false);
    try {
      const humanAction = escalate
        ? 'ESCALADA_N2'
        : text === originalDraft.trim()
        ? 'ACEITA_SEM_EDICAO'
        : 'EDITADA';

      await api.confirmSuggestion(activeId, pending.suggestion_id, {
        human_action: humanAction,
        human_final_text: escalate
          ? 'Seu atendimento foi transferido para um especialista N2/N3 que dará continuidade por aqui.'
          : text,
        attendant_id: 'n1-agent',
      });
      await loadSessions();
      await loadDetail(activeId);
    } finally {
      setBusy(false);
    }
  };

  const handleClose = async () => {
    if (!activeId || isLocked || busy) return;
    setBusy(true);
    try {
      await api.closeByAgent(activeId);
      await loadSessions();
      await loadDetail(activeId);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="h-[calc(100vh-48px)] w-full grid grid-cols-1 lg:grid-cols-[280px_minmax(0,1fr)_340px] bg-light-surface">
      {/* LEFT SIDEBAR: Your Inbox */}
      <aside className="bg-light-surface-container-low border-r border-light-outline-variant flex flex-col overflow-hidden">
        <header className="px-lg pt-lg pb-md border-b border-light-outline-variant flex flex-col gap-md">
          <div className="flex items-center gap-sm">
            <div className="w-7 h-7 rounded bg-light-primary text-light-on-primary flex items-center justify-center shrink-0">
              <span className="material-symbols-outlined text-body-md">hub</span>
            </div>
            <span className="font-headline text-headline-sm text-light-on-surface">
              Nexus Support Copilot
            </span>
          </div>

          <div className="flex items-center justify-between">
            <h1 className="font-headline text-headline-md text-light-on-surface">Your Inbox</h1>
            <span className="inline-flex items-center justify-center min-w-[20px] h-5 px-xs rounded-full bg-light-tertiary-container text-light-on-tertiary-container font-label text-label-sm tabular-nums">
              {filteredSessions.length}
            </span>
          </div>

          <div className="grid grid-cols-3 gap-xs bg-light-surface-container p-xs rounded">
            {['Open', 'Escalated', 'Closed'].map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => setActiveFilter(tab)}
                className={`py-xs px-xs rounded-sm font-label text-label-md transition-colors duration-state-change ${
                  activeFilter === tab
                    ? 'bg-light-surface text-light-primary shadow-sm'
                    : 'text-light-on-surface-variant hover:text-light-on-surface'
                }`}
              >
                {tab}
              </button>
            ))}
          </div>

          <label className="relative flex items-center w-full">
            <span className="material-symbols-outlined text-headline-md text-light-outline absolute left-md pointer-events-none">
              search
            </span>
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search conversations..."
              className="w-full rounded bg-light-surface border border-light-outline-variant pl-2xl pr-md py-sm font-body text-body-sm text-light-on-surface placeholder:text-light-outline focus:border-light-primary focus:ring-1 focus:ring-light-primary focus:outline-none"
            />
          </label>
        </header>

        <nav className="flex-1 overflow-y-auto p-sm flex flex-col gap-xs">
          {filteredSessions.length === 0 ? (
            <div className="p-lg text-center text-light-on-surface-variant font-body text-body-sm">
              Nenhuma sessão em {activeFilter}.
            </div>
          ) : (
            filteredSessions.map((s) => {
              const selected = s.session_id === activeId;
              return (
                <button
                  key={s.session_id}
                  type="button"
                  onClick={() => setActiveId(s.session_id)}
                  className={`text-left rounded p-md border transition-colors duration-state-change flex items-start gap-md ${
                    selected
                      ? 'bg-light-surface border-light-primary ring-1 ring-light-primary shadow-sm'
                      : 'bg-light-surface border-light-outline-variant hover:border-light-primary'
                  }`}
                >
                  <div
                    className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 font-title text-title-sm ${
                      selected
                        ? 'bg-light-primary text-light-on-primary'
                        : 'bg-light-surface-container-high text-light-on-surface'
                    }`}
                  >
                    {getInitials(s.customer_name)}
                  </div>
                  <div className="flex-1 min-w-0 flex flex-col gap-xs">
                    <div className="flex items-center justify-between gap-xs">
                      <span className="font-title text-title-sm text-light-on-surface truncate">
                        {s.customer_name || 'Cliente'}
                      </span>
                      <span className="font-label text-label-sm text-light-outline tabular-nums">
                        T{s.turno_global || 0}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-xs">
                      <span
                        className={`inline-flex items-center px-sm py-xs rounded-full font-label text-label-sm ${statusBadge(
                          s.status
                        )}`}
                      >
                        {s.status}
                      </span>
                      <span className="font-label text-label-sm text-light-outline truncate">
                        {s.categoria_atual || 'Geral'}
                      </span>
                    </div>
                  </div>
                </button>
              );
            })
          )}
        </nav>
      </aside>

      {/* CENTER PANEL: Thread & Composer */}
      <main className="bg-light-surface flex flex-col border-r border-light-outline-variant overflow-hidden">
        {!activeSession ? (
          <div className="m-auto text-center text-light-on-surface-variant p-xl">
            <span className="material-symbols-outlined text-headline-lg text-light-outline">
              forum
            </span>
            <p className="mt-sm font-body text-body-md">
              Selecione uma conversa na fila à esquerda.
            </p>
          </div>
        ) : (
          <>
            <header className="px-xl py-md border-b border-light-outline-variant flex items-center justify-between gap-md">
              <div className="flex items-center gap-md min-w-0">
                <div className="w-9 h-9 rounded-full bg-light-tertiary-container text-light-on-tertiary-container flex items-center justify-center shrink-0 font-title text-title-sm">
                  {getInitials(activeSession.customer_name)}
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-sm flex-wrap">
                    <h2 className="font-headline text-headline-md text-light-on-surface">
                      {activeSession.customer_name || 'Cliente'}
                    </h2>
                    <span className="inline-flex items-center px-sm py-xs rounded-full bg-light-surface-container text-light-on-surface-variant font-label text-label-sm">
                      {detail?.categoria_atual || activeSession.categoria_atual || 'Geral'}
                    </span>
                    <span
                      className={`inline-flex items-center px-sm py-xs rounded-full font-label text-label-sm ${statusBadge(
                        currentStatus
                      )}`}
                    >
                      {currentStatus}
                    </span>
                  </div>
                  <p className="font-mono text-mono-sm text-light-on-surface-variant truncate">
                    Session: {activeSession.session_id}
                  </p>
                </div>
              </div>

              <button
                type="button"
                disabled={isLocked || busy}
                onClick={handleClose}
                title={
                  currentStatus === 'ESCALADA_N2'
                    ? 'Sessão sob posse do Especialista N2/N3'
                    : 'Encerrar atendimento'
                }
                className="inline-flex items-center gap-xs px-lg py-sm rounded bg-light-surface border border-light-outline-variant text-light-on-surface hover:bg-light-surface-container disabled:opacity-40 disabled:cursor-not-allowed font-label text-label-lg transition-colors"
              >
                <span className="material-symbols-outlined text-body-md text-light-on-surface-variant">
                  check_circle
                </span>
                Close
              </button>
            </header>

            <section className="flex-1 overflow-y-auto px-xl py-lg flex flex-col gap-lg">
              {(detail?.messages || []).map((m) => {
                const isClient = m.sender_role === 'CLIENT';
                const isN2 = m.sender_role === 'SPECIALIST_N2';
                return (
                  <div
                    key={m.message_id}
                    className={`flex flex-col gap-xs max-w-prose ${
                      isClient ? 'items-start' : 'items-end self-end'
                    }`}
                  >
                    <div className="flex items-center gap-sm">
                      <span className="font-label text-label-md text-light-on-surface">
                        {isClient
                          ? activeSession.customer_name || 'Cliente'
                          : isN2
                          ? 'Specialist N2'
                          : 'Agent N1'}
                      </span>
                      <span className="font-label text-label-sm text-light-outline tabular-nums">
                        {formatTime(m.created_at)}
                      </span>
                    </div>
                    <div
                      className={`rounded-md px-lg py-md font-body text-body-md whitespace-pre-wrap ${
                        isClient
                          ? 'bg-slate-bubble text-on-slate-bubble'
                          : isN2
                          ? 'bg-light-tertiary-container text-light-on-tertiary-container border border-light-primary'
                          : 'bg-agent-bubble text-on-agent-bubble border border-light-tertiary-container'
                      }`}
                    >
                      {m.content}
                    </div>
                  </div>
                );
              })}

              {pendingQuestion && (
                <div className="flex flex-col items-start gap-xs max-w-prose">
                  <span className="font-label text-label-sm text-light-primary uppercase">
                    Pergunta pendente
                  </span>
                  <div className="rounded-md bg-slate-bubble text-on-slate-bubble px-lg py-md font-body text-body-md border border-light-primary">
                    {pendingQuestion}
                  </div>
                </div>
              )}

              {processingMap[activeId] && (
                <div className="self-start inline-flex items-center gap-sm px-md py-sm rounded-md bg-light-tertiary-container text-light-on-tertiary-container font-label text-label-md">
                  <span className="material-symbols-outlined text-body-md">auto_awesome</span>
                  Copiloto gerando sugestão...
                </div>
              )}
            </section>

            {clientTypingMap[activeId] && (
              <div className="px-xl pb-sm flex items-center gap-sm text-light-on-surface-variant">
                <div className="inline-flex items-center gap-xs px-md py-sm rounded-md bg-slate-bubble">
                  <span className="w-1.5 h-1.5 rounded-full bg-light-outline typing-dot-1" />
                  <span className="w-1.5 h-1.5 rounded-full bg-light-outline typing-dot-2" />
                  <span className="w-1.5 h-1.5 rounded-full bg-light-outline typing-dot-3" />
                </div>
                <span className="font-body text-body-sm text-light-outline">Client is typing...</span>
              </div>
            )}

            <footer className="px-xl pb-lg pt-sm border-t border-light-outline-variant">
              {isLocked ? (
                <div className="rounded-md bg-warning-container border border-warning px-lg py-md flex items-center gap-sm text-on-warning-container font-body text-body-sm">
                  <span className="material-symbols-outlined text-warning">lock</span>
                  {currentStatus === 'ESCALADA_N2'
                    ? 'Conversa escalada para o Especialista N2/N3. Somente leitura para o N1.'
                    : 'Conversa encerrada.'}
                </div>
              ) : (
                <div className="rounded-md border border-light-outline-variant bg-light-surface focus-within:border-light-primary focus-within:ring-1 focus-within:ring-light-primary">
                  <div className="px-md py-sm border-b border-light-outline-variant bg-light-surface-container-low rounded-t-md flex items-center justify-between">
                    <div className="flex items-center gap-xs text-light-primary">
                      <span className="material-symbols-outlined text-body-md">auto_awesome</span>
                      <span className="font-label text-label-md">
                        {pending ? 'AI Copilot Draft · Ready for review' : 'Aguardando mensagem do cliente'}
                      </span>
                    </div>
                  </div>

                  <textarea
                    rows={4}
                    value={draft}
                    disabled={!pending}
                    onChange={(e) => {
                      setDraft(e.target.value);
                      sendTyping(true);
                      clearTimeout(typingTimerRef.current);
                      typingTimerRef.current = setTimeout(() => sendTyping(false), 1800);
                    }}
                    placeholder="O rascunho do Copiloto aparecerá aqui..."
                    className="w-full border-0 bg-transparent px-md py-md font-body text-body-md text-light-on-surface placeholder:text-light-outline focus:ring-0 resize-none disabled:opacity-50"
                  />

                  <div className="px-md py-sm border-t border-light-outline-variant flex items-center justify-end gap-sm">
                    <button
                      type="button"
                      disabled={!pending || busy}
                      onClick={() => handleConfirm(true)}
                      className="inline-flex items-center gap-xs px-lg py-sm rounded bg-light-surface border border-light-outline-variant text-light-on-surface hover:bg-light-surface-container disabled:opacity-40 font-label text-label-lg transition-colors"
                    >
                      <span className="material-symbols-outlined text-headline-md text-warning">
                        arrow_upward
                      </span>
                      Escalate to N2
                    </button>

                    <button
                      type="button"
                      disabled={!pending || !draft.trim() || busy}
                      onClick={() => handleConfirm(false)}
                      className="inline-flex items-center gap-xs px-lg py-sm rounded bg-light-primary text-light-on-primary hover:bg-light-primary-container disabled:opacity-40 font-label text-label-lg transition-colors"
                    >
                      <span className="material-symbols-outlined text-headline-md">send</span>
                      Send Reply
                    </button>
                  </div>
                </div>
              )}
            </footer>
          </>
        )}
      </main>

      {/* RIGHT SIDEBAR: AI Copilot & Details */}
      <aside className="bg-light-surface-container-low flex flex-col overflow-hidden">
        <div className="px-lg pt-lg border-b border-light-outline-variant flex items-center gap-xl bg-light-surface">
          <button
            type="button"
            onClick={() => setRightTab('copilot')}
            className={`inline-flex items-center gap-xs pb-md border-b-2 font-label text-label-lg transition-colors ${
              rightTab === 'copilot'
                ? 'border-light-primary text-light-primary'
                : 'border-transparent text-light-on-surface-variant'
            }`}
          >
            <span className="material-symbols-outlined text-headline-md">auto_awesome</span>
            AI Copilot
          </button>
          <button
            type="button"
            onClick={() => setRightTab('details')}
            className={`inline-flex items-center gap-xs pb-md border-b-2 font-label text-label-lg transition-colors ${
              rightTab === 'details'
                ? 'border-light-primary text-light-primary'
                : 'border-transparent text-light-on-surface-variant'
            }`}
          >
            <span className="material-symbols-outlined text-headline-md">info</span>
            Details
          </button>
        </div>

        {rightTab === 'copilot' ? (
          <div className="p-lg flex flex-col gap-lg overflow-y-auto">
            <h3 className="font-headline text-headline-sm text-light-on-surface">Copilot Analysis</h3>

            <article className="rounded-md bg-light-surface border border-light-outline-variant p-lg flex flex-col gap-sm">
              <header className="flex items-center gap-xs">
                <span className="material-symbols-outlined text-body-md text-light-primary">
                  psychology
                </span>
                <h4 className="font-label text-label-sm uppercase text-light-outline">
                  WHY THIS RESPONSE?
                </h4>
              </header>
              <p className="font-body text-body-sm text-light-on-surface leading-relaxed">
                {auditorReason}
              </p>
            </article>

            <article className="rounded-md bg-light-surface border border-light-outline-variant p-lg flex flex-col gap-md">
              <header className="flex items-center gap-xs">
                <span className="material-symbols-outlined text-body-md text-light-primary">
                  database
                </span>
                <h4 className="font-label text-label-sm uppercase text-light-outline">
                  SIGNALS &amp; SOURCES
                </h4>
              </header>
              <div className="flex flex-col gap-sm">
                <div className="flex items-center justify-between">
                  <span className="font-body text-body-sm text-light-on-surface-variant">Category</span>
                  <span className="px-sm py-xs rounded-sm bg-light-surface-container font-label text-label-sm">
                    {detail?.categoria_atual || activeSession?.categoria_atual || '—'}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="font-body text-body-sm text-light-on-surface-variant">RAG Chunk ID</span>
                  <span className="px-sm py-xs rounded-sm bg-light-tertiary-container text-light-on-tertiary-container font-mono text-mono-sm">
                    {ragChunk}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="font-body text-body-sm text-light-on-surface-variant">
                    Semantic Cache
                  </span>
                  <span
                    className={`inline-flex items-center gap-xs px-sm py-xs rounded-full font-label text-label-sm ${
                      cacheHit
                        ? 'bg-success-container text-on-success-container'
                        : 'bg-light-surface-container text-light-on-surface-variant'
                    }`}
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${
                        cacheHit ? 'bg-success' : 'bg-light-outline'
                      }`}
                    />
                    {cacheHit ? 'Cache Hit' : 'Vector Search'}
                  </span>
                </div>
              </div>
            </article>

            {escalationAlert && (
              <article
                role="alert"
                className="rounded-md bg-warning-container border border-warning p-lg flex flex-col gap-sm"
              >
                <header className="flex items-center gap-xs text-on-warning-container">
                  <span className="material-symbols-outlined text-headline-md text-warning">
                    warning
                  </span>
                  <h4 className="font-label text-label-sm uppercase">ESCALATION ALERT</h4>
                </header>
                <p className="font-body text-body-sm text-on-warning-container">{auditorReason}</p>
              </article>
            )}
          </div>
        ) : (
          <div className="p-lg flex flex-col gap-md">
            <h3 className="font-headline text-headline-sm text-light-on-surface">
              Session Details
            </h3>
            <article className="rounded-md bg-light-surface border border-light-outline-variant p-lg flex flex-col gap-md">
              <div className="flex justify-between">
                <span className="font-body text-body-sm text-light-on-surface-variant">Customer</span>
                <span className="font-title text-title-sm">{activeSession?.customer_name || '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="font-body text-body-sm text-light-on-surface-variant">Status</span>
                <span className="font-label text-label-md">{currentStatus || '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="font-body text-body-sm text-light-on-surface-variant">Turns</span>
                <span className="font-mono text-mono-sm">{activeSession?.turno_global || 0}</span>
              </div>
            </article>
          </div>
        )}
      </aside>
    </div>
  );
}