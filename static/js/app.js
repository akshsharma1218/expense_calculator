document.addEventListener('DOMContentLoaded', function () {
  initSidebar();
  initAnimations();
  initToasts();
  initCounters();
});

function initSidebar() {
  const sidebar = document.getElementById('sidebar');
  const toggle = document.getElementById('sidebarToggle');
  const backdrop = document.getElementById('sidebarBackdrop');

  if (!sidebar || !toggle) return;

  function open() {
    sidebar.classList.add('open');
    backdrop?.classList.add('show');
    document.body.style.overflow = 'hidden';
  }

  function close() {
    sidebar.classList.remove('open');
    backdrop?.classList.remove('show');
    document.body.style.overflow = '';
  }

  toggle.addEventListener('click', () => {
    sidebar.classList.contains('open') ? close() : open();
  });

  backdrop?.addEventListener('click', close);

  document.querySelectorAll('.sidebar-nav .nav-item').forEach((link) => {
    link.addEventListener('click', () => {
      if (window.innerWidth < 992) close();
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

function formatINR(value) {
  return '₹' + Number(value).toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

document.querySelectorAll(".form-select").forEach((el) => {
    new TomSelect(el, {
        create: false,
        placeholder: "Select",
        allowEmptyOption: true,
    });
});

window.FinFlow = { formatINR };
