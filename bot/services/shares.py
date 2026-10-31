"""Розподіл загальної суми збору між власником і учасниками. Чиста логіка, без БД."""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ShareInput:
    member_id: int
    custom_share_kop: int | None = None  # None — частка рахується автоматично
    weight: int = 1  # кількість «часток» (родина з двох = 2); ігнорується для ручної


@dataclass(frozen=True, slots=True)
class SharePlan:
    owner_share_kop: int
    member_shares: dict[int, int]
    # True, якщо ручні частки довелося скинути (їхня сума перевищила загальну)
    custom_reset: bool = False

    @property
    def total_kop(self) -> int:
        return self.owner_share_kop + sum(self.member_shares.values())


def compute_shares(
    total_kop: int,
    include_owner: bool,
    members: Sequence[ShareInput],
    *,
    owner_weight: int = 1,
) -> SharePlan:
    """Ділить `total_kop` між власником (якщо `include_owner`) та учасниками.

    Правила:
    * ручні частки (`custom_share_kop`) лишаються як є, решта ділиться пропорційно
      вагам між власником (якщо включений) та учасниками без ручної частки;
      за однакових ваг (за замовчуванням 1) це звичайний поділ порівну;
    * залишок у копійках, що не ділиться, іде власнику (якщо включений),
      інакше першому учаснику з автоматичною часткою;
    * якщо ділити нема між ким, невкриту суму несе власник;
    * якщо ручні частки разом більші за загальну суму, вони скидаються.

    Інваріант: owner_share_kop + Σ member_shares == total_kop.
    """
    if total_kop <= 0:
        raise ValueError("total_kop must be positive")
    if owner_weight < 1 or any(m.weight < 1 for m in members):
        raise ValueError("weights must be >= 1")

    custom_sum = sum(m.custom_share_kop or 0 for m in members)
    custom_reset = custom_sum > total_kop
    if custom_reset:
        members = [ShareInput(m.member_id, weight=m.weight) for m in members]
        custom_sum = 0

    shares: dict[int, int] = {
        m.member_id: m.custom_share_kop for m in members if m.custom_share_kop is not None
    }
    auto_members = [m for m in members if m.custom_share_kop is None]
    remaining = total_kop - custom_sum

    total_weight = sum(m.weight for m in auto_members) + (owner_weight if include_owner else 0)
    if total_weight == 0:
        # Усі учасники з ручними частками, власник не в розподілі: решту покриває власник
        return SharePlan(remaining, shares, custom_reset)

    # Пропорційно вагам з округленням донизу; залишок — за правилом вище
    for member in auto_members:
        shares[member.member_id] = remaining * member.weight // total_weight
    owner_share = remaining * owner_weight // total_weight if include_owner else 0
    leftover = remaining - owner_share - sum(shares[m.member_id] for m in auto_members)

    if include_owner:
        owner_share += leftover
    else:
        shares[auto_members[0].member_id] += leftover

    plan = SharePlan(owner_share, shares, custom_reset)
    assert plan.total_kop == total_kop
    return plan
