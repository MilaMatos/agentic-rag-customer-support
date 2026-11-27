import { useEffect, useRef, useState } from 'react';
import { api, DEFAULT_TENANT, formatTime, getInitials } from '../services/api';

export default function ClientView() {
  const [customerName, setCustomerName] = useState('');
  const [session, setSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [status, setStatus] = useState('');
  const [typingLabel, setTypingLabel] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');

  const wsRef = useRef(null);
  const typingTimerRef = useRef(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, typingLabel]);

  useEffect(() => {
    if (!session?.session_id) return;

    const ws = new WebSocket(api.wsClientUrl(session.session_id, DEFAULT_TENANT));
    wsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        const { type, data } = msg;

        if (type === 'agent.message_sent' || type === 'specialist.message_sent') {
          setTypingLabel('');
          setMessages((prev) => {
            if (prev.some((m) => m.message_id === data.message_id)) return prev;
            return [...prev, data];
          });
        } else if (type === 'session.escalated') {
          setStatus('ESCALADA_N2');
          setTypingLabel('');
          if (data.system_notice) {
            setMessages((prev) => [
              ...prev,
              {
                message_id: `sys-${Date.now()}`,
                sender_role: 'SYSTEM',
                content: data.system_notice,
                created_at: new Date().toISOString(),
              },
            ]);
          }
        } else if (type === 'session.closed') {
          setStatus('ENCERRADA');
          setTypingLabel('');
        } else if (type === 'agent.typing') {
          setTypingLabel(data.is_typing ? 'Atendente N1 está digitando...' : '');
        } else if (type === 'specialist.typing') {
          setTypingLabel(data.is_typing ? 'Especialista N2 está digitando...' : '');
        }
      } catch {
        // ignora payload inválido
      }
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [session?.session_id]);

  const sendTyping = (isTyping) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'typing', is_typing: isTyping }));
    }
  };

  const handleStart = async (e) => {
    e.preventDefault();
    if (!customerName.trim()) return;
    setError('');
    try {
      const created = await api.createSession(customerName.trim());
      setSession(created);
      setStatus(created.status);
      setMessages([]);
    } catch (err) {
      setError(err.message);
    }
  };

  const handleSend = async (e) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || !session || status === 'ENCERRADA' || sending) return;

    setSending(true);
    setError('');
    sendTyping(false);
    setInput('');

    try {
      const res = await api.sendClientMessage(session.session_id, text);
      setMessages((prev) => [
        ...prev,
        {
          message_id: res.message_id,
          sender_role: 'CLIENT',
          content: text,
          created_at: res.created_at,
        },
      ]);
    } catch (err) {
      setError(err.message);
      setInput(text);
    } finally {
      setSending(false);
    }
  };

  const handleClientClose = async () => {
    if (!session || status === 'ENCERRADA') return;
    try {
      await api.closeByClient(session.session_id);
      setStatus('ENCERRADA');
    } catch (err) {
      setError(err.message);
    }
  };

  if (!session) {
    return (
      <div className="min-h-[calc(100vh-48px)] flex items-center justify-center bg-light-background p-lg">
        <form
          onSubmit={handleStart}
          className="w-full max-w-md rounded-lg bg-light-surface border border-light-outline-variant p-xl flex flex-col gap-lg shadow-sm"
        >
          <div className="flex items-center gap-md">
            <div className="w-10 h-10 rounded bg-light-primary text-light-on-primary flex items-center justify-center">
              <span className="material-symbols-outlined">support_agent</span>
            </div>
            <div>
              <h1 className="font-headline text-headline-md text-light-on-surface">NexusTech Support</h1>
              <p className="font-body text-body-sm text-light-on-surface-variant">
                Inicie um atendimento em tempo real
              </p>
            </div>
          </div>

          <div className="flex flex-col gap-xs">
            <label htmlFor="client-name" className="font-label text-label-md text-light-on-surface">
              Seu nome
            </label>
            <input
              id="client-name"
              type="text"
              required
              value={customerName}
              onChange={(e) => setCustomerName(e.target.value)}
              placeholder="Ex: Maria Silva"
              className="w-full rounded bg-light-surface border border-light-outline-variant px-md py-sm font-body text-body-md text-light-on-surface focus:border-light-primary focus:ring-1 focus:ring-light-primary focus:outline-none"
            />
          </div>

          {error && <p className="font-body text-body-sm text-light-error">{error}</p>}

          <button
            type="submit"
            className="inline-flex items-center justify-center gap-xs px-lg py-sm rounded bg-light-primary text-light-on-primary hover:bg-light-primary-container font-label text-label-lg transition-colors duration-state-change"
          >
            <span className="material-symbols-outlined text-body-md">chat</span>
            Iniciar Atendimento
          </button>
        </form>
      </div>
    );
  }

  const isClosed = status === 'ENCERRADA';

  return (
    <div className="h-[calc(100vh-48px)] bg-light-background flex items-center justify-center p-md">
      <div className="w-full max-w-3xl h-full rounded-lg bg-light-surface border border-light-outline-variant flex flex-col overflow-hidden shadow-sm">
        {/* Header */}
        <header className="px-xl py-md border-b border-light-outline-variant flex items-center justify-between gap-md">
          <div className="flex items-center gap-md">
            <div className="w-9 h-9 rounded-full bg-light-tertiary-container text-light-on-tertiary-container flex items-center justify-center font-title text-title-sm">
              {getInitials(session.customer_name)}
            </div>
            <div>
              <div className="flex items-center gap-sm">
                <h2 className="font-headline text-headline-md text-light-on-surface">
                  Suporte NexusTech
                </h2>
                <span
                  className={`inline-flex items-center px-sm py-xs rounded-full font-label text-label-sm ${
                    status === 'ESCALADA_N2'
                      ? 'bg-warning-container text-on-warning-container'
                      : isClosed
                      ? 'bg-light-surface-container text-light-on-surface-variant'
                      : 'bg-light-tertiary-container text-light-on-tertiary-container'
                  }`}
                >
                  {status === 'ESCALADA_N2'
                    ? 'Com Especialista N2'
                    : isClosed
                    ? 'Encerrada'
                    : 'Em Atendimento'}
                </span>
              </div>
              <p className="font-body text-body-sm text-light-on-surface-variant">
                Cliente: {session.customer_name} · Sessão{' '}
                <span className="font-mono text-mono-sm">{session.session_id.slice(0, 8)}</span>
              </p>
            </div>
          </div>

          {!isClosed && (
            <button
              type="button"
              onClick={handleClientClose}
              className="inline-flex items-center gap-xs px-md py-sm rounded border border-light-outline-variant text-light-on-surface hover:bg-light-surface-container font-label text-label-md transition-colors"
            >
              <span className="material-symbols-outlined text-body-md">close</span>
              Encerrar Chat
            </button>
          )}
        </header>

        {/* Thread */}
        <section className="flex-1 overflow-y-auto px-xl py-lg flex flex-col gap-md">
          {messages.length === 0 && (
            <div className="m-auto text-center text-light-on-surface-variant">
              <p className="font-body text-body-md">Envie sua dúvida abaixo para começar.</p>
            </div>
          )}

          {messages.map((m) => {
            if (m.sender_role === 'SYSTEM') {
              return (
                <div
                  key={m.message_id}
                  className="self-center px-lg py-sm rounded-full bg-warning-container text-on-warning-container font-label text-label-md text-center"
                >
                  {m.content}
                </div>
              );
            }
            const isClient = m.sender_role === 'CLIENT';
            const isSpecialist = m.sender_role === 'SPECIALIST_N2';
            return (
              <div
                key={m.message_id}
                className={`flex flex-col gap-xs max-w-prose ${
                  isClient ? 'items-end self-end' : 'items-start self-start'
                }`}
              >
                <div className="flex items-center gap-sm">
                  <span className="font-label text-label-md text-light-on-surface-variant">
                    {isClient ? 'Você' : isSpecialist ? 'Especialista N2' : 'Atendente N1'}
                  </span>
                  <span className="font-label text-label-sm text-light-outline tabular-nums">
                    {formatTime(m.created_at)}
                  </span>
                </div>
                <div
                  className={`rounded-md px-lg py-md font-body text-body-md whitespace-pre-wrap ${
                    isClient
                      ? 'bg-light-primary text-light-on-primary'
                      : isSpecialist
                      ? 'bg-light-tertiary-container text-light-on-tertiary-container border border-light-primary'
                      : 'bg-slate-bubble text-on-slate-bubble'
                  }`}
                >
                  {m.content}
                </div>
              </div>
            );
          })}

          {typingLabel && (
            <div className="flex items-center gap-sm text-light-on-surface-variant">
              <div className="inline-flex items-center gap-xs px-md py-sm rounded-md bg-slate-bubble">
                <span className="w-1.5 h-1.5 rounded-full bg-light-outline typing-dot-1" />
                <span className="w-1.5 h-1.5 rounded-full bg-light-outline typing-dot-2" />
                <span className="w-1.5 h-1.5 rounded-full bg-light-outline typing-dot-3" />
              </div>
              <span className="font-body text-body-sm text-light-outline">{typingLabel}</span>
            </div>
          )}
          <div ref={bottomRef} />
        </section>

        {/* Composer */}
        <footer className="px-xl py-md border-t border-light-outline-variant bg-light-surface">
          {error && <p className="mb-sm font-body text-body-sm text-light-error">{error}</p>}
          {isClosed ? (
            <div className="p-md rounded bg-light-surface-container text-center font-body text-body-sm text-light-on-surface-variant">
              Esta conversa foi encerrada. Recarregue a página para iniciar um novo atendimento.
            </div>
          ) : (
            <form onSubmit={handleSend} className="flex items-center gap-sm">
              <input
                type="text"
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
                  sendTyping(true);
                  clearTimeout(typingTimerRef.current);
                  typingTimerRef.current = setTimeout(() => sendTyping(false), 1800);
                }}
                placeholder="Digite sua mensagem..."
                className="flex-1 rounded bg-light-surface border border-light-outline-variant px-md py-sm font-body text-body-md text-light-on-surface focus:border-light-primary focus:ring-1 focus:ring-light-primary focus:outline-none"
              />
              <button
                type="submit"
                disabled={sending || !input.trim()}
                className="inline-flex items-center gap-xs px-lg py-sm rounded bg-light-primary text-light-on-primary hover:bg-light-primary-container disabled:opacity-50 font-label text-label-lg transition-colors"
              >
                <span className="material-symbols-outlined text-body-md">send</span>
                Enviar
              </button>
            </form>
          )}
        </footer>
      </div>
    </div>
  );
}