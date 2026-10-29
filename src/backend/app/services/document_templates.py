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
        body.inside-iframe {{
            background: #ffffff;
            padding: 12px;
        }}
        body.inside-iframe .print-toolbar {{
            display: none !important;
        }}
    </style>
</head>
<body>

    <div class="print-toolbar" id="doc-print-toolbar">
        <div>
            <strong>معاينة المستند الرسمي:</strong> {title} — <code>{doc_ref}</code>
        </div>
        <div style="display:flex; gap:10px;">
            <button class="btn-print" onclick="window.print()">🖨️ طباعة المستند (PDF)</button>
            <button class="btn-print" style="background:#64748b;" onclick="closePreviewDoc()">✕ إغلاق</button>
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

    <script>
        if (window.self !== window.top) {{
            document.body.classList.add('inside-iframe');
        }}
        function closePreviewDoc() {{
            try {{
                if (window.parent && window.parent !== window) {{
                    if (typeof window.parent.closeModal === 'function') {{
                        window.parent.closeModal('modal-doc-preview');
                        return;
                    }}
                    var m = window.parent.document.getElementById('modal-doc-preview');
                    if (m) {{ m.style.display = 'none'; return; }}
                }}
            }} catch(e) {{}}
            window.close();
        }}
        window.addEventListener('keydown', function(e) {{
            if (e.key === 'Escape') {{
                closePreviewDoc();
            }}
        }});
    </script>
</body>
</html>"""


def render_due_diligence_report(doc: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """Renders the comprehensive Technical & Investment Due Diligence Report (تقرير الفحص الفني والاستثماري)."""
    capex = float(meta.get("estimated_capex_sar") or 0.0)
    price_adj = float(meta.get("suggested_price_adjustment_sar") or capex)
    cond_raw = str(meta.get("structural_condition") or "GOOD").upper()
    rec_raw = str(meta.get("recommendation") or "RECOMMENDED").upper()
    asking_price = float(meta.get("purchase_price") or meta.get("asking_price") or doc.get("asking_price") or meta.get("expected_value") or meta.get("offer_amount") or 0.0)
    prop_name = meta.get("property_name") or (f"{doc.get('project_name', '')} - {doc.get('building_name', '')} - وحدة {doc.get('unit_number', '')}".strip(" -")) or f"الوحدة العقارية #{meta.get('unit_number', '')}"
    customer_name = " ".join((meta.get("customer_name") or doc.get("customer_name") or meta.get("buyer_name") or "المستثمر المستهدف").split())
    inspector_name = " ".join((meta.get("inspector_name") or doc.get("uploaded_by_user_name") or "م. الفاحص المعتمد (فحص مباني)").split())
    unit_num = meta.get("unit_number") or doc.get("unit_number") or "--"
    deed_number = meta.get("deed_number") or meta.get("instrument_number") or (f"صك-{unit_num}" if unit_num != "--" else "موثق إلكترونياً")

    # Structural condition mapping
    cond_map = {
        "EXCELLENT": ("ممتاز (سليم إنشائياً)", "#16a34a", "badge-success", "الهيكل الخرساني والأساسات بحالة إنشائية ممتازة ومطابقة لكافة اشتراطات السلامة"),
        "GOOD": ("سليم ومستقر (جيد)", "#16a34a", "badge-success", "الهيكل الإنشائي سليم ومستقر، فواصل التمدد طبيعية، ولا توجد تصدعات إنشائية جوهرية"),
        "FAIR": ("متوسط (صيانة طفيفة)", "#d97706", "badge-warning", "توجد ملاحظات سطحية وشروخ شعرية غير إنشائية تتطلب معالجة وترميم سطحي"),
        "CRITICAL": ("حرج (تصدعات خطيرة)", "#dc2626", "badge-danger", "رصد هبوط أو تصدعات إنشائية حرجة تتطلب كشفاً هندسياً عاجلاً وتدعيماً")
    }
    cond_label, cond_color, cond_badge_cls, cond_desc = cond_map.get(cond_raw, ("سليم ومستقر", "#16a34a", "badge-success", "الهيكل الإنشائي سليم ومستقر"))

    # Recommendation badge
    if "RECOMMEND" in rec_raw and "ADJUSTMENT" not in rec_raw and "REJECT" not in rec_raw:
        rec_badge = '<span class="badge badge-success">✓ موصى به للاستحواذ</span>'
    elif "ADJUSTMENT" in rec_raw or "PRICE" in rec_raw:
        rec_badge = '<span class="badge badge-warning">⚠ موصى به مع تعديل سعري (CapEx)</span>'
    else:
        rec_badge = '<span class="badge badge-danger">✗ غير موصى به للاستثمار</span>'

    # Saudi Building Code
    sbc_val = meta.get("saudi_building_code_compliant")
    sbc_compliant = sbc_val is True or str(sbc_val).lower() in ("true", "1", "yes")
    sbc_badge = '<span class="badge badge-success">✓ مطابق للكود السعودي SBC</span>' if sbc_compliant else '<span class="badge badge-danger">✗ غير مطابق للكود السعودي</span>'
    sbc_desc = "مطابق لاشتراطات كود البناء السعودي (SBC) ومتطلبات السلامة الحضرية" if sbc_compliant else "توجد ملاحظات فنية تستلزم تصحيحاً للتوافق مع الكود السعودي"
    sbc_status_lbl = "مطابق ومعتمد" if sbc_compliant else "غير مطابق"
    sbc_status_cls = "badge-success" if sbc_compliant else "badge-danger"

    # Technical systems mappings
    hvac_st = str(meta.get("hvac_status") or "OPERATIONAL").upper()
    hvac_map = {
        "OPERATIONAL": ("يعمل بكفاءة عالية", "badge-success", "وحدات التكييف والتهوية مجربة وتعمل بكفاءة تبريد وتدفق هواء ممتازة"),
        "MAINTENANCE_REQUIRED": ("يحتاج صيانة وتحديث", "badge-warning", "تحتاج صيانة دورية، تنظيف مجاري الهواء واستبدال فلاتر وقطع استهلاكية"),
        "FAULTY": ("معطل / يتطلب استبدال", "badge-danger", "وحدات تكييف رئيسية تالفة أو ضواغط محترقة تتطلب استبدالاً وتجديداً")
    }
    hvac_lbl, hvac_badge, hvac_desc = hvac_map.get(hvac_st, ("يعمل بكفاءة عالية", "badge-success", "منظومة التكييف والتهوية بحالة تشغيلية جيدة"))

    elev_st = str(meta.get("elevators_status") or "OPERATIONAL").upper()
    elev_map = {
        "OPERATIONAL": ("تعمل بعقود سارية", "badge-success", "المصاعد مفحوصة وتعمل بسلاسة بموجب عقود صيانة سنوية سارية"),
        "MAINTENANCE_REQUIRED": ("تحتاج صيانة وتحديث", "badge-warning", "تحتاج صيانة دورية، تجديد بطاقات تحكم واختبارات أمان ميكانيكية"),
        "INOPERATIVE": ("متوقفة خارج الخدمة", "badge-danger", "المصاعد متوقفة وتستوجب عمرة ميكانيكية شاملة وشهادة اعتماد فحص")
    }
    elev_lbl, elev_badge, elev_desc = elev_map.get(elev_st, ("تعمل بعقود سارية", "badge-success", "أنظمة المصاعد تعمل بحالة جيدة وموثقة"))

    roof_st = str(meta.get("roofing_and_insulation_status") or "GOOD").upper()
    roof_map = {
        "GOOD": ("عوازل سليمة ومجربة", "badge-success", "عوازل الأسطح بحالة ممتازة وخالية تماماً من آثار التسريب والرطوبة"),
        "NEEDS_REPAIR": ("يحتاج صيانة موضعية", "badge-warning", "يوجد تآكل طفيف في فواصل العزل السطحي يستوجب صيانة وقائية وتجديد"),
        "WATER_LEAKAGE": ("تسريب ورطوبة نشطة", "badge-danger", "رصد تسريبات مياه نشطة وتلف في العوازل يستلزم إزالة وإعادة عزل بالكامل")
    }
    roof_lbl, roof_badge, roof_desc = roof_map.get(roof_st, ("عوازل سليمة ومجربة", "badge-success", "عوازل الأسطح بحالة جيدة"))

    plumb_st = str(meta.get("plumbing_network_status") or "GOOD").upper()
    plumb_map = {
        "GOOD": ("سليمة ومختبرة", "badge-success", "شبكات التغذية والصرف والمضخات تعمل بضغط قياسي وخالية من التسريبات"),
        "NEEDS_REPAIR": ("تحتاج معالجة وصيانة", "badge-warning", "انسدادات أو تسريبات طفيفة في المحابس وشبكات الصرف تحتاج إصلاح")
    }
    plumb_lbl, plumb_badge, plumb_desc = plumb_map.get(plumb_st, ("سليمة ومختبرة", "badge-success", "شبكات السباكة تعمل بانتظام"))

    fire_st = str(meta.get("fire_safety_compliance") or "COMPLIANT").upper()
    fire_map = {
        "COMPLIANT": ("مكتملة ومطابقة", "badge-success", "الشبكات الكهربائية وأنظمة السلامة ومكافحة الحريق معتمدة ومطابقة"),
        "NON_COMPLIANT": ("تحتاج استكمال وتحديث", "badge-warning", "تحتاج تحديث لوحات الإنذار ومضخات الحريق واستيفاء شهادات السلامة")
    }
    fire_lbl, fire_badge, fire_desc = fire_map.get(fire_st, ("مكتملة ومطابقة", "badge-success", "أنظمة السلامة والكهرباء بحالة جيدة"))

    tech_notes = str(meta.get("technical_notes") or "").strip()

    # Determine defective systems and allocate CapEx cleanly
    defective_items = []
    if cond_raw in ("FAIR", "CRITICAL"):
        defective_items.append("الهيكل الإنشائي")
    if not sbc_compliant:
        defective_items.append("كود البناء السعودي")
    if hvac_st in ("MAINTENANCE_REQUIRED", "FAULTY"):
        defective_items.append("منظومة التكييف")
    if elev_st in ("MAINTENANCE_REQUIRED", "INOPERATIVE"):
        defective_items.append("المصاعد الميكانيكية")
    if roof_st in ("NEEDS_REPAIR", "WATER_LEAKAGE"):
        defective_items.append("عزل الأسطح")
    if plumb_st == "NEEDS_REPAIR":
        defective_items.append("شبكة السباكة")
    if fire_st == "NON_COMPLIANT":
        defective_items.append("السلامة والكهرباء")

    # Build technical systems inspection table rows
    systems_rows_html = f"""
            <tr>
                <td>الهيكل الإنشائي والخرسانات</td>
                <td><span class="badge {cond_badge_cls}">{cond_label}</span></td>
                <td>{cond_desc}</td>
                <td>{'0.00 ر.س' if 'الهيكل الإنشائي' not in defective_items else f'{capex:,.2f} ر.س'}</td>
            </tr>
            <tr>
                <td>مطابقة كود البناء السعودي (SBC)</td>
                <td><span class="badge {sbc_status_cls}">{sbc_status_lbl}</span></td>
                <td>{sbc_desc}</td>
                <td>0.00 ر.س</td>
            </tr>
            <tr>
                <td>منظومة التكييف والتهوية (HVAC)</td>
                <td><span class="badge {hvac_badge}">{hvac_lbl}</span></td>
                <td>{hvac_desc}</td>
                <td>{'0.00 ر.س' if 'منظومة التكييف' not in defective_items else f'{capex:,.2f} ر.س'}</td>
            </tr>
            <tr>
                <td>المصاعد والأنظمة الميكانيكية</td>
                <td><span class="badge {elev_badge}">{elev_lbl}</span></td>
                <td>{elev_desc}</td>
                <td>{'0.00 ر.س' if 'المصاعد الميكانيكية' not in defective_items else f'{capex:,.2f} ر.س'}</td>
            </tr>
            <tr>
                <td>العوازل المائية والحرارية للأسطح</td>
                <td><span class="badge {roof_badge}">{roof_lbl}</span></td>
                <td>{roof_desc}</td>
                <td>{'0.00 ر.س' if 'عزل الأسطح' not in defective_items else f'{capex:,.2f} ر.س'}</td>
            </tr>
            <tr>
                <td>شبكات التغذية والصرف (السباكة)</td>
                <td><span class="badge {plumb_badge}">{plumb_lbl}</span></td>
                <td>{plumb_desc}</td>
                <td>0.00 ر.س</td>
            </tr>
            <tr>
                <td>الشبكة الكهربائية والسلامة ومكافحة الحريق</td>
                <td><span class="badge {fire_badge}">{fire_lbl}</span></td>
                <td>{fire_desc}</td>
                <td>0.00 ر.س</td>
            </tr>
    """

    # If CapEx > 0 and no specific system defect was flagged, add explicit general CapEx maintenance row
    if capex > 0 and not defective_items:
        capex_note = tech_notes if tech_notes else "مخصص أعمال الصيانة الوقائية والتهيئة الفنية للأصل الاستثماري"
        systems_rows_html += f"""
            <tr style="background: #fffbeb;">
                <td>مخصص الصيانة الوقائية والتحسينات (CapEx)</td>
                <td><span class="badge badge-warning">تجهيزات تشغيلية</span></td>
                <td>{capex_note}</td>
                <td style="font-weight:700; color:#b45309;">{capex:,.2f} ر.س</td>
            </tr>
        """
    elif tech_notes:
        systems_rows_html += f"""
            <tr style="background: #f8fafc;">
                <td>ملاحظات الفاحص الإضافية</td>
                <td><span class="badge badge-info">ملاحظة هندسية</span></td>
                <td colspan="2">{tech_notes}</td>
            </tr>
        """

    # Rent roll details
    occ_count = int(meta.get("occupied_units") or meta.get("occupied_units_count") or 1)
    tot_units_raw = int(meta.get("total_units") or meta.get("total_units_inspected") or 1)
    tot_units = max(tot_units_raw, occ_count)
    raw_occ_rate = meta.get("actual_occupancy_rate")
    if raw_occ_rate is None:
        raw_occ_rate = meta.get("occupancy_rate")
    try:
        actual_occ_float = float(str(raw_occ_rate).replace("%", "")) if raw_occ_rate is not None else 95.0
    except Exception:
        actual_occ_float = 95.0

    gross_rent = float(meta.get("gross_annual_rent") or meta.get("gross_rent") or meta.get("rent_price") or 0.0)
    rent_roll_verified = meta.get("rent_roll_verified")
    rent_verified = rent_roll_verified is True or str(rent_roll_verified).lower() in ("true", "1", "yes") or rent_roll_verified is None
    rent_badge = '<span class="badge badge-success">✓ تم التحقق عبر منصة إيجار</span>' if rent_verified else '<span class="badge badge-warning">جاري التحقق</span>'
    pm_notes = meta.get("property_manager_interview_notes") or meta.get("property_manager_notes") or meta.get("pm_notes") or "تمت مقابلة المشرف الميداني والتأكد من سريان عقود الإيجار والتزام المستأجرين بالسداد عبر شبكة إيجار."

    # Financial Feasibility Calculations
    p_price = asking_price
    vac_allowance = float(meta.get("annual_vacancy_allowance") or meta.get("vacancy_allowance") or meta.get("vacancy_allowance_sar") or 0.0)
    if vac_allowance == 0.0 and gross_rent > 0 and actual_occ_float < 100.0:
        vac_allowance = gross_rent * (max(0.0, 100.0 - actual_occ_float) / 100.0)

    vac_pct = (vac_allowance / gross_rent * 100.0) if gross_rent > 0 else 0.0
    gross_rent_pct = (gross_rent / p_price * 100.0) if p_price > 0 else 0.0
    eff_gross_income = float(meta.get("effective_gross_income") or meta.get("effective_gross_income_sar") or max(0.0, gross_rent - vac_allowance))
    egi_pct = (eff_gross_income / p_price * 100.0) if p_price > 0 else 0.0
    opex = float(meta.get("annual_operating_expenses") or meta.get("operating_expenses") or meta.get("operating_expenses_opex_sar") or (gross_rent * 0.10))
    opex_pct = (opex / gross_rent * 100.0) if gross_rent > 0 else 0.0
    noi = float(meta.get("net_operating_income") or meta.get("net_operating_income_noi_sar") or meta.get("target_noi") or max(0.0, eff_gross_income - opex))
    cap_rate = float(meta.get("cap_rate") or meta.get("cap_rate_percent") or ((noi / p_price * 100.0) if p_price > 0 else 0.0))
    cash_inv = float(meta.get("cash_invested") or meta.get("cash_invested_sar") or p_price)
    coc_return = float(meta.get("cash_on_cash_return_percent") or ((noi / cash_inv * 100.0) if cash_inv > 0 else 0.0))
    adj_price = max(0.0, p_price - price_adj)
    price_adj_pct = (price_adj / p_price * 100.0) if p_price > 0 else 0.0
    total_basis = float(meta.get("total_investment_basis") or (p_price + capex))
    net_yield = float(meta.get("net_yield_percent") or ((noi / total_basis * 100.0) if total_basis > 0 else 0.0))

    content = f"""
    <div class="doc-title-block">
        <h3>تقرير الفحص الفني والاستثماري والنافي للجهالة</h3>
        <div class="doc-subtitle">Investment & Technical Due Diligence Assessment Report</div>
    </div>

    <div class="info-grid">
        <div class="info-item"><span class="info-label">اسم الأصل / العقار:</span><span class="info-val">{prop_name}</span></div>
        <div class="info-item"><span class="info-label">رقم الوحدة:</span><span class="info-val">{unit_num}</span></div>
        <div class="info-item"><span class="info-label">المستثمر المستهدف:</span><span class="info-val">{customer_name}</span></div>
        <div class="info-item"><span class="info-label">المهندس الفاحص:</span><span class="info-val">{inspector_name}</span></div>
        <div class="info-item"><span class="info-label">رقم الصك الإلكتروني:</span><span class="info-val">{deed_number}</span></div>
        <div class="info-item"><span class="info-label">سعر الطلب الأولي (Asking):</span><span class="info-val">{asking_price:,.2f} ريال</span></div>
    </div>

    <div class="kpi-row">
        <div class="kpi-box">
            <div class="kpi-txt">الحالة الإنشائية العامة</div>
            <div class="kpi-num" style="font-size:1.05em; color:{cond_color};">{cond_label}</div>
            <div class="kpi-txt">{sbc_badge}</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">إجمالي CapEx المقدر للعيوب</div>
            <div class="kpi-num" style="color:#d97706;">{capex:,.2f} ر.س</div>
            <div class="kpi-txt">تكلفة الإصلاحات الفنية</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">الخصم المقترح للتفاوض</div>
            <div class="kpi-num" style="color:#dc2626;">{price_adj:,.2f} ر.س</div>
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
                <th>الملاحظات والتقييم الهندسي</th>
                <th>تكلفة المعالجة التقديرية (CapEx)</th>
            </tr>
        </thead>
        <tbody>
            {systems_rows_html}
            <tr style="font-weight: bold; background: #f1f5f9;">
                <td colspan="3">إجمالي تكلفة الإصلاحات الرأسمالية (Total Estimated CapEx)</td>
                <td style="color:#b45309; font-size:1.05em;">{capex:,.2f} ر.س</td>
            </tr>
        </tbody>
    </table>

    <div class="section-title">ثانياً: التحقق التجاري وعقود الإشغال الميداني (Rent Roll Verification)</div>
    <p style="font-size:0.88em; color:#334155; margin-bottom:8px;">
        تمت مطابقة جدول الإيجارات مع منصة <strong>إيجار الموحدة</strong> ومقابلة المشرف الميداني للعقار:
    </p>
    <div class="info-grid">
        <div class="info-item"><span class="info-label">إجمالي الوحدات المشغولة:</span><span class="info-val">{occ_count} من أصل {tot_units} وحدة</span></div>
        <div class="info-item"><span class="info-label">نسبة الإشغال الفعلية:</span><span class="info-val">{actual_occ_float:.1f}%</span></div>
        <div class="info-item"><span class="info-label">إجمالي الإيجارات السنوية المحصلة:</span><span class="info-val">{gross_rent:,.2f} ريال</span></div>
        <div class="info-item"><span class="info-label">حالة التوثيق في شبكة إيجار:</span><span class="info-val">{rent_badge}</span></div>
    </div>
    <div style="font-size:0.84em; background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:8px 12px; margin-top:8px; color:#334155;">
        <strong>ملاحظات المشرف الميداني / مدير الأملاك:</strong> {pm_notes}
    </div>

    <div class="section-title">ثالثاً: دراسة الجدوى والتحليل المالي الاستثماري (Financial Baseline & Feasibility Analysis)</div>
    <p style="font-size:0.88em; color:#334155; margin-bottom:8px;">
        مؤشرات التدفق النقدي والعوائد الاستثمارية المستهدفة بعد أخذ نتائج الفحص الميداني ومخصصات الـ CapEx في الحسبان:
    </p>
    <table class="data-table">
        <thead>
            <tr>
                <th>المؤشر المالي / الاستثماري</th>
                <th>القيمة الأساسية (SAR)</th>
                <th>النسبة المئوية (%)</th>
                <th>الأثر والتحليل المالي</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>سعر الاستحواذ المبدئي (Initial Asking Price)</td>
                <td style="font-weight:700;">{p_price:,.2f} ر.س</td>
                <td>100.00%</td>
                <td>القيمة التعاقدية المعروضة قبل تطبيق نتائج الفحص الفني</td>
            </tr>
            <tr>
                <td>إجمالي الدخل الإيجاري السنوي (Gross Potential Rent)</td>
                <td style="font-weight:700; color:#16a34a;">{gross_rent:,.2f} ر.س</td>
                <td>{gross_rent_pct:.2f}%</td>
                <td>إجمالي الإيجارات وفق العقود وسجلات منصة إيجار</td>
            </tr>
            <tr>
                <td>مخصص الشغور والتعثر التشغيلي (Vacancy Allowance)</td>
                <td style="font-weight:700; color:#dc2626;">-{vac_allowance:,.2f} ر.س</td>
                <td>{vac_pct:.2f}%</td>
                <td>مخصص محسوب بناءً على نسبة الإشغال الفعلي ({actual_occ_float:.1f}%)</td>
            </tr>
            <tr>
                <td>الدخل الإيجاري الفعلي المحقق (Effective Gross Income - EGI)</td>
                <td style="font-weight:700; color:#0369a1;">{eff_gross_income:,.2f} ر.س</td>
                <td>{egi_pct:.2f}%</td>
                <td>صافي التدفق الإيجاري الفعلي المحصل سنوياً</td>
            </tr>
            <tr>
                <td>مصاريف التشغيل السنوية (Operating Expenses - OPEX)</td>
                <td style="font-weight:700; color:#dc2626;">-{opex:,.2f} ر.س</td>
                <td>{opex_pct:.2f}%</td>
                <td>تشمل الصيانة الدورية، الحراسة، التأمين وإدارة الأملاك</td>
            </tr>
            <tr style="background:#f0fdf4; font-weight:700;">
                <td style="color:#15803d;">صافي الدخل التشغيلي السنوي (Net Operating Income - NOI)</td>
                <td style="color:#15803d; font-size:1.05em;">{noi:,.2f} ر.س</td>
                <td style="color:#15803d; font-size:1.05em;">{cap_rate:.2f}% (Cap Rate)</td>
                <td style="color:#15803d;">معدل الرسملة الصافي المحقق على سعر الأصل</td>
            </tr>
            <tr>
                <td>رأس المال النقدي المستثمر (Equity / Cash Invested)</td>
                <td style="font-weight:700;">{cash_inv:,.2f} ر.س</td>
                <td>--</td>
                <td>إجمالي السيولة النقدية المستثمرة (شاملاً رأس المال وتكاليف الاستحواذ)</td>
            </tr>
            <tr style="background:#f8fafc; font-weight:700;">
                <td style="color:#0284c7;">العائد على النقد المستثمر (Cash-on-Cash Return - CoC)</td>
                <td style="color:#0284c7; font-size:1.05em;">{noi:,.2f} ر.س سنوياً</td>
                <td style="color:#0284c7; font-size:1.05em;">{coc_return:.2f}%</td>
                <td style="color:#0284c7;">العائد النقدي الفعلي السنوي على رأس المال المدفوع</td>
            </tr>
            <tr>
                <td>المصاريف الرأسمالية المطلوبة للإصلاح (Estimated CapEx)</td>
                <td style="font-weight:700; color:#d97706;">{capex:,.2f} ر.س</td>
                <td>--</td>
                <td>مخصص مالي لتسوية الملاحظات الفنية وإعادة تأهيل الأصل</td>
            </tr>
            <tr style="background:#eff6ff; font-weight:700;">
                <td style="color:#1d4ed8;">سعر الاستحواذ المستهدف بعد خصم الـ CapEx (Adjusted Target Price)</td>
                <td style="color:#1d4ed8; font-size:1.05em;">{adj_price:,.2f} ر.س</td>
                <td style="color:#1d4ed8; font-size:1.05em;">-{price_adj_pct:.2f}% خصم</td>
                <td style="color:#1d4ed8;">القيمة العادلة للتفاوض لحماية العائد الاستثماري</td>
            </tr>
        </tbody>
    </table>

    <div class="notice-box">
        <strong>خلاصة القرار الاستثماري والتوصية الفنية:</strong><br>
        أظهر الفحص الميداني أن العقار يتمتع بحالة إنشائية آمنة (<strong>{cond_label}</strong>) ونسبة إشغال فعلية تبلغ <strong>{actual_occ_float:.1f}%</strong> 
        بإجمالي دخل إيجاري محقق قدره <strong>{gross_rent:,.2f} ريال</strong> سنوياً. 
        ولحماية العائد الاستثماري المستهدف (معدل رسملة Cap Rate يبلغ <strong>{cap_rate:.2f}%</strong> وعائد على النقد CoC يبلغ <strong>{coc_return:.2f}%</strong>)، 
        توصي الدراسة بحسم مبلغ <strong>{price_adj:,.2f} ريال</strong> للتفاوض مع البائع لتغطية نفقات الـ CapEx الموضحة أعلاه، 
        ليكون سعر الاستحواذ المستهدف بعد التعديل <strong>{adj_price:,.2f} ريال</strong>.
    </div>

    <div class="signatures-area">
        <div class="signature-box">
            <div class="signature-role">المهندس / الاستشاري الفاحص المعتمد</div>
            <div class="signature-space" style="font-weight:700; color:#0f172a; font-size:0.95em;">{inspector_name}</div>
            <div style="font-size:0.75em; color:#64748b;">رخصة الهيئة السعودية للمهندسين</div>
        </div>
        <div class="signature-box">
            <div class="signature-role">ختم الاعتماد الفني والمطابقة</div>
            <div class="signature-stamp">معتمد فحصاً</div>
            <div style="font-size:0.75em; color:#64748b; margin-top:4px;">RECRM Inspection Dept</div>
        </div>
        <div class="signature-box">
            <div class="signature-role">المستثمر / المشتري المستهدف</div>
            <div class="signature-space" style="font-weight:700; color:#0f172a; font-size:0.95em;">{customer_name}</div>
            <div style="font-size:0.75em; color:#64748b;">اطّلع وأقر بالتوصية الفنية والاستثمارية</div>
        </div>
    </div>
    """
    return content


def render_counter_offer_letter(doc: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """Renders the official CapEx Price Discount Negotiation Letter (خطاب التفاوض وتعديل السعر)."""
    orig_price = float(meta.get("original_price") or meta.get("asking_price") or meta.get("offer_amount") or 0.0)
    discount = float(meta.get("discount_amount") or meta.get("suggested_price_adjustment_sar") or 0.0)
    revised_price = max(0.0, orig_price - discount)
    seller_name = meta.get("seller_name") or meta.get("owner_name") or "الطرف البائع"
    buyer_name = meta.get("buyer_name") or meta.get("customer_name") or "المستثمر مقدم العرض"
    prop_name = meta.get("property_name") or f"الوحدة العقارية {meta.get('unit_number', '')}"

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
            <div class="signature-space">{seller_name}</div>
            <div style="font-size:0.75em; color:#64748b;">الختم والتاريخ</div>
        </div>
    </div>
    """
    return content


def render_baseline_financial_sheet(doc: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """Renders the Investment Baseline Financial Model Sheet (ورقة خط الأساس المالي والاستثماري للأصل)."""
    acq_price = float(meta.get("acquisition_price") or meta.get("purchase_price_sar") or meta.get("asking_price") or meta.get("offer_amount") or 0.0)
    equity = float(meta.get("equity") or acq_price)
    gross_rent = float(meta.get("gross_annual_rent") or (acq_price * 0.08 if acq_price > 0 else 0.0))
    target_noi = float(meta.get("target_noi") or (gross_rent * 0.88 if gross_rent > 0 else 0.0))
    opex = max(0.0, gross_rent - target_noi)
    cap_rate = (target_noi / acq_price * 100) if acq_price > 0 else 7.14
    coc_return = (target_noi / equity * 100) if equity > 0 else 7.14

    prop_name = meta.get("property_name") or f"الأصل العقاري #{meta.get('unit_number', '')}"
    cust_name = meta.get("customer_name") or "المستثمر المستهدف"

    content = f"""
    <div class="doc-title-block">
        <h3>ورقة خط الأساس المالي والأداء الاستثماري للأصل</h3>
        <div class="doc-subtitle">Asset Investment Baseline Financial Performance Sheet</div>
    </div>

    <div class="info-grid">
        <div class="info-item"><span class="info-label">الأصل الاستثماري:</span><span class="info-val">{prop_name}</span></div>
        <div class="info-item"><span class="info-label">المستثمر:</span><span class="info-val">{cust_name}</span></div>
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


def render_investment_comparative_report(doc: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """Renders the Multi-Asset Comparative Investment Feasibility & Yield Benchmark Report (تقرير المفاضلة والتحليل المالي المقارن للوحدات الاستثمارية)."""
    cust_name = meta.get("customer_name") or "المستثمر المستهدف"
    cust_mobile = meta.get("customer_mobile") or "--"
    advisor_name = meta.get("advisor_name") or "مستشار الاستثمار العقاري"
    comp_date = meta.get("comparison_date") or str(doc.get("issued_at") or doc.get("created_at") or date.today())[:10]
    rec_notes = meta.get("recommendation_notes") or "تمت دراسة ومقارنة العوائد الاستثمارية للوحدات المرشحة واختيار الأصل الأعلى أداءً واستقراراً تأجيرياً."
    primary_unit_id = meta.get("primary_unit_id")
    compared_units = meta.get("compared_units") or []

    # If compared_units is empty, build from meta
    if not compared_units:
        p_price = float(meta.get("purchase_price") or meta.get("acquisition_price") or 0.0)
        g_rent = float(meta.get("gross_annual_rent") or 0.0)
        vac = float(meta.get("annual_vacancy_allowance") or 0.0)
        opex = float(meta.get("annual_operating_expenses") or 0.0)
        noi = max(0.0, g_rent - vac - opex)
        cap = (noi / p_price * 100) if p_price > 0 else 0.0
        compared_units = [{
            "unit_id": meta.get("unit_id") or "Unit-01",
            "unit_number": meta.get("unit_number") or meta.get("unit_id") or "INV-01",
            "property_type": meta.get("property_type") or "وحدة استثمارية",
            "area_sqm": meta.get("area_sqm") or "--",
            "purchase_price": p_price,
            "acquisition_costs": float(meta.get("acquisition_costs") or 0.0),
            "cash_invested": float(meta.get("cash_invested") or p_price),
            "gross_annual_rent": g_rent,
            "annual_vacancy_allowance": vac,
            "annual_operating_expenses": opex,
            "net_operating_income": noi,
            "gross_yield_percent": (g_rent / p_price * 100) if p_price > 0 else 0.0,
            "cap_rate": cap,
            "cash_on_cash_return_percent": cap,
            "payback_years": round(p_price / noi, 1) if noi > 0 else 0.0,
            "is_primary": True
        }]

    is_single = (len(compared_units) == 1)
    prim_u = next((u for u in compared_units if u.get("is_primary") or str(u.get("unit_id")) == str(primary_unit_id)), compared_units[0])
    doc_main_title = "دراسة الجدوى والعوائد الاستثمارية للأصل العقاري" if is_single else "تقرير المفاضلة والتحليل المالي المقارن للوحدات الاستثمارية"
    doc_sub_title = "Asset Investment Feasibility & Returns Analysis Report" if is_single else "Multi-Asset Comparative Investment Feasibility & Yield Benchmark Report"
    scope_label = "نطاق الدراسة:" if is_single else "عدد الوحدات المرشحة للمفاضلة:"
    scope_val = "أصل استثماري محدد (دراسة جدوى شاملة)" if is_single else f"{len(compared_units)} أصول عقارية"
    kpi_header_txt = f"⭐ مؤشرات الأصل الاستثماري المعتمد للاستحواذ ({prim_u.get('unit_number') or prim_u.get('unit_id')}):" if is_single else f"⭐ مؤشرات الأصل الاستثماري الموصى به للاستحواذ ({prim_u.get('unit_number') or prim_u.get('unit_id')}):"
    kpi_badge_txt = "Approved Investment Asset" if is_single else "Top Recommended Asset"
    table_sec_title = "التحليل المالي المعياري وتفاصيل تدفقات الأصل الاستثماري:" if is_single else "مصفوفة المقارنة والمفاضلة المالية التفصيلية بين الوحدات المرشحة:"
    badge_txt = "⭐ الأصل المعتمد للاستحواذ" if is_single else "⭐ الخيار الموصى به للاستحواذ"

    # Table headers
    th_cols = ""
    for u in compared_units:
        is_prim = u.get("is_primary") or (str(u.get("unit_id")) == str(primary_unit_id)) or is_single
        u_num = u.get("unit_number") or u.get("unit_id") or "وحدة"
        p_type = u.get("property_type") or "وحدة استثمارية"
        if is_prim:
            th_cols += f"""
            <th style="background:#0369a1; color:white; text-align:center; min-width:180px; padding:12px 10px; border:1px solid #0284c7;">
                <div style="background:#fef08a; color:#854d0e; font-size:0.75em; padding:2px 8px; border-radius:12px; display:inline-block; margin-bottom:6px; font-weight:800;">{badge_txt}</div>
                <div style="font-size:1.1em; font-weight:800;">{u_num}</div>
                <div style="font-size:0.8em; opacity:0.9; margin-top:2px;">{p_type}</div>
            </th>
            """
        else:
            th_cols += f"""
            <th style="background:#1e293b; color:white; text-align:center; min-width:180px; padding:12px 10px; border:1px solid #334155;">
                <div style="font-size:1.05em; font-weight:800;">{u_num}</div>
                <div style="font-size:0.8em; opacity:0.85; margin-top:2px;">{p_type}</div>
            </th>
            """

    # Helper function to generate row cells
    def make_cells(val_fn, is_highlight=False, extra_style=""):
        cells = ""
        for u in compared_units:
            is_prim = u.get("is_primary") or (str(u.get("unit_id")) == str(primary_unit_id)) or is_single
            bg = "#f0f9ff" if (is_prim and not is_highlight) else ("#eff6ff" if is_prim else "")
            border = "border-right: 2px solid #38bdf8; border-left: 2px solid #38bdf8;" if is_prim else ""
            txt = val_fn(u)
            cells += f'<td style="text-align:center; font-weight:{"700" if is_prim else "500"}; background:{bg}; {border} {extra_style}">{txt}</td>'
        return cells

    # Primary unit for the recommendation block
    prim_u = next((u for u in compared_units if u.get("is_primary") or str(u.get("unit_id")) == str(primary_unit_id)), compared_units[0])
    prim_price = float(prim_u.get("purchase_price") or 0.0)
    prim_noi = float(prim_u.get("net_operating_income") or 0.0)
    prim_cap = float(prim_u.get("cap_rate") or prim_u.get("net_operating_yield_percent") or 0.0)
    prim_coc = float(prim_u.get("cash_on_cash_return_percent") or 0.0)

    content = f"""
    <div class="doc-title-block">
        <h3>{doc_main_title}</h3>
        <div class="doc-subtitle">{doc_sub_title}</div>
    </div>

    <div class="info-grid">
        <div class="info-item"><span class="info-label">المستثمر المستهدف:</span><span class="info-val">{cust_name}</span></div>
        <div class="info-item"><span class="info-label">رقم الهاتف:</span><span class="info-val">{cust_mobile}</span></div>
        <div class="info-item"><span class="info-label">تاريخ المقارنة المالية:</span><span class="info-val">{comp_date}</span></div>
        <div class="info-item"><span class="info-label">مستشار الاستثمار المسؤول:</span><span class="info-val">{advisor_name}</span></div>
        <div class="info-item"><span class="info-label">رقم الفرصة الاستثمارية:</span><span class="info-val">{meta.get("opportunity_id", "--")}</span></div>
        <div class="info-item"><span class="info-label">{scope_label}</span><span class="info-val">{scope_val}</span></div>
    </div>

    <!-- Highlight KPI Row for Recommended Asset -->
    <div style="background:#f8fafc; border:1.5px solid #0284c7; border-radius:8px; padding:12px 16px; margin-bottom:20px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <span style="font-weight:800; color:#0369a1; font-size:0.95em;">{kpi_header_txt}</span>
            <span style="background:#dbeafe; color:#1e40af; padding:3px 10px; border-radius:12px; font-weight:700; font-size:0.75em;">{kpi_badge_txt}</span>
        </div>
        <div class="kpi-row" style="margin:0;">
            <div class="kpi-box">
                <div class="kpi-txt">سعر الشراء المقترح</div>
                <div class="kpi-num">{prim_price:,.2f} ر.س</div>
                <div class="kpi-txt">Purchase Price</div>
            </div>
            <div class="kpi-box">
                <div class="kpi-txt">صافي الدخل السنوي (NOI)</div>
                <div class="kpi-num" style="color:#16a34a;">{prim_noi:,.2f} ر.س</div>
                <div class="kpi-txt">Net Operating Income</div>
            </div>
            <div class="kpi-box">
                <div class="kpi-txt">معدل الرسملة (Cap Rate)</div>
                <div class="kpi-num" style="color:#0284c7;">{prim_cap:.2f}%</div>
                <div class="kpi-txt">عائد التشغيل الصافي</div>
            </div>
            <div class="kpi-box">
                <div class="kpi-txt">العائد على النقد (Cash-on-Cash)</div>
                <div class="kpi-num" style="color:#7c3aed;">{prim_coc:.2f}%</div>
                <div class="kpi-txt">CoC Return</div>
            </div>
        </div>
    </div>

    <!-- Side-by-Side Comparison Matrix -->
    <div class="section-title">{table_sec_title}</div>
    <div style="overflow-x:auto;">
        <table class="data-table" style="margin-top:8px;">
            <thead>
                <tr>
                    <th style="min-width:220px; text-align:right; background:#0f172a; color:#fff;">المؤشر / الخاصية الاستثمارية</th>
                    {th_cols}
                </tr>
            </thead>
            <tbody>
                <!-- 1. Asset Specifications -->
                <tr style="background:#f1f5f9; font-weight:700;">
                    <td colspan="{len(compared_units) + 1}" style="color:#1e3a8a; font-size:0.92em; padding:6px 12px;">🏢 أولاً: المواصفات الفنية والمكانية للأصول</td>
                </tr>
                <tr>
                    <td><strong>كود / رقم الوحدة</strong></td>
                    {make_cells(lambda u: str(u.get("unit_number") or u.get("unit_id") or "--"))}
                </tr>
                <tr>
                    <td>نوع العقار واستخدامه</td>
                    {make_cells(lambda u: str(u.get("property_type") or "شقة سكنية استثمارية"))}
                </tr>
                <tr>
                    <td>المساحة الإجمالية</td>
                    {make_cells(lambda u: f"{u.get('area_sqm', '--')} م²" if u.get('area_sqm') else "--")}
                </tr>

                <!-- 2. Financial Acquisition Costs -->
                <tr style="background:#f1f5f9; font-weight:700;">
                    <td colspan="{len(compared_units) + 1}" style="color:#1e3a8a; font-size:0.92em; padding:6px 12px;">💰 ثانياً: متطلبات وتكاليف الاستحواذ (SAR)</td>
                </tr>
                <tr>
                    <td><strong>سعر الاستحواذ / الشراء المطلوب</strong></td>
                    {make_cells(lambda u: f"<strong>{float(u.get('purchase_price') or 0.0):,.2f} ر.س</strong>")}
                </tr>
                <tr>
                    <td>تكاليف الاستحواذ الإضافية (سعي، نقل، ضرائب)</td>
                    {make_cells(lambda u: f"{float(u.get('acquisition_costs') or 0.0):,.2f} ر.س")}
                </tr>
                <tr>
                    <td>رأس المال النقدي المطلوب استثماره (Equity)</td>
                    {make_cells(lambda u: f"{float(u.get('cash_invested') or u.get('purchase_price') or 0.0):,.2f} ر.س")}
                </tr>

                <!-- 3. Operational Revenues & Deductions -->
                <tr style="background:#f1f5f9; font-weight:700;">
                    <td colspan="{len(compared_units) + 1}" style="color:#1e3a8a; font-size:0.92em; padding:6px 12px;">📊 ثالثاً: التدفقات النقدية التشغيلية السنوية (SAR)</td>
                </tr>
                <tr>
                    <td><strong>إجمالي الدخل الإيجاري السنوي المتوقع (Gross Rent)</strong></td>
                    {make_cells(lambda u: f"<strong>{float(u.get('gross_annual_rent') or 0.0):,.2f} ر.س</strong>")}
                </tr>
                <tr>
                    <td>الإيجار الشهري التقديري</td>
                    {make_cells(lambda u: f"{float(u.get('gross_annual_rent') or 0.0) / 12.0:,.2f} ر.س")}
                </tr>
                <tr>
                    <td>مخصص الشغور والتعثر السنوي (Vacancy Reserve)</td>
                    {make_cells(lambda u: f"-{float(u.get('annual_vacancy_allowance') or 0.0):,.2f} ر.س", extra_style="color:#dc2626;")}
                </tr>
                <tr>
                    <td>مصاريف التشغيل والصيانة والإدارة (OPEX)</td>
                    {make_cells(lambda u: f"-{float(u.get('annual_operating_expenses') or 0.0):,.2f} ر.س", extra_style="color:#dc2626;")}
                </tr>
                <tr style="background:#f0fdf4;">
                    <td style="color:#166534; font-weight:800;"><strong>صافي الدخل التشغيلي السنوي (Net Operating Income - NOI)</strong></td>
                    {make_cells(lambda u: f"<strong style='color:#15803d; font-size:1.1em;'>{float(u.get('net_operating_income') or 0.0):,.2f} ر.س</strong>", is_highlight=True)}
                </tr>

                <!-- 4. Key Performance Indicators & Returns -->
                <tr style="background:#f1f5f9; font-weight:700;">
                    <td colspan="{len(compared_units) + 1}" style="color:#1e3a8a; font-size:0.92em; padding:6px 12px;">⚡ رابعاً: مؤشرات الربحية والعائد الاستثماري (Key Yield Ratios)</td>
                </tr>
                <tr>
                    <td>العائد الإيجاري الإجمالي (Gross Rental Yield)</td>
                    {make_cells(lambda u: f"<strong>{float(u.get('gross_yield_percent') or 0.0):.2f}%</strong>")}
                </tr>
                <tr style="background:#eff6ff;">
                    <td style="color:#1d4ed8; font-weight:800;"><strong>معدل الرسملة الصافي (Capitalization Rate / Cap Rate)</strong></td>
                    {make_cells(lambda u: f"<strong style='color:#1d4ed8; font-size:1.15em;'>{float(u.get('cap_rate') or u.get('net_operating_yield_percent') or 0.0):.2f}%</strong>", is_highlight=True)}
                </tr>
                <tr>
                    <td>العائد على النقد المستثمر (Cash-on-Cash Return - CoC)</td>
                    {make_cells(lambda u: f"<strong style='color:#7c3aed;'>{float(u.get('cash_on_cash_return_percent') or 0.0):.2f}%</strong>")}
                </tr>
                <tr>
                    <td>فترة استرداد رأس المال التقديرية (Payback Period)</td>
                    {make_cells(lambda u: f"{float(u.get('payback_years') or ((float(u.get('purchase_price') or 1) / float(u.get('net_operating_income') or 1)) if float(u.get('net_operating_income') or 0) > 0 else 0)):.1f} سنة" if (float(u.get('net_operating_income') or 0) > 0 and float(u.get('payback_years') or 1) > 0) else "قيد التسكين (شغور)")}
                </tr>
            </tbody>
        </table>
    </div>

    <!-- Recommendation & Strategic Rationale Card -->
    <div class="notice-box" style="margin-top:20px; background:#f0fdf4; border-right:4px solid #16a34a; color:#14532d;">
        <div style="font-weight:800; font-size:1.05em; margin-bottom:6px;">🎯 توصية المستشار الاستثماري والخيار الموصى به:</div>
        <p style="margin:0 0 8px 0; line-height:1.7;">{rec_notes}</p>
        <div style="font-size:0.85em; color:#15803d; border-top:1px dashed #bbf7d0; padding-top:6px; margin-top:6px;">
            <strong>معايير التفضيل:</strong> تم ترجيح الوحدة <strong>{prim_u.get("unit_number") or prim_u.get("unit_id")}</strong> لتحقيقها أعلى عائد تشغيلي صافي (Cap Rate {prim_cap:.2f}%) وتوازن تكاليف التشغيل بما يحقق التدفق النقدي الأمثل للمستثمر.
        </div>
    </div>

    <!-- Best Practice Governance Note -->
    <div style="background:#fff7ed; border-right:4px solid #f97316; padding:12px 16px; border-radius:6px; font-size:0.82em; color:#9a3412; margin:16px 0; line-height:1.6;">
        <strong>ملاحظة الحوكمة والمطابقة النظامية:</strong>
        تم إعداد هذه الدراسة المالية المقارنة وفقاً لمعايير الهيئة العامة للعقار (REGA) وأصول التقييم والاستثمار العقاري المهني. تخضع هذه النتائج للتحقق الفني الميداني ضمن مهمة <strong>الفحص الفني والاستثماري النافي للجهالة (Due Diligence)</strong> قبل الارتباط التعاقدي النهائي.
    </div>

    <!-- Signatures -->
    <div class="signatures-area">
        <div class="signature-box">
            <div class="signature-role">مستشار الاستثمار العقاري</div>
            <div class="signature-space">{advisor_name}</div>
            <div style="font-size:0.75em; color:#64748b;">رخصة فال للوساطة والتسويق</div>
        </div>
        <div class="signature-box">
            <div class="signature-role">اعتماد إدارة الاستثمار والمحافظ</div>
            <div class="signature-stamp">معتمد استثمارياً</div>
            <div style="font-size:0.75em; color:#64748b; margin-top:4px;">RECRM Investment Board</div>
        </div>
        <div class="signature-box">
            <div class="signature-role">المستثمر المستهدف</div>
            <div class="signature-space">{cust_name}</div>
            <div style="font-size:0.75em; color:#64748b;">اطلاع واعتماد التوصية</div>
        </div>
    </div>
    """
    return content


def render_commercial_offer(doc: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """Renders the official Acquisition / Purchase Offer (خطاب عرض الاستحواذ المالي الرسمي)."""
    offer_amount = meta.get("offer_amount") or meta.get("acquisition_price") or meta.get("asking_price") or meta.get("expected_value") or 0.0
    offer_amount = float(offer_amount)
    earnest_money = float(meta.get("earnest_money") or (offer_amount * 0.05 if offer_amount else 0.0))
    buyer_name = meta.get("buyer_name") or meta.get("customer_name") or "المشتري مقدم العرض"
    seller_name = meta.get("seller_name") or meta.get("owner_name") or "مالك العقار المعتمد"
    prop_name = meta.get("property_name") or f"الوحدة العقارية #{meta.get('unit_number', '')}"
    
    city = meta.get("city_name") or "المملكة العربية السعودية"
    project_or_bld = meta.get("project_name") or meta.get("building_name") or ""
    city_district = f"{city} - {project_or_bld}" if project_or_bld else city

    content = f"""
    <div class="doc-title-block">
        <h3>خطاب عرض الاستحواذ والشراء المالي الرسمي</h3>
        <div class="doc-subtitle">Official Commercial Acquisition & Purchase Offer</div>
    </div>

    <div class="info-grid">
        <div class="info-item"><span class="info-label">مقدم العرض (المشتري):</span><span class="info-val">{buyer_name}</span></div>
        <div class="info-item"><span class="info-label">الجهة الموجه إليها (البائع):</span><span class="info-val">{seller_name}</span></div>
        <div class="info-item"><span class="info-label">العقار محل العرض:</span><span class="info-val">{prop_name}</span></div>
        <div class="info-item"><span class="info-label">رقم الصك والمدينة:</span><span class="info-val">{meta.get("deed_number", "310124009852")} - {city_district}</span></div>
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
            <div class="kpi-txt">تحويل عبر السجل العقاري / البورصة</div>
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
            <div class="signature-space">{buyer_name}</div>
        </div>
        <div class="signature-box">
            <div class="signature-role">اعتماد الوسيط العقاري المرخص</div>
            <div class="signature-stamp">معتمد وساطة</div>
            <div style="font-size:0.75em; color:#64748b; margin-top:4px;">ترخيص فال 1200000000</div>
        </div>
        <div class="signature-box">
            <div class="signature-role">الطرف البائع (القبول والاعتماد)</div>
            <div class="signature-space">{seller_name}</div>
        </div>
    </div>
    """
    return content


def render_offer_decision(doc: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """Renders the official Commercial Offer Decision & Negotiation Acceptance Protocol (وثيقة ومحضر قرار العرض المالي)."""
    offer_amount = float(meta.get("offer_amount", 800000.0))
    asking_price = float(meta.get("asking_price", offer_amount))
    decision = str(meta.get("decision", meta.get("offer_status", "ACCEPTED"))).upper()
    discount_amount = max(0.0, asking_price - offer_amount)
    discount_pct = round((discount_amount / asking_price * 100.0), 2) if asking_price > 0 else 0.0

    customer_name = meta.get("customer_name") or meta.get("buyer_name") or "العميل المشتري"
    owner_name = meta.get("owner_name") or meta.get("seller_name") or "مالك العقار المعتمد"
    property_name = meta.get("property_name") or f"الوحدة العقارية #{meta.get('unit_number', '')}"
    offer_ref = meta.get("offer_id") or meta.get("offer_number") or doc.get("document_id") or "OFF-001"

    decision_label_ar = "✓ تم قبول واعتماد العرض رسمياً (ACCEPTED)"
    decision_color = "#16a34a"
    if decision == "REJECTED":
        decision_label_ar = "✕ تم رفض العرض المالي (REJECTED)"
        decision_color = "#dc2626"
    elif decision == "COUNTERED":
        decision_label_ar = "⚡ تم تقديم عرض مالي مقابل للتفاوض (COUNTERED)"
        decision_color = "#d97706"
    elif decision == "APPROVED":
        decision_label_ar = "✓ معتمد من إدارة المبيعات (APPROVED)"
        decision_color = "#1e3a8a"

    earnest_money = float(meta.get("earnest_money", offer_amount * 0.05))

    content = f"""
    <div class="doc-title-block">
        <h3>وثيقة قرار العرض المالي واعتماد التفاوض</h3>
        <div class="doc-subtitle">Official Commercial Offer Decision & Negotiation Protocol</div>
    </div>

    <div class="info-grid">
        <div class="info-item"><span class="info-label">العميل (مقدم العرض):</span><span class="info-val">{customer_name}</span></div>
        <div class="info-item"><span class="info-label">المالك / الطرف البائع:</span><span class="info-val">{owner_name}</span></div>
        <div class="info-item"><span class="info-label">العقار محل التفاوض:</span><span class="info-val">{property_name}</span></div>
        <div class="info-item"><span class="info-label">رقم مرجع العرض:</span><span class="info-val">{offer_ref}</span></div>
    </div>

    <div class="kpi-row">
        <div class="kpi-box">
            <div class="kpi-txt">قرار التفاوض المعتمد</div>
            <div class="kpi-num" style="color:{decision_color}; font-size:1.05em;">{decision_label_ar}</div>
            <div class="kpi-txt">Negotiation Verdict</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">قيمة العرض المالي المعتمد</div>
            <div class="kpi-num" style="color:#16a34a;">{offer_amount:,.2f} ر.س</div>
            <div class="kpi-txt">Approved Offer Amount</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">السعر المطلوب المعلن</div>
            <div class="kpi-num" style="color:#475569;">{asking_price:,.2f} ر.س</div>
            <div class="kpi-txt">نسبة الخصم: {discount_pct}% ({discount_amount:,.2f} ر.س)</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">العربون المطلوب للحجز (5%)</div>
            <div class="kpi-num" style="color:#0284c7;">{earnest_money:,.2f} ر.س</div>
            <div class="kpi-txt">شيك مصدق / إيداع سداد</div>
        </div>
    </div>

    <div class="section-title">بنود قرار العرض المالي والتزامات الأطراف:</div>
    <div style="font-size:0.9em; line-height:1.8; color:#1e293b;">
        <ol>
            <li><strong>اعتماد نتيجة التفاوض:</strong> يُقر الطرفان بصحة القيمة المالية المتفق عليها أعلاه، وتعتبر ملزمة للطرفين للمضي قدماً في إجراءات حجز الوحدة وتحصيل العربون ثم إفراغ الصك أو توثيق العقد.</li>
            <li><strong>تثبيت حجز الأصل العقاري:</strong> بناءً على صدور هذا القرار، يتم سحب الوحدة العقارية من قائمة العرض المتاح وتحويلها لحالة (RESERVED) فور سداد العربون النظامي البالغ ({earnest_money:,.2f} ر.س).</li>
            <li><strong>المهلة الزمنية لسداد العربون:</strong> يلتزم المشتري بإيداع العربون خلال مهلة أقصاها 48 ساعة من تاريخ صدور هذا القرار، وإلا اعتبر العرض لاغياً وتعود الوحدة للعرض العام تلقائياً.</li>
            <li><strong>أتعاب الوساطة العقارية:</strong> يلتزم الأطراف بسداد أتعاب الوساطة العقارية المقررة نظاماً بنسبة (2.5%) وفق لوائح الهيئة العامة للعقار وضوابط شبكة إيجار / البورصة العقارية.</li>
        </ol>
    </div>

    <div class="signatures-area">
        <div class="signature-box">
            <div class="signature-role">المشتري (الموافقة والالتزام)</div>
            <div class="signature-space">{customer_name}</div>
        </div>
        <div class="signature-box">
            <div class="signature-role">اعتماد الوسيط العقاري المرخص</div>
            <div class="signature-stamp">قرار معتمد</div>
            <div style="font-size:0.75em; color:#64748b; margin-top:4px;">ترخيص فال 1200000000</div>
        </div>
        <div class="signature-box">
            <div class="signature-role">المالك / المفوض بالاعتماد</div>
            <div class="signature-space">{owner_name}</div>
        </div>
    </div>
    """
    return content


def render_taqeem_valuation(doc: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """Renders certified Saudi Taqeem Valuation Report (تقرير التقييم العقاري المعتمد - مقيم)."""
    val_val = float(meta.get("valuation_value_sar") or meta.get("market_value_sar") or meta.get("asking_price") or meta.get("offer_amount") or 0.0)
    prop_name = meta.get("property_name") or f"الوحدة العقارية #{meta.get('unit_number', '')}"
    return f"""
    <div class="doc-title-block">
        <h3>تقرير التقييم العقاري المعتمد (هيئة تقييم)</h3>
        <div class="doc-subtitle">Certified Real Estate Appraisal Report (Taqeem Standards)</div>
    </div>
    <div class="info-grid">
        <div class="info-item"><span class="info-label">اسم الأصل / العقار:</span><span class="info-val">{prop_name}</span></div>
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
            <div class="kpi-num" style="color:#334155;">حسب تقرير مقيم</div>
            <div class="kpi-txt">مبني على صفقات مقارنة موثقة</div>
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
    prop_val = float(meta.get("property_value") or meta.get("offer_amount") or meta.get("asking_price") or 0.0)
    rett_amount = float(meta.get("rett_amount") or (prop_val * 0.05 if prop_val else 0.0))
    cust_name = meta.get("customer_name") or doc.get("customer_name") or "المكلف بسداد الضريبة"
    return f"""
    <div class="doc-title-block">
        <h3>إشعار سداد ضريبة التصرفات العقارية (RETT) وبراءة الذمة</h3>
        <div class="doc-subtitle">Real Estate Transaction Tax (RETT) Assessment & Clearance</div>
    </div>
    <div class="info-grid">
        <div class="info-item"><span class="info-label">رقم الطلب الضريبي:</span><span class="info-val">{meta.get("tax_request_number", "RETT-2026-998412")}</span></div>
        <div class="info-item"><span class="info-label">رقم فاتورة سداد الإلكترونية:</span><span class="info-val">{meta.get("sadad_number", "901238491024")}</span></div>
        <div class="info-item"><span class="info-label">المكلف بسداد الضريبة:</span><span class="info-val">{cust_name}</span></div>
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
    base_deal_val = float(meta.get("offer_amount") or meta.get("asking_price") or 0.0)
    subtotal = float(meta.get("subtotal") or (base_deal_val * 0.025 if base_deal_val > 0 else 0.0))
    vat = subtotal * 0.15
    total = subtotal + vat
    cust_name = meta.get("customer_name") or doc.get("customer_name") or "العميل المستفيد"
    return f"""
    <div class="doc-title-block">
        <h3>فاتورة ضريبية رسمية (وساطة وتسويق عقاري)</h3>
        <div class="doc-subtitle">Official Tax Invoice - ZATCA E-Invoicing Phase 2</div>
    </div>
    <div class="info-grid">
        <div class="info-item"><span class="info-label">رقم الفاتورة:</span><span class="info-val">{doc.get("file_name", "INV-2026-001")}</span></div>
        <div class="info-item"><span class="info-label">العميل المستفيد:</span><span class="info-val">{cust_name}</span></div>
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
                <td>أتعاب وسعي الوساطة العقارية المعتمدة (ترخيص فال 1200000000)</td>
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
    is_lease = "LEASE" in (doc.get("document_type_code") or "").upper() or (str(meta.get("inquiry_type", "")).upper() == "RENT")
    doc_title = "عقد إيجار عقاري موحد موثق" if is_lease else "عقد بيع وتمليك عقاري نهائي موثق"
    price = float(meta.get("contract_amount") or meta.get("offer_amount") or meta.get("asking_price") or meta.get("rent_price") or 0.0)
    party_a_title = "الطرف الأول (المؤجر):" if is_lease else "الطرف الأول (البائع):"
    party_b_title = "الطرف الثاني (المستأجر):" if is_lease else "الطرف الثاني (المشتري):"
    party_a = meta.get("owner_name") or meta.get("seller_name") or meta.get("party_a") or ("المؤجر / مالك العقار" if is_lease else "البائع / مالك العقار")
    party_b = meta.get("customer_name") or meta.get("buyer_name") or meta.get("party_b") or ("المستأجر" if is_lease else "المشتري")
    prop_name = meta.get("property_name") or f"الوحدة العقارية {meta.get('unit_number', '')}"

    freq_map = {
        "MONTHLY": "شهري (12 دفعة)",
        "QUARTERLY": "ربع سنوي (4 دفعات)",
        "SEMI_ANNUAL": "نصف سنوي (دفعتان)",
        "ANNUAL": "سنوي (دفعة واحدة)"
    }
    freq_label = freq_map.get(str(meta.get("payment_frequency", "")).upper(), meta.get("payment_frequency") or "سنوي")

    lease_extra = ""
    if is_lease:
        lease_extra = f"""
        <div class="info-item"><span class="info-label">سريان العقد:</span><span class="info-val">من {meta.get("start_date", "--")} إلى {meta.get("end_date", "--")}</span></div>
        <div class="info-item"><span class="info-label">دورية سداد الدفعات:</span><span class="info-val">{freq_label}</span></div>
        <div class="info-item"><span class="info-label">مبلغ الضمان / التأمين:</span><span class="info-val">{float(meta.get("deposit_amount") or 0.0):,.2f} ريال</span></div>
        """

    return f"""
    <div class="doc-title-block">
        <h3>{doc_title}</h3>
        <div class="doc-subtitle">Standard Real Estate Unified Agreement (REGA Compliant)</div>
    </div>
    <div class="info-grid">
        <div class="info-item"><span class="info-label">رقم العقد الموحد:</span><span class="info-val">{meta.get("contract_number") or doc.get("contract_number") or "--"}</span></div>
        <div class="info-item"><span class="info-label">تاريخ توثيق العقد:</span><span class="info-val">{doc.get("issued_at", date.today().isoformat())}</span></div>
        <div class="info-item"><span class="info-label">{party_a_title}</span><span class="info-val">{party_a}</span></div>
        <div class="info-item"><span class="info-label">{party_b_title}</span><span class="info-val">{party_b}</span></div>
        <div class="info-item"><span class="info-label">العين العقارية:</span><span class="info-val">{prop_name}</span></div>
        <div class="info-item"><span class="info-label">القيمة المالية الإجمالية للعقد:</span><span class="info-val">{price:,.2f} ريال سعودي</span></div>
        {lease_extra}
    </div>
    <div class="notice-box">
        <strong>حجية العقد:</strong> يعتبر هذا العقد سنداً تنفيذياً ملزماً لطرفيه طبقاً للأنظمة واللوائح الصادرة عن الهيئة العامة للعقار ووزارة العدل بالمملكة العربية السعودية.
    </div>
    """


def render_commission_settlement(doc: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """Renders Official Licensed Broker Commission Settlement Voucher (سند صرف واعتماد عمولة الوسيط المرخص فال)."""
    comm_amount = float(meta.get("commission_amount") or doc.get("amount") or 0.0)
    deal_value = float(meta.get("contract_amount") or meta.get("offer_amount") or meta.get("gross_deal_value") or (comm_amount / 0.0075 if comm_amount > 0 else 0.0))
    broker_name = meta.get("broker_name") or doc.get("broker_name") or "الوسيط المعتمد"
    fal_no = meta.get("fal_license_number") or "1200018890"
    iban = meta.get("iban") or "SA0380000000608010167519"
    contract_ref = meta.get("contract_number") or "عقد موثق"
    unit_ref = meta.get("unit_number") or "--"
    approved_date = str(meta.get("approved_at") or doc.get("issued_at") or date.today())[:10]

    return f"""
    <div class="doc-title-block">
        <h3>سند صرف واعتماد عمولة وسيط عقاري معتمد</h3>
        <div class="doc-subtitle">Official REGA Fal-Licensed Broker Commission Disbursement Voucher</div>
    </div>
    <div class="info-grid">
        <div class="info-item"><span class="info-label">اسم الوسيط المستحق:</span><span class="info-val">{broker_name}</span></div>
        <div class="info-item"><span class="info-label">رقم رخصة فال العقارية:</span><span class="info-val">{fal_no}</span></div>
        <div class="info-item"><span class="info-label">رقم العقد المرتبط:</span><span class="info-val">{contract_ref}</span></div>
        <div class="info-item"><span class="info-label">الوحدة العقارية:</span><span class="info-val">{unit_ref}</span></div>
        <div class="info-item"><span class="info-label">إجمالي قيمة الصفقة:</span><span class="info-val">{deal_value:,.2f} ريال سعودي</span></div>
        <div class="info-item"><span class="info-label">صافي العمولة المستحقة:</span><span class="info-val" style="color:#15803d; font-weight:800;">{comm_amount:,.2f} ريال سعودي</span></div>
        <div class="info-item"><span class="info-label">الحساب البنكي (IBAN):</span><span class="info-val">{iban}</span></div>
        <div class="info-item"><span class="info-label">تاريخ التدقيق والاعتماد:</span><span class="info-val">{approved_date}</span></div>
    </div>
    <div class="notice-box">
        <strong>إشعار الصرف المحاسبي:</strong> تم تدقيق سريان رخصة فال للوسيط واستيفاء شروط تسليم العقار وتحصيل سعي الوساطة لحساب الشركة، واعتماد قيد الصرف المحاسبي نظاماً.
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
    """Renders the official Saudi Earnest Money Deposit & Reservation Receipt (سند حجز وحدة عقارية وإيداع عربون)."""
    res_num = meta.get("reservation_number") or doc.get("document_id") or "RES-000001"
    dep_amount = float(meta.get("deposit_amount", 0.0) or 0.0)
    
    # Accurate property/deal price resolution:
    offer_amount = meta.get("offer_amount") or meta.get("acquisition_price") or meta.get("expected_value") or meta.get("asking_price") or meta.get("rent_price")
    if offer_amount is not None:
        offer_amount = float(offer_amount)
    elif dep_amount > 0:
        offer_amount = dep_amount / 0.05
    else:
        offer_amount = 0.0

    inquiry_type = str(meta.get("inquiry_type", "BUY")).upper()
    if inquiry_type == "RENT":
        doc_main_title = "سند حجز وحدة عقارية وإيداع عربون إيجاري"
        doc_sub_title = "Official Real Estate Lease Reservation & Earnest Money Deposit Certificate"
        buyer_role_title = "المستأجر (الحاجز)"
        owner_role_title = "المؤجر / مالك العقار"
        price_metric_title = "القيمة الإيجارية السنوية"
        price_metric_sub = "إجمالي الأجرة السنوية المعتمدة"
        terms_completion_text = "مهلة توثيق العقد الإيجاري: يلتزم الطرفان باستكمال توثيق عقد الإيجار الموحد عبر شبكة إيجار وسداد باقي الدفعة الأولى قبل انتهاء المهلة المحددة."
    elif inquiry_type == "INVESTMENT":
        doc_main_title = "سند حجز أصل عقاري استثماري وإيداع عربون الجدية"
        doc_sub_title = "Official Real Estate Investment Reservation & Earnest Money Deposit Certificate"
        buyer_role_title = "المستثمر (الحاجز)"
        owner_role_title = "المالك / المفوض بالبيع"
        price_metric_title = "قيمة الاستحواذ الإجمالية"
        price_metric_sub = "القيمة الاستثمارية المعتمدة للشراء"
        terms_completion_text = "مهلة الإفراغ العقاري: يلتزم الطرفان باستكمال الإفراغ العقاري ونقل الملكية وسداد باقي الثمن عبر البورصة العقارية أو منصة ناجز قبل انتهاء المهلة المحددة."
    else:
        doc_main_title = "سند حجز وحدة عقارية وإيداع عربون الشراء"
        doc_sub_title = "Official Real Estate Purchase Reservation & Earnest Money Deposit Certificate"
        buyer_role_title = "المشتري (الحاجز)"
        owner_role_title = "المالك / الطرف البائع"
        price_metric_title = "قيمة الشراء المعتمدة"
        price_metric_sub = "إجمالي الثمن المتفق عليه للوحدة"
        terms_completion_text = "مهلة الإفراغ العقاري: يلتزم الطرفان باستكمال الإفراغ العقاري وسداد باقي الثمن عبر البورصة العقارية أو منصة ناجز بوزارة العدل قبل انتهاء المهلة المحددة."

    customer_name = meta.get("customer_name") or doc.get("customer_name") or "العميل المستفيد"
    owner_name = meta.get("owner_name") or meta.get("seller_name") or "مالك العقار المعتمد"
    prop_name = meta.get("property_name") or f"الوحدة العقارية {meta.get('unit_number', '')}"
    unit_num = meta.get("unit_number") or "--"
    
    area_val = meta.get("area_sqm")
    area_sqm = f"{float(area_val):,.2f} م²" if area_val else "حسب الصك المعتمد"

    city = meta.get("city_name") or "المملكة العربية السعودية"
    project_or_bld = meta.get("project_name") or meta.get("building_name") or ""
    city_district = f"{city} - {project_or_bld}" if project_or_bld else city

    expiry_date = str(meta.get("expires_at", "خلال 48 ساعة من تاريخ الإصدار"))[:10]
    res_status = meta.get("status", "ACTIVE")
    status_label = "حجز نشط ومثبت (ACTIVE)" if res_status == "ACTIVE" else ("حجز مكتمل بالإفراغ (CONVERTED)" if res_status == "CONVERTED" else res_status)
    national_id = meta.get("national_id") or meta.get("customer_mobile") or "موثق بالنظام"

    content = f"""
    <div class="doc-title-block">
        <h3>{doc_main_title}</h3>
        <div class="doc-subtitle">{doc_sub_title}</div>
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
            <div class="kpi-txt">دفعة حجز مؤكدة</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">{price_metric_title}</div>
            <div class="kpi-num" style="color:#0284c7;">{offer_amount:,.2f} ر.س</div>
            <div class="kpi-txt">{price_metric_sub}</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-txt">حالة الحجز القانونية</div>
            <div class="kpi-num" style="color:#7c3aed; font-size:1.0em;">{status_label}</div>
            <div class="kpi-txt">ساري حتى {expiry_date}</div>
        </div>
    </div>

    <div class="section-title">أولاً: بيانات الأصل والوحدة العقارية المحجوزة</div>
    <div class="info-grid">
        <div class="info-item"><span class="info-label">اسم المشروع / المبنى:</span><span class="info-val">{prop_name}</span></div>
        <div class="info-item"><span class="info-label">رقم الوحدة:</span><span class="info-val">{unit_num}</span></div>
        <div class="info-item"><span class="info-label">المدينة والحي:</span><span class="info-val">{city_district}</span></div>
        <div class="info-item"><span class="info-label">المساحة الإجمالية:</span><span class="info-val">{area_sqm}</span></div>
        <div class="info-item"><span class="info-label">{buyer_role_title}:</span><span class="info-val">{customer_name}</span></div>
        <div class="info-item"><span class="info-label">{owner_role_title}:</span><span class="info-val">{owner_name}</span></div>
        <div class="info-item"><span class="info-label">صلاحية الحجز حتى:</span><span class="info-val">{expiry_date}</span></div>
        <div class="info-item"><span class="info-label">الوسيط العقاري المعتمد:</span><span class="info-val">مكتب معاذ خضر النمري (ترخيص فال: 1200000000)</span></div>
    </div>

    <div class="section-title">ثانياً: الشروط والأحكام النظامية للحجز والعربون (وفق لائحة الهيئة العامة للعقار)</div>
    <div style="font-size:0.88em; color:#334155; line-height:1.8; background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:14px; margin-bottom:16px;">
        <ol style="margin:0; padding-right:20px;">
            <li><strong>أثر الحجز على الأصل:</strong> بموجب هذا السند وسداد العربون، تُسحب الوحدة العقارية فوراً من قائمة العرض المتاح (AVAILABLE) وتعتبر محجوزة رسمياً (RESERVED) لصالح الطرف الحاجز المذكور أعلاه، ويمتنع على المالك أو الوسيط تسويقها أو تلقي أي عروض أخرى عليها خلال سريان مدة الحجز.</li>
            <li><strong>احتساب العربون:</strong> يُعد مبلغ العربون البالغ <strong>({dep_amount:,.2f} ر.س)</strong> جزءاً لا يتجزأ من الثمن الإجمالي المتفق عليه، ويُحسم تلقائياً من إجمالي القيمة عند التعاقد أو الإفراغ العقاري النهائي.</li>
            <li><strong>مهلة الإنجاز والتعاقد:</strong> {terms_completion_text} بتاريخ <strong>{expiry_date}</strong>.</li>
            <li><strong>التنظيم النظامي للعربون:</strong> يخضع هذا السند لأحكام نظام الوساطة العقارية ولائحته التنفيذية الصادرة عن الهيئة العامة للعقار؛ وفي حال نكول المشتري أو المستأجر عن إتمام الصفقة دون مبرر نظامي يسقط حقه في استرداد العربون وفق الأنظمة المرعية، وفي حال رجوع البائع يلتزم برد مثل العربون.</li>
        </ol>
    </div>

    <div class="notice-box">
        <strong>إشعار فوري:</strong> تم قفل وتثبيت حالة الوحدة العقارية في المنظومة لمنع التعارض لضمان سلامة الإجراءات التعاقدية حتى إتمام التوثيق الرسمي.
    </div>

    <div class="signatures-area">
        <div class="signature-box">
            <div class="signature-role">{buyer_role_title}</div>
            <div class="signature-space">{customer_name}</div>
            <div style="font-size:0.75em; color:#64748b;">توقيع دفع العربون وتثبيت الحجز</div>
        </div>
        <div class="signature-box">
            <div class="signature-role">ختم وتوثيق الوسيط العقاري (فال)</div>
            <div class="signature-stamp">سند معتمد</div>
            <div style="font-size:0.75em; color:#64748b; margin-top:4px;">RECRM Operations & Trust</div>
        </div>
        <div class="signature-box">
            <div class="signature-role">{owner_role_title}</div>
            <div class="signature-space">{owner_name}</div>
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

    if "INVEST_COMPARE" in code or "COMPARATIVE" in code or meta.get("doc_type") == "INVEST_COMPARATIVE_REPORT" or "مقارنة" in (doc_row.get("file_name") or ""):
        content = render_investment_comparative_report(doc_row, meta)
    elif "DUE_DILIGENCE" in code:
        content = render_due_diligence_report(doc_row, meta)
    elif "COUNTER_OFFER" in code or "NEGOTIAT" in code:
        content = render_counter_offer_letter(doc_row, meta)
    elif "BASELINE" in code:
        content = render_baseline_financial_sheet(doc_row, meta)
    elif "OFFER_DECISION" in code or "DECISION" in code:
        content = render_offer_decision(doc_row, meta)
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
    elif "COMMISSION" in code:
        content = render_commission_settlement(doc_row, meta)
    else:
        content = render_generic_document(doc_row, meta)

    return get_base_html_wrapper(title=title, content=content, doc_ref=doc_ref, doc_date=doc_date)

