/**
 * Ordered list editor with add/remove functionality.
 *
 * Exports: ListField (default)
 */

import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';

interface ListFieldProps {
  value: string[];
  onChange: (value: string[]) => void;
  disabled?: boolean;
}

export default function ListField({
  value,
  onChange,
  disabled = false
}: ListFieldProps) {
  const { t } = useTranslation();
  const [newItem, setNewItem] = useState('');

  const addItem = () => {
    if (newItem.trim()) {
      onChange([...value, newItem.trim()]);
      setNewItem('');
    }
  };

  const removeItem = (index: number) => {
    onChange(value.filter((_, i) => i !== index));
  };

  const moveItem = (from: number, to: number) => {
    const updated = [...value];
    const [removed] = updated.splice(from, 1);
    updated.splice(to, 0, removed);
    onChange(updated);
  };

  return (
    <div className="space-y-2">
      {value.map((item, index) => (
        <div key={index} className="flex items-center gap-2">
          <button
            onClick={() => moveItem(index, Math.max(0, index - 1))}
            disabled={disabled || index === 0}
            className="px-2 py-1 text-sm border rounded"
          >
            ↑
          </button>
          <button
            onClick={() => moveItem(index, Math.min(value.length - 1, index + 1))}
            disabled={disabled || index === value.length - 1}
            className="px-2 py-1 text-sm border rounded"
          >
            ↓
          </button>
          <span className="flex-1">{item}</span>
          <button
            onClick={() => removeItem(index)}
            disabled={disabled}
            className="px-2 py-1 text-sm text-red-600 border rounded"
          >
            {t('experimentBuilder.listField.remove')}
          </button>
        </div>
      ))}
      <div className="flex gap-2">
        <input
          type="text"
          value={newItem}
          onChange={(e) => setNewItem(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && addItem()}
          placeholder={t('experimentBuilder.listField.addItem')}
          disabled={disabled}
          className="flex-1 px-3 py-2 border rounded-lg"
        />
        <button
          onClick={addItem}
          disabled={disabled || !newItem.trim()}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg"
        >
          {t('experimentBuilder.listField.add')}
        </button>
      </div>
    </div>
  );
}
