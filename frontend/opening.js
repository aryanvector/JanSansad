/* Every document load gets a new timeline. No visit flags or storage. */
(() => {
  'use strict';
  const root = document.documentElement;
  const overlay = document.getElementById('opening');
  const content = document.querySelector('.container');
  const hole = document.getElementById('keyhole');
  if (window.janSansadInternalNavigation) {
    overlay?.remove();
    root.classList.add('opening-complete');
    return;
  }
  if (!overlay || !hole || !content) return;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const paper = overlay.querySelector('.opening-paper');
  const logo = overlay.querySelector('.opening-logo');
  const caption = overlay.querySelector('.opening-caption');
  let raf, finished = false, scale = 1, started;
  const clamp = n => Math.max(0, Math.min(1, n));
  const position = () => {
    const w = innerWidth, h = innerHeight;
    const unit = Math.min(h / 600, w / 290);
    hole.setAttribute('transform', `translate(${w / 2} ${h / 2}) scale(${unit * scale})`);
    logo.style.width = `${unit * 102}px`;
    logo.style.top = `${h / 2 - unit * 70}px`;
    caption.style.top = `${h / 2 + unit * 145}px`;
  };
  function finish() {
    if (finished) return;
    finished = true;
    cancelAnimationFrame(raf);
    clearTimeout(window.openSansadFallback);
    root.classList.remove('opening-pending', 'opening-ready');
    root.classList.add('opening-complete');
    content.inert = false;
    const skipHadFocus = document.activeElement === document.getElementById('skip-opening');
    overlay.remove();
    removeEventListener('resize', position);
    reduced.removeEventListener('change', motionChanged);
    if (skipHadFocus) document.querySelector('.explore-cta, .brand-name')?.focus({preventScroll:true});
  }
  function motionChanged() { if (reduced.matches) finish(); }
  content.inert = true;
  position();
  addEventListener('resize', position, {passive:true});
  reduced.addEventListener('change', motionChanged);
  document.getElementById('skip-opening').addEventListener('click', finish);
  root.classList.add('opening-ready');
  // In reduced motion the logo appears briefly, without zoom or parallax.
  function frame(now) {
    if (finished) return;
    if (started === undefined) started = now;
    const t = (now - started) / 1000;
    if (reduced.matches) {
      if (t >= .35) return finish();
    } else {
      // Reference: quiet hold -> accelerating keyhole -> typography settling.
      const expansion = clamp((t - .56) / 1.14);
      scale = 1 + 24 * Math.pow(expansion, 4);
      position();
      caption.style.opacity = String(1 - clamp((t - .48) / .27));
      paper.style.opacity = logo.style.opacity = String(1 - clamp((t - .68) / .24));
      if (t >= 1.53) root.classList.add('hero-arriving');
      if (t >= 1.75) return finish();
    }
    raf = requestAnimationFrame(frame);
  }
  // Decode assets before starting; a bounded wait and head watchdog fail open.
  const scene = document.querySelector('.hero-scene');
  Promise.race([
    Promise.allSettled([logo.decode(), ...(scene ? [scene.decode()] : [])]),
    new Promise(resolve => setTimeout(resolve, 1200))
  ]).then(() => { if (!finished) raf = requestAnimationFrame(frame); });
  // A bfcache restore is not a new page load and must not replay the intro.
  addEventListener('pagehide', finish, {once:true});
})();
