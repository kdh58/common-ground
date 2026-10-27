// Display-only conversion. Stored timestamps and gathering schedule text are untouched.
(() => {
  'use strict';
  const FALLBACK_TIMEZONE = 'America/New_York';
  const UNAVAILABLE = 'Time unavailable';

  function selectTimeZone(detect = () => Intl.DateTimeFormat().resolvedOptions().timeZone) {
    try {
      const timeZone = detect();
      if (typeof timeZone !== 'string' || !timeZone.trim()) throw new Error('Missing timezone');
      // Reject unsupported/invalid names before using them in a formatter.
      new Intl.DateTimeFormat('en-US', { timeZone }).format(0);
      return { timeZone, fallback: false };
    } catch {
      return { timeZone: FALLBACK_TIMEZONE, fallback: true };
    }
  }

  function parseTimestamp(value) {
    // An offset is mandatory: Date must never interpret a naive time as local.
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(value)) return null;
    const datePart = value.slice(0, 10);
    const calendarDate = new Date(`${datePart}T00:00:00Z`);
    // Date otherwise silently normalizes values such as February 30.
    if (Number.isNaN(calendarDate.getTime()) || calendarDate.toISOString().slice(0, 10) !== datePart) return null;
    const instant = new Date(value);
    return Number.isNaN(instant.getTime()) ? null : instant;
  }

  function formatTimestamp(value, zone = selectTimeZone()) {
    const instant = parseTimestamp(value);
    if (!instant) return UNAVAILABLE;
    const formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: zone.timeZone,
      year: 'numeric', month: 'short', day: 'numeric',
      hour: 'numeric', minute: '2-digit', hour12: true, timeZoneName: 'short'
    });
    const parts = Object.fromEntries(formatter.formatToParts(instant).map((part) => [part.type, part.value]));
    const label = `${parts.month} ${parts.day}, ${parts.year} · ${parts.hour}:${parts.minute} ${parts.dayPeriod} ${parts.timeZoneName}`;
    return zone.fallback ? `${label} (${zone.timeZone}; fallback)` : label;
  }

  function localizeTimestamps(doc, zone = selectTimeZone()) {
    doc.querySelectorAll('time[data-local-time]').forEach((element) => {
      try {
        const text = formatTimestamp(element.getAttribute('datetime'), zone);
        // Only textContent is used; timestamps and zone names never become HTML.
        element.textContent = text;
        if (text === UNAVAILABLE) {
          element.removeAttribute('datetime');
          element.removeAttribute('title');
        } else {
          element.title = `${text} — ${zone.timeZone}`;
        }
      } catch {
        // Keep the readable, explicitly labeled server fallback if Intl is unavailable.
      }
    });
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { selectTimeZone, parseTimestamp, formatTimestamp, localizeTimestamps };
  }
  if (typeof document !== 'undefined') localizeTimestamps(document);
})();
