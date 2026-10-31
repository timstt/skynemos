import pytest

from bot.services.shares import ShareInput, compute_shares


def auto(*ids: int) -> list[ShareInput]:
    return [ShareInput(i) for i in ids]


def test_equal_split_with_owner() -> None:
    plan = compute_shares(30_000, True, auto(1, 2, 3, 4))
    assert plan.owner_share_kop == 6_000
    assert plan.member_shares == {1: 6_000, 2: 6_000, 3: 6_000, 4: 6_000}


def test_equal_split_without_owner() -> None:
    plan = compute_shares(30_000, False, auto(1, 2, 3))
    assert plan.owner_share_kop == 0
    assert plan.member_shares == {1: 10_000, 2: 10_000, 3: 10_000}


def test_remainder_goes_to_owner_when_included() -> None:
    plan = compute_shares(10_000, True, auto(1, 2))  # 100 грн на трьох
    assert plan.member_shares == {1: 3_333, 2: 3_333}
    assert plan.owner_share_kop == 3_334


def test_remainder_goes_to_first_member_without_owner() -> None:
    plan = compute_shares(10_000, False, auto(7, 3, 5))
    assert plan.member_shares == {7: 3_334, 3: 3_333, 5: 3_333}
    assert plan.owner_share_kop == 0


def test_owner_alone_pays_everything() -> None:
    assert compute_shares(30_000, True, []).owner_share_kop == 30_000
    # Власник не в розподілі, але учасників немає: невкрита сума на ньому
    assert compute_shares(30_000, False, []).owner_share_kop == 30_000


def test_custom_shares_are_kept() -> None:
    members = [ShareInput(1, custom_share_kop=5_000), *auto(2, 3)]
    plan = compute_shares(30_000, True, members)
    assert plan.member_shares[1] == 5_000
    # Решта 250 грн порівну між власником та двома учасниками
    assert plan.member_shares[2] == plan.member_shares[3] == 8_333
    assert plan.owner_share_kop == 8_334
    assert plan.custom_reset is False


def test_all_custom_without_owner_leaves_rest_on_owner() -> None:
    members = [ShareInput(1, 10_000), ShareInput(2, 5_000)]
    plan = compute_shares(30_000, False, members)
    assert plan.member_shares == {1: 10_000, 2: 5_000}
    assert plan.owner_share_kop == 15_000


def test_custom_shares_exceeding_total_are_reset() -> None:
    members = [ShareInput(1, 20_000), ShareInput(2, 20_000)]
    plan = compute_shares(30_000, False, members)
    assert plan.custom_reset is True
    assert plan.member_shares == {1: 15_000, 2: 15_000}


def test_one_kopeck_split() -> None:
    plan = compute_shares(1, True, auto(1, 2))
    assert plan.member_shares == {1: 0, 2: 0}
    assert plan.owner_share_kop == 1


@pytest.mark.parametrize("total", [1, 99, 10_000, 30_001, 9_999_999])
@pytest.mark.parametrize("include_owner", [True, False])
@pytest.mark.parametrize("n", [0, 1, 3, 7, 10])
def test_sum_always_equals_total(total: int, include_owner: bool, n: int) -> None:
    plan = compute_shares(total, include_owner, auto(*range(1, n + 1)))
    assert plan.total_kop == total
    shares = list(plan.member_shares.values())
    if include_owner:
        shares.append(plan.owner_share_kop)
    if shares:
        # Весь залишок (< кількості учасників) іде одній людині, решта рівні
        assert max(shares) - min(shares) < len(shares)
        assert sorted(shares)[:-1] == [min(shares)] * (len(shares) - 1)


def test_rejects_non_positive_total() -> None:
    with pytest.raises(ValueError):
        compute_shares(0, True, [])
