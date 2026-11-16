import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CountBarChart } from './CountBarChart';

describe('CountBarChart', () => {
  it('renders a row per bar with its label and value', () => {
    render(<CountBarChart bars={[{ label: 'Alice', value: 3 }, { label: 'Bob', value: 1 }]} />);
    expect(screen.getByText('Alice')).toBeTruthy();
    expect(screen.getByText('Bob')).toBeTruthy();
    expect(screen.getByText('3')).toBeTruthy();
    expect(screen.getByText('1')).toBeTruthy();
  });

  it('sizes each bar as a percentage of the largest value', () => {
    const { container } = render(
      <CountBarChart bars={[{ label: 'Alice', value: 3 }, { label: 'Bob', value: 1 }]} />,
    );
    expect(container.querySelectorAll('[data-pct]')).toHaveLength(2);
    expect(container.querySelector('[data-label="Alice"]')?.getAttribute('data-pct')).toBe('100');
    expect(container.querySelector('[data-label="Bob"]')?.getAttribute('data-pct')).toBe('33.33');
  });

  it('throws when given no bars', () => {
    expect(() => render(<CountBarChart bars={[]} />)).toThrow();
  });
});
