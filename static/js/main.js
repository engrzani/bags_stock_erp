// ============================================================
// Bags Stock ERP — Main JavaScript
// ============================================================

// ─── Current date in navbar ───
(function updateNavDate() {
  const el = document.getElementById('currentDate');
  if (!el) return;
  const now = new Date();
  const options = { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' };
  el.textContent = now.toLocaleDateString('en-PK', options);
})();

// ─── Sidebar Toggle ───
const sidebarEl    = document.getElementById('sidebar');
const mainWrapper  = document.getElementById('mainWrapper');
const toggleBtn    = document.getElementById('sidebarToggle');

if (toggleBtn) {
  toggleBtn.addEventListener('click', () => {
    const isMobile = window.innerWidth <= 768;
    if (isMobile) {
      sidebarEl.classList.toggle('open');
    } else {
      sidebarEl.classList.toggle('collapsed');
      mainWrapper.classList.toggle('expanded');
    }
  });
}

// ─── Auto-dismiss alerts after 5s ───
document.querySelectorAll('.custom-alert').forEach(alert => {
  setTimeout(() => {
    const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
    if (bsAlert) bsAlert.close();
  }, 5000);
});

// ─── Confirm before delete ───
document.querySelectorAll('form[data-confirm]').forEach(form => {
  form.addEventListener('submit', e => {
    if (!confirm(form.dataset.confirm)) e.preventDefault();
  });
});
