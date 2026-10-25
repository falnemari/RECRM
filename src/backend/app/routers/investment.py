from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import asyncpg

from app.database import get_db
from app.schemas.common import ResponseEnvelope, BaseMeta
from app.services.workflow_engine import get_next_id
from app.services.calculation_service import CalculationService

router = APIRouter(prefix="/investment", tags=["Investment Due Diligence & Portfolio"])


class DueDiligenceReportCreateIn(BaseModel):
    opportunity_id: str
    unit_id: str
    viewing_id: Optional[str] = None
    structural_condition: Optional[str] = "GOOD"
    building_age_years: Optional[int] = 5
    saudi_building_code_compliant: Optional[bool] = True
    hvac_status: Optional[str] = "OPERATIONAL"
    elevators_status: Optional[str] = "OPERATIONAL"
    plumbing_network_status: Optional[str] = "GOOD"
    electrical_network_status: Optional[str] = "GOOD"
    roofing_and_insulation_status: Optional[str] = "GOOD"
    fire_safety_compliance: Optional[str] = "COMPLIANT"
    estimated_capex_sar: Optional[float] = 0.0
    technical_notes: Optional[str] = None
    location_traffic_flow: Optional[str] = "HIGH"
    access_and_egress_quality: Optional[str] = "GOOD"
    parking_availability: Optional[str] = "ADEQUATE"
    actual_occupancy_rate: Optional[float] = 95.0
    total_units_inspected: Optional[int] = 1
    occupied_units_count: Optional[int] = 1
    vacant_units_count: Optional[int] = 0
    rent_roll_verified: Optional[bool] = True
    property_manager_interview_notes: Optional[str] = None
    commercial_viability_score: Optional[int] = 85
    commercial_notes: Optional[str] = None
    recommendation: Optional[str] = "RECOMMENDED"
    suggested_price_adjustment_sar: Optional[float] = 0.0
    final_verdict_summary: Optional[str] = None

    # Financial Due Diligence & Baseline Metrics
    purchase_price_sar: Optional[float] = None
    gross_annual_rent_sar: Optional[float] = None
    vacancy_allowance_sar: Optional[float] = None
    effective_gross_income_sar: Optional[float] = None
    operating_expenses_opex_sar: Optional[float] = None
    net_operating_income_noi_sar: Optional[float] = None
    total_investment_basis_sar: Optional[float] = None
    gross_yield_percent: Optional[float] = None
    cap_rate_percent: Optional[float] = None
    net_yield_percent: Optional[float] = None
    cash_invested_sar: Optional[float] = None
    cash_on_cash_return_percent: Optional[float] = None


@router.get("/reports/{report_id}", response_model=ResponseEnvelope[dict])
async def get_due_diligence_report(
    report_id: str,
    conn: asyncpg.Connection = Depends(get_db)
):
    query = """
        SELECT r.*, 
               u.unit_number, 
               COALESCE(p.name_ar, p.name_en) as project_name,
               b.name as building_name,
               c.first_name || ' ' || c.last_name as customer_name,
               usr.full_name as inspector_name
        FROM investment_due_diligence_reports r
        JOIN units u ON r.unit_id = u.unit_id
        LEFT JOIN buildings b ON u.building_id = b.building_id
        LEFT JOIN projects p ON b.project_id = p.project_id
        LEFT JOIN opportunities opp ON r.opportunity_id = opp.opportunity_id
        LEFT JOIN customers c ON opp.customer_id = c.customer_id
        LEFT JOIN users usr ON r.inspector_user_id = usr.user_id
        WHERE r.report_id = $1
    """
    row = await conn.fetchrow(query, report_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"تقرير الفحص النافي للجهالة '{report_id}' غير موجود.")
    return ResponseEnvelope(data=dict(row))


@router.get("/opportunities/{opportunity_id}/due-diligence", response_model=ResponseEnvelope[List[dict]])
async def get_opportunity_due_diligence_reports(
    opportunity_id: str,
    conn: asyncpg.Connection = Depends(get_db)
):
    query = """
        SELECT r.*, 
               u.unit_number,
               usr.full_name as inspector_name
        FROM investment_due_diligence_reports r
        JOIN units u ON r.unit_id = u.unit_id
        LEFT JOIN users usr ON r.inspector_user_id = usr.user_id
        WHERE r.opportunity_id = $1
        ORDER BY r.inspection_date DESC
    """
    rows = await conn.fetch(query, opportunity_id)
    return ResponseEnvelope(data=[dict(r) for r in rows], meta=BaseMeta(total=len(rows)))


@router.get("/units/{unit_id}/due-diligence", response_model=ResponseEnvelope[List[dict]])
async def get_unit_due_diligence_reports(
    unit_id: str,
    conn: asyncpg.Connection = Depends(get_db)
):
    query = """
        SELECT r.*, 
               u.unit_number,
               usr.full_name as inspector_name
        FROM investment_due_diligence_reports r
        JOIN units u ON r.unit_id = u.unit_id
        LEFT JOIN users usr ON r.inspector_user_id = usr.user_id
        WHERE r.unit_id = $1
        ORDER BY r.inspection_date DESC
    """
    rows = await conn.fetch(query, unit_id)
    return ResponseEnvelope(data=[dict(r) for r in rows], meta=BaseMeta(total=len(rows)))


@router.post("/due-diligence", response_model=ResponseEnvelope[dict])
async def create_due_diligence_report(
    payload: DueDiligenceReportCreateIn,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    user_id = x_user_id or "user-51"
    report_id = await get_next_id(conn, "investment_due_diligence_reports", "ddr")

    # 1. Determine purchase price (prioritizing unit asking price over opportunity expected value)
    p_price = float(payload.purchase_price_sar or 0.0)
    if p_price <= 0.0 and payload.unit_id:
        u_p = await conn.fetchval("SELECT asking_price FROM units WHERE unit_id = $1", payload.unit_id)
        if u_p and float(u_p) > 0:
            p_price = float(u_p)
    if p_price <= 0.0 and payload.opportunity_id:
        opp_v = await conn.fetchval("SELECT expected_value FROM opportunities WHERE opportunity_id = $1", payload.opportunity_id)
        p_price = float(opp_v or 0.0)

    # 2. Determine Gross Annual Rent
    gross_rent = float(payload.gross_annual_rent_sar or 0.0)
    if gross_rent <= 0.0 and payload.unit_id:
        u_rent = await conn.fetchval("SELECT rent_price FROM units WHERE unit_id = $1", payload.unit_id)
        if u_rent and float(u_rent) > 0:
            gross_rent = float(u_rent) if float(u_rent) > 50000 else float(u_rent) * 12.0
    if gross_rent <= 0.0 and p_price > 0:
        gross_rent = p_price * 0.08  # Market baseline 8% gross yield

    actual_occ = float(payload.actual_occupancy_rate if payload.actual_occupancy_rate is not None else 95.0)

    # 3. Vacancy allowance derived from actual field occupancy
    if payload.vacancy_allowance_sar is not None:
        vac_allowance = float(payload.vacancy_allowance_sar)
    else:
        vac_percent = max(0.0, 100.0 - actual_occ)
        vac_allowance = gross_rent * (vac_percent / 100.0)

    # 4. OPEX (Operating Expenses)
    if payload.operating_expenses_opex_sar is not None:
        opex = float(payload.operating_expenses_opex_sar)
    else:
        opex = gross_rent * 0.10

    est_capex = float(payload.estimated_capex_sar or 0.0)
    cash_inv = float(payload.cash_invested_sar or (p_price if p_price > 0 else 1.0))

    # 5. Financial metrics computation via CalculationService
    r_metrics = CalculationService.calculate_rental_metrics(
        monthly_rent=gross_rent / 12.0 if gross_rent > 0 else 0.0,
        purchase_price=p_price,
        annual_vacancy_allowance=vac_allowance,
        annual_operating_expenses=opex,
        acquisition_costs=est_capex
    )
    i_returns = CalculationService.calculate_investment_returns(
        purchase_price=p_price,
        cash_invested=cash_inv,
        annual_pre_tax_cash_flow=r_metrics["net_operating_income"]
    )

    eff_income = float(payload.effective_gross_income_sar or r_metrics["effective_annual_rent"])
    noi = float(payload.net_operating_income_noi_sar or r_metrics["net_operating_income"])
    tot_basis = float(payload.total_investment_basis_sar or r_metrics["total_investment_basis"])
    gross_yield = float(payload.gross_yield_percent or r_metrics["gross_yield_percent"])
    cap_rate = float(payload.cap_rate_percent or (round(noi / p_price * 100.0, 2) if p_price > 0 else 0.0))
    net_yield = float(payload.net_yield_percent or r_metrics["net_operating_yield_percent"])
    coc_return = float(payload.cash_on_cash_return_percent or i_returns["cash_on_cash_return_percent"])

    query = """
        INSERT INTO investment_due_diligence_reports (
            report_id, opportunity_id, unit_id, viewing_id, inspector_user_id, inspection_date,
            structural_condition, building_age_years, saudi_building_code_compliant,
            hvac_status, elevators_status, plumbing_network_status, electrical_network_status,
            roofing_and_insulation_status, fire_safety_compliance, estimated_capex_sar, technical_notes,
            location_traffic_flow, access_and_egress_quality, parking_availability,
            actual_occupancy_rate, total_units_inspected, occupied_units_count, vacant_units_count,
            rent_roll_verified, property_manager_interview_notes, commercial_viability_score, commercial_notes,
            recommendation, suggested_price_adjustment_sar, final_verdict_summary,
            purchase_price_sar, gross_annual_rent_sar, vacancy_allowance_sar, effective_gross_income_sar,
            operating_expenses_opex_sar, net_operating_income_noi_sar, total_investment_basis_sar,
            gross_yield_percent, cap_rate_percent, net_yield_percent, cash_invested_sar, cash_on_cash_return_percent,
            created_at, updated_at
        ) VALUES (
            $1, $2, $3, $4, $5, NOW(),
            $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16,
            $17, $18, $19, $20, $21, $22, $23, $24, $25, $26, $27,
            $28, $29, $30,
            $31, $32, $33, $34, $35, $36, $37, $38, $39, $40, $41, $42,
            NOW(), NOW()
        )
        RETURNING *
    """
    row = await conn.fetchrow(
        query,
        report_id, payload.opportunity_id, payload.unit_id, payload.viewing_id, user_id,
        payload.structural_condition, payload.building_age_years, payload.saudi_building_code_compliant,
        payload.hvac_status, payload.elevators_status, payload.plumbing_network_status, payload.electrical_network_status,
        payload.roofing_and_insulation_status, payload.fire_safety_compliance, est_capex, payload.technical_notes,
        payload.location_traffic_flow, payload.access_and_egress_quality, payload.parking_availability,
        actual_occ, payload.total_units_inspected, payload.occupied_units_count, payload.vacant_units_count,
        payload.rent_roll_verified, payload.property_manager_interview_notes, payload.commercial_viability_score, payload.commercial_notes,
        payload.recommendation, payload.suggested_price_adjustment_sar, payload.final_verdict_summary,
        p_price, gross_rent, vac_allowance, eff_income,
        opex, noi, tot_basis,
        gross_yield, cap_rate, net_yield, cash_inv, coc_return
    )

    return ResponseEnvelope(data=dict(row))


@router.get("/reports/{report_id}/html", response_class=HTMLResponse)
async def get_due_diligence_report_html(
    report_id: str,
    conn: asyncpg.Connection = Depends(get_db)
):
    query = """
        SELECT r.*, 
               u.unit_number, 
               u.asking_price,
               COALESCE(p.name_ar, p.name_en) as project_name,
               b.name as building_name,
               c.first_name || ' ' || c.last_name as customer_name,
               usr.full_name as inspector_name
        FROM investment_due_diligence_reports r
        JOIN units u ON r.unit_id = u.unit_id
        LEFT JOIN buildings b ON u.building_id = b.building_id
        LEFT JOIN projects p ON b.project_id = p.project_id
        LEFT JOIN opportunities opp ON r.opportunity_id = opp.opportunity_id
        LEFT JOIN customers c ON opp.customer_id = c.customer_id
        LEFT JOIN users usr ON r.inspector_user_id = usr.user_id
        WHERE r.report_id = $1
    """
    row = await conn.fetchrow(query, report_id)
    if not row:
        raise HTTPException(status_code=404, detail="تقرير الفحص غير موجود")

    r = dict(row)
    sbc_badge = '<span style="color:#16a34a; font-weight:bold;">✓ مطابق للكود السعودي</span>' if r['saudi_building_code_compliant'] else '<span style="color:#dc2626; font-weight:bold;">✗ غير مطابق للكود</span>'
    rent_badge = '<span style="color:#16a34a; font-weight:bold;">✓ تم التحقق والمطابقة مع منصة إيجار</span>' if r['rent_roll_verified'] else '<span style="color:#dc2626; font-weight:bold;">✗ غير مطابق</span>'

    rec_color = "#16a34a" if "RECOMMEND" in r['recommendation'] else ("#ea580c" if "RENEGOTIATE" in r['recommendation'] else "#dc2626")

    html_content = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>تقرير الفحص الفني والاستثماري النافي للجهالة - #{r['report_id']}</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8fafc; color: #1e293b; padding: 25px; line-height: 1.6; }}
            .card {{ background: white; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); padding: 30px; max-width: 900px; margin: 0 auto; }}
            .header {{ border-bottom: 2px solid #e2e8f0; padding-bottom: 20px; margin-bottom: 25px; display: flex; justify-content: space-between; align-items: center; }}
            .badge {{ display: inline-block; padding: 4px 12px; border-radius: 9999px; font-size: 0.85em; font-weight: 600; }}
            .section {{ margin-bottom: 30px; }}
            .section-title {{ font-size: 1.2em; color: #0f172a; border-right: 4px solid #2563eb; padding-right: 12px; margin-bottom: 15px; font-weight: bold; }}
            .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; }}
            .grid-item {{ background: #f1f5f9; padding: 12px 16px; border-radius: 8px; }}
            .grid-item label {{ font-size: 0.85em; color: #64748b; display: block; }}
            .grid-item span {{ font-size: 1.05em; font-weight: 600; color: #0f172a; }}
            .verdict-box {{ background: #eff6ff; border: 2px solid {rec_color}; border-radius: 8px; padding: 20px; margin-top: 25px; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="header">
                <div>
                    <h1 style="margin:0; color:#1e3a8a; font-size:1.6em;">مكتب معاذ خضر النمري للخدمات العقارية</h1>
                    <h2 style="margin:5px 0 0; color:#475569; font-size:1.1em;">تقرير الفحص الفني والاستثماري النافي للجهالة (Due Diligence Report)</h2>
                </div>
                <div style="text-align:left;">
                    <div style="font-weight:bold; color:#2563eb;">#{r['report_id']}</div>
                    <div style="font-size:0.85em; color:#64748b;">تاريخ الفحص: {r['inspection_date'].strftime('%Y-%m-%d')}</div>
                </div>
            </div>

            <!-- معلومات العقار والعميل -->
            <div class="section">
                <div class="section-title">بيانات الأصل الاستثماري والعميل</div>
                <div class="grid">
                    <div class="grid-item"><label>المستثمر المستهدف</label><span>{r['customer_name'] or 'غير محدد'}</span></div>
                    <div class="grid-item"><label>المشروع / المبنى</label><span>{r['project_name']} - {r['building_name']}</span></div>
                    <div class="grid-item"><label>الوحدة العقارية</label><span>#{r['unit_number']}</span></div>
                    <div class="grid-item"><label>المهندس / المستشار الفاحص</label><span>{r['inspector_name'] or 'فريق الفحص الفني'}</span></div>
                </div>
            </div>

            <!-- الفحص الفني والإنشائي النافي للجهالة -->
            <div class="section">
                <div class="section-title">1. الفحص الفني والإنشائي النافي للجهالة (Technical Due Diligence)</div>
                <div class="grid">
                    <div class="grid-item"><label>سلامة الهيكل الخرساني والإنشائي</label><span>{r['structural_condition']}</span></div>
                    <div class="grid-item"><label>عمر المبنى التقديري</label><span>{r['building_age_years']} سنوات</span></div>
                    <div class="grid-item"><label>مطابقة الكود السعودي للمباني</label><span>{sbc_badge}</span></div>
                    <div class="grid-item"><label>كفاءة أنظمة التكييف والتهوية</label><span>{r['hvac_status']}</span></div>
                    <div class="grid-item"><label>حالة المصاعد والصيانة الدورية</label><span>{r['elevators_status']}</span></div>
                    <div class="grid-item"><label>شبكات السباكة وتصريف المياه</label><span>{r['plumbing_network_status']}</span></div>
                    <div class="grid-item"><label>الشبكة واللوحات الكهربائية</label><span>{r['electrical_network_status']}</span></div>
                    <div class="grid-item"><label>عزل الأسطح وسلامة العزل المائي والحراري</label><span>{r['roofing_and_insulation_status']}</span></div>
                    <div class="grid-item" style="grid-column: span 2; background:#fee2e2;"><label style="color:#991b1b;">المصاريف الرأسمالية المستقبلية المقدرة (Estimated CapEx)</label><span style="color:#b91c1c; font-size:1.3em;">{r['estimated_capex_sar']:,.2f} ريال سعودي</span></div>
                </div>
                <div style="margin-top:10px; font-size:0.9em; background:#f8fafc; padding:10px; border-radius:6px; border-right:3px solid #cbd5e1;">
                    <strong>الملاحظات الإنشائية والفنية:</strong> {r['technical_notes'] or 'لا توجد ملاحظات سلبية مسجلة.'}
                </div>
            </div>

            <!-- المعاينة التجارية للموقع والإشغال -->
            <div class="section">
                <div class="section-title">2. المعاينة التجارية للموقع والإشغال (Commercial & Occupancy Inspection)</div>
                <div class="grid">
                    <div class="grid-item"><label>حركة السير وسهولة الوصول والمداخل</label><span>{r['location_traffic_flow']} / {r['access_and_egress_quality']}</span></div>
                    <div class="grid-item"><label>توفر المواقف لرواد وسكان العقار</label><span>{r['parking_availability']}</span></div>
                    <div class="grid-item"><label>نسبة الإشغال الميداني الفعلي</label><span style="color:#16a34a; font-size:1.2em;">{r['actual_occupancy_rate']}%</span></div>
                    <div class="grid-item"><label>مطابقة عقود منصة إيجار (Rent Roll)</label><span>{rent_badge}</span></div>
                    <div class="grid-item"><label>الوحدات المشغولة / الشاغرة</label><span>{r['occupied_units_count']} مشغولة من إجمالي {r['total_units_inspected']}</span></div>
                    <div class="grid-item"><label>مؤشر الجاذبية الاستثمارية (Score)</label><span>{r['commercial_viability_score']} / 100</span></div>
                </div>
                <div style="margin-top:10px; font-size:0.9em; background:#f8fafc; padding:10px; border-radius:6px; border-right:3px solid #cbd5e1;">
                    <strong>تقرير مقابلة إدارة العقار والحارس:</strong> {r['property_manager_interview_notes'] or 'تمت المطابقة مع إدارة المبنى.'}
                </div>
            </div>

            <!-- التحليل المالي وخط الأساس لمؤشرات الأداء والعائد -->
            <div class="section">
                <div class="section-title">3. التحليل المالي وخط الأساس لمؤشرات الأداء والعائد (Financial Due Diligence & Investment Baseline)</div>
                <div class="grid" style="grid-template-columns: repeat(3, 1fr);">
                    <div class="grid-item"><label>قيمة الاستحواذ المقدرة</label><span>{float(r['purchase_price_sar'] or 0.0):,.2f} ريال</span></div>
                    <div class="grid-item"><label>إجمالي الإيجار السنوي (Gross Scheduled Rent)</label><span>{float(r['gross_annual_rent_sar'] or 0.0):,.2f} ريال</span></div>
                    <div class="grid-item"><label>مخصص الشغور الميداني (Vacancy Allowance)</label><span style="color:#b91c1c;">{float(r['vacancy_allowance_sar'] or 0.0):,.2f} ريال</span></div>
                    <div class="grid-item"><label>إجمالي الدخل الفعلي (EGI)</label><span>{float(r['effective_gross_income_sar'] or 0.0):,.2f} ريال</span></div>
                    <div class="grid-item"><label>مصاريف التشغيل السنوية (OPEX)</label><span style="color:#b91c1c;">{float(r['operating_expenses_opex_sar'] or 0.0):,.2f} ريال</span></div>
                    <div class="grid-item" style="background:#dbeafe;"><label style="color:#1e40af; font-weight:bold;">صافي الدخل التشغيلي (NOI)</label><span style="color:#1d4ed8; font-size:1.25em;">{float(r['net_operating_income_noi_sar'] or 0.0):,.2f} ريال</span></div>
                    <div class="grid-item"><label>التكلفة الاستثمارية الشاملة (Basis + CapEx)</label><span>{float(r['total_investment_basis_sar'] or 0.0):,.2f} ريال</span></div>
                    <div class="grid-item" style="background:#f0fdf4;"><label style="color:#15803d; font-weight:bold;">معدل الرسملة (Cap Rate)</label><span style="color:#16a34a; font-size:1.25em;">{float(r['cap_rate_percent'] or 0.0)}%</span></div>
                    <div class="grid-item" style="background:#f0fdf4;"><label style="color:#15803d; font-weight:bold;">صافي العائد بعد CapEx (Net Yield)</label><span style="color:#16a34a; font-size:1.25em;">{float(r['net_yield_percent'] or 0.0)}%</span></div>
                    <div class="grid-item"><label>رأس المال النقدي المستثمر (Cash Invested)</label><span>{float(r['cash_invested_sar'] or 0.0):,.2f} ريال</span></div>
                    <div class="grid-item" style="background:#fef3c7; grid-column: span 2;"><label style="color:#b45309; font-weight:bold;">العائد على النقد المستثمر (Cash-on-Cash Return)</label><span style="color:#d97706; font-size:1.25em;">{float(r['cash_on_cash_return_percent'] or 0.0)}%</span></div>
                </div>
            </div>

            <!-- التوصية الاستثمارية والمالية النهائية -->
            <div class="verdict-box">
                <div style="font-size:0.9em; color:#64748b; font-weight:600;">القرار والتوصية الاستثمارية الميدانية النهائية</div>
                <div style="font-size:1.5em; font-weight:bold; color:{rec_color}; margin:8px 0;">{r['recommendation']}</div>
                {f'<div style="font-size:1.1em; color:#b91c1c; font-weight:600;">التعديل السعري المقترح لتغطية الـ CapEx: {r["suggested_price_adjustment_sar"]:,.2f} ريال</div>' if r['suggested_price_adjustment_sar'] > 0 else ''}
                <div style="margin-top:10px; font-size:0.95em; color:#334155;">{r['final_verdict_summary'] or 'العقار مؤهل للاستحواذ الاستثماري.'}</div>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

