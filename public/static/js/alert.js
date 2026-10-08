// Safe alert dismissal logic. Handles multi-alerts and is error-free.
document.addEventListener('DOMContentLoaded', () => {
  const closeBtns = document.querySelectorAll('.alert .close, .alert .btn-close');
  closeBtns.forEach(btn => {
    btn.addEventListener('click', (e) => {
      const alert = e.target.closest('.alert');
      if (alert) {
        alert.style.opacity = '0';
        setTimeout(() => alert.remove(), 150);
      }
    });
  });
});