const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

const generationUrl = 'http://test/host/gatherings/1/themes?tab=themes';
const statusUrl = 'http://test/host/gatherings/1/themes/status?tab=themes';
const completed = {ok: true, redirected: true, url: 'http://test/host/gatherings/1?tab=themes&analysis=22'};
const htmlResponse = {ok: true, redirected: false, text: async () => 'server HTML'};
const tick = () => new Promise(resolve => setImmediate(resolve));

function fixture(initialState = '') {
  const events = {}, windowEvents = {}, requests = [], navigation = [], scrollCalls = [];
  const container = () => ({className: '', childNodes: [], querySelectorAll: () => [], contains: () => false,
    replaceChildren(...nodes) { this.childNodes = nodes; }});
  const button = {disabled: false, textContent: 'Suggest Discussion Themes'};
  const loading = {hidden: true}, result = container();
  const loadingLabel = {}, loadingMessage = {}, dispatched = [];
  const currentThemes = container(), history = container();
  const refresh = {querySelector: () => ({addEventListener() {}})};
  const key = {value: 'original-key'};
  const form = {
    action: initialState === 'pending' ? statusUrl : generationUrl,
    dataset: {generationUrl, statusUrl, recoveryState: initialState},
    querySelector: s => ({
      'button[type="submit"]': button, '[data-ai-loading]': loading,
      '[data-ai-result]': result, '[name="request_key"]': key,
      '[data-ai-loading-label]': loadingLabel, '[data-ai-loading-message]': loadingMessage
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
  let returnedPage = {querySelector: () => null};
  const selectors = {'[data-current-themes]': currentThemes, '[data-analysis-history]': history, '[data-ai-refresh]': refresh};
  const revealed = {id: 'analysis-22', tagName: 'DETAILS', open: false};
  vm.runInNewContext(fs.readFileSync('app/static/theme-workflow.js', 'utf8'), {
    document: {
      activeElement, createElement: tag => ({tag, textContent: ''}),
      dispatchEvent: event => dispatched.push(event.type),
      querySelector: s => selectors[s],
      querySelectorAll: s => s === '[data-ai-analysis]' ? [form] : [],
      getElementById: id => id === revealed.id ? revealed : null
    },
    window: browser, URL, Event: class { constructor(type) { this.type = type; } },
    FormData: class {
      constructor(form) { this.key = form.querySelector('[name="request_key"]').value; }
      set(name, value) { assert.equal(name, 'request_key'); this.key = value; }
    },
    DOMParser: class { parseFromString() { return returnedPage; } },
    fetch: (url, options) => new Promise((resolve, reject) => {
      requests.push({url, options, resolve, reject});
    })
  });
  return {
    button, loading, result, key, form, requests, navigation, browser, location, activeElement,
    scrollCalls, history, currentThemes, revealed, windowEvents, loadingLabel, dispatched,
    setFeedback(text, nextKey = 'fresh-key', state = 'failed', savedHistory = 'refreshed history') {
      const returnedForm = {
        dataset: {recoveryState: state},
        querySelector: s => ({
          '[data-ai-result]': {textContent: text, childNodes: [{textContent: text}]},
          '[name="request_key"]': {value: nextKey},
          'button[type="submit"]': {textContent: state === 'pending' ? 'Refresh analysis status' :
            state === 'unrecorded' ? 'Submit original request' : 'Retry'}
        })[s]
      };
      returnedPage = {querySelector: s => ({
        '[data-ai-analysis]': returnedForm,
        '[data-current-themes]': {childNodes: [{textContent: 'refreshed current themes'}]},
        '[data-analysis-history]': {childNodes: [{textContent: savedHistory}]},
        '[data-analysis-history] details.analysis-run[open]': revealed
      })[s]};
    },
    complete(response = htmlResponse) { requests.at(-1).resolve(response); },
    fail() { requests.at(-1).reject(new Error('network failure')); },
    submit() {
      let prevented = false;
      const done = events.submit({preventDefault() { prevented = true; }});
      assert.equal(prevented, true);
      return done;
    }
  };
}

for (const message of [
  'AI assistance is currently on standby',
  "AI analysis couldn't be completed",
  'The analysis request timed out.'
]) {
  test(message + ': confirmed failure refreshes history and retry uses a fresh key', async () => {
    const f = fixture();
    f.setFeedback(message);
    const pending = f.submit();
    assert.equal(f.button.disabled, true);
    assert.equal(f.loading.hidden, false);
    await f.submit();
    assert.equal(f.requests.length, 1, 'double submit is blocked');
    assert.equal(f.requests[0].options.credentials, 'same-origin');
    assert.equal(f.requests[0].options.cache, 'no-store');
    assert.equal(f.requests[0].options.body.key, 'original-key');
    f.browser.scrollY = 940;
    f.complete();
    await pending;
    assert.deepEqual(f.scrollCalls.at(-1), [0, 940]);
    assert.deepEqual(f.navigation, []);
    assert.equal(f.result.childNodes[0].textContent, message);
    assert.equal(f.history.childNodes[0].textContent, 'refreshed history');
    assert.equal(f.currentThemes.childNodes[0].textContent, 'refreshed current themes');
    assert.equal(f.revealed.open, true);
    assert.deepEqual(f.dispatched, ['theme-workspace-updated']);
    assert.equal(f.button.disabled, false);
    assert.equal(f.loading.hidden, true);
    assert.equal(f.button.textContent, 'Retry');
    const retry = f.submit();
    assert.equal(f.requests[1].url, generationUrl);
    assert.equal(f.requests[1].options.body.key, 'fresh-key');
    f.complete(completed);
    await retry;
    assert.deepEqual(f.navigation, ['http://test/host/gatherings/1?tab=themes&analysis=22#analysis-22']);
  });
}

for (const failure of ['lost POST response', 'redirect GET rejects', 'redirect GET returns 503', 'unparseable response']) {
  test(failure + ': reconciles original receipt and recovers saved analysis without another generation', async () => {
    const f = fixture();
    const pending = f.submit();
    if (failure === 'redirect GET returns 503') {
      f.complete({ok: false, redirected: true, status: 503});
    } else if (failure === 'unparseable response') {
      f.complete(htmlResponse);
    } else {
      // fetch rejects for both lost POST delivery and redirect network failure.
      f.fail();
    }
    await tick();
    assert.equal(f.requests.length, 2);
    assert.equal(f.requests[1].url, statusUrl);
    assert.equal(f.requests[1].options.body.key, 'original-key');
    assert.equal(f.button.disabled, true);
    f.complete(completed);
    await pending;
    assert.deepEqual(f.navigation, ['http://test/host/gatherings/1?tab=themes&analysis=22#analysis-22']);
    assert.equal(f.requests.filter(r => r.url === generationUrl).length, 1);
  });
}

test('unavailable reconciliation only offers another status check, retaining the original key', async () => {
  const f = fixture();
  const pending = f.submit();
  f.fail();
  await tick();
  f.fail();
  await pending;
  assert.equal(f.result.childNodes[0].textContent, 'Analysis status could not be confirmed');
  assert.equal(f.button.textContent, 'Refresh analysis status');
  assert.equal(f.form.action, statusUrl);
  assert.equal(f.key.value, 'original-key');
  assert.equal(f.loading.hidden, true);
  assert.equal(f.button.disabled, false);
  assert.deepEqual(f.navigation, []);
  const retry = f.submit();
  assert.equal(f.requests[2].url, statusUrl);
  f.complete(completed);
  await retry;
  assert.equal(f.requests.filter(r => r.url === generationUrl).length, 1);
});

test('pending recovery refreshes history including another tab and keeps checking until completion', async () => {
  const f = fixture('pending');
  f.setFeedback('Analysis is in progress or interrupted', 'original-key', 'pending', 'Analysis #22 and #23 from another tab');
  const refresh = f.submit();
  assert.equal(f.requests[0].url, statusUrl);
  assert.equal(f.loadingLabel.textContent, 'Checking saved analysis status…');
  f.complete();
  await refresh;
  assert.equal(f.key.value, 'original-key');
  assert.equal(f.form.action, statusUrl);
  assert.equal(f.history.childNodes[0].textContent, 'Analysis #22 and #23 from another tab');
  assert.equal(f.button.textContent, 'Refresh analysis status');
  const again = f.submit();
  assert.equal(f.requests[1].url, statusUrl);
  f.complete(completed);
  await again;
  assert.equal(f.requests.filter(r => r.url === generationUrl).length, 0);
  assert.match(f.navigation[0], /analysis=22#analysis-22$/);
});

for (const state of ['failed', 'deleted']) {
  test(state + ': reconciliation requires an explicit new attempt with a fresh key', async () => {
    const f = fixture('pending');
    f.setFeedback('Attempt ' + state, 'fresh-key', state);
    const refresh = f.submit();
    f.complete();
    await refresh;
    assert.equal(f.requests.length, 1, 'no automatic generation');
    assert.equal(f.key.value, 'fresh-key');
    const retry = f.submit();
    assert.equal(f.requests[1].url, generationUrl);
    assert.equal(f.requests[1].options.body.key, 'fresh-key');
    f.complete(completed);
    await retry;
  });
}

test('unrecorded outcome can explicitly resubmit only the original idempotent request', async () => {
  const f = fixture('pending');
  f.setFeedback('No receipt yet', 'original-key', 'unrecorded');
  const refresh = f.submit();
  f.complete();
  await refresh;
  assert.equal(f.requests.length, 1);
  assert.equal(f.button.textContent, 'Submit original request');
  const resend = f.submit();
  assert.equal(f.requests[1].url, generationUrl);
  assert.equal(f.requests[1].options.body.key, 'original-key');
  f.complete(completed);
  await resend;
});

test('server renders accessible status and recovery controls', () => {
  const html = fs.readFileSync('app/templates/theme_workflow.html', 'utf8');
  const form = html.match(/<form[^>]*data-ai-analysis[\s\S]*?<\/form>/)[0];
  assert.match(form, /role="alert" aria-atomic="true" data-ai-result/);
  assert.match(form, /role="status" aria-live="polite"/);
  assert.match(form, /data-status-url=/);
  assert.match(form, /Refresh analysis status/);
  assert.doesNotMatch(form, /autofocus|tabindex/);
});
