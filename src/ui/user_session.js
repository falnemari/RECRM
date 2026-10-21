// Global User Session & RBAC Handler for RECRM
(function() {
    let currentUserProfile = null;

    // RBAC Page Permissions & Role Access Map
    const PAGE_ACCESS_MAP = {
        'index.html': {
            nameAr: 'لوحة المؤشرات والتقارير',
            nameEn: 'Dashboard & Reports',
            publicAuth: true,
            permissions: ['REPORT_READ', 'ADMIN']
        },
        'customers.html': {
            nameAr: 'العملاء 360',
            nameEn: 'Customers 360',
            permissions: ['CUSTOMER_READ', 'CUSTOMER_WRITE', 'PAYMENT_READ', 'ADMIN'],
            roles: ['SYS_ADMIN', 'SALES_MANAGER', 'SALES_AGENT', 'LEASING_AGENT', 'ACCOUNTANT', 'DOCUMENT_CONTROL', 'BRANCH_MANAGER', 'GENERAL_MANAGER', 'VIEWER', 'AUDITOR']
        },
        'leads.html': {
            nameAr: 'الطلبات',
            nameEn: 'Leads',
            permissions: ['LEAD_READ', 'LEAD_WRITE', 'ADMIN'],
            roles: ['SYS_ADMIN', 'SALES_MANAGER', 'SALES_AGENT', 'LEASING_AGENT', 'MARKETING', 'BRANCH_MANAGER', 'GENERAL_MANAGER', 'VIEWER', 'AUDITOR']
        },
        'properties.html': {
            nameAr: 'المخزون',
            nameEn: 'Properties',
            permissions: ['PROPERTY_READ', 'PROPERTY_WRITE', 'ADMIN'],
            roles: ['SYS_ADMIN', 'SALES_MANAGER', 'SALES_AGENT', 'LEASING_AGENT', 'PROPERTY_MANAGER', 'ACCOUNTANT', 'DOCUMENT_CONTROL', 'BRANCH_MANAGER', 'GENERAL_MANAGER', 'VIEWER', 'AUDITOR']
        },
        'sales.html': {
            nameAr: 'مسار المبيعات والصفقات',
            nameEn: 'Sales Pipeline',
            permissions: ['SALES_WRITE', 'ADMIN'],
            roles: ['SYS_ADMIN', 'SALES_MANAGER', 'SALES_AGENT', 'LEASING_AGENT', 'BRANCH_MANAGER', 'GENERAL_MANAGER']
        },
        'finance.html': {
            nameAr: 'المالية والعقود',
            nameEn: 'Finance & Contracts',
            permissions: ['PAYMENT_READ', 'PAYMENT_WRITE', 'ADMIN'],
            roles: ['SYS_ADMIN', 'ACCOUNTANT', 'BRANCH_MANAGER', 'GENERAL_MANAGER', 'AUDITOR']
        },
        'management.html': {
            nameAr: 'إدارة الأملاك والتأجير',
            nameEn: 'Property Management',
            permissions: ['PM_WRITE', 'ADMIN'],
            roles: ['SYS_ADMIN', 'PROPERTY_MANAGER', 'BRANCH_MANAGER', 'GENERAL_MANAGER', 'ACCOUNTANT', 'LEASING_AGENT', 'SALES_MANAGER', 'SALES_AGENT', 'SALES_DIRECTOR', 'VIEWER', 'AUDITOR']
        },
        'tasks.html': {
            nameAr: 'المهام والمتابعات',
            nameEn: 'Tasks & Activities',
            publicAuth: true,
            permissions: ['SALES_WRITE', 'LEAD_READ', 'CUSTOMER_READ', 'PM_WRITE', 'PAYMENT_READ', 'PAYMENT_WRITE', 'DOCUMENT_READ', 'DOCUMENT_WRITE', 'REPORT_READ', 'ADMIN'],
            roles: ['SYS_ADMIN', 'SALES_MANAGER', 'SALES_AGENT', 'LEASING_AGENT', 'PROPERTY_MANAGER', 'ACCOUNTANT', 'DOCUMENT_CONTROL', 'BRANCH_MANAGER', 'GENERAL_MANAGER', 'SALES_DIRECTOR', 'MARKETING', 'AUDITOR', 'VIEWER', 'INVESTMENT_ADVISOR']
        },
        'documents.html': {
            nameAr: 'المستندات والوثائق',
            nameEn: 'Documents & Files',
            permissions: ['DOCUMENT_READ', 'DOCUMENT_WRITE', 'PAYMENT_READ', 'ADMIN'],
            roles: ['SYS_ADMIN', 'DOCUMENT_CONTROL', 'PROPERTY_MANAGER', 'ACCOUNTANT', 'BRANCH_MANAGER', 'GENERAL_MANAGER', 'SALES_AGENT', 'SALES_MANAGER', 'SALES_DIRECTOR', 'LEASING_AGENT', 'VIEWER', 'AUDITOR']
        },
        'campaigns.html': {
            nameAr: 'الحملات والتسويق',
            nameEn: 'Marketing & Campaigns',
            permissions: ['MARKETING_WRITE', 'ADMIN'],
            roles: ['SYS_ADMIN', 'MARKETING', 'BRANCH_MANAGER', 'GENERAL_MANAGER', 'SALES_DIRECTOR', 'SALES_MANAGER', 'SALES_AGENT', 'LEASING_AGENT', 'VIEWER', 'AUDITOR']
        },
        'listings.html': {
            nameAr: 'العروض العقارية',
            nameEn: 'Property Listings',
            permissions: ['PROPERTY_READ', 'PROPERTY_WRITE', 'ADMIN'],
            roles: ['SYS_ADMIN', 'SALES_MANAGER', 'SALES_AGENT', 'LEASING_AGENT', 'PROPERTY_MANAGER', 'BRANCH_MANAGER', 'GENERAL_MANAGER', 'DOCUMENT_CONTROL', 'MARKETING', 'ACCOUNTANT', 'VIEWER', 'AUDITOR']
        },
        'admin.html': {
            nameAr: 'الإدارة والحوكمة',
            nameEn: 'Admin & Governance',
            permissions: ['ADMIN', 'USER_MANAGE', 'ROLE_MANAGE', 'AUDIT_READ'],
            roles: ['SYS_ADMIN', 'AUDITOR']
        },
        '/docs': {
            nameAr: 'توثيق واجهة البرمجة (Swagger Docs)',
            nameEn: 'API Swagger Documentation',
            permissions: ['ADMIN'],
            roles: ['SYS_ADMIN']
        }
    };

    function getPageKeyFromHref(href) {
        if (!href) return 'index.html';
        if (href.includes('/docs')) return '/docs';
        const clean = href.split('?')[0].split('#')[0];
        const parts = clean.split('/');
        let filename = parts[parts.length - 1];
        if (!filename || filename === '') filename = 'index.html';
        return filename;
    }

    function getCurrentPageKey() {
        return getPageKeyFromHref(window.location.pathname);
    }

    function isArabic() {
        return (typeof currentLang !== 'undefined' && currentLang === 'ar') ||
               (typeof window.currentLang !== 'undefined' && window.currentLang === 'ar') ||
               (localStorage.getItem('recrm_lang') !== 'en');
    }

    function canUserAccessPage(profile, pageHref) {
        const pageKey = getPageKeyFromHref(pageHref);
        const rule = PAGE_ACCESS_MAP[pageKey];
        if (!rule) {
            return !!profile;
        }

        if (!profile) {
            return false;
        }

        const roleCodes = (profile.role_codes || []).map(r => r.toUpperCase());
        const permCodes = (profile.permission_codes || []).map(p => p.toUpperCase());

        // Sys Admin role or explicit ADMIN permission grants full access to all pages
        if (roleCodes.includes('SYS_ADMIN') || permCodes.includes('ADMIN')) {
            return true;
        }

        // Publicly authorized pages (Dashboard for any authenticated team member)
        if (rule.publicAuth) {
            return true;
        }

        // Check if user has any of the required permissions
        if (rule.permissions && rule.permissions.some(p => permCodes.includes(p.toUpperCase()))) {
            return true;
        }

        // Check if user has any of the authorized roles
        if (rule.roles && rule.roles.some(r => roleCodes.includes(r.toUpperCase()))) {
            return true;
        }

        return false;
    }

    function filterNavbarLinks() {
        // 1. Filter navbar items across all 12 operational pages
        const navLinks = document.querySelectorAll('.nav ul li a, nav a');
        navLinks.forEach(a => {
            const href = a.getAttribute('href');
            if (!href) return;
            const li = a.closest('li') || a;

            const isAllowed = canUserAccessPage(currentUserProfile, href);
            if (isAllowed) {
                li.style.display = '';
            } else {
                li.style.display = 'none';
            }
        });

        // 2. Filter Dashboard module cards on index.html
        const moduleCards = document.querySelectorAll('.module-card');
        moduleCards.forEach(card => {
            const link = card.querySelector('a[href]');
            if (!link) return;
            const href = link.getAttribute('href');
            if (!href) return;

            const isAllowed = canUserAccessPage(currentUserProfile, href);
            if (isAllowed) {
                card.style.display = '';
            } else {
                card.style.display = 'none';
            }
        });

        // 3. Filter any action buttons or links targeting restricted pages
        document.querySelectorAll('a.btn-drill[href], a.quick-link[href]').forEach(a => {
            const href = a.getAttribute('href');
            if (!href) return;
            const isAllowed = canUserAccessPage(currentUserProfile, href);
            if (isAllowed) {
                a.style.display = '';
            } else {
                a.style.display = 'none';
            }
        });
    }

    function renderAccessDeniedCard(pageKey) {
        const pageRule = PAGE_ACCESS_MAP[pageKey] || {
            nameAr: pageKey,
            nameEn: pageKey,
            permissions: ['AUTHENTICATION_REQUIRED']
        };

        // Cleanly hide the main content container
        document.querySelectorAll('.content, .main-content, main').forEach(el => {
            el.style.display = 'none';
        });

        // Remove any existing access denied card
        const existingCard = document.getElementById('recrm-access-denied-container');
        if (existingCard) existingCard.remove();

        const isAr = isArabic();
        const container = document.createElement('div');
        container.id = 'recrm-access-denied-container';
        container.style.cssText = `max-width: 860px; margin: 35px auto; padding: 0 20px; font-family: inherit; direction: ${isAr ? 'rtl' : 'ltr'};`;

        const isGuest = !currentUserProfile;
        const userFullname = currentUserProfile ? currentUserProfile.full_name : (isAr ? 'غير مسجل الدخول' : 'Guest (Not Signed In)');
        const userId = currentUserProfile ? currentUserProfile.user_id : 'GUEST';
        const branchName = currentUserProfile && currentUserProfile.branch_name ? currentUserProfile.branch_name : (isAr ? 'الإدارة العامة / غير مسند' : 'Headquarters / Unassigned');
        const userScope = currentUserProfile ? (currentUserProfile.effective_scope || 'GLOBAL') : 'NONE';
        const rolesList = currentUserProfile && currentUserProfile.roles && currentUserProfile.roles.length > 0 
            ? currentUserProfile.roles.map(r => r.name || r.role_code).join(', ') 
            : (isAr ? 'لا يوجد' : 'None');

        let scopeBg = '#10b981';
        if (userScope === 'OWN') scopeBg = '#f59e0b';
        else if (userScope === 'BRANCH') scopeBg = '#0284c7';
        else if (userScope === 'NONE') scopeBg = '#ef4444';

        const pageName = isAr ? pageRule.nameAr : pageRule.nameEn;
        const alertTitle = isAr ? '403 - غير مصرح بالوصول' : '403 - Access Denied';
        const alertSub = isAr ? 'نظام التحكم المتقدم بالصلاحيات وعزل البيانات' : 'Role-Based Access Control & Multi-Tenant Isolation';
        const explanation = isAr
            ? `عذراً، الحساب النشط حالياً لا يمتلك الصلاحيات الإدارية أو الوظيفية للوصول إلى صفحة <strong style="color: #b91c1c; font-size: 1.1em;">${pageName}</strong>. يتم تقييد الوصول لهذه الصفحة التزاماً بسياسة حوكمة البيانات وعزل النطاقات التشغيلية في المنظمة.`
            : `Sorry, your current account does not possess the permissions required to access <strong style="color: #b91c1c; font-size: 1.1em;">${pageName}</strong>. Access is restricted in accordance with data governance and scope isolation policies.`;

        const identityTitle = isAr ? 'بيانات الجلسة والصلاحيات المسندة:' : 'Current Session Identity & Permissions:';
        const lblActiveUser = isAr ? 'المستخدم النشط:' : 'Active User:';
        const lblBranch = isAr ? 'الفرع التشغيلي:' : 'Operating Branch:';
        const lblScope = isAr ? 'نطاق البيانات:' : 'Data Scope:';
        const lblRoles = isAr ? 'الأدوار الممنوحة:' : 'Assigned Roles:';
        const lblReqPerms = isAr ? '🔑 الصلاحيات المطلوبة لهذه الصفحة:' : '🔑 Required Permissions:';
        const btnDashboard = isAr ? 'العودة للوحة المؤشرات الرئيسية' : 'Back to Dashboard';
        const btnSwitch = isAr ? 'تبديل المستخدم' : 'Switch User';
        const btnSignOut = isAr ? 'تسجيل الخروج' : 'Sign Out';

        container.innerHTML = `
            <div style="background: #ffffff; border: 2px solid #fecaca; border-radius: 16px; box-shadow: 0 12px 30px -5px rgba(220, 38, 38, 0.16); overflow: hidden;">
                <!-- Red Alert Banner -->
                <div style="background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%); color: white; padding: 22px 28px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 14px;">
                    <div style="display: flex; align-items: center; gap: 14px;">
                        <span style="font-size: 2.2em; background: rgba(255,255,255,0.2); width: 54px; height: 54px; border-radius: 12px; display: flex; align-items: center; justify-content: center;">🛡️🚫</span>
                        <div>
                            <div style="font-size: 1.35em; font-weight: 800; letter-spacing: -0.3px;">${alertTitle}</div>
                            <div style="font-size: 0.88em; opacity: 0.92; margin-top: 3px;">${alertSub}</div>
                        </div>
                    </div>
                    <span style="background: rgba(0,0,0,0.3); color: #fff; padding: 5px 14px; border-radius: 20px; font-size: 0.82em; font-weight: 800; letter-spacing: 0.5px;">HTTP 403 FORBIDDEN</span>
                </div>

                <!-- Explanation Body -->
                <div style="padding: 26px 28px;">
                    <div style="font-size: 1.05em; color: #1e293b; line-height: 1.8; margin-bottom: 22px;">
                        ${explanation}
                    </div>

                    <!-- User Identity & Security Context Box -->
                    <div style="background: #f8fafc; border: 1.5px solid #e2e8f0; border-radius: 10px; padding: 18px 20px; margin-bottom: 24px;">
                        <div style="font-weight: 700; color: #0f172a; margin-bottom: 12px; font-size: 0.95em; display: flex; align-items: center; gap: 8px;">
                            <span>👤</span> <span>${identityTitle}</span>
                        </div>
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px; font-size: 0.88em;">
                            <div>
                                <span style="color: #64748b; display: block; font-size: 0.84em; margin-bottom: 2px;">${lblActiveUser}</span>
                                <strong>${userFullname}</strong> <span style="font-size: 0.85em; color: #64748b;">(${userId})</span>
                            </div>
                            <div>
                                <span style="color: #64748b; display: block; font-size: 0.84em; margin-bottom: 2px;">${lblBranch}</span>
                                <strong>🏢 ${branchName}</strong>
                            </div>
                            <div>
                                <span style="color: #64748b; display: block; font-size: 0.84em; margin-bottom: 2px;">${lblScope}</span>
                                <span style="background: ${scopeBg}; color: white; padding: 3px 9px; border-radius: 4px; font-weight: 700; font-size: 0.84em;">${userScope}</span>
                            </div>
                            <div>
                                <span style="color: #64748b; display: block; font-size: 0.84em; margin-bottom: 2px;">${lblRoles}</span>
                                <strong style="color: #0369a1;">${rolesList}</strong>
                            </div>
                        </div>

                        <div style="margin-top: 14px; padding-top: 12px; border-top: 1px dashed #cbd5e1; font-size: 0.86em; color: #475569; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                            <span style="font-weight: 700; color: #0f172a;">${lblReqPerms}</span>
                            <span style="background: #fee2e2; color: #991b1b; padding: 2px 8px; border-radius: 4px; font-weight: 700;">${(pageRule.permissions || []).join(isAr ? ' أو ' : ' OR ')}</span>
                        </div>
                    </div>

                    <!-- Fast Recovery Actions -->
                    <div style="display: flex; gap: 12px; flex-wrap: wrap; justify-content: flex-end; align-items: center;">
                        <a href="index.html" class="btn" style="background: #0284c7; color: white; text-decoration: none; padding: 10px 22px; border-radius: 8px; font-weight: 700; font-size: 0.9em; display: inline-flex; align-items: center; gap: 8px;">
                            <span>🏠</span> <span>${btnDashboard}</span>
                        </a>
                        <button type="button" onclick="window.openUserProfileModal()" class="btn" style="background: #2563eb; color: white; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 700; font-size: 0.9em; cursor: pointer; display: inline-flex; align-items: center; gap: 8px;">
                            <span>🔄</span> <span>${btnSwitch}</span>
                        </button>
                        ${!isGuest ? `
                        <button type="button" onclick="window.signOutUser()" class="btn" style="background: #dc2626; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: 600; font-size: 0.9em; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;">
                            <span>🚪</span> <span>${btnSignOut}</span>
                        </button>` : ''}
                    </div>
                </div>
            </div>
        `;

        // Insert container directly after sub-nav-banner or nav or body
        const banner = document.querySelector('.sub-nav-banner') || document.querySelector('.nav') || document.querySelector('.header');
        if (banner && banner.parentNode) {
            banner.parentNode.insertBefore(container, banner.nextSibling);
        } else {
            document.body.prepend(container);
        }
    }

    function enforcePageAccessGuard() {
        const currentPageKey = getCurrentPageKey();
        const isAllowed = canUserAccessPage(currentUserProfile, currentPageKey);

        if (isAllowed) {
            const deniedEl = document.getElementById('recrm-access-denied-container');
            if (deniedEl) deniedEl.remove();
            document.querySelectorAll('.content, .main-content, main').forEach(el => {
                el.style.display = '';
            });
            return true;
        }

        renderAccessDeniedCard(currentPageKey);
        return false;
    }

    // Cross-tab / cross-window session broadcast channel
    const sessionChannel = ('BroadcastChannel' in window) ? new BroadcastChannel('recrm_session_sync') : null;

    if (sessionChannel) {
        sessionChannel.onmessage = function(ev) {
            if (ev.data && (ev.data.type === 'USER_SWITCHED' || ev.data.type === 'USER_SIGNED_OUT')) {
                console.log('🔄 Session change received from another page/tab. Reloading to sync data context...');
                reloadCurrentPageClean();
            }
        };
    }

    // Storage event fires in all other tabs when localStorage changes
    window.addEventListener('storage', function(e) {
        if (e.key === 'recrm_user_id') {
            console.log('🔄 recrm_user_id changed in localStorage. Reloading to sync data context...');
            reloadCurrentPageClean();
        }
    });

    function reloadCurrentPageClean() {
        const url = new URL(window.location.href);
        if (url.searchParams.has('user_id') || url.searchParams.has('u')) {
            url.searchParams.delete('user_id');
            url.searchParams.delete('u');
            window.location.href = url.toString();
        } else {
            window.location.reload();
        }
    }

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
            const activeUserId = localStorage.getItem('recrm_user_id') || 'user-51';
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

            // Check if explicitly logged out
            if (activeUserId === 'GUEST') {
                currentUserProfile = null;
                renderSignedOutHeader();
                filterNavbarLinks();
                enforcePageAccessGuard();
                return;
            }

            const apiBase = getApiBase();
            const res = await fetch(`${apiBase}/api/v1/me?user_id=${encodeURIComponent(activeUserId)}`);
            if (!res.ok) {
                if (res.status === 404 && activeUserId !== 'user-51') {
                    // Fallback to default user-51 if stored user no longer exists
                    localStorage.setItem('recrm_user_id', 'user-51');
                    return loadUserProfile();
                }
                throw new Error('Failed to load user profile');
            }
            const json = await res.json();
            currentUserProfile = json.data;

            // Render top bar header display
            renderSignedInHeader();

            // Dynamic Navigation Filtering according to user permissions & roles
            filterNavbarLinks();

            // Enforce direct URL access guard
            const isAllowed = enforcePageAccessGuard();
            if (!isAllowed) {
                return;
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
            filterNavbarLinks();
            enforcePageAccessGuard();
        }
    }

    function renderSignedInHeader() {
        const nameDisplay = document.getElementById('user-name-display');
        if (!nameDisplay || !currentUserProfile) return;
        const roleName = (currentUserProfile.roles && currentUserProfile.roles[0]) 
            ? currentUserProfile.roles[0].name 
            : (currentUserProfile.role_codes ? currentUserProfile.role_codes[0] : 'SYS_ADMIN');
        const isOwn = currentUserProfile.effective_scope === 'OWN';
        const isBranch = currentUserProfile.effective_scope === 'BRANCH';
        const isTeam = currentUserProfile.effective_scope === 'TEAM';
        
        let scopeBadge = `<span style="background: #10b981; color: white; padding: 2px 7px; border-radius: 4px; font-size: 0.78em; font-weight: 700; margin-inline-start: 4px;">🌐 GLOBAL</span>`;
        if (isOwn) {
            scopeBadge = `<span style="background: #f59e0b; color: white; padding: 2px 7px; border-radius: 4px; font-size: 0.78em; font-weight: 700; margin-inline-start: 4px;">🔒 OWN</span>`;
        } else if (isBranch) {
            scopeBadge = `<span style="background: #0284c7; color: white; padding: 2px 7px; border-radius: 4px; font-size: 0.78em; font-weight: 700; margin-inline-start: 4px;">🏢 BRANCH</span>`;
        } else if (isTeam) {
            scopeBadge = `<span style="background: #8b5cf6; color: white; padding: 2px 7px; border-radius: 4px; font-size: 0.78em; font-weight: 700; margin-inline-start: 4px;">👥 TEAM</span>`;
        }

        const branchPart = currentUserProfile.branch_name ? `<span style="opacity: 0.9; font-size: 0.82em; background: rgba(0,0,0,0.22); padding: 2px 6px; border-radius: 4px; margin-inline-start: 4px;">🏢 ${currentUserProfile.branch_name}</span>` : '';

        nameDisplay.innerHTML = `<strong>${currentUserProfile.full_name}</strong> <span style="opacity: 0.85; font-size: 0.82em; background: rgba(255,255,255,0.22); padding: 2px 6px; border-radius: 4px; margin-inline-start: 4px;">${currentUserProfile.user_id}</span>${branchPart} ${scopeBadge}`;
    }

    function renderSignedOutHeader() {
        const nameDisplay = document.getElementById('user-name-display');
        if (nameDisplay) {
            const isAr = isArabic();
            const label = isAr ? '🚪 غير مسجل الدخول (اضغط لتسجيل الدخول)' : '🚪 Not Signed In (Click to Sign In)';
            nameDisplay.innerHTML = `<span style="background: #ef4444; color: white; padding: 3px 10px; border-radius: 4px; font-size: 0.85em; font-weight: 700; display: inline-flex; align-items: center; gap: 4px;">${label}</span>`;
        }
    }

    function applyDataScopingToPage() {
        if (!currentUserProfile) return;
        const isOwn = currentUserProfile.effective_scope === 'OWN';
        const isBranch = currentUserProfile.effective_scope === 'BRANCH';
        const userId = currentUserProfile.user_id;
        const userName = currentUserProfile.full_name;
        const branchName = currentUserProfile.branch_name || '';
        const isAr = isArabic();

        // 1. Sales Pipeline Page filter
        const oppAgFilter = document.getElementById('opp-agent-filter');
        if (oppAgFilter) {
            if (isOwn) {
                oppAgFilter.innerHTML = `<option value="${userId}" selected>🔒 ${userName} (${userId}) - ${isAr ? 'صفقاتي فقط' : 'My Deals Only'}</option>`;
                oppAgFilter.disabled = true;
                if (typeof filterOpportunities === 'function') filterOpportunities();
                showScopeNotificationBanner(isAr 
                    ? `🔒 تم تطبيق عزل البيانات الشخصية: يتم عرض الصفقات والفرص البيعية المسندة إليك فقط (${userName}).`
                    : `🔒 Personal Data Isolation Active: Showing deals and opportunities assigned to you only (${userName}).`);
            } else if (isBranch) {
                oppAgFilter.disabled = false;
                showScopeNotificationBanner(isAr 
                    ? `🏢 تم تفعيل نطاق الفرع (${branchName}): يتم عرض صفقات وفرص فرعك البيعية (${userName}).`
                    : `🏢 Branch Scope Active (${branchName}): Showing deals for your branch (${userName}).`);
                if (typeof filterOpportunities === 'function') filterOpportunities();
            } else {
                oppAgFilter.disabled = false;
                const banner = document.getElementById('recrm-scope-banner');
                if (banner) banner.remove();
                if (typeof filterOpportunities === 'function') filterOpportunities();
            }
        }

        // 2. Leads Page filter
        const leadAgFilter = document.getElementById('agent-filter');
        if (leadAgFilter) {
            if (isOwn) {
                leadAgFilter.innerHTML = `<option value="${userId}" selected>🔒 ${userName} (${userId}) - ${isAr ? 'طلباتي فقط' : 'My Leads Only'}</option>`;
                leadAgFilter.disabled = true;
                if (typeof fetchLeads === 'function') fetchLeads(1);
                showScopeNotificationBanner(isAr 
                    ? `🔒 تم تطبيق عزل البيانات الشخصية: يتم عرض العملاء والطلبات المسندة إليك فقط (${userName}).`
                    : `🔒 Personal Data Isolation Active: Showing inquiries and leads assigned to you only (${userName}).`);
            } else if (isBranch) {
                leadAgFilter.disabled = false;
                showScopeNotificationBanner(isAr 
                    ? `🏢 تم تفعيل نطاق الفرع (${branchName}): يتم عرض طلبات فرعك وفريق مبيعاتك (${userName}).`
                    : `🏢 Branch Scope Active (${branchName}): Showing leads for your branch and sales team (${userName}).`);
                if (typeof fetchLeads === 'function') fetchLeads(1);
            } else {
                leadAgFilter.disabled = false;
                const banner = document.getElementById('recrm-scope-banner');
                if (banner) banner.remove();
                if (typeof fetchLeads === 'function') fetchLeads(1);
            }
        }

        // 3. Tasks Page filter
        const taskAgFilter = document.getElementById('task-agent-filter');
        if (taskAgFilter) {
            if (isOwn) {
                taskAgFilter.innerHTML = `<option value="${userId}" selected>🔒 ${userName} (${userId}) - ${isAr ? 'مهامي فقط' : 'My Tasks Only'}</option>`;
                taskAgFilter.disabled = true;
                if (typeof loadTasks === 'function') loadTasks();
                if (typeof loadActivities === 'function') loadActivities();
                if (typeof loadSummary === 'function') loadSummary();
                showScopeNotificationBanner(isAr 
                    ? `🔒 تم تطبيق عزل البيانات الشخصية: يتم عرض المهام والمتابعات المسندة إليك فقط (${userName}).`
                    : `🔒 Personal Data Isolation Active: Showing tasks and follow-ups assigned to you only (${userName}).`);
            } else if (isBranch) {
                taskAgFilter.disabled = false;
                showScopeNotificationBanner(isAr 
                    ? `🏢 تم تفعيل نطاق الفرع (${branchName}): يتم عرض مهام ومتابعات فرعك (${userName}).`
                    : `🏢 Branch Scope Active (${branchName}): Showing tasks for your branch (${userName}).`);
                if (typeof loadTasks === 'function') loadTasks();
                if (typeof loadActivities === 'function') loadActivities();
                if (typeof loadSummary === 'function') loadSummary();
            } else {
                taskAgFilter.disabled = false;
                const banner = document.getElementById('recrm-scope-banner');
                if (banner) banner.remove();
                if (typeof loadTasks === 'function') loadTasks();
                if (typeof loadActivities === 'function') loadActivities();
                if (typeof loadSummary === 'function') loadSummary();
            }
        }

        // 4. Properties Page: Property Inventory is open to all sales agents to market & match for leads
        const unitAgFilter = document.getElementById('unit-agent-filter');
        if (unitAgFilter) {
            // Keep filter unlocked so agents can view full inventory or optionally filter by agent
            unitAgFilter.disabled = false;
        }

        // 5. Customers Page (customers.html)
        const curPage = getCurrentPageKey();
        const hasCustAccess = currentUserProfile && currentUserProfile.permission_codes && 
            (currentUserProfile.permission_codes.includes('CUSTOMER_READ') || 
             currentUserProfile.permission_codes.includes('CUSTOMER_WRITE') || 
             currentUserProfile.permission_codes.includes('ADMIN'));
        if (curPage === 'customers.html' && isOwn && !hasCustAccess) {
            showScopeNotificationBanner(isAr 
                ? `🔒 تم تطبيق عزل البيانات الشخصية: يتم عرض العملاء المرتبطين بطلباتك ووحداتك وصفقاتك المسندة إليك فقط (${userName}).`
                : `🔒 Personal Data Isolation Active: Showing customers linked to your assigned records only (${userName}).`);
        }

        // 6. Dashboard Page (index.html)
        if (typeof setDashboardScope === 'function' && typeof dashboardState !== 'undefined') {
            if (isOwn) {
                dashboardState.userId = userId;
                setDashboardScope('OWN');
                const btnGlobal = document.getElementById('btn-scope-GLOBAL');
                const btnBranch = document.getElementById('btn-scope-BRANCH');
                const btnTeam = document.getElementById('btn-scope-TEAM');
                const bSel = document.getElementById('dash-branch-select');
                const aSel = document.getElementById('dash-agent-select');
                if (btnGlobal) btnGlobal.style.display = 'none';
                if (btnBranch) btnBranch.style.display = 'none';
                if (btnTeam) btnTeam.style.display = 'none';
                if (bSel) bSel.style.display = 'none';
                if (aSel) aSel.style.display = 'none';
                showScopeNotificationBanner(isAr 
                    ? `🔒 تم تطبيق عزل البيانات الشخصية: يتم استعراض لوحة التحكم الخاصة بك فقط (${userName}).`
                    : `🔒 Personal Data Isolation Active: Displaying your personal dashboard metrics only (${userName}).`);
            } else if (isBranch && currentUserProfile.branch_id) {
                dashboardState.branchId = currentUserProfile.branch_id;
                setDashboardScope('BRANCH');
                const btnGlobal = document.getElementById('btn-scope-GLOBAL');
                if (btnGlobal) btnGlobal.style.display = 'none';
                const bSel = document.getElementById('dash-branch-select');
                if (bSel) bSel.disabled = true;
            }
        }
    }

    function showScopeNotificationBanner(text) {
        if (document.getElementById('recrm-scope-banner')) return;
        const mainContainer = document.querySelector('.main-content') || document.querySelector('.container') || document.body;
        const banner = document.createElement('div');
        banner.id = 'recrm-scope-banner';
        banner.style.cssText = 'background: #eff6ff; border: 1.5px solid #93c5fd; color: #1e3a8a; padding: 10px 16px; border-radius: 8px; margin-bottom: 16px; font-size: 0.88em; font-weight: 600; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 4px rgba(0,0,0,0.04); flex-wrap: wrap; gap: 8px;';
        const isAr = isArabic();
        const btnSwitchText = isAr ? '🔄 تبديل المستخدم' : '🔄 Switch User';
        const btnAdminText = isAr ? 'العودة لمدير النظام (user-51)' : 'Back to Admin (user-51)';
        banner.innerHTML = `
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 1.2em;">🛡️</span>
                <span>${text}</span>
            </div>
            <div style="display: flex; gap: 8px; align-items: center;">
                <button type="button" onclick="window.openUserProfileModal()" style="background: #0284c7; color: white; border: none; border-radius: 4px; padding: 5px 12px; font-size: 0.82em; cursor: pointer; font-weight: 700;">
                    ${btnSwitchText}
                </button>
                <button type="button" onclick="window.switchActiveUser('user-51')" style="background: #2563eb; color: white; border: none; border-radius: 4px; padding: 5px 12px; font-size: 0.82em; cursor: pointer; font-weight: 700;">
                    ${btnAdminText}
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
        const isAr = isArabic();
        let modalDiv = document.getElementById('user-profile-modal');
        if (modalDiv) {
            const curLang = modalDiv.getAttribute('data-lang');
            if (curLang === (isAr ? 'ar' : 'en')) return;
            modalDiv.remove();
        }

        modalDiv = document.createElement('div');
        modalDiv.id = 'user-profile-modal';
        modalDiv.setAttribute('data-lang', isAr ? 'ar' : 'en');
        modalDiv.className = 'modal-overlay';
        modalDiv.style.cssText = `position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(15, 23, 42, 0.6); backdrop-filter: blur(2px); display: none; justify-content: center; align-items: center; z-index: 2000; direction: ${isAr ? 'rtl' : 'ltr'};`;
        modalDiv.onclick = function(e) { if (e.target === modalDiv) window.closeUserProfileModal(); };

        const modalTitle = isAr ? 'ملف المستخدم والأدوار وتسجيل الدخول' : 'User Profile & Authentication';
        const lblBranch = isAr ? 'الفرع:' : 'Branch:';
        const lblScope = isAr ? 'نطاق البيانات:' : 'Data Scope:';
        const lblRoles = isAr ? 'الأدوار:' : 'Assigned Roles:';
        const lblSwitch = isAr ? '🔄 تسجيل الدخول وتبديل المستخدم:' : '🔄 Switch Active User / Sign In:';
        const tipSwitch = isAr ? '💡 القائمة مرتبة ومجمعة حسب الفروع 🏢. عند اختيار أي مستخدم والضغط على <strong>تسجيل الدخول / تبديل</strong>، سيتم تحديث جميع الصفحات فوراً.' : '💡 Grouped by branch 🏢. Selecting a user and clicking <strong>Switch User</strong> updates all pages immediately.';
        const optLoading = isAr ? 'جاري تحميل المستخدمين والفروع...' : 'Loading users and branches...';
        const btnSwitchText = isAr ? 'تسجيل الدخول / تبديل' : 'Switch User';
        const btnSignOutText = isAr ? 'خروج' : 'Sign Out';
        const lblPerms = isAr ? '📋 الصلاحيات الممنوحة للمستخدم الحالي:' : '📋 Active Granted Permissions:';
        const adminText = isAr ? 'المدير العام الافتراضي: <strong>user-51</strong> (فهد خضر النمري)' : 'Default Administrator: <strong>user-51</strong> (Fahad Khader Alnemari)';
        const btnCloseText = isAr ? 'إغلاق' : 'Close';

        modalDiv.innerHTML = `
            <div class="modal-box" style="max-width: 780px; width: 95%; background: #fff; border-radius: 12px; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.25); overflow: hidden; font-family: inherit;">
                <div style="padding: 16px 20px; background: #0f172a; color: white; display: flex; justify-content: space-between; align-items: center;">
                    <div style="font-weight: 700; font-size: 1.05em; display: flex; align-items: center; gap: 8px;">
                        <span>🛡️</span>
                        <span>${modalTitle}</span>
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
                                <span id="modal-user-status-badge" style="background: #dcfce7; color: #166534; font-size: 0.82em; font-weight: 700; padding: 4px 8px; border-radius: 4px;">ACTIVE</span>
                            </div>
                        </div>

                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; font-size: 0.85em; border-top: 1px dashed #cbd5e1; padding-top: 10px;">
                            <div>
                                <span style="color: #64748b; font-size: 0.82em;">${lblBranch}</span>
                                <strong id="modal-user-branch" style="display: block; color: #0f172a; font-size: 0.95em;">--</strong>
                            </div>
                            <div>
                                <span style="color: #64748b; font-size: 0.82em;">${lblScope}</span>
                                <strong id="modal-user-scope" style="display: block; color: #7c3aed; font-size: 0.95em;">GLOBAL</strong>
                            </div>
                            <div>
                                <span style="color: #64748b; font-size: 0.82em;">${lblRoles}</span>
                                <div id="modal-user-roles" style="margin-top: 3px;">--</div>
                            </div>
                        </div>
                    </div>

                    <!-- Fast User Switcher & Sign In / Out -->
                    <div style="background: #eff6ff; border: 1.5px solid #bfdbfe; border-radius: 8px; padding: 14px 16px; margin-bottom: 18px;">
                        <label style="display: block; font-size: 0.9em; font-weight: 700; color: #1e3a8a; margin-bottom: 4px;">
                            ${lblSwitch}
                        </label>
                        <div style="font-size: 0.8em; color: #475569; margin-bottom: 10px;">
                            ${tipSwitch}
                        </div>
                        <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center;">
                            <select id="modal-user-switch-select" style="flex: 1; min-width: 320px; padding: 9px 12px; border-radius: 6px; border: 1.5px solid #93c5fd; font-size: 0.88em; background: white; font-weight: 500;">
                                <option value="">${optLoading}</option>
                            </select>
                            <button type="button" class="btn" onclick="window.switchActiveUser()" style="padding: 9px 18px; font-size: 0.88em; background: #0284c7; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: 700; display: inline-flex; align-items: center; gap: 6px;">
                                <span>🔑</span> <span>${btnSwitchText}</span>
                            </button>
                            <button type="button" class="btn" onclick="window.signOutUser()" style="padding: 9px 14px; font-size: 0.88em; background: #dc2626; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; display: inline-flex; align-items: center; gap: 4px;" title="Sign out">
                                <span>🚪</span> <span>${btnSignOutText}</span>
                            </button>
                        </div>
                    </div>

                    <!-- Granted Permissions Section -->
                    <div>
                        <div style="font-weight: 700; font-size: 0.95em; color: #0f172a; margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between;">
                            <span>${lblPerms}</span>
                            <span id="modal-perm-count-badge" style="font-size: 0.8em; background: #e0f2fe; color: #0369a1; padding: 2px 8px; border-radius: 4px; font-weight: 700;">--</span>
                        </div>
                        <div id="modal-user-permissions" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 8px; max-height: 220px; overflow-y: auto; padding: 2px;">
                            <!-- dynamic items -->
                        </div>
                    </div>
                </div>

                <div style="padding: 12px 20px; background: #f8fafc; border-top: 1px solid #e2e8f0; display: flex; justify-content: space-between; align-items: center;">
                    <div style="font-size: 0.82em; color: #64748b;">
                        ${adminText}
                    </div>
                    <button type="button" onclick="window.closeUserProfileModal()" style="background: #64748b; color: white; border: none; border-radius: 6px; padding: 6px 16px; cursor: pointer; font-weight: 600;">${btnCloseText}</button>
                </div>
            </div>
        `;
        document.body.appendChild(modalDiv);
    }

    window.openUserProfileModal = async function() {
        ensureUserProfileModal();
        if (!currentUserProfile) await loadUserProfile();
        const modal = document.getElementById('user-profile-modal');
        if (!modal) return;
        const isAr = isArabic();
        
        if (currentUserProfile) {
            document.getElementById('modal-user-fullname').textContent = currentUserProfile.full_name || '--';
            document.getElementById('modal-user-id').textContent = currentUserProfile.user_id || '--';
            document.getElementById('modal-user-email').textContent = currentUserProfile.email || '--';
            document.getElementById('modal-user-mobile').textContent = currentUserProfile.mobile || '--';
            document.getElementById('modal-user-branch').textContent = currentUserProfile.branch_name || (isAr ? 'الإدارة العامة / غير مسند' : 'Headquarters / Unassigned');
            document.getElementById('modal-user-scope').textContent = currentUserProfile.effective_scope || 'GLOBAL';
            const statusBadge = document.getElementById('modal-user-status-badge');
            if (statusBadge) {
                statusBadge.textContent = currentUserProfile.status || 'ACTIVE';
                statusBadge.style.background = currentUserProfile.status === 'ACTIVE' ? '#dcfce7' : '#fee2e2';
                statusBadge.style.color = currentUserProfile.status === 'ACTIVE' ? '#166534' : '#991b1b';
            }

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
        } else {
            // Signed out state display
            document.getElementById('modal-user-fullname').textContent = isAr ? 'غير مسجل الدخول' : 'Not Signed In';
            document.getElementById('modal-user-id').textContent = 'GUEST';
            document.getElementById('modal-user-email').textContent = isAr ? 'يرجى اختيار مستخدم لتسجيل الدخول' : 'Please select a user to sign in';
            document.getElementById('modal-user-mobile').textContent = '--';
            document.getElementById('modal-user-branch').textContent = '--';
            document.getElementById('modal-user-scope').textContent = 'NONE';
            const statusBadge = document.getElementById('modal-user-status-badge');
            if (statusBadge) {
                statusBadge.textContent = 'SIGNED_OUT';
                statusBadge.style.background = '#fee2e2';
                statusBadge.style.color = '#991b1b';
            }
            const rolesWrap = document.getElementById('modal-user-roles');
            if (rolesWrap) rolesWrap.innerHTML = `<span style="color: #64748b;">${isAr ? 'لا يوجد' : 'None'}</span>`;
            const permsWrap = document.getElementById('modal-user-permissions');
            if (permsWrap) permsWrap.innerHTML = `<div style="color: #64748b;">${isAr ? 'قم بتسجيل الدخول لمعاينة الصلاحيات' : 'Sign in to view permissions'}</div>`;
        }

        // Populate switch user select grouped by branch
        const switchSel = document.getElementById('modal-user-switch-select');
        if (switchSel) {
            try {
                const apiBase = getApiBase();
                const uRes = await fetch(`${apiBase}/api/v1/auth/users`);
                if (uRes.ok) {
                    const uJson = await uRes.json();
                    const users = uJson.data || [];
                    
                    // Group users by branch
                    const branchesMap = {};
                    users.forEach(u => {
                        const bName = u.branch_name 
                            ? `${u.branch_name} (${u.branch_code || ''})` 
                            : (isAr ? 'الإدارة العامة / غير مسند لفرع' : 'Headquarters / Unassigned Branch');
                        if (!branchesMap[bName]) branchesMap[bName] = [];
                        branchesMap[bName].push(u);
                    });

                    let optionsHtml = '';
                    for (const [bName, bUsers] of Object.entries(branchesMap)) {
                        optionsHtml += `<optgroup label="🏢 ${bName}">`;
                        optionsHtml += bUsers.map(u => {
                            const rolesStr = (u.role_names && u.role_names.length > 0) ? u.role_names.join(', ') : (u.roles || []).join(', ');
                            const scope = u.effective_scope || 'GLOBAL';
                            let scopeLabel = `[${scope}]`;
                            if (scope === 'OWN') scopeLabel = isAr ? '[🔒 OWN - بياناته فقط]' : '[🔒 OWN - Personal Only]';
                            else if (scope === 'BRANCH') scopeLabel = isAr ? '[🏢 BRANCH - فرعه فقط]' : '[🏢 BRANCH - Branch Only]';
                            else if (scope === 'TEAM') scopeLabel = isAr ? '[👥 TEAM - فريقه فقط]' : '[👥 TEAM - Team Only]';
                            else if (scope === 'GLOBAL') scopeLabel = isAr ? '[🌐 GLOBAL - شامل]' : '[🌐 GLOBAL - All Branches]';

                            const activeUid = currentUserProfile ? currentUserProfile.user_id : '';
                            const isSelected = u.user_id === activeUid ? 'selected' : '';
                            return `<option value="${u.user_id}" ${isSelected}>👤 ${u.full_name} (${u.user_id}) | 🛡️ ${rolesStr} | ${scopeLabel}</option>`;
                        }).join('');
                        optionsHtml += `</optgroup>`;
                    }
                    switchSel.innerHTML = optionsHtml;
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
            if (sessionChannel) {
                sessionChannel.postMessage({ type: 'USER_SWITCHED', userId: newUid });
            }
            reloadCurrentPageClean();
        }
    };

    window.signOutUser = function() {
        const isAr = isArabic();
        const msg = isAr ? 'هل تريد تأكيد تسجيل الخروج من الحساب الحالي؟' : 'Do you want to sign out from the current user session?';
        if (!confirm(msg)) return;
        localStorage.setItem('recrm_user_id', 'GUEST');
        if (sessionChannel) {
            sessionChannel.postMessage({ type: 'USER_SIGNED_OUT' });
        }
        reloadCurrentPageClean();
    };

    window.getCurrentUserProfile = function() {
        return currentUserProfile;
    };

    window.canUserAccessPage = canUserAccessPage;
    window.PAGE_ACCESS_MAP = PAGE_ACCESS_MAP;

    // Auto-init on load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadUserProfile);
    } else {
        loadUserProfile();
    }
})();
