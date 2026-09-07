"""Tests for Simplified Chinese team-name mapping."""

from socceran.names import load_team_name_map, normalize_key, to_zh


def test_to_zh_arsenal():
    assert to_zh("Arsenal") == "阿森纳"


def test_aliases_manchester_united():
    assert to_zh("Man United") == "曼联"
    assert to_zh("Manchester United") == "曼联"
    assert to_zh("Manchester United FC") == "曼联"
    assert to_zh("Man Utd") == "曼联"


def test_aliases_arsenal_fc():
    assert to_zh("FC Arsenal") == "阿森纳"
    assert to_zh("Arsenal FC") == "阿森纳"
    assert to_zh("arsenal") == "阿森纳"


def test_bundesliga_umlauts():
    assert to_zh("Bayern München") == "拜仁慕尼黑"
    assert to_zh("Bayern Munich") == "拜仁慕尼黑"
    assert to_zh("VfB Stuttgart") == "斯图加特"
    assert to_zh("Mainz") == "美因茨"
    assert to_zh("Hamburg") == "汉堡"


def test_common_big_five():
    assert to_zh("Manchester City") == "曼城"
    assert to_zh("Man City") == "曼城"
    assert to_zh("Chelsea") == "切尔西"
    assert to_zh("Everton") == "埃弗顿"
    assert to_zh("Coventry City") == "考文垂"
    assert to_zh("Barcelona") == "巴萨"
    assert to_zh("Real Madrid") == "皇马"
    assert to_zh("Inter") == "国米"
    assert to_zh("Juventus") == "尤文"
    assert to_zh("Paris SG") == "巴黎圣日耳曼"
    assert to_zh("PSG") == "巴黎圣日耳曼"


def test_unknown_passthrough():
    assert to_zh("Unknown FC United of Somewhere") == "Unknown FC United of Somewhere"
    assert to_zh("ZZZ Not A Team") == "ZZZ Not A Team"


def test_normalize_key_strips_suffix():
    assert normalize_key("Arsenal FC") == normalize_key("Arsenal")
    assert normalize_key("AFC Bournemouth") == normalize_key("Bournemouth")
    assert "fc" not in normalize_key("Liverpool FC")


def test_map_nonempty():
    m = load_team_name_map()
    assert len(m) >= 100
    assert m["Arsenal"] == "阿森纳"
