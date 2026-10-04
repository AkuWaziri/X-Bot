    posts = provider.get_latest_posts("alice", limit=1)
    assert len(posts) == 1
    assert posts[0].id == "original"


def test_monitored_pool_randomizes_full_account_list():
    accounts = [f"@user{i}" for i in range(20)]
    selected = _select_handles(accounts)

    assert len(selected) == 20
    assert set(selected) == set(accounts)
    assert MONITORED_HANDLES_PER_RUN == 17


def test_monitored_handles_randomly_change_between_schedules():
    from bot.monitor import _select_rotating_handles

    accounts = [f"@user{i:02d}" for i in range(20)]
    db = IntegrationDB()

    first = _select_rotating_handles(db, accounts)
    second = _select_rotating_handles(db, accounts)
    third = _select_rotating_handles(db, accounts)

    assert len(first) == 17
    assert len(second) == 17
    assert len(third) == 17
    assert set(first) != set(second)
    assert set(second) != set(third)
    assert set(first + second) == set(accounts)


def test_monitored_handle_selection_uses_random_sample(monkeypatch):
    from bot.monitor import _select_rotating_handles

    accounts = [f"@user{i:02d}" for i in range(20)]
    db = IntegrationDB()
    calls = []

    def fake_sample(pool, count):
        calls.append((list(pool), count))
        return list(pool)[:count]

    monkeypatch.setattr("bot.monitor.random.sample", fake_sample)
