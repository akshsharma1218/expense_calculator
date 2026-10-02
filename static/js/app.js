document.addEventListener('DOMContentLoaded', function () {
  initSidebar();
  initAnimations();
  initToasts();
  initCounters();
  initPasswordToggles();
  initSelects();
  initLinkedModal();
});

function initSidebar() {
  const sidebar = document.getElementById('sidebar');
  const toggle = document.getElementById('sidebarToggle');
  const backdrop = document.getElementById('sidebarBackdrop');
  const appShell = document.getElementById('appShell');
  const desktopQuery = window.matchMedia('(min-width: 1201px)');
  let previousBodyOverflow = null;

  if (!sidebar || !toggle) return;

  function updateExpanded(isExpanded) {
    toggle.setAttribute('aria-expanded', String(isExpanded));
    toggle.setAttribute('aria-label', desktopQuery.matches
      ? (isExpanded ? 'Collapse sidebar' : 'Expand sidebar')
      : (isExpanded ? 'Close navigation' : 'Open navigation'));
    const icon = toggle.querySelector('i');
    if (icon) icon.className = `bi ${isExpanded ? 'bi-layout-sidebar-inset' : 'bi-layout-sidebar'}`;
  }

  function lockPageScroll() {
    if (previousBodyOverflow === null) previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
  }

  function restorePageScroll() {
    if (previousBodyOverflow === null) return;
    document.body.style.overflow = previousBodyOverflow;
    previousBodyOverflow = null;
  }

  function open() {
    sidebar.classList.add('open');
    backdrop?.classList.add('show');
    lockPageScroll();
    updateExpanded(true);
  }

  function close() {
    sidebar.classList.remove('open');
    backdrop?.classList.remove('show');
    restorePageScroll();
    updateExpanded(false);
  }

  function syncViewport() {
    if (desktopQuery.matches) {
      sidebar.classList.remove('open');
      backdrop?.classList.remove('show');
      restorePageScroll();
      appShell?.classList.toggle(
        'sidebar-collapsed',
        window.localStorage.getItem('finflow-sidebar-collapsed') === 'true',
      );
    } else {
      appShell?.classList.remove('sidebar-collapsed');
      close();
      return;
    }
    updateExpanded(!appShell?.classList.contains('sidebar-collapsed'));
  }

  toggle.addEventListener('click', () => {
    if (desktopQuery.matches) {
      const isCollapsed = appShell?.classList.toggle('sidebar-collapsed') ?? false;
      window.localStorage.setItem('finflow-sidebar-collapsed', String(isCollapsed));
      updateExpanded(!isCollapsed);
      return;
    }

    sidebar.classList.contains('open') ? close() : open();
  });

  backdrop?.addEventListener('click', close);

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !desktopQuery.matches && sidebar.classList.contains('open')) {
      close();
    }
  });

  desktopQuery.addEventListener('change', syncViewport);
  syncViewport();

  document.querySelectorAll('.sidebar-nav .nav-item').forEach((link) => {
    link.addEventListener('click', () => {
      if (!desktopQuery.matches) close();
    });
  });
}

function initAnimations() {
  document.querySelectorAll('[data-animate]').forEach((el, index) => {
    el.style.animationDelay = `${index * 80}ms`;
  });
}

function initToasts() {
  document.querySelectorAll('[data-toast]').forEach((toast) => {
    setTimeout(() => {
      toast.style.transition = 'opacity 0.4s, transform 0.4s';
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(24px)';
      setTimeout(() => toast.remove(), 400);
    }, 4500);
  });
}

function initCounters() {
  document.querySelectorAll('[data-count]').forEach((el) => {
    const target = parseFloat(el.dataset.count);
    if (isNaN(target)) return;

    const prefix = el.dataset.prefix || '';
    const suffix = el.dataset.suffix || '';
    const duration = 1200;
    const start = performance.now();

    function tick(now) {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = target * eased;
      el.textContent = prefix + current.toLocaleString('en-IN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }) + suffix;
      if (progress < 1) requestAnimationFrame(tick);
    }

    requestAnimationFrame(tick);
  });
}

function initPasswordToggles() {
  document.addEventListener('click', (event) => {
    const toggle = event.target.closest('[data-password-toggle]');
    if (!toggle) return;
    const input = document.getElementById(toggle.dataset.passwordToggle);
    if (!input) return;
    const visible = input.type === 'password';
    input.type = visible ? 'text' : 'password';
    toggle.setAttribute('aria-pressed', String(visible));
    toggle.setAttribute('aria-label', visible ? 'Hide password' : 'Show password');
    toggle.querySelector('i')?.classList.toggle('bi-eye', !visible);
    toggle.querySelector('i')?.classList.toggle('bi-eye-slash', visible);
  });
}

function initSelects() {
  if (typeof TomSelect === 'undefined') return;
  document.querySelectorAll('.form-select:not([data-native-select])').forEach((el) => {
    if (el.tomselect) return;
    new TomSelect(el, {
      create: false,
      placeholder: 'Select',
      allowEmptyOption: true,
      closeAfterSelect: !el.multiple,
      dropdownParent: 'body',
    });
  });
}

function initLinkedModal() {
  if (typeof bootstrap === 'undefined') return;

  function showModalFromHash() {
    if (!window.location.hash) return;
    const modal = document.getElementById(decodeURIComponent(window.location.hash.slice(1)));
    if (modal?.classList.contains('modal')) {
      bootstrap.Modal.getOrCreateInstance(modal).show();
    }
  }

  showModalFromHash();
  window.addEventListener('hashchange', showModalFromHash);
  document.addEventListener('click', (event) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest('a[href]');
    if (!link) return;

    const targetUrl = new URL(link.href, window.location.href);
    if (
      targetUrl.origin !== window.location.origin
      || targetUrl.pathname !== window.location.pathname
      || targetUrl.search !== window.location.search
      || !targetUrl.hash
    ) return;

    const modal = document.getElementById(decodeURIComponent(targetUrl.hash.slice(1)));
    if (!modal?.classList.contains('modal')) return;

    event.preventDefault();
    if (window.location.hash !== targetUrl.hash) window.location.hash = targetUrl.hash;
    bootstrap.Modal.getOrCreateInstance(modal).show();
  });
}

function formatINR(value) {
  return '₹' + Number(value).toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

window.FinFlow = { formatINR };
