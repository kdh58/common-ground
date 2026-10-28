// Progressive enhancement: disclosures and all forms also work without JavaScript.
(() => {
  document.querySelectorAll('[data-ai-analysis]').forEach((form) => {
    const button = form.querySelector('button[type="submit"]');
    const loading = form.querySelector('[data-ai-loading]');
    const result = form.querySelector('[data-ai-result]');
    const reset = () => {
      button.disabled = false;
      loading.hidden = true;
    };
    const showFailure = () => {
      result.className = 'notice';
      const heading = document.createElement('h4');
      heading.textContent = "AI analysis couldn't be completed";
      const message = document.createElement('p');
      message.textContent = 'Something interrupted the analysis. Please try again, or contact the demonstration host if the problem continues.';
      result.replaceChildren(heading, message);
      button.textContent = 'Retry';
    };
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (button.disabled) return;
      const initialScroll = [window.scrollX, window.scrollY];
      button.disabled = true;
      loading.hidden = false;
      result.replaceChildren();
      result.className = '';
      window.scrollTo(...initialScroll);
      let completionScroll;
      try {
        const response = await fetch(form.action, {
          method: 'POST', body: new FormData(form), credentials: 'same-origin'
        });
        if (response.ok && response.redirected) {
          // Fetch response URLs can omit the redirect fragment. Keep the
          // existing success destination at the discussion themes section.
          window.location.assign(response.url.split('#')[0] + '#discussion-themes');
          return;
        }
        const html = await response.text();
        completionScroll = [window.scrollX, window.scrollY];
        const page = new DOMParser().parseFromString(html, 'text/html');
        const returnedForm = page.querySelector('[data-ai-analysis]');
        const feedback = returnedForm?.querySelector('[data-ai-result]');
        const requestKey = returnedForm?.querySelector('[name="request_key"]');
        // Keep the current document, focus and URL. Retry needs the fresh server
        // key because the failed analysis has already consumed the previous key.
        if (requestKey) form.querySelector('[name="request_key"]').value = requestKey.value;
        if (feedback?.textContent.trim()) {
          result.className = 'notice';
          result.replaceChildren(...feedback.childNodes);
          button.textContent = 'Retry';
        } else {
          showFailure();
        }
      } catch {
        completionScroll = [window.scrollX, window.scrollY];
        showFailure();
      } finally {
        reset();
        if (completionScroll) window.scrollTo(...completionScroll);
      }
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
