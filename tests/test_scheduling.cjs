const test = require('node:test');
const assert = require('node:assert/strict');
const { validTimezone, browserTimezone, sameTimezone, setupSchedule, initialize } = require('../app/static/scheduling.js');

function fixture(saved = '', selected = saved) {
  const listeners = {};
  const form = { addEventListener: (name, fn) => { listeners[name] = fn; } };
  const element = () => ({ hidden: false, textContent: '', focus() { this.focused = true; } });
  const zone = { value: selected, dataset: { savedTimezone: saved } };
  const status = element();
  const error = element();
  const change = { ...element(), addEventListener: (name, fn) => { listeners[name] = fn; } };
  const fields = {
    '[name="timezone"]': zone, '[data-schedule-timezone-status]': status,
    '[data-change-schedule-timezone]': change, '[data-schedule-timezone-error]': error
  };
  // No date/time selector exists in this fixture: timezone logic must not rewrite them.
  const fieldset = { closest: () => form, querySelector: selector => {
    assert.ok(selector in fields, `Unexpected selector ${selector}`);
    return fields[selector];
  } };
  return { zone, status, error, change, fieldset, listeners,
    submit() { const event = { prevented: false, preventDefault() { this.prevented = true; } }; listeners.submit(event); return event; } };
}

for (const zone of ['America/New_York', 'Europe/London', 'Asia/Tokyo', 'UTC']) {
  test(`valid IANA zone ${zone}`, () => assert.equal(validTimezone(zone), zone));
}
for (const zone of [undefined, null, '', 'Invalid/Zone', '<script>', '+01:00', 'localtime', 'posix/Europe/London']) {
  test(`invalid timezone ${String(zone)}`, () => assert.equal(validTimezone(zone), null));
}
test('surrounding whitespace is trimmed independently of server validation', () => {
  assert.equal(validTimezone('\u00a0America/New_York '), 'America/New_York');
});
test('browser detector uses Intl resolvedOptions timezone', () => {
  assert.equal(browserTimezone(), Intl.DateTimeFormat().resolvedOptions().timeZone);
});
test('missing Intl provides no guessed timezone', () => {
  const original = Intl.DateTimeFormat;
  Intl.DateTimeFormat = () => { throw new Error('Unavailable'); };
  try { assert.equal(browserTimezone(), null); } finally { Intl.DateTimeFormat = original; }
});
test('new form initializes from browser and submits a valid hidden zone', () => {
  const f = fixture();
  setupSchedule(f.fieldset, () => 'Europe/London');
  assert.equal(f.zone.value, 'Europe/London');
  assert.match(f.status.textContent, /Scheduled timezone: Europe\/London/);
  assert.equal(f.change.hidden, true);
  assert.equal(f.submit().prevented, false);
});
for (const value of [null, '', 'Invalid/Zone']) {
  test(`unavailable/invalid browser ${String(value)} blocks submission visibly`, () => {
    const f = fixture();
    setupSchedule(f.fieldset, () => value);
    assert.equal(f.zone.value, '');
    assert.equal(f.submit().prevented, true);
    assert.equal(f.error.hidden, false);
    assert.equal(f.error.focused, true);
    assert.match(f.error.textContent, /has not been saved/);
  });
}
test('saved timezone is preserved when browser differs until explicit change', () => {
  const f = fixture('America/New_York');
  setupSchedule(f.fieldset, () => 'Europe/London');
  assert.equal(f.zone.value, 'America/New_York');
  assert.equal(f.change.hidden, false);
  assert.match(f.status.textContent, /Your browser timezone is Europe\/London/);
  assert.equal(f.submit().prevented, false);
  assert.equal(f.zone.value, 'America/New_York');
  f.listeners.click();
  assert.equal(f.zone.value, 'Europe/London');
  assert.equal(f.change.hidden, true);
  assert.match(f.status.textContent, /Date and times have not changed/);
  assert.equal(f.status.focused, true);
});
test('saved timezone still submits if browser timezone detection is unavailable', () => {
  const f = fixture('America/New_York');
  setupSchedule(f.fieldset, () => { throw new Error('No detector'); });
  assert.equal(f.zone.value, 'America/New_York');
  assert.equal(f.submit().prevented, false);
  assert.equal(f.change.hidden, true);
});
test('tampered hidden timezone is validated again at submit and not silently replaced', () => {
  const f = fixture('America/New_York');
  setupSchedule(f.fieldset, () => 'Europe/London');
  f.zone.value = 'Invalid/Zone';
  assert.equal(f.submit().prevented, true);
  assert.equal(f.zone.value, 'Invalid/Zone');
  f.listeners.click();
  assert.equal(f.zone.value, 'Europe/London');
});
test('validation rerender retains explicitly changed timezone', () => {
  const f = fixture('America/New_York', 'Europe/London');
  setupSchedule(f.fieldset, () => 'America/New_York');
  assert.equal(f.zone.value, 'Europe/London');
  assert.equal(f.submit().prevented, false);
});
test('unset legacy timezone initializes without touching time inputs', () => {
  const f = fixture();
  setupSchedule(f.fieldset, () => 'Asia/Tokyo');
  assert.equal(f.zone.value, 'Asia/Tokyo');
});
test('alias-equivalent zones do not request an unnecessary change', () => {
  assert.equal(sameTimezone('UTC', 'Etc/UTC'), true);
});
test('all schedule fieldsets initialize independently', () => {
  const a = fixture('America/New_York'), b = fixture('Europe/London');
  initialize({ querySelectorAll: selector => {
    assert.equal(selector, '[data-schedule-fields]'); return [a.fieldset, b.fieldset];
  } });
  assert.equal(a.zone.value, 'America/New_York');
  assert.equal(b.zone.value, 'Europe/London');
});
