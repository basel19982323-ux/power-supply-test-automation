"""Config save/load round-trip."""
import testtypes
from core import config as configmod


def test_config_roundtrip(tmp_path):
    t = testtypes.default_test()
    cfg = t.default_config()
    path = str(tmp_path / "cfg.yaml")
    configmod.save_config(cfg, path)
    assert configmod.load_config(path) == cfg


def test_list_configs_finds_default():
    # the shipped default config should be discoverable
    names = [n for n, _ in configmod.list_configs()]
    assert any("dynamic_output_response" in n for n in names)
