/*
  Curtain-reveal / spotlight page transition - added 11/14/26
  The opening (enter) animation is pure CSS in static/css/transition.css.
  This script only handles LEAVING a page: when someone clicks a link to another page on
  this site, it closes the curtains first and then navigates.

  It deliberately leaves alone: links other scripts already handled (preventDefault),
  new-tab / modifier clicks, downloads, links to other sites, same-page #anchors,
  javascript: links, and users who prefer reduced motion.
*/
(function () {
  "use strict";

  var CLOSE_MS = 380;          // keep in sync with --st-curtain-close in transition.css
  var SAFETY_MS = 4000;        // if navigation never happens (download, cancelled), reopen
  var LEAVE_CLASS = "st-curtain-leave";
  var root = document.documentElement;

  function prefersReducedMotion() {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  function shouldAnimate(event, link) {
    if (event.defaultPrevented) return false;                  // another script handled it
    if (event.button !== 0) return false;                      // left click only
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
    if (link.hasAttribute("download")) return false;
    if (link.hasAttribute("data-no-transition")) return false; // opt-out hook for any link

    var target = (link.getAttribute("target") || "").toLowerCase();
    if (target && target !== "_self") return false;

    var rawHref = link.getAttribute("href");
    if (!rawHref || rawHref.charAt(0) === "#") return false;
    if (/^\s*javascript:/i.test(rawHref)) return false;

    var url;
    try {
      url = new URL(link.href, window.location.href);
    } catch (e) {
      return false;
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") return false;
    if (url.origin !== window.location.origin) return false;

    // Same page, only the #hash differs: let the browser just scroll.
    if (url.pathname === window.location.pathname &&
        url.search === window.location.search &&
        url.hash) return false;

    return true;
  }

  function closeCurtainsThenGo(href) {
    root.classList.add(LEAVE_CLASS);
    window.setTimeout(function () {
      window.location.href = href;
    }, CLOSE_MS);
    // Safety net: if we're somehow still on this page, open the curtains again.
    window.setTimeout(function () {
      root.classList.remove(LEAVE_CLASS);
    }, SAFETY_MS);
  }

  // Bubble phase on document, so page scripts' own click handlers run first.
  document.addEventListener("click", function (event) {
    if (prefersReducedMotion()) return;
    var link = event.target && event.target.closest ? event.target.closest("a[href]") : null;
    if (!link || !shouldAnimate(event, link)) return;
    if (root.classList.contains(LEAVE_CLASS)) {               // already leaving
      event.preventDefault();
      return;
    }
    event.preventDefault();
    closeCurtainsThenGo(link.href);
  });

  // Back/forward cache: a restored page would otherwise still have closed curtains.
  // Removing the class restarts the CSS opening animation.
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) root.classList.remove(LEAVE_CLASS);
  });
})();
