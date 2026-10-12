import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '../store/auth';
import { adminGetStats, adminListSimulations, adminListUsers, adminUpdateUserRole } from '../services/admin';
import { AppSelect } from '../components/AppSelect';
import { TitleCard } from '../components/TitleCard';
import { BarChartIcon, CaretUpIcon, CaretDownIcon } from '@radix-ui/react-icons';
import { ResponsiveContainer, LineChart as RLineChart, Line, XAxis, YAxis, Tooltip } from 'recharts';

export function AdminPage() {
  const { t } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const isAdmin = String((user as any)?.role || '') === 'admin';
  const [tab, setTab] = useState<'overview' | 'users' | 'sims'>('overview');

  if (!isAdmin) {
    return (
      <div className="panel">
        <div className="panel-title">{t('admin.title')}</div>
        <div className="card" style={{ color: 'var(--ss-error-400)' }}>{t('admin.noAccess')}</div>
      </div>
    );
  }

  return (
    <div className="scroll-panel" style={{ height: '100%', overflow: 'auto' }}>
      <TitleCard title={t('admin.title')} />
      <div className="tab-layout">
        <nav className="tab-nav">
          <button type="button" className={`tab-button ${tab === 'overview' ? 'active' : ''}`} onClick={() => setTab('overview')}>
            {t('admin.stats.title')}
          </button>
          <button type="button" className={`tab-button ${tab === 'users' ? 'active' : ''}`} onClick={() => setTab('users')}>
            {t('admin.users.title')}
          </button>
          <button type="button" className={`tab-button ${tab === 'sims' ? 'active' : ''}`} onClick={() => setTab('sims')}>
            {t('admin.sims.title')}
          </button>
        </nav>
        <section style={{ display: 'grid', gap: 'var(--ss-space-3)' }}>
          {tab === 'overview' && <StatsCard />}
          {tab === 'users' && <UsersCard />}
          {tab === 'sims' && <SimulationsCard />}
        </section>
      </div>
    </div>
  );
}

function UsersCard() {
  const { t } = useTranslation();
  const [q, setQ] = useState('');
  const [org, setOrg] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [sort, setSort] = useState('created_desc');

  const query = useQuery({
    queryKey: ['admin-users', q, org, from, to, sort],
    queryFn: () => adminListUsers({ q, org, created_from: from, created_to: to, sort }),
  });

  return (
    <div className="card" style={{ display: 'grid', gap: 'var(--ss-space-2)' }}>
      <div className="panel-subtitle">{t('admin.users.title')}</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 'var(--ss-space-2)' }}>
        <label style={{ display: 'grid', gap: 4 }}>
          {t('admin.users.name')}
          <input className="input small" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <label style={{ display: 'grid', gap: 4 }}>
          {t('admin.users.organization')}
          <input className="input small" value={org} onChange={(e) => setOrg(e.target.value)} />
        </label>
        <label style={{ display: 'grid', gap: 4 }}>
          {t('admin.common.from')}
          <input className="input small" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label style={{ display: 'grid', gap: 4 }}>
          {t('admin.common.to')}
          <input className="input small" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
      </div>
      <div className="card" style={{ padding: 0 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr 1fr 1fr 0.8fr 0.8fr', gap: 'var(--ss-gap-xs)', padding: 'var(--ss-space-2) var(--ss-gap-lg)', color: 'var(--muted)', fontSize: 'var(--ss-type-sm)', borderBottom: '1px solid var(--border)' }}>
          <div style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }} onClick={() => setSort(sort === 'name_asc' ? 'name_desc' : 'name_asc')}>
            {t('admin.users.columns.name')} {sort.startsWith('name_') ? (sort.endsWith('asc') ? <CaretUpIcon /> : <CaretDownIcon />) : null}
          </div>
          <div>{t('admin.users.columns.email')}</div>
          <div style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }} onClick={() => setSort(sort === 'org_asc' ? 'org_desc' : 'org_asc')}>
            {t('admin.users.columns.organization')} {sort.startsWith('org_') ? (sort.endsWith('asc') ? <CaretUpIcon /> : <CaretDownIcon />) : null}
          </div>
          <div style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }} onClick={() => setSort(sort === 'created_asc' ? 'created_desc' : 'created_asc')}>
            {t('admin.users.columns.created')} {sort.startsWith('created_') ? (sort.endsWith('asc') ? <CaretUpIcon /> : <CaretDownIcon />) : null}
          </div>
          <div>{t('admin.users.columns.status')}</div>
          <div>{t('admin.users.columns.role') || 'Role'}</div>
        </div>
        <div>
          {(query.data || []).map((u, idx, arr) => (
            <div key={u.id} style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr 1fr 1fr 0.8fr 0.8fr', gap: 'var(--ss-gap-xs)', padding: 'var(--ss-space-2) var(--ss-gap-lg)', borderBottom: idx === arr.length - 1 ? 'none' : '1px solid var(--border)' }}>
              <div style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{u.full_name || u.username}</div>
              <div style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{u.email}</div>
              <div style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{u.organization || '-'}</div>
              <div>{new Date(u.created_at).toLocaleString()}</div>
              <div>{u.is_active ? t('admin.common.active') : t('admin.common.disabled')}</div>
              <div>
                <AppSelect
                  value={String((u as any).role || 'user')}
                  size="small"
                  options={[{ value: 'user', label: 'user' }, { value: 'admin', label: 'admin' }]}
                  onChange={async (val) => {
                    await adminUpdateUserRole(u.id, val as 'user' | 'admin');
                    query.refetch();
                  }}
                />
              </div>
            </div>
          ))}
          {query.isLoading && <div style={{ padding: 'var(--ss-space-2) var(--ss-gap-lg)', color: 'var(--muted)' }}>{t('common.loading')}</div>}
          {query.error && <div style={{ padding: 'var(--ss-space-2) var(--ss-gap-lg)', color: 'var(--ss-error-400)' }}>{t('admin.common.fetchError')}</div>}
        </div>
      </div>
    </div>
  );
}

function SimulationsCard() {
  const { t } = useTranslation();
  const [userQ, setUserQ] = useState('');
  const [scene, setScene] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [sort, setSort] = useState('created_desc');
  const query = useQuery({
    queryKey: ['admin-sims', userQ, scene, from, to, sort],
    queryFn: () => adminListSimulations({ user: userQ, scene_type: scene, created_from: from, created_to: to, sort }),
  });

  return (
    <div className="card" style={{ display: 'grid', gap: 'var(--ss-space-2)' }}>
      <div className="panel-subtitle">{t('admin.sims.title')}</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 'var(--ss-space-2)' }}>
        <label style={{ display: 'grid', gap: 4 }}>
          {t('admin.sims.username')}
          <input className="input small" value={userQ} onChange={(e) => setUserQ(e.target.value)} />
        </label>
        <label style={{ display: 'grid', gap: 4 }}>
          {t('admin.sims.scene')}
          <input className="input small" value={scene} onChange={(e) => setScene(e.target.value)} />
        </label>
        <label style={{ display: 'grid', gap: 4 }}>
          {t('admin.common.from')}
          <input className="input small" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label style={{ display: 'grid', gap: 4 }}>
          {t('admin.common.to')}
          <input className="input small" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
      </div>
      <div className="card" style={{ padding: 0 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 'var(--ss-gap-xs)', padding: 'var(--ss-space-2) var(--ss-gap-lg)', color: 'var(--muted)', fontSize: 'var(--ss-type-sm)', borderBottom: '1px solid var(--border)' }}>
          <div style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }} onClick={() => setSort(sort === 'username_asc' ? 'username_desc' : 'username_asc')}>
            {t('admin.sims.columns.user')} {sort.startsWith('username_') ? (sort.endsWith('asc') ? <CaretUpIcon /> : <CaretDownIcon />) : null}
          </div>
          <div>{t('admin.sims.columns.name')}</div>
          <div style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }} onClick={() => setSort(sort === 'scene_asc' ? 'scene_desc' : 'scene_asc')}>
            {t('admin.sims.columns.scene')} {sort.startsWith('scene_') ? (sort.endsWith('asc') ? <CaretUpIcon /> : <CaretDownIcon />) : null}
          </div>
          <div style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }} onClick={() => setSort(sort === 'created_asc' ? 'created_desc' : 'created_asc')}>
            {t('admin.sims.columns.created')} {sort.startsWith('created_') ? (sort.endsWith('asc') ? <CaretUpIcon /> : <CaretDownIcon />) : null}
          </div>
        </div>
        <div>
          {(query.data || []).map((s, idx, arr) => (
            <div key={s.id} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 'var(--ss-gap-xs)', padding: 'var(--ss-space-2) var(--ss-gap-lg)', borderBottom: idx === arr.length - 1 ? 'none' : '1px solid var(--border)' }}>
              <div>{s.owner_username || s.owner_id}</div>
              <div style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.name}</div>
              <div>{s.scene_type}</div>
              <div>{new Date(s.created_at).toLocaleString()}</div>
            </div>
          ))}
          {query.isLoading && <div style={{ padding: 'var(--ss-space-2) var(--ss-gap-lg)', color: 'var(--muted)' }}>{t('common.loading')}</div>}
          {query.error && <div style={{ padding: 'var(--ss-space-2) var(--ss-gap-lg)', color: 'var(--ss-error-400)' }}>{t('admin.common.fetchError')}</div>}
        </div>
      </div>
    </div>
  );
}

function StatsCard() {
  const { t } = useTranslation();
  const [period, setPeriod] = useState<'day' | 'week' | 'month'>('day');
  const query = useQuery({ queryKey: ['admin-stats', period], queryFn: () => adminGetStats(period) });
  const stats = query.data;
  const toTotal = (arr?: { date: string; count: number }[]) => (arr || []).reduce((a, b) => a + Number(b.count || 0), 0);

  return (
    <div className="card" style={{ display: 'grid', gap: 'var(--ss-space-2)' }}>
      <div className="panel-subtitle" style={{ display: 'flex', alignItems: 'center', gap: 'var(--ss-gap-sm)' }}>
        <BarChartIcon /> {t('admin.stats.title')}
      </div>
      <div style={{ display: 'flex', gap: 'var(--ss-space-2)', alignItems: 'center', flexWrap: 'nowrap' }}>
        <span style={{ color: 'var(--muted)', fontSize: 'var(--ss-type-md)', whiteSpace: 'nowrap' }}>{t('admin.stats.period')}</span>
        <AppSelect
          value={period}
          onChange={(v) => setPeriod(v as any)}
          size="small"
          options={[
            { value: 'day', label: t('admin.stats.day') },
            { value: 'week', label: t('admin.stats.week') },
            { value: 'month', label: t('admin.stats.month') },
          ]}
        />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 'var(--ss-space-2)' }}>
        <div className="card" style={{ padding: 'var(--ss-gap-lg)', gap: 'var(--ss-gap-xs)' }}>
          <div style={{ color: 'var(--muted)', fontSize: 'var(--ss-type-sm)' }}>{t('admin.stats.simRuns')}</div>
          <div style={{ fontSize: 'var(--ss-type-subtitle)', fontWeight: 700 }}>{toTotal(stats?.sim_runs)}</div>
          <LineChart series={stats?.sim_runs || []} color="var(--accent-b)" />
        </div>
        <div className="card" style={{ padding: 'var(--ss-gap-lg)', gap: 'var(--ss-gap-xs)' }}>
          <div style={{ color: 'var(--muted)', fontSize: 'var(--ss-type-sm)' }}>{t('admin.stats.userVisits')}</div>
          <div style={{ fontSize: 'var(--ss-type-subtitle)', fontWeight: 700 }}>{toTotal(stats?.user_visits)}</div>
          <LineChart series={stats?.user_visits || []} color="var(--ss-success-400)" />
        </div>
        <div className="card" style={{ padding: 'var(--ss-gap-lg)', gap: 'var(--ss-gap-xs)' }}>
          <div style={{ color: 'var(--muted)', fontSize: 'var(--ss-type-sm)' }}>{t('admin.stats.userSignups')}</div>
          <div style={{ fontSize: 'var(--ss-type-subtitle)', fontWeight: 700 }}>{toTotal(stats?.user_signups)}</div>
          <LineChart series={stats?.user_signups || []} color="var(--ss-warning-600)" />
        </div>
      </div>
      {query.isLoading && <div style={{ color: 'var(--muted)' }}>{t('common.loading')}</div>}
      {query.error && <div style={{ color: 'var(--ss-error-400)' }}>{t('admin.common.fetchError')}</div>}
    </div>
  );
}

function LineChart({ series, color }: { series: { date: string; count: number }[]; color: string }) {
  const data = (series || []).map((s) => ({ date: s.date, value: Number(s.count || 0) }));
  return (
    <div style={{ width: '100%', height: 80 }}>
      <ResponsiveContainer width="100%" height="100%">
        <RLineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <XAxis dataKey="date" hide tick={false} axisLine={false} tickLine={false} />
          <YAxis hide tick={false} axisLine={false} tickLine={false} domain={["dataMin", "dataMax"]} />
          <Tooltip
            contentStyle={{
              fontSize: 12,
              background: 'var(--overlay-bg)',
              color: 'var(--text)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              padding: '6px 8px',
            }}
            labelStyle={{ color: 'var(--muted)' }}
            itemStyle={{ color: 'var(--text)' }}
            formatter={(v: any) => [String(v), '']}
            labelFormatter={(l) => l}
          />
          <Line type="monotone" dataKey="value" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
        </RLineChart>
      </ResponsiveContainer>
    </div>
  );
}
