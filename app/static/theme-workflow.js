// Progressive enhancement: disclosures and all forms also work without JavaScript.
(() => {
  document.querySelectorAll('[data-ai-analysis]').forEach((form) => {
    const button = form.querySelector('button[type="submit"]');
    const loading = form.querySelector('[data-ai-loading]');
    const result = form.querySelector('[data-ai-result]');
    const reset = () => {
      button.disabled = false;
      loading.hidden = true;
      if (result) result.hidden = false;
    };
    form.addEventListener('submit', (event) => {
      if (button.disabled) { event.preventDefault(); return; }
      button.disabled = true;
      loading.hidden = false;
      if (result) result.hidden = true;
    });
    window.addEventListener('pageshow', reset);
  });
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
