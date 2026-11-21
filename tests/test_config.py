"""Tests for `fleet_logging.config.load_config`."""

from __future__ import annotations

import json
import typing
from dataclasses import dataclass, field, make_dataclass

import pytest
import yaml

from fleet_logging.config import ConfigError, load_config


class TestConfigErrorReExport:
    def test_config_error_importable_from_package_root(self):
        """ConfigError is a raised part of load_config's public contract, so
        it must be reachable via `from fleet_logging import ConfigError`,
        not only via the `fleet_logging.config` submodule."""
        import fleet_logging

        assert fleet_logging.ConfigError is ConfigError


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


@dataclass
class TypedConfig:
    ratio: float = 0.5
    limit: int | None = None
    tags: list[str] = field(default_factory=list)
    label: str = "x"
    enabled: bool = False


OptionalConfig = make_dataclass(
    "OptionalConfig", [("limit", typing.Optional.__getitem__(int), field(default=None))]
)


@dataclass
class RequiredConfig:
    name: str


class TestCoercionCharacterization:
    def test_float_optional_int_list_and_str(self, monkeypatch):
        monkeypatch.setenv("RATIO", "1.25")
        monkeypatch.setenv("LIMIT", "9")
        monkeypatch.setenv("TAGS", "a, b,,c")
        monkeypatch.setenv("LABEL", "hello")
        cfg = load_config(TypedConfig)
        # `int | None` (PEP 604) is unwrapped on every supported Python.
        assert cfg == TypedConfig(ratio=1.25, limit=9, tags=["a", "b", "c"], label="hello")

    def test_typing_optional_is_unwrapped(self, monkeypatch):
        monkeypatch.setenv("LIMIT", "9")
        assert load_config(OptionalConfig).limit == 9

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("YES", True), (" On ", True), ("1", True), ("off", False), ("0", False), ("No", False)],
    )
    def test_bool_spellings(self, monkeypatch, raw, expected):
        monkeypatch.setenv("ENABLED", raw)
        assert load_config(TypedConfig).enabled is expected

    def test_bad_bool_message(self, monkeypatch):
        monkeypatch.setenv("ENABLED", "maybe")
        with pytest.raises(ConfigError) as err:
            load_config(TypedConfig)
        assert "env override for field 'enabled' ('maybe')" in str(err.value)
        assert "'maybe' is not a recognized boolean" in str(err.value)

    def test_bad_float_raises_config_error(self, monkeypatch):
        monkeypatch.setenv("RATIO", "abc")
        with pytest.raises(ConfigError, match="could not be coerced to <class 'float'>"):
            load_config(TypedConfig)


class TestFieldResolutionCharacterization:
    def test_missing_required_field_names_path(self, tmp_path):
        path = tmp_path / "c.yaml"
        path.write_text("other: 1\n")
        with pytest.raises(ConfigError, match="field 'name' has no default") as err:
            load_config(RequiredConfig, path)
        assert repr(path) in str(err.value)

    def test_yaml_null_falls_back_to_default(self, tmp_path):
        path = tmp_path / "c.yaml"
        path.write_text("label: null\n")
        assert load_config(TypedConfig, path).label == "x"

    def test_empty_yaml_file_uses_defaults(self, tmp_path):
        path = tmp_path / "c.yaml"
        path.write_text("")
        assert load_config(TypedConfig, path) == TypedConfig()

    def test_required_error_message(self, tmp_path):
        path = tmp_path / "gone.yaml"
        with pytest.raises(FileNotFoundError, match="missing and required=True"):
            load_config(TypedConfig, path, required=True)

    def test_missing_file_warns_with_service(self, tmp_path, capsys):
        path = tmp_path / "gone.yaml"
        load_config(TypedConfig, path, service="svc")
        line = json.loads(capsys.readouterr().out.strip())
        assert line["event"] == "config.missing"
        assert line["level"] == "warn"
        assert line["service"] == "svc"
        assert line["path"] == str(path.resolve())

    def test_parse_failure_logs_then_raises(self, tmp_path, capsys):
        path = tmp_path / "bad.yaml"
        path.write_text("a: [1, 2\n")
        with pytest.raises(yaml.YAMLError):
            load_config(TypedConfig, path, service="svc")
        line = json.loads(capsys.readouterr().out.strip())
        assert line["event"] == "config.parse_failed"
        assert line["level"] == "error"
        assert line["err_type"] == "ParserError"
        assert line["path"] == str(path.resolve())
