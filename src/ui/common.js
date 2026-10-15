/**
 * RECRM Unified Frontend Core Library (common.js)
 * مكتبة الواجهة الموحدة لنظام RECRM
 * 
 * Provides centralized API client, toast notifications, confirmation modals,
 * data formatting, and pagination helpers across all 12 operational portals.
 */

(function(window) {
    'use strict';

    // -------------------------------------------------------------------------
    // 1. Toast Notification System
    // -------------------------------------------------------------------------
    function ensureToastContainer() {
        let container = document.getElementById('recrm-toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'recrm-toast-container';
            container.style.cssText = `
                position: fixed;
                bottom: 24px;
                right: 24px;
                z-index: 99999;
                display: flex;
                flex-direction: column;
                gap: 10px;
                max-width: 420px;
                width: calc(100% - 48px);
                pointer-events: none;
                font-family: 'Cairo', 'Tajawal', 'Almarai', -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            `;
            document.body.appendChild(container);
        }
        return container;
    }

    function showToast(message, type = 'info', duration = 3500) {
        if (!message) return;
        if (typeof message !== 'string') {
            message = message.message || JSON.stringify(message);
        }

        // Smart type detection if default 'info' was provided
        if (type === 'info') {
            const m = message.toLowerCase();
            if (m.includes('نجاح') || m.includes('بنجاح') || m.includes('تم ') || m.includes('success') || m.includes('saved') || m.includes('created') || m.includes('updated') || m.includes('copied') || m.includes('النسخ')) {
                type = 'success';
            } else if (m.includes('خطأ') || m.includes('فشل') || m.includes('error') || m.includes('failed') || m.includes('رفض') || m.includes('تعذر') || m.includes('غير مصرح')) {
                type = 'error';
            } else if (m.includes('تحذير') || m.includes('warning') || m.includes('يرجى') || m.includes('تنبيه') || m.includes('caution')) {
                type = 'warning';
            }
        }

        const container = ensureToastContainer();
        const toast = document.createElement('div');
        toast.className = `recrm-toast recrm-toast-${type}`;
        toast.style.cssText = `
            pointer-events: auto;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            padding: 12px 18px;
            border-radius: 10px;
            font-size: 0.9em;
            font-weight: 600;
            line-height: 1.4;
            box-shadow: 0 8px 24px -4px rgba(0, 0, 0, 0.18);
            direction: rtl;
            transition: all 0.25s ease-out;
            opacity: 0;
            transform: translateY(16px);
        `;

        let icon = 'ℹ️';
        let bg = '#1e293b';
        let textCol = '#ffffff';
        let borderCol = '#334155';

        if (type === 'success') {
            icon = '✓';
            bg = '#065f46';
            borderCol = '#059669';
        } else if (type === 'error' || type === 'danger') {
            icon = '✗';
            bg = '#991b1b';
            borderCol = '#dc2626';
        } else if (type === 'warning') {
            icon = '⚠️';
            bg = '#92400e';
            borderCol = '#d97706';
        } else if (type === 'info') {
            icon = 'ℹ️';
            bg = '#0c4a6e';
            borderCol = '#0284c7';
        }

        toast.style.background = bg;
        toast.style.color = textCol;
        toast.style.border = `1.5px solid ${borderCol}`;

        toast.innerHTML = `
            <div style="display: flex; align-items: center; gap: 10px; flex: 1;">
                <span style="font-size: 1.25em; line-height: 1;">${icon}</span>
                <span>${message}</span>
            </div>
            <button type="button" style="background: none; border: none; color: rgba(255,255,255,0.7); font-size: 1.2em; cursor: pointer; padding: 0 4px; line-height: 1;">&times;</button>
        `;

        const closeBtn = toast.querySelector('button');
        const dismiss = () => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(16px)';
            setTimeout(() => { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 250);
        };

        closeBtn.onclick = dismiss;
        container.appendChild(toast);

        // Animate in
        requestAnimationFrame(() => {
            toast.style.opacity = '1';
            toast.style.transform = 'translateY(0)';
        });

        if (duration > 0) {
            setTimeout(dismiss, duration);
        }

        // Backward compatibility: hide legacy #toast element to prevent double rendering
        const legacyToast = document.getElementById('toast');
        if (legacyToast) {
            legacyToast.style.display = 'none';
        }

        return toast;
    }

    // -------------------------------------------------------------------------
    // 2. Confirmation Modal System
    // -------------------------------------------------------------------------
    function confirmDialog({
        title = 'تأكيد الإجراء / Confirm Action',
        message = 'هل أنت متأكد من رغبتك في متابعة هذا الإجراء؟',
        confirmText = 'تأكيد (Confirm)',
        cancelText = 'إلغاء (Cancel)',
        type = 'primary' // 'primary' | 'danger' | 'warning'
    }) {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'recrm-confirm-overlay';
            overlay.style.cssText = `
                position: fixed;
                top: 0; left: 0; right: 0; bottom: 0;
                background: rgba(15, 23, 42, 0.65);
                backdrop-filter: blur(2px);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 100000;
                direction: rtl;
                font-family: inherit;
            `;

            let confirmBtnBg = '#2563eb';
            if (type === 'danger') confirmBtnBg = '#dc2626';
            else if (type === 'warning') confirmBtnBg = '#d97706';

            overlay.innerHTML = `
                <div style="background: white; border-radius: 14px; max-width: 480px; width: 92%; overflow: hidden; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.25); animation: recrmModalIn 0.2s ease-out;">
                    <div style="padding: 18px 22px; background: #0f172a; color: white; display: flex; justify-content: space-between; align-items: center;">
                        <div style="font-weight: 700; font-size: 1.05em;">${title}</div>
                        <button type="button" class="recrm-close-x" style="background: none; border: none; color: #94a3b8; font-size: 1.4em; cursor: pointer; line-height: 1;">&times;</button>
                    </div>
                    <div style="padding: 22px; font-size: 0.95em; color: #334155; line-height: 1.6;">
                        ${message}
                    </div>
                    <div style="padding: 14px 22px; background: #f8fafc; border-top: 1px solid #e2e8f0; display: flex; justify-content: flex-end; gap: 10px;">
                        <button type="button" class="recrm-cancel-btn" style="background: #e2e8f0; color: #1e293b; border: none; padding: 8px 18px; border-radius: 6px; font-weight: 600; font-size: 0.9em; cursor: pointer;">${cancelText}</button>
                        <button type="button" class="recrm-confirm-btn" style="background: ${confirmBtnBg}; color: white; border: none; padding: 8px 20px; border-radius: 6px; font-weight: 700; font-size: 0.9em; cursor: pointer;">${confirmText}</button>
                    </div>
                </div>
            `;

            const cleanup = (result) => {
                overlay.style.opacity = '0';
                setTimeout(() => { if (overlay.parentNode) overlay.parentNode.removeChild(overlay); }, 150);
                resolve(result);
            };

            overlay.querySelector('.recrm-close-x').onclick = () => cleanup(false);
            overlay.querySelector('.recrm-cancel-btn').onclick = () => cleanup(false);
            overlay.querySelector('.recrm-confirm-btn').onclick = () => cleanup(true);

            overlay.onclick = (e) => {
                if (e.target === overlay) cleanup(false);
            };

            document.body.appendChild(overlay);
        });
    }

    // -------------------------------------------------------------------------
    // 3. Centralized REST API Client
    // -------------------------------------------------------------------------
    function getApiBase() {
        if (typeof API_BASE !== 'undefined') return API_BASE;
        if (window.location.protocol === 'file:') return 'http://localhost:8000';
        if (window.location.port === '8000' || window.location.port === '') return '';
        const host = window.location.hostname || 'localhost';
        return `${window.location.protocol}//${host}:8000`;
    }

    async function apiRequest(endpoint, options = {}) {
        const base = getApiBase();
        const url = endpoint.startsWith('http') ? endpoint : `${base}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;
        
        options.headers = options.headers || {};
        if (!(options.headers instanceof Headers)) {
            options.headers['Content-Type'] = options.headers['Content-Type'] || 'application/json';
            const activeUser = localStorage.getItem('recrm_user_id') || 'user-51';
            options.headers['X-User-ID'] = options.headers['X-User-ID'] || activeUser;
        }

        try {
            const response = await fetch(url, options);
            const contentType = response.headers.get('content-type') || '';
            const isJson = contentType.includes('application/json');
            const data = isJson ? await response.json() : await response.text();

            if (!response.ok) {
                let errorMessage = `Request failed with status ${response.status}`;
                if (isJson && data) {
                    if (data.error && data.error.message) {
                        errorMessage = data.error.message;
                    } else if (data.detail) {
                        errorMessage = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
                    } else if (data.message) {
                        errorMessage = data.message;
                    }
                }
                const err = new Error(errorMessage);
                err.status = response.status;
                err.data = data;
                throw err;
            }

            return data;
        } catch (err) {
            console.error(`API Error [${options.method || 'GET'} ${url}]:`, err);
            throw err;
        }
    }

    const api = {
        get: (endpoint, options = {}) => apiRequest(endpoint, { ...options, method: 'GET' }),
        post: (endpoint, body, options = {}) => apiRequest(endpoint, { ...options, method: 'POST', body: JSON.stringify(body) }),
        patch: (endpoint, body, options = {}) => apiRequest(endpoint, { ...options, method: 'PATCH', body: JSON.stringify(body) }),
        delete: (endpoint, options = {}) => apiRequest(endpoint, { ...options, method: 'DELETE' }),
        getBaseUrl: getApiBase
    };

    // -------------------------------------------------------------------------
    // 4. Data Formatting Utilities
    // -------------------------------------------------------------------------
    const format = {
        currency: function(amount, currency = 'SAR') {
            if (amount === null || amount === undefined || isNaN(amount)) return '0.00 ' + currency;
            const num = parseFloat(amount);
            const parts = num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            return `${parts} ${currency}`;
        },

        number: function(val, decimals = 0) {
            if (val === null || val === undefined || isNaN(val)) return '0';
            return parseFloat(val).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
        },

        date: function(dateStr, includeTime = false) {
            if (!dateStr) return '--';
            try {
                const d = new Date(dateStr);
                if (isNaN(d.getTime())) return String(dateStr);
                const yyyy = d.getFullYear();
                const mm = String(d.getMonth() + 1).padStart(2, '0');
                const dd = String(d.getDate()).padStart(2, '0');
                if (!includeTime) return `${yyyy}-${mm}-${dd}`;
                const hh = String(d.getHours()).padStart(2, '0');
                const min = String(d.getMinutes()).padStart(2, '0');
                return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
            } catch (e) {
                return String(dateStr);
            }
        },

        phone: function(phoneStr) {
            if (!phoneStr) return '--';
            let clean = String(phoneStr).trim();
            if (clean.startsWith('05') && clean.length === 10) {
                return `+966 ${clean.substring(1, 3)} ${clean.substring(3, 6)} ${clean.substring(6)}`;
            }
            return clean;
        },

        statusBadge: function(status) {
            if (!status) return '<span class="status-badge">--</span>';
            const s = String(status).toUpperCase();
            let bg = '#e2e8f0';
            let color = '#334155';

            if (['ACTIVE', 'QUALIFIED', 'WON', 'CLOSED_WON', 'AVAILABLE', 'PAID', 'COMPLETED', 'RESOLVED'].includes(s)) {
                bg = '#dcfce7'; color = '#15803d';
            } else if (['NEW', 'OPEN', 'PENDING', 'RESERVED', 'PARTIAL', 'IN_PROGRESS'].includes(s)) {
                bg = '#fef3c7'; color = '#b45309';
            } else if (['LOST', 'CLOSED_LOST', 'CANCELLED', 'OVERDUE', 'REJECTED', 'DISQUALIFIED'].includes(s)) {
                bg = '#fee2e2'; color = '#b91c1c';
            } else if (['RENTED', 'OCCUPIED', 'CONTRACTED', 'PROPOSAL', 'OFFER'].includes(s)) {
                bg = '#e0f2fe'; color = '#0369a1';
            }

            return `<span style="background: ${bg}; color: ${color}; font-weight: 700; font-size: 0.8em; padding: 3px 8px; border-radius: 4px; display: inline-block;">${s}</span>`;
        }
    };

    // -------------------------------------------------------------------------
    // 5. General Utilities
    // -------------------------------------------------------------------------
    const utils = {
        debounce: function(func, wait = 300) {
            let timeout;
            return function(...args) {
                clearTimeout(timeout);
                timeout = setTimeout(() => func.apply(this, args), wait);
            };
        },

        copyToClipboard: function(text, successMsg = 'تم النسخ إلى الحافظة بنجاح!') {
            if (!text || text === '--') return;
            const str = String(text).trim();
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(str)
                    .then(() => showToast(`${successMsg} (${str})`, 'success', 2500))
                    .catch(() => showToast(`تم النسخ: ${str}`, 'info', 2500));
            } else {
                // Fallback
                const ta = document.createElement('textarea');
                ta.value = str;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                showToast(`${successMsg} (${str})`, 'success', 2500);
            }
        },

        escapeHtml: function(unsafe) {
            if (unsafe === null || unsafe === undefined) return '';
            return String(unsafe)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        },

        getQueryParam: function(key) {
            const params = new URLSearchParams(window.location.search);
            return params.get(key);
        }
    };

    // -------------------------------------------------------------------------
    // 6. Pagination Bar Component Renderer
    // -------------------------------------------------------------------------
    function renderPagination(containerId, {
        page = 1,
        pageSize = 25,
        total = 0,
        onPageChange,
        onPageSizeChange,
        pageSizeOptions = [15, 25, 50, 100]
    }) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const totalPages = Math.max(1, Math.ceil(total / pageSize));
        const startRecord = total === 0 ? 0 : (page - 1) * pageSize + 1;
        const endRecord = Math.min(total, page * pageSize);

        let sizeOptionsHtml = pageSizeOptions.map(opt => 
            `<option value="${opt}" ${opt === pageSize ? 'selected' : ''}>${opt}</option>`
        ).join('');

        container.style.cssText = `
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
            padding: 14px 18px;
            background: #ffffff;
            border-top: 1px solid #e2e8f0;
            font-size: 0.88em;
            color: #64748b;
        `;

        container.innerHTML = `
            <div>
                عرض <strong style="color: #0f172a;">${startRecord}</strong> إلى <strong style="color: #0f172a;">${endRecord}</strong> من إجمالي <strong style="color: #0f172a;">${total}</strong> سجل
                <span style="opacity: 0.6; margin-inline-start: 6px;">(Showing ${startRecord}-${endRecord} of ${total})</span>
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
                <label style="font-size: 0.9em;">لكل صفحة:</label>
                <select class="recrm-pagesize-sel" style="padding: 4px 8px; border: 1px solid #cbd5e1; border-radius: 4px; background: white; font-size: 0.9em;">
                    ${sizeOptionsHtml}
                </select>
                <button type="button" class="recrm-prev-btn btn-page" ${page <= 1 ? 'disabled style="opacity: 0.5; cursor: not-allowed;"' : 'style="cursor: pointer;"'}>
                    ◀ السابق
                </button>
                <span style="font-weight: 700; color: #0f172a; padding: 0 4px;">صفحة ${page} من ${totalPages}</span>
                <button type="button" class="recrm-next-btn btn-page" ${page >= totalPages ? 'disabled style="opacity: 0.5; cursor: not-allowed;"' : 'style="cursor: pointer;"'}>
                    التالي ▶
                </button>
            </div>
        `;

        const prevBtn = container.querySelector('.recrm-prev-btn');
        const nextBtn = container.querySelector('.recrm-next-btn');
        const sizeSel = container.querySelector('.recrm-pagesize-sel');

        if (prevBtn && page > 1) {
            prevBtn.onclick = () => onPageChange && onPageChange(page - 1);
        }
        if (nextBtn && page < totalPages) {
            nextBtn.onclick = () => onPageChange && onPageChange(page + 1);
        }
        if (sizeSel) {
            sizeSel.onchange = (e) => onPageSizeChange && onPageSizeChange(parseInt(e.target.value, 10));
        }
    }

    // -------------------------------------------------------------------------
    // 7. Global Namespace Export
    // -------------------------------------------------------------------------
    const RECRM = {
        api,
        ui: {
            toast: showToast,
            confirm: confirmDialog,
            renderPagination
        },
        format,
        utils
    };

    window.RECRM = RECRM;

    // Backward compatibility globals
    window.showToast = showToast;
    window.copyId = utils.copyToClipboard;
    window.formatCurrency = format.currency;
    window.formatDate = format.date;

})(window);
