document.addEventListener('DOMContentLoaded', () => {
    const themeSwitch = document.querySelector('.theme-switch');
    if (themeSwitch) {
        themeSwitch.addEventListener('click', () => {
            document.body.classList.toggle('light-theme');
            localStorage.setItem('theme', document.body.classList.contains('light-theme') ? 'light' : 'dark');
            showToast(`Тема изменена на ${document.body.classList.contains('light-theme') ? 'светлую' : 'тёмную'}`);
        });
    }
    if (localStorage.getItem('theme') === 'light') document.body.classList.add('light-theme');

    document.querySelectorAll('.fade-in').forEach(el => el.style.opacity = 1);

    document.querySelectorAll('.confirm-action').forEach(btn => {
        btn.addEventListener('click', (e) => {
            if (!confirm('Вы уверены?')) e.preventDefault();
        });
    });

    const canvas = document.getElementById('submissionsChart');
    if (canvas) {
        fetch('/api/analytics/daily?period=7d')
            .then(r => r.json())
            .then(data => {
                new Chart(canvas, {
                    type: 'line',
                    data: {
                        labels: data.dates,
                        datasets: [
                            { label: 'Заявки', data: data.submissions, borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.1)', tension: 0.3, fill: true },
                            { label: 'Выплаты ($)', data: data.revenue, borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.1)', tension: 0.3, fill: true }
                        ]
                    },
                    options: { responsive: true, plugins: { tooltip: { mode: 'index' } }, scales: { y: { beginAtZero: true, grid: { color: '#334155' }, ticks: { color: '#cbd5e1' } }, x: { ticks: { color: '#cbd5e1' } } } }
                });
            });
    }

    const statusCanvas = document.getElementById('statusChart');
    if (statusCanvas) {
        const ratio = JSON.parse(statusCanvas.dataset.ratio || '{"accepted":0,"rejected":0,"pending":0}');
        new Chart(statusCanvas, {
            type: 'doughnut',
            data: { labels: ['Принятые', 'Отклонённые', 'В обработке'], datasets: [{ data: [ratio.accepted, ratio.rejected, ratio.pending], backgroundColor: ['#10b981', '#ef4444', '#f59e0b'], borderWidth: 0 }] },
            options: { responsive: true, plugins: { legend: { position: 'bottom', labels: { color: '#e2e8f0' } } } }
        });
    }

    setInterval(() => {
        fetch('/api/status').then(r => r.json()).catch(e => console.warn);
    }, 30000);

    window.onclick = function(event) {
        if (event.target.classList && event.target.classList.contains('modal')) {
            event.target.style.display = 'none';
        }
    };
});

function showToast(message, type = 'info') {
    const container = document.querySelector('.toast-container') || (() => { let div = document.createElement('div'); div.className = 'toast-container'; document.body.appendChild(div); return div; })();
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerText = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

function openModal(id) { document.getElementById(id).style.display = 'flex'; }
function closeModal(id) { document.getElementById(id).style.display = 'none'; }