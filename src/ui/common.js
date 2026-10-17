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
        title = null,
        message = null,
        confirmText = null,
        cancelText = null,
        type = 'primary' // 'primary' | 'danger' | 'warning'
    }) {
        return new Promise((resolve) => {
            const isAr = (typeof currentLang !== 'undefined' && currentLang === 'ar') || 
                         (typeof window.currentLang !== 'undefined' && window.currentLang === 'ar') || 
                         (localStorage.getItem('recrm_lang') !== 'en');

            const resolvedTitle = title || (isAr ? 'تأكيد الإجراء' : 'Confirm Action');
            const resolvedMessage = message || (isAr ? 'هل أنت متأكد من رغبتك في متابعة هذا الإجراء؟' : 'Are you sure you want to proceed?');
            const resolvedConfirm = confirmText || (isAr ? 'تأكيد' : 'Confirm');
            const resolvedCancel = cancelText || (isAr ? 'إلغاء' : 'Cancel');

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
                direction: ${isAr ? 'rtl' : 'ltr'};
                font-family: inherit;
            `;

            let confirmBtnBg = '#2563eb';
            if (type === 'danger') confirmBtnBg = '#dc2626';
            else if (type === 'warning') confirmBtnBg = '#d97706';

            overlay.innerHTML = `
                <div style="background: white; border-radius: 14px; max-width: 480px; width: 92%; overflow: hidden; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.25); animation: recrmModalIn 0.2s ease-out;">
                    <div style="padding: 18px 22px; background: #0f172a; color: white; display: flex; justify-content: space-between; align-items: center;">
                        <div style="font-weight: 700; font-size: 1.05em;">${resolvedTitle}</div>
                        <button type="button" class="recrm-close-x" style="background: none; border: none; color: #94a3b8; font-size: 1.4em; cursor: pointer; line-height: 1;">&times;</button>
                    </div>
                    <div style="padding: 22px; font-size: 0.95em; color: #334155; line-height: 1.6;">
                        ${resolvedMessage}
                    </div>
                    <div style="padding: 14px 22px; background: #f8fafc; border-top: 1px solid #e2e8f0; display: flex; justify-content: flex-end; gap: 10px;">
                        <button type="button" class="recrm-cancel-btn" style="background: #e2e8f0; color: #1e293b; border: none; padding: 8px 18px; border-radius: 6px; font-weight: 600; font-size: 0.9em; cursor: pointer;">${resolvedCancel}</button>
                        <button type="button" class="recrm-confirm-btn" style="background: ${confirmBtnBg}; color: white; border: none; padding: 8px 20px; border-radius: 6px; font-weight: 700; font-size: 0.9em; cursor: pointer;">${resolvedConfirm}</button>
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

        copyToClipboard: function(text, successMsg = null) {
            if (!text || text === '--') return;
            const isAr = (typeof currentLang !== 'undefined' && currentLang === 'ar') || 
                         (typeof window.currentLang !== 'undefined' && window.currentLang === 'ar') || 
                         (localStorage.getItem('recrm_lang') !== 'en');
            const msg = successMsg || (isAr ? 'تم النسخ إلى الحافظة بنجاح!' : 'Copied to clipboard successfully!');
            const str = String(text).trim();
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(str)
                    .then(() => showToast(`${msg} (${str})`, 'success', 2500))
                    .catch(() => showToast(`${isAr ? 'تم النسخ' : 'Copied'}: ${str}`, 'info', 2500));
            } else {
                // Fallback
                const ta = document.createElement('textarea');
                ta.value = str;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                showToast(`${msg} (${str})`, 'success', 2500);
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

        const isAr = (typeof currentLang !== 'undefined' && currentLang === 'ar') || 
                     (typeof window.currentLang !== 'undefined' && window.currentLang === 'ar') || 
                     (localStorage.getItem('recrm_lang') !== 'en');

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

        const countHtml = isAr
            ? `عرض <strong style="color: #0f172a;">${startRecord}</strong> إلى <strong style="color: #0f172a;">${endRecord}</strong> من إجمالي <strong style="color: #0f172a;">${total}</strong> سجل`
            : `Showing <strong style="color: #0f172a;">${startRecord}</strong> to <strong style="color: #0f172a;">${endRecord}</strong> of <strong style="color: #0f172a;">${total}</strong> records`;

        const perPageLabel = isAr ? 'لكل صفحة:' : 'Per page:';
        const prevLabel = isAr ? '◀ السابق' : '◀ Prev';
        const pageLabel = isAr ? `صفحة ${page} من ${totalPages}` : `Page ${page} of ${totalPages}`;
        const nextLabel = isAr ? 'التالي ▶' : 'Next ▶';

        container.innerHTML = `
            <div>
                ${countHtml}
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
                <label style="font-size: 0.9em;">${perPageLabel}</label>
                <select class="recrm-pagesize-sel" style="padding: 4px 8px; border: 1px solid #cbd5e1; border-radius: 4px; background: white; font-size: 0.9em;">
                    ${sizeOptionsHtml}
                </select>
                <button type="button" class="recrm-prev-btn btn-page" ${page <= 1 ? 'disabled style="opacity: 0.5; cursor: not-allowed;"' : 'style="cursor: pointer;"'}>
                    ${prevLabel}
                </button>
                <span style="font-weight: 700; color: #0f172a; padding: 0 4px;">${pageLabel}</span>
                <button type="button" class="recrm-next-btn btn-page" ${page >= totalPages ? 'disabled style="opacity: 0.5; cursor: not-allowed;"' : 'style="cursor: pointer;"'}>
                    ${nextLabel}
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
    // 8. Situation & Operational Journey Modal
    // -------------------------------------------------------------------------
    async function openSituationModal({ leadId, oppId }) {
        if (!leadId && !oppId) {
            console.error('openSituationModal requires leadId or oppId');
            return;
        }

        const isAr = (typeof currentLang !== 'undefined' && currentLang === 'ar') || 
                     (typeof window.currentLang !== 'undefined' && window.currentLang === 'ar') || 
                     (localStorage.getItem('recrm_lang') !== 'en');

        // Remove existing overlay if any
        let existingOverlay = document.getElementById('recrm-situation-modal-overlay');
        if (existingOverlay && existingOverlay.parentNode) {
            existingOverlay.parentNode.removeChild(existingOverlay);
        }

        const overlay = document.createElement('div');
        overlay.id = 'recrm-situation-modal-overlay';
        overlay.style.cssText = `
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(15, 23, 42, 0.7);
            backdrop-filter: blur(4px);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 100000;
            direction: ${isAr ? 'rtl' : 'ltr'};
            font-family: inherit;
        `;

        overlay.innerHTML = `
            <div style="background: #ffffff; border-radius: 14px; max-width: 860px; width: 94%; max-height: 90vh; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.3); animation: recrmModalIn 0.2s ease-out;">
                <div style="padding: 16px 22px; background: #0f172a; color: white; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #1e293b;">
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <span style="font-size: 1.3em;">📍</span>
                        <div>
                            <div style="font-weight: 700; font-size: 1.1em; line-height: 1.2;">
                                ${isAr ? 'مسار المعاملة والتشخيص التشغيلي' : 'Transaction Situation & Journey'}
                            </div>
                            <div style="font-size: 0.78em; color: #94a3b8; margin-top: 2px;">
                                ${isAr ? 'تتبع فوري لكافة المهام والأنشطة والتعثر التشغيلي' : 'Real-time operational status, stalled detection & journey history'}
                            </div>
                        </div>
                    </div>
                    <button type="button" class="recrm-situation-close" style="background: none; border: none; color: #94a3b8; font-size: 1.5em; cursor: pointer; line-height: 1; padding: 4px 8px;">&times;</button>
                </div>
                <div class="recrm-situation-body" style="padding: 24px; overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: 16px;">
                    <div style="text-align: center; padding: 40px; color: #64748b;">
                        <div style="font-size: 2em; animation: spin 1s linear infinite; display: inline-block;">⏳</div>
                        <div style="margin-top: 10px; font-weight: 600;">${isAr ? 'جاري جلب تفاصيل المسار والتشخيص التشغيلي...' : 'Loading operational situation...'}</div>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(overlay);

        const closeBtn = overlay.querySelector('.recrm-situation-close');
        const cleanup = () => {
            overlay.style.opacity = '0';
            setTimeout(() => { if (overlay.parentNode) overlay.parentNode.removeChild(overlay); }, 150);
        };
        closeBtn.onclick = cleanup;
        overlay.onclick = (e) => {
            if (e.target === overlay) cleanup();
        };

        const loadData = async () => {
            try {
                const endpoint = leadId 
                    ? `/api/v1/leads/${encodeURIComponent(leadId)}/situation` 
                    : `/api/v1/opportunities/${encodeURIComponent(oppId)}/situation`;
                
                const res = await apiRequest(endpoint);
                const data = res.data;
                renderSituation(data);
            } catch (err) {
                const body = overlay.querySelector('.recrm-situation-body');
                if (body) {
                    body.innerHTML = `
                        <div style="padding: 24px; text-align: center; background: #fef2f2; border: 1px solid #fecaca; border-radius: 10px; color: #991b1b;">
                            <div style="font-size: 1.5em; margin-bottom: 8px;">⚠️</div>
                            <div style="font-weight: 700; margin-bottom: 6px;">${isAr ? 'تعذر جلب بيانات المسار' : 'Failed to load transaction situation'}</div>
                            <div style="font-size: 0.88em; color: #b91c1c;">${err.message || err}</div>
                            <button type="button" class="recrm-retry-btn" style="margin-top: 14px; background: #dc2626; color: white; border: none; padding: 6px 16px; border-radius: 6px; cursor: pointer; font-weight: 600;">${isAr ? 'إعادة المحاولة' : 'Retry'}</button>
                        </div>
                    `;
                    const retryBtn = body.querySelector('.recrm-retry-btn');
                    if (retryBtn) retryBtn.onclick = loadData;
                }
            }
        };

        const executeUnblock = async (actionCode, targetLeadId, targetOppId) => {
            try {
                const unblockEndpoint = targetLeadId 
                    ? `/api/v1/leads/${encodeURIComponent(targetLeadId)}/unblock` 
                    : `/api/v1/opportunities/${encodeURIComponent(targetOppId)}/unblock`;
                
                const btnContainer = overlay.querySelector('.recrm-unblock-actions');
                if (btnContainer) {
                    btnContainer.innerHTML = `<div style="color: #0369a1; font-weight: 600; padding: 8px;">⏳ ${isAr ? 'جاري تنفيذ الإجراء وتوليد المهمة...' : 'Unblocking transaction & spawning workflow task...'}</div>`;
                }

                await apiRequest(unblockEndpoint, {
                    method: 'POST',
                    body: JSON.stringify({ action: actionCode })
                });

                showToast(
                    isAr ? 'تم تنشيط مسار المعاملة وتوليد المهمة المطلوبة بنجاح!' : 'Transaction resumed and task spawned successfully!',
                    'success'
                );

                // Reload data to reflect updated situation
                await loadData();
            } catch (err) {
                showToast(
                    (isAr ? 'فشل تنفيذ الإجراء: ' : 'Failed to unblock: ') + (err.message || err),
                    'error'
                );
                await loadData();
            }
        };

        const renderSituation = (d) => {
            const body = overlay.querySelector('.recrm-situation-body');
            if (!body) return;

            // Stalled banner
            let stalledBannerHtml = '';
            if (d.is_stalled) {
                const actionsHtml = (d.recommended_actions || []).map(act => `
                    <button type="button" class="recrm-unblock-action-btn" data-action="${act.action}" style="
                        background: #0284c7; color: white; border: none; padding: 8px 16px; border-radius: 6px;
                        font-weight: 600; font-size: 0.88em; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;
                        transition: background 0.2s; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                    ">
                        ${isAr ? act.label_ar : act.label_en}
                    </button>
                `).join('');

                stalledBannerHtml = `
                    <div style="background: #fffbeb; border: 1px solid #fde68a; border-radius: 10px; padding: 16px; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
                        <div style="display: flex; align-items: flex-start; gap: 10px;">
                            <span style="font-size: 1.4em; line-height: 1;">⚠️</span>
                            <div style="flex: 1;">
                                <div style="font-weight: 700; color: #92400e; font-size: 0.98em;">
                                    ${isAr ? 'المعاملة متعثرة تشغيلياً (بدون مهام نشطة حالياً)' : 'Operationally Stalled Deal (0 Open Tasks)'}
                                </div>
                                <div style="font-size: 0.88em; color: #b45309; margin-top: 4px; line-height: 1.5;">
                                    ${isAr ? (d.stalled_reason_ar || '') : (d.stalled_reason_en || '')}
                                </div>
                                <div style="margin-top: 12px;">
                                    <div style="font-size: 0.82em; font-weight: 700; color: #78350f; margin-bottom: 8px;">
                                        ${isAr ? '⚡ الإجراءات الفورية المقترحة لفك التعثر بضغطة واحدة:' : '⚡ Recommended 1-Click Unblock Actions:'}
                                    </div>
                                    <div class="recrm-unblock-actions" style="display: flex; flex-wrap: wrap; gap: 8px;">
                                        ${actionsHtml || `<span style="font-size: 0.85em; color: #92400e;">${isAr ? 'لا توجد إجراءات محددة' : 'No specific actions'}</span>`}
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            } else {
                stalledBannerHtml = `
                    <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 10px; padding: 12px 16px; display: flex; align-items: center; gap: 10px;">
                        <span style="font-size: 1.3em;">✅</span>
                        <div>
                            <div style="font-weight: 700; color: #166534; font-size: 0.92em;">
                                ${isAr ? 'المعاملة نشطة ولديها مهام ومواعيد متابعة' : 'Transaction Active with Scheduled Work'}
                            </div>
                            <div style="font-size: 0.82em; color: #15803d; margin-top: 2px;">
                                ${isAr ? `توجد (${(d.pending_tasks || []).length}) مهام جارية تضمن تقدم المعاملة نحو الإغلاق` : `There are (${(d.pending_tasks || []).length}) pending tasks advancing this deal.`}
                            </div>
                        </div>
                    </div>
                `;
            }

            // Info cards
            const infoCardsHtml = `
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px;">
                    <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 14px;">
                        <div style="font-size: 0.76em; color: #64748b; font-weight: 600;">${isAr ? 'العميل' : 'Customer'}</div>
                        <div style="font-weight: 700; color: #0f172a; margin-top: 2px; font-size: 0.95em;">${d.customer_name || '--'}</div>
                        <div style="font-size: 0.78em; color: #64748b; margin-top: 2px;">📞 ${d.customer_mobile || '--'}</div>
                    </div>
                    <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 14px;">
                        <div style="font-size: 0.76em; color: #64748b; font-weight: 600;">${isAr ? 'المرحلة الحالية' : 'Current Stage'}</div>
                        <div style="margin-top: 4px;">
                            <span style="background: #e0f2fe; color: #0369a1; padding: 3px 8px; border-radius: 5px; font-weight: 700; font-size: 0.85em; display: inline-block;">
                                ${d.current_stage || '--'}
                            </span>
                        </div>
                    </div>
                    <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 14px;">
                        <div style="font-size: 0.76em; color: #64748b; font-weight: 600;">${isAr ? 'الوسيط المسؤول' : 'Assigned Agent'}</div>
                        <div style="font-weight: 700; color: #0f172a; margin-top: 2px; font-size: 0.92em;">👤 ${d.assigned_agent_name || (isAr ? 'غير محدد' : 'Unassigned')}</div>
                        <div style="font-size: 0.76em; color: #64748b; margin-top: 2px;">${isAr ? 'المدير: ' : 'Mgr: '} ${d.manager_name || '--'}</div>
                    </div>
                    <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 14px;">
                        <div style="font-size: 0.76em; color: #64748b; font-weight: 600;">${isAr ? 'المعرفات' : 'Entity Identifiers'}</div>
                        <div style="font-size: 0.82em; margin-top: 3px; display: flex; flex-direction: column; gap: 2px;">
                            ${d.lead_id ? `<div>${isAr ? 'الطلب: ' : 'Lead: '} <span style="font-family: monospace; background: #e2e8f0; padding: 1px 5px; border-radius: 4px;">${d.lead_id}</span></div>` : ''}
                            ${d.opportunity_id ? `<div>${isAr ? 'الصفقة: ' : 'Deal: '} <span style="font-family: monospace; background: #e2e8f0; padding: 1px 5px; border-radius: 4px;">${d.opportunity_id}</span></div>` : ''}
                        </div>
                    </div>
                </div>
            `;

            // Metrics Row
            const metricsHtml = `
                <div style="display: flex; flex-wrap: wrap; gap: 8px; font-size: 0.8em;">
                    <span style="background: #f1f5f9; padding: 4px 10px; border-radius: 6px; border: 1px solid #e2e8f0; color: #334155;">
                        📋 ${isAr ? 'المهام المنجزة: ' : 'Completed Tasks: '} <strong>${d.completed_tasks_count || 0}</strong>
                    </span>
                    <span style="background: #f1f5f9; padding: 4px 10px; border-radius: 6px; border: 1px solid #e2e8f0; color: #334155;">
                        📝 ${isAr ? 'الأنشطة: ' : 'Activities: '} <strong>${d.activities_count || 0}</strong>
                    </span>
                    <span style="background: #f1f5f9; padding: 4px 10px; border-radius: 6px; border: 1px solid #e2e8f0; color: #334155;">
                        👁️ ${isAr ? 'المعاينات: ' : 'Viewings: '} <strong>${d.viewings_count || 0}</strong>
                    </span>
                    <span style="background: #f1f5f9; padding: 4px 10px; border-radius: 6px; border: 1px solid #e2e8f0; color: #334155;">
                        💬 ${isAr ? 'المراسلات: ' : 'Comms: '} <strong>${d.communications_count || 0}</strong>
                    </span>
                    <span style="background: #f1f5f9; padding: 4px 10px; border-radius: 6px; border: 1px solid #e2e8f0; color: #334155;">
                        💼 ${isAr ? 'العروض: ' : 'Offers: '} <strong>${d.offers_count || 0}</strong>
                    </span>
                    <span style="background: #f1f5f9; padding: 4px 10px; border-radius: 6px; border: 1px solid #e2e8f0; color: #334155;">
                        🔒 ${isAr ? 'الحجوزات: ' : 'Reservations: '} <strong>${d.reservations_count || 0}</strong>
                    </span>
                    <span style="background: #f1f5f9; padding: 4px 10px; border-radius: 6px; border: 1px solid #e2e8f0; color: #334155;">
                        🤝 ${isAr ? 'العقود: ' : 'Contracts: '} <strong>${d.contracts_count || 0}</strong>
                    </span>
                </div>
            `;

            // Pending Tasks Box
            let pendingTasksHtml = '';
            if (d.pending_tasks && d.pending_tasks.length > 0) {
                const listItems = d.pending_tasks.map(t => {
                    const dueStr = t.due_date ? new Date(t.due_date).toLocaleString() : '--';
                    return `
                        <div style="background: white; border: 1px solid #cbd5e1; border-radius: 6px; padding: 10px 12px; display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                            <div>
                                <div style="font-weight: 700; font-size: 0.9em; color: #0f172a;">${t.title}</div>
                                <div style="font-size: 0.78em; color: #64748b; margin-top: 3px;">
                                    <span>🆔 ${t.task_id}</span> • 
                                    <span>👤 ${t.assignee_name || (isAr ? 'غير مسند' : 'Unassigned')}</span> • 
                                    <span>⏰ ${dueStr}</span>
                                </div>
                            </div>
                            <div style="display: flex; align-items: center; gap: 6px;">
                                <span style="font-size: 0.74em; font-weight: 700; padding: 2px 6px; border-radius: 4px; background: #e0e7ff; color: #3730a3;">
                                    ${t.priority || 'NORMAL'}
                                </span>
                                <a href="tasks.html?task_id=${encodeURIComponent(t.task_id)}" class="btn-sm" style="font-size: 0.78em; padding: 3px 8px; background: #0f172a; color: white; border-radius: 4px; text-decoration: none;" target="_blank">
                                    ${isAr ? 'فتح في المهام' : 'Open'}
                                </a>
                            </div>
                        </div>
                    `;
                }).join('');

                pendingTasksHtml = `
                    <div style="border: 1px solid #cbd5e1; border-radius: 8px; padding: 14px; background: #f8fafc;">
                        <div style="font-weight: 700; font-size: 0.92em; color: #1e293b; margin-bottom: 8px; display: flex; justify-content: space-between;">
                            <span>⏳ ${isAr ? 'المهام المعلقة الجارية' : 'Active Pending Tasks'} (${d.pending_tasks.length})</span>
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 6px;">
                            ${listItems}
                        </div>
                    </div>
                `;
            }

            // Timeline Items
            const timeline = d.timeline || [];
            let timelineHtml = '';
            if (timeline.length === 0) {
                timelineHtml = `
                    <div style="text-align: center; padding: 24px; color: #94a3b8; font-size: 0.9em;">
                        ${isAr ? 'لا توجد أنشطة مسجلة حتى الآن في مسار المعاملة' : 'No activities recorded yet in the journey timeline.'}
                    </div>
                `;
            } else {
                const getIcon = (tp) => {
                    switch (tp) {
                        case 'TASK': return '📋';
                        case 'ACTIVITY': return '📝';
                        case 'COMMUNICATION': return '💬';
                        case 'VIEWING': return '👁️';
                        case 'OFFER': return '💼';
                        case 'RESERVATION': return '🔒';
                        case 'CONTRACT': return '🤝';
                        default: return '📌';
                    }
                };

                const itemsHtml = timeline.map(item => {
                    const dt = item.timestamp ? new Date(item.timestamp).toLocaleString(undefined, {
                        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
                    }) : '--';
                    
                    const outcomeBadge = item.outcome ? `
                        <span style="font-size: 0.72em; font-weight: 700; padding: 2px 6px; border-radius: 4px; background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0;">
                            ${item.outcome}
                        </span>
                    ` : '';

                    return `
                        <div style="position: relative; padding-bottom: 16px; padding-inline-start: 28px;">
                            <div style="
                                position: absolute;
                                ${isAr ? 'right: 0;' : 'left: 0;'}
                                top: 2px;
                                width: 20px;
                                height: 20px;
                                border-radius: 50%;
                                background: #e2e8f0;
                                display: flex;
                                align-items: center;
                                justify-content: center;
                                font-size: 0.75em;
                            ">
                                ${getIcon(item.type)}
                            </div>
                            <div style="display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 6px;">
                                <div style="display: flex; align-items: center; gap: 6px;">
                                    <strong style="font-size: 0.9em; color: #0f172a;">${item.subject || item.type}</strong>
                                    ${outcomeBadge}
                                </div>
                                <div style="font-size: 0.76em; color: #64748b;">
                                    ${dt} ${item.user_name ? `• ${item.user_name}` : ''}
                                </div>
                            </div>
                            ${item.description ? `
                                <div style="font-size: 0.84em; color: #475569; margin-top: 4px; background: #f8fafc; padding: 6px 10px; border-radius: 6px; border: 1px solid #f1f5f9; line-height: 1.4;">
                                    ${item.description}
                                </div>
                            ` : ''}
                        </div>
                    `;
                }).join('');

                timelineHtml = `
                    <div style="border-top: 1px solid #e2e8f0; padding-top: 16px;">
                        <div style="font-weight: 700; font-size: 0.95em; color: #1e293b; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center;">
                            <span>📜 ${isAr ? 'السجل الزمني للمسار والأنشطة' : 'Chronological Journey Timeline'} (${timeline.length})</span>
                            <span style="font-size: 0.8em; color: #64748b; font-weight: normal;">${isAr ? 'مرتب من الأحدث للأقدم' : 'Latest first'}</span>
                        </div>
                        <div style="
                            position: relative;
                            margin-inline-start: 8px;
                            border-inline-start: 2px solid #e2e8f0;
                        ">
                            ${itemsHtml}
                        </div>
                    </div>
                `;
            }

            body.innerHTML = `
                ${stalledBannerHtml}
                ${infoCardsHtml}
                ${metricsHtml}
                ${pendingTasksHtml}
                ${timelineHtml}
            `;

            // Bind unblock buttons
            const actionBtns = body.querySelectorAll('.recrm-unblock-action-btn');
            actionBtns.forEach(btn => {
                btn.onclick = () => {
                    const actCode = btn.getAttribute('data-action');
                    executeUnblock(actCode, d.lead_id, d.opportunity_id);
                };
            });
        };

        // Fetch and show data
        await loadData();
    }

    // -------------------------------------------------------------------------
    // 9. Global Namespace Export
    // -------------------------------------------------------------------------
    const RECRM = {
        api,
        ui: {
            toast: showToast,
            confirm: confirmDialog,
            renderPagination,
            openSituationModal
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
    window.openSituationModal = openSituationModal;

})(window);
