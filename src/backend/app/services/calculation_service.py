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
