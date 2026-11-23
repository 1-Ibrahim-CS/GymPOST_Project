import { TimeUntilPipe } from './time-until.pipe';

describe('TimeUntilPipe', () => {
  const pipe = new TimeUntilPipe();
  const now = new Date('2026-11-23T10:00:00Z');

  it('shows minutes for under an hour', () => {
    expect(pipe.transform('2026-11-23T10:45:00Z', now)).toBe('in 45 min');
  });

  it('shows hours for under a day', () => {
    expect(pipe.transform('2026-11-23T13:00:00Z', now)).toBe('in 3 h');
  });

  it('shows days after that', () => {
    expect(pipe.transform('2026-11-24T10:00:00Z', now)).toBe('in 1 day');
    expect(pipe.transform('2026-11-26T10:00:00Z', now)).toBe('in 3 days');
  });

  it('says started for past times and handles empty values', () => {
    expect(pipe.transform('2026-11-23T09:00:00Z', now)).toBe('started');
    expect(pipe.transform(null)).toBe('');
  });
});
