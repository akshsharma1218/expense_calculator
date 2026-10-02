/**
 * Realtime notification bell — connects to the Django Channels websocket
 * endpoint and renders incoming group invitation notifications as toasts
 * plus entries in the notification dropdown.
 */
(function () {
    const bell = document.getElementById('notificationBell');
    const badge = document.getElementById('notificationBadge');
    const list = document.getElementById('notificationList');

    if (!bell || !badge || !list) {
        return;
    }

    let unreadCount = 0;

    function updateBadge() {
        if (unreadCount > 0) {
            badge.textContent = unreadCount > 9 ? '9+' : String(unreadCount);
            badge.classList.remove('d-none');
        } else {
            badge.classList.add('d-none');
        }
    }

    function clearEmptyState() {
        const empty = list.querySelector('.notification-empty');
        if (empty) {
            empty.remove();
        }
    }

    function addNotificationEntry(payload) {
        clearEmptyState();
        unreadCount += 1;
        updateBadge();

        const item = document.createElement('div');
        item.className = 'notification-item';

        if (payload.event === 'group_invitation.created') {
            item.innerHTML = `
                <div class="notification-item-body">
                    <i class="bi bi-people-fill"></i>
                    <span>${payload.message}</span>
                </div>
                <div class="notification-item-actions">
                    <a href="/groups/invitations/" class="btn btn-sm btn-primary">Review</a>
                </div>
            `;
        } else {
            item.innerHTML = `
                <div class="notification-item-body">
                    <i class="bi bi-info-circle"></i>
                    <span>${payload.message}</span>
                </div>
            `;
        }

        list.prepend(item);
        showToast(payload.message);
    }

    function showToast(message) {
        const stack = document.getElementById('toastStack') || (function () {
            const el = document.createElement('div');
            el.className = 'toast-stack';
            el.id = 'toastStack';
            document.body.appendChild(el);
            return el;
        })();

        const toast = document.createElement('div');
        toast.className = 'app-toast toast-info';
        toast.innerHTML = `
            <i class="bi bi-bell-fill"></i>
            <span>${message}</span>
            <button class="toast-close" onclick="this.parentElement.remove()"><i class="bi bi-x"></i></button>
        `;
        stack.appendChild(toast);
        setTimeout(() => toast.remove(), 8000);
    }

    function connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
        const socket = new WebSocket(`${protocol}${window.location.host}/ws/notifications/`);

        socket.addEventListener('message', (event) => {
            try {
                const payload = JSON.parse(event.data);
                addNotificationEntry(payload);
            } catch (err) {
                console.error('Failed to parse notification payload', err);
            }
        });

        socket.addEventListener('close', () => {
            setTimeout(connect, 3000);
        });

        socket.addEventListener('error', () => {
            socket.close();
        });
    }

    connect();
})();
