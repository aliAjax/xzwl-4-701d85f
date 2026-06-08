from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional, List
from math import ceil

from ..database import get_db
from ..models.user import User, UserRole
from ..models.device import DeviceCategory
from ..models.pricing_rule import PricingRule, TieredDiscount, PricingRuleStatus
from ..schemas import (
    PricingRuleCreate,
    PricingRuleUpdate,
    PricingRuleResponse,
    TrialCalcRequest,
    TrialCalcResponse,
    TrialCalcItemResult,
    APIResponse,
    PaginatedResponse,
)
from ..core import get_current_active_user, require_role, AuditLogger

router = APIRouter(prefix="/api/pricing-rules", tags=["Pricing Rules"])


def get_applicable_pricing_rule(
    db: Session,
    category_id: int,
    rental_days: int,
    customer_role: Optional[UserRole] = None
) -> Optional[PricingRule]:
    query = db.query(PricingRule).filter(
        PricingRule.category_id == category_id,
        PricingRule.status == PricingRuleStatus.ACTIVE
    )

    rules = query.order_by(PricingRule.priority.asc(), PricingRule.id.desc()).all()

    for rule in rules:
        if not rule.is_within_valid_period():
            continue
        if customer_role and not rule.is_available_for_role(customer_role):
            continue
        return rule

    return None


@router.get("", response_model=PaginatedResponse[PricingRuleResponse])
async def list_pricing_rules(
    page: int = 1,
    per_page: int = 20,
    category_id: Optional[int] = None,
    status: Optional[PricingRuleStatus] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    query = db.query(PricingRule)

    if category_id:
        query = query.filter(PricingRule.category_id == category_id)
    if status:
        query = query.filter(PricingRule.status == status)
    if search:
        query = query.filter(
            (PricingRule.name.ilike(f"%{search}%")) |
            (PricingRule.description.ilike(f"%{search}%"))
        )

    total = query.count()
    rules = query.order_by(PricingRule.priority.asc(), PricingRule.id.desc()) \
        .offset((page - 1) * per_page) \
        .limit(per_page) \
        .all()

    return PaginatedResponse(
        data=rules,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/{rule_id}", response_model=APIResponse[PricingRuleResponse])
async def get_pricing_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    rule = db.query(PricingRule).filter(PricingRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Pricing rule not found")
    return APIResponse(data=rule)


@router.post("", response_model=APIResponse[PricingRuleResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def create_pricing_rule(
    request: Request,
    rule_data: PricingRuleCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    category = db.query(DeviceCategory).filter(DeviceCategory.id == rule_data.category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Device category not found")

    if rule_data.valid_from and rule_data.valid_to and rule_data.valid_from >= rule_data.valid_to:
        raise HTTPException(status_code=400, detail="valid_from must be before valid_to")

    for discount in rule_data.tiered_discounts:
        if discount.max_days is not None and discount.min_days > discount.max_days:
            raise HTTPException(status_code=400, detail="min_days must be less than or equal to max_days")

    new_rule = PricingRule(
        name=rule_data.name,
        description=rule_data.description,
        category_id=rule_data.category_id,
        priority=rule_data.priority,
        min_rental_days=rule_data.min_rental_days,
        deposit_adjustment_factor=rule_data.deposit_adjustment_factor,
        overdue_daily_rate_multiplier=rule_data.overdue_daily_rate_multiplier,
        allowed_customer_roles=rule_data.allowed_customer_roles or [],
        valid_from=rule_data.valid_from,
        valid_to=rule_data.valid_to,
        created_by_id=current_user.id,
    )

    for discount_data in rule_data.tiered_discounts:
        discount = TieredDiscount(**discount_data.model_dump())
        new_rule.tiered_discounts.append(discount)

    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)

    audit_logger = AuditLogger(db)
    audit_logger.log_create(
        resource_type="pricing_rule",
        resource_id=str(new_rule.id),
        user=current_user,
        new_values=rule_data.model_dump(),
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Pricing rule created successfully", data=new_rule)


@router.put("/{rule_id}", response_model=APIResponse[PricingRuleResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def update_pricing_rule(
    request: Request,
    rule_id: int,
    rule_data: PricingRuleUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    rule = db.query(PricingRule).filter(PricingRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Pricing rule not found")

    old_values = {
        "name": rule.name,
        "category_id": rule.category_id,
        "priority": rule.priority,
        "min_rental_days": rule.min_rental_days,
        "deposit_adjustment_factor": rule.deposit_adjustment_factor,
    }

    if rule_data.category_id is not None:
        category = db.query(DeviceCategory).filter(DeviceCategory.id == rule_data.category_id).first()
        if not category:
            raise HTTPException(status_code=404, detail="Device category not found")

    valid_from = rule_data.valid_from if rule_data.valid_from is not None else rule.valid_from
    valid_to = rule_data.valid_to if rule_data.valid_to is not None else rule.valid_to
    if valid_from and valid_to and valid_from >= valid_to:
        raise HTTPException(status_code=400, detail="valid_from must be before valid_to")

    if rule_data.tiered_discounts is not None:
        for discount in rule_data.tiered_discounts:
            if discount.max_days is not None and discount.min_days > discount.max_days:
                raise HTTPException(status_code=400, detail="min_days must be less than or equal to max_days")

    update_data = rule_data.model_dump(exclude_unset=True, exclude={"tiered_discounts"})
    for field, value in update_data.items():
        setattr(rule, field, value)

    if rule_data.tiered_discounts is not None:
        for discount in rule.tiered_discounts:
            db.delete(discount)
        rule.tiered_discounts = []

        for discount_data in rule_data.tiered_discounts:
            discount = TieredDiscount(**discount_data.model_dump())
            rule.tiered_discounts.append(discount)

    db.commit()
    db.refresh(rule)

    audit_logger = AuditLogger(db)
    audit_logger.log_update(
        resource_type="pricing_rule",
        resource_id=str(rule_id),
        user=current_user,
        old_values=old_values,
        new_values=rule_data.model_dump(exclude_unset=True),
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Pricing rule updated successfully", data=rule)


@router.delete("/{rule_id}", response_model=APIResponse)
@require_role([UserRole.ADMIN])
async def delete_pricing_rule(
    request: Request,
    rule_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    rule = db.query(PricingRule).filter(PricingRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Pricing rule not found")

    old_values = {"name": rule.name, "id": rule.id, "category_id": rule.category_id}

    db.delete(rule)
    db.commit()

    audit_logger = AuditLogger(db)
    audit_logger.log_delete(
        resource_type="pricing_rule",
        resource_id=str(rule_id),
        user=current_user,
        old_values=old_values,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Pricing rule deleted successfully")


@router.post("/trial-calc", response_model=APIResponse[TrialCalcResponse])
async def trial_calculate(
    calc_request: TrialCalcRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    warnings: List[str] = []
    item_results: List[TrialCalcItemResult] = []
    applied_rules = []
    total_rental_fee = 0.0
    total_deposit = 0.0
    total_discount = 0.0
    total_base_rental = 0.0
    effective_rental_days = calc_request.rental_days

    customer_role = None
    if calc_request.customer_id:
        customer = db.query(User).filter(User.id == calc_request.customer_id).first()
        if customer:
            customer_role = customer.role
    elif calc_request.customer_role:
        try:
            customer_role = UserRole(calc_request.customer_role)
        except ValueError:
            warnings.append(f"Invalid customer role: {calc_request.customer_role}")

    for item in calc_request.items:
        category = db.query(DeviceCategory).filter(DeviceCategory.id == item.category_id).first()
        if not category:
            warnings.append(f"Category not found: {item.category_id}")
            continue

        daily_rate = item.daily_rate_override or category.daily_rental_rate
        base_deposit = item.deposit_override or category.deposit_amount

        rule = get_applicable_pricing_rule(
            db,
            category_id=item.category_id,
            rental_days=calc_request.rental_days,
            customer_role=customer_role
        )

        discount_rate = 0.0
        base_rental = daily_rate * calc_request.rental_days * item.quantity
        discount_amount = 0.0
        rental_fee = round(base_rental, 2)
        deposit = round(base_deposit * item.quantity, 2)

        if rule:
            if rule.min_rental_days > effective_rental_days:
                effective_rental_days = rule.min_rental_days

            discount_rate = rule.get_applicable_discount(calc_request.rental_days)
            rental_fee = rule.calculate_rental_fee(daily_rate, calc_request.rental_days, item.quantity)
            deposit = rule.calculate_deposit(base_deposit, item.quantity)

            base_rental = daily_rate * max(calc_request.rental_days, rule.min_rental_days) * item.quantity
            discount_amount = base_rental * (discount_rate / 100)

            applied_rule_info = {
                "rule_id": rule.id,
                "rule_name": rule.name,
                "category_id": category.id,
                "discount_rate": discount_rate,
                "min_rental_days": rule.min_rental_days,
            }
            if applied_rule_info not in applied_rules:
                applied_rules.append(applied_rule_info)
        else:
            warnings.append(f"No pricing rule found for category '{category.name}', using default rates")

        total_base_rental += base_rental
        total_discount += discount_amount
        total_rental_fee += rental_fee
        total_deposit += deposit

        item_result = TrialCalcItemResult(
            category_id=category.id,
            category_name=category.name,
            quantity=item.quantity,
            daily_rate=daily_rate,
            base_deposit=base_deposit,
            applied_discount_rate=discount_rate,
            applied_pricing_rule_id=rule.id if rule else None,
            applied_pricing_rule_name=rule.name if rule else None,
            rental_fee=rental_fee,
            deposit=deposit,
            subtotal=round(rental_fee + deposit, 2),
        )
        item_results.append(item_result)

    manual_discount_amount = 0.0
    if calc_request.manual_discount_rate and calc_request.manual_discount_rate > 0:
        manual_discount_amount = round(total_rental_fee * (calc_request.manual_discount_rate / 100), 2)
        total_discount += manual_discount_amount
        total_rental_fee = round(total_rental_fee - manual_discount_amount, 2)

    estimated_overdue_fee = 0.0
    if calc_request.expected_overdue_days and calc_request.expected_overdue_days > 0:
        from ..config import settings
        unique_categories = set(item.category_id for item in calc_request.items)
        for category_id in unique_categories:
            rule = get_applicable_pricing_rule(db, category_id, calc_request.rental_days, customer_role)
            multiplier = rule.overdue_daily_rate_multiplier if rule else 1.0
            quantity = sum(i.quantity for i in calc_request.items if i.category_id == category_id)
            estimated_overdue_fee += settings.OVERDUE_DAILY_RATE * multiplier * calc_request.expected_overdue_days * quantity
        estimated_overdue_fee = round(estimated_overdue_fee, 2)

    grand_total = round(total_rental_fee + total_deposit + estimated_overdue_fee, 2)

    response = TrialCalcResponse(
        items=item_results,
        rental_days=calc_request.rental_days,
        effective_rental_days=effective_rental_days,
        total_rental_fee=round(total_rental_fee, 2),
        total_deposit=round(total_deposit, 2),
        total_discount=round(total_discount, 2),
        manual_discount_amount=manual_discount_amount,
        estimated_overdue_fee=estimated_overdue_fee,
        grand_total=grand_total,
        applied_rules=applied_rules,
        warnings=warnings,
    )

    return APIResponse(data=response)
