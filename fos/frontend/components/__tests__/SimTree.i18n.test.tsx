/**
 * This file tests SimTree language behavior in runtime rendering.
 * test_sim_tree_shows_english_labels_by_default checks default English labels.
 * test_sim_tree_shows_chinese_labels_after_language_switch checks labels after switching to Chinese.
 * test_sim_tree_rerenders_labels_when_language_changes checks labels update after language change and rerender.
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SimTree } from '../SimTree';
import { useSimulationStore } from '../../store';
import { resetLanguage, switchLanguage } from '../../test-utils/i18n';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const language = (globalThis as unknown as { i18n: { language: 'en' | 'zh' } }).i18n.language;
      const translations: Record<'en' | 'zh', Record<string, string>> = {
        en: {
          'components.simTree.title': 'Simulation Tree',
          'components.simTree.legendHelp': 'Legend',
          'components.simTree.zoomIn': 'Zoom in',
          'components.simTree.frontier': 'Frontier',
          'components.simTree.selected': 'Selected',
          'components.simTree.failed': 'Failed',
          'components.sidebar.overviewHint': 'Overview hint',
          'simPage.branch': 'Create branch',
        },
        zh: {
          'components.simTree.title': '模拟树',
          'components.simTree.legendHelp': '图例',
          'components.simTree.zoomIn': '放大',
          'components.simTree.frontier': '前沿',
          'components.simTree.selected': '已选中',
          'components.simTree.failed': '失败',
          'components.sidebar.overviewHint': '概览提示',
          'simPage.branch': '创建分支',
        },
      };
      return translations[language][key] ?? key;
    },
  }),
}));

describe('SimTree i18n', () => {
  beforeEach(async () => {
    await resetLanguage();
    Object.defineProperty(globalThis.SVGSVGElement.prototype, 'width', {
      configurable: true,
      value: { baseVal: { value: 800 } },
    });
    Object.defineProperty(globalThis.SVGSVGElement.prototype, 'height', {
      configurable: true,
      value: { baseVal: { value: 600 } },
    });
    useSimulationStore.setState({
      nodes: [
        {
          id: '1',
          display_id: '1',
          parentId: null,
          name: 'Root',
          depth: 0,
          isLeaf: true,
          status: 'completed',
          timestamp: '10:00',
          worldTime: '2026-05-21T10:00:00.000Z',
          meta: {},
        },
      ],
      selectedNodeId: '1',
      compareTargetNodeId: null,
      isCompareMode: false,
      branchSimulation: vi.fn(),
      selectNode: vi.fn(),
      setCompareTarget: vi.fn(),
      toggleHelpModal: vi.fn(),
      deleteNode: vi.fn(),
      currentSimulation: { id: 'sim-1' },
    } as never);
  });

  afterEach(async () => {
    await resetLanguage();
  });

  it('test_sim_tree_shows_english_labels_by_default', () => {
    render(<SimTree layoutDirection="vertical" />);
    expect(screen.getByRole('heading', { name: 'Simulation Tree' })).toBeInTheDocument();
    expect(screen.getByText('Legend')).toBeInTheDocument();
    expect(screen.getByText('Frontier')).toBeInTheDocument();
    expect(screen.getByTitle('Zoom in')).toBeInTheDocument();
  });

  it('test_sim_tree_shows_chinese_labels_after_language_switch', async () => {
    await switchLanguage('zh');
    render(<SimTree layoutDirection="vertical" />);
    expect(screen.getByRole('heading', { name: '模拟树' })).toBeInTheDocument();
    expect(screen.getByText('图例')).toBeInTheDocument();
    expect(screen.getByText('前沿')).toBeInTheDocument();
    expect(screen.getByTitle('放大')).toBeInTheDocument();
  });

  it('test_sim_tree_rerenders_labels_when_language_changes', async () => {
    const { rerender } = render(<SimTree layoutDirection="vertical" />);
    expect(screen.getByRole('heading', { name: 'Simulation Tree' })).toBeInTheDocument();
    await switchLanguage('zh');
    rerender(<SimTree layoutDirection="vertical" />);
    expect(screen.getByRole('heading', { name: '模拟树' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Simulation Tree' })).not.toBeInTheDocument();
  });
});
