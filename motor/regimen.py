# -*- coding: utf-8 -*-
"""Regimen de mercado: ALCISTA, BAJISTA o NEUTRO segun SPY vs MM200."""


def regimen_mercado(df_spy):
    """
    Calcula el regimen de mercado basado en SPY vs MM200.

    Returns:
        "ALCISTA": SPY > MM200 (mercado alcista)
        "BAJISTA": SPY < MM200 * 0.95 (mercado bajista)
        "NEUTRO": SPY entre ambos
    """
    if df_spy is None or df_spy.empty or len(df_spy) < 200:
        return "NEUTRO"

    try:
        precio = float(df_spy["Close"].iloc[-1])
        mm200 = float(df_spy["Close"].rolling(window=200).mean().iloc[-1])

        if precio > mm200:
            return "ALCISTA"
        elif precio < mm200 * 0.95:
            return "BAJISTA"
        else:
            return "NEUTRO"
    except Exception:
        return "NEUTRO"