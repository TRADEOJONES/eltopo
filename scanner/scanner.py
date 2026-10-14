# -*- coding: utf-8 -*-
"""Scanner principal ELTOPO."""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from motor.datos import obtener_datos
from motor.indicadores import agregar_indicadores, resumen_indicadores

from motor.indicadores_extra import calcular_fuerza_relativa, calcular_volume_profile
from motor.regimen import regimen_mercado

from .config import (
    MAX_TICKERS, TOP_N_LONG, TOP_N_SHORT, MAX_WORKERS,
    MIN_SCORE_LONG, MIN_SCORE_SHORT, TIMEFRAME,
    PAUSA_CADA_TICKERS, PAUSA_SEGUNDOS,
)
from .filtros import es_operable, es_short_operable
from .scoring_long import calcular_score_long
from .scoring_short import calcular_score_short


def _ruta_resultado():
    return Path(__file__).parent.parent / "data" / "scanner_result.json"


def _ruta_top1000():
    return Path(__file__).parent.parent / "data" / "top_1000.json"


def _ruta_universo():
    return Path(__file__).parent.parent / "motor" / "universe_swing.json"


def _ruta_resultado_full():
    return Path(__file__).parent.parent / "data" / "scanner_result_full.json"


def _es_elegible_long(item):
    """Filtro de elegibilidad para LONG: excluir empresas con ROE < -20%."""
    f = item.get("fundamental") or {}
    roe = f.get("roe")
    if roe is not None and roe < -0.20:
        return False
    return True


def _es_elegible_short(item):
    """Filtro de elegibilidad para SHORT: excluir empresas muy buenas y baratas."""
    f = item.get("fundamental") or {}
    roe = f.get("roe")
    per = f.get("per")
    if roe is not None and roe > 0.30 and per is not None and 0 < per < 15:
        return False
    return True

def _clasificar_rebote(item):
    """Clasifica el rebote en 3 subcategorías: rango, alcista, bajista.
    
    Returns:
        str: "REBOTE_RANGO" | "REBOTE_ALCISTA" | "REBOTE_BAJISTA" | "REBOTE_INDEFINIDO"
    """
    precios = item.get("precios_historicos") or []
    mm200 = item.get("mm200")
    mm50 = item.get("mm50")
    precio = item.get("precio")
    adx = item.get("adx")
    
    if not precios or not precio or len(precios) < 60:
        return "REBOTE_INDEFINIDO"
    
    # Calcular pendiente MM200 (20 días)
    if len(precios) >= 220:
        mm200_hoy = sum(precios[-200:]) / 200
        mm200_antes = sum(precios[-220:-20]) / 200
        pend_mm200 = (mm200_hoy / mm200_antes - 1) * 100 if mm200_antes > 0 else 0
    else:
        pend_mm200 = 0
    
    # Calcular rango de 60 días
    ultimos_60 = precios[-60:]
    rango_alto = max(ultimos_60)
    rango_bajo = min(ultimos_60)
    rango_pct = (rango_alto - rango_bajo) / rango_bajo * 100 if rango_bajo > 0 else 100
    
    # 1. TENDENCIA ALCISTA: MM200 ascendente + precio > MM200
    if pend_mm200 > 0.5 and mm200 and precio > mm200:
        return "REBOTE_ALCISTA"
    
    # 2. RANGO: rango estrecho + ADX bajo
    if rango_pct < 20 and adx and adx < 25:
        return "REBOTE_RANGO"
    
    # 3. TENDENCIA BAJISTA: precio < MM200 + ADX alto
    if mm200 and precio < mm200 and adx and adx > 25:
        return "REBOTE_BAJISTA"
    
    # 4. Por defecto
    return "REBOTE_INDEFINIDO"

def _enriquecer_top(items, top_n=15):
    """Anade fundamental + sentimiento + catalizadores + recalcula score."""
    from motor.datos import obtener_fundamental
    from motor.sentimiento import obtener_sentimiento
    from motor.catalizadores import obtener_catalizadores
    from .scoring_long import calcular_score_long
    from .scoring_short import calcular_score_short

    enriquecidos = []
    for item in items[:top_n]:
        ticker = item["ticker"]
        try:
            item["fundamental"] = obtener_fundamental(ticker)
        except Exception:
            item["fundamental"] = None
        try:
            item["sentimiento"] = obtener_sentimiento(ticker)
        except Exception:
            item["sentimiento"] = None
        try:
            item["catalizadores"] = obtener_catalizadores(ticker)
        except Exception:
            item["catalizadores"] = None

        # RECALCULAR el score con fundamental y sentimiento
        try:
            resumen_completo = {
                "precio": item.get("precio"),
                "mm50": item.get("mm50"),
                "mm200": item.get("mm200"),
                "rsi": item.get("rsi"),
                "macd": item.get("macd"),
                "macd_signal": item.get("macd_signal"),
                "vol_relativo": item.get("vol_relativo"),
                "atr": item.get("atr"),
                "adx": item.get("adx"),
                "poc": item.get("poc"),
                "obv": item.get("obv"),
                "obv_anterior": item.get("obv_anterior"),
                "fundamental": item.get("fundamental"),
                "sentimiento": item.get("sentimiento"),
                "precios_historicos": item.get("precios_historicos"),
                "fuerza_relativa": item.get("fuerza_relativa"),
            }
            # Si faltan indicadores en item, usar desglose
            rl = calcular_score_long(resumen_completo)
            rs = calcular_score_short(resumen_completo)
            item["score_long"] = rl["score"]
            item["score_short"] = rs["score"]
            item["desglose_long"] = rl["desglose"]
            item["desglose_short"] = rs["desglose"]
        except Exception as e:
            print(f"[WARN] No se pudo recalcular {ticker}: {e}")

        enriquecidos.append(item)
    return enriquecidos


def analizar_ticker_scanner(ticker, df_spy):
    try:
        df = obtener_datos(ticker, TIMEFRAME)
        if df is None:
            return None
        if not es_operable(df, ticker):
            return None

        df = agregar_indicadores(df, motor=TIMEFRAME)
        resumen = resumen_indicadores(df)
        resumen["fuerza_relativa"] = calcular_fuerza_relativa(df, df_spy, ventana=30)
        resumen["precios_historicos"] = df["Close"].tail(50).tolist()

        # POC (Point of Control)
        try:
            poc, _ = calcular_volume_profile(df.tail(60))
            resumen["poc"] = poc
        except Exception:
            resumen["poc"] = None

        long_result = calcular_score_long(resumen)
        short_result = calcular_score_short(resumen)

        # STOP, OBJETIVO, R:B (para horizonte 5-20 dias)
        atr_val = resumen.get("atr")
        precio_val = resumen.get("precio")
        stop_val = None
        objetivo_val = None
        rb_val = None
        if atr_val and precio_val:
            stop_val = precio_val - (2.5 * atr_val)
            objetivo_val = precio_val + (7.5 * atr_val)
            riesgo = precio_val - stop_val
            beneficio = objetivo_val - precio_val
            if riesgo > 0:
                rb_val = round(beneficio / riesgo, 2)
            stop_val = round(stop_val, 2)
            objetivo_val = round(objetivo_val, 2)

        return {
            "ticker": ticker,
            "score_long": long_result["score"],
            "score_short": short_result["score"],
            "precio": resumen.get("precio"),
            "desglose_long": long_result["desglose"],
            "desglose_short": short_result["desglose"],
            "rsi": resumen.get("rsi"),
            "macd": resumen.get("macd"),
            "macd_signal": resumen.get("macd_signal"),
            "mm50": resumen.get("mm50"),
            "mm200": resumen.get("mm200"),
            "vol_relativo": resumen.get("vol_relativo"),
            "atr": resumen.get("atr"),
            "adx": resumen.get("adx"),
            "poc": resumen.get("poc"),
            "obv": resumen.get("obv"),
            "obv_anterior": resumen.get("obv_anterior"),
            "precios_historicos": resumen.get("precios_historicos"),
            "fuerza_relativa": resumen.get("fuerza_relativa"),
            "stop": stop_val,
            "objetivo": objetivo_val,
            "rb": rb_val,
        }
    except Exception:
        return None


def _cargar_tickers(tickers_file=None):
    """Carga la lista de tickers."""
    if tickers_file:
        ruta = Path(tickers_file)
        if ruta.exists():
            with open(ruta, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "tickers" in data:
                return data["tickers"]
            elif isinstance(data, list):
                return data
            else:
                print(f"[WARN] Formato desconocido en {ruta}. Usando tickers.json")
        else:
            print(f"[WARN] No existe {ruta}. Usando tickers.json completo")

    tickers_path = Path(__file__).parent.parent / "motor" / "tickers.json"
    with open(tickers_path, "r", encoding="utf-8") as f:
        tickers = json.load(f)
    return list(tickers.keys())


def _cargar_universo():
    """Carga la lista de tickers del universo generado."""
    ruta = _ruta_universo()
    if not ruta.exists():
        print(f"[WARN] No existe {ruta}. Usando tickers.json")
        return _cargar_tickers()
    with open(ruta, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "tickers" in data:
        return data["tickers"]
    return list(data)


def escanear(
    max_tickers=None,
    top_n_long=None,
    top_n_short=None,
    tickers_file=None,
    save_top_long=1000,
):
    """Ejecuta el scanner con pausas anti rate-limit."""
    top_n_long = top_n_long or TOP_N_LONG
    top_n_short = top_n_short or TOP_N_SHORT

    print(f"\n{'='*70}")
    print(f"  SCANNER ELTOPO")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if tickers_file:
        print(f"  Modo: tickers especificos ({tickers_file})")
    else:
        print(f"  Modo: escaneo completo")
    print(f"  Workers: {MAX_WORKERS}")
    print(f"  Pausa: {PAUSA_SEGUNDOS}s cada {PAUSA_CADA_TICKERS} tickers")
    print(f"{'='*70}\n")

    # Cargar lista de tickers
    if tickers_file:
        lista = _cargar_tickers(tickers_file)
        print(f"Tickers desde archivo: {len(lista)}")
    else:
        todos = _cargar_tickers()
        max_tickers = max_tickers or MAX_TICKERS
        lista = todos[:max_tickers]
        print(f"Tickers disponibles: {len(todos)}")
        print(f"A analizar: {len(lista)}")

    print(f"Top: {top_n_long} LONG + {top_n_short} SHORT\n")

    print("Descargando SPY (referencia)...")
    df_spy = obtener_datos("SPY", TIMEFRAME)

    # REGIMEN DE MERCADO
    regimen = regimen_mercado(df_spy)
    print(f"[+] Regimen de mercado: {regimen}")

    resultados = []
    inicio = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futuros = {executor.submit(analizar_ticker_scanner, t, df_spy): t for t in lista}

        for i, futuro in enumerate(as_completed(futuros), 1):
            try:
                r = futuro.result()
                if r:
                    resultados.append(r)
            except Exception:
                pass

            # Pausa anti rate-limit
            if i % PAUSA_CADA_TICKERS == 0:
                print(f"  [PAUSA] {PAUSA_SEGUNDOS}s despues de {i} tickers...")
                time.sleep(PAUSA_SEGUNDOS)

            if i % 20 == 0:
                elapsed = time.time() - inicio
                print(f"  [{i}/{len(lista)}] {elapsed:.0f}s - {len(resultados)} validos")

    elapsed = time.time() - inicio

    top_long = sorted(
        [r for r in resultados if r["score_long"] >= MIN_SCORE_LONG],
        key=lambda x: (
            x["score_long"],
            x["desglose_long"].get("fuerza_relativa", 0),
            x["desglose_long"].get("momentum", 0)
        ),
        reverse=True
    )[:top_n_long]

    top_short = sorted(
        [r for r in resultados
         if r["score_short"] >= MIN_SCORE_SHORT
         and es_short_operable(r["ticker"])],
        key=lambda x: (
            x["score_short"],
            x["desglose_short"].get("fuerza_relativa", 0),
            x["desglose_short"].get("momentum", 0)
        ),
        reverse=True
    )[:top_n_short]

    # ENRIQUECER EL TOP 15 con fundamental + sentimiento + catalizadores
    print(f"\n[+] Enriqueciendo Top {top_n_long} LONG con Finnhub...")
    top_long = _enriquecer_top(top_long, top_n_long)
    print(f"[+] Enriqueciendo Top {top_n_short} SHORT con Finnhub...")
    top_short = _enriquecer_top(top_short, top_n_short)

    # FILTRO DE ELEGIBILIDAD
    top_long = [t for t in top_long if _es_elegible_long(t)]
    top_short = [t for t in top_short if _es_elegible_short(t)]

    # RE-ORDENAR despues del recalculo
    top_long = sorted(top_long, key=lambda x: x["score_long"], reverse=True)
    top_short = sorted(top_short, key=lambda x: x["score_short"], reverse=True)

    # FILTRO DE REGIMEN DE MERCADO
    if regimen == "BAJISTA":
        top_long = []  # Sin LONG en mercado bajista
    elif regimen == "NEUTRO":
        top_long = top_long[:5]  # Reducir LONG en mercado neutro

    resultado_final = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_analizados": len(resultados),
        "tiempo_segundos": round(elapsed, 1),
        "top_long": top_long,
        "top_short": top_short,
    }

    ruta = _ruta_resultado()
    ruta.parent.mkdir(exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resultado_final, f, ensure_ascii=False, indent=2)

    # Guardar top N LONG en top_1000.json (solo si save_top_long > 0 y modo full)
    if save_top_long > 0 and not tickers_file:
        mejores_long = sorted(
            [r for r in resultados if r["score_long"] >= MIN_SCORE_LONG],
            key=lambda x: x["score_long"],
            reverse=True
        )[:save_top_long]

        tickers_top = [r["ticker"] for r in mejores_long]

        top1000_data = {
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "total": len(tickers_top),
            "tickers": tickers_top,
        }

        ruta_top = _ruta_top1000()
        with open(ruta_top, "w", encoding="utf-8") as f:
            json.dump(top1000_data, f, ensure_ascii=False, indent=2)

        print(f"\n[OK] Guardados {len(tickers_top)} tickers en top_1000.json")

    print(f"\n{'='*70}")
    print(f"  COMPLETADO en {elapsed:.0f}s")
    print(f"{'='*70}\n")

    print(f"--- TOP {top_n_long} LONG ---")
    for i, r in enumerate(top_long, 1):
        print(f"  {i:2d}. {r['ticker']:6s} {r['score_long']:.2f}")

    print(f"\n--- TOP {top_n_short} SHORT ---")
    for i, r in enumerate(top_short, 1):
        print(f"  {i:2d}. {r['ticker']:6s} {r['score_short']:.2f}")

    print(f"\n{'='*70}")
    print(f"Guardado en: {ruta}")
    print(f"{'='*70}\n")

    return resultado_final


# =====================================================
# ESCANEO DE REVERSION (on-demand)
# =====================================================

def analizar_ticker_reversion(ticker, df_spy):
    """Analiza un ticker especificamente para REVERSION (v3)."""
    from .scoring_reversion import calcular_score_reversion

    try:
        df = obtener_datos(ticker, TIMEFRAME)
        if df is None:
            return None
        if not es_operable(df, ticker):
            return None

        df = agregar_indicadores(df, motor=TIMEFRAME)
        resumen = resumen_indicadores(df)
        resumen["fuerza_relativa"] = calcular_fuerza_relativa(df, df_spy, ventana=30)
        resumen["precios_historicos"] = df["Close"].tail(250).tolist()

        # POC (Point of Control)
        try:
            poc, _ = calcular_volume_profile(df.tail(60))
            resumen["poc"] = poc
        except Exception:
            resumen["poc"] = None

        rev = calcular_score_reversion(resumen)

        return {
            "ticker": ticker,
            "score_reversion": rev["score"],
            "score_rebote": rev["score_rebote"],
            "score_cambio": rev["score_cambio"],
            "categoria": rev["categoria"],
            "texto": rev["texto"],
            "precio": resumen.get("precio"),
            "estado": rev.get("estado", "DEBIL"),
            "stop": rev.get("stop"),
            "objetivo": rev.get("objetivo"),
            "rb": rev.get("rb"),
        }
    except Exception:
        return None


def escanear_reversion(tickers_file=None, top_n=15, max_tickers=500, progress_callback=None):
    """
    Escaneo especifico para REVERSION.
    Analiza el universo completo (universe_swing.json) y calcula score_reversion.
    """
    if progress_callback:
        progress_callback(0, 0, "Cargando lista de tickers...")

    if tickers_file is None:
        tickers_file = _ruta_universo()

    with open(tickers_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "tickers" in data:
        tickers = data["tickers"]
    else:
        tickers = data

    tickers = tickers[:max_tickers]
    total = len(tickers)

    if progress_callback:
        progress_callback(0, total, "Descargando SPY (referencia)...")

    df_spy = obtener_datos("SPY", TIMEFRAME)

    # REGIMEN DE MERCADO
    regimen = regimen_mercado(df_spy)
    print(f"[+] Regimen de mercado: {regimen}")

    resultados = []
    inicio = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futuros = {executor.submit(analizar_ticker_reversion, t, df_spy): t for t in tickers}

        for i, futuro in enumerate(as_completed(futuros), 1):
            try:
                r = futuro.result()
                if r:
                    resultados.append(r)
            except Exception:
                pass

            if i % PAUSA_CADA_TICKERS == 0:
                time.sleep(PAUSA_SEGUNDOS)

            if progress_callback and (i % 10 == 0 or i == total):
                progress_callback(i, total, None)

    elapsed = time.time() - inicio

    top = sorted(
        [r for r in resultados if r["score_reversion"] >= 5.0],
        key=lambda x: x["score_reversion"],
        reverse=True
    )
    
    # FILTRO R:B >= 1.5
    top = [t for t in top if t.get("rb") is None or t["rb"] >= 1.5]

    # FILTRO DE REGIMEN
    if regimen == "BAJISTA" and top:
        # En mercado bajista, los rebotes son menos fiables
        # Reducimos a la mitad
        top = top[:max(3, top_n // 2)]

    top = top[:top_n]

    # ENRIQUECER con fundamental + sentimiento + catalizadores
    from motor.datos import obtener_fundamental
    from motor.sentimiento import obtener_sentimiento
    from motor.catalizadores import obtener_catalizadores

    for item in top:
        ticker = item["ticker"]
        try:
            item["fundamental"] = obtener_fundamental(ticker)
        except Exception:
            item["fundamental"] = None
        try:
            item["sentimiento"] = obtener_sentimiento(ticker)
        except Exception:
            item["sentimiento"] = None
        try:
            item["catalizadores"] = obtener_catalizadores(ticker)
        except Exception:
            item["catalizadores"] = None

    # FILTRO EARNINGS < 5 dias
    top = [t for t in top if not (
        t.get("catalizadores") and
        t["catalizadores"].get("dias_hasta_earnings") is not None and
        t["catalizadores"]["dias_hasta_earnings"] < 5
    )]
    # AÑADIR: Extraer campos de earnings para fácil acceso en el frontend
    for item in top:
        cat = item.get("catalizadores") or {}
        item["dias_hasta_earnings"] = cat.get("dias_hasta_earnings")
        item["proximos_earnings"] = cat.get("proximos_earnings")
        item["fecha_earnings_fiable"] = cat.get("fecha_fiable", "desconocida")
    # SEPARAR EN 2 LISTAS
      # SEPARAR EN 2 LISTAS
    top_rebote = sorted(
        [t for t in top if t.get("categoria") == "REBOTE"],
        key=lambda x: x["score_reversion"],
        reverse=True
    )[:top_n]
    top_cambio = sorted(
        [t for t in top if t.get("categoria") == "CAMBIO"],
        key=lambda x: x["score_reversion"],
        reverse=True
    )[:top_n]
    
    # AÑADIR: Clasificar rebotes en 3 subcategorías + excluir tendencia bajista
    top_rebote_filtrado = []
    for t in top_rebote:
        cat_rebote = _clasificar_rebote(t)
        t["categoria_rebote"] = cat_rebote
        
        # EXCLUIR rebotes en tendencia bajista
        if cat_rebote == "REBOTE_BAJISTA":
            print(f"[EXCLUIDO] {t['ticker']} - Rebote en tendencia bajista")
            continue
        
        top_rebote_filtrado.append(t)
    
    top_rebote = top_rebote_filtrado

    return {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_analizados": len(resultados),
        "tiempo_segundos": round(elapsed, 1),
        "top_reversion": top,
        "top_rebote": top_rebote,
        "top_cambio": top_cambio,
    }


def escanear_full(top_n_long=15, top_n_short=15, save_top_long=0):
    """Escaneo del universo ampliado (1786 tickers).

    Analiza el universo generado y guarda el resultado en
    data/scanner_result_full.json. NO toca top_1000.json.
    """
    print(f"\n{'='*70}")
    print(f"  SCANNER FULL ELTOPO")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}\n")

    lista = _cargar_universo()
    print(f"Universo cargado: {len(lista)} tickers")
    print(f"Workers: {MAX_WORKERS}")
    print(f"Top: {top_n_long} LONG + {top_n_short} SHORT\n")

    print("Descargando SPY (referencia)...")
    df_spy = obtener_datos("SPY", TIMEFRAME)

    # REGIMEN DE MERCADO
    regimen = regimen_mercado(df_spy)
    print(f"[+] Regimen de mercado: {regimen}")

    resultados = []
    inicio = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futuros = {executor.submit(analizar_ticker_scanner, t, df_spy): t for t in lista}

        for i, futuro in enumerate(as_completed(futuros), 1):
            try:
                r = futuro.result()
                if r:
                    resultados.append(r)
            except Exception:
                pass

            if i % PAUSA_CADA_TICKERS == 0:
                time.sleep(PAUSA_SEGUNDOS)

            if i % 20 == 0 or i == len(lista):
                elapsed = time.time() - inicio
                ritmo = i / elapsed if elapsed > 0 else 0
                print(f"  [{i}/{len(lista)}] {elapsed:.0f}s - {len(resultados)} validos - {ritmo:.2f}/s")

    elapsed = time.time() - inicio

    top_long = sorted(
        [r for r in resultados if r["score_long"] >= MIN_SCORE_LONG],
        key=lambda x: (
            x["score_long"],
            x["desglose_long"].get("fuerza_relativa", 0),
            x["desglose_long"].get("momentum", 0)
        ),
        reverse=True
    )[:top_n_long]

    top_short = sorted(
        [r for r in resultados
         if r["score_short"] >= MIN_SCORE_SHORT
         and es_short_operable(r["ticker"])],
        key=lambda x: (
            x["score_short"],
            x["desglose_short"].get("fuerza_relativa", 0),
            x["desglose_short"].get("momentum", 0)
        ),
        reverse=True
    )[:top_n_short]

    resultado_final = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_analizados": len(resultados),
        "tiempo_segundos": round(elapsed, 1),
        "universo_usado": len(lista),
        "top_long": top_long,
        "top_short": top_short,
    }

    ruta = _ruta_resultado_full()
    ruta.parent.mkdir(exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resultado_final, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*70}")
    print(f"  COMPLETADO en {elapsed:.0f}s")
    print(f"  Guardado en: {ruta}")
    print(f"{'='*70}\n")

    print(f"--- TOP {top_n_long} LONG ---")
    for i, r in enumerate(top_long, 1):
        print(f"  {i:2d}. {r['ticker']:6s} {r['score_long']:.2f}")

    print(f"\n--- TOP {top_n_short} SHORT ---")
    for i, r in enumerate(top_short, 1):
        print(f"  {i:2d}. {r['ticker']:6s} {r['score_short']:.2f}")

    return resultado_final
