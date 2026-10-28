const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

function fixture() {
  const events = {}, windowEvents = {}, requests = [], navigation = [], scrollCalls = [];
  const button = {disabled: false, textContent: 'Suggest Discussion Themes'};
  const loading = {hidden: true};
  const result = {className: '', childNodes: [], replaceChildren(...nodes) { this.childNodes = nodes; }};
  const key = {value: 'original-key'};
  const form = {
    action: 'http://test/host/gatherings/1/themes?tab=themes',
    querySelector: s => ({
      'button[type="submit"]': button, '[data-ai-loading]': loading,
      '[data-ai-result]': result, '[name="request_key"]': key
    })[s],
    addEventListener: (name, fn) => { events[name] = fn; }
  };
  const activeElement = {focus() { assert.fail('must not move focus'); }};
  const location = {hash: '#discussion-themes', assign: url => navigation.push(url)};
  const browser = {
    location, scrollX: 0, scrollY: 720,
    scrollTo(x, y) { scrollCalls.push([x, y]); this.scrollX = x; this.scrollY = y; },
    addEventListener: (name, fn) => { windowEvents[name] = fn; }
  };
  let finish;
  let returnedForm;
  vm.runInNewContext(fs.readFileSync('app/static/theme-workflow.js', 'utf8'), {
    document: {
      activeElement, createElement: tag => ({tag, textContent: ''}),
      querySelectorAll: s => s === '[data-ai-analysis]' ? [form] : [], getElementById: () => null
    },
    window: browser,
    FormData: class { constructor(form) { this.key = form.querySelector('[name="request_key"]').value; } },
    DOMParser: class { parseFromString() { return {querySelector: () => returnedForm}; } },
    fetch: (url, options) => {
      requests.push({url, options});
      return new Promise((resolve, reject) => { finish = {resolve, reject}; });
    }
  });
  return {
    button, loading, result, key, requests, navigation, browser, location, activeElement, scrollCalls,
    setFeedback(text, nextKey = 'fresh-key') {
      returnedForm = {querySelector: s => s === '[data-ai-result]' ?
        {textContent: text, childNodes: [{textContent: text}]} : {value: nextKey}};
    },
    complete(response = {ok: true, redirected: false, text: async () => 'server HTML'}) { finish.resolve(response); },
    fail() { finish.reject(new Error('network failure')); },
    submit() {
      let prevented = false;
      const done = events.submit({preventDefault() { prevented = true; }});
      assert.equal(prevented, true, 'prevent native page reload on every submission');
      return done;
    }
  };
}

for (const message of [
  'AI assistance is currently on standby',
  "AI analysis couldn't be completed",
  'The analysis request timed out.'
]) {
  test(message + ': inline feedback preserves scroll, URL and focus; retry uses fresh key', async () => {
    const f = fixture();
    f.setFeedback(message);
    const pending = f.submit();
    assert.equal(f.button.disabled, true);
    assert.equal(f.loading.hidden, false);
    await f.submit();
    assert.equal(f.requests.length, 1, 'duplicate requests are blocked');
    assert.equal(f.requests[0].options.method, 'POST');
    assert.equal(f.requests[0].options.credentials, 'same-origin');
    assert.equal(f.requests[0].options.body.key, 'original-key');
    // A visitor may continue scrolling while the model is working.
    f.browser.scrollY = 940;
    f.complete();
    await pending;
    assert.equal(f.browser.scrollY, 940);
    assert.deepEqual(f.scrollCalls.at(-1), [0, 940]);
    assert.equal(f.location.hash, '#discussion-themes');
    assert.deepEqual(f.navigation, []);
    assert.equal(f.result.childNodes[0].textContent, message);
    assert.equal(f.button.disabled, false);
    assert.equal(f.loading.hidden, true);
    assert.equal(f.button.textContent, 'Retry');
    const retry = f.submit();
    assert.equal(f.requests[1].options.body.key, 'fresh-key');
    f.complete({ok: true, redirected: true, url: 'http://test/host/gatherings/1?tab=themes'});
    await retry;
    assert.deepEqual(f.navigation, ['http://test/host/gatherings/1?tab=themes#discussion-themes']);
  });
}

test('network failure stays inline, restores controls, and allows retry', async () => {
  const f = fixture();
  const pending = f.submit();
  f.fail();
  await pending;
  assert.equal(f.result.childNodes[0].textContent, "AI analysis couldn't be completed");
  assert.equal(f.browser.scrollY, 720);
  assert.deepEqual(f.navigation, []);
  assert.equal(f.button.disabled, false);
  assert.equal(f.loading.hidden, true);
  const retry = f.submit();
  f.setFeedback('Retry response');
  f.complete();
  await retry;
  assert.equal(f.requests.length, 2);
});

test('unexpected error responses stay inline rather than navigating or reloading', async () => {
  const f = fixture();
  const pending = f.submit();
  f.complete({ok: false, redirected: false, text: async () => 'error page without form'});
  await pending;
  assert.equal(f.result.childNodes[0].textContent, "AI analysis couldn't be completed");
  assert.deepEqual(f.navigation, []);
  assert.equal(f.browser.scrollY, 720);
});

test('server renders a persistent atomic alert next to the analysis controls', () => {
  const html = fs.readFileSync('app/templates/theme_workflow.html', 'utf8');
  const form = html.match(/<form[^>]*data-ai-analysis>[\s\S]*?<\/form>/)[0];
  assert.match(form, /role="alert" aria-atomic="true" data-ai-result/);
  assert.match(form, /role="status" aria-live="polite"/);
  assert.doesNotMatch(form, /autofocus|tabindex/);
});
