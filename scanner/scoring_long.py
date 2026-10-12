# -*- coding: utf-8 -*-
"""Scoring para LONG con filtros de calidad."""


def calcular_score_long(ind):
    """Score 0-10 para LONG con filtros anti-extendido."""
    scores = {}

    precio = ind.get("precio")
    mm200 = ind.get("mm200")
    mm50 = ind.get("mm50")
    rsi = ind.get("rsi")
    macd = ind.get("macd")
    macd_signal = ind.get("macd_signal")
    vol_rel = ind.get("vol_relativo")
    atr = ind.get("atr")
    precios = ind.get("precios_historicos")
    rs = ind.get("fuerza_relativa")

    # 1. Tendencia (25%)
    if precio and mm200 and mm50:
        if precio > mm200 and precio > mm50:
            scores["tendencia"] = 10.0
        elif precio > mm200:
            scores["tendencia"] = 8.0
        elif precio > mm50:
            scores["tendencia"] = 6.0
        else:
            scores["tendencia"] = 2.0

        dist_mm50_pct = (precio / mm50 - 1) * 100
        if dist_mm50_pct > 20:
            scores["tendencia"] -= 4.0
        elif dist_mm50_pct > 15:
            scores["tendencia"] -= 3.0
        elif dist_mm50_pct > 10:
            scores["tendencia"] -= 1.5

        scores["tendencia"] = max(0.0, scores["tendencia"])

        # MEJORA 2: Penalizar subidas verticales (>15% en 5 dias)
        if precios and len(precios) >= 6:
            precio_actual = precios[-1]
            precio_hace_5d = precios[-6]
            if precio_hace_5d > 0:
                subida_5d_pct = (precio_actual / precio_hace_5d - 1) * 100
                if subida_5d_pct > 15:
                    scores["tendencia"] -= 2.0
                    scores["tendencia"] = max(0.0, scores["tendencia"])
    else:
        scores["tendencia"] = 5.0

    # 2. Momentum (20%)
    momentum = 5.0
    if rsi:
        if 50 <= rsi <= 65:
            momentum = 10.0
        elif 45 <= rsi < 50:
            momentum = 8.0
        elif 65 < rsi <= 70:
            momentum = 6.0
        elif 40 <= rsi < 45:
            momentum = 5.0
        elif 70 < rsi <= 75:
            momentum = 4.0
        elif rsi > 75:
            momentum = 1.5
        elif 35 <= rsi < 40:
            momentum = 4.0
        elif rsi < 35:
            momentum = 6.0
        else:
            momentum = 5.0

    if macd and macd_signal and macd < macd_signal:
        momentum -= 1.5

    scores["momentum"] = max(0.0, momentum)

    # 3. Volumen (15%)
    if vol_rel:
        if vol_rel > 2.5:
            scores["volumen"] = 10.0
        elif vol_rel > 2.0:
            scores["volumen"] = 9.0
        elif vol_rel > 1.5:
            scores["volumen"] = 8.0
        elif vol_rel > 1.2:
            scores["volumen"] = 7.0
        elif vol_rel > 0.8:
            scores["volumen"] = 5.5
        else:
            scores["volumen"] = 3.0
    else:
        scores["volumen"] = 5.0

    # 4. Estructura (15%)
    if precios and len(precios) >= 20:
        primer = sum(precios[:7]) / 7
        ultimo = sum(precios[-7:]) / 7
        if ultimo > primer * 1.05:
            scores["estructura"] = 10.0
        elif ultimo > primer * 1.02:
            scores["estructura"] = 8.0
        elif ultimo > primer:
            scores["estructura"] = 6.0
        else:
            scores["estructura"] = 3.0
    else:
        scores["estructura"] = 5.0

    # 5. Fuerza relativa (10%)
    if rs:
        if rs > 10:
            scores["fuerza_relativa"] = 10.0
        elif rs > 5:
            scores["fuerza_relativa"] = 8.5
        elif rs > 2:
            scores["fuerza_relativa"] = 7.0
        elif rs > -2:
            scores["fuerza_relativa"] = 5.0
        elif rs > -5:
            scores["fuerza_relativa"] = 3.0
        else:
            scores["fuerza_relativa"] = 1.0
    else:
        scores["fuerza_relativa"] = 5.0

    # 6. ATR (5%)
    if atr and precio:
        atr_pct = (atr / precio) * 100
        if 2.0 <= atr_pct <= 4.0:
            scores["volatilidad"] = 10.0
        elif 1.5 <= atr_pct < 2.0:
            scores["volatilidad"] = 8.0
        elif 4.0 < atr_pct <= 5.0:
            scores["volatilidad"] = 6.0
        elif atr_pct > 5.0:
            scores["volatilidad"] = 3.0
        else:
            scores["volatilidad"] = 5.0
    else:
        scores["volatilidad"] = 5.0

    # 7. ADX - Fuerza de la tendencia (8%)
    adx = ind.get("adx")
    if adx:
        if adx > 30:
            scores["adx"] = 10.0
        elif adx > 25:
            scores["adx"] = 8.0
        elif adx > 20:
            scores["adx"] = 6.0
        elif adx > 15:
            scores["adx"] = 4.0
        else:
            scores["adx"] = 2.0
    else:
        scores["adx"] = 5.0

    # 8. POC - Point of Control (5%)
    # Premia cuando el precio esta JUSTO por encima del POC (soporte cercano)
    poc = ind.get("poc")
    precio = ind.get("precio")
    if poc and precio and poc > 0:
        if precio >= poc:
            dist_poc_pct = (precio / poc - 1) * 100
            if dist_poc_pct < 3:
                scores["poc"] = 10.0
            elif dist_poc_pct < 7:
                scores["poc"] = 8.0
            elif dist_poc_pct < 12:
                scores["poc"] = 5.0
            else:
                scores["poc"] = 3.0
        else:
            dist_poc_pct = (poc / precio - 1) * 100
            if dist_poc_pct < 5:
                scores["poc"] = 7.0
            else:
                scores["poc"] = 4.0
    else:
        scores["poc"] = 5.0

    # 9. OBV - On-Balance Volume (5%)
    obv = ind.get("obv")
    obv_ant = ind.get("obv_anterior")
    if obv is not None and obv_ant is not None and obv_ant != 0:
        if obv_ant < 0:
            obv_ant_abs = abs(obv_ant)
            cambio_obv_pct = (obv - obv_ant) / obv_ant_abs * 100
        else:
            cambio_obv_pct = (obv / obv_ant - 1) * 100
        if cambio_obv_pct > 3:
            scores["obv"] = 10.0
        elif cambio_obv_pct > 1:
            scores["obv"] = 8.0
        elif cambio_obv_pct > -1:
            scores["obv"] = 6.0
        elif cambio_obv_pct > -3:
            scores["obv"] = 4.0
        else:
            scores["obv"] = 2.0
    else:
        scores["obv"] = 5.0

    # 10. FUNDAMENTAL (8%) - basado en datos reales
    f = ind.get("fundamental") or {}
    if f:
        score_fund = 5.0
        roe = f.get("roe")
        per = f.get("per")
        ingresos_yoy = f.get("ingresos_yoy")
        margen_neto = f.get("margen_neto")
        deuda_equity = f.get("deuda_equity")

        # ROE
        if roe is not None:
            if roe > 0.20:
                score_fund += 2.0
            elif roe > 0.15:
                score_fund += 1.5
            elif roe > 0.10:
                score_fund += 1.0
            elif roe > 0.05:
                score_fund += 0.5
            elif roe < 0:
                score_fund -= 2.5
            elif roe < 0.05:
                score_fund -= 0.5

        # PER (solo si positivo)
        if per is not None and per > 0:
            if per < 15:
                score_fund += 1.0
            elif per < 25:
                score_fund += 0.5
            elif per > 50:
                score_fund -= 1.0
            elif per > 35:
                score_fund -= 0.5

        # Ingresos YoY
        if ingresos_yoy is not None:
            if ingresos_yoy > 0.20:
                score_fund += 1.5
            elif ingresos_yoy > 0.10:
                score_fund += 1.0
            elif ingresos_yoy > 0.05:
                score_fund += 0.5
            elif ingresos_yoy < -0.10:
                score_fund -= 1.5
            elif ingresos_yoy < 0:
                score_fund -= 0.5

        # Margen neto
        if margen_neto is not None:
            if margen_neto > 0.20:
                score_fund += 1.0
            elif margen_neto > 0.10:
                score_fund += 0.5
            elif margen_neto < 0:
                score_fund -= 1.0

        scores["fundamental"] = max(1.0, min(10.0, score_fund))
    else:
        scores["fundamental"] = 5.0

    # 11. SENTIMIENTO (9%) - basado en analistas e insider
    s = ind.get("sentimiento") or {}
    if s:
        score_sent = 5.0
        rec = s.get("recomendacion_analistas")
        if rec:
            buys = (rec.get("strong_buy") or 0) + (rec.get("buy") or 0)
            sells = (rec.get("sell") or 0) + (rec.get("strong_sell") or 0)
            holds = rec.get("hold") or 0
            total = buys + holds + sells
            if total > 0:
                ratio_buy = buys / total
                ratio_sell = sells / total
                if ratio_buy > 0.75:
                    score_sent += 3.0
                elif ratio_buy > 0.60:
                    score_sent += 2.0
                elif ratio_buy > 0.50:
                    score_sent += 1.0
                elif ratio_sell > 0.30:
                    score_sent -= 2.0
                elif ratio_sell > 0.20:
                    score_sent -= 1.0

        # Insider
        compras = s.get("insider_compras")
        ventas = s.get("insider_ventas")
        if compras is not None and ventas is not None:
            if compras > ventas * 2 and compras > 0:
                score_sent += 1.0
            elif ventas > compras * 3 and ventas > 0:
                score_sent -= 1.0

        scores["sentimiento"] = max(1.0, min(10.0, score_sent))
    else:
        scores["sentimiento"] = 5.0

    scores["catalizadores"] = 5.0

    pesos = {
        "tendencia": 0.18,
        "momentum": 0.13,
        "volumen": 0.10,
        "estructura": 0.11,
        "fuerza_relativa": 0.07,
        "volatilidad": 0.05,
        "adx": 0.07,
        "poc": 0.04,
        "obv": 0.04,
        "catalizadores": 0.04,
        "fundamental": 0.08,
        "sentimiento": 0.09,
    }

    score = sum(scores[k] * pesos[k] for k in pesos)
    return {"score": round(score, 3), "desglose": scores}
