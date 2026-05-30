/* SmartTrack v2 - Main JavaScript */

// CSRF Token helper
function getCookie(name) {
  let v = document.cookie.match('(^|;) ?' + name + '=([^;]*)(;|$)');
  return v ? v[2] : null;
}
const csrfToken = getCookie('csrftoken');

// Toast & confirm modals — see static/js/smarttrack_ui.js (showToast, showConfirmModal)

// Auto-dismiss alert messages
document.addEventListener('DOMContentLoaded', () => {
  // Auto-hide Django messages after 5s
  document.querySelectorAll('.animate-slide-in').forEach(el => {
    setTimeout(() => {
      el.style.opacity = '0';
      el.style.transition = 'opacity 0.3s';
      setTimeout(() => el.remove(), 300);
    }, 6000);
  });

  // Sidebar: mark active link
  const path = window.location.pathname;
  document.querySelectorAll('.sidebar-link').forEach(link => {
    if (link.getAttribute('href') === path) {
      link.classList.add('active');
    }
  });

  // Animate bar chart bars on load
  document.querySelectorAll('[style*="height"]').forEach(bar => {
    const targetH = bar.style.height;
    bar.style.height = '0%';
    setTimeout(() => {
      bar.style.transition = 'height 0.6s cubic-bezier(0.34, 1.56, 0.64, 1)';
      bar.style.height = targetH;
    }, 100);
  });

  // Animate progress rings
  document.querySelectorAll('[stroke-dasharray]').forEach(path => {
    const target = path.getAttribute('stroke-dasharray');
    path.setAttribute('stroke-dasharray', '0, 100');
    setTimeout(() => {
      path.style.transition = 'stroke-dasharray 1s ease';
      path.setAttribute('stroke-dasharray', target);
    }, 200);
  });

  // Init unread count polling
  if (document.querySelector('.sidebar-link')) {
    pollNotifications();
  }
});

// Poll for unread notifications
function pollNotifications() {
  setInterval(() => {
    fetch('/notifications/unread-count/')
      .then(r => r.json())
      .then(data => {
        const badges = document.querySelectorAll('.notif-badge');
        badges.forEach(b => {
          if (data.count > 0) {
            b.textContent = data.count;
            b.style.display = 'flex';
          } else {
            b.style.display = 'none';
          }
        });
      }).catch(() => {});
  }, 30000);
}

// Sidebar toggle
function toggleSidebar() {
  const sb = document.getElementById('sidebar');
  if (sb) {
    sb.classList.toggle('-translate-x-full');
    sb.classList.toggle('open');
  }
}

// Password strength checker
function checkPasswordStrength(password) {
  const checks = {
    length:  password.length >= 8,
    upper:   /[A-Z]/.test(password),
    lower:   /[a-z]/.test(password),
    number:  /\d/.test(password),
    special: /[!@#$%^&*(),.?":{}|<>]/.test(password),
  };
  const score = Object.values(checks).filter(Boolean).length;
  return { checks, score };
}

// Medicine mark taken with animation
function animateMarkTaken(btn) {
  btn.classList.add('scale-95');
  setTimeout(() => btn.classList.remove('scale-95'), 150);
}

// Number Counter Animation
function animateCounter(el, target, duration = 1000) {
  const start = 0;
  const step = (target / duration) * 16;
  let current = start;
  const timer = setInterval(() => {
    current += step;
    if (current >= target) {
      el.textContent = target;
      clearInterval(timer);
    } else {
      el.textContent = Math.floor(current);
    }
  }, 16);
}

// Animate stat numbers on dashboard load
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.stat-card .text-3xl').forEach(el => {
    const val = parseInt(el.textContent);
    if (!isNaN(val) && val > 0) {
      animateCounter(el, val, 800);
    }
  });
});

// Debounce utility
function debounce(fn, delay) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), delay);
  };
}

// Global search send request
function sendRequest(targetId, btn) {
  fetch('/connections/send-request/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'X-CSRFToken': csrfToken
    },
    body: `target_id=${targetId}&message=Hello, I'd like to connect with you.`
  })
  .then(r => r.json())
  .then(data => {
    if (data.success) {
      btn.textContent = 'Request Sent';
      btn.className = 'text-xs bg-amber-100 text-amber-700 px-3 py-1 rounded-full font-medium';
      btn.disabled = true;
      showToast('Connection request sent!', 'success');
    } else {
      showToast(data.error || 'Could not send request', 'error');
    }
  })
  .catch(() => showToast('Network error', 'error'));
}

// Format time helper
function formatTime(dateStr) {
  return new Date(dateStr).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

// Scroll to element
function scrollTo(id) {
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/* Video consultation join flow lives in static/js/video_join.js (loaded from base_dashboard.html). */
