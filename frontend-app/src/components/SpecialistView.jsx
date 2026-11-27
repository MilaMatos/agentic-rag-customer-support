import { useCallback, useEffect, useRef, useState } from 'react';
import { api, DEFAULT_TENANT, formatTime, getInitials } from '../services/api';

export default function SpecialistView() {
  const [queue, setQueue] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [dossier, setDossier] = useState(null);
  const [reply, setReply] = useState('');
  const [clientTyping, setClientTyping] = useState(false);
  const [busy, setBusy] = useState(false);

  const wsRef = useRef(null);
  const typingTimerRef = useRef(null);
  const activeIdRef = useRef(null);
  activeIdRef.current = activeId;

  const loadQueue = useCallback(async () => {
    try {
      const res = await api.listSpecialistQueue();
      setQueue(res.items || []);
    } catch {
      // ignora erro transitório
    }
  }, []);

  const loadDossier = useCallback(async (sessionId) => {
    if (!sessionId) return;
    try {
      const data = await api.getSpecialistDossier(sessionId);
      setDossier(data);
    } catch {
      // ignora erro transitório
    }
  }, []);

  useEffect(() => {
    loadQueue();
  }, [loadQueue]);

  useEffect(() => {
    if (activeId) {
      setClientTyping(false);
      loadDossier(activeId);
    }
  }, [activeId, loadDossier]);

  useEffect(() => {
    const ws = new WebSocket(api.wsSpecialistUrl(DEFAULT_TENANT));
    wsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const { type, data } = JSON.parse(event.data);
        const sid = data?.session_id;

        if (type === 'client.typing' && sid === activeIdRef.current) {
          setClientTyping(Boolean(data.is_typing));
        } else if (
          type === 'session.escalated' ||
          type === 'client.message_received' ||
          type === 'specialist.message_sent' ||
          type === 'session.closed'
        ) {
          if (sid === activeIdRef.current) {
            setClientTyping(false);
            loadDossier(sid);
          }
          loadQueue();
        }
      } catch {
        // ignora payload inválido
      }
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [loadDossier, loadQueue]);

  const sendTyping = (isTyping) => {
    if (!activeId || wsRef.current?.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: 'typing', session_id: activeId, is_typing: isTyping }));
  };

  const handleSendReply = async () => {
    const text = reply.trim();
    if (!activeId || !text || busy || dossier?.status !== 'ESCALADA_N2') return;
    setBusy(true);
    sendTyping(false);
    setReply('');
    try {
      await api.sendSpecialistMessage(activeId, text);
      await loadDossier(activeId);
    } finally {
      setBusy(false);
    }
  };

  const handleResolve = async () => {
    if (!activeId || busy || dossier?.status === 'ENCERRADA') return;
    setBusy(true);
    try {
      await api.resolveBySpecialist(activeId);
      await loadQueue();
      await loadDossier(activeId);
    } finally {
      setBusy(false);
    }
  };

  const isResolved = dossier?.status === 'ENCERRADA';

  return (
    <div className="h-[calc(100vh-48px)] w-full grid grid-cols-1 lg:grid-cols-[280px_minmax(0,1fr)_340px] bg-light-surface">
      {/* LEFT SIDEBAR: Escalated Queue */}
      <aside className="bg-light-surface-container-low border-r border-light-outline-variant flex flex-col overflow-hidden">
        <header className="px-lg pt-lg pb-md border-b border-light-outline-variant flex flex-col gap-md">
          <div className="flex items-center justify-between gap-sm">
            <div className="flex items-center gap-sm min-w-0">
              <div className="w-7 h-7 rounded bg-light-tertiary text-light-on-tertiary flex items-center justify-center shrink-0">
                <span className="material-symbols-outlined text-body-md">engineering</span>
              </div>
              <span className="font-headline text-headline-sm text-light-on-surface truncate">
                Nexus Specialist
              </span>
            </div>
            <span className="px-sm py-xs rounded-sm bg-light-surface-container text-light-on-surface-variant font-label text-label-sm">
              N2/N3
            </span>
          </div>

          <div className="flex items-center justify-between">
            <h1 className="font-headline text-headline-sm text-light-on-surface">
              Escalated Queue (N2/N3)
            </h1>
            <span className="inline-flex items-center justify-center min-w-[20px] h-5 px-xs rounded-full bg-light-tertiary-container text-light-on-tertiary-container font-label text-label-sm tabular-nums">
              {queue.length}
            </span>
          </div>
        </header>

        <nav className="flex-1 overflow-y-auto p-sm flex flex-col gap-xs">
          {queue.length === 0 ? (
            <div className="p-lg text-center text-light-on-surface-variant font-body text-body-sm">
              Nenhum chamado escalado no momento.
            </div>
          ) : (
            queue.map((t) => {
              const selected = t.session_id === activeId;
              return (
                <button
                  key={t.session_id}
                  type="button"
                  onClick={() => setActiveId(t.session_id)}
                  className={`text-left rounded p-md border bg-light-surface transition-colors flex flex-col gap-xs ${
                    selected
                      ? 'border-light-primary ring-1 ring-light-primary shadow-sm'
                      : 'border-light-outline-variant hover:border-light-primary'
                  }`}
                >
                  <div className="flex items-center justify-between gap-xs">
                    <span className="font-title text-title-sm text-light-on-surface truncate">
                      {t.customer_name || 'Cliente'}
                    </span>
                    <span className="font-label text-label-sm text-light-outline tabular-nums">
                      {t.turno_global} turns
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-xs">
                    <span className="px-sm py-xs rounded-sm bg-light-surface-container text-light-on-surface-variant font-label text-label-sm">
                      {t.categoria_atual || 'Geral'}
                    </span>
                    <span className="px-sm py-xs rounded-full bg-warning-container text-on-warning-container font-label text-label-sm">
                      ESCALADA_N2
                    </span>
                  </div>
                </button>
              );
            })
          )}
        </nav>
      </aside>

      {/* CENTER PANEL: History & Direct Reply */}
      <main className="bg-light-surface flex flex-col border-r border-light-outline-variant overflow-hidden">
        {!dossier ? (
          <div className="m-auto text-center text-light-on-surface-variant p-xl">
            <span className="material-symbols-outlined text-headline-lg text-light-outline">
              folder_shared
            </span>
            <p className="mt-sm font-body text-body-md">
              Selecione um chamado escalado na fila à esquerda.
            </p>
          </div>
        ) : (
          <>
            <header className="px-xl py-md border-b border-light-outline-variant flex items-center justify-between gap-md">
              <div className="flex items-center gap-md min-w-0">
                <div className="w-9 h-9 rounded-full bg-light-tertiary-container text-light-on-tertiary-container flex items-center justify-center font-title text-title-sm">
                  {getInitials(dossier.customer_name)}
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-sm flex-wrap">
                    <h2 className="font-headline text-headline-md text-light-on-surface">
                      {dossier.customer_name || 'Cliente'}
                    </h2>
                    <span
                      className={`px-sm py-xs rounded-full font-label text-label-sm ${
                        isResolved
                          ? 'bg-success-container text-on-success-container'
                          : 'bg-warning-container text-on-warning-container'
                      }`}
                    >
                      {isResolved ? 'RESOLVED' : 'ESCALADA_N2'}
                    </span>
                  </div>
                  <p className="font-mono text-mono-sm text-light-on-surface-variant truncate">
                    Session ID: {dossier.session_id}
                  </p>
                </div>
              </div>

              <button
                type="button"
                disabled={isResolved || busy}
                onClick={handleResolve}
                className="inline-flex items-center gap-xs px-lg py-sm rounded bg-success text-on-success hover:opacity-90 disabled:opacity-40 font-label text-label-lg transition-opacity"
              >
                <span className="material-symbols-outlined text-headline-md">task_alt</span>
                Resolve Ticket
              </button>
            </header>

            <section className="flex-1 overflow-y-auto px-xl py-lg flex flex-col gap-lg">
              {(dossier.messages || []).map((m) => {
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
                      {isN2 && (
                        <span className="px-xs py-xs rounded-sm bg-light-tertiary text-light-on-tertiary font-label text-label-sm">
                          N2
                        </span>
                      )}
                      <span className="font-label text-label-md text-light-on-surface">
                        {isClient
                          ? `${dossier.customer_name || 'Cliente'} (Client)`
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

              {clientTyping && (
                <div className="flex items-center gap-sm text-light-on-surface-variant">
                  <div className="inline-flex items-center gap-xs px-md py-sm rounded-md bg-slate-bubble">
                    <span className="w-1.5 h-1.5 rounded-full bg-light-outline typing-dot-1" />
                    <span className="w-1.5 h-1.5 rounded-full bg-light-outline typing-dot-2" />
                    <span className="w-1.5 h-1.5 rounded-full bg-light-outline typing-dot-3" />
                  </div>
                  <span className="font-body text-body-sm text-light-outline">
                    Client is typing...
                  </span>
                </div>
              )}
            </section>

            <footer className="px-xl pb-lg pt-sm border-t border-light-outline-variant">
              {isResolved ? (
                <div className="p-md rounded bg-success-container text-on-success-container text-center font-label text-label-md">
                  Chamado resolvido e encerrado.
                </div>
              ) : (
                <div className="rounded-md border border-light-outline-variant bg-light-surface focus-within:border-light-primary focus-within:ring-1 focus-within:ring-light-primary">
                  <div className="px-md py-sm border-b border-light-outline-variant bg-light-surface-container-low rounded-t-md flex items-center justify-between">
                    <div className="flex items-center gap-xs">
                      <span className="material-symbols-outlined text-body-md text-light-primary">
                        support_agent
                      </span>
                      <span className="font-label text-label-md text-light-on-surface">
                        Specialist N2 Direct Reply · Live Customer Channel
                      </span>
                    </div>
                  </div>
                  <textarea
                    rows={3}
                    value={reply}
                    onChange={(e) => {
                      setReply(e.target.value);
                      sendTyping(true);
                      clearTimeout(typingTimerRef.current);
                      typingTimerRef.current = setTimeout(() => sendTyping(false), 1800);
                    }}
                    placeholder="Escreva uma resposta direta para o cliente..."
                    className="w-full border-0 bg-transparent px-md py-md font-body text-body-md text-light-on-surface placeholder:text-light-outline focus:ring-0 resize-none"
                  />
                  <div className="px-md py-sm border-t border-light-outline-variant flex justify-end">
                    <button
                      type="button"
                      disabled={!reply.trim() || busy}
                      onClick={handleSendReply}
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

      {/* RIGHT SIDEBAR: Escalation Dossier */}
      <aside className="bg-light-surface-container-low flex flex-col overflow-hidden">
        <header className="px-lg pt-lg pb-md border-b border-light-outline-variant bg-light-surface flex items-center justify-between">
          <div className="flex items-center gap-xs">
            <span className="material-symbols-outlined text-headline-md text-light-primary">
              folder_shared
            </span>
            <h2 className="font-headline text-headline-md text-light-on-surface">
              Escalation Dossier
            </h2>
          </div>
          {dossier && (
            <span className="font-mono text-mono-sm text-light-outline">
              {dossier.turno_global} turns
            </span>
          )}
        </header>

        {dossier && (
          <div className="p-lg flex flex-col gap-md overflow-y-auto flex-1">
            <article className="rounded-md bg-light-surface border border-light-outline-variant p-lg flex flex-col gap-sm">
              <header className="flex items-center gap-xs">
                <span className="material-symbols-outlined text-body-md text-light-primary">
                  summarize
                </span>
                <h3 className="font-label text-label-sm uppercase text-light-outline">
                  HANDOFF SUMMARY
                </h3>
              </header>
              <p className="font-body text-body-sm text-light-on-surface whitespace-pre-wrap">
                {dossier.handoff_summary || 'Resumo não disponível.'}
              </p>
            </article>

            <article
              role="alert"
              className="rounded-md bg-warning-container border border-warning p-lg flex flex-col gap-sm"
            >
              <header className="flex items-center gap-xs text-on-warning-container">
                <span className="material-symbols-outlined text-headline-md text-warning">
                  gavel
                </span>
                <h3 className="font-label text-label-sm uppercase">AUDITOR ESCALATION REASON</h3>
              </header>
              <p className="font-body text-body-sm text-on-warning-container">
                {dossier.auditor_escalation_reason || 'Escalada manual pelo atendente N1.'}
              </p>
            </article>

            <article className="rounded-md bg-light-surface border border-light-outline-variant p-lg flex flex-col gap-md">
              <header className="flex items-center gap-xs">
                <span className="material-symbols-outlined text-body-md text-light-primary">
                  menu_book
                </span>
                <h3 className="font-label text-label-sm uppercase text-light-outline">
                  SOURCES USED
                </h3>
              </header>
              <div className="flex flex-col gap-sm">
                <div className="flex justify-between">
                  <span className="font-body text-body-sm text-light-on-surface-variant">Category</span>
                  <span className="px-sm py-xs rounded-sm bg-light-surface-container font-label text-label-sm">
                    {dossier.categoria_atual || '—'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="font-body text-body-sm text-light-on-surface-variant">
                    Manual Chunk ID
                  </span>
                  <span className="px-sm py-xs rounded-sm bg-light-tertiary-container text-light-on-tertiary-container font-mono text-mono-sm">
                    {dossier.last_chunk_id || '—'}
                  </span>
                </div>
              </div>
            </article>

            <article className="rounded-md bg-light-surface border border-light-outline-variant p-lg flex flex-col gap-md">
              <header className="flex items-center gap-xs">
                <span className="material-symbols-outlined text-body-md text-light-primary">
                  badge
                </span>
                <h3 className="font-label text-label-sm uppercase text-light-outline">
                  CUSTOMER DETAILS
                </h3>
              </header>
              <div className="flex justify-between">
                <span className="font-body text-body-sm text-light-on-surface-variant">Name</span>
                <span className="font-title text-title-sm">{dossier.customer_name || '—'}</span>
              </div>
            </article>
          </div>
        )}
      </aside>
    </div>
  );
}