/**
 * Payoff matrix editor for 2-player game theory scenarios.
 *
 * Renders an N×N table for editing game payoffs.
 * Supports symmetric mode (one value per cell) and asymmetric mode (two values).
 *
 * Exports: PayoffMatrixEditor (default)
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { Info } from 'lucide-react';

export interface MatrixCell {
  symmetric: boolean;
  rows: string[];
  cols: string[];
  cells: Record<string, string>; // Maps "row:col" to parameter name
}

interface PayoffMatrixEditorProps {
  matrixMeta: MatrixCell;
  parameters: Record<string, number>;
  onChange: (key: string, value: number) => void;
  disabled?: boolean;
}

export default function PayoffMatrixEditor({
  matrixMeta,
  parameters,
  onChange,
  disabled = false
}: PayoffMatrixEditorProps) {
  const { t } = useTranslation();

  const formatActionName = (action: string): string => {
    return action.charAt(0).toUpperCase() + action.slice(1).replace(/_/g, ' ');
  };

  const getActionName = (action: string): string => {
    const normalized = action.toLowerCase().replace(/\s+/g, '_');
    const translated = t(`experimentBuilder.payoffMatrix.actionNames.${normalized}`, { defaultValue: '' });
    return translated || formatActionName(action);
  };

  const getCellKey = (row: string, col: string): string => {
    return `${row}:${col}`;
  };

  // Get action description for tooltip
  const getActionDescription = (action: string): string => {
    const key = `experimentBuilder.payoffMatrix.actions.${action}`;
    const translated = t(key);
    // If translation doesn't exist, fall back to "Choose {action}"
    if (translated === key) {
      return t('experimentBuilder.payoffMatrix.actions.choose', { action: formatActionName(action) });
    }
    return translated;
  };

  return (
    <div className="space-y-4">
      {/* Explanation Box */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-3">
        <div className="flex items-start gap-2">
          <Info className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
          <div className="text-sm text-blue-800">
            <strong>{t('experimentBuilder.payoffMatrix.howToRead.title')}</strong>
            <ul className="mt-2 space-y-1 list-disc list-inside text-blue-700">
              <li><strong>{t('experimentBuilder.payoffMatrix.howToRead.rows')}</strong> = {t('experimentBuilder.payoffMatrix.rowLabel')}</li>
              <li><strong>{t('experimentBuilder.payoffMatrix.howToRead.columns')}</strong> = {t('experimentBuilder.payoffMatrix.colLabel')}</li>
              <li><strong>{t('experimentBuilder.payoffMatrix.howToRead.cellValues')}</strong> = {t('experimentBuilder.payoffMatrix.pointsLabel')}</li>
            </ul>
          </div>
        </div>

        {matrixMeta.symmetric ? (
          <div className="text-sm text-blue-700 bg-blue-100 p-2 rounded">
            <strong>{t('experimentBuilder.payoffMatrix.symmetric.title')}</strong> {t('experimentBuilder.payoffMatrix.symmetric.description')}
            {' '}{t('experimentBuilder.payoffMatrix.symmetric.example')}
          </div>
        ) : (
          <div className="text-sm text-blue-700 bg-blue-100 p-2 rounded">
            <strong>{t('experimentBuilder.payoffMatrix.asymmetric.title')}</strong> {t('experimentBuilder.payoffMatrix.asymmetric.description')}
            <span className="font-medium"> {t('experimentBuilder.payoffMatrix.asymmetric.row')}</span> = Player 1's payoff,
            <span className="font-medium"> {t('experimentBuilder.payoffMatrix.asymmetric.col')}</span> = Player 2's payoff.
          </div>
        )}
      </div>

      {/* Action Legend */}
      <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
        <h4 className="text-sm font-medium text-gray-700 mb-2">{t('experimentBuilder.payoffMatrix.actionLegend')}</h4>
        <div className="flex flex-wrap gap-3">
          {[...matrixMeta.rows, ...matrixMeta.cols].filter((v, i, a) => a.indexOf(v) === i).map(action => (
            <div key={action} className="flex items-center gap-2 text-sm">
              <span className="font-medium text-gray-900 bg-white px-2 py-0.5 rounded border">
                {getActionName(action)}
              </span>
              <span className="text-gray-600">{getActionDescription(action)}</span>
            </div>
          ))}
        </div>
      </div>

      {/* The Matrix */}
      <div className="overflow-x-auto">
        <div className="text-sm text-gray-600 mb-2 italic">
          {t('experimentBuilder.payoffMatrix.readInstruction')}
        </div>
        <table className="border-collapse">
          <thead>
            <tr>
              <th className="border p-2 bg-gray-200 text-gray-900 font-semibold">
                <div className="text-xs text-gray-500">{t('experimentBuilder.payoffMatrix.iChoose')}</div>
                <div className="text-xs text-gray-500">{t('experimentBuilder.payoffMatrix.theyChoose')}</div>
              </th>
              {matrixMeta.cols.map(col => (
                <th key={col} className="border p-2 bg-gray-200 text-gray-900 font-semibold min-w-32">
                  <div>{getActionName(col)}</div>
                  <div className="text-xs text-gray-500 font-normal">{getActionDescription(col)}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrixMeta.rows.map(row => (
              <tr key={row}>
                <th className="border p-2 bg-gray-200 text-gray-900 font-semibold min-w-32">
                  <div>{getActionName(row)}</div>
                  <div className="text-xs text-gray-500 font-normal">{getActionDescription(row)}</div>
                </th>
                {matrixMeta.cols.map(col => {
                  const cellKey = getCellKey(row, col);
                  const paramKey = matrixMeta.cells[cellKey];
                  const value = parameters[paramKey] ?? 0;

                  return (
                    <td key={col} className="border p-2 bg-white">
                      {matrixMeta.symmetric ? (
                        <div className="flex flex-col items-center">
                          <input
                            type="number"
                            value={value}
                            onChange={(e) =>
                              onChange(paramKey, parseFloat(e.target.value) || 0)
                            }
                            disabled={disabled}
                            className="w-20 px-2 py-1 border border-gray-300 rounded text-center text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                          />
                          <span className="text-xs text-gray-500 mt-1">{t('experimentBuilder.payoffMatrix.pointsEach')}</span>
                        </div>
                      ) : (
                        <div className="flex flex-col items-center gap-1">
                          <div className="flex items-center gap-1">
                            <span className="text-xs text-gray-600 font-medium">P1:</span>
                            <input
                              type="number"
                              value={parameters[`${paramKey}_row`] ?? value}
                              onChange={(e) =>
                                onChange(`${paramKey}_row`, parseFloat(e.target.value) || 0)
                              }
                              disabled={disabled}
                              className="w-14 px-1 py-1 border border-gray-300 rounded text-center text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                            />
                          </div>
                          <div className="flex items-center gap-1">
                            <span className="text-xs text-gray-600 font-medium">P2:</span>
                            <input
                              type="number"
                              value={parameters[`${paramKey}_col`] ?? value}
                              onChange={(e) =>
                                onChange(`${paramKey}_col`, parseFloat(e.target.value) || 0)
                              }
                              disabled={disabled}
                              className="w-14 px-1 py-1 border border-gray-300 rounded text-center text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                            />
                          </div>
                        </div>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="text-xs text-gray-600 bg-gray-50 p-2 rounded">
        💡 <strong>{t('experimentBuilder.payoffMatrix.tip')}</strong>
      </div>
    </div>
  );
}
