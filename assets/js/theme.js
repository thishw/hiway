(function () {
  var root = document.documentElement;
  var media = window.matchMedia("(prefers-color-scheme: dark)");
  function current() {
    return root.getAttribute("data-theme") || (media.matches ? "dark" : "light");
  }
  document.querySelectorAll(".theme-toggle").forEach(function (btn) {
    btn.setAttribute("aria-pressed", current() === "dark" ? "true" : "false");
    btn.addEventListener("click", function () {
      var next = current() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      btn.setAttribute("aria-pressed", next === "dark" ? "true" : "false");
      try { localStorage.setItem("theme", next); } catch (e) {}
    });
  });
})();
