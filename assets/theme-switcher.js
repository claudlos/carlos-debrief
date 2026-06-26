/* nemoguardian theme-switcher.js
 *
 * Sets data-theme on <html>, persists in localStorage, renders the picker UI.
 * Loaded with `defer` from every page. No dependencies.
 */
(function () {
  'use strict';

  var STORAGE_KEY = 'carlos-debrief.theme';
  var THEMES = [
    { id: 'github-dark', label: 'Default' },
    { id: 'cyber',       label: 'Cyber' },
    { id: 'modern',      label: 'Modern' },
    { id: 'dark-mono',   label: 'Mono' },
    { id: 'light',       label: 'Light' },
  ];
  var DEFAULT = 'github-dark';

  function readStored() {
    try {
      var v = localStorage.getItem(STORAGE_KEY);
      if (!v) return null;
      // Migrate removed theme IDs (cyberpunk -> cyber, dark-monk -> dark-mono)
      // so users who picked the old names still get a valid theme.
      var LEGACY = { cyberpunk: 'cyber', 'dark-monk': 'dark-mono' };
      if (Object.prototype.hasOwnProperty.call(LEGACY, v)) {
        v = LEGACY[v];
        try { localStorage.setItem(STORAGE_KEY, v); } catch (e) { /* ignore */ }
      }
      if (THEMES.some(function (t) { return t.id === v; })) return v;
    } catch (e) { /* localStorage may be blocked; fall back */ }
    return null;
  }

  function persist(id) {
    try { localStorage.setItem(STORAGE_KEY, id); } catch (e) { /* ignore */ }
  }

  function apply(id) {
    document.documentElement.setAttribute('data-theme', id);
    // Hint the browser which color-scheme variants to expect (for native form controls / scrollbars).
    var LIGHT_THEMES = { modern: 1, light: 1 };
    document.documentElement.style.colorScheme = LIGHT_THEMES[id] ? 'light' : 'dark';
    persist(id);
    // notify any listeners (e.g. for analytics or tag-color refresh)
    document.dispatchEvent(new CustomEvent('themechange', { detail: { theme: id } }));
  }

  function mount() {
    // Picker is rendered statically in the HTML; wire up its buttons.
    var slot = document.getElementById('theme-picker');
    if (!slot) {
      // Fallback: create it (shouldn't happen on modern pages).
      slot = document.createElement('div');
      slot.id = 'theme-picker';
      slot.className = 'theme-picker';
      slot.setAttribute('role', 'group');
      slot.setAttribute('aria-label', 'Theme switcher');
      document.body.insertBefore(slot, document.body.firstChild);
    }
    var current = document.documentElement.getAttribute('data-theme') || DEFAULT;
    // Wire up any pre-existing buttons or create them.
    var existingButtons = slot.querySelectorAll('button[data-theme]');
    if (existingButtons.length === 0) {
      slot.innerHTML = '';
      THEMES.forEach(function (t) {
        var b = document.createElement('button');
        b.type = 'button';
        b.dataset.theme = t.id;
        b.textContent = t.label;
        slot.appendChild(b);
      });
    }
    function update() {
      var c = document.documentElement.getAttribute('data-theme') || DEFAULT;
      Array.prototype.forEach.call(slot.querySelectorAll('button[data-theme]'), function (btn) {
        btn.setAttribute('aria-pressed', String(btn.dataset.theme === c));
      });
    }
    Array.prototype.forEach.call(slot.querySelectorAll('button[data-theme]'), function (btn) {
      btn.addEventListener('click', function () { apply(btn.dataset.theme); update(); });
    });
    update();
  }

  // Apply stored theme BEFORE first paint to avoid flash.
  var initial = readStored() || DEFAULT;
  document.documentElement.setAttribute('data-theme', initial);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }

  // Keyboard shortcut: Alt+T cycles through themes.
  document.addEventListener('keydown', function (e) {
    if (!e.altKey || e.key !== 't') return;
    var i = THEMES.findIndex(function (t) { return t.id === (document.documentElement.getAttribute('data-theme') || DEFAULT); });
    var next = THEMES[(i + 1) % THEMES.length];
    apply(next.id);
    var slot = document.getElementById('theme-picker');
    if (slot) {
      Array.prototype.forEach.call(slot.querySelectorAll('button'), function (btn) {
        btn.setAttribute('aria-pressed', String(btn.dataset.theme === next.id));
      });
    }
  });
})();
