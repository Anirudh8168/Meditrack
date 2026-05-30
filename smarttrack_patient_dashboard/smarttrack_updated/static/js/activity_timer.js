/**
 * SmartTrack — single source of truth for activity countdowns.
 * Always derive remaining time from scheduled_time / started_at (ISO), never local decrement counters.
 */
(function (global) {
  'use strict';

  function parseIsoMs(iso) {
    if (!iso) return null;
    var ms = new Date(iso).getTime();
    return isNaN(ms) ? null : ms;
  }

  function formatMMSS(totalSeconds) {
    var sec = Math.max(0, Math.floor(totalSeconds));
    var m = Math.floor(sec / 60);
    var s = sec % 60;
    return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
  }

  /** Seconds until scheduled_time (negative = past due). */
  function secondsUntilScheduled(scheduledIso, nowMs) {
    var target = parseIsoMs(scheduledIso);
    if (target == null) return 0;
    var now = nowMs != null ? nowMs : Date.now();
    return Math.ceil((target - now) / 1000);
  }

  /** Seconds left in an in-progress session from started_at + duration. */
  function secondsRemaining(startedIso, durationSeconds, nowMs) {
    var started = parseIsoMs(startedIso);
    if (started == null) return Math.max(0, durationSeconds || 0);
    var now = nowMs != null ? nowMs : Date.now();
    var elapsed = (now - started) / 1000;
    return Math.max(0, Math.ceil((durationSeconds || 0) - elapsed));
  }

  function isSessionComplete(startedIso, durationSeconds, nowMs) {
    return secondsRemaining(startedIso, durationSeconds, nowMs) <= 0;
  }

  global.ActivityTimer = {
    parseIsoMs: parseIsoMs,
    formatMMSS: formatMMSS,
    secondsUntilScheduled: secondsUntilScheduled,
    secondsRemaining: secondsRemaining,
    isSessionComplete: isSessionComplete,
  };
})(typeof window !== 'undefined' ? window : this);
