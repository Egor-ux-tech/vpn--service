from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.models.device import Device
from app.models.enums import RouteType, RoutingMode
from app.models.routing import (
    RoutingCategory,
    RoutingRule,
    UserCategoryPreference,
    UserCustomDomain,
    UserRoutingProfile,
)
from app.models.vpn_profile import VPNProfile
from app.repositories.routing_repository import (
    RoutingCategoryRepository,
    RoutingRuleRepository,
    UserCategoryPreferenceRepository,
    UserCustomDomainRepository,
    UserRoutingProfileRepository,
)
from app.repositories.vpn_profile_repository import VPNProfileRepository
from app.schemas.routing import RoutingRuleCreate
from app.services.routing.engine import DomainRule, RoutingEngine


class RoutingService:
    def __init__(
        self,
        category_repository: RoutingCategoryRepository,
        rule_repository: RoutingRuleRepository,
        user_profile_repository: UserRoutingProfileRepository,
        user_category_pref_repository: UserCategoryPreferenceRepository,
        user_custom_domain_repository: UserCustomDomainRepository,
        vpn_profile_repository: VPNProfileRepository,
        engine: RoutingEngine,
    ) -> None:
        self._categories = category_repository
        self._rules = rule_repository
        self._user_profiles = user_profile_repository
        self._user_category_prefs = user_category_pref_repository
        self._user_custom_domains = user_custom_domain_repository
        self._vpn_profiles = vpn_profile_repository
        self._engine = engine

    async def list_categories(self) -> list[RoutingCategory]:
        return await self._categories.list_enabled()

    async def create_category(self, name: str, description: str | None) -> RoutingCategory:
        category = RoutingCategory(name=name, description=description, enabled=True)
        self._categories.add(category)
        await self._categories.flush()
        return category

    async def add_rule(self, payload: RoutingRuleCreate) -> RoutingRule:
        rule = RoutingRule(
            category_id=payload.category_id,
            domain=payload.domain.lower().strip(),
            route_type=payload.route_type,
            enabled=payload.enabled,
            updated_at=datetime.now(UTC),
        )
        self._rules.add(rule)
        await self._rules.flush()
        return rule

    async def list_user_category_preferences(self, user_id: int) -> list[UserCategoryPreference]:
        return await self._user_category_prefs.list_for_user(user_id)

    async def list_user_custom_domains(self, user_id: int) -> list[UserCustomDomain]:
        return await self._user_custom_domains.list_for_user(user_id)

    async def get_or_create_user_profile(self, user_id: int) -> UserRoutingProfile:
        profile = await self._user_profiles.get_for_user(user_id)
        if profile is None:
            profile = UserRoutingProfile(user_id=user_id, mode=RoutingMode.FULL_VPN)
            self._user_profiles.add(profile)
            await self._user_profiles.flush()
        return profile

    async def set_mode(self, user_id: int, mode: RoutingMode) -> UserRoutingProfile:
        profile = await self.get_or_create_user_profile(user_id)
        profile.mode = mode
        return profile

    async def set_category_preference(self, user_id: int, category_id: int, enabled: bool) -> None:
        if await self._categories.get(category_id) is None:
            raise NotFoundError("Routing category not found", error_code="category_not_found")
        pref = await self._user_category_prefs.get(user_id, category_id)
        if pref is None:
            pref = UserCategoryPreference(user_id=user_id, category_id=category_id, enabled=enabled)
            self._user_category_prefs.add(pref)
        else:
            pref.enabled = enabled
        await self._user_category_prefs.flush()

    async def add_custom_domain(self, user_id: int, domain: str, route_type: RouteType) -> None:
        existing = await self._user_custom_domains.list_for_user(user_id)
        domain = domain.lower().strip()
        for d in existing:
            if d.domain == domain:
                d.route_type = route_type
                d.enabled = True
                return
        self._user_custom_domains.add(
            UserCustomDomain(
                user_id=user_id,
                domain=domain,
                route_type=route_type,
                enabled=True,
                created_at=datetime.now(UTC),
            )
        )
        await self._user_custom_domains.flush()

    async def _resolve_user_domain_rules(self, user_id: int) -> list[DomainRule]:
        prefs = {
            p.category_id: p.enabled for p in await self._user_category_prefs.list_for_user(user_id)
        }
        rules = await self._rules.list_enabled_with_category()

        domain_rules: list[DomainRule] = []
        for rule in rules:
            category_enabled = prefs.get(rule.category_id, False)
            route_type = rule.route_type if category_enabled else RouteType.DIRECT
            domain_rules.append((rule.domain, route_type))

        for custom in await self._user_custom_domains.list_for_user(user_id):
            if custom.enabled:
                domain_rules.append((custom.domain, custom.route_type))

        return domain_rules

    async def regenerate_profile(self, device: Device, user_id: int) -> VPNProfile:
        """Builds a fresh, versioned VPNProfile snapshot for a device and marks any
        previous snapshot superseded. Never mutates a profile in place, so a client mid-read
        never observes a half-written AllowedIPs list."""
        profile = await self.get_or_create_user_profile(user_id)

        if profile.mode is RoutingMode.FULL_VPN:
            allowed_ips = RoutingEngine.full_vpn_allowed_ips()
        else:
            domain_rules = await self._resolve_user_domain_rules(user_id)
            allowed_ips = await self._engine.build_allowed_ips(domain_rules)
            if not allowed_ips:
                # Safe fallback: never provision a peer that can reach nothing.
                allowed_ips = RoutingEngine.full_vpn_allowed_ips()

        current = await self._vpn_profiles.get_current_for_device(device.id)
        next_version = (current.version + 1) if current else 1
        await self._vpn_profiles.mark_superseded(device.id)

        settings = get_settings()
        new_profile = VPNProfile(
            device_id=device.id,
            mode=profile.mode,
            allowed_ips=allowed_ips,
            dns=settings.vpn_dns_list,
            version=next_version,
            is_current=True,
            generated_at=datetime.now(UTC),
        )
        self._vpn_profiles.add(new_profile)
        await self._vpn_profiles.flush()
        return new_profile
