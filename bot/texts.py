"""Усі тексти бота в одному місці. HTML-розмітка (parse_mode=HTML).

Будь-який текст від користувача (назви, імена, реквізити) екрануємо через `esc`.
"""

from collections.abc import Sequence
from html import escape as esc

from bot.db.models import Member, Pool, User
from bot.services.errors import DomainError, ErrorCode
from bot.services.money import format_money
from bot.services.pools import MAX_MEMBERS, JoinPreview, JoinResult, JoinStatus, NewPoolData

# --- загальне ----------------------------------------------------------------

START = (
    "Привіт, {name}! 👋\n\n"
    "Я <b>Скинемось</b>: допомагаю збирати гроші за спільні підписки й витрати "
    "(YouTube Family, Netflix, інтернет, комуналка).\n\n"
    "<b>Як це працює:</b>\n"
    "1. Ти створюєш збір через /new: назва, сума, день списання, реквізити.\n"
    "2. Надсилаєш друзям посилання-запрошення.\n"
    "3. Щомісяця я сам нагадую кожному скинути свою частку, "
    "а ти лише підтверджуєш оплати.\n\n"
    "Усі команди: /help"
)

HELP = (
    "<b>Команди</b>\n\n"
    "/new — створити новий збір\n"
    "/my — мої збори (де я власник чи учасник)\n"
    "/status — хто вже скинув за цей місяць\n"
    "/cancel — скасувати поточну дію\n"
    "/help — ця довідка\n\n"
    "<b>Як приєднатися до збору?</b>\n"
    "Попроси власника збору надіслати посилання-запрошення й перейди за ним.\n\n"
    "<b>Як я рахую суми?</b>\n"
    "Загальна сума ділиться порівну між учасниками (і власником, якщо він у розподілі). "
    "Власник може вручну змінити частку будь-кого."
)

NOT_IMPLEMENTED = "🛠 Ця функція ще в розробці."
CANCELLED = "Скасовано 👌"
NOTHING_TO_CANCEL = "Немає чого скасовувати 🙂"

COMMANDS: dict[str, str] = {
    "start": "Почати",
    "new": "Створити збір",
    "my": "Мої збори",
    "status": "Статус оплат за місяць",
    "cancel": "Скасувати дію",
    "help": "Довідка",
}

# --- кнопки ------------------------------------------------------------------

BTN_OWNER_YES = "Так, я теж плачу свою частку"
BTN_OWNER_NO = "Ні, ділимо лише між учасниками"
BTN_CREATE = "✅ Створити"
BTN_CANCEL = "✖️ Скасувати"
BTN_JOIN = "🤝 Приєднатися"
BTN_INVITE_LINK = "🔗 Посилання-запрошення"
BTN_BACK_TO_LIST = "⬅️ До списку зборів"
BTN_BACK = "⬅️ Назад"
BTN_OPEN_POOL = "Відкрити збір"

# --- помилки -----------------------------------------------------------------

ERRORS: dict[ErrorCode, str] = {
    ErrorCode.INVALID_TITLE: "Назва має бути від 1 до 64 символів. Спробуй ще раз.",
    ErrorCode.INVALID_AMOUNT: (
        "Не розумію суму 🤔 Напиши число від 0,01 до 100 000, наприклад <code>300</code> "
        "або <code>149,99</code>."
    ),
    ErrorCode.INVALID_BILLING_DAY: "День списання — це число від 1 до 31. Спробуй ще раз.",
    ErrorCode.INVALID_DETAILS: "Реквізити не можуть бути порожніми й довшими за 500 символів.",
    ErrorCode.POOL_NOT_FOUND: (
        "Цей збір не знайдено 😕 Можливо, посилання застаріло або збір видалено. "
        "Попроси у власника нове посилання."
    ),
    ErrorCode.NOT_POOL_OWNER: "Це може робити лише власник збору.",
    ErrorCode.OWNER_CANNOT_JOIN: (
        "Це твій власний збір 🙂 Ти вже в ньому як власник, приєднуватися не треба."
    ),
    ErrorCode.POOL_FULL: f"У зборі вже максимум учасників ({MAX_MEMBERS}) 😔",
    ErrorCode.NOT_A_MEMBER: "Ти не береш участі в цьому зборі.",
}


def error_text(error: DomainError) -> str:
    return ERRORS.get(error.code, "Щось пішло не так. Спробуй ще раз.")


# --- створення збору ---------------------------------------------------------

ASK_TITLE = (
    "Створюємо новий збір 💸\n\n"
    "<b>Крок 1/5.</b> Як він називається? Наприклад: <i>YouTube Family</i>.\n\n"
    "Скасувати можна будь-коли: /cancel"
)
ASK_AMOUNT = "<b>Крок 2/5.</b> Яка загальна сума на місяць у гривнях? Наприклад: <code>300</code>."
ASK_BILLING_DAY = (
    "<b>Крок 3/5.</b> Якого числа щомісяця списуються гроші? Напиши число від 1 до 31.\n"
    "Цього дня я надішлю учасникам нагадування."
)
ASK_INCLUDE_OWNER = "<b>Крок 4/5.</b> Ти теж платиш свою частку, як усі учасники?"
ASK_DETAILS = (
    "<b>Крок 5/5.</b> Куди скидати гроші? Номер картки, посилання на банку mono "
    "чи інші реквізити, як ти хочеш їх показати учасникам."
)
EXPECT_TEXT = "Напиши, будь ласка, текстом ✍️"
EXPECT_BUTTON = "Обери варіант кнопкою вище 👆"
LOOKS_LIKE_COMMAND = "Схоже на команду. Щоб вийти зі створення збору, натисни /cancel."
CREATE_SESSION_EXPIRED = "Ця кнопка вже неактуальна. Почни заново: /new"


def billing_day_text(day: int) -> str:
    text = f"{day} числа"
    if day >= 29:
        text += " (у коротших місяцях — в останній день)"
    return text


def confirm_pool(data: NewPoolData) -> str:
    return (
        "Перевір, чи все правильно:\n\n"
        f"📌 <b>{esc(data.title)}</b>\n"
        f"💰 Сума: {format_money(data.total_amount_kop)} на місяць\n"
        f"📅 Списання: {billing_day_text(data.billing_day)}\n"
        f"👑 Ти в розподілі: {'так' if data.include_owner else 'ні'}\n"
        f"💳 Реквізити: {esc(data.payment_details)}"
    )


def pool_created(pool: Pool, invite_link: str) -> str:
    return (
        f"Збір <b>{esc(pool.title)}</b> створено 🎉\n\n"
        "Надішли друзям це посилання, щоб вони приєдналися:\n"
        f"{invite_link}\n\n"
        f"Учасників може бути до {MAX_MEMBERS}. Сума ділиться автоматично."
    )


# --- приєднання --------------------------------------------------------------


def join_preview(preview: JoinPreview) -> str:
    pool = preview.pool
    owner_note = "" if pool.include_owner else "\n<i>Власник у розподілі не бере участі.</i>"
    return (
        f"<b>{esc(pool.owner.display_name)}</b> запрошує тебе до збору "
        f"<b>{esc(pool.title)}</b> 💸\n\n"
        f"💰 Загальна сума: {format_money(pool.total_amount_kop)} на місяць\n"
        f"📅 Списання: {billing_day_text(pool.billing_day)}\n"
        f"👥 Учасників зараз: {preview.members_count}\n"
        f"🧮 Твоя частка буде: <b>{format_money(preview.estimated_share_kop)}</b>"
        f"{owner_note}\n\n"
        "Приєднуєшся?"
    )


def already_member(pool: Pool) -> str:
    return f"Ти вже в зборі <b>{esc(pool.title)}</b> 👍"


def joined(result: JoinResult) -> str:
    pool = result.pool
    hello = "З поверненням" if result.status is JoinStatus.REJOINED else "Готово"
    return (
        f"{hello}! Ти в зборі <b>{esc(pool.title)}</b> 🎉\n\n"
        f"🧮 Твоя частка: <b>{format_money(result.member.share_kop)}</b> на місяць\n"
        f"📅 Я нагадаю {billing_day_text(pool.billing_day)}.\n"
        f"💳 Реквізити: {esc(pool.payment_details)}\n\n"
        "Якщо хтось ще приєднається, частка може змінитися з наступного місяця."
    )


def owner_member_joined(result: JoinResult, member_user: User) -> str:
    return (
        f"🙋 <b>{esc(member_user.display_name)}</b> приєднався(-лася) до збору "
        f"<b>{esc(result.pool.title)}</b>.\n"
        f"Учасників: {result.members_count}/{MAX_MEMBERS}. "
        "Нові частки діють з наступного списання."
    )


# --- перегляд зборів ---------------------------------------------------------

NO_POOLS = (
    "У тебе ще немає зборів.\n\nСтвори свій через /new або попроси в друзів посилання-запрошення."
)


def my_pools(owned: Sequence[Pool], memberships: Sequence[Member]) -> str:
    lines = ["<b>Мої збори</b>\n"]
    if owned:
        lines.append("👑 — ти власник, 🙋 — ти учасник.")
    elif memberships:
        lines.append("🙋 — збори, де ти учасник.")
    lines.append("Обери збір, щоб побачити деталі:")
    return "\n".join(lines)


def _pool_header(pool: Pool) -> list[str]:
    lines = [f"📌 <b>{esc(pool.title)}</b>"]
    if pool.is_paused:
        lines.append("⏸ <i>Збір на паузі</i>")
    lines += [
        f"💰 {format_money(pool.total_amount_kop)} на місяць",
        f"📅 Списання: {billing_day_text(pool.billing_day)}",
    ]
    return lines


def owner_pool_card(pool: Pool, members: Sequence[Member]) -> str:
    lines = _pool_header(pool)
    lines.append(f"💳 Реквізити: {esc(pool.payment_details)}")
    lines.append(f"\n<b>Учасники ({len(members)}/{MAX_MEMBERS}):</b>")
    if pool.include_owner or pool.owner_share_kop:
        label = "Ти" if pool.include_owner else "Ти (невкрита частина)"
        lines.append(f"👑 {label} — {format_money(pool.owner_share_kop)}")
    for member in members:
        mark = "" if member.user.is_reachable else " ⚠️ недоступний"
        custom = " ✏️" if member.share_is_custom else ""
        lines.append(
            f"• {esc(member.user.display_name)} — {format_money(member.share_kop)}{custom}{mark}"
        )
    if not members:
        lines.append("<i>Поки нікого. Надішли друзям посилання-запрошення.</i>")
    return "\n".join(lines)


def member_pool_card(member: Member) -> str:
    pool = member.pool
    lines = _pool_header(pool)
    lines += [
        f"👑 Власник: {esc(pool.owner.display_name)}",
        f"🧮 Твоя частка: <b>{format_money(member.share_kop)}</b>",
        f"💳 Реквізити: {esc(pool.payment_details)}",
    ]
    return "\n".join(lines)


def invite_link(pool: Pool, link: str) -> str:
    return (
        f"🔗 Посилання-запрошення до <b>{esc(pool.title)}</b>:\n\n{link}\n\n"
        "Перешли його тим, хто має скидатися."
    )
