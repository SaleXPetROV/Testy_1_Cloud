import { useEffect, useRef } from 'react';

/**
 * Performant mouse-parallax tilt with depth.
 *
 *  - Listens to `mousemove` on window (passive) for a smooth global feel.
 *  - Single rAF loop, lerp smoothing, no React re-renders.
 *  - Sets CSS variables on the bound element:
 *      --tx / --ty  → rotation in degrees (rotateY / rotateX)
 *      --px / --py  → translation in px (translate3d)
 *  - The CSS class `.holo-tilt` consumes those vars (see index.css).
 *
 *  - Disabled automatically on:
 *      • coarse pointers (touch / mobile)
 *      • prefers-reduced-motion
 *      • viewport width < 1024px
 *      • low-end devices (deviceMemory <= 2 or hardwareConcurrency <= 2)
 *      • when the page is hidden (visibilitychange)
 *
 *  Returns a ref to attach to the parent element of the SVG.
 *
 *  @param {{ max?: number, shift?: number, damp?: number }} opts
 *      max   - max tilt angle in degrees (default 12)
 *      shift - max translation in px      (default 10)
 *      damp  - lerp factor 0..1           (default 0.10)
 */
export function useMouseParallax({ max = 12, shift = 10, damp = 0.10 } = {}) {
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof window === 'undefined') return;

    // ----- Bail-out conditions for low-end / touch / reduced-motion ---------
    const mqCoarse = window.matchMedia?.('(pointer: coarse)');
    const mqReduce = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    const mqSmall  = window.matchMedia?.('(max-width: 1023px)');
    const lowMem   = (navigator.deviceMemory || 8) <= 2;
    const lowCpu   = (navigator.hardwareConcurrency || 8) <= 2;
    if (mqCoarse?.matches || mqReduce?.matches || mqSmall?.matches || lowMem || lowCpu) {
      // Make sure no stale tilt remains
      el.style.setProperty('--tx', '0deg');
      el.style.setProperty('--ty', '0deg');
      el.style.setProperty('--px', '0px');
      el.style.setProperty('--py', '0px');
      return;
    }

    let targetX = 0, targetY = 0;          // -1..1 normalised mouse pos
    let curX = 0, curY = 0;                // smoothed values
    let raf = 0;
    let active = false;
    let visible = !document.hidden;
    let inView = true;                     // IntersectionObserver gate

    const loop = () => {
      curX += (targetX - curX) * damp;
      curY += (targetY - curY) * damp;

      // Rotate around centre — cap to `max` deg
      const rotY = curX * max;
      const rotX = -curY * max;

      // Slight translation for depth / "follow" feel
      const trX = curX * shift;
      const trY = curY * shift;

      el.style.setProperty('--tx', `${rotY.toFixed(2)}deg`);
      el.style.setProperty('--ty', `${rotX.toFixed(2)}deg`);
      el.style.setProperty('--px', `${trX.toFixed(2)}px`);
      el.style.setProperty('--py', `${trY.toFixed(2)}px`);

      if (
        Math.abs(targetX - curX) > 0.001 ||
        Math.abs(targetY - curY) > 0.001
      ) {
        raf = requestAnimationFrame(loop);
      } else {
        active = false;
      }
    };

    const ensureLoop = () => {
      if (!active && visible && inView) {
        active = true;
        raf = requestAnimationFrame(loop);
      }
    };

    const onMove = (e) => {
      // Skip updates entirely while the element is offscreen / hidden — its
      // getBoundingClientRect() returns coordinates far outside the viewport,
      // which would push targetX/targetY to extreme values. When the user
      // scrolls back into view, the rAF loop would then animate from old
      // curX/curY toward those stale extremes, causing a visible "lag" /
      // catch-up dance for ~0.5s. Ignoring mouse while offscreen keeps the
      // hologram perfectly still until the user actually sees it again.
      if (!inView || !visible) return;
      // Compute pos relative to the bound element's centre, normalised to [-1, 1]
      // by half the **viewport** so the effect scales nicely with the whole screen.
      const rect = el.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const halfW = window.innerWidth  / 2;
      const halfH = window.innerHeight / 2;
      const nx = (e.clientX - cx) / halfW;
      const ny = (e.clientY - cy) / halfH;
      targetX = Math.max(-1, Math.min(1, nx));
      targetY = Math.max(-1, Math.min(1, ny));
      ensureLoop();
    };

    const onLeaveWindow = () => {
      targetX = 0;
      targetY = 0;
      ensureLoop();
    };

    const onVisibility = () => {
      visible = !document.hidden;
      if (!visible) {
        cancelAnimationFrame(raf);
        active = false;
      } else {
        ensureLoop();
      }
    };

    window.addEventListener('mousemove', onMove, { passive: true });
    window.addEventListener('mouseout', (e) => {
      // Only when leaving the document
      if (!e.relatedTarget && !e.toElement) onLeaveWindow();
    }, { passive: true });
    document.addEventListener('visibilitychange', onVisibility);

    // Pause the rAF loop whenever the element is scrolled out of view.
    // Saves battery/CPU on long pages where the crystal is far below the fold.
    let io = null;
    if ('IntersectionObserver' in window) {
      io = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            const wasInView = inView;
            inView = entry.isIntersecting;
            // Toggle .holo-paused so all SVG keyframe animations literally
            // pause via animation-play-state when offscreen — prevents a
            // jank spike when the user scrolls back: nothing was running, so
            // nothing has to "catch up" or be re-rasterised.
            if (inView) {
              el.classList.remove('holo-paused');
            } else {
              el.classList.add('holo-paused');
            }
            if (inView && !wasInView) {
              // Just re-entered view: snap target AND smoothing values to a
              // neutral (zero) tilt and write CSS vars immediately. This
              // prevents the loop from animating from a stale old curX/curY
              // toward whatever target was last computed, which would look
              // like a "lag" / drift when scrolling back to the hologram.
              targetX = 0; targetY = 0;
              curX = 0; curY = 0;
              el.style.setProperty('--tx', '0deg');
              el.style.setProperty('--ty', '0deg');
              el.style.setProperty('--px', '0px');
              el.style.setProperty('--py', '0px');
            }
          }
          if (!inView) {
            cancelAnimationFrame(raf);
            active = false;
          } else {
            ensureLoop();
          }
        },
        { root: null, rootMargin: '200px', threshold: 0 }
      );
      io.observe(el);
    }

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('mousemove', onMove);
      document.removeEventListener('visibilitychange', onVisibility);
      if (io) io.disconnect();
    };
  }, [max, shift, damp]);

  return ref;
}
