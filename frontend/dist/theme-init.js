// Apply theme before React renders to prevent flash of wrong theme
(function () {
  var stored = localStorage.getItem("a2d-theme");
  if (stored === "light") {
    document.documentElement.classList.remove("dark");
  } else if (stored === "dark") {
    document.documentElement.classList.add("dark");
  } else {
    // No stored preference — respect system setting
    if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  }
})();
