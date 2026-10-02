/**
 * Realtime notification bell — listens for Django Channels events and loads
 * saved notifications so they remain visible after refresh or offline periods.
 */
(function () {
    const bell = document.getElementById('notificationBell');
    const badge = document.getElementById('notificationBadge');
    const list = document.getElementById('notificationList');

    if (!bell || !badge || !list) {
        return;
    }

    const entries = new Map();
    const pendingReadUpdates = new Set();
    const csrfToken = document.querySelector(
        '#notificationCsrfForm [name="csrfmiddlewaretoken"]'
    )?.value;
    let unreadCount = 0;
    let initialLoadComplete = false;

    function renderNotifications() {
        list.replaceChildren();

        const latestEntries = [...entries.values()].sort(
            (left, right) => new Date(right.created_at) - new Date(left.created_at)
        );
        for (const payload of latestEntries) {
            const item = document.createElement('div');
            item.className = 'notification-item';
            if (!payload.is_read) {
                item.classList.add('unread');
            }

            const body = document.createElement('button');
            body.className = 'notification-item-body';
            body.type = 'button';
            body.title = payload.is_read ? '' : 'Click to mark as read';
            body.setAttribute(
                'aria-label',
                payload.is_read
                    ? payload.message
                    : `Mark as read: ${payload.message}`
            );
            body.disabled = payload.is_read || pendingReadUpdates.has(payload.notification_id);
            body.addEventListener('click', () => {
                markNotificationRead(payload.notification_id);
            });

            const icon = document.createElement('i');
            icon.className = payload.event.startsWith('group_invitation.')
                ? 'bi bi-people-fill'
                : 'bi bi-info-circle';

            const message = document.createElement('span');
            message.textContent = payload.message;
            body.append(icon, message);
            item.appendChild(body);

            if (payload.event === 'group_invitation.created') {
                const actions = document.createElement('div');
                actions.className = 'notification-item-actions';
                const link = document.createElement('a');
                link.href = bell.dataset.invitationsUrl;
                link.className = 'btn btn-sm btn-primary';
                link.textContent = 'Review';
                link.addEventListener('click', () => {
                    markNotificationRead(payload.notification_id, true);
                });
                actions.appendChild(link);
                item.appendChild(actions);
            } else if (
                payload.group_id
                && payload.event.startsWith('group_')
                && payload.event !== 'group_member.removed'
            ) {
                const actions = document.createElement('div');
                actions.className = 'notification-item-actions';
                const link = document.createElement('a');
                const groupUrl = `/groups/${encodeURIComponent(payload.group_id)}/`;
                link.href = payload.event.startsWith('group_settlement.')
                    ? `${groupUrl}settle/`
                    : groupUrl;
                link.className = 'btn btn-sm btn-outline-primary';
                link.textContent = 'Open group';
                link.addEventListener('click', () => {
                    markNotificationRead(payload.notification_id, true);
                });
                actions.appendChild(link);
                item.appendChild(actions);
            }

            list.appendChild(item);
        }

        if (entries.size === 0) {
            const empty = document.createElement('div');
            empty.className = 'notification-empty';
            empty.textContent = 'No new notifications';
            list.appendChild(empty);
        }

        if (unreadCount > 0) {
            badge.textContent = unreadCount > 9 ? '9+' : String(unreadCount);
            badge.classList.remove('d-none');
        } else {
            badge.classList.add('d-none');
        }
    }

    function addNotificationEntry(payload, shouldShowToast = true) {
        const key = payload.notification_id || payload.id
            ? `notification:${payload.notification_id || payload.id}`
            : `${payload.event}:${payload.invitation_id || ''}`;
        const isNew = !entries.has(key);
        if (isNew && !payload.is_read) {
            unreadCount += 1;
        }
        entries.set(key, payload);
        renderNotifications();

        if (isNew && shouldShowToast) {
            showToast(payload.message);
        }
    }

    async function markNotificationRead(notificationId, keepalive = false) {
        const key = `notification:${notificationId}`;
        const payload = entries.get(key);
        if (!payload || payload.is_read || pendingReadUpdates.has(notificationId)) {
            return;
        }

        payload.is_read = true;
        unreadCount = Math.max(0, unreadCount - 1);
        pendingReadUpdates.add(notificationId);
        renderNotifications();

        try {
            const response = await fetch(
                bell.dataset.notificationReadUrl.replace(
                    '00000000-0000-0000-0000-000000000000',
                    encodeURIComponent(notificationId)
                ),
                {
                    method: 'POST',
                    credentials: 'same-origin',
                    keepalive: keepalive,
                    headers: {
                        'X-CSRFToken': csrfToken,
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                }
            );
            if (!response.ok) {
                throw new Error(`Mark notification read failed (${response.status})`);
            }
            const result = await response.json();
            unreadCount = result.unread_count;
        } catch (err) {
            console.error('Failed to mark notification as read', err);
            if (!keepalive) {
                payload.is_read = false;
                unreadCount += 1;
            }
        } finally {
            pendingReadUpdates.delete(notificationId);
            renderNotifications();
        }
    }

    async function markAllNotificationsRead() {
        const unreadEntries = [...entries.values()].filter(
            (notification) => !notification.is_read
        );
        if (!unreadEntries.length) {
            return;
        }

        unreadEntries.forEach((notification) => {
            notification.is_read = true;
        });
        unreadCount = 0;
        renderNotifications();

        try {
            const response = await fetch(bell.dataset.notificationReadAllUrl, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest',
                },
            });
            if (!response.ok) {
                throw new Error(`Mark all notifications read failed (${response.status})`);
            }
            const result = await response.json();
            unreadCount = result.unread_count;
        } catch (err) {
            console.error('Failed to mark notifications as read', err);
            await loadNotifications();
        } finally {
            renderNotifications();
        }
    }

    async function loadNotifications() {
        try {
            const response = await fetch(bell.dataset.notificationsUrl, {
                credentials: 'same-origin',
            });
            if (!response.ok) {
                throw new Error(`Notification refresh failed (${response.status})`);
            }

            const data = await response.json();
            const notifications = data.notifications || [];
            const currentIds = new Set(notifications.map((notification) => notification.id));
            const liveUnreadIds = new Set(
                [...entries.entries()]
                    .filter(([key, notification]) =>
                        key.startsWith('notification:')
                        && !notification.is_read
                        && !currentIds.has(key.slice(13))
                    )
                    .map(([key]) => key.slice(13))
            );

            for (const notification of notifications) {
                const key = `notification:${notification.id}`;
                addNotificationEntry({
                    ...notification,
                    notification_id: notification.id,
                }, initialLoadComplete && !entries.has(key));
            }

            for (const key of entries.keys()) {
                if (key.startsWith('notification:') && !currentIds.has(key.slice(13))) {
                    entries.delete(key);
                }
            }

            unreadCount = data.unread_count + liveUnreadIds.size;
            initialLoadComplete = true;
            renderNotifications();
        } catch (err) {
            console.error('Failed to load notifications', err);
        }
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

        const icon = document.createElement('i');
        icon.className = 'bi bi-bell-fill';
        const text = document.createElement('span');
        text.textContent = message;
        const close = document.createElement('button');
        close.className = 'toast-close';
        close.setAttribute('aria-label', 'Dismiss notification');
        close.innerHTML = '<i class="bi bi-x"></i>';
        close.addEventListener('click', () => toast.remove());

        toast.append(icon, text, close);
        stack.appendChild(toast);
        setTimeout(() => toast.remove(), 8000);
    }

    function connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
        const socket = new WebSocket(
            `${protocol}${window.location.host}/ws/notifications/`
        );

        socket.addEventListener('message', (event) => {
            try {
                addNotificationEntry(JSON.parse(event.data));
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

    renderNotifications();
    loadNotifications();
    setInterval(loadNotifications, 30000);
    const dropdown = document.getElementById('notificationDropdown');
    if (dropdown) {
        const dropdownObserver = new MutationObserver(() => {
            if (dropdown.classList.contains('show')) {
                markAllNotificationsRead();
            }
        });
        dropdownObserver.observe(dropdown, {
            attributes: true,
            attributeFilter: ['class'],
        });
    }
    connect();
})();
