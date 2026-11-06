"""英雄包奖励偏好：数据只落在英雄包，核心层不认识具体名字。"""

from lorwright.champions import available, load

PREFERENCE_ATTRS = (
    "relic_preferences",
    "item_preferences",
    "spell_preferences",
    "power_preferences",
)


def test_all_packs_expose_reward_preferences() -> None:
    for name in available():
        pack = load(name)
        for attr in PREFERENCE_ATTRS:
            prefs = getattr(pack, attr)
            assert isinstance(prefs, tuple), (name, attr)
            for pref in prefs:
                assert pref.names, (name, attr)
                assert pref.note, (name, attr)


def test_jinx_prefers_shadow_totem_and_stabilize() -> None:
    pack = load("jinx")
    assert pack.relic_preferences[0].names == ("Shadow Totem", "闇影圖騰")
    assert pack.power_preferences[0].names == ("Stabilize", "分身術")


def test_elise_top_relic_is_heavy_hands() -> None:
    pack = load("elise")
    assert pack.relic_preferences[0].names == ("Heavy Hands", "重拳出擊")
