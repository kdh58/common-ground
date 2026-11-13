// Progressive enhancement: disclosures and all forms also work without JavaScript.
(() => {
  const reveal = (id) => {
    const target = document.getElementById(id);
    if (!target) return;
    for (let node = target; node; node = node.parentElement) {
      if (node.tagName === 'DETAILS') node.open = true;
    }
  };
  const wireLinks = () => {
    document.querySelectorAll('[data-open-analysis], [data-open-theme]').forEach((link) => {
      link.addEventListener('click', () => reveal(link.dataset.openAnalysis || link.dataset.openTheme));
    });
  };
  document.querySelectorAll('[data-ai-analysis]').forEach((form) => {
    const button = form.querySelector('button[type="submit"]');
    const loading = form.querySelector('[data-ai-loading]');
    const loadingLabel = form.querySelector('[data-ai-loading-label]');
    const loadingMessage = form.querySelector('[data-ai-loading-message]');
    const result = form.querySelector('[data-ai-result]');
    const refresh = document.querySelector('[data-ai-refresh]');
    const refreshMessage = refresh.querySelector('[data-ai-refresh-message]');
    const refreshButton = refresh.querySelector('[data-ai-refresh-saved]');
    const discard = refresh.querySelector('[data-ai-discard]');
    const completedLink = refresh.querySelector('[data-ai-completed-link]');
    const sectionSelectors = ['[data-current-themes]', '[data-analysis-history]'];
    // Only theme/manual text and private-note forms participate. Keep their DOM
    // intact when dirty: copying values into newer revision tokens is unsafe.
    const editForms = () => [...document.querySelectorAll('[data-theme-edit]')];
    const hasEdits = () => editForms().some((editor) => editor.hasAttribute('data-unsaved-edit') ||
      [...editor.querySelectorAll('input:not([type="hidden"]), textarea')]
        .some((field) => field.value !== field.defaultValue));
    const protectEditors = () => hasEdits() || editForms().some((editor) => editor.contains(document.activeElement)) || sectionSelectors.some((selector) =>
      document.querySelector(selector)?.contains(document.activeElement));
    let receiptKey = form.querySelector('[name="request_key"]').value;
    const deferRefresh = (message, destination) => {
      refresh.hidden = false;
      refreshMessage.textContent = message;
      const run = destination?.searchParams.get('analysis');
      completedLink.hidden = !run;
      if (run) {
        const report = new URL(form.dataset.generationUrl, form.action);
        report.pathname = report.pathname.replace(/\/themes$/, `/analyses/${run}/view.html`);
        report.search = '';
        completedLink.href = report.href;
        completedLink.setAttribute('data-analysis-export', '');
        completedLink.textContent = `View completed Analysis #${run} in a new tab`;
        document.dispatchEvent(new Event('theme-workspace-updated'));
      }
    };
    const disclosureKey = (details, root) => {
      if (details.id) return details.id;
      const owner = details.parentElement.closest('details[id]') || root;
      return `${owner.id || (root.hasAttribute('data-analysis-history') ? 'history' : 'current')}:${[...owner.querySelectorAll('details')].indexOf(details)}`;
    };
    const reset = () => {
      button.disabled = false;
      loading.hidden = true;
    };
    // Uncertain outcomes can only check status. Never replace a consumed key
    // until the server confirms failure/deletion (or confirms no receipt yet).
    let checking = form.dataset.recoveryState === 'pending';
    const showUncertain = () => {
      checking = true;
      form.action = form.dataset.statusUrl;
      result.className = 'notice';
      const heading = document.createElement('h4');
      heading.textContent = 'Analysis status could not be confirmed';
      const message = document.createElement('p');
      message.textContent = 'The request may still be processing or its results may already be saved. Refresh its status before starting another analysis. This does not start another analysis.';
      result.replaceChildren(heading, message);
      button.textContent = 'Refresh analysis status';
    };
    const applyResponse = async (response, options = {}) => {
      let destination;
      if (response.ok && response.redirected) {
        // Fetch may omit the redirect fragment; recover the specific run anchor.
        destination = new URL(response.url);
        const run = destination.searchParams.get('analysis');
        destination.hash = run ? `analysis-${run}` : 'discussion-themes';
        if (!options.refresh) {
          if (protectEditors()) {
            checking = true;
            form.action = form.dataset.statusUrl;
            button.textContent = 'Refresh analysis status';
            const message = `Analysis #${run} is complete. Your unsaved edits have been kept; view the saved analysis in a new tab or refresh after saving or explicitly discarding edits.`;
            result.textContent = message;
            result.className = 'notice';
            deferRefresh(message, destination);
          } else {
            window.location.assign(destination.href);
          }
          return;
        }
      }
      if (!response.ok) throw new Error('Analysis response unavailable');
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      const returnedForm = page.querySelector('[data-ai-analysis]');
      const feedback = returnedForm?.querySelector('[data-ai-result]');
      const requestKey = returnedForm?.querySelector('[name="request_key"]');
      if (!requestKey || (!feedback?.textContent.trim() && !options.refresh)) throw new Error('Missing analysis status');
      const openRun = page.querySelector('[data-analysis-history] details.analysis-run[open]');
      form.querySelector('[name="request_key"]').value = requestKey.value;
      form.dataset.recoveryState = returnedForm.dataset.recoveryState;
      checking = returnedForm.dataset.recoveryState === 'pending';
      form.action = checking ? form.dataset.statusUrl : form.dataset.generationUrl;
      result.className = 'notice';
      if (feedback?.textContent.trim()) result.replaceChildren(...feedback.childNodes);
      else result.textContent = destination ? `Analysis #${destination.searchParams.get('analysis')} is complete. Saved results are available.` : 'Saved analysis content refreshed.';
      button.textContent = returnedForm.querySelector('button[type="submit"]').textContent;
      if (!(options.discard && discard.checked) && protectEditors()) {
        deferRefresh('Saved analysis content is available. Your edits, focus, and revision tokens have been kept. Save or explicitly discard edits before refreshing.', destination);
        return;
      }
      // Reconcile the saved workspace too, including results from another tab.
      const sections = sectionSelectors.map((selector) => {
        const current = document.querySelector(selector);
        const returned = page.querySelector(selector);
        if (!current || !returned) throw new Error('Missing analysis history');
        return {current, returned};
      });
      // Preserve disclosures on surviving runs/themes, including nested citations.
      const disclosures = new Map();
      for (const {current} of sections) {
        current.querySelectorAll('details').forEach((details) => disclosures.set(disclosureKey(details, current), details.open));
      }
      if (options.discard && discard.checked) editForms().forEach((editor) => {
        editor.reset();
        editor.removeAttribute('data-unsaved-edit');
      });
      for (const {current, returned} of sections) {
        current.replaceChildren(...returned.childNodes);
        current.querySelectorAll('details').forEach((details) => {
          const key = disclosureKey(details, current);
          if (disclosures.has(key)) details.open = disclosures.get(key);
        });
      }
      // Keep the explicit refresh control in place while it has keyboard focus.
      refresh.hidden = !options.refresh;
      if (options.refresh) refreshMessage.textContent = 'Saved analysis content refreshed. Further refreshes check the original request without starting another analysis.';
      discard.checked = false;
      document.dispatchEvent(new Event('theme-workspace-updated'));
      wireLinks();
      if (openRun) reveal(openRun.id);
    };
    const announceLoading = (statusOnly) => {
      loadingLabel.textContent = statusOnly ? 'Checking saved analysis status…' : 'Ollama is analyzing your discussion ideas…';
      loadingMessage.textContent = statusOnly ? 'Looking for the original request and its saved results. No new analysis is being started.' :
        'Identifying common themes and preparing suggestions. This may take a little while.';
    };
    const checkStatus = (options) => {
      announceLoading(true);
      const body = new FormData(form);
      body.set('request_key', receiptKey);
      return fetch(form.dataset.statusUrl, {
        method: 'POST', body, credentials: 'same-origin', cache: 'no-store'
      }).then((response) => applyResponse(response, options));
    };
    refreshButton.addEventListener('click', async () => {
      if (button.disabled || refreshButton.disabled) return;
      if (hasEdits() && !discard.checked) {
        refreshMessage.textContent = 'Your edits are still unsaved. Save them first, or select the discard checkbox to refresh without saving.';
        return;
      }
      const focused = document.activeElement;
      refreshButton.disabled = true;
      button.disabled = true;
      try {
        // Fetch a current receipt/workspace, never apply a buffered stale page.
        await checkStatus({refresh: true, discard: discard.checked});
      } catch {
        showUncertain();
        refreshMessage.textContent = 'Saved content could not be refreshed. Your current edits have been kept.';
      } finally {
        refreshButton.disabled = false;
        reset();
        if (focused === refreshButton && document.activeElement === document.body) refreshButton.focus({preventScroll: true});
      }
    });
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (button.disabled) return;
      const initialScroll = [window.scrollX, window.scrollY];
      const focused = document.activeElement;
      button.disabled = true;
      announceLoading(checking);
      loading.hidden = false;
      result.replaceChildren();
      result.className = '';
      window.scrollTo(...initialScroll);
      let completionScroll;
      try {
        if (checking) {
          await checkStatus();
        } else {
          try {
            receiptKey = form.querySelector('[name="request_key"]').value;
            const response = await fetch(form.dataset.generationUrl, {
              method: 'POST', body: new FormData(form), credentials: 'same-origin', cache: 'no-store'
            });
            await applyResponse(response);
          } catch {
            // Includes a lost POST response and a failed GET following its 303.
            // Only the read-only status endpoint is called automatically.
            checking = true;
            await checkStatus();
          }
        }
      } catch {
        showUncertain();
      } finally {
        completionScroll = [window.scrollX, window.scrollY];
        reset();
        if (focused === button && document.activeElement === document.body) button.focus({preventScroll: true});
        if (completionScroll) window.scrollTo(...completionScroll);
      }
    });
    window.addEventListener('pageshow', reset);
  });
  wireLinks();
  reveal(window.location.hash.slice(1));
})();
