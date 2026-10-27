// Progressive enhancement: disclosures and all forms also work without JavaScript.
(() => {
  const reveal = (id) => {
    const target = document.getElementById(id);
    if (!target) return;
    for (let node = target; node; node = node.parentElement) {
      if (node.tagName === 'DETAILS') node.open = true;
    }
  };
  document.querySelectorAll('[data-open-analysis], [data-open-theme]').forEach((link) => {
    link.addEventListener('click', () => reveal(link.dataset.openAnalysis || link.dataset.openTheme));
  });
  reveal(window.location.hash.slice(1));
})();
