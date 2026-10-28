// Static contracts for the server-rendered UI; no new browser dependency.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const read = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');
test('horizontal entries stack on mobile with comfortable navigation', () => {
  const css = read('app/static/style.css');
  assert.match(css, /\.gathering-entry \{ display: flex;/);
  assert.match(css, /@media \(max-width: 700px\)\s*\{\s*\.gathering-entry \{ flex-direction: column;/);
  assert.match(css, /min-height: 44px/);
  const lists = read('app/templates/macros/gathering_lists.html');
  assert.match(lists, /pagination\(section, 'top'\)/);
  assert.match(lists, /pagination\(section, 'bottom'\)/);
  assert.match(lists, /aria-label="{{ section.title }} pagination/);
  assert.match(lists, /<details class="gathering-directory"/);
  assert.match(lists, /<summary id="{{ section.id }}-heading">/);
  assert.match(lists, /section.pages > 1/);
});
test('native disclosures and original form security and routes remain', () => {
  const host = read('app/templates/host.html');
  assert.match(host, /<details class="card create-gathering"/);
  assert.match(host, /<summary>Create a gathering<\/summary>/);
  assert.match(host, /<summary>Recent questions and RSVPs<\/summary>/);
  assert.match(host, /action="\/host\/gatherings#create-feedback" method="post"/);
  assert.match(host, /name="csrf_token"/);
  for (const field of ['title', 'description', 'location', 'agenda']) {
    assert.match(host, new RegExp('name="' + field + '"[^>]*required'));
  }
  assert.match(read('app/templates/home.html'), /directory\(sections\)/);
});

test('schedule fields use local date/time inputs and hidden browser timezone', () => {
  const fields = read('app/templates/macros/schedule_fields.html');
  assert.match(fields, /'gathering_date','Date','date'/);
  assert.match(fields, /'start_time','Start time','time'/);
  assert.match(fields, /'end_time','End time \(optional\)','time'/);
  assert.match(fields, /name="timezone"/);
  assert.match(fields, /type="hidden" name="timezone"/);
  assert.doesNotMatch(fields, /<select/);
  assert.doesNotMatch(fields, /IANA timezone/);
  assert.match(fields, /Change timezone/);
  assert.match(fields, /aria-describedby=/);
  assert.doesNotMatch(read('app/templates/host.html'), /name="when_text"/);
});

test('save actions target visible feedback without changing POST routes', () => {
  const edit = read('app/templates/host_tabs/gathering.html');
  assert.match(edit, /edit\?tab=gathering#details-feedback/);
  assert.match(edit, /Details were not saved/);
  assert.match(edit, /Gathering details saved/);
  assert.match(edit, /role="alert"/);
  assert.match(edit, /role="status"/);
  assert.match(edit, /Review the validation error above/);
  assert.match(read('app/static/style.css'), /\.save-error/);
});

test('resource edit does not target gathering-details feedback', () => {
  const edit = read('app/templates/host_tabs/gathering.html');
  assert.match(edit, /resources\/{{ resource.id }}\/edit\?tab=gathering"/);
  assert.doesNotMatch(edit, /resources\/{{ resource.id }}\/edit\?tab=gathering#details-feedback/);
});
