from bot import texts
from bot.db.models import User


def user(first_name: str, username: str | None, telegram_id: int = 42) -> User:
    return User(telegram_id=telegram_id, username=username, first_name=first_name)


def test_mention_with_username_links_to_chat() -> None:
    assert texts.mention(user("Тимофей", "tim_k")) == (
        '<a href="https://t.me/tim_k">Тимофей</a> (@tim_k)'
    )


def test_mention_without_first_name_does_not_duplicate_username() -> None:
    assert texts.mention(user("", "tim_k")) == '<a href="https://t.me/tim_k">@tim_k</a>'


def test_mention_without_username_links_to_profile_by_id() -> None:
    assert texts.mention(user("Оля", None, 777)) == '<a href="tg://user?id=777">Оля</a>'


def test_mention_escapes_html_in_name() -> None:
    assert "&lt;b&gt;" in texts.mention(user("<b>хакер</b>", None))


def test_plain_name_for_buttons() -> None:
    assert texts.plain_name(user(".", "dot_guy")) == ". @dot_guy"
    assert texts.plain_name(user("Оля", None)) == "Оля"
    assert texts.plain_name(user("", "tim_k")) == "@tim_k"
