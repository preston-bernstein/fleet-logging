"""Tests for `fleet_logging.config.load_config`."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
import yaml

from fleet_logging.config import ConfigError, load_config


@dataclass
class SampleConfig:
    db_path: str = "data/db.sqlite"
    review_min_days: int = 7
    verbose: bool = False
    symbol_universe: list[str] = field(default_factory=list)


class TestMissingFile:
    def test_non_fatal_by_default_falls_back_to_defaults(self, tmp_path):
        cfg = load_config(SampleConfig, tmp_path / "does-not-exist.yaml")
        assert cfg == SampleConfig()

    def test_required_true_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(SampleConfig, tmp_path / "nope.yaml", required=True)

    def test_no_path_at_all_uses_defaults(self):
        cfg = load_config(SampleConfig)
        assert cfg == SampleConfig()


class TestYamlOverlay:
    def test_yaml_values_override_defaults(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("db_path: /srv/real.db\nreview_min_days: 14\n")
        cfg = load_config(SampleConfig, cfg_file)
        assert cfg.db_path == "/srv/real.db"
        assert cfg.review_min_days == 14

    def test_yaml_list_field(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("symbol_universe: [AAPL, MSFT]\n")
        cfg = load_config(SampleConfig, cfg_file)
        assert cfg.symbol_universe == ["AAPL", "MSFT"]

    def test_malformed_yaml_raises(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("db_path: [unterminated\n")
        with pytest.raises(yaml.YAMLError):
            load_config(SampleConfig, cfg_file)


class TestEnvOverride:
    def test_env_var_overrides_yaml(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("review_min_days: 14\n")
        monkeypatch.setenv("REVIEW_MIN_DAYS", "30")
        cfg = load_config(SampleConfig, cfg_file)
        assert cfg.review_min_days == 30

    def test_env_var_coerces_bool(self, monkeypatch):
        monkeypatch.setenv("VERBOSE", "true")
        cfg = load_config(SampleConfig)
        assert cfg.verbose is True

    def test_env_var_coerces_list(self, monkeypatch):
        monkeypatch.setenv("SYMBOL_UNIVERSE", "AAPL, MSFT, TSLA")
        cfg = load_config(SampleConfig)
        assert cfg.symbol_universe == ["AAPL", "MSFT", "TSLA"]

    def test_env_prefix(self, monkeypatch):
        monkeypatch.setenv("MYAPP_REVIEW_MIN_DAYS", "3")
        cfg = load_config(SampleConfig, env_prefix="MYAPP_")
        assert cfg.review_min_days == 3

    def test_bad_int_raises_config_error(self, monkeypatch):
        monkeypatch.setenv("REVIEW_MIN_DAYS", "not-a-number")
        with pytest.raises(ConfigError):
            load_config(SampleConfig)


class TestNotADataclass:
    def test_raises_type_error(self):
        class NotADataclass:
            pass

        with pytest.raises(TypeError):
            load_config(NotADataclass)
