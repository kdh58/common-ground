const test = require('node:test');
const assert = require('node:assert/strict');
const { selectTimeZone, parseTimestamp, formatTimestamp, localizeTimestamps } = require('../app/static/timestamps.js');

const zone = (timeZone) => ({ timeZone, fallback: false });

for (const [name, timestamp, timeZone, expected] of [
  ['New York summer', '2026-10-27T17:22:00.123456+00:00', 'America/New_York', 'Oct 27, 2026 · 1:22 PM EDT'],
  ['Los Angeles summer', '2026-10-27T17:22:00Z', 'America/Los_Angeles', 'Oct 27, 2026 · 10:22 AM PDT'],
  ['New York winter', '2026-01-27T17:22:00Z', 'America/New_York', 'Jan 27, 2026 · 12:22 PM EST'],
  ['Los Angeles winter', '2026-01-27T17:22:00Z', 'America/Los_Angeles', 'Jan 27, 2026 · 9:22 AM PST'],
  ['New York spring before jump', '2026-03-08T06:59:00Z', 'America/New_York', 'Mar 8, 2026 · 1:59 AM EST'],
  ['New York spring after jump', '2026-03-08T07:00:00Z', 'America/New_York', 'Mar 8, 2026 · 3:00 AM EDT'],
  ['Los Angeles spring before jump', '2026-03-08T09:59:00Z', 'America/Los_Angeles', 'Mar 8, 2026 · 1:59 AM PST'],
  ['Los Angeles spring after jump', '2026-03-08T10:00:00Z', 'America/Los_Angeles', 'Mar 8, 2026 · 3:00 AM PDT'],
  ['New York fall first hour', '2026-11-01T05:30:00Z', 'America/New_York', 'Nov 1, 2026 · 1:30 AM EDT'],
  ['New York fall repeated hour', '2026-11-01T06:30:00Z', 'America/New_York', 'Nov 1, 2026 · 1:30 AM EST'],
  ['Los Angeles fall first hour', '2026-11-01T08:30:00Z', 'America/Los_Angeles', 'Nov 1, 2026 · 1:30 AM PDT'],
  ['Los Angeles fall repeated hour', '2026-11-01T09:30:00Z', 'America/Los_Angeles', 'Nov 1, 2026 · 1:30 AM PST'],
  ['previous calendar day', '2026-10-28T01:22:00Z', 'America/Los_Angeles', 'Oct 27, 2026 · 6:22 PM PDT'],
  ['midnight AM', '2026-10-27T04:00:00Z', 'America/New_York', 'Oct 27, 2026 · 12:00 AM EDT'],
  ['explicit offset input', '2026-10-27T13:22:00-04:00', 'America/Los_Angeles', 'Oct 27, 2026 · 10:22 AM PDT'],
  ['non-US timezone', '2026-10-27T17:22:00Z', 'Asia/Tokyo', 'Oct 28, 2026 · 2:22 AM GMT+9'],
]) {
  test(name, () => assert.equal(formatTimestamp(timestamp, zone(timeZone)), expected));
}

for (const value of [undefined, null, '', 'Invalid/Zone', '<img src=x onerror=alert(1)>']) {
  test(`timezone fallback for ${JSON.stringify(value)}`, () => {
    const selected = selectTimeZone(() => value);
    assert.deepEqual(selected, { timeZone: 'America/New_York', fallback: true });
    assert.equal(formatTimestamp('2026-10-27T17:22:00Z', selected),
      'Oct 27, 2026 · 1:22 PM EDT (America/New_York; fallback)');
  });
}

test('timezone detection exception falls back visibly', () => {
  const selected = selectTimeZone(() => { throw new Error('Unavailable'); });
  assert.equal(selected.fallback, true);
  assert.match(formatTimestamp('2026-01-27T17:22:00Z', selected), /12:22 PM EST \(America\/New_York; fallback\)$/);
});

test('default detector uses Intl resolvedOptions rather than a fixed timezone', () => {
  const previous = process.env.TZ;
  try {
    for (const name of ['America/Los_Angeles', 'America/New_York']) {
      process.env.TZ = name;
      assert.deepEqual(selectTimeZone(), { timeZone: name, fallback: false });
    }
    process.env.TZ = 'UTC';
    assert.equal(formatTimestamp('2026-10-27T17:22:00Z', zone('America/Los_Angeles')), 'Oct 27, 2026 · 10:22 AM PDT');
  } finally {
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
  }
});

for (const timestamp of [undefined, null, '', 'bad', '2026-10-27', '2026-10-27T17:22:00',
  '2026-02-30T17:22:00Z', '2026-13-01T17:22:00Z', '2026-10-27T24:00:00Z', '<script>alert(1)</script>']) {
  test(`invalid or missing timestamp ${JSON.stringify(timestamp)}`, () => {
    assert.equal(parseTimestamp(timestamp), null);
    assert.equal(formatTimestamp(timestamp, zone('America/New_York')), 'Time unavailable');
  });
}

function element(value) {
  return {
    attrs: { datetime: value, title: 'old raw timestamp' },
    getAttribute(name) { return this.attrs[name]; },
    removeAttribute(name) { delete this.attrs[name]; },
    set innerHTML(_) { throw new Error('Never insert HTML'); }
  };
}

test('DOM enhancement formats only system time elements using textContent', () => {
  const valid = element('2026-10-27T17:22:00.123456+00:00');
  const invalid = element('<img src=x onerror=alert(1)>');
  const schedule = { textContent: 'Saturday, November 14 · 2:00 PM' };
  const doc = { querySelectorAll(selector) {
    assert.equal(selector, 'time[data-local-time]');
    return [valid, invalid];
  } };
  localizeTimestamps(doc, zone('America/Los_Angeles'));
  assert.equal(valid.textContent, 'Oct 27, 2026 · 10:22 AM PDT');
  assert.equal(valid.title, 'Oct 27, 2026 · 10:22 AM PDT — America/Los_Angeles');
  assert.doesNotMatch(valid.title, /123456|T17:/);
  assert.equal(invalid.textContent, 'Time unavailable');
  assert.equal(invalid.attrs.datetime, undefined);
  assert.equal(invalid.attrs.title, undefined);
  assert.equal(schedule.textContent, 'Saturday, November 14 · 2:00 PM');
});

test('missing Intl formatter preserves readable server fallback', () => {
  const value = element('2026-10-27T17:22:00Z');
  value.textContent = 'Oct 27, 2026 · 1:22 PM EDT (America/New_York; fallback)';
  const original = Intl.DateTimeFormat;
  try {
    Intl.DateTimeFormat = () => { throw new Error('Intl unavailable'); };
    localizeTimestamps({ querySelectorAll: () => [value] });
    assert.equal(value.textContent, 'Oct 27, 2026 · 1:22 PM EDT (America/New_York; fallback)');
  } finally {
    Intl.DateTimeFormat = original;
  }
});
