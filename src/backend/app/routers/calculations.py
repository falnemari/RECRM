from fastapi import APIRouter, HTTPException, status
from app.schemas.common import ResponseEnvelope, BaseMeta
from app.schemas.calculations import (
    BudgetValidationIn,
    PropertyMatchScoreIn,
    RentalMetricsIn,
    InvestmentReturnsIn,
    CommissionCalculationIn,
    BalanceCalculationIn,
)
from app.services.calculation_service import CalculationService

router = APIRouter(prefix="/calculations", tags=["Financial, Yield & Matching Calculations"])


@router.post("/validate-budget", response_model=ResponseEnvelope[dict])
def validate_budget_endpoint(payload: BudgetValidationIn):
    is_valid, error_msg = CalculationService.validate_budget_range(
        budget_min=payload.budget_min,
        budget_max=payload.budget_max
    )
    return ResponseEnvelope(
        data={"is_valid": is_valid, "error_message": error_msg},
        meta=BaseMeta()
    )


@router.post("/property-match-score", response_model=ResponseEnvelope[dict])
def calculate_match_score_endpoint(payload: PropertyMatchScoreIn):
    is_eligible, total_score, breakdown = CalculationService.calculate_property_match_score(
        property_amount=payload.property_amount,
        budget_min=payload.budget_min,
        budget_max=payload.budget_max,
        unit_city_id=payload.unit_city_id,
        preferred_city_id=payload.preferred_city_id,
        unit_bedrooms=payload.unit_bedrooms,
        required_bedrooms_min=payload.required_bedrooms_min,
        unit_area_sqm=payload.unit_area_sqm,
        required_area_min=payload.required_area_min,
        is_available=payload.is_available,
        amenities_match_ratio=payload.amenities_match_ratio,
        timing_score=payload.timing_score,
        custom_weights=payload.custom_weights
    )
    return ResponseEnvelope(
        data={
            "is_eligible": is_eligible,
            "total_score": total_score,
            "breakdown": breakdown
        },
        meta=BaseMeta()
    )


@router.post("/rental-metrics", response_model=ResponseEnvelope[dict])
def calculate_rental_metrics_endpoint(payload: RentalMetricsIn):
    try:
        metrics = CalculationService.calculate_rental_metrics(
            monthly_rent=payload.monthly_rent,
            purchase_price=payload.purchase_price,
            annual_vacancy_allowance=payload.annual_vacancy_allowance,
            annual_operating_expenses=payload.annual_operating_expenses,
            acquisition_costs=payload.acquisition_costs
        )
        return ResponseEnvelope(data=metrics, meta=BaseMeta())
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/investment-returns", response_model=ResponseEnvelope[dict])
def calculate_investment_returns_endpoint(payload: InvestmentReturnsIn):
    try:
        returns = CalculationService.calculate_investment_returns(
            purchase_price=payload.purchase_price,
            cash_invested=payload.cash_invested,
            annual_pre_tax_cash_flow=payload.annual_pre_tax_cash_flow,
            current_estimated_value=payload.current_estimated_value,
            net_sale_proceeds=payload.net_sale_proceeds,
            cumulative_rental_cash_flow=payload.cumulative_rental_cash_flow
        )
        return ResponseEnvelope(data=returns, meta=BaseMeta())
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/commission", response_model=ResponseEnvelope[dict])
def calculate_commission_endpoint(payload: CommissionCalculationIn):
    try:
        comm = CalculationService.calculate_commission(
            transaction_type=payload.transaction_type,
            base_amount=payload.base_amount,
            rate_percent=payload.rate_percent,
            fixed_fee=payload.fixed_fee,
            tax_rate_percent=payload.tax_rate_percent
        )
        return ResponseEnvelope(data=comm, meta=BaseMeta())
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/balance", response_model=ResponseEnvelope[dict])
def calculate_balance_endpoint(payload: BalanceCalculationIn):
    try:
        balance = CalculationService.calculate_outstanding_balance(
            amount_due=payload.amount_due,
            amount_paid=payload.amount_paid
        )
        return ResponseEnvelope(data=balance, meta=BaseMeta())
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

