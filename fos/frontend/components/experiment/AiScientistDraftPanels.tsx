/**
 * This file holds reusable editor panels for AI scientist draft data.
 *
 * What this file does:
 * - renders scenario settings editor,
 * - renders action editor with selection toggle,
 * - renders agent editor with selection toggle and count.
 */
import { Check, Plus, X } from 'lucide-react';
import type { ReactNode } from 'react';

import { Card } from '../ui/card';
import { Button } from '../ui/button';

export interface DraftItem {
  id: string;
  label: string;
  description: string;
  selected: boolean;
  count?: number;
}

export interface SettingDraft {
  id: string;
  key: string;
  value: string;
  reason: string;
}

interface SharedPanelProps {
  textColor: string;
  helperText?: string;
  headerAction?: ReactNode;
}

interface SettingsPanelProps extends SharedPanelProps {
  t: (key: string) => string;
  settingsDrafts: SettingDraft[];
  onAddSetting: () => void;
  onUpdateSetting: (id: string, updates: Partial<SettingDraft>) => void;
  onRemoveSetting: (id: string) => void;
}

interface ActionsPanelProps extends SharedPanelProps {
  t: (key: string) => string;
  actionDrafts: DraftItem[];
  onAddAction: () => void;
  onUpdateAction: (id: string, updates: Partial<DraftItem>) => void;
  onRemoveAction: (id: string) => void;
}

interface AgentsPanelProps extends SharedPanelProps {
  t: (key: string) => string;
  agentDrafts: DraftItem[];
  onAddAgent: () => void;
  onUpdateAgent: (id: string, updates: Partial<DraftItem>) => void;
  onRemoveAgent: (id: string) => void;
}

export function SettingsDraftPanel({
  t,
  textColor,
  helperText,
  headerAction,
  settingsDrafts,
  onAddSetting,
  onUpdateSetting,
  onRemoveSetting,
}: SettingsPanelProps) {
  return (
    <Card className="p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold" style={{ color: textColor }}>
            {t('createExperiment.customBuilder.settingsTitle')}
          </h2>
          <p className="text-sm" style={{ color: 'var(--ss-text)' }}>
            {t('createExperiment.customBuilder.settingsSubtitle')}
          </p>
          {helperText ? (
            <p className="mt-1 text-xs leading-5" style={{ color: 'var(--ss-text-muted)' }}>
              {helperText}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {headerAction}
          <Button variant="outline" onClick={onAddSetting}>
            <Plus size={16} />
            {t('createExperiment.customBuilder.addSetting')}
          </Button>
        </div>
      </div>

      <div className="space-y-3">
        {settingsDrafts.length > 0 ? settingsDrafts.map((draft) => (
          <div key={draft.id} className="rounded-xl border p-3" style={{ borderColor: 'var(--ss-border-strong)', background: 'var(--ss-page-surface)' }}>
            <div className="grid gap-2 md:grid-cols-[1fr_1fr_auto]">
              <input
                value={draft.key}
                onChange={(event) => onUpdateSetting(draft.id, { key: event.target.value })}
                className="rounded-lg border px-3 py-2 text-sm outline-none"
                style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-page-surface)', color: 'var(--ss-text)' }}
                placeholder={t('createExperiment.customBuilder.settingKeyPlaceholder')}
              />
              <input
                value={draft.value}
                onChange={(event) => onUpdateSetting(draft.id, { value: event.target.value })}
                className="rounded-lg border px-3 py-2 text-sm outline-none"
                style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-page-surface)', color: 'var(--ss-text)' }}
                placeholder={t('createExperiment.customBuilder.settingValuePlaceholder')}
              />
              <button
                type="button"
                className="text-slate-400 transition hover:text-slate-700"
                onClick={() => onRemoveSetting(draft.id)}
                aria-label={t('common.remove')}
              >
                <X size={16} />
              </button>
            </div>
            <textarea
              value={draft.reason}
              onChange={(event) => onUpdateSetting(draft.id, { reason: event.target.value })}
              rows={2}
              className="mt-2 w-full rounded-lg border px-3 py-2 text-sm outline-none"
              style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-page-surface)', color: 'var(--ss-text)' }}
              placeholder={t('createExperiment.customBuilder.settingReasonPlaceholder')}
            />
          </div>
        )) : (
          <div className="rounded-xl border border-dashed p-4 text-sm" style={{ borderColor: 'var(--ss-border-strong)', color: 'var(--ss-text-muted)' }}>
            {t('createExperiment.customBuilder.noSettings')}
          </div>
        )}
      </div>
    </Card>
  );
}

export function ActionsDraftPanel({
  t,
  textColor,
  helperText,
  headerAction,
  actionDrafts,
  onAddAction,
  onUpdateAction,
  onRemoveAction,
}: ActionsPanelProps) {
  return (
    <Card className="p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold" style={{ color: textColor }}>
            {t('createExperiment.customBuilder.actionsTitle')}
          </h2>
          {helperText ? (
            <p className="mt-1 text-xs leading-5" style={{ color: 'var(--ss-text-muted)' }}>
              {helperText}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {headerAction}
          <Button variant="outline" onClick={onAddAction}>
            <Plus size={16} />
            {t('createExperiment.customBuilder.addAction')}
          </Button>
        </div>
      </div>

      <div className="space-y-3">
        {actionDrafts.length > 0 ? actionDrafts.map((draft) => (
          <div key={draft.id} className="rounded-xl border p-3" style={{ borderColor: 'var(--ss-border-strong)', background: draft.selected ? 'var(--ss-accent-warm-soft)' : 'var(--ss-page-surface)' }}>
            <div className="grid gap-3 md:grid-cols-[auto_minmax(0,1fr)_auto] md:items-start">
              <button
                type="button"
                className="mt-1 inline-flex h-5 w-5 items-center justify-center rounded-full border"
                style={{ borderColor: 'var(--ss-border-strong)', background: draft.selected ? 'var(--ss-brand-primary)' : 'var(--ss-page-surface)' }}
                onClick={() => onUpdateAction(draft.id, { selected: !draft.selected })}
                aria-label={t('createExperiment.customBuilder.toggleSelection')}
              >
                {draft.selected && <Check size={12} className="text-white" />}
              </button>
              <div className="min-w-0 flex-1 space-y-2">
                <input
                  value={draft.label}
                  onChange={(event) => onUpdateAction(draft.id, { label: event.target.value })}
                  className="w-full rounded-lg border px-3 py-2 text-sm outline-none"
                  style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-page-surface)', color: 'var(--ss-text)' }}
                />
                <textarea
                  value={draft.description}
                  onChange={(event) => onUpdateAction(draft.id, { description: event.target.value })}
                  rows={2}
                  className="w-full rounded-lg border px-3 py-2 text-sm outline-none"
                  style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-page-surface)', color: 'var(--ss-text)' }}
                  placeholder={t('createExperiment.customBuilder.actionDescriptionPlaceholder')}
                />
              </div>
              <button
                type="button"
                className="justify-self-end text-slate-400 transition hover:text-slate-700"
                onClick={() => onRemoveAction(draft.id)}
                aria-label={t('common.remove')}
              >
                <X size={16} />
              </button>
            </div>
          </div>
        )) : (
          <div className="rounded-xl border border-dashed p-4 text-sm" style={{ borderColor: 'var(--ss-border-strong)', color: 'var(--ss-text-muted)' }}>
            {t('createExperiment.customBuilder.noActions')}
          </div>
        )}
      </div>
    </Card>
  );
}

export function AgentsDraftPanel({
  t,
  textColor,
  helperText,
  headerAction,
  agentDrafts,
  onAddAgent,
  onUpdateAgent,
  onRemoveAgent,
}: AgentsPanelProps) {
  return (
    <Card className="p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold" style={{ color: textColor }}>
            {t('createExperiment.customBuilder.agentsTitle')}
          </h2>
          {helperText ? (
            <p className="mt-1 text-xs leading-5" style={{ color: 'var(--ss-text-muted)' }}>
              {helperText}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {headerAction}
          <Button variant="outline" onClick={onAddAgent}>
            <Plus size={16} />
            {t('createExperiment.customBuilder.addAgent')}
          </Button>
        </div>
      </div>

      <div className="space-y-3">
        {agentDrafts.length > 0 ? agentDrafts.map((draft) => (
          <div key={draft.id} className="rounded-xl border p-3" style={{ borderColor: 'var(--ss-border-strong)', background: draft.selected ? 'var(--ss-accent-warm-soft)' : 'var(--ss-page-surface)' }}>
            <div className="grid gap-3 md:grid-cols-[auto_minmax(0,1fr)_104px_auto] md:items-start">
              <button
                type="button"
                className="mt-1 inline-flex h-5 w-5 items-center justify-center rounded-full border"
                style={{ borderColor: 'var(--ss-border-strong)', background: draft.selected ? 'var(--ss-brand-primary)' : 'var(--ss-page-surface)' }}
                onClick={() => onUpdateAgent(draft.id, { selected: !draft.selected })}
                aria-label={t('createExperiment.customBuilder.toggleSelection')}
              >
                {draft.selected && <Check size={12} className="text-white" />}
              </button>
              <div className="min-w-0 flex-1 space-y-2">
                <input
                  value={draft.label}
                  onChange={(event) => onUpdateAgent(draft.id, { label: event.target.value })}
                  className="w-full rounded-lg border px-3 py-2 text-sm outline-none"
                  style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-page-surface)', color: 'var(--ss-text)' }}
                />
                <textarea
                  value={draft.description}
                  onChange={(event) => onUpdateAgent(draft.id, { description: event.target.value })}
                  rows={2}
                  className="w-full rounded-lg border px-3 py-2 text-sm outline-none"
                  style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-page-surface)', color: 'var(--ss-text)' }}
                  placeholder={t('createExperiment.customBuilder.agentDescriptionPlaceholder')}
                />
              </div>
              <label className="space-y-1 text-xs font-medium" style={{ color: 'var(--ss-text-muted)' }}>
                <span>{t('experimentBuilder.step4.count')}</span>
                <input
                  type="number"
                  min={1}
                  value={draft.count || 1}
                  onChange={(event) => onUpdateAgent(draft.id, { count: Math.max(1, Number(event.target.value || 1)) })}
                  className="w-full rounded-lg border px-3 py-2 text-sm outline-none"
                  style={{ borderColor: 'var(--ss-border)', background: 'var(--ss-page-surface)', color: 'var(--ss-text)' }}
                />
              </label>
              <button
                type="button"
                className="justify-self-end text-slate-400 transition hover:text-slate-700"
                onClick={() => onRemoveAgent(draft.id)}
                aria-label={t('common.remove')}
              >
                <X size={16} />
              </button>
            </div>
          </div>
        )) : (
          <div className="rounded-xl border border-dashed p-4 text-sm" style={{ borderColor: 'var(--ss-border-strong)', color: 'var(--ss-text-muted)' }}>
            {t('createExperiment.customBuilder.noAgents')}
          </div>
        )}
      </div>
    </Card>
  );
}
