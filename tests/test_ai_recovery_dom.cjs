const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM, VirtualConsole} = require('jsdom');
const tick = () => new Promise(resolve => setImmediate(resolve));

// Real DOM controls mirror the server's edit/note forms. In particular, rendered
// defaults, focus, selection, details, and FormData are provided by jsdom.
function html(state = '', revision = '7', includeCompleted = false) {
  const editor = (id) => `<details id="theme-${id}" open><summary>Theme ${id}</summary>
    <form data-theme-edit action="/host/gatherings/1/themes/${id}/edit?tab=themes" method="post">
      <input type="hidden" name="csrf_token" value="csrf">
      <input type="hidden" name="revision" value="${revision}">
      <input id="title-${id}" name="title" value="Saved title ${id}">
      <textarea id="description-${id}" name="description">Saved description ${id}</textarea>
      <button>Save as draft</button>
    </form>
    <form data-theme-edit action="/host/gatherings/1/themes/${id}/notes?tab=themes" method="post">
      <input type="hidden" name="csrf_token" value="csrf">
      <input type="hidden" name="notes_revision" value="${revision}">
      <textarea id="notes-${id}" name="shared_concerns">Saved notes ${id}</textarea>
      <button>Save private notes</button>
    </form>
    <details><summary>Sources</summary>Original questions</details>
  </details>`;
  return `<!doctype html><html><body>
    <section data-current-themes>${editor(1)}</section>
    <form data-theme-edit><input id="manual-title" name="title" value=""></form>
    <form data-ai-analysis data-generation-url="/host/gatherings/1/themes?tab=themes"
      data-status-url="/host/gatherings/1/themes/status?tab=themes" data-recovery-state="${state}"
      action="/host/gatherings/1/themes?tab=themes" method="post">
      <input type="hidden" name="request_key" value="${state === 'failed' || includeCompleted ? 'fresh-key' : 'original-key'}">
      <input type="hidden" name="csrf_token" value="csrf">
      <button type="submit">${state === 'pending' ? 'Refresh analysis status' : state === 'failed' ? 'Retry' : 'Suggest Discussion Themes'}</button>
      <div data-ai-loading role="status" hidden><strong data-ai-loading-label></strong><p data-ai-loading-message></p></div>
      <div data-ai-result role="alert" aria-atomic="true">${state ? `Analysis ${state}` : ''}</div>
    </form>
    <div data-ai-refresh hidden>
      <p role="status" data-ai-refresh-message></p>
      <a data-ai-completed-link target="_blank" rel="noopener noreferrer" hidden></a>
      <input type="checkbox" data-ai-discard>
      <button type="button" data-ai-refresh-saved>Refresh saved content</button>
    </div>
    <div data-analysis-history><details class="analysis-run" id="analysis-1" ${includeCompleted ? '' : 'open'}>
      <summary>Analysis 1</summary>${editor(2)}</details>
      ${includeCompleted ? `<details class="analysis-run" id="analysis-2" open><summary>Analysis 2 complete</summary>
        <time data-local-time datetime="2026-10-27T17:22:00Z">Server fallback</time>
        <a data-analysis-export href="/host/gatherings/1/analyses/2/view.html">View / Print</a>
        <a data-open-theme="theme-2" href="#theme-2">Review original theme</a></details>` : ''}
    </div>
  </body></html>`;
}

function fixture() {
  const errors = [];
  const console = new VirtualConsole();
  console.on('jsdomError', error => errors.push(error));
  const dom = new JSDOM(html(), {url: 'http://test/host/gatherings/1?tab=themes', runScripts: 'outside-only', virtualConsole: console});
  const {window} = dom;
  window.scrollTo = () => {};
  const requests = [];
  window.fetch = (url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject}));
  window.eval(fs.readFileSync('app/static/timestamps.js', 'utf8'));
  window.eval(fs.readFileSync('app/static/theme-workflow.js', 'utf8'));
  const query = selector => window.document.querySelector(selector);
  return {
    window, dom, errors, requests, query,
    submit() { query('[data-ai-analysis]').dispatchEvent(new window.Event('submit', {bubbles: true, cancelable: true})); },
    fail() { requests.at(-1).reject(new Error('Lost POST response')); },
    respond(state = 'pending', completed = false) {
      requests.at(-1).resolve({ok: true, redirected: completed,
        url: 'http://test/host/gatherings/1?tab=themes&analysis=2',
        text: async () => html(completed ? '' : state, '99', completed)});
    },
    edit(selector, value) {
      const field = query(selector);
      field.focus();
      field.value = value;
      field.setSelectionRange(1, 4);
      field.dispatchEvent(new window.Event('input', {bubbles: true}));
      return field;
    }
  };
}

for (const id of [1, 2]) {
  for (const type of ['description', 'notes']) {
    test(`edits to ${type} in ${id === 1 ? 'Current Themes' : 'analysis history'} survive automatic recovery`, async (t) => {
      const f = fixture();
      t.after(() => f.dom.window.close());
      const originalTheme = f.query(`#theme-${id}`);
      const nested = originalTheme.querySelector('details');
      nested.open = true;
      f.submit();
      const field = f.edit(`#${type}-${id}`, 'Unsaved PRIVATE text');
      f.fail();
      await tick();
      assert.match(f.requests[1].url, /themes\/status/);
      assert.equal(f.requests[1].options.body.get('request_key'), 'original-key');
      f.respond();
      await tick();
      assert.strictEqual(f.query(`#theme-${id}`), originalTheme);
      assert.strictEqual(f.window.document.activeElement, field);
      assert.equal(field.value, 'Unsaved PRIVATE text');
      assert.equal(field.selectionStart, 1);
      assert.equal(field.selectionEnd, 4);
      assert.equal(originalTheme.querySelector('[name="revision"]').value, '7');
      assert.equal(originalTheme.querySelector('[name="notes_revision"]').value, '7');
      assert.equal(nested.open, true);
      assert.equal(f.query('[data-ai-refresh]').hidden, false);
      assert.match(f.query('[data-ai-result]').textContent, /pending/);
      f.query('[data-ai-refresh-saved]').click();
      assert.equal(f.requests.length, 2, 'dirty content cannot refresh without explicit discard');
      assert.match(f.query('[data-ai-refresh-message]').textContent, /still unsaved/);
      assert.deepEqual(f.errors, []);
    });
  }
}

test('completed analysis remains discoverable without navigation or loss of edits in either section', async (t) => {
  const f = fixture();
  t.after(() => f.dom.window.close());
  f.submit();
  f.edit('#description-1', 'Unsaved theme text');
  const notes = f.edit('#notes-2', 'Unsaved private notes');
  f.fail();
  await tick();
  f.respond('', true);
  await tick();
  assert.strictEqual(f.window.document.activeElement, notes);
  assert.equal(f.query('#description-1').value, 'Unsaved theme text');
  assert.equal(notes.value, 'Unsaved private notes');
  assert.match(f.query('[data-ai-result]').textContent, /Analysis #2 is complete/);
  const link = f.query('[data-ai-completed-link]');
  assert.equal(link.hidden, false);
  assert.equal(link.target, '_blank');
  assert.match(link.href, /\/analyses\/2\/view.html/);
  assert.equal(f.query('[data-ai-analysis] button').textContent, 'Refresh analysis status');
  assert.equal(f.requests.length, 2);
  assert.deepEqual(f.errors, [], 'no attempted page navigation');
});

test('explicit discard refreshes the latest completed history and preserves disclosures and enhancements', async (t) => {
  const f = fixture();
  t.after(() => f.dom.window.close());
  f.query('#analysis-1').open = false;
  f.query('#theme-1 details').open = true;
  f.submit();
  f.edit('#notes-2', 'Unsaved notes');
  f.fail();
  await tick();
  f.respond('', true);
  await tick();
  f.query('[data-ai-discard]').checked = true;
  const refresh = f.query('[data-ai-refresh-saved]');
  refresh.focus();
  refresh.click();
  assert.equal(f.requests.length, 3);
  assert.match(f.requests[2].url, /themes\/status/);
  assert.equal(f.requests[2].options.body.get('request_key'), 'original-key');
  assert.equal(f.query('#notes-2').value, 'Unsaved notes', 'discard waits for a valid fresh response');
  f.respond('', true);
  await tick();
  assert.equal(f.query('#notes-2').value, 'Saved notes 2');
  assert.equal(f.query('#theme-2 [name="notes_revision"]').value, '99');
  assert.strictEqual(f.window.document.activeElement, refresh);
  assert.equal(f.query('#analysis-1').open, false);
  assert.equal(f.query('#theme-1 details').open, true);
  assert.equal(f.query('#analysis-2').open, true);
  assert.equal(f.query('[data-ai-refresh]').hidden, false, 'explicit refresh control keeps focus');
  assert.match(f.query('[data-ai-refresh-message]').textContent, /content refreshed/);
  assert.notEqual(f.query('#analysis-2 time').textContent, 'Server fallback');
  assert.ok(new URL(f.query('#analysis-2 [data-analysis-export]').href).searchParams.get('timezone'));
  f.query('#theme-2').open = false;
  f.query('[data-open-theme]').click();
  assert.equal(f.query('#theme-2').open, true, 'new disclosure links have their handlers');
  assert.equal(f.requests.filter(r => !r.url.includes('/status')).length, 1);
  assert.deepEqual(f.errors, []);
});

test('failed recovery keeps original tokens; reverted edits permit refresh, and a later edit defers it again', async (t) => {
  const f = fixture();
  t.after(() => f.dom.window.close());
  f.submit();
  const field = f.edit('#description-1', 'Unsaved draft');
  f.respond('failed');
  await tick();
  assert.equal(f.query('[name="request_key"]').value, 'fresh-key');
  assert.equal(f.query('#theme-1 [name="revision"]').value, '7');
  field.form.reset(); // An explicit user reversion to the rendered values.
  f.query('[data-ai-refresh-saved]').click();
  assert.equal(f.requests.length, 2);
  assert.equal(f.requests[1].options.body.get('request_key'), 'original-key', 'refresh checks the failed receipt, not the fresh retry key');
  f.edit('#notes-2', 'New edits while refresh is in flight');
  f.respond('failed');
  await tick();
  assert.equal(f.query('#notes-2').value, 'New edits while refresh is in flight');
  assert.equal(f.query('#theme-2 [name="notes_revision"]').value, '7');
  assert.equal(f.query('[data-ai-refresh]').hidden, false);
  assert.deepEqual(f.errors, []);
});

test('clean editor with keyboard focus is retained even before a value changes', async (t) => {
  const f = fixture();
  t.after(() => f.dom.window.close());
  f.submit();
  const field = f.query('#description-1');
  field.focus();
  f.respond('pending');
  await tick();
  assert.strictEqual(f.window.document.activeElement, field);
  assert.strictEqual(f.query('#description-1'), field);
  assert.equal(f.query('[data-ai-refresh]').hidden, false);
  assert.deepEqual(f.errors, []);
});

test('rejected server-rendered edits stay protected even when values equal their HTML defaults', async (t) => {
  const f = fixture();
  t.after(() => f.dom.window.close());
  const field = f.query('#description-1');
  field.value = field.defaultValue = 'Rejected unsaved interpretation';
  field.form.setAttribute('data-unsaved-edit', '');
  f.submit();
  f.respond('failed');
  await tick();
  assert.strictEqual(f.query('#description-1'), field);
  assert.equal(field.value, 'Rejected unsaved interpretation');
  assert.equal(f.query('#theme-1 [name="revision"]').value, '7');
  assert.equal(f.query('[data-ai-refresh]').hidden, false);
  assert.deepEqual(f.errors, []);
});

test('withdrawing discard consent during refresh keeps edits and original revision tokens', async (t) => {
  const f = fixture();
  t.after(() => f.dom.window.close());
  f.submit();
  const notes = f.edit('#notes-2', 'Unsaved notes');
  f.respond('pending');
  await tick();
  const consent = f.query('[data-ai-discard]');
  consent.checked = true;
  f.query('[data-ai-refresh-saved]').click();
  consent.checked = false;
  f.respond('pending');
  await tick();
  assert.strictEqual(f.query('#notes-2'), notes);
  assert.equal(notes.value, 'Unsaved notes');
  assert.equal(f.query('#theme-2 [name="notes_revision"]').value, '7');
  assert.deepEqual(f.errors, []);
});
