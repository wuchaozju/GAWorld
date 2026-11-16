/**
 * Draggable reorderable list field.
 *
 * Similar to ListField but with drag-to-reorder UI.
 *
 * Exports: DragListField (default)
 */

import React from 'react';

interface DragListFieldProps {
  value: string[];
  onChange: (value: string[]) => void;
  disabled?: boolean;
}

export default function DragListField({
  value,
  onChange,
  disabled = false
}: DragListFieldProps) {
  const moveItem = (from: number, to: number) => {
    const updated = [...value];
    const [removed] = updated.splice(from, 1);
    updated.splice(to, 0, removed);
    onChange(updated);
  };

  return (
    <div className="space-y-1">
      {value.map((item, index) => (
        <div
          key={index}
          className="flex items-center gap-2 p-2 bg-gray-50 rounded border"
        >
          <span className="text-gray-400 cursor-grab">:::</span>
          <span className="flex-1">{item}</span>
          <button
            onClick={() => moveItem(index, Math.max(0, index - 1))}
            disabled={disabled || index === 0}
            className="px-2 py-1 text-sm border rounded hover:bg-gray-100"
          >
            ↑
          </button>
          <button
            onClick={() => moveItem(index, Math.min(value.length - 1, index + 1))}
            disabled={disabled || index === value.length - 1}
            className="px-2 py-1 text-sm border rounded hover:bg-gray-100"
          >
            ↓
          </button>
        </div>
      ))}
    </div>
  );
}
