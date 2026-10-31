"""Усі тексти бота в одному місці. HTML-розмітка (parse_mode=HTML).

Будь-який текст від користувача (назви, імена, реквізити) екрануємо через `esc`.
"""

from collections.abc import Sequence
from datetime import date, datetime
from html import escape as esc

from bot.db.models import Member, Payment, PaymentStatus, Pool, User
from bot.services.errors import DomainError, ErrorCode
from bot.services.money import format_money
from bot.services.payments import PoolStatus
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

UNKNOWN_MESSAGE = "Не зовсім розумію 🙂 Подивись, що я вмію: /help"
STALE_BUTTON = "Ця кнопка вже неактуальна. Відкрий потрібний збір через /my."
UNEXPECTED_ERROR = "Ой, щось пішло не так 😔 Спробуй ще раз трохи згодом."
UNEXPECTED_ERROR_ALERT = "Щось пішло не так. Спробуй ще раз трохи згодом."
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
BTN_CLAIM = "Я скинув ✅"
BTN_CONFIRM = "✅ Підтвердити"
BTN_REJECT = "❌ Не бачу оплати"
BTN_REGEN_INVITE = "🔄 Нове посилання"
BTN_EDIT_AMOUNT = "✏️ Сума"
BTN_EDIT_DAY = "📅 День"
BTN_EDIT_DETAILS = "💳 Реквізити"
BTN_MEMBERS = "👥 Учасники й частки"
BTN_MARK_PAID = "✅ Позначити оплату вручну"
BTN_PAUSE = "⏸ Поставити на паузу"
BTN_RESUME = "▶️ Відновити збір"
BTN_DELETE = "🗑 Видалити збір"
BTN_DELETE_CONFIRM = "Так, видалити"
BTN_KEEP = "Ні, залишити"
BTN_HISTORY = "📜 Історія платежів"
BTN_LEAVE = "🚪 Вийти зі збору"
BTN_LEAVE_CONFIRM = "Так, вийти"
BTN_STAY = "Ні, лишаюся"
BTN_SET_SHARE = "✏️ Змінити частку"
BTN_SHARE_AUTO = "🔄 Повернути автоматичну частку"
BTN_REMOVE_MEMBER = "🚫 Видалити зі збору"

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
    ErrorCode.MEMBER_NOT_FOUND: "Цього учасника вже немає в зборі.",
    ErrorCode.INVALID_SHARE: (
        "Так не вийде: ручні частки разом не можуть перевищувати загальну суму збору."
    ),
    ErrorCode.PAYMENT_NOT_FOUND: "Цей платіж не знайдено. Можливо, збір видалено.",
    ErrorCode.INVALID_TRANSITION: "Статус цього платежу вже змінився. Онови список.",
}


def error_text(error: DomainError) -> str:
    return ERRORS.get(error.code, "Щось пішло не так. Спробуй ще раз.")


# --- імена користувачів ----------------------------------------------------------


def mention(user: User) -> str:
    """Клікабельне ім'я: з username відкриває чат (t.me/…), без нього — профіль за id.

    Поруч показуємо @username, щоб людину було легко впізнати навіть з ім'ям «.».
    Посилання за id відкривається, лише якщо налаштування приватності користувача це дозволяють.
    """
    name = esc(user.display_name)
    if user.username:
        link = f'<a href="https://t.me/{esc(user.username)}">{name}</a>'
        # display_name уже дорівнює @username, якщо імені немає: не дублюємо
        return f"{link} (@{esc(user.username)})" if user.first_name else link
    return f'<a href="tg://user?id={user.telegram_id}">{name}</a>'


def plain_name(user: User) -> str:
    """Ім'я для кнопок і спливаючих вікон, де посилання неможливі."""
    if user.username and user.first_name:
        return f"{user.first_name} @{user.username}"
    return user.display_name


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
        f"<b>{mention(pool.owner)}</b> запрошує тебе до збору "
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
        f"🙋 <b>{mention(member_user)}</b> приєднався(-лася) до збору "
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
        lines.append(f"• {mention(member.user)} — {format_money(member.share_kop)}{custom}{mark}")
    if not members:
        lines.append("<i>Поки нікого. Надішли друзям посилання-запрошення.</i>")
    return "\n".join(lines)


def member_pool_card(member: Member) -> str:
    pool = member.pool
    lines = _pool_header(pool)
    lines += [
        f"👑 Власник: {mention(pool.owner)}",
        f"🧮 Твоя частка: <b>{format_money(member.share_kop)}</b>",
        f"💳 Реквізити: {esc(pool.payment_details)}",
    ]
    return "\n".join(lines)


def invite_link(pool: Pool, link: str) -> str:
    return (
        f"🔗 Посилання-запрошення до <b>{esc(pool.title)}</b>:\n\n{link}\n\n"
        "Перешли його тим, хто має скидатися."
    )


# --- платежі -------------------------------------------------------------------

MONTHS = (
    "січень", "лютий", "березень", "квітень", "травень", "червень",
    "липень", "серпень", "вересень", "жовтень", "листопад", "грудень",
)  # fmt: skip
MONTHS_GENITIVE = (
    "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
)  # fmt: skip


def period_name(period: date) -> str:
    return f"{MONTHS[period.month - 1]} {period.year}"


def short_date(moment: datetime) -> str:
    return f"{moment.day} {MONTHS_GENITIVE[moment.month - 1]}"


def _payment_body(payment: Payment) -> str:
    pool = payment.member.pool
    return (
        f"📌 <b>{esc(pool.title)}</b> — {period_name(payment.period)}\n"
        f"💰 Твоя частка: <b>{format_money(payment.amount_kop)}</b>\n"
        f"👑 Отримувач: {mention(pool.owner)}\n"
        f"💳 Реквізити: {esc(pool.payment_details)}"
    )


def payment_request(payment: Payment) -> str:
    return (
        f"Час скинутися 💸\n\n{_payment_body(payment)}\n\n"
        "Коли переведеш гроші, натисни кнопку нижче."
    )


def payment_reminder(payment: Payment) -> str:
    return (
        f"Нагадую 🙂 Схоже, за цей місяць ще не скинуто.\n\n{_payment_body(payment)}\n\n"
        "Якщо вже переказав(-ла), натисни кнопку, щоб власник перевірив."
    )


def payment_claimed_member(payment: Payment) -> str:
    return f"{_payment_body(payment)}\n\n⏳ Дякую! Чекаємо, поки власник підтвердить оплату."


def owner_claim(payment: Payment) -> str:
    member = payment.member
    return (
        f"💸 <b>{mention(member.user)}</b> каже, що скинув(-ла) "
        f"<b>{format_money(payment.amount_kop)}</b> за <b>{esc(member.pool.title)}</b> "
        f"({period_name(payment.period)}).\n\nПеревір надходження і підтверди."
    )


def owner_confirmed(payment: Payment) -> str:
    return f"{owner_claim(payment)}\n\n✅ Підтверджено."


def owner_rejected(payment: Payment) -> str:
    return (
        f"{owner_claim(payment)}\n\n↩️ Ти позначив(-ла), що оплати не видно. Учасника повідомлено."
    )


def member_confirmed(payment: Payment) -> str:
    pool = payment.member.pool
    return (
        f"✅ {mention(pool.owner)} підтвердив(-ла) твою оплату "
        f"{format_money(payment.amount_kop)} за <b>{esc(pool.title)}</b> "
        f"({period_name(payment.period)}). Дякую!"
    )


def member_rejected(payment: Payment) -> str:
    return (
        f"🤔 {mention(payment.member.pool.owner)} поки не бачить твоєї оплати.\n\n"
        f"{_payment_body(payment)}\n\n"
        "Перевір переказ. Якщо все гаразд, натисни кнопку ще раз."
    )


def owner_member_unreachable(payment: Payment) -> str:
    member = payment.member
    return (
        f"⚠️ Не можу написати <b>{mention(member.user)}</b> "
        f"(збір <b>{esc(member.pool.title)}</b>): схоже, бота заблоковано. "
        f"Нагадай, будь ласка, сам(-а): {format_money(payment.amount_kop)} "
        f"за {period_name(payment.period)}."
    )


ALREADY_CLAIMED = "Ти вже позначив(-ла) оплату. Чекаємо підтвердження ⏳"
ALREADY_PAID = "Оплату вже підтверджено ✅"
ALREADY_REJECTED = "Ти вже позначив(-ла), що оплати не видно."


# --- /status -----------------------------------------------------------------

STATUS_NO_POOLS = "У тебе немає зборів, де ти власник. Створи свій через /new."

_STATUS_ICONS = {
    PaymentStatus.PAID: "✅",
    PaymentStatus.CLAIMED: "⏳",
    PaymentStatus.PENDING: "❌",
}


def _status_line(payment: Payment) -> str:
    member = payment.member
    line = (
        f"{_STATUS_ICONS[payment.status]} {mention(member.user)} — "
        f"{format_money(payment.amount_kop)}"
    )
    if payment.status is PaymentStatus.CLAIMED:
        line += " (чекає підтвердження)"
    if not member.is_active:
        line += " · вийшов(-ла) зі збору"
    elif not member.user.is_reachable:
        line += " · ⚠️ бот заблоковано"
    return line


def pool_status(status: PoolStatus) -> str:
    pool = status.pool
    if status.period is None:
        header = f"📌 <b>{esc(pool.title)}</b>"
        body = f"Перше списання {short_date(status.next_billing)}."
    else:
        header = f"📌 <b>{esc(pool.title)}</b> — {period_name(status.period)}"
        lines = [_status_line(p) for p in status.payments]
        lines += [
            f"🆕 {mention(m.user)} — платить з наступного місяця" for m in status.not_billed_yet
        ]
        if not lines:
            lines.append("<i>Цього місяця платежів немає.</i>")
        if status.payments:
            lines.append(
                f"\nЗібрано: {format_money(status.paid_kop)} з {format_money(status.expected_kop)}"
            )
        body = "\n".join(lines)
    if pool.is_paused:
        header += "\n⏸ <i>на паузі</i>"
    return f"{header}\n{body}"


def statuses(items: Sequence[PoolStatus]) -> str:
    return "\n\n".join(pool_status(s) for s in items)


# --- керування збором (власник) ------------------------------------------------

SAVED = "Збережено ✅"
EDIT_HINT = "\n\nСкасувати: /cancel або кнопка нижче."
EXPECT_TEXT_INPUT = "Надішли нове значення текстом або натисни /cancel."
EDIT_SESSION_EXPIRED = "Ця дія вже неактуальна. Відкрий збір ще раз: /my"
NEXT_CYCLE_NOTE = "Діє з наступного списання: уже виставлені платежі не змінюються."


def ask_new_amount(pool: Pool) -> str:
    return (
        f"Зараз загальна сума <b>{esc(pool.title)}</b>: {format_money(pool.total_amount_kop)}.\n"
        f"Напиши нову суму на місяць у гривнях.\n<i>{NEXT_CYCLE_NOTE}</i>{EDIT_HINT}"
    )


def ask_new_day(pool: Pool) -> str:
    return (
        f"Зараз списання {billing_day_text(pool.billing_day)}.\n"
        f"Напиши новий день від 1 до 31.{EDIT_HINT}"
    )


def ask_new_details(pool: Pool) -> str:
    return f"Зараз реквізити: {esc(pool.payment_details)}\n\nНадішли нові реквізити.{EDIT_HINT}"


def ask_member_share(pool: Pool, member: Member) -> str:
    return (
        f"Частка <b>{mention(member.user)}</b> зараз {format_money(member.share_kop)} "
        f"із {format_money(pool.total_amount_kop)}.\n"
        "Напиши нову частку в гривнях. Решта суми поділиться між іншими автоматично.\n"
        f"<i>{NEXT_CYCLE_NOTE}</i>{EDIT_HINT}"
    )


def members_list(pool: Pool, members: Sequence[Member]) -> str:
    if not members:
        return f"У зборі <b>{esc(pool.title)}</b> поки немає учасників."
    return (
        f"<b>Учасники {esc(pool.title)}</b>\n"
        "✏️ — частка задана вручну. Обери учасника, щоб змінити частку або видалити:"
    )


def member_card(member: Member) -> str:
    custom = " (задана вручну ✏️)" if member.share_is_custom else " (автоматично)"
    reach = "" if member.user.is_reachable else "\n⚠️ Бот заблоковано: повідомлення не доходять."
    return (
        f"🙋 <b>{mention(member.user)}</b>\n"
        f"🧮 Частка: {format_money(member.share_kop)}{custom}{reach}"
    )


def confirm_remove_member(member: Member) -> str:
    return (
        f"Видалити <b>{mention(member.user)}</b> зі збору "
        f"<b>{esc(member.pool.title)}</b>?\n"
        "Його частку буде розподілено між іншими з наступного списання."
    )


def confirm_delete(pool: Pool) -> str:
    return (
        f"Точно видалити збір <b>{esc(pool.title)}</b>? 🗑\n\n"
        "Усі учасники отримають сповіщення, а історію платежів буде видалено. "
        "Скасувати це не можна."
    )


def pool_deleted(title: str) -> str:
    return f"Збір <b>{esc(title)}</b> видалено."


# Спливаючі вікна (callback alert): без HTML і не довші за 200 символів
PAUSED_ALERT = (
    "⏸ Збір на паузі. Нових платежів і нагадувань не буде, поки не відновиш. Учасників повідомлено."
)


def resumed_alert(next_billing: datetime) -> str:
    return (
        f"▶️ Збір відновлено. Наступне списання {short_date(next_billing)}. Учасників повідомлено."
    )


def invite_regenerated(pool: Pool, link: str) -> str:
    return f"Старе посилання більше не працює.\n\n{invite_link(pool, link)}"


def custom_shares_reset_note() -> str:
    return "\n\n⚠️ Ручні частки більше не вміщалися в нову суму, тому їх скинуто на автоматичні."


MARKED_PAID_ALERT = "Позначено оплаченим ✅ Учасника повідомлено."
NO_UNPAID = "Усі платежі цього збору вже підтверджено ✅"


def unpaid_list(pool: Pool) -> str:
    return (
        f"<b>Неоплачені платежі {esc(pool.title)}</b>\n"
        "Натисни на платіж, щоб позначити його оплаченим (наприклад, якщо віддали готівкою)."
    )


def unpaid_button(payment: Payment) -> str:
    icon = _STATUS_ICONS[payment.status]
    return (
        f"{icon} {plain_name(payment.member.user)} — {format_money(payment.amount_kop)} "
        f"({MONTHS[payment.period.month - 1]})"
    )


def marked_paid_owner(payment: Payment) -> str:
    return (
        f"✅ Позначено оплаченим: {mention(payment.member.user)} — "
        f"{format_money(payment.amount_kop)} ({period_name(payment.period)})."
    )


# --- сповіщення учасникам про дії власника -------------------------------------


def member_share_changed(pool: Pool, old_kop: int, new_kop: int) -> str:
    return (
        f"🧮 У зборі <b>{esc(pool.title)}</b> змінився розподіл: твоя частка тепер "
        f"<b>{format_money(new_kop)}</b> (було {format_money(old_kop)}).\n{NEXT_CYCLE_NOTE}"
    )


def member_day_changed(pool: Pool) -> str:
    return (
        f"📅 У зборі <b>{esc(pool.title)}</b> новий день списання: "
        f"{billing_day_text(pool.billing_day)}."
    )


def member_details_changed(pool: Pool) -> str:
    return (
        f"💳 У зборі <b>{esc(pool.title)}</b> нові реквізити для оплати:\n"
        f"{esc(pool.payment_details)}"
    )


def member_removed(pool: Pool) -> str:
    return (
        f"Власник видалив тебе зі збору <b>{esc(pool.title)}</b>. "
        "Нагадувань про нього більше не буде."
    )


def member_pool_paused(pool: Pool) -> str:
    return f"⏸ Збір <b>{esc(pool.title)}</b> поставлено на паузу. Поки що нічого скидати не треба."


def member_pool_resumed(pool: Pool, next_billing: datetime) -> str:
    return (
        f"▶️ Збір <b>{esc(pool.title)}</b> знову активний. "
        f"Наступне списання {short_date(next_billing)}."
    )


def member_pool_deleted(title: str) -> str:
    return f"🗑 Власник видалив збір <b>{esc(title)}</b>. Більше нагадувань про нього не буде."


def member_marked_paid(payment: Payment) -> str:
    pool = payment.member.pool
    return (
        f"✅ {mention(pool.owner)} позначив(-ла) твою оплату "
        f"{format_money(payment.amount_kop)} за <b>{esc(pool.title)}</b> "
        f"({period_name(payment.period)}) як отриману. Дякую!"
    )


# --- дії учасника ----------------------------------------------------------------


def confirm_leave(pool: Pool) -> str:
    return (
        f"Вийти зі збору <b>{esc(pool.title)}</b>?\n"
        "Власник отримає сповіщення, а нагадування припиняться."
    )


def left_pool(pool: Pool) -> str:
    return f"Ти вийшов(-ла) зі збору <b>{esc(pool.title)}</b> 👋"


def owner_member_left(pool: Pool, member: Member) -> str:
    return (
        f"🚪 <b>{mention(member.user)}</b> вийшов(-ла) зі збору "
        f"<b>{esc(pool.title)}</b>. Частки перераховано. {NEXT_CYCLE_NOTE}"
    )


_HISTORY_STATUS = {
    PaymentStatus.PAID: "✅ оплачено",
    PaymentStatus.CLAIMED: "⏳ чекає підтвердження",
    PaymentStatus.PENDING: "❌ не оплачено",
}


def payment_history(member: Member, payments: Sequence[Payment]) -> str:
    header = f"📜 <b>Історія платежів: {esc(member.pool.title)}</b>"
    if not payments:
        return f"{header}\n\nПлатежів ще не було."
    lines = [
        f"{period_name(p.period)} — {format_money(p.amount_kop)} · {_HISTORY_STATUS[p.status]}"
        for p in payments
    ]
    return header + "\n\n" + "\n".join(lines)
