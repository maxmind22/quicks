// Auto-dismiss and interactive dismissal logic for flash alert notifications
document.addEventListener('DOMContentLoaded', () => {
  function dismissAlert(alert) {
    if (!alert || alert.dataset.dismissing === 'true') return;
    alert.dataset.dismissing = 'true';

    // Smooth CSS fade-out, collapse, and removal
    alert.style.transition = 'opacity 0.4s ease, transform 0.4s ease, max-height 0.4s ease, margin 0.4s ease, padding 0.4s ease';
    alert.style.opacity = '0';
    alert.style.transform = 'translateY(-6px)';

    setTimeout(() => {
      alert.style.maxHeight = '0';
      alert.style.paddingTop = '0';
      alert.style.paddingBottom = '0';
      alert.style.marginTop = '0';
      alert.style.marginBottom = '0';
      alert.style.overflow = 'hidden';
      setTimeout(() => alert.remove(), 400);
    }, 200);
  }

  // Handle manual clicks on close buttons (.btn-close, .close)
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.alert .close, .alert .btn-close');
    if (btn) {
      const alert = btn.closest('.alert');
      if (alert) {
        dismissAlert(alert);
      }
    }
  });

  // Automatically dismiss flash notifications after 4 seconds
  const flashAlerts = document.querySelectorAll('.alert.alert-dismissible:not(.alert-permanent)');
  flashAlerts.forEach(alert => {
    let timer = setTimeout(() => {
      dismissAlert(alert);
    }, 4000);

    // Pause timer if user hovers over notification
    alert.addEventListener('mouseenter', () => clearTimeout(timer));
    alert.addEventListener('mouseleave', () => {
      timer = setTimeout(() => dismissAlert(alert), 1800);
    });
  });
});