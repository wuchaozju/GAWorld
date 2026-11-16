/**
 * Key-value pair editor.
 *
 * Exports: KeyValueField (default)
 */

import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';

interface KeyValueFieldProps {
  value: Record<string, string>;
  onChange: (value: Record<string, string>) => void;
  disabled?: boolean;
}

export default function KeyValueField({
  value,
  onChange,
  disabled = false
}: KeyValueFieldProps) {
  const { t } = useTranslation();
  const [newKey, setNewKey] = useState('');
  const [newValue, setNewValue] = useState('');

  const addPair = () => {
    if (newKey.trim()) {
      onChange({ ...value, [newKey.trim()]: newValue });
      setNewKey('');
      setNewValue('');
    }
  };

  const removePair = (key: string) => {
    const updated = { ...value };
    delete updated[key];
    onChange(updated);
  };

  const updatePair = (key: string, newVal: string) => {
    onChange({ ...value, [key]: newVal });
  };

  return (
    <div className="space-y-2">
      {Object.entries(value).map(([key, val]) => (
        <div key={key} className="flex items-center gap-2">
          <input
            type="text"
            value={key}
            disabled={disabled}
            className="w-1/3 px-2 py-1 border rounded"
            readOnly
          />
          <input
            type="text"
            value={val}
            onChange={(e) => updatePair(key, e.target.value)}
            disabled={disabled}
            className="flex-1 px-2 py-1 border rounded"
          />
          <button
            onClick={() => removePair(key)}
            disabled={disabled}
            className="px-2 py-1 text-sm text-red-600 border rounded"
          >
            {t('experimentBuilder.keyValueField.remove')}
          </button>
        </div>
      ))}
      <div className="flex gap-2">
        <input
          type="text"
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          placeholder={t('experimentBuilder.keyValueField.key')}
          disabled={disabled}
          className="w-1/3 px-2 py-1 border rounded"
        />
        <input
          type="text"
          value={newValue}
          onChange={(e) => setNewValue(e.target.value)}
          placeholder={t('experimentBuilder.keyValueField.value')}
          disabled={disabled}
          className="flex-1 px-2 py-1 border rounded"
        />
        <button
          onClick={addPair}
          disabled={disabled || !newKey.trim()}
          className="px-3 py-1 bg-blue-600 text-white rounded text-sm"
        >
          {t('experimentBuilder.keyValueField.add')}
        </button>
      </div>
    </div>
  );
}
