import { describe, expect, it } from 'vitest';
import { formatCount, formatDuration } from './format';

describe('formatDuration', () => {
  it('renders sub-minute values in seconds', () => {
    expect(formatDuration(0)).toBe('0s');
    expect(formatDuration(45.6)).toBe('46s');
  });

  it('switches unit as the duration grows', () => {
    expect(formatDuration(90)).toBe('1.5 min');
    expect(formatDuration(7200)).toBe('2.0 h');
    expect(formatDuration(172_800)).toBe('2.0 days');
  });

  it('refuses to render nonsense as a duration', () => {
    expect(formatDuration(-5)).toBe('—');
    expect(formatDuration(Number.NaN)).toBe('—');
  });
});

describe('formatCount', () => {
  it('groups thousands', () => {
    expect(formatCount(1234567)).toMatch(/1.234.567/);
  });
});
