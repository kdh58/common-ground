// Gathering wall-clock inputs use their saved zone, or the browser zone when unset.
(() => {
  'use strict';

  function validTimezone(value) {
    if (typeof value !== 'string') return null;
    const name = value.trim();
    if (!name || name.length > 100 || /^[+-]/.test(name) ||
        /^(?:localtime|posixrules)$|^(?:posix|right)\//.test(name)) return null;
    try {
      new Intl.DateTimeFormat('en-US', { timeZone: name }).format(0);
      return name;
    } catch {
      return null;
    }
  }

  function browserTimezone() {
    try {
      return validTimezone(Intl.DateTimeFormat().resolvedOptions().timeZone);
    } catch {
      return null; // No guessed timezone or UTC fallback for schedule input.
    }
  }

  function sameTimezone(a, b) {
    if (!a || !b) return false;
    try {
      const canonical = name => new Intl.DateTimeFormat('en-US', { timeZone: name }).resolvedOptions().timeZone;
      return canonical(a) === canonical(b);
    } catch {
      return false;
    }
  }

  function setupSchedule(fieldset, detect = browserTimezone) {
    const form = fieldset.closest('form');
    const zone = fieldset.querySelector('[name="timezone"]');
    const status = fieldset.querySelector('[data-schedule-timezone-status]');
    const change = fieldset.querySelector('[data-change-schedule-timezone]');
    const error = fieldset.querySelector('[data-schedule-timezone-error]');
    let browser = null;
    let changed = false;
    const detectSafely = () => {
      try { return validTimezone(detect()); } catch { return null; }
    };

    function refresh() {
      browser = detectSafely();
      if (!zone.value.trim()) zone.value = zone.dataset.savedTimezone || browser || '';
      const selected = validTimezone(zone.value);
      if (selected) zone.value = selected;
      status.textContent = selected
        ? `Scheduled timezone: ${selected}.` : 'Your timezone could not be determined.';
      if (browser && !sameTimezone(selected, browser)) {
        status.textContent += ` Your browser timezone is ${browser}. Change timezone will use it and keep the date and times as entered.`;
      } else if (!browser && selected) {
        status.textContent += ' Your browser timezone is unavailable; the saved timezone is preserved.';
      }
      if (changed) status.textContent += ' Timezone changed. Date and times have not changed; review them before saving.';
      change.hidden = !browser || sameTimezone(selected, browser);
      error.hidden = Boolean(selected);
      error.textContent = selected ? '' : 'We could not determine a valid timezone. Check your device timezone settings, then reload this page. Your schedule has not been saved.';
      return Boolean(selected);
    }

    change.addEventListener('click', () => {
      browser = detectSafely();
      if (!browser) { refresh(); return; }
      zone.value = browser;
      changed = true;
      refresh();
      status.focus();
    });
    status.tabIndex = -1;
    form.addEventListener('submit', event => {
      // Recheck before submission; hidden inputs have no native required validation.
      if (!refresh()) {
        event.preventDefault();
        error.focus();
      }
    });
    refresh();
  }

  function initialize(doc) {
    doc.querySelectorAll('[data-schedule-fields]').forEach(fieldset => setupSchedule(fieldset));
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { validTimezone, browserTimezone, sameTimezone, setupSchedule, initialize };
  }
  if (typeof document !== 'undefined') initialize(document);
})();
