// Global User Session & RBAC Handler for RECRM
(function() {
    let currentUserProfile = null;

    function getApiBase() {
        if (typeof API_BASE !== 'undefined') return API_BASE;
        if (window.location.protocol === 'file:') return 'http://localhost:8000';
        if (window.location.port === '8000' || window.location.port === '') return '';
        const host = window.location.hostname || 'localhost';
        return `${window.location.protocol}//${host}:8000`;
    }

    // Intercept window.fetch to automatically include X-User-ID header
    const originalFetch = window.fetch;
    window.fetch = function(url, options = {}) {
        try {
            const urlParams = new URLSearchParams(window.location.search);
            const activeUserId = urlParams.get('user_id') || localStorage.getItem('recrm_user_id') || 'user-51';
            const urlStr = typeof url === 'string' ? url : (url && url.url ? url.url : '');

            if (urlStr.includes('/api/v1/')) {
                options = options || {};
                options.headers = options.headers || {};
                if (options.headers instanceof Headers) {
                    if (!options.headers.has('X-User-ID')) {
                        options.headers.set('X-User-ID', activeUserId);
                    }
                } else if (Array.isArray(options.headers)) {
                    if (!options.headers.some(([k]) => k.toLowerCase() === 'x-user-id')) {
                        options.headers.push(['X-User-ID', activeUserId]);
                    }
                } else {
                    if (!options.headers['X-User-ID'] && !options.headers['x-user-id']) {
                        options.headers['X-User-ID'] = activeUserId;
                    }
                }
            }
        } catch (e) {
            console.warn('Error injecting X-User-ID into fetch:', e);
        }
        return originalFetch.call(this, url, options);
    };

    async function loadUserProfile() {
        try {
            const urlParams = new URLSearchParams(window.location.search);
            const queryUser = urlParams.get('user_id') || urlParams.get('u');
            if (queryUser) {
                localStorage.setItem('recrm_user_id', queryUser);
            }
            const activeUserId = localStorage.getItem('recrm_user_id') || 'user-51';
            const apiBase = getApiBase();
            
            const res = await fetch(`${apiBase}/api/v1/me?user_id=${encodeURIComponent(activeUserId)}`);
            if (!res.ok) throw new Error('Failed to load user profile');
            const json = await res.json();
            currentUserProfile = json.data;

            // Update top bar name display
            const nameDisplay = document.getElementById('user-name-display');
            if (nameDisplay && currentUserProfile) {
                const roleName = (currentUserProfile.roles && currentUserProfile.roles[0]) 
                    ? currentUserProfile.roles[0].name 
                    : (currentUserProfile.role_codes ? currentUserProfile.role_codes[0] : 'SYS_ADMIN');
                const isOwn = currentUserProfile.effective_scope === 'OWN';
                const scopeBadge = isOwn 
                    ? `<span style="background: #f59e0b; color: white; padding: 1px 6px; border-radius: 4px; font-size: 0.8em; font-weight: 700; margin-inline-start: 4px;">🔒 OWN SCOPE</span>`
                    : `<span style="background: #10b981; color: white; padding: 1px 6px; border-radius: 4px; font-size: 0.8em; font-weight: 700; margin-inline-start: 4px;">🛡️ ${roleName}</span>`;

                nameDisplay.innerHTML = `<strong>${currentUserProfile.full_name}</strong> <span style="opacity: 0.85; font-size: 0.85em; background: rgba(255,255,255,0.22); padding: 1px 6px; border-radius: 4px; margin-inline-start: 4px;">${currentUserProfile.user_id}</span> ${scopeBadge}`;
            }

            // Dispatch global event for pages that want to sync their UI
            window.dispatchEvent(new CustomEvent('recrm:user-ready', { 
                detail: { 
                    profile: currentUserProfile, 
                    userId: activeUserId, 
                    isOwnScope: currentUserProfile.effective_scope === 'OWN' 
                } 
            }));

            // Auto-apply data scoping to on-page filters
            applyDataScopingToPage();

        } catch (err) {
            console.warn('Error loading user profile:', err);
            const nameDisplay = document.getElementById('user-name-display');
            if (nameDisplay) nameDisplay.textContent = 'Fahad Kh. Alnemari (user-51)';
        }
    }

    function applyDataScopingToPage() {
        if (!currentUserProfile) return;
        const isOwn = currentUserProfile.effective_scope === 'OWN';
        const userId = currentUserProfile.user_id;
        const userName = currentUserProfile.full_name;

        // 1. Sales Pipeline Page filter
        const oppAgFilter = document.getElementById('opp-agent-filter');
        if (oppAgFilter && isOwn) {
            oppAgFilter.innerHTML = `<option value="${userId}" selected>🔒 ${userName} (${userId}) - بياناتي فقط</option>`;
            oppAgFilter.disabled = true;
            if (typeof filterOpportunities === 'function') filterOpportunities();
            showScopeNotificationBanner(`🔒 تم تطبيق عزل البيانات الشخصية: يتم عرض الصفقات والفرص البيعية المسندة إليك فقط.`);
        }

        // 2. Leads Page filter
        const leadAgFilter = document.getElementById('agent-filter');
        if (leadAgFilter && isOwn) {
            leadAgFilter.innerHTML = `<option value="${userId}" selected>🔒 ${userName} (${userId}) - بياناتي فقط</option>`;
            leadAgFilter.disabled = true;
            if (typeof fetchLeads === 'function') fetchLeads(1);
            showScopeNotificationBanner(`🔒 تم تطبيق عزل البيانات الشخصية: يتم عرض العملاء المحتملين المسندين إليك فقط.`);
        }

        // 3. Tasks Page filter
        const taskAgFilter = document.getElementById('task-agent-filter');
        if (taskAgFilter && isOwn) {
            taskAgFilter.innerHTML = `<option value="${userId}" selected>🔒 ${userName} (${userId}) - مهامي فقط</option>`;
            taskAgFilter.disabled = true;
            if (typeof loadTasks === 'function') loadTasks();
            if (typeof loadSummary === 'function') loadSummary();
            showScopeNotificationBanner(`🔒 تم تطبيق عزل البيانات الشخصية: يتم عرض المهام والمتابعات المسندة إليك فقط.`);
        }

        // 4. Properties Page filter
        const unitAgFilter = document.getElementById('unit-agent-filter');
        if (unitAgFilter && isOwn) {
            unitAgFilter.innerHTML = `<option value="${userId}" selected>🔒 ${userName} (${userId}) - وحداتي فقط</option>`;
            unitAgFilter.disabled = true;
            if (typeof fetchUnits === 'function') fetchUnits();
            showScopeNotificationBanner(`🔒 تم تطبيق عزل البيانات الشخصية: يتم عرض الوحدات العقارية المسندة إليك فقط.`);
        }
    }

    function showScopeNotificationBanner(text) {
        if (document.getElementById('recrm-scope-banner')) return;
        const mainContainer = document.querySelector('.main-content') || document.querySelector('.container') || document.body;
        const banner = document.createElement('div');
        banner.id = 'recrm-scope-banner';
        banner.style.cssText = 'background: #eff6ff; border: 1.5px solid #93c5fd; color: #1e3a8a; padding: 10px 16px; border-radius: 8px; margin-bottom: 16px; font-size: 0.88em; font-weight: 600; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 4px rgba(0,0,0,0.04);';
        banner.innerHTML = `
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 1.2em;">🛡️</span>
                <span>${text}</span>
            </div>
            <div style="display: flex; gap: 8px; align-items: center;">
                <button type="button" onclick="window.switchActiveUser('user-51')" style="background: #2563eb; color: white; border: none; border-radius: 4px; padding: 4px 10px; font-size: 0.82em; cursor: pointer; font-weight: 700;">
                    العودة لمدير النظام (user-51)
                </button>
            </div>
        `;
        if (mainContainer.firstChild) {
            mainContainer.insertBefore(banner, mainContainer.firstChild);
        } else {
            mainContainer.appendChild(banner);
        }
    }

    function ensureUserProfileModal() {
        if (document.getElementById('user-profile-modal')) return;

        const modalDiv = document.createElement('div');
        modalDiv.id = 'user-profile-modal';
        modalDiv.className = 'modal-overlay';
        modalDiv.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(15, 23, 42, 0.55); backdrop-filter: blur(2px); display: none; justify-content: center; align-items: center; z-index: 2000;';
        modalDiv.onclick = function(e) { if (e.target === modalDiv) window.closeUserProfileModal(); };

        modalDiv.innerHTML = `
            <div class="modal-box" style="max-width: 740px; width: 95%; background: #fff; border-radius: 10px; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.25); overflow: hidden; font-family: inherit;">
                <div style="padding: 16px 20px; background: #0f172a; color: white; display: flex; justify-content: space-between; align-items: center;">
                    <div style="font-weight: 700; font-size: 1.05em; display: flex; align-items: center; gap: 8px;">
                        <span>🛡️</span>
                        <span>ملف المستخدم والأدوار وعزل البيانات (User Profile & RBAC)</span>
                    </div>
                    <button onclick="window.closeUserProfileModal()" style="background: none; border: none; color: #94a3b8; font-size: 1.4em; cursor: pointer; line-height: 1;">&times;</button>
                </div>
                
                <div style="padding: 20px; max-height: 75vh; overflow-y: auto;">
                    <!-- Identity Card -->
                    <div style="background: #f8fafc; border: 1.5px solid #cbd5e1; border-radius: 8px; padding: 14px 16px; margin-bottom: 16px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 10px;">
                            <div>
                                <div style="font-size: 1.25em; font-weight: 800; color: #0f172a;" id="modal-user-fullname">--</div>
                                <div style="font-size: 0.85em; color: #64748b; margin-top: 3px;">
                                    <span id="modal-user-email">--</span> • <span id="modal-user-mobile">--</span>
                                </div>
                            </div>
                            <div style="display: flex; gap: 6px; align-items: center;">
                                <span class="id-badge" style="background: #e2e8f0; color: #0f172a; font-size: 0.85em; font-weight: 700; padding: 4px 8px; border-radius: 4px;" id="modal-user-id">--</span>
                                <span style="background: #dcfce7; color: #166534; font-size: 0.82em; font-weight: 700; padding: 4px 8px; border-radius: 4px;">ACTIVE</span>
                            </div>
                        </div>

                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; font-size: 0.85em; border-top: 1px dashed #cbd5e1; padding-top: 10px;">
                            <div>
                                <span style="color: #64748b; font-size: 0.82em;">الفرع (Branch):</span>
                                <strong id="modal-user-branch" style="display: block; color: #0f172a; font-size: 0.95em;">--</strong>
                            </div>
                            <div>
                                <span style="color: #64748b; font-size: 0.82em;">نطاق البيانات (Data Scope):</span>
                                <strong id="modal-user-scope" style="display: block; color: #7c3aed; font-size: 0.95em;">GLOBAL</strong>
                            </div>
                            <div>
                                <span style="color: #64748b; font-size: 0.82em;">الأدوار (Assigned Roles):</span>
                                <div id="modal-user-roles" style="margin-top: 3px;">--</div>
                            </div>
                        </div>
                    </div>

                    <!-- Fast User Switcher -->
                    <div style="background: #eff6ff; border: 1.5px solid #bfdbfe; border-radius: 8px; padding: 14px 16px; margin-bottom: 18px;">
                        <label style="display: block; font-size: 0.88em; font-weight: 700; color: #1e3a8a; margin-bottom: 4px;">
                            🔄 تبديل المستخدم الحالي (Switch Active User Context):
                        </label>
                        <div style="font-size: 0.8em; color: #475569; margin-bottom: 8px;">
                            💡 عند اختيار وسيط ذو نطاق شخصي (OWN Scope)، يتم عزل وحجب بيانات المستخدمين الآخرين تلقائياً وعرض بيانات ذلك المستخدم فقط.
                        </div>
                        <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                            <select id="modal-user-switch-select" style="flex: 1; min-width: 260px; padding: 8px 10px; border-radius: 6px; border: 1px solid #93c5fd; font-size: 0.88em; background: white;">
                                <option value="">جاري تحميل المستخدمين...</option>
                            </select>
                            <button type="button" class="btn" onclick="window.switchActiveUser()" style="padding: 8px 16px; font-size: 0.88em; background: #0284c7; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: 600;">
                                تطبيق التبديل (Switch User)
                            </button>
                        </div>
                    </div>

                    <!-- Granted Permissions Section -->
                    <div>
                        <div style="font-weight: 700; font-size: 0.95em; color: #0f172a; margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between;">
                            <span>📋 الصلاحيات الممنوحة (Active Permissions):</span>
                            <span id="modal-perm-count-badge" style="font-size: 0.8em; background: #e0f2fe; color: #0369a1; padding: 2px 8px; border-radius: 4px; font-weight: 700;">--</span>
                        </div>
                        <div id="modal-user-permissions" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 8px; max-height: 220px; overflow-y: auto; padding: 2px;">
                            <!-- dynamic items -->
                        </div>
                    </div>
                </div>

                <div style="padding: 12px 20px; background: #f8fafc; border-top: 1px solid #e2e8f0; display: flex; justify-content: space-between; align-items: center;">
                    <div style="font-size: 0.82em; color: #64748b;">
                        المدير الافتراضي: <strong>user-51</strong> (فهد الخديدي النمري)
                    </div>
                    <button type="button" onclick="window.closeUserProfileModal()" style="background: #64748b; color: white; border: none; border-radius: 6px; padding: 6px 16px; cursor: pointer; font-weight: 600;">إغلاق (Close)</button>
                </div>
            </div>
        `;
        document.body.appendChild(modalDiv);
    }

    window.openUserProfileModal = async function() {
        ensureUserProfileModal();
        if (!currentUserProfile) await loadUserProfile();
        if (!currentUserProfile) return;
        const modal = document.getElementById('user-profile-modal');
        if (!modal) return;
        
        document.getElementById('modal-user-fullname').textContent = currentUserProfile.full_name || '--';
        document.getElementById('modal-user-id').textContent = currentUserProfile.user_id || '--';
        document.getElementById('modal-user-email').textContent = currentUserProfile.email || '--';
        document.getElementById('modal-user-mobile').textContent = currentUserProfile.mobile || '--';
        document.getElementById('modal-user-branch').textContent = currentUserProfile.branch_name || '--';
        document.getElementById('modal-user-scope').textContent = currentUserProfile.effective_scope || 'GLOBAL';

        const rolesWrap = document.getElementById('modal-user-roles');
        if (rolesWrap) {
            rolesWrap.innerHTML = (currentUserProfile.roles || []).map(r => 
                `<span style="background: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd; font-size: 0.85em; font-weight: 700; padding: 3px 8px; border-radius: 4px; margin-inline-end: 4px;">🛡️ ${r.name || r.role_code} (${r.role_code})</span>`
            ).join('') || '--';
        }

        const permsWrap = document.getElementById('modal-user-permissions');
        const countBadge = document.getElementById('modal-perm-count-badge');
        const perms = currentUserProfile.permissions || [];
        if (countBadge) countBadge.textContent = `${perms.length} Active Permissions`;
        if (permsWrap) {
            permsWrap.innerHTML = perms.map(p => 
                `<div style="display: flex; align-items: center; gap: 6px; background: #f8fafc; border: 1px solid #e2e8f0; padding: 6px 10px; border-radius: 6px; font-size: 0.82em;">
                    <span style="color: #16a34a; font-weight: 800;">✓</span>
                    <span style="font-weight: 700; color: #1e3a8a;">${p.code}</span>
                    <span style="color: #64748b; font-size: 0.9em;">- ${p.name}</span>
                </div>`
            ).join('') || `<div style="color: #64748b;">No explicit permissions</div>`;
        }

        const switchSel = document.getElementById('modal-user-switch-select');
        if (switchSel) {
            try {
                const apiBase = getApiBase();
                const uRes = await fetch(`${apiBase}/api/v1/auth/users`);
                if (uRes.ok) {
                    const uJson = await uRes.json();
                    const users = uJson.data || [];
                    switchSel.innerHTML = users.map(u => {
                        const rolesStr = (u.roles || []).join(', ');
                        const isOwn = (u.roles || []).some(r => ['SALES_AGENT', 'LEASING_AGENT'].includes(r));
                        const scopeTag = isOwn ? '[OWN Scope - بياناته فقط]' : '[GLOBAL Scope - شامل]';
                        return `<option value="${u.user_id}" ${u.user_id === currentUserProfile.user_id ? 'selected' : ''}>👤 ${u.full_name} (${u.user_id}) - ${rolesStr} ${scopeTag}</option>`;
                    }).join('');
                }
            } catch (e) {
                console.warn('Failed to load user switch list:', e);
            }
        }

        modal.style.display = 'flex';
    };

    window.closeUserProfileModal = function() {
        const modal = document.getElementById('user-profile-modal');
        if (modal) modal.style.display = 'none';
    };

    window.switchActiveUser = function(targetUid) {
        let newUid = targetUid;
        if (!newUid) {
            const switchSel = document.getElementById('modal-user-switch-select');
            if (switchSel) newUid = switchSel.value;
        }
        if (newUid) {
            localStorage.setItem('recrm_user_id', newUid);
            const url = new URL(window.location.href);
            url.searchParams.set('user_id', newUid);
            window.location.href = url.toString();
        }
    };

    window.getCurrentUserProfile = function() {
        return currentUserProfile;
    };

    // Auto-init on load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadUserProfile);
    } else {
        loadUserProfile();
    }
})();
