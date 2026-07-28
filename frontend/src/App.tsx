import { useMemo, useState } from 'react';
import clsx from 'clsx';
import { Activity, BarChart3, Radio, ScanEye, Settings2, Waypoints } from 'lucide-react';

import { useTrafficSocket } from './hooks/useTrafficSocket';
import { LiveView } from './views/LiveView';
import { DetectionView } from './views/DetectionView';
import { InsightsView } from './views/InsightsView';
import { CorridorView } from './views/CorridorView';
import { SystemView } from './views/SystemView';

const TABS = [
  { id: 'live', label: 'Live control', icon: Activity },
  { id: 'detection', label: 'Detection', icon: ScanEye },
  { id: 'insights', label: 'Insights', icon: BarChart3 },
  { id: 'corridor', label: 'Corridor', icon: Waypoints },
  { id: 'system', label: 'System', icon: Settings2 },
] as const;

type TabId = (typeof TABS)[number]['id'];

const CONNECTION_LABELS = {
  open: { text: 'Live', className: 'bg-green-500/15 text-green-400' },
  connecting: { text: 'Connecting', className: 'bg-amber-500/15 text-amber-400' },
  closed: { text: 'Reconnecting', className: 'bg-red-500/15 text-red-400' },
} as const;

export default function App() {
  const [activeTab, setActiveTab] = useState<TabId>('live');
  const [intersectionId, setIntersectionId] = useState('main_intersection');

  const { connectionState, statuses, events } = useTrafficSocket();
  const status = useMemo(
    () => statuses[intersectionId] ?? null,
    [statuses, intersectionId],
  );

  const connection = CONNECTION_LABELS[connectionState];

  return (
    <div className="min-h-full bg-slate-950">
      <header className="sticky top-0 z-10 border-b border-slate-800 bg-slate-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-4 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex flex-col gap-0.5 rounded-md border border-slate-700 bg-slate-900 p-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
              <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
            </div>
            <div>
              <h1 className="text-lg leading-tight font-semibold text-slate-50">
                AI Traffic Management
              </h1>
              <p className="text-xs text-slate-500">
                Adaptive signal control · {intersectionId}
              </p>
            </div>
          </div>

          <div
            className={clsx('badge', connection.className)}
            role="status"
            aria-live="polite"
          >
            <Radio size={12} className={connectionState === 'open' ? 'animate-pulse' : undefined} />
            {connection.text}
          </div>
        </div>

        <nav className="mx-auto max-w-7xl px-4 sm:px-6" aria-label="Sections">
          <ul className="flex gap-1 overflow-x-auto">
            {TABS.map(({ id, label, icon: Icon }) => (
              <li key={id}>
                <button
                  type="button"
                  onClick={() => setActiveTab(id)}
                  aria-current={activeTab === id ? 'page' : undefined}
                  className={clsx(
                    'flex items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium whitespace-nowrap transition-colors',
                    activeTab === id
                      ? 'border-sky-500 text-sky-400'
                      : 'border-transparent text-slate-400 hover:border-slate-700 hover:text-slate-200',
                  )}
                >
                  <Icon size={15} />
                  {label}
                </button>
              </li>
            ))}
          </ul>
        </nav>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        {activeTab === 'live' && (
          <LiveView intersectionId={intersectionId} status={status} events={events} />
        )}
        {activeTab === 'detection' && <DetectionView intersectionId={intersectionId} />}
        {activeTab === 'insights' && <InsightsView intersectionId={intersectionId} />}
        {activeTab === 'corridor' && (
          <CorridorView selectedId={intersectionId} onSelect={setIntersectionId} />
        )}
        {activeTab === 'system' && <SystemView intersectionId={intersectionId} />}
      </main>

      <footer className="mx-auto max-w-7xl px-4 py-8 text-xs text-slate-600 sm:px-6">
        Impact figures are modelled estimates, not measurements. Re-base the assumptions on local
        data before using them in a business case.
      </footer>
    </div>
  );
}
