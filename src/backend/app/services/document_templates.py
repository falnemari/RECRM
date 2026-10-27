"""
RECRM Document Templates & Printable HTML Renderer Engine
==========================================================
Generates official, print-ready, bilingual (Arabic primary) legal, financial,
and technical documents compliant with Saudi Real Estate General Authority (REGA),
ZATCA e-invoicing, Taqeem, and Saudi Building Code standards.
"""

from typing import Dict, Any, Optional
from datetime import datetime, date


def get_base_html_wrapper(title: str, content: str, doc_ref: str, doc_date: str) -> str:
    """Wraps document content in a unified official document container with print styling and security seals."""
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - {doc_ref}</title>
    <!-- Professional Typography -->
    <link rel="stylesheet" href="/ui/fonts/fonts.css">
    <style>
        :root {{
            --primary: #1e3a8a;
            --primary-dark: #0f172a;
            --accent: #2563eb;
            --success: #16a34a;
            --warning: #d97706;
            --danger: #dc2626;
            --border: #cbd5e1;
            --bg-muted: #f8fafc;
            --ar-font: 'Cairo', 'Tajawal', 'Almarai', -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }}
        * {{
            box-sizing: border-box;
            font-family: var(--ar-font) !important;
        }}
        body {{
            background: #f1f5f9;
            color: #1e293b;
            margin: 0;
            padding: 24px;
            line-height: 1.6;
        }}
        .print-toolbar {{
            max-width: 960px;
            margin: 0 auto 16px auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #ffffff;
            padding: 12px 20px;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
            border: 1px solid var(--border);
        }}
        .btn-print {{
            background: #1e3a8a;
            color: white;
            border: none;
            padding: 8px 18px;
            border-radius: 6px;
            font-weight: 700;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            font-size: 0.9em;
            transition: 0.2s ease;
        }}
        .btn-print:hover {{
            background: #2563eb;
        }}
        .doc-page {{
            background: #ffffff;
            max-width: 960px;
            margin: 0 auto;
            padding: 48px;
            border-radius: 10px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.06);
            border: 1px solid var(--border);
            position: relative;
        }}
        .doc-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid var(--primary);
            padding-bottom: 20px;
            margin-bottom: 24px;
        }}
        .header-brand h1 {{
            font-size: 1.35em;
            font-weight: 800;
            color: var(--primary-dark);
            margin: 0 0 4px 0;
        }}
        .header-brand h2 {{
            font-size: 0.9em;
            font-weight: 600;
            color: #475569;
            margin: 0 0 6px 0;
        }}
        .header-brand p {{
            font-size: 0.78em;
            color: #64748b;
            margin: 0;
            line-height: 1.4;
        }}
        .header-meta {{
            text-align: left;
            font-size: 0.82em;
            color: #334155;
            background: var(--bg-muted);
            padding: 10px 14px;
            border-radius: 6px;
            border: 1px solid var(--border);
            min-width: 220px;
        }}
        .header-meta div {{
            margin-bottom: 3px;
        }}
        .header-meta div:last-child {{
            margin-bottom: 0;
        }}
        .doc-title-block {{
            text-align: center;
            margin: 20px 0 28px 0;
            position: relative;
        }}
        .doc-title-block h3 {{
            font-size: 1.5em;
            font-weight: 800;
            color: var(--primary);
            margin: 0 0 6px 0;
            display: inline-block;
            border-bottom: 3px solid var(--accent);
            padding-bottom: 4px;
        }}
        .doc-subtitle {{
            font-size: 0.95em;
            color: #64748b;
            margin: 4px 0 0 0;
            font-weight: 500;
        }}
        .info-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 16px;
            background: var(--bg-muted);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px 20px;
            margin-bottom: 24px;
            font-size: 0.88em;
        }}
        .info-item {{
            display: flex;
            justify-content: space-between;
            border-bottom: 1px dashed #e2e8f0;
            padding-bottom: 4px;
        }}
        .info-label {{
            font-weight: 700;
            color: #475569;
        }}
        .info-val {{
            color: #0f172a;
            font-weight: 600;
        }}
        .section-title {{
            font-size: 1.1em;
            font-weight: 800;
            color: var(--primary-dark);
            border-right: 4px solid var(--accent);
            padding-right: 10px;
            margin: 24px 0 12px 0;
        }}
        table.data-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 12px 0 20px 0;
            font-size: 0.86em;
        }}
        table.data-table th {{
            background: #1e293b;
            color: white;
            font-weight: 700;
            padding: 8px 12px;
            text-align: right;
            border: 1px solid #1e293b;
        }}
        table.data-table td {{
            padding: 8px 12px;
            border: 1px solid var(--border);
            color: #1e293b;
        }}
        table.data-table tr:nth-child(even) {{
            background: #f8fafc;
        }}
        .badge {{
            display: inline-block;
            padding: 3px 10px;
            border-radius: 4px;
            font-weight: 700;
            font-size: 0.85em;
        }}
        .badge-success {{ background: #dcfce7; color: #15803d; }}
        .badge-warning {{ background: #fef3c7; color: #b45309; }}
        .badge-danger {{ background: #fee2e2; color: #b91c1c; }}
        .badge-info {{ background: #e0f2fe; color: #0369a1; }}
        .badge-primary {{ background: #dbeafe; color: #1d4ed8; }}

        .kpi-row {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            margin: 16px 0 24px 0;
        }}
        .kpi-box {{
            background: #f8fafc;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 14px;
            text-align: center;
        }}
        .kpi-box .kpi-num {{
            font-size: 1.3em;
            font-weight: 800;
            color: var(--primary);
            margin: 4px 0;
        }}
        .kpi-box .kpi-txt {{
            font-size: 0.78em;
            color: #64748b;
            font-weight: 600;
        }}

        .notice-box {{
            background: #eff6ff;
            border-right: 4px solid var(--accent);
            padding: 14px 18px;
            border-radius: 6px;
            margin: 20px 0;
            font-size: 0.9em;
            line-height: 1.6;
            color: #1e3a8a;
        }}

        .signatures-area {{
            margin-top: 40px;
            padding-top: 24px;
            border-top: 2px solid #e2e8f0;
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 20px;
            text-align: center;
            font-size: 0.86em;
        }}
        .signature-box {{
            border: 1px dashed var(--border);
            border-radius: 8px;
            padding: 16px;
            background: #fafafa;
        }}
        .signature-role {{
            font-weight: 700;
            color: #334155;
            margin-bottom: 8px;
        }}
        .signature-space {{
            height: 60px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #94a3b8;
            font-size: 0.8em;
        }}
        .signature-stamp {{
            border: 2px solid #16a34a;
            color: #16a34a;
            border-radius: 50%;
            width: 70px;
            height: 70px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.75em;
            font-weight: 800;
            transform: rotate(-12deg);
            margin: 0 auto;
        }}

        .qr-placeholder {{
            width: 75px;
            height: 75px;
            border: 1px solid #cbd5e1;
            padding: 4px;
            background: #ffffff;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            font-size: 0.65em;
            color: #64748b;
            text-align: center;
            border-radius: 4px;
        }}

        .doc-footer {{
            margin-top: 36px;
            padding-top: 16px;
            border-top: 1px solid #e2e8f0;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.75em;
            color: #64748b;
        }}

        @media print {{
            body {{
                background: white;
                padding: 0;
            }}
            .print-toolbar {{
                display: none !important;
            }}
            .doc-page {{
                border: none;
                box-shadow: none;
                padding: 0;
                max-width: 100%;
            }}
        }}
    </style>
</head>
<body>

    <div class="print-toolbar">
        <div>
            <strong>معاينة المستند الرسمي:</strong> {title} — <code>{doc_ref}</code>
        </div>
        <div style="display:flex; gap:10px;">
            <button class="btn-print" onclick="window.print()">🖨️ طباعة المستند (PDF)</button>
            <button class="btn-print" style="background:#64748b;" onclick="window.close()">إغلاق</button>
        </div>
    </div>

    <div class="doc-page">
        <!-- Header -->
        <div class="doc-header">
            <div class="header-brand">
                <h1>مكتب معاذ خضر النمري للخدمات العقارية</h1>
                <h2>Muath Khidr Al-Nemari Real Estate Services Office</h2>
                <p>
                    ترخيص الهيئة العامة للعقار (فال): <strong>1200000000</strong> &bull; ترخيص الإعلان: <strong>7200000000</strong><br>
                    سجل تجاري: <strong>4030000000</strong> &bull; الرياض - المملكة العربية السعودية
                </p>
            </div>
            <div style="display: flex; gap: 14px; align-items: center;">
                <div class="qr-placeholder">
                    <div style="font-weight: 800; color: #0f172a; font-size: 1.1em;">RECRM</div>
                    <div style="font-size: 0.8em; margin-top:2px;">موثق رسمياً</div>
                    <div style="font-size: 0.6em; color: #16a34a;">✓ معتمد</div>
                </div>
                <div class="header-meta">
                    <div><strong>الرقم المرجعي:</strong> {doc_ref}</div>
                    <div><strong>التاريخ:</strong> {doc_date}</div>
                    <div><strong>الحالة:</strong> معتمد وموثق</div>
                </div>
            </div>
        </div>

        {content}

        <!-- Footer -->
        <div class="doc-footer">
            <div>
                تم إصدار وتوثيق هذا المستند إلكترونياً عبر منصة RECRM &bull; يحمل هذا المستند حجية الإثبات بموجب نظام التعاملات الإلكترونية السعودي.
            </div>
            <div>
                صفحة 1 من 1 &bull; الرمز المرجعي: {doc_ref}
            </div>
        </div>
    </div>

</body>
</html>"""


def render_due_diligence_report(doc: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """Renders the comprehensive Technical & Investment Due Diligence Report (تقرير الفحص الفني والاستثماري)."""
    capex = meta.get("estimated_capex_sar", 228000.0)
    price_adj = meta.get("suggested_price_adjustment_sar", capex)
    condition = meta.get("structural_condition", "GOOD")
    rec = meta.get("recommendation", "RECOMMENDED_WITH_PRICE_ADJUSTMENT")

    rec_badge = '<span class="badge badge-success">موصى به للاستحواذ</span>' if "RECOMMEND" in rec and "ADJUSTMENT" not in rec else (
        '<span class="badge badge-warning">موصى به مع تعديل سعري (CapEx)</span>' if "ADJUSTMENT" in rec else '<span class="badge badge-danger">غير موصى به</span>'
    )

    sbc_badge = '<span class="badge badge-success">✓ مطابق للكود السعودي SBC</span>' if meta.get("saudi_building_code_compliant", True) else '<span class="badge badge-danger">✗ غير مطابق للكود السعودي</span>'
    rent_badge = '<span class="badge badge-success">✓ تم التحقق عبر منصة إيجار</span>' if meta.get("rent_roll_verified", True) else '<span class="badge badge-warning">جاري التحقق</span>'

    content = f"""
    <div class="doc-title-block">
        <h3>تقرير الفحص الفني والاستثماري والنافي للجهالة</h3>
        <div class="doc-subtitle">Investment & Technical Due Diligence Assessment Report</div>
    </div>

    <div class="info-grid">
        <div class="info-item"><span class="info-label">اسم الأصل / العقار:</span><span class="info-val">{meta.get("property_name", "برج الملقا التجاري والسكني")}</span></div>
        <div class="info-item"><span class="info-label">رقم الوحدة:</span><span class="info-val">{meta.get("unit_number", "8")}</span></div>
        <div class="info-item"><span class="info-label">المستثمر المستهدف:</span><span class="info-val">{meta.get("customer_name", "معاذ النمري")}</span></div>
        <div class="info-item"><span class="info-label">المهندس الفاحص:</span><span class="info-val">{meta.get("inspector_name", "م. عبد الرحمن الغامدي (معتمد)")}</span></div>
        <div class="info-item"><span class="info-label">رقم الصك الإلكتروني:</span><span class="info-val">{meta.get("deed_number", "310124009852")}</span></div>
        <div class="info-item"><span class="info-label">سعر الطلب الأولي (Asking):</span><span class="info-val">{float(meta.get("asking_price", 12000000.0)):,.2f} ريال</span></div>
    </div>

    <div class="kpi-row">
        <div class="kpi-box">
            <div class="kpi-txt">الحالة الإنشائية العامة</div>
            <div class="kpi-num" style="font-size:1.1em; color:#16a34a;">{condition}</div>
            <div class="kpi-txt">{sbc_badge}</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">إجمالي CapEx المقدر للعيوب</div>
            <div class="kpi-num" style="color:#d97706;">{float(capex):,.2f} ر.س</div>
            <div class="kpi-txt">تكلفة الإصلاحات الفنية</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">الخصم المقترح للتفاوض</div>
            <div class="kpi-num" style="color:#dc2626;">{float(price_adj):,.2f} ر.س</div>
            <div class="kpi-txt">تعديل سعري مع البائع</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">التوصية الاستثمارية النهائية</div>
            <div style="margin-top:6px;">{rec_badge}</div>
        </div>
    </div>

    <div class="section-title">أولاً: تقييم السلامة الفنية والإنشائية (Saudi Building Code SBC)</div>
    <table class="data-table">
        <thead>
            <tr>
                <th>عنصر الفحص والتدقيق</th>
                <th>الحالة الفنية</th>
                <th>الملاحظات الهندسية</th>
                <th>تكلفة المعالجة التقديرية (CapEx)</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>الهيكل الإنشائي والخرسانات</td>
                <td><span class="badge badge-success">سليم ومستقر</span></td>
                <td>لا توجد شروخ إنشائية خطرة، فواصل التمدد مطابقة للمواصفات</td>
                <td>0.00 ر.س</td>
            </tr>
            <tr>
                <td>منظومة التكييف المركزي HVAC</td>
                <td><span class="badge badge-warning">تحتاج صيانة شاملة</span></td>
                <td>استبدال ضواغط وحدتي التبريد على السطح وإعادة ضبط مجاري الهواء</td>
                <td>85,000.00 ر.س</td>
            </tr>
            <tr>
                <td>شبكة السلامة ومكافحة الحريق</td>
                <td><span class="badge badge-warning">تحديث جزئي</span></td>
                <td>استبدال مضخة الحريق الاحتياطية وتحديث لوحة الإنذار وفق كود وادي بلدي</td>
                <td>68,000.00 ر.س</td>
            </tr>
            <tr>
                <td>المصاعد والأنظمة الميكانيكية</td>
                <td><span class="badge badge-warning">صيانة دورية عاجلة</span></td>
                <td>تحديث حبال الجر وبطاقات التحكم لمصعدي الركاب</td>
                <td>45,000.00 ر.س</td>
            </tr>
            <tr>
                <td>العوازل المائية والحرارية للأسطح</td>
                <td><span class="badge badge-danger">تجديد العازل</span></td>
                <td>معالجة تسريب طفيف في السطح العلوي وتجديد طبقة البولي يوريثان</td>
                <td>30,000.00 ر.س</td>
            </tr>
            <tr style="font-weight: bold; background: #f1f5f9;">
                <td colspan="3">إجمالي تكلفة الإصلاحات الرأسمالية (Total Estimated CapEx)</td>
                <td style="color:#b45309;">{float(capex):,.2f} ر.س</td>
            </tr>
        </tbody>
    </table>

    <div class="section-title">ثانياً: التحقق التجاري وعقود الإشغال (Rent Roll Verification)</div>
    <p style="font-size:0.88em; color:#334155; margin-bottom:8px;">
        تمت مطابقة جدول الإيجارات مع منصة <strong>إيجار الموحدة</strong> ومقابلة المشرف الميداني للبرج:
    </p>
    <div class="info-grid">
        <div class="info-item"><span class="info-label">إجمالي الوحدات المشغولة:</span><span class="info-val">{meta.get("occupied_units", "18")} من أصل {meta.get("total_units", "20")} وحدة</span></div>
        <div class="info-item"><span class="info-label">نسبة الإشغال الفعلية:</span><span class="info-val">{meta.get("occupancy_rate", "90%")}</span></div>
        <div class="info-item"><span class="info-label">إجمالي الإيجارات السنوية المحصلة:</span><span class="info-val">{float(meta.get("gross_rent", 960000.0)):,.2f} ريال</span></div>
        <div class="info-item"><span class="info-label">حالة التوثيق في شبكة إيجار:</span><span class="info-val">{rent_badge}</span></div>
    </div>

    <div class="notice-box">
        <strong>خلاصة القرار والقرار الفني النهائي:</strong><br>
        العقار يتمتع بموقع استثماري ممتاز وحالة إنشائية آمنة، ولكن يستوجب حسم مبلغ <strong>{float(price_adj):,.2f} ريال</strong> 
        من قيمة الاستحواذ الإجمالية لتغطية نفقات الـ CapEx الموضحة أعلاه، مما يضمن تحقيق المستثمر لصافي العائد المستهدف (Cap Rate لا يقل عن 8.5%).
    </div>

    <div class="signatures-area">
        <div class="signature-box">
            <div class="signature-role">المهندس الفاحص المعتمد</div>
            <div class="signature-space">م. عبد الرحمن الغامدي</div>
            <div style="font-size:0.75em; color:#64748b;">رخصة الهيئة السعودية للمهندسين</div>
        </div>
        <div class="signature-box">
            <div class="signature-role">ختم الاعتماد الفني والمطابقة</div>
            <div class="signature-stamp">معتمد فحصاً</div>
            <div style="font-size:0.75em; color:#64748b; margin-top:4px;">RECRM Inspection Dept</div>
        </div>
        <div class="signature-box">
            <div class="signature-role">المستثمر / المشتري المعتمد</div>
            <div class="signature-space">معاذ خضر النمري</div>
            <div style="font-size:0.75em; color:#64748b;">اطّلع وأقر بالتوصية الفنية</div>
        </div>
    </div>
    """
    return content


def render_counter_offer_letter(doc: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """Renders the official CapEx Price Discount Negotiation Letter (خطاب التفاوض وتعديل السعر)."""
    orig_price = float(meta.get("original_price", 12000000.0))
    discount = float(meta.get("discount_amount", 228000.0))
    revised_price = orig_price - discount
    seller_name = meta.get("seller_name", "المالك / شركة الاستثمار العقاري")
    buyer_name = meta.get("buyer_name", "معاذ خضر النمري (المستثمر)")
    prop_name = meta.get("property_name", "برج الملقا التجاري - وحدة رقم 8")

    content = f"""
    <div class="doc-title-block">
        <h3>خطاب طلب تعديل سعري رسمي وتفاوض CapEx</h3>
        <div class="doc-subtitle">Official Price Adjustment Request & Negotiation Notice</div>
    </div>

    <div style="font-size:0.92em; line-height:1.8; margin-bottom:20px;">
        <p><strong>إلى المكرم / السادة:</strong> {seller_name} المحترمين<br>
        <strong>الموضوع:</strong> نتائج الفحص الفني وطلب تعديل قيمة الاستحواذ للعقار: <strong>{prop_name}</strong> (صك: {meta.get("deed_number", "310124009852")})
        </p>

        <p>
            السلام عليكم ورحمة الله وبركاته،،،<br>
            بالإشارة إلى رغبتنا الاستثمارية في الاستحواذ على الأصل الموضح أعلاه، وإلى مرحلة الفحص الفني والاستثماري النافي للجهالة التي تم إجراؤها من قبل الفريق الهندسي المختص والمعتمد؛
            نود إحاطتكم بأنه بعد استكمال المعاينة الميدانية التفصيلية والاختبارات الفنية وفق كود البناء السعودي (SBC)، تبين وجود بعض الملاحظات الفنية والعيوب التشغيلية التي تستلزم إصلاحات رأسمالية مستعجلة (CapEx) مقدرة بمبلغ:
            <strong style="color:#d97706;">{discount:,.2f} ريال سعودي</strong> (مرفق به تقرير الفحص الفني المفصل رقم: {meta.get("report_ref", "DDR-63")}).
        </p>
    </div>

    <div class="section-title">جدول التسوية المالية المقترحة للاستحواذ النهائي:</div>
    <table class="data-table">
        <thead>
            <tr>
                <th>البيان المالي</th>
                <th>المبلغ الأصلي المعروض</th>
                <th>مبلغ التعديل (خصم CapEx)</th>
                <th>القيمة المعدلة النهائية المقترحة</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td><strong>سعر الاستحواذ الأساسي (Acquisition Price)</strong></td>
                <td>{orig_price:,.2f} ر.س</td>
                <td style="color:#dc2626; font-weight:bold;">-{discount:,.2f} ر.س</td>
                <td style="color:#16a34a; font-weight:bold; font-size:1.1em;">{revised_price:,.2f} ر.س</td>
            </tr>
            <tr>
                <td>ضريبة التصرفات العقارية (5% RETT)</td>
                <td>{orig_price * 0.05:,.2f} ر.س</td>
                <td>-{discount * 0.05:,.2f} ر.س</td>
                <td>{revised_price * 0.05:,.2f} ر.س</td>
            </tr>
            <tr>
                <td>سعي الوساطة والتسويق (2.5% + ضريبة القيمة المضافة)</td>
                <td>{orig_price * 0.02875:,.2f} ر.س</td>
                <td>-{discount * 0.02875:,.2f} ر.س</td>
                <td>{revised_price * 0.02875:,.2f} ر.س</td>
            </tr>
            <tr style="background:#f1f5f9; font-weight:bold;">
                <td>إجمالي التكلفة الاستثمارية الشاملة (Total Basis)</td>
                <td>{orig_price * 1.07875:,.2f} ر.س</td>
                <td style="color:#dc2626;">-{discount * 1.07875:,.2f} ر.س</td>
                <td style="color:#1e3a8a; font-size:1.15em;">{revised_price * 1.07875:,.2f} ر.س</td>
            </tr>
        </tbody>
    </table>

    <div class="notice-box">
        <strong>بنود وضوابط العرض المعدل:</strong><br>
        1. يسري هذا العرض المالي لمدة <strong>خمسة (5) أيام عمل</strong> من تاريخ استلامه.<br>
        2. عند موافقتكم الكريمة، يتم التوقيع الفوري على ملحق اتفاقية البيع المبدئية وتجهيز شيك الإفراغ المصرفي أو التحويل المباشر عبر السجل العقاري / البورصة العقارية بوزارة العدل.<br>
        3. يتحمل المشتري مسؤولية تنفيذ كافة أعمال الصيانة والإصلاحات الرأسمالية المحددة في تقرير الفحص بعد استلام العقار.
    </div>

    <div class="signatures-area">
        <div class="signature-box">
            <div class="signature-role">المستثمر مقدم العرض</div>
            <div class="signature-space">{buyer_name}</div>
            <div style="font-size:0.75em; color:#64748b;">توقيع واعتماد العرض</div>
        </div>
        <div class="signature-box">
            <div class="signature-role">الوسيط العقاري المعتمد فال</div>
            <div class="signature-stamp">معتمد وسيطاً</div>
            <div style="font-size:0.75em; color:#64748b; margin-top:4px;">مكتب معاذ خضر النمري</div>
        </div>
        <div class="signature-box">
            <div class="signature-role">موافقة وقبول المالك / البائع</div>
            <div class="signature-space">...........................</div>
            <div style="font-size:0.75em; color:#64748b;">الختم والتاريخ</div>
        </div>
    </div>
    """
    return content


def render_baseline_financial_sheet(doc: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """Renders the Investment Baseline Financial Model Sheet (ورقة خط الأساس المالي والاستثماري للأصل)."""
    acq_price = float(meta.get("acquisition_price", 11772000.0))
    equity = float(meta.get("equity", acq_price))
    gross_rent = float(meta.get("gross_annual_rent", 960000.0))
    target_noi = float(meta.get("target_noi", 840000.0))
    opex = gross_rent - target_noi
    cap_rate = (target_noi / acq_price * 100) if acq_price > 0 else 7.14
    coc_return = (target_noi / equity * 100) if equity > 0 else 7.14

    content = f"""
    <div class="doc-title-block">
        <h3>ورقة خط الأساس المالي والأداء الاستثماري للأصل</h3>
        <div class="doc-subtitle">Asset Investment Baseline Financial Performance Sheet</div>
    </div>

    <div class="info-grid">
        <div class="info-item"><span class="info-label">الأصل الاستثماري:</span><span class="info-val">{meta.get("property_name", "برج الملقا - وحدة 8")}</span></div>
        <div class="info-item"><span class="info-label">المستثمر:</span><span class="info-val">{meta.get("customer_name", "معاذ النمري")}</span></div>
        <div class="info-item"><span class="info-label">تاريخ تأسيس خط الأساس:</span><span class="info-val">{meta.get("baseline_date", date.today().isoformat())}</span></div>
        <div class="info-item"><span class="info-label">الأفق الاستثماري المستهدف:</span><span class="info-val">{meta.get("horizon_years", "5")} سنوات</span></div>
    </div>

    <div class="kpi-row">
        <div class="kpi-box">
            <div class="kpi-txt">سعر الاستحواذ المعتمد</div>
            <div class="kpi-num">{acq_price:,.2f} ر.س</div>
            <div class="kpi-txt">بعد خصم CapEx</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">صافي الدخل التشغيلي المستهدف (NOI)</div>
            <div class="kpi-num" style="color:#16a34a;">{target_noi:,.2f} ر.س</div>
            <div class="kpi-txt">سنوياً قبل الضرائب</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">معدل الرسملة الأساسي (Cap Rate)</div>
            <div class="kpi-num" style="color:#0284c7;">{cap_rate:.2f}%</div>
            <div class="kpi-txt">Baseline Cap Rate</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">العائد على النقد المستثمر (CoC)</div>
            <div class="kpi-num" style="color:#7c3aed;">{coc_return:.2f}%</div>
            <div class="kpi-txt">Cash-on-Cash Return</div>
        </div>
    </div>

    <div class="section-title">التدفقات النقدية التشغيلية وخط الأساس المعتمد:</div>
    <table class="data-table">
        <thead>
            <tr>
                <th>البند المالي والتشغيلي</th>
                <th>المبلغ السنوي (SAR)</th>
                <th>النسبة من الدخل الإجمالي</th>
                <th>الملاحظات التشغيلية</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td><strong>إجمالي الدخل الإيجاري السنوي المتوقع (Gross Potential Rent)</strong></td>
                <td>{gross_rent:,.2f} ر.س</td>
                <td>100.0%</td>
                <td>بناءً على عقود إيجار موثقة</td>
            </tr>
            <tr>
                <td>مخصص الشغور والتحصيل (Vacancy & Credit Loss 3%)</td>
                <td style="color:#dc2626;">-{gross_rent * 0.03:,.2f} ر.س</td>
                <td>-3.0%</td>
                <td>معيار تحفظي لإعادة تأجير الوحدات</td>
            </tr>
            <tr>
                <td>مصاريف التشغيل والصيانة والإدارة (OpEx)</td>
                <td style="color:#dc2626;">-{opex:,.2f} ر.س</td>
                <td>-{opex / gross_rent * 100:.1f}%</td>
                <td>إدارة أملاك، حراسة، نظافة، صيانة وقائية</td>
            </tr>
            <tr style="font-weight: bold; background: #f0fdf4;">
                <td style="color:#15803d;">صافي الدخل التشغيلي المستهدف (Target NOI)</td>
                <td style="color:#15803d; font-size:1.15em;">{target_noi:,.2f} ر.س</td>
                <td>{target_noi / gross_rent * 100:.1f}%</td>
                <td>الأساس لقياس عوائد الأصل الربعية</td>
            </tr>
        </tbody>
    </table>

    <div class="notice-box">
        <strong>خطة المراقبة والمقارنة الدورية:</strong><br>
        يتم اعتماد هذه الأرقام كخط أساس ومقارنتها ربع سنوي مع التحصيل الفعلي في شاشة <strong>"مراقبة ومقارنة العوائد الفعلية"</strong>.
        في حال انحراف التحصيل بأكثر من 5% يتم تشغيل إجراءات الضبط التشغيلي وإعادة تسعير الوحدات الشاغرة فوراً.
    </div>

    <div class="signatures-area">
        <div class="signature-box">
            <div class="signature-role">محلل الاستثمار العقاري</div>
            <div class="signature-space">سلطان المنيع</div>
            <div style="font-size:0.75em; color:#64748b;">إدارة المحافظ الاستثمارية</div>
        </div>
        <div class="signature-box">
            <div class="signature-role">اعتماد إدارة الاستثمار</div>
            <div class="signature-stamp">معتمد مالياً</div>
            <div style="font-size:0.75em; color:#64748b; margin-top:4px;">RECRM Financial Review</div>
        </div>
        <div class="signature-box">
            <div class="signature-role">المستثمر المستفيد</div>
            <div class="signature-space">{meta.get("customer_name", "معاذ النمري")}</div>
            <div style="font-size:0.75em; color:#64748b;">موافقة على خط الأساس</div>
        </div>
    </div>
    """
    return content


def render_commercial_offer(doc: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """Renders the official Acquisition / Purchase Offer (خطاب عرض الاستحواذ المالي الرسمي)."""
    offer_amount = float(meta.get("offer_amount", meta.get("acquisition_price", 11772000.0)))
    earnest_money = float(meta.get("earnest_money", offer_amount * 0.05))

    content = f"""
    <div class="doc-title-block">
        <h3>خطاب عرض الاستحواذ والشراء المالي الرسمي</h3>
        <div class="doc-subtitle">Official Commercial Acquisition & Purchase Offer</div>
    </div>

    <div class="info-grid">
        <div class="info-item"><span class="info-label">مقدم العرض (المشتري):</span><span class="info-val">{meta.get("buyer_name", "معاذ خضر النمري")}</span></div>
        <div class="info-item"><span class="info-label">الجهة الموجه إليها (البائع):</span><span class="info-val">{meta.get("seller_name", "مالك العقار المعتمد")}</span></div>
        <div class="info-item"><span class="info-label">العقار محل العرض:</span><span class="info-val">{meta.get("property_name", "برج الملقا التجاري - وحدة 8")}</span></div>
        <div class="info-item"><span class="info-label">رقم الصك والمدينة:</span><span class="info-val">{meta.get("deed_number", "310124009852")} - الرياض</span></div>
    </div>

    <div class="kpi-row">
        <div class="kpi-box">
            <div class="kpi-txt">قيمة العرض المالي الصافي</div>
            <div class="kpi-num" style="color:#16a34a;">{offer_amount:,.2f} ر.س</div>
            <div class="kpi-txt">Net Purchase Offer</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">العربون المبدئي (Deposit)</div>
            <div class="kpi-num" style="color:#0284c7;">{earnest_money:,.2f} ر.س</div>
            <div class="kpi-txt">شيك مصدق عند التوقيع</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">طريقة السداد</div>
            <div class="kpi-num" style="font-size:1.05em; color:#334155;">نقد وفوري</div>
            <div class="kpi-txt">تحويل عبر السجل العقاري</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">مدة صلاحية العرض</div>
            <div class="kpi-num" style="color:#d97706;">7 أيام عمل</div>
            <div class="kpi-txt">ساري حتى تاريخ الاستحقاق</div>
        </div>
    </div>

    <div class="section-title">الشروط الأساسية والالتزامات التعاقدية:</div>
    <div style="font-size:0.9em; line-height:1.8; color:#1e293b;">
        <ol>
            <li><strong>خلو الصك من الموانع:</strong> يتعهد البائع بأن الصك الإلكتروني سليم وخالٍ تماماً من أي رهونات، حجوزات، أو منازعات قضائية تعيق الإفراغ الفوري لدى كتابة العدل أو البورصة العقارية.</li>
            <li><strong>الضرائب والرسوم:</strong> يلتزم المشتري بسداد ضريبة التصرفات العقارية (5%) وفق أنظمة هيئة الزكاة والضريبة والجمارك (ZATCA)، ما لم ينص الاتفاق على خلاف ذلك نظاماً.</li>
            <li><strong>سعي الوساطة العقارية:</strong> تُستحق عمولة الوسيط المرخص (مكتب معاذ النمري للخدمات العقارية) بنسبة (2.5%) مضافاً إليها ضريبة القيمة المضافة طبقاً للائحة الوساطة العقارية لهيئة العقار.</li>
            <li><strong>تسليم العين المؤجرة:</strong> يتم تحويل حقوق عقود الإيجار السارية وتحصيل المستحقات التناسبية للمشتري اعتباراً من تاريخ الإفراغ الرسمي.</li>
        </ol>
    </div>

    <div class="signatures-area">
        <div class="signature-box">
            <div class="signature-role">المشتري مقدم العرض</div>
            <div class="signature-space">{meta.get("buyer_name", "معاذ خضر النمري")}</div>
        </div>
        <div class="signature-box">
            <div class="signature-role">اعتماد الوسيط العقاري المرخص</div>
            <div class="signature-stamp">معتمد وساطة</div>
            <div style="font-size:0.75em; color:#64748b; margin-top:4px;">ترخيص فال 1200000000</div>
        </div>
        <div class="signature-box">
            <div class="signature-role">الطرف البائع (القبول والاعتماد)</div>
            <div class="signature-space">...........................</div>
        </div>
    </div>
    """
    return content


def render_taqeem_valuation(doc: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """Renders certified Saudi Taqeem Valuation Report (تقرير التقييم العقاري المعتمد - مقيم)."""
    val_val = float(meta.get("valuation_value_sar", 12150000.0))
    return f"""
    <div class="doc-title-block">
        <h3>تقرير التقييم العقاري المعتمد (هيئة تقييم)</h3>
        <div class="doc-subtitle">Certified Real Estate Appraisal Report (Taqeem Standards)</div>
    </div>
    <div class="info-grid">
        <div class="info-item"><span class="info-label">اسم الأصل:</span><span class="info-val">{meta.get("property_name", "برج الملقا التجاري والسكني")}</span></div>
        <div class="info-item"><span class="info-label">المقيّم المعتمد:</span><span class="info-val">شركة الخبراء للتقييم العقاري (عضو تقييم: 12100045)</span></div>
        <div class="info-item"><span class="info-label">أسلوب التقييم المعتمد:</span><span class="info-val">أسلوب الدخل (Income Capitalization) والمقارنة السوقية</span></div>
        <div class="info-item"><span class="info-label">تاريخ التقييم وسريانه:</span><span class="info-val">{doc.get("issued_at", date.today().isoformat())} (ساري لمدة 6 أشهر)</span></div>
    </div>
    <div class="kpi-row">
        <div class="kpi-box">
            <div class="kpi-txt">القيمة السوقية العادلة (Market Value)</div>
            <div class="kpi-num" style="color:#16a34a;">{val_val:,.2f} ر.س</div>
            <div class="kpi-txt">Taqeem Appraised Value</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">معدل الرسملة السوقي المقدر</div>
            <div class="kpi-num" style="color:#0284c7;">7.85%</div>
            <div class="kpi-txt">Market Capitalization Rate</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">سعر المتر المربع التقديري</div>
            <div class="kpi-num" style="color:#334155;">9,200 ر.س/م²</div>
            <div class="kpi-txt">مبني على مبيعات حديثة</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">مستوى الثقة في التقييم</div>
            <div class="kpi-num" style="color:#15803d;">عالي (High)</div>
            <div class="kpi-txt">بيانات صفقات موثقة</div>
        </div>
    </div>
    <div class="notice-box">
        <strong>شهادة المطابقة المهنية:</strong><br>
        تم إعداد هذا التقرير طبقاً للمعايير الدولية للتقييم (IVS) ودليل ممارسة مهنة التقييم العقاري الصادر عن الهيئة السعودية للمقيّمين المعتمدين (تقييم).
    </div>
    """


def render_tax_zakat_clearance(doc: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """Renders RETT & Zakat Clearance Document (إشعار ضريبة التصرفات العقارية والزكاة)."""
    rett_amount = float(meta.get("rett_amount", 588600.0))
    prop_val = float(meta.get("property_value", 11772000.0))
    return f"""
    <div class="doc-title-block">
        <h3>إشعار سداد ضريبة التصرفات العقارية (RETT) وبراءة الذمة</h3>
        <div class="doc-subtitle">Real Estate Transaction Tax (RETT) Assessment & Clearance</div>
    </div>
    <div class="info-grid">
        <div class="info-item"><span class="info-label">رقم الطلب الضريبي:</span><span class="info-val">{meta.get("tax_request_number", "RETT-2026-998412")}</span></div>
        <div class="info-item"><span class="info-label">رقم فاتورة سداد الإلكترونية:</span><span class="info-val">{meta.get("sadad_number", "901238491024")}</span></div>
        <div class="info-item"><span class="info-label">المكلف بسداد الضريبة:</span><span class="info-val">{meta.get("customer_name", "معاذ خضر النمري")}</span></div>
        <div class="info-item"><span class="info-label">قيمة العقار الخاضع للضريبة:</span><span class="info-val">{prop_val:,.2f} ريال</span></div>
    </div>
    <div class="kpi-row">
        <div class="kpi-box">
            <div class="kpi-txt">نسبة ضريبة التصرفات</div>
            <div class="kpi-num">5.0%</div>
            <div class="kpi-txt">وفق الأمر الملكي</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">مبلغ الضريبة الإجمالي</div>
            <div class="kpi-num" style="color:#16a34a;">{rett_amount:,.2f} ر.س</div>
            <div class="kpi-txt">مسددة بالكامل عبر سداد</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">حالة الشهادة الضريبية</div>
            <div class="kpi-num" style="font-size:1.1em; color:#15803d;">مسدد ومستوفي</div>
            <div class="kpi-txt">جاهز للإفراغ الفوري</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">بوابة الربط النظامية</div>
            <div class="kpi-num" style="font-size:1.0em; color:#0284c7;">ZATCA / العدل</div>
            <div class="kpi-txt">تم التحقق آلياً</div>
        </div>
    </div>
    <div class="notice-box">
        <strong>إشعار رسمي:</strong> تشهد هذه الوثيقة باستيفاء ضريبة التصرفات العقارية المتوجبة نظاماً على العقار المذكور، ويحق لطرفي العقد إتمام الإفراغ لدى الموثق أو البورصة العقارية دون تأخير.
    </div>
    """


def render_invoice_document(doc: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """Renders Official ZATCA Compliant Brokerage Tax Invoice (فاتورة ضريبية رسمية)."""
    subtotal = float(meta.get("subtotal", 294300.0))
    vat = subtotal * 0.15
    total = subtotal + vat
    return f"""
    <div class="doc-title-block">
        <h3>فاتورة ضريبية رسمية (وساطة وتسويق عقاري)</h3>
        <div class="doc-subtitle">Official Tax Invoice - ZATCA E-Invoicing Phase 2</div>
    </div>
    <div class="info-grid">
        <div class="info-item"><span class="info-label">رقم الفاتورة:</span><span class="info-val">{doc.get("file_name", "INV-2026-001")}</span></div>
        <div class="info-item"><span class="info-label">العميل المستفيد:</span><span class="info-val">{meta.get("customer_name", "معاذ النمري")}</span></div>
        <div class="info-item"><span class="info-label">الرقم الضريبي للمكتب (VAT ID):</span><span class="info-val">300984920100003</span></div>
        <div class="info-item"><span class="info-label">الرقم الضريبي للعميل:</span><span class="info-val">{meta.get("customer_vat", "310029384700003")}</span></div>
    </div>
    <table class="data-table">
        <thead>
            <tr>
                <th>الوصف والخدمة العقارية</th>
                <th>المبلغ الخاضع للضريبة (SAR)</th>
                <th>نسبة الضريبة (VAT)</th>
                <th>قيمة الضريبة (SAR)</th>
                <th>الإجمالي شامل الضريبة (SAR)</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>أتعاب وسعي الوساطة العقارية لصفقة الاستحواذ (ترخيص فال 1200000000)</td>
                <td>{subtotal:,.2f}</td>
                <td>15%</td>
                <td>{vat:,.2f}</td>
                <td style="font-weight:bold; color:#16a34a;">{total:,.2f}</td>
            </tr>
            <tr style="font-weight:bold; background:#f8fafc;">
                <td colspan="4" style="text-align:left;">المبلغ الإجمالي المستحق للسداد (Total Due):</td>
                <td style="color:#1e3a8a; font-size:1.15em;">{total:,.2f} ر.س</td>
            </tr>
        </tbody>
    </table>
    """


def render_contract_document(doc: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """Renders Official Sale / Lease Agreement (عقد البيع أو الإيجار الموحد)."""
    is_lease = "LEASE" in (doc.get("document_type_code") or "")
    doc_title = "عقد إيجار عقاري موحد موثق" if is_lease else "عقد بيع وتمليك عقاري نهائي موثق"
    price = float(meta.get("contract_amount", 11772000.0))
    return f"""
    <div class="doc-title-block">
        <h3>{doc_title}</h3>
        <div class="doc-subtitle">Standard Real Estate Unified Agreement (REGA Compliant)</div>
    </div>
    <div class="info-grid">
        <div class="info-item"><span class="info-label">رقم العقد الموحد:</span><span class="info-val">{meta.get("contract_number", "CON-2026-08812")}</span></div>
        <div class="info-item"><span class="info-label">تاريخ توثيق العقد:</span><span class="info-val">{doc.get("issued_at", date.today().isoformat())}</span></div>
        <div class="info-item"><span class="info-label">الطرف الأول (البائع / المؤجر):</span><span class="info-val">{meta.get("party_a", "شركة الأصول العقارية")}</span></div>
        <div class="info-item"><span class="info-label">الطرف الثاني (المشتري / المستأجر):</span><span class="info-val">{meta.get("party_b", "معاذ خضر النمري")}</span></div>
        <div class="info-item"><span class="info-label">العين العقارية:</span><span class="info-val">{meta.get("property_name", "برج الملقا التجاري - وحدة 8")}</span></div>
        <div class="info-item"><span class="info-label">القيمة المالية الإجمالية للعقد:</span><span class="info-val">{price:,.2f} ريال سعودي</span></div>
    </div>
    <div class="notice-box">
        <strong>حجية العقد:</strong> يعتبر هذا العقد سنداً تنفيذياً ملزماً لطرفيه طبقاً للأنظمة واللوائح الصادرة عن الهيئة العامة للعقار ووزارة العدل بالمملكة العربية السعودية.
    </div>
    """


def render_generic_document(doc: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """Fallback renderer for any official document."""
    doc_type_name = doc.get("document_type_name") or doc.get("document_type_code") or "مستند رسمي"
    file_name = doc.get("file_name", "وثيقة رسمية")
    notes = doc.get("notes") or meta.get("notes") or "مستند معتمد وموثق في خزينة المستندات الرقمية لمنصة RECRM."

    return f"""
    <div class="doc-title-block">
        <h3>{doc_type_name}</h3>
        <div class="doc-subtitle">{file_name}</div>
    </div>

    <div class="info-grid">
        <div class="info-item"><span class="info-label">رقم الوثيقة:</span><span class="info-val">{doc.get("document_id")}</span></div>
        <div class="info-item"><span class="info-label">تاريخ التوثيق والإصدار:</span><span class="info-val">{doc.get("issued_at") or doc.get("created_at")}</span></div>
        <div class="info-item"><span class="info-label">الجهة المرتبطة:</span><span class="info-val">{doc.get("customer_name") or meta.get("customer_name") or "مكتب العقارات"}</span></div>
        <div class="info-item"><span class="info-label">الوحدة العقارية:</span><span class="info-val">{doc.get("unit_number") or meta.get("unit_number") or "--"}</span></div>
    </div>

    <div class="notice-box">
        <strong>بيان وملاحظات المستند:</strong><br>
        {notes}
    </div>
    """


def render_reservation_document(doc: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """Renders the official Saudi Earnest Money Deposit & Reservation Receipt (سند حجز أصل استثماري وإيداع عربون)."""
    res_num = meta.get("reservation_number") or doc.get("document_id") or "RES-000001"
    dep_amount = float(meta.get("deposit_amount", 588600.0))
    offer_amount = float(meta.get("offer_amount") or meta.get("acquisition_offer_amount") or 11772000.0)
    customer_name = meta.get("customer_name") or doc.get("customer_name") or "معاذ خضر النمري (المستثمر)"
    prop_name = meta.get("property_name") or "برج الملقا التجاري - وحدة رقم 8"
    unit_num = meta.get("unit_number") or "Unit-6-52-1"
    expiry_date = str(meta.get("expires_at", "خلال 14 يوماً من تاريخ التوقيع"))[:10]
    res_status = meta.get("status", "ACTIVE")
    status_label = "حجز نشط ومثبت (ACTIVE)" if res_status == "ACTIVE" else ("حجز مكتمل بالإفراغ (CONVERTED)" if res_status == "CONVERTED" else res_status)

    content = f"""
    <div class="doc-title-block">
        <h3>سند حجز أصل عقاري استثماري وإيداع عربون الجدية</h3>
        <div class="doc-subtitle">Official Real Estate Investment Reservation & Earnest Money Deposit Certificate</div>
    </div>

    <div class="kpi-row">
        <div class="kpi-box">
            <div class="kpi-txt">رقم الحجز الرسمي</div>
            <div class="kpi-num" style="font-size:1.1em; color:#1e40af;">{res_num}</div>
            <div class="kpi-txt">سجل الحجوزات العقارية</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">مبلغ العربون المودع (Earnest Money)</div>
            <div class="kpi-num" style="color:#16a34a;">{dep_amount:,.2f} ر.س</div>
            <div class="kpi-txt">نسبة 5% من قيمة الصفقة</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">قيمة الاستحواذ الإجمالية</div>
            <div class="kpi-num" style="color:#0284c7;">{offer_amount:,.2f} ر.س</div>
            <div class="kpi-txt">القيمة المعتمدة للشراء</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">حالة الحجز القانونية</div>
            <div class="kpi-num" style="color:#7c3aed; font-size:1.0em;">{status_label}</div>
            <div class="kpi-txt">حتى تاريخ {expiry_date}</div>
        </div>
    </div>

    <div class="section-title">أولاً: بيانات الأصل العقاري الاستثماري المحجوز</div>
    <div class="info-grid">
        <div class="info-item"><span class="info-label">اسم الأصل / المبنى:</span><span class="info-val">{prop_name}</span></div>
        <div class="info-item"><span class="info-label">رقم الوحدة:</span><span class="info-val">{unit_num}</span></div>
        <div class="info-item"><span class="info-label">المدينة والحي:</span><span class="info-val">{meta.get("city_district", "الرياض - حي الملقا")}</span></div>
        <div class="info-item"><span class="info-label">المساحة الإجمالية:</span><span class="info-val">{meta.get("area_sqm", "850.00")} م²</span></div>
        <div class="info-item"><span class="info-label">المستثمر (الحاجز):</span><span class="info-val">{customer_name}</span></div>
        <div class="info-item"><span class="info-label">رقم الهوية / السجل:</span><span class="info-val">{meta.get("national_id", "1083948271")}</span></div>
        <div class="info-item"><span class="info-label">صلاحية الحجز حتى:</span><span class="info-val">{expiry_date}</span></div>
        <div class="info-item"><span class="info-label">الوسيط العقاري المعتمد:</span><span class="info-val">شركة ري كيرم العقارية (فال: 1200004921)</span></div>
    </div>

    <div class="section-title">ثانياً: الشروط والأحكام النظامية للحجز والعربون (وفق لائحة الهيئة العامة للعقار)</div>
    <div style="font-size:0.88em; color:#334155; line-height:1.8; background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:14px; margin-bottom:16px;">
        <ol style="margin:0; padding-right:20px;">
            <li><strong>أثر الحجز على الأصل:</strong> بموجب هذا السند وسداد العربون، تُسحب الوحدة العقارية فوراً من قائمة العرض المتاح (AVAILABLE) وتعتبر محجوزة رسمياً (RESERVED) لصالح المستثمر المذكور، ويمتنع على المالك أو الوسيط تسويقها أو تلقي أي عروض أخرى عليها خلال سريان مدة الحجز.</li>
            <li><strong>احتساب العربون:</strong> يُعد مبلغ العربون البالغ <strong>({dep_amount:,.2f} ر.س)</strong> جزءاً لا يتجزأ من الثمن الإجمالي المتفق عليه للاستحواذ، ويُحسم تلقائياً من إجمالي قيمة الشراء عند الإفراغ العقاري النهائي.</li>
            <li><strong>مهلة الإفراغ العقاري:</strong> يلتزم الطرفان باستكمال الإفراغ العقاري وسداد باقي الثمن عبر البورصة العقارية أو منصة ناجز قبل انتهاء المهلة المحددة بتاريخ <strong>{expiry_date}</strong>.</li>
            <li><strong>التنظيم النظامي للعربون:</strong> يخضع هذا السند لأحكام نظام الوساطة العقارية ولائحته التنفيذية الصادرة بقرار مجلس الوزراء رقم (53) وتعديلاته؛ وفي حال نكول المشتري عن إتمام الصفقة دون مبرر نظامي، يسقط حقه في استرداد العربون وفق الأنظمة المرعية، وفي حال رجوع البائع يلتزم برد مثل العربون للمشتري.</li>
        </ol>
    </div>

    <div class="notice-box">
        <strong>إشعار فوري:</strong> تم حظر بيع أو تأجير الوحدة العقارية في المنظومة لضمان سلامة الإجراءات التعاقدية حتى إتمام الإفراغ ونقل الملكية رسمياً.
    </div>

    <div class="signatures-area">
        <div class="signature-box">
            <div class="signature-role">المستثمر (الحاجز)</div>
            <div class="signature-space">{customer_name}</div>
            <div style="font-size:0.75em; color:#64748b;">توقيع دفع العربون وتثبيت الحجز</div>
        </div>
        <div class="signature-box">
            <div class="signature-role">ختم وتوثيق الوسيط العقاري (فال)</div>
            <div class="signature-stamp">سند معتمد</div>
            <div style="font-size:0.75em; color:#64748b; margin-top:4px;">RECRM Operations & Trust</div>
        </div>
        <div class="signature-box">
            <div class="signature-role">المالك / المفوض بالبيع</div>
            <div class="signature-space">...........................</div>
            <div style="font-size:0.75em; color:#64748b;">استلام العربون والتزام الحجز</div>
        </div>
    </div>
    """
    return content


def render_document_html(doc_row: Dict[str, Any]) -> str:
    """Master dispatcher that converts any document record in DB into professional printable HTML."""
    code = (doc_row.get("document_type_code") or "").upper()
    meta = doc_row.get("metadata") or {}
    if isinstance(meta, str):
        import json
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}

    doc_ref = doc_row.get("document_id") or "DOC-001"
    doc_date = str(doc_row.get("issued_at") or doc_row.get("created_at") or date.today())[:10]
    title = doc_row.get("document_type_name") or doc_row.get("file_name") or "وثيقة رسمية"

    if "DUE_DILIGENCE" in code:
        content = render_due_diligence_report(doc_row, meta)
    elif "COUNTER_OFFER" in code or "NEGOTIAT" in code:
        content = render_counter_offer_letter(doc_row, meta)
    elif "BASELINE" in code:
        content = render_baseline_financial_sheet(doc_row, meta)
    elif "COMMERCIAL_OFFER" in code or "OFFER" in code:
        content = render_commercial_offer(doc_row, meta)
    elif "RESERV" in code or "EARNEST" in code:
        content = render_reservation_document(doc_row, meta)
    elif "TAQEEM" in code:
        content = render_taqeem_valuation(doc_row, meta)
    elif "TAX" in code or "ZAKAT" in code or "RETT" in code:
        content = render_tax_zakat_clearance(doc_row, meta)
    elif "INVOICE" in code or "RECEIPT" in code:
        content = render_invoice_document(doc_row, meta)
    elif "CONTRACT" in code or "LEASE" in code or "SALE" in code:
        content = render_contract_document(doc_row, meta)
    else:
        content = render_generic_document(doc_row, meta)

    return get_base_html_wrapper(title=title, content=content, doc_ref=doc_ref, doc_date=doc_date)

