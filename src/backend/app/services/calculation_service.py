import math
from typing import Optional, Dict, Any, Tuple, List


class CalculationService:
    """
    Centralized Financial, Mathematical and Business Rules Calculation Engine.
    Implements all formulas from 'Docs/Customer Business roules and workflow.md':
      - Rule 1..4: Budget validity, budget matching, property eligibility, and weighted score.
      - Rental yield, NOI, gross/net operating yield.
      - Investment returns: Cash-on-Cash, Capital Appreciation, Total ROI.
      - Financial and commission controls: Outstanding balance, transaction-based commissions.
      - Managerial performance KPIs: SLA compliance %, conversion %, completion %, income variance %.
    """

    # Default weights from Section 3.A, Rule 4
    DEFAULT_MATCH_WEIGHTS: Dict[str, float] = {
        "budget": 0.30,
        "location": 0.25,
        "size_bedrooms": 0.20,
        "amenities": 0.10,
        "timing": 0.15,
    }

    # =========================================================================
    # 3.A. Customer Qualification & Property Matching Equations
    # =========================================================================

    @staticmethod
    def validate_budget_range(
        budget_min: Optional[float],
        budget_max: Optional[float]
    ) -> Tuple[bool, Optional[str]]:
        """
        Rule 1 — Budget validity:
        B_min <= B_max
        If both values are supplied, minimum cannot exceed maximum. Amounts must be non-negative.
        """
        if budget_min is not None and budget_min < 0:
            return False, "Minimum budget cannot be negative."
        if budget_max is not None and budget_max < 0:
            return False, "Maximum budget cannot be negative."
        if budget_min is not None and budget_max is not None:
            if budget_min > budget_max:
                return False, f"Minimum budget ({budget_min:,.2f}) cannot exceed maximum budget ({budget_max:,.2f})."
        return True, None

    @staticmethod
    def check_budget_match(
        property_amount: float,
        budget_max: Optional[float],
        budget_min: Optional[float] = None
    ) -> bool:
        """
        Rule 2 — Property budget match:
        Rental: R_property <= B_rent,max
        Purchase: P_property <= B_purchase,max
        """
        if property_amount < 0:
            return False
        if budget_max is not None and property_amount > budget_max:
            return False
        return True

    @classmethod
    def check_property_eligibility(
        cls,
        unit_status: str,
        property_amount: float,
        budget_max: Optional[float],
        unit_city_id: Optional[str] = None,
        preferred_city_id: Optional[str] = None,
        unit_bedrooms: Optional[int] = None,
        required_bedrooms_min: Optional[int] = None,
        unit_property_type_id: Optional[str] = None,
        preferred_property_type_id: Optional[str] = None,
        unit_area_sqm: Optional[float] = None,
        required_area_min: Optional[float] = None,
        allowed_statuses: Optional[List[str]] = None
    ) -> Tuple[bool, Dict[str, bool]]:
        """
        Rule 3 — Property eligibility:
        Eligible = Available AND BudgetMatch AND LocationMatch AND RequirementsMatch
        A property qualifies only if all mandatory conditions are satisfied.
        """
        if allowed_statuses is None:
            allowed_statuses = ["AVAILABLE", "ACTIVE", "READY_FOR_LEASING", "LISTED"]

        # 1. Availability check
        available = (unit_status or "").upper() in allowed_statuses

        # 2. Budget match check
        budget_match = cls.check_budget_match(property_amount, budget_max)

        # 3. Location match check
        location_match = True
        if preferred_city_id and unit_city_id:
            location_match = (unit_city_id == preferred_city_id)

        # 4. Requirements match (Bedrooms, Property Type, Area)
        bedrooms_match = True
        if required_bedrooms_min is not None and unit_bedrooms is not None:
            bedrooms_match = (unit_bedrooms >= required_bedrooms_min)

        property_type_match = True
        if preferred_property_type_id and unit_property_type_id:
            property_type_match = (unit_property_type_id == preferred_property_type_id)

        area_match = True
        if required_area_min is not None and unit_area_sqm is not None:
            area_match = (unit_area_sqm >= required_area_min)

        requirements_match = bedrooms_match and property_type_match and area_match

        is_eligible = available and budget_match and location_match and requirements_match

        criteria = {
            "available": available,
            "budget_match": budget_match,
            "location_match": location_match,
            "bedrooms_match": bedrooms_match,
            "property_type_match": property_type_match,
            "area_match": area_match,
            "requirements_match": requirements_match,
        }
        return is_eligible, criteria

    @classmethod
    def calculate_property_match_score(
        cls,
        property_amount: float,
        budget_min: Optional[float],
        budget_max: Optional[float],
        unit_city_id: Optional[str] = None,
        preferred_city_id: Optional[str] = None,
        unit_bedrooms: Optional[int] = None,
        required_bedrooms_min: Optional[int] = None,
        unit_area_sqm: Optional[float] = None,
        required_area_min: Optional[float] = None,
        is_available: bool = True,
        amenities_match_ratio: float = 1.0,
        timing_score: float = 100.0,
        custom_weights: Optional[Dict[str, float]] = None
    ) -> Tuple[bool, float, Dict[str, float]]:
        """
        Rule 4 — Property matching score:
        S = sum(w_i * s_i) where sum(w_i) = 1.0, s_i in [0, 100].
        Weights: Budget (30%), Location (25%), Size/Bedrooms (20%), Amenities (10%), Timing (15%).
        Note: The score helps rank properties; it does NOT override mandatory eligibility!
        """
        weights = cls.DEFAULT_MATCH_WEIGHTS.copy()
        if custom_weights:
            weights.update(custom_weights)
            # Normalize weights so sum equals 1.0
            total_w = sum(weights.values())
            if total_w > 0:
                weights = {k: v / total_w for k, v in weights.items()}

        # Mandatory check
        is_budget_ok = cls.check_budget_match(property_amount, budget_max)
        is_eligible = is_available and is_budget_ok

        # 1. Budget Factor (s_budget):
        # Best score (100) when property amount is comfortable within budget range
        if budget_max is not None and budget_max > 0:
            if property_amount > budget_max:
                # Exceeds maximum budget: score drops significantly
                overage_ratio = (property_amount - budget_max) / budget_max
                s_budget = max(0.0, 50.0 - overage_ratio * 100.0)
            elif budget_min is not None and property_amount < budget_min:
                # Below minimum (acceptable but slightly penalized for quality expectation)
                s_budget = max(60.0, 100.0 - ((budget_min - property_amount) / budget_min) * 40.0)
            else:
                # Perfectly inside budget range [budget_min, budget_max]
                target = (budget_min + budget_max) / 2.0 if budget_min is not None else budget_max * 0.85
                diff_ratio = abs(property_amount - target) / budget_max
                s_budget = max(70.0, 100.0 - diff_ratio * 30.0)
        else:
            s_budget = 100.0

        # 2. Location Factor (s_location):
        if preferred_city_id and unit_city_id:
            s_location = 100.0 if preferred_city_id == unit_city_id else 0.0
        else:
            s_location = 85.0  # Open / Any city

        # 3. Size and Bedrooms Factor (s_size):
        s_size_items = []
        if required_bedrooms_min is not None and unit_bedrooms is not None:
            if unit_bedrooms == required_bedrooms_min:
                s_size_items.append(100.0)
            elif unit_bedrooms == required_bedrooms_min + 1:
                s_size_items.append(90.0)
            elif unit_bedrooms > required_bedrooms_min:
                s_size_items.append(80.0)
            else:
                s_size_items.append(0.0)

        if required_area_min is not None and unit_area_sqm is not None:
            if unit_area_sqm >= required_area_min:
                area_ratio = min(1.3, unit_area_sqm / required_area_min)
                s_size_items.append(min(100.0, 70.0 + (area_ratio - 1.0) * 100.0))
            else:
                s_size_items.append(max(0.0, (unit_area_sqm / required_area_min) * 60.0))

        s_size = (sum(s_size_items) / len(s_size_items)) if s_size_items else 90.0

        # 4. Amenities Factor (s_amenities):
        s_amenities = max(0.0, min(100.0, float(amenities_match_ratio) * 100.0))

        # 5. Timing Factor (s_timing):
        s_timing = max(0.0, min(100.0, float(timing_score)))

        # Weighted composite score: S = sum(w_i * s_i)
        total_score = (
            weights["budget"] * s_budget
            + weights["location"] * s_location
            + weights["size_bedrooms"] * s_size
            + weights["amenities"] * s_amenities
            + weights["timing"] * s_timing
        )
        total_score = round(max(0.0, min(100.0, total_score)), 2)

        breakdown = {
            "budget": round(s_budget, 2),
            "location": round(s_location, 2),
            "size_bedrooms": round(s_size, 2),
            "amenities": round(s_amenities, 2),
            "timing": round(s_timing, 2),
            "total_score": total_score,
            "weights": weights,
        }
        return is_eligible, total_score, breakdown

    # =========================================================================
    # 3.B. Rental Calculations
    # =========================================================================

    @staticmethod
    def calculate_rental_metrics(
        monthly_rent: float,
        purchase_price: float,
        annual_vacancy_allowance: float = 0.0,
        annual_operating_expenses: float = 0.0,
        acquisition_costs: float = 0.0
    ) -> Dict[str, Any]:
        """
        Section 3.B Rental calculations:
        1. Annual gross rent: G = R_m * 12
        2. Effective annual rental income: E = G - V (V = vacancy allowance)
        3. Net operating income (NOI): NOI = E - O (O = operating expenses)
        4. Gross rental yield: Y_g = (G / P) * 100%
        5. Net operating yield: Y_n = (NOI / (P + C)) * 100%
        """
        if monthly_rent < 0 or purchase_price < 0:
            raise ValueError("Rent and purchase price must be non-negative.")

        # 1. Annual gross rent: G = R_m * 12
        gross_annual_rent = monthly_rent * 12.0

        # 2. Effective annual rental income: E = G - V
        effective_annual_rent = max(0.0, gross_annual_rent - max(0.0, annual_vacancy_allowance))

        # 3. Net Operating Income: NOI = E - O
        noi = effective_annual_rent - max(0.0, annual_operating_expenses)

        # 4. Gross rental yield: Y_g = (G / P) * 100
        gross_yield = (gross_annual_rent / purchase_price * 100.0) if purchase_price > 0 else 0.0

        # 5. Net operating yield: Y_n = (NOI / (P + C)) * 100
        total_investment_basis = purchase_price + max(0.0, acquisition_costs)
        net_operating_yield = (noi / total_investment_basis * 100.0) if total_investment_basis > 0 else 0.0

        return {
            "monthly_rent": round(monthly_rent, 2),
            "purchase_price": round(purchase_price, 2),
            "gross_annual_rent": round(gross_annual_rent, 2),
            "vacancy_allowance": round(annual_vacancy_allowance, 2),
            "effective_annual_rent": round(effective_annual_rent, 2),
            "operating_expenses": round(annual_operating_expenses, 2),
            "net_operating_income": round(noi, 2),
            "acquisition_costs": round(acquisition_costs, 2),
            "total_investment_basis": round(total_investment_basis, 2),
            "gross_yield_percent": round(gross_yield, 2),
            "net_operating_yield_percent": round(net_operating_yield, 2),
        }

    # =========================================================================
    # 3.C. Investment Return Calculations
    # =========================================================================

    @staticmethod
    def calculate_investment_returns(
        purchase_price: float,
        cash_invested: float,
        annual_pre_tax_cash_flow: float,
        current_estimated_value: Optional[float] = None,
        net_sale_proceeds: Optional[float] = None,
        cumulative_rental_cash_flow: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Section 3.C Investment return calculations:
        1. Cash-on-cash return:
           CoC = (Annual pre-tax cash flow / Cash invested) * 100%
        2. Capital appreciation:
           A = ((P_current - P_purchase) / P_purchase) * 100%
        3. Total investment return (1-period ROI):
           ROI = ((Net sale proceeds + Net rental cash flow - Initial cash invested) / Initial cash invested) * 100%
        """
        if cash_invested <= 0:
            raise ValueError("Cash invested must be greater than zero for rate-of-return calculations.")

        # 1. Cash-on-Cash Return: CoC = (Annual pre-tax cash flow / Cash invested) * 100%
        cash_on_cash_return = (annual_pre_tax_cash_flow / cash_invested) * 100.0

        # 2. Capital Appreciation: A = ((P_current - P_purchase) / P_purchase) * 100%
        capital_appreciation_percent = None
        unrealized_gain = None
        if current_estimated_value is not None and purchase_price > 0:
            unrealized_gain = current_estimated_value - purchase_price
            capital_appreciation_percent = (unrealized_gain / purchase_price) * 100.0

        # 3. Total Investment Return (ROI):
        total_roi_percent = None
        if net_sale_proceeds is not None and cumulative_rental_cash_flow is not None:
            net_total_gain = net_sale_proceeds + cumulative_rental_cash_flow - cash_invested
            total_roi_percent = (net_total_gain / cash_invested) * 100.0

        return {
            "cash_invested": round(cash_invested, 2),
            "annual_pre_tax_cash_flow": round(annual_pre_tax_cash_flow, 2),
            "cash_on_cash_return_percent": round(cash_on_cash_return, 2),
            "current_estimated_value": round(current_estimated_value, 2) if current_estimated_value is not None else None,
            "unrealized_gain": round(unrealized_gain, 2) if unrealized_gain is not None else None,
            "capital_appreciation_percent": round(capital_appreciation_percent, 2) if capital_appreciation_percent is not None else None,
            "net_sale_proceeds": round(net_sale_proceeds, 2) if net_sale_proceeds is not None else None,
            "cumulative_rental_cash_flow": round(cumulative_rental_cash_flow, 2) if cumulative_rental_cash_flow is not None else None,
            "total_roi_percent": round(total_roi_percent, 2) if total_roi_percent is not None else None,
        }

    # =========================================================================
    # 3.D. Technical Due Diligence & CapEx Engineering Estimator
    # =========================================================================

    @staticmethod
    def estimate_technical_capex_and_adjustment(
        purchase_price: float,
        building_age_years: int = 5,
        structural_condition: str = "GOOD",
        saudi_building_code_compliant: bool = True,
        hvac_status: str = "OPERATIONAL",
        elevators_status: str = "OPERATIONAL",
        roofing_and_insulation_status: str = "GOOD",
        max_budget: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Estimates future Capital Expenditures (CapEx) and suggested purchase price
        discount based on structural, mechanical, envelope, and regulatory findings.

        Formulas:
        1. Structural remediation:
           - EXCELLENT: 0.0%
           - GOOD: 0.5%
           - FAIR: 2.5%
           - CRITICAL: 8.0%
        2. Saudi Building Code (SBC) retrofitting:
           - Compliant: 0
           - Non-compliant: max(50,000, 1.5% * purchase_price)
        3. HVAC overhaul/replacement:
           - OPERATIONAL: 0
           - MAINTENANCE_REQUIRED: max(20,000, 1.0% * purchase_price)
           - FAULTY: max(80,000, 3.5% * purchase_price)
        4. Elevator refurbishment:
           - OPERATIONAL: 0
           - MAINTENANCE_REQUIRED: max(25,000, 0.75% * purchase_price)
           - INOPERATIVE: max(100,000, 2.0% * purchase_price)
        5. Roofing and insulation waterproofing:
           - GOOD: 0
           - NEEDS_REPAIR: max(15,000, 0.5% * purchase_price)
           - WATER_LEAKAGE: max(45,000, 1.2% * purchase_price)
        6. Age-based capital replacement reserve:
           - Age > 15: purchase_price * ((age - 15) * 0.003)
           - Age > 8: purchase_price * ((age - 8) * 0.0015)
           - Otherwise: 0
        """
        base = max(0.0, float(purchase_price))
        breakdown = {}

        # 1. Structural
        s_norm = (structural_condition or "GOOD").upper()
        s_rates = {"EXCELLENT": 0.0, "GOOD": 0.005, "FAIR": 0.025, "CRITICAL": 0.08}
        breakdown["structural_sar"] = round(base * s_rates.get(s_norm, 0.005), 2)

        # 2. SBC Compliance
        sbc = bool(saudi_building_code_compliant)
        breakdown["sbc_retrofitting_sar"] = 0.0 if sbc else round(max(50000.0, base * 0.015), 2)

        # 3. HVAC
        h_norm = (hvac_status or "OPERATIONAL").upper()
        if h_norm == "FAULTY":
            breakdown["hvac_sar"] = round(max(80000.0, base * 0.035), 2)
        elif h_norm == "MAINTENANCE_REQUIRED":
            breakdown["hvac_sar"] = round(max(20000.0, base * 0.010), 2)
        else:
            breakdown["hvac_sar"] = 0.0

        # 4. Elevators
        e_norm = (elevators_status or "OPERATIONAL").upper()
        if e_norm == "INOPERATIVE":
            breakdown["elevators_sar"] = round(max(100000.0, base * 0.020), 2)
        elif e_norm == "MAINTENANCE_REQUIRED":
            breakdown["elevators_sar"] = round(max(25000.0, base * 0.0075), 2)
        else:
            breakdown["elevators_sar"] = 0.0

        # 5. Roofing & Insulation
        r_norm = (roofing_and_insulation_status or "GOOD").upper()
        if r_norm == "WATER_LEAKAGE":
            breakdown["roofing_insulation_sar"] = round(max(45000.0, base * 0.012), 2)
        elif r_norm == "NEEDS_REPAIR":
            breakdown["roofing_insulation_sar"] = round(max(15000.0, base * 0.005), 2)
        else:
            breakdown["roofing_insulation_sar"] = 0.0

        # 6. Building Age Reserve
        age = max(0, int(building_age_years))
        if age > 15:
            breakdown["age_reserve_sar"] = round(base * ((age - 15) * 0.003), 2)
        elif age > 8:
            breakdown["age_reserve_sar"] = round(base * ((age - 8) * 0.0015), 2)
        else:
            breakdown["age_reserve_sar"] = 0.0

        total_capex = round(sum(breakdown.values()), 2)
        suggested_price_adjustment = total_capex
        adjusted_target_purchase_price = max(0.0, round(base - suggested_price_adjustment, 2))
        worst_case_total_cost = round(base + total_capex, 2)

        solvency_analysis = None
        if max_budget is not None and max_budget > 0:
            mb = float(max_budget)
            buffer = round(mb - worst_case_total_cost, 2)
            is_solvent = buffer >= 0
            solvency_analysis = {
                "max_budget_sar": round(mb, 2),
                "worst_case_total_cost_sar": worst_case_total_cost,
                "capital_buffer_sar": buffer,
                "solvency_status": "SOLVENT" if is_solvent else "DEFICIT",
                "negotiation_posture": "SAFE_ABSORPTION" if is_solvent else "MANDATORY_DISCOUNT_CONTINGENCY",
                "assessment_ar": (
                    f"ملاءة مكتملة: المستثمر قادر على استيعاب رفض البائع للتخفيض وإتمام الصفقة مع بقاء احتياطي قدره {buffer:,.2f} ر.س."
                    if is_solvent else
                    f"مخاطرة سيولة: تتجاوز التكلفة سقف ميزانية المستثمر بعجز قدره {abs(buffer):,.2f} ر.س — قبول التعديل السعري شرط إلزامي للاستمرار."
                )
            }

        return {
            "purchase_price": round(base, 2),
            "estimated_capex_sar": total_capex,
            "suggested_price_adjustment_sar": suggested_price_adjustment,
            "adjusted_target_purchase_price_sar": adjusted_target_purchase_price,
            "worst_case_total_cost_sar": worst_case_total_cost,
            "solvency_analysis": solvency_analysis,
            "breakdown": breakdown
        }

    # =========================================================================
    # 3.E. Financial & Commission Controls
    # =========================================================================

    @staticmethod
    def calculate_outstanding_balance(
        amount_due: float,
        amount_paid: float
    ) -> Dict[str, Any]:
        """
        Section 3.E Financial Controls:
        Balance = AmountDue - AmountPaid
        Constraint: amount_paid cannot exceed amount_due, both non-negative.
        """
        if amount_due < 0 or amount_paid < 0:
            raise ValueError("Amounts must be non-negative.")
        if amount_paid > amount_due:
            raise ValueError(f"Amount paid ({amount_paid:,.2f}) cannot exceed amount due ({amount_due:,.2f}).")

        balance = round(amount_due - amount_paid, 2)
        is_fully_paid = (balance == 0.0)

        return {
            "amount_due": round(amount_due, 2),
            "amount_paid": round(amount_paid, 2),
            "outstanding_balance": balance,
            "is_fully_paid": is_fully_paid,
            "payment_ratio_percent": round((amount_paid / amount_due * 100.0), 2) if amount_due > 0 else 100.0
        }

    @staticmethod
    def calculate_commission(
        transaction_type: str,
        base_amount: float,
        rate_percent: float,
        fixed_fee: float = 0.0,
        tax_rate_percent: float = 0.0
    ) -> Dict[str, Any]:
        """
        Section 3.E Commission calculation:
        Commission = CommissionBase * (Rate / 100)
        Sale: typically 2.5% or policy-defined rate of purchase price.
        Rent: typically fixed fee or defined portion of annual rent.
        """
        if base_amount < 0 or rate_percent < 0 or fixed_fee < 0:
            raise ValueError("Base amount, rate percent, and fixed fee must be non-negative.")

        t_type = (transaction_type or "SALE").upper()
        if t_type == "RENT" and fixed_fee > 0:
            base_comm = fixed_fee
            calculation_method = "FIXED_FEE"
        else:
            base_comm = base_amount * (rate_percent / 100.0)
            calculation_method = f"PERCENTAGE_{rate_percent}%"

        tax_amount = base_comm * (tax_rate_percent / 100.0) if tax_rate_percent > 0 else 0.0
        total_commission = base_comm + tax_amount

        return {
            "transaction_type": t_type,
            "commission_base": round(base_amount, 2),
            "rate_percent": round(rate_percent, 2),
            "calculation_method": calculation_method,
            "commission_net": round(base_comm, 2),
            "tax_amount": round(tax_amount, 2),
            "commission_gross": round(total_commission, 2),
        }

    @staticmethod
    def calculate_agent_commission(
        transaction_type: str,
        deal_value: float,
        brokerage_rate_percent: float = 2.5,
        brokerage_flat_amount: Optional[float] = None,
        agent_profile: Optional[Dict[str, Any]] = None,
        vat_rate_percent: float = 15.0,
    ) -> Dict[str, Any]:
        """
        Calculates agent commission ensuring Saudi statutory & government fees 
        (RETT 5%, Ejar fee, 15% VAT) are 100% excluded from the commissionable base.

        Supports:
          1. SALARY: Salaried employee (exempt from deal commission, 0 SAR payout).
          2. COMMISSION: Percentage split of NET brokerage fee (ex: 25% or 30%).
          3. FIXED_CUT: Fixed lump-sum cut per deal (ex: 2,500 SAR per sale).
          4. SALARY_PLUS_COMMISSION: Base salary + lower incentive commission cut.
        """
        t_type = (transaction_type or "SALE").upper()
        deal_val = max(0.0, float(deal_value or 0.0))

        # 1. Gross Office Brokerage (سعي المكتب قبل الضريبة)
        if brokerage_flat_amount is not None and brokerage_flat_amount > 0:
            gross_brokerage = float(brokerage_flat_amount)
        else:
            gross_brokerage = round(deal_val * (brokerage_rate_percent / 100.0), 2)

        # 2. Government Fees to Exclude
        # A) 15% VAT on Brokerage (ضريبة القيمة المضافة)
        vat_amount = round(gross_brokerage * (vat_rate_percent / 100.0), 2)

        # B) Statutory Pass-Through Taxes (for reporting/auditing)
        # RETT 5% on sales or Ejar 125/200 on rentals are direct government collections
        rett_or_ejar_fee = round(deal_val * 0.05, 2) if t_type == "SALE" else 125.0

        total_gov_fees_deducted = vat_amount  # VAT on brokerage is directly isolated from brokerage

        # 3. Net Commissionable Base (صافي سعي المكتب الفعلي)
        net_commission_base = max(0.0, round(gross_brokerage, 2))

        # 4. Resolve Agent Profile
        profile = agent_profile or {}
        comp_type = (profile.get("compensation_type") or "COMMISSION").upper()

        sales_comm_rate = float(profile.get("sales_commission_rate") if profile.get("sales_commission_rate") is not None else 25.0)
        rent_comm_rate = float(profile.get("rent_commission_rate") if profile.get("rent_commission_rate") is not None else 25.0)
        sales_cut = float(profile.get("sales_fixed_cut") or 0.0)
        rent_cut = float(profile.get("rent_fixed_cut") or 0.0)

        # 5. Apply Agent Compensation Formula
        if comp_type == "SALARY":
            # Salaried Employee: No transaction commission
            agent_amount = 0.0
            rate = 0.0
            status = "EXEMPT_SALARY"
            notes = (
                f"الوسيط موظف براتب شهري ثابت ({float(profile.get('base_salary') or 0):,.2f} ر.س) — "
                f"معفى من عمولة الصفقات الفردية. صافي سعي المكتب المحقق: {net_commission_base:,.2f} ر.س."
            )
        elif comp_type == "FIXED_CUT":
            # Flat fee / Cutting amount per closed deal
            target_cut = sales_cut if t_type == "SALE" else rent_cut
            # Cap at net brokerage to prevent office losses
            agent_amount = min(target_cut, net_commission_base)
            rate = round((agent_amount / net_commission_base * 100.0), 2) if net_commission_base > 0 else 0.0
            status = "PENDING"
            notes = (
                f"مبلغ مقطوع ثابت ({target_cut:,.2f} ر.س) عن صفقة {t_type} "
                f"من صافي سعي المكتب ({net_commission_base:,.2f} ر.س خالي من ضريبة الـ 15% والرسوم الحكومية)."
            )
        elif comp_type == "SALARY_PLUS_COMMISSION":
            # Hybrid: Salary + Incentive Commission
            rate = sales_comm_rate if t_type == "SALE" else rent_comm_rate
            agent_amount = round(net_commission_base * (rate / 100.0), 2)
            status = "PENDING"
            notes = (
                f"عمولة تحفيزية إضافية بنسبة {rate:.1f}% من صافي سعي المكتب ({net_commission_base:,.2f} ر.س) "
                f"بالإضافة للراتب الأساسي ({float(profile.get('base_salary') or 0):,.2f} ر.س)."
            )
        else:  # COMMISSION
            # Standard Commission Split on Net Brokerage
            rate = sales_comm_rate if t_type == "SALE" else rent_comm_rate
            agent_amount = round(net_commission_base * (rate / 100.0), 2)
            status = "PENDING"
            notes = (
                f"نسبة عمولة {rate:.1f}% من صافي سعي المكتب ({net_commission_base:,.2f} ر.س) "
                f"بعد استبعاد ضريبة القيمة المضافة والرسوم الحكومية."
            )

        return {
            "transaction_type": t_type,
            "compensation_type": comp_type,
            "gross_deal_value": round(deal_val, 2),
            "gross_brokerage_amount": round(gross_brokerage, 2),
            "gov_fees_deducted": round(total_gov_fees_deducted, 2),
            "statutory_pass_through_tax": round(rett_or_ejar_fee, 2),
            "net_commission_base": round(net_commission_base, 2),
            "rate": round(rate, 2),
            "amount": round(agent_amount, 2),
            "status": status,
            "calculation_notes": notes
        }

    # =========================================================================
    # 7. Equations for Managers and Team Performance
    # =========================================================================

    @staticmethod
    def calculate_sla_compliance_rate(
        leads_contacted_within_sla: int,
        eligible_leads_due: int
    ) -> Dict[str, Any]:
        """
        Section 7 Lead contact SLA compliance:
        SLA% = (Leads contacted within SLA / Eligible leads due for contact) * 100
        """
        if eligible_leads_due <= 0:
            compliance = 100.0 if leads_contacted_within_sla >= 0 else 0.0
        else:
            compliance = (leads_contacted_within_sla / eligible_leads_due) * 100.0

        return {
            "leads_contacted_within_sla": leads_contacted_within_sla,
            "eligible_leads_due": eligible_leads_due,
            "sla_compliance_percent": round(max(0.0, min(100.0, compliance)), 2)
        }

    @staticmethod
    def calculate_cohort_conversion_rate(
        successful_leads: int,
        total_qualified_leads_in_cohort: int
    ) -> Dict[str, Any]:
        """
        Section 7 Lead-to-transaction conversion:
        Conversion% = (Qualified leads achieving defined outcome / Qualified leads in same cohort) * 100
        """
        if total_qualified_leads_in_cohort <= 0:
            rate = 0.0
        else:
            rate = (successful_leads / total_qualified_leads_in_cohort) * 100.0

        return {
            "successful_leads": successful_leads,
            "total_qualified_leads_in_cohort": total_qualified_leads_in_cohort,
            "conversion_rate_percent": round(max(0.0, min(100.0, rate)), 2)
        }

    @staticmethod
    def calculate_task_completion_rate(
        tasks_completed_on_time: int,
        tasks_due: int,
        tasks_overdue: int = 0
    ) -> Dict[str, Any]:
        """
        Section 7 Task completion rate:
        Completion% = (Tasks completed by cutoff / Tasks due by cutoff) * 100
        Overdue tasks reported separately. Tasks completed after deadline do not count as on-time.
        """
        if tasks_due <= 0:
            rate = 100.0 if tasks_overdue == 0 else 0.0
        else:
            rate = (tasks_completed_on_time / tasks_due) * 100.0

        return {
            "tasks_completed_on_time": tasks_completed_on_time,
            "tasks_due": tasks_due,
            "tasks_overdue": tasks_overdue,
            "on_time_completion_rate_percent": round(max(0.0, min(100.0, rate)), 2)
        }

    @staticmethod
    def calculate_viewing_to_offer_conversion(
        offers_generated: int,
        eligible_completed_viewings: int
    ) -> Dict[str, Any]:
        """
        Section 7 Viewing-to-offer conversion:
        Conversion% = (Eligible completed viewings followed by an offer / Eligible completed viewings) * 100
        """
        if eligible_completed_viewings <= 0:
            rate = 0.0
        else:
            rate = (offers_generated / eligible_completed_viewings) * 100.0

        return {
            "offers_generated": offers_generated,
            "eligible_completed_viewings": eligible_completed_viewings,
            "viewing_to_offer_conversion_percent": round(max(0.0, min(100.0, rate)), 2)
        }

    @staticmethod
    def calculate_forecast_rental_variance(
        actual_income: float,
        forecast_income: float
    ) -> Dict[str, Any]:
        """
        Section 7 Forecast versus actual rental income:
        Variance = ActualIncome - ForecastIncome
        Variance% = ((ActualIncome - ForecastIncome) / ForecastIncome) * 100%
        If forecast is zero, variance percentage is reported as unavailable (None).
        """
        variance = actual_income - forecast_income
        variance_percent = ((variance / forecast_income) * 100.0) if forecast_income > 0 else None

        return {
            "actual_income": round(actual_income, 2),
            "forecast_income": round(forecast_income, 2),
            "variance": round(variance, 2),
            "variance_percent": round(variance_percent, 2) if variance_percent is not None else None,
            "is_favorable": variance >= 0.0
        }

    @classmethod
    def compare_investment_properties(
        cls,
        candidates: List[Dict[str, Any]],
        sort_by: str = "net_operating_yield_percent"
    ) -> Dict[str, Any]:
        """
        Compares multiple investment candidate properties under uniform, documented assumptions.
        Ranks properties based on specified metric (e.g. net_operating_yield_percent, gross_yield_percent, or cash_on_cash_return_percent).
        """
        results = []
        for c in candidates:
            p_price = float(c.get("purchase_price") or 0.0)
            m_rent = float(c.get("monthly_rent") or 0.0)
            vac = float(c.get("annual_vacancy_allowance") or 0.0)
            opex = float(c.get("annual_operating_expenses") or 0.0)
            acq = float(c.get("acquisition_costs") or 0.0)
            cash_inv = float(c.get("cash_invested") or (p_price if p_price > 0 else 1.0))
            cf = float(c.get("annual_pre_tax_cash_flow") or max(0.0, (m_rent * 12.0) - vac - opex))

            r_metrics = cls.calculate_rental_metrics(
                monthly_rent=m_rent,
                purchase_price=p_price,
                annual_vacancy_allowance=vac,
                annual_operating_expenses=opex,
                acquisition_costs=acq
            )
            i_returns = cls.calculate_investment_returns(
                purchase_price=p_price,
                cash_invested=cash_inv,
                annual_pre_tax_cash_flow=cf
            )

            item = {
                "property_id": c.get("property_id"),
                "property_title": c.get("property_title"),
                **r_metrics,
                **i_returns
            }
            results.append(item)

        results.sort(key=lambda x: (x.get(sort_by) is not None, x.get(sort_by) or 0.0), reverse=True)

        best_pick = results[0] if results else None
        return {
            "total_candidates": len(results),
            "sorted_by": sort_by,
            "best_candidate_id": best_pick.get("property_id") if best_pick else None,
            "comparison": results
        }


