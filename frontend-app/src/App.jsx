import { useState } from 'react';
import AgentView from './components/AgentView';
import ClientView from './components/ClientView';
import SpecialistView from './components/SpecialistView';

function getInitialRole() {
  const param = new URLSearchParams(window.location.search).get('role');
  if (param === 'client' || param === 'agent' || param === 'specialist') return param;
  return 'agent';
}

export default function App() {
  const [role, setRole] = useState(getInitialRole);

  const switchRole = (nextRole) => {
    setRole(nextRole);
    const url = new URL(window.location.href);
    url.searchParams.set('role', nextRole);
    window.history.replaceState({}, '', url);
  };

  return (
    <div className="min-h-screen flex flex-col bg-light-background">
      {/* Barra superior discreta para alternar entre as 3 visões ou abrir em abas */}
      <div className="h-12 px-lg bg-light-tertiary text-light-on-tertiary flex items-center justify-between gap-md">
        <div className="flex items-center gap-sm">
          <span className="font-headline text-headline-sm">NexusTech</span>
          <span className="text-light-outline text-label-sm">Support Copilot</span>
        </div>

        <div className="flex items-center gap-xs">
          {[
            { id: 'client', label: 'Cliente' },
            { id: 'agent', label: 'Atendente N1' },
            { id: 'specialist', label: 'Especialista N2/N3' },
          ].map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => switchRole(item.id)}
              className={`px-md py-xs rounded font-label text-label-md transition-colors ${
                role === item.id
                  ? 'bg-light-primary text-light-on-primary'
                  : 'text-slate-300 hover:text-white'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {role === 'client' && <ClientView />}
      {role === 'agent' && <AgentView />}
      {role === 'specialist' && <SpecialistView />}
    </div>
  );
}