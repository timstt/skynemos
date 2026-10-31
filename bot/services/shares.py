"""Розподіл загальної суми збору між власником і учасниками. Чиста логіка, без БД."""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ShareInput:
    member_id: int
    custom_share_kop: int | None = None  # None — частка рахується автоматично


@dataclass(frozen=True, slots=True)
class SharePlan:
    owner_share_kop: int
    member_shares: dict[int, int]
    # True, якщо ручні частки довелося скинути (їхня сума перевищила загальну)
    custom_reset: bool = False

    @property
    def total_kop(self) -> int:
        return self.owner_share_kop + sum(self.member_shares.values())


def compute_shares(total_kop: int, include_owner: bool, members: Sequence[ShareInput]) -> SharePlan:
    """Ділить `total_kop` між власником (якщо `include_owner`) та учасниками.

    Правила:
    * ручні частки (`custom_share_kop`) лишаються як є, решта ділиться порівну
      між власником (якщо включений) та учасниками без ручної частки;
    * залишок у копійках, що не ділиться порівну, іде власнику (якщо включений),
      інакше першому учаснику з автоматичною часткою;
    * якщо ділити нема між ким, невкриту суму несе власник;
    * якщо ручні частки разом більші за загальну суму, вони скидаються.

    Інваріант: owner_share_kop + Σ member_shares == total_kop.
    """
    if total_kop <= 0:
        raise ValueError("total_kop must be positive")

    custom_sum = sum(m.custom_share_kop or 0 for m in members)
    custom_reset = custom_sum > total_kop
    if custom_reset:
        members = [ShareInput(m.member_id) for m in members]
        custom_sum = 0

    shares: dict[int, int] = {
        m.member_id: m.custom_share_kop for m in members if m.custom_share_kop is not None
    }
    auto_members = [m.member_id for m in members if m.custom_share_kop is None]
    remaining = total_kop - custom_sum

    participants = len(auto_members) + (1 if include_owner else 0)
    if participants == 0:
        # Усі учасники з ручними частками, власник не в розподілі: решту покриває власник
        return SharePlan(remaining, shares, custom_reset)

    base, remainder = divmod(remaining, participants)
    owner_share = base if include_owner else 0
    for member_id in auto_members:
        shares[member_id] = base

    if include_owner:
        owner_share += remainder
    else:
        shares[auto_members[0]] += remainder

    plan = SharePlan(owner_share, shares, custom_reset)
    assert plan.total_kop == total_kop
    return plan
