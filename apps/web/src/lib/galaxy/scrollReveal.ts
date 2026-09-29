/**
 * GSAP ScrollTrigger reveal for `.animate-fade-up` elements.
 *
 * Elements rise and un-blur as they scroll into view, staggered when several
 * enter together. A MutationObserver picks up elements rendered later (data
 * loading, route changes). After the tween the inline styles are cleared and
 * the element gets `data-revealed`, so no transform/filter is left behind
 * (those would break sticky positioning and backdrop blur inside it).
 */
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

const SELECTOR = ".animate-fade-up:not([data-revealed])";
const FROM = { opacity: 0, y: 40, scale: 0.985, filter: "blur(6px)" };

export function startScrollReveal(): () => void {
  gsap.registerPlugin(ScrollTrigger);
  (window as Window & { __galaxyReveal?: boolean }).__galaxyReveal = true;
  const seen = new WeakSet<Element>();
  let queued: Element[] = [];
  let flushRaf = 0;
  let refreshTimer = 0;

  const done = (el: Element) => {
    el.setAttribute("data-revealed", "");
    gsap.set(el, { clearProps: "opacity,transform,filter" });
  };

  const flush = () => {
    flushRaf = 0;
    const els = queued.filter((el) => el.isConnected);
    queued = [];
    if (!els.length) return;
    gsap.set(els, FROM);
    ScrollTrigger.batch(els, {
      start: "top 92%",
      once: true,
      onEnter: (batch) =>
        gsap.to(batch, {
          opacity: 1,
          y: 0,
          scale: 1,
          filter: "blur(0px)",
          duration: 0.9,
          ease: "power3.out",
          stagger: { each: 0.08, onComplete: function (this: gsap.core.Tween) { done(this.targets()[0] as Element); } },
          overwrite: true,
        }),
    });
  };

  const collect = (root: ParentNode) => {
    root.querySelectorAll(SELECTOR).forEach((el) => {
      if (seen.has(el)) return;
      seen.add(el);
      queued.push(el);
    });
    if (queued.length && !flushRaf) flushRaf = requestAnimationFrame(flush);
  };

  collect(document);
  const observer = new MutationObserver((records) => {
    let removed = false;
    for (const r of records) {
      r.addedNodes.forEach((n) => {
        if (!(n instanceof Element)) return;
        if (n.matches(SELECTOR)) collect(n.parentElement ?? document);
        else collect(n);
      });
      if (r.removedNodes.length) removed = true;
    }
    // Layout changed: trigger positions must be recomputed; drop dead triggers.
    window.clearTimeout(refreshTimer);
    refreshTimer = window.setTimeout(() => {
      if (removed) ScrollTrigger.getAll().forEach((t) => t.trigger && !t.trigger.isConnected && t.kill());
      ScrollTrigger.refresh();
    }, 150);
  });
  observer.observe(document.body, { childList: true, subtree: true });

  return () => {
    observer.disconnect();
    cancelAnimationFrame(flushRaf);
    window.clearTimeout(refreshTimer);
    ScrollTrigger.getAll().forEach((t) => t.kill());
  };
}
