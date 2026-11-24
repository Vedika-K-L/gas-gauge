"""Spotlight glow for the dashboard cards.

The glow is drawn by CSS (see assets/styles.css, ".gg-card::before/::after"). CSS cannot read the
pointer, so a few lines of JavaScript copy the mouse position into per-card variables (--mx, --my)
and the page-wide hue variable (--gg-xp). Streamlit strips <script> from markdown, so the script is
loaded through a zero-height components.html iframe that talks to the parent page.

Skipped on touch screens and when the visitor prefers reduced motion. If the browser blocks access
to the parent page, the cards simply render without the moving glow.
"""
from __future__ import annotations

_SCRIPT = """
<script>
(function () {
  try {
    var P = window.parent, D = P.document;
    if (P.__ggSpotOff) { try { P.__ggSpotOff(); } catch (e) {} }
    if (P.matchMedia('(prefers-reduced-motion: reduce)').matches || P.matchMedia('(pointer: coarse)').matches) return;
    var x = -9999, y = -9999, raf = 0;
    function paint() {
      raf = 0;
      var cards = D.querySelectorAll('.gg-card');
      D.documentElement.style.setProperty('--gg-xp', Math.min(1, Math.max(0, x / P.innerWidth)).toFixed(3));
      for (var i = 0; i < cards.length; i++) {
        var r = cards[i].getBoundingClientRect();
        cards[i].style.setProperty('--mx', (x - r.left).toFixed(1) + 'px');
        cards[i].style.setProperty('--my', (y - r.top).toFixed(1) + 'px');
      }
    }
    function move(e) { x = e.clientX; y = e.clientY; if (!raf) raf = P.requestAnimationFrame(paint); }
    // Streamlit redraws cards on every refresh, so re-apply the position a few times a second.
    var tick = P.setInterval(function () { if (x > -9999 && !raf) raf = P.requestAnimationFrame(paint); }, 250);
    D.addEventListener('pointermove', move, { passive: true });
    P.__ggSpotOff = function () { D.removeEventListener('pointermove', move); P.clearInterval(tick); };
  } catch (e) { /* blocked: static cards */ }
})();
</script>
"""


def inject_spotlight() -> None:
    try:
        import streamlit.components.v1 as components

        components.html(_SCRIPT, height=0)
    except Exception:
        pass
