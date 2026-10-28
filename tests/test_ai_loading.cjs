const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

test('analysis form announces loading, blocks duplicates, and resets on return', () => {
  const events = {}, windowEvents = {};
  const button = {disabled: false}, loading = {hidden: true}, result = {hidden: false};
  const form = {
    querySelector: s => s === 'button[type="submit"]' ? button : s === '[data-ai-loading]' ? loading : result,
    addEventListener: (name, fn) => { events[name] = fn; }
  };
  vm.runInNewContext(fs.readFileSync('app/static/theme-workflow.js', 'utf8'), {
    document: {querySelectorAll: s => s === '[data-ai-analysis]' ? [form] : [], getElementById: () => null},
    window: {location: {hash: ''}, addEventListener: (name, fn) => { windowEvents[name] = fn; }}
  });
  events.submit({preventDefault: () => assert.fail('first submission blocked')});
  assert.equal(button.disabled, true);
  assert.equal(loading.hidden, false);
  assert.equal(result.hidden, true);
  let blocked = false;
  events.submit({preventDefault: () => { blocked = true; }});
  assert.equal(blocked, true);
  windowEvents.pageshow();
  assert.equal(button.disabled, false);
  assert.equal(loading.hidden, true);
  assert.equal(result.hidden, false);
  events.submit({preventDefault: () => assert.fail('retry blocked')});
  assert.equal(loading.hidden, false);
});
