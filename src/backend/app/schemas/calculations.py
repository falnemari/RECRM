from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class BudgetValidationIn(BaseModel):
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None


class PropertyMatchScoreIn(BaseModel):
    property_amount: float
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    unit_city_id: Optional[str] = None
    preferred_city_id: Optional[str] = None
    unit_bedrooms: Optional[int] = None
    required_bedrooms_min: Optional[int] = None
    unit_area_sqm: Optional[float] = None
    required_area_min: Optional[float] = None
    is_available: bool = True
    amenities_match_ratio: float = 1.0
    timing_score: float = 100.0
    custom_weights: Optional[Dict[str, float]] = None


class RentalMetricsIn(BaseModel):
    monthly_rent: float
    purchase_price: float
    annual_vacancy_allowance: float = 0.0
    annual_operating_expenses: float = 0.0
    acquisition_costs: float = 0.0


class InvestmentReturnsIn(BaseModel):
    purchase_price: float
    cash_invested: float
    annual_pre_tax_cash_flow: float
    current_estimated_value: Optional[float] = None
    net_sale_proceeds: Optional[float] = None
    cumulative_rental_cash_flow: Optional[float] = None


class CommissionCalculationIn(BaseModel):
    transaction_type: str = "SALE"  # "SALE" or "RENT"
    base_amount: float
    rate_percent: float = 2.5
    fixed_fee: float = 0.0
    tax_rate_percent: float = 0.0


class AgentCommissionCalculationIn(BaseModel):
    transaction_type: str = "SALE"  # "SALE" or "RENT"
    deal_value: float
    brokerage_rate_percent: float = 2.5
    brokerage_flat_amount: Optional[float] = None
    compensation_type: str = "COMMISSION"  # "SALARY", "COMMISSION", "FIXED_CUT", "SALARY_PLUS_COMMISSION"
    sales_commission_rate: Optional[float] = 25.0
    rent_commission_rate: Optional[float] = 25.0
    sales_fixed_cut: Optional[float] = 0.0
    rent_fixed_cut: Optional[float] = 0.0
    base_salary: Optional[float] = 0.0
    vat_rate_percent: float = 15.0


class BalanceCalculationIn(BaseModel):
    amount_due: float
    amount_paid: float


class InvestmentCandidateIn(BaseModel):
    property_id: Optional[str] = None
    property_title: Optional[str] = None
    purchase_price: float
    monthly_rent: float
    annual_vacancy_allowance: float = 0.0
    annual_operating_expenses: float = 0.0
    acquisition_costs: float = 0.0
    cash_invested: Optional[float] = None
    annual_pre_tax_cash_flow: Optional[float] = None


class InvestmentComparisonIn(BaseModel):
    candidates: list[InvestmentCandidateIn]
    sort_by: Optional[str] = "net_operating_yield_percent"


