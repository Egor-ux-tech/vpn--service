from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🔌 Подключиться", callback_data="device:new")],
        [InlineKeyboardButton("🌍 Серверы", callback_data="menu:servers")],
        [InlineKeyboardButton("🧭 Smart VPN", callback_data="menu:smart")],
        [InlineKeyboardButton("📱 Мои устройства", callback_data="menu:devices")],
        [InlineKeyboardButton("💳 Подписка", callback_data="menu:subscription")],
        [InlineKeyboardButton("👤 Профиль", callback_data="menu:profile")],
        [InlineKeyboardButton("🆘 Поддержка", callback_data="menu:support")],
    ]
    return InlineKeyboardMarkup(rows)


def back_to_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:main")]]
    )


def protocol_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔒 WireGuard", callback_data="device:new:proto:wireguard")],
            [InlineKeyboardButton("⚡ VLESS", callback_data="device:new:proto:vless")],
            [InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:main")],
        ]
    )


def devices_keyboard(devices: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for device in devices:
        status_icon = {"active": "🟢", "disabled": "⏸️", "revoked": "🔴"}.get(device["status"], "⚪")
        rows.append(
            [
                InlineKeyboardButton(
                    f"{status_icon} {device['name']}", callback_data=f"device:manage:{device['id']}"
                )
            ]
        )
    rows.append([InlineKeyboardButton("➕ Новое устройство", callback_data="device:new")])
    rows.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def device_manage_keyboard(device: dict) -> InlineKeyboardMarkup:
    device_id = device["id"]
    rows = []
    # Reissue rotates a WireGuard keypair — meaningless for VLESS, where the
    # subscription link already reflects the device's current credential live (see
    # DeviceService.reissue's explicit rejection for protocol=vless).
    if device.get("protocol", "wireguard") == "wireguard":
        rows.append(
            [
                InlineKeyboardButton(
                    "🔄 Переиздать конфиг", callback_data=f"device:reissue:{device_id}"
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "🔗 Ссылка подписки", callback_data=f"device:sublink:view:{device_id}"
            )
        ]
    )
    if device["status"] == "active":
        rows.append(
            [InlineKeyboardButton("⏸️ Отключить", callback_data=f"device:disable:{device_id}")]
        )
    elif device["status"] == "disabled":
        rows.append(
            [InlineKeyboardButton("▶️ Включить", callback_data=f"device:enable:{device_id}")]
        )
    rows.append([InlineKeyboardButton("🗑️ Удалить", callback_data=f"device:revoke:{device_id}")])
    rows.append([InlineKeyboardButton("⬅️ Мои устройства", callback_data="menu:devices")])
    return InlineKeyboardMarkup(rows)


def subscription_link_keyboard(device_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔄 Обновить ссылку", callback_data=f"device:sublink:rotate:{device_id}"
                )
            ],
            [InlineKeyboardButton("⬅️ К устройству", callback_data=f"device:manage:{device_id}")],
        ]
    )


def plans_keyboard(plans: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                f"{plan['name']} — {plan['price']} {plan['currency']} / {plan['duration_days']}д",
                callback_data=f"plan:buy:{plan['id']}",
            )
        ]
        for plan in plans
    ]
    rows.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def smart_vpn_mode_keyboard(current_mode: str) -> InlineKeyboardMarkup:
    full_label = "✅ FULL VPN" if current_mode == "full_vpn" else "FULL VPN"
    smart_label = "✅ SMART VPN" if current_mode == "smart_vpn" else "SMART VPN"
    rows = [
        [InlineKeyboardButton(full_label, callback_data="smart:mode:full_vpn")],
        [InlineKeyboardButton(smart_label, callback_data="smart:mode:smart_vpn")],
    ]
    if current_mode == "smart_vpn":
        rows.append([InlineKeyboardButton("🗂️ Категории", callback_data="smart:categories")])
        rows.append([InlineKeyboardButton("➕ Свой домен", callback_data="smart:add_domain")])
    rows.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def smart_vpn_categories_keyboard(
    categories: list[dict], enabled_ids: set[int]
) -> InlineKeyboardMarkup:
    rows = []
    for category in categories:
        checked = "☑️" if category["id"] in enabled_ids else "⬜️"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{checked} {category['name']}", callback_data=f"smart:cat:{category['id']}"
                )
            ]
        )
    rows.append([InlineKeyboardButton("⬅️ Smart VPN", callback_data="menu:smart")])
    return InlineKeyboardMarkup(rows)


def servers_keyboard(servers: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for server in servers:
        icon = "🟢" if server["status"] == "online" else "🔴"
        load = f"{server['current_load']}/{server['capacity']}"
        label = f"{icon} {server['name']} ({server['country']}) — {load}"
        rows.append([InlineKeyboardButton(label, callback_data=f"device:new:{server['id']}")])
    rows.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)
