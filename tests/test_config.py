import os
from decimal import Decimal

import pytest

from ventas.config import REQUERIDAS, ConfigError, Settings, cargar

BASE = {
    "BEDROCK_API_KEY": "bk", "BEDROCK_MODEL": "nvidia.nemotron-nano-3-30b",
    "NVIDIA_API_KEY": "nv", "GOOGLE_API_KEY": "gg", "NIM_MODEL": "meta/llama-3.3-70b-instruct",
    "GEMINI_MODEL": "gemini-x", "DATABASE_URL": "postgresql://rw", "DATABASE_URL_RO": "postgresql://ro",
}


def test_defaults():
    s = Settings.from_env(BASE)
    assert s.tasa_impuesto == Decimal("0.16")
    assert s.nim_timeout == 20.0
    assert s.nim_model == "meta/llama-3.3-70b-instruct"


def test_sqlite_no_necesita_url_de_solo_lectura():
    env = {k: v for k, v in BASE.items() if k != "DATABASE_URL_RO"} | {"DATABASE_URL": "sqlite:///demo.db"}
    s = Settings.from_env(env)
    assert s.database_url == s.database_url_ro == "sqlite:///demo.db"


def test_postgres_sigue_exigiendo_url_de_solo_lectura():
    with pytest.raises(ConfigError, match="DATABASE_URL_RO"):
        Settings.from_env({k: v for k, v in BASE.items() if k != "DATABASE_URL_RO"})


def test_faltan_variables_las_nombra_todas():
    env = {k: v for k, v in BASE.items() if k not in ("NIM_MODEL", "GOOGLE_API_KEY")}
    with pytest.raises(ConfigError) as e:
        Settings.from_env(env)
    assert "NIM_MODEL" in str(e.value) and "GOOGLE_API_KEY" in str(e.value)


def test_variable_en_blanco_cuenta_como_faltante():
    with pytest.raises(ConfigError, match="GEMINI_MODEL"):
        Settings.from_env({**BASE, "GEMINI_MODEL": "   "})


@pytest.mark.parametrize("tasa", ["abc", "-0.1", "1", "1.5"])
def test_tasa_invalida(tasa):
    with pytest.raises(ConfigError, match="TASA_IMPUESTO"):
        Settings.from_env({**BASE, "TASA_IMPUESTO": tasa})


def test_tasa_y_timeout_personalizados():
    s = Settings.from_env({**BASE, "TASA_IMPUESTO": "0.10", "NIM_TIMEOUT": "5"})
    assert s.tasa_impuesto == Decimal("0.10") and s.nim_timeout == 5.0


def test_timeout_invalido():
    with pytest.raises(ConfigError, match="NIM_TIMEOUT"):
        Settings.from_env({**BASE, "NIM_TIMEOUT": "rápido"})


def test_cargar_no_hereda_variables_de_env_ajenos(tmp_path, monkeypatch):
    # el proyecto vive dentro de otro directorio con su propio .env (aquí sí existe uno): solo cuenta el del cwd
    (tmp_path / ".env").write_text("\n".join(f"{k}=v" for k in REQUERIDAS if k != "BEDROCK_API_KEY") + "\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(os, "environ", {})
    with pytest.raises(ConfigError) as e:
        cargar()
    assert "BEDROCK_API_KEY" in str(e.value)


def test_cargar_lee_el_env_del_directorio_actual(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("\n".join(f"{k}=v" for k in REQUERIDAS) + "\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(os, "environ", {})
    assert cargar().nim_model == "v"
