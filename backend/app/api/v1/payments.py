from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from app.core.deps import (
    get_audit_service,
    get_current_admin,
    get_current_user,
    get_payment_repository,
    get_payment_service,
    get_plan_service,
    require_admin_role,
)
from app.core.errors import NotFoundError
from app.models.admin_user import AdminUser
from app.models.enums import AdminRole
from app.models.user import User
from app.repositories.payment_repository import PaymentRepository
from app.schemas.common import Pagination
from app.schemas.payment import PaymentCreateRequest, PaymentCreateResponse, PaymentRead, WebhookAck
from app.services.audit_service import AuditService
from app.services.payment_service import PaymentService
from app.services.plan_service import PlanService

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("", response_model=PaymentCreateResponse, status_code=201)
async def create_payment(
    payload: PaymentCreateRequest,
    user: Annotated[User, Depends(get_current_user)],
    plan_service: Annotated[PlanService, Depends(get_plan_service)],
    payment_service: Annotated[PaymentService, Depends(get_payment_service)],
) -> PaymentCreateResponse:
    plan = await plan_service.get(payload.plan_id)
    payment, checkout_url = await payment_service.create_payment(
        user=user, plan=plan, promo_code=payload.promo_code
    )
    return PaymentCreateResponse(
        payment_id=payment.id, checkout_url=checkout_url, status=payment.status
    )


@router.get("/me", response_model=list[PaymentRead])
async def list_my_payments(
    user: Annotated[User, Depends(get_current_user)],
    repo: Annotated[PaymentRepository, Depends(get_payment_repository)],
) -> list[PaymentRead]:
    payments = await repo.list_for_user(user.id)
    return [PaymentRead.model_validate(p) for p in payments]


@router.get(
    "",
    response_model=list[PaymentRead],
    dependencies=[
        Depends(require_admin_role(AdminRole.SUPERADMIN, AdminRole.SUPPORT, AdminRole.VIEWER))
    ],
)
async def list_all_payments(
    repo: Annotated[PaymentRepository, Depends(get_payment_repository)],
    pagination: Annotated[Pagination, Depends()],
) -> list[PaymentRead]:
    payments = await repo.list_all(offset=pagination.offset, limit=pagination.limit)
    return [PaymentRead.model_validate(p) for p in payments]


@router.post("/webhook", response_model=WebhookAck)
async def payment_webhook(
    request: Request,
    payment_service: Annotated[PaymentService, Depends(get_payment_service)],
    x_signature: Annotated[str | None, Header()] = None,
) -> WebhookAck:
    """Idempotent by `external_payment_id`: replays of the same event are acknowledged
    without re-applying subscription activation (see `PaymentService.handle_webhook`)."""
    raw_body = await request.body()
    await payment_service.handle_webhook(raw_body=raw_body, signature=x_signature or "")
    return WebhookAck()


@router.post(
    "/{payment_id}/refund",
    response_model=PaymentRead,
    dependencies=[Depends(require_admin_role(AdminRole.SUPERADMIN))],
)
async def refund_payment(
    payment_id: int,
    repo: Annotated[PaymentRepository, Depends(get_payment_repository)],
    payment_service: Annotated[PaymentService, Depends(get_payment_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    admin: Annotated[AdminUser, Depends(get_current_admin)],
) -> PaymentRead:
    payment = await repo.get(payment_id)
    if payment is None:
        raise NotFoundError("Payment not found", error_code="payment_not_found")
    payment = await payment_service.refund(payment)
    await audit.record(
        admin_id=admin.id,
        action="payment.refunded",
        target_type="payment",
        target_id=str(payment_id),
        metadata={"user_id": payment.user_id, "amount": str(payment.amount)},
    )
    return PaymentRead.model_validate(payment)
