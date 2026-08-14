from fastapi import APIRouter

from app.api.v1 import (
    admin,
    auth,
    devices,
    payments,
    plans,
    routing,
    servers,
    subscription_links,
    subscriptions,
    support,
    users,
    vless_servers,
    vpn,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(plans.router)
api_router.include_router(subscriptions.router)
api_router.include_router(devices.router)
api_router.include_router(subscription_links.router)
api_router.include_router(vpn.router)
api_router.include_router(servers.router)
api_router.include_router(vless_servers.router)
api_router.include_router(routing.router)
api_router.include_router(payments.router)
api_router.include_router(support.router)
api_router.include_router(admin.router)
