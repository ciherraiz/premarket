"""
Tests para el indicador Net GEX (IND-03 e IND-04).

Cubre:
  1. Flip Level — detección y scoring
  2. Put Wall / Call Wall
  3. Max Pain (solo cadena 0DTE)
  4. Scoring del Net GEX (score_gex) — umbrales 15B / 5B
  5. Casos de error
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.calculate_indicators import calc_net_gex


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = "2026-03-30"


def _make_contract(strike, option_type, oi, gamma=None, expiry=TODAY):
    return {
        "strike":        strike,
        "option_type":   option_type,  # "C" o "P"
        "open_interest": oi,
        "gamma":         gamma,
        "expiry":        expiry,
    }


def _make_chain(contracts, status="OK"):
    expiries = list({c["expiry"] for c in contracts})
    return {
        "contracts":   contracts,
        "expiries":    expiries,
        "n_contracts": len(contracts),
        "status":      status,
    }


def _empty_chain():
    return {"contracts": [], "expiries": [], "n_contracts": 0, "status": "EMPTY_CHAIN"}


# ---------------------------------------------------------------------------
# Grupo 1: Flip Level
# ---------------------------------------------------------------------------


def test_flip_level_detectado():
    """
    Puts concentradas en 5100, calls en 5300 → el GEX acumulado cruza de
    negativo a positivo → flip_level detectado en 5200 o 5300.
    """
    spot = 5250.0
    contracts = [
        _make_contract(5100, "P", oi=5000, gamma=0.002),
        _make_contract(5200, "C", oi=1000, gamma=0.001),
        _make_contract(5300, "C", oi=8000, gamma=0.002),
    ]
    chain = _make_chain(contracts)
    result = calc_net_gex(chain, chain, spot=spot, fecha=TODAY)

    assert result["status"] == "OK"
    assert result["flip_level"] is not None
    assert result["flip_level"] in [5200, 5300]


def test_flip_level_no_existe_todo_positivo():
    """Solo calls con GEX positivo → acumulado nunca negativo → flip_level=None, score_flip=0"""
    spot = 5200.0
    contracts = [
        _make_contract(5100, "C", oi=1000, gamma=0.001),
        _make_contract(5200, "C", oi=2000, gamma=0.001),
        _make_contract(5300, "C", oi=1500, gamma=0.001),
    ]
    chain = _make_chain(contracts)
    result = calc_net_gex(chain, chain, spot=spot, fecha=TODAY)

    assert result["flip_level"] is None
    assert result["score_flip"] == 0
    assert result["signal_flip"] == "SIN_FLIP"


def test_flip_level_spot_bajo():
    """Flip detectado pero spot < flip_level → score_flip=-2, signal=BAJO_FLIP"""
    spot = 5100.0
    contracts = [
        _make_contract(5000, "P", oi=5000, gamma=0.002),
        _make_contract(5200, "C", oi=8000, gamma=0.002),
        _make_contract(5300, "C", oi=3000, gamma=0.001),
    ]
    chain = _make_chain(contracts)
    result = calc_net_gex(chain, chain, spot=spot, fecha=TODAY)

    assert result["flip_level"] is not None
    assert result["score_flip"] == -2
    assert result["signal_flip"] == "BAJO_FLIP"


# ---------------------------------------------------------------------------
# Grupo 2: Put Wall / Call Wall
# ---------------------------------------------------------------------------


def test_put_wall_call_wall():
    """
    Concentración de puts en 5100 y calls en 5400 →
    put_wall=5100, call_wall=5400.
    """
    spot = 5250.0
    contracts = [
        _make_contract(5100, "P", oi=10000, gamma=0.003),  # put wall
        _make_contract(5200, "P", oi=1000,  gamma=0.001),
        _make_contract(5200, "C", oi=1000,  gamma=0.001),
        _make_contract(5400, "C", oi=10000, gamma=0.003),  # call wall
    ]
    chain = _make_chain(contracts)
    result = calc_net_gex(chain, chain, spot=spot, fecha=TODAY)

    assert result["put_wall"]  == 5100
    assert result["call_wall"] == 5400


# ---------------------------------------------------------------------------
# Grupo 3: Max Pain
# ---------------------------------------------------------------------------


def test_max_pain_calculado():
    """
    Cadena 0DTE sencilla — el max pain minimiza el valor intrínseco total.

    Strikes: 5100C(OI=100), 5200C(OI=200), 5200P(OI=200), 5300P(OI=100)
    Para precio_final=5200:
        calls 5100 ITM → 100×100×100 = 1_000_000
        puts  5300 ITM → 100×100×100 = 1_000_000  → total=2_000_000
    Para precio_final=5100:
        calls ITM=0
        puts 5200 ITM → 100×200×100=2_000_000
        puts 5300 ITM → 200×100×100=2_000_000  → total=4_000_000
    → max_pain = 5200.
    """
    spot = 5200.0
    contracts = [
        _make_contract(5100, "C", oi=100, gamma=0.001),
        _make_contract(5200, "C", oi=200, gamma=0.001),
        _make_contract(5200, "P", oi=200, gamma=0.001),
        _make_contract(5300, "P", oi=100, gamma=0.001),
    ]
    chain = _make_chain(contracts)
    result = calc_net_gex(chain, chain, spot=spot, fecha=TODAY)

    assert result["max_pain"] == 5200


def test_max_pain_un_strike():
    """Un único strike → max_pain = ese strike."""
    spot = 5200.0
    contracts = [
        _make_contract(5200, "C", oi=500, gamma=0.001),
        _make_contract(5200, "P", oi=500, gamma=0.001),
    ]
    chain = _make_chain(contracts)
    result = calc_net_gex(chain, chain, spot=spot, fecha=TODAY)

    assert result["max_pain"] == 5200


# ---------------------------------------------------------------------------
# Grupo 4: Scoring Net GEX — umbrales 15B (long) / 5B (short)
# ---------------------------------------------------------------------------


def _chain_with_net_gex(target_bn: float, spot: float = 5200.0):
    """
    Construye una cadena mínima que produce aproximadamente target_bn billions de GEX.
    GEX = gamma × OI × spot² / 1e9  (sin factor ×100 tras recalibración en PR #16)
    Usamos gamma=0.001 fijo, OI calculado para alcanzar el target.
    """
    factor = 1e9 / (spot ** 2)
    oi = max(1, round(abs(target_bn) * factor / 0.001))
    if target_bn >= 0:
        contracts = [_make_contract(5200, "C", oi=oi, gamma=0.001)]
    else:
        contracts = [_make_contract(5200, "P", oi=oi, gamma=0.001)]
    return _make_chain(contracts)


def test_score_long_gamma_fuerte():
    """net_gex > +15B → score_gex=+3, signal=LONG_GAMMA_FUERTE"""
    chain = _chain_with_net_gex(target_bn=20.0)
    result = calc_net_gex(_empty_chain(), chain, spot=5200.0, fecha=TODAY)
    assert result["score_gex"]  == 3
    assert result["signal_gex"] == "LONG_GAMMA_FUERTE"
    assert result["net_gex_bn"] > 15.0


def test_score_long_gamma_suave():
    """0 < net_gex < +15B → score_gex=+1, signal=LONG_GAMMA_SUAVE"""
    chain = _chain_with_net_gex(target_bn=5.0)
    result = calc_net_gex(_empty_chain(), chain, spot=5200.0, fecha=TODAY)
    assert result["score_gex"]  == 1
    assert result["signal_gex"] == "LONG_GAMMA_SUAVE"
    assert 0 < result["net_gex_bn"] <= 15.0


def test_score_short_gamma_suave():
    """-5B < net_gex < 0 → score_gex=-1, signal=SHORT_GAMMA_SUAVE"""
    chain = _chain_with_net_gex(target_bn=-2.0)
    result = calc_net_gex(_empty_chain(), chain, spot=5200.0, fecha=TODAY)
    assert result["score_gex"]  == -1
    assert result["signal_gex"] == "SHORT_GAMMA_SUAVE"
    assert -5.0 <= result["net_gex_bn"] < 0


def test_score_short_gamma_fuerte():
    """net_gex < -5B → score_gex=-3, signal=SHORT_GAMMA_FUERTE"""
    chain = _chain_with_net_gex(target_bn=-8.0)
    result = calc_net_gex(_empty_chain(), chain, spot=5200.0, fecha=TODAY)
    assert result["score_gex"]  == -3
    assert result["signal_gex"] == "SHORT_GAMMA_FUERTE"
    assert result["net_gex_bn"] < -5.0


# ---------------------------------------------------------------------------
# Grupo 5: Casos de error
# ---------------------------------------------------------------------------


def test_cadena_vacia():
    """Cadena multi vacía → status=EMPTY_CHAIN, ambos scores=0"""
    result = calc_net_gex(_empty_chain(), _empty_chain(), spot=5200.0, fecha=TODAY)
    assert result["status"]    == "EMPTY_CHAIN"
    assert result["score_gex"] == 0
    assert result["score_flip"] == 0


def test_spot_none():
    """spot=None → status=MISSING_DATA, ambos scores=0"""
    contracts = [_make_contract(5200, "C", oi=1000, gamma=0.001)]
    chain = _make_chain(contracts)
    result = calc_net_gex(chain, chain, spot=None, fecha=TODAY)
    assert result["status"]    == "MISSING_DATA"
    assert result["score_gex"] == 0
    assert result["score_flip"] == 0


def test_sin_gamma():
    """Contratos con gamma=None → ninguno aporta GEX → status=ERROR, ambos scores=0"""
    contracts = [
        _make_contract(5200, "C", oi=1000, gamma=None),
        _make_contract(5200, "P", oi=1000, gamma=None),
    ]
    chain = _make_chain(contracts)
    result = calc_net_gex(chain, chain, spot=5200.0, fecha=TODAY)
    assert result["status"]    == "ERROR"
    assert result["score_gex"] == 0
    assert result["score_flip"] == 0


def test_error_no_interrumpe_pipeline():
    """Cadena con status=ERROR desde fetch → no lanza excepción, devuelve dict con status"""
    bad_chain = {"contracts": [], "expiries": [], "n_contracts": 0, "status": "ERROR"}
    try:
        result = calc_net_gex(bad_chain, bad_chain, spot=5200.0, fecha=TODAY)
        assert isinstance(result, dict)
        assert "status" in result
        assert result["score_gex"]  == 0
        assert result["score_flip"] == 0
    except Exception as e:
        raise AssertionError(f"calc_net_gex no debe propagar excepciones, pero lanzó: {e}")


# ---------------------------------------------------------------------------
# Grupo 6: Control Node
# ---------------------------------------------------------------------------


def test_control_node_en_short_gamma():
    """Short gamma con puts concentradas en 5150 → control_node=5150 (GEX más negativo)"""
    spot = 5200.0
    contracts = [
        _make_contract(5150, "P", oi=10000, gamma=0.003),  # GEX más negativo
        _make_contract(5200, "P", oi=2000,  gamma=0.001),
        _make_contract(5250, "C", oi=1000,  gamma=0.001),
    ]
    chain = _make_chain(contracts)
    result = calc_net_gex(chain, chain, spot=spot, fecha=TODAY)

    assert result["status"] == "OK"
    assert result["control_node"] == 5150
    assert result["net_gex_bn"] < 0


def test_control_node_none_en_long_gamma():
    """Long gamma (solo calls) → control_node=None"""
    spot = 5200.0
    contracts = [
        _make_contract(5100, "C", oi=5000, gamma=0.002),
        _make_contract(5200, "C", oi=8000, gamma=0.003),
        _make_contract(5300, "C", oi=3000, gamma=0.001),
    ]
    chain = _make_chain(contracts)
    result = calc_net_gex(chain, chain, spot=spot, fecha=TODAY)

    assert result["control_node"] is None
    assert result["net_gex_bn"] > 0


# ---------------------------------------------------------------------------
# Grupo 7: Chop Zone
# ---------------------------------------------------------------------------


def test_chop_zone_calculada_alrededor_del_flip():
    """Flip detectado → chop_zone_low < flip_level = chop_zone_high"""
    spot = 5250.0
    contracts = [
        _make_contract(5100, "P", oi=5000, gamma=0.002),
        _make_contract(5200, "C", oi=1000, gamma=0.001),
        _make_contract(5300, "C", oi=8000, gamma=0.002),
    ]
    chain = _make_chain(contracts)
    result = calc_net_gex(chain, chain, spot=spot, fecha=TODAY)

    assert result["flip_level"] is not None
    assert result["chop_zone_low"]  is not None
    assert result["chop_zone_high"] is not None
    assert result["chop_zone_low"]  < result["flip_level"]
    assert result["chop_zone_high"] == result["flip_level"]


def test_chop_zone_none_sin_flip():
    """GEX siempre positivo → flip_level=None → chop_zone_low=None, chop_zone_high=None"""
    spot = 5200.0
    contracts = [
        _make_contract(5100, "C", oi=1000, gamma=0.001),
        _make_contract(5200, "C", oi=2000, gamma=0.001),
        _make_contract(5300, "C", oi=1500, gamma=0.001),
    ]
    chain = _make_chain(contracts)
    result = calc_net_gex(chain, chain, spot=spot, fecha=TODAY)

    assert result["chop_zone_low"]  is None
    assert result["chop_zone_high"] is None


# ---------------------------------------------------------------------------
# Grupo 8: GEX relativo por strike
# ---------------------------------------------------------------------------


def test_gex_pct_maximo_es_100():
    """El strike con mayor abs(GEX) debe tener abs(pct)==100.0"""
    spot = 5250.0
    contracts = [
        _make_contract(5100, "P", oi=10000, gamma=0.003),
        _make_contract(5200, "P", oi=1000,  gamma=0.001),
        _make_contract(5300, "C", oi=2000,  gamma=0.002),
    ]
    chain = _make_chain(contracts)
    result = calc_net_gex(chain, chain, spot=spot, fecha=TODAY)

    pct = result["gex_pct_by_strike"]
    assert len(pct) > 0
    max_abs_pct = max(abs(v) for v in pct.values())
    assert max_abs_pct == 100.0


def test_gex_pct_vacio_sin_gamma():
    """Cadena sin gamma válida → gex_pct_by_strike == {}"""
    spot = 5200.0
    contracts = [
        _make_contract(5200, "C", oi=1000, gamma=None),
        _make_contract(5200, "P", oi=1000, gamma=None),
    ]
    chain = _make_chain(contracts)
    result = calc_net_gex(chain, chain, spot=spot, fecha=TODAY)

    assert result["gex_pct_by_strike"] == {}


# ---------------------------------------------------------------------------
# Grupo 9: Regime Text
# ---------------------------------------------------------------------------


def test_regime_text_short_gamma_incluye_flip():
    """
    Short gamma + flip_level → regime_text incluye 'bajo <flip>'.

    Cadena diseñada para tener net_gex < 0 Y cumsum que cruza cero:
      5000P → cumsum negativo (chop_low)
      5200C → cumsum cruza a positivo (flip_level=5200)
      5300P grande → cumsum vuelve negativo (net_gex < 0)
    """
    spot = 5200.0
    contracts = [
        _make_contract(5000, "P", oi=5000, gamma=0.002),  # GEX ≈ -0.26B
        _make_contract(5200, "C", oi=5000, gamma=0.003),  # GEX ≈ +0.41B  → cumsum positivo
        _make_contract(5300, "P", oi=8000, gamma=0.003),  # GEX ≈ -0.62B  → net < 0
    ]
    chain = _make_chain(contracts)
    result = calc_net_gex(chain, chain, spot=spot, fecha=TODAY)

    assert result["status"] == "OK"
    assert result["net_gex_bn"] < 0, "Debe ser short gamma"
    assert result["flip_level"] is not None, "Debe existir flip_level"
    assert "bajo" in result["regime_text"]
    assert str(int(result["flip_level"])) in result["regime_text"]


def test_regime_text_long_gamma_no_incluye_flip():
    """LONG_GAMMA → regime_text no menciona 'bajo'"""
    spot = 5200.0
    contracts = [
        _make_contract(5100, "C", oi=5000, gamma=0.002),
        _make_contract(5200, "C", oi=8000, gamma=0.003),
    ]
    chain = _make_chain(contracts)
    result = calc_net_gex(chain, chain, spot=spot, fecha=TODAY)

    assert "bajo" not in result["regime_text"]
    assert result["regime_text"] != "Régimen GEX no disponible"


def test_regime_text_error_devuelve_fallback():
    """Error en la cadena → regime_text='Régimen GEX no disponible'"""
    result = calc_net_gex(_empty_chain(), _empty_chain(), spot=5200.0, fecha=TODAY)
    assert result["regime_text"] == "Régimen GEX no disponible"
