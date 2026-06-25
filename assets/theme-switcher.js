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
    { id: 'cyberpunk',   label: 'Cyber' },
    { id: 'dark-monk',   label: 'Monk' },
  ];
  var DEFAULT = 'github-dark';

  function readStored() {
    try {
      var v = localStorage.getItem(STORAGE_KEY);
      if (v && THEMES.some(function (t) { return t.id === v; })) return v;
    } catch (e) { /* localStorage may be blocked; fall back */ }
    return null;
  }

  function persist(id) {
    try { localStorage.setItem(STORAGE_KEY, id); } catch (e) { /* ignore */ }
  }

  function apply(id) {
    document.documentElement.setAttribute('data-theme', id);
    document.documentElement.style.colorScheme = id === 'dark-monk' ? 'light dark' : 'dark';
    persist(id);
    // notify any listeners (e.g. for analytics or tag-color refresh)
    document.dispatchEvent(new CustomEvent('themechange', { detail: { theme: id } }));
  }

  function mount() {
    // Inline picker mount so pages don't need to add HTML.
    var slot = document.getElementById('theme-picker');
    if (!slot) {
      slot = document.createElement('div');
      slot.id = 'theme-picker';
      slot.className = 'theme-picker';
      slot.setAttribute('role', 'group');
      slot.setAttribute('aria-label', 'Theme switcher');
      document.body.appendChild(slot);
    }
    var current = document.documentElement.getAttribute('data-theme') || DEFAULT;
    slot.innerHTML = '';
    THEMES.forEach(function (t) {
      var b = document.createElement('button');
      b.type = 'button';
      b.dataset.theme = t.id;
      b.textContent = t.label;
      b.setAttribute('aria-pressed', String(t.id === current));
      b.addEventListener('click', function () { apply(t.id); update(); });
      slot.appendChild(b);
    });
    function update() {
      var c = document.documentElement.getAttribute('data-theme') || DEFAULT;
      Array.prototype.forEach.call(slot.querySelectorAll('button'), function (btn) {
        btn.setAttribute('aria-pressed', String(btn.dataset.theme === c));
      });
    }
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
