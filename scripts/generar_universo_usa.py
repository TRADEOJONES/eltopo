"""Genera universe_usa.json con solo acciones de USA que Alpaca soporta."""
import json
import os
from datetime import datetime
from pathlib import Path


def _cargar_env():
    """Carga el .env manualmente (sin dependencias externas)."""
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        print(f"[AVISO] No existe {env_path}")
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, valor = linea.split("=", 1)
            clave = clave.strip()
            valor = valor.strip().strip('"').strip("'")
            if clave and valor:
                os.environ.setdefault(clave, valor)
    print(f"[OK] .env cargado desde {env_path}")


_cargar_env()

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass


def main():
    api_key = os.environ.get("ALPACA_API_KEY", "").strip()
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "").strip()

    if not api_key or not secret_key:
        print("[ERROR] Faltan ALPACA_API_KEY o ALPACA_SECRET_KEY")
        return

    print("Conectando con Alpaca...")
    client = TradingClient(api_key, secret_key)

    print("Descargando lista de activos USA...")
    search_params = GetAssetsRequest(asset_class=AssetClass.US_EQUITY)
    assets = client.get_all_assets(search_params)
    print(f"  Total recibidos: {len(assets)}")

    # Palabras clave a excluir en el nombre
    excluidos_nombre = [
        "warrant", "unit", "right", "etf", "etn", "fund", "trust",
        "preferred", "depositary", "closed end", "closed-end",
        "acquisition corp", "acquisition company", "blank check",
    ]

    tickers = []
    for a in assets:
        # Filtros base
        if a.status != "active":
            continue
        if not a.tradable:
            continue
        if a.exchange not in ("NASDAQ", "NYSE", "AMEX", "ARCA"):
            continue
        if not a.name:
            continue

        symbol = a.symbol
        nombre = (a.name or "").lower()

        # Excluir simbolos con caracteres raros
        if any(x in symbol for x in ["/", ".", "^", "=", "-"]):
            continue

        # Excluir warrants/units/rights (5 letras terminadas en W, U, R)
        if len(symbol) == 5 and symbol[-1] in ("W", "U", "R"):
            continue

        # Excluir preferred shares (6+ letras)
        if len(symbol) > 5:
            continue

        # Excluir por nombre
        if any(palabra in nombre for palabra in excluidos_nombre):
            continue

        # Excluir nombres muy cortos
        if len(nombre) < 3:
            continue

        tickers.append({
            "ticker": symbol,
            "nombre": a.name,
            "exchange": a.exchange,
        })

    tickers.sort(key=lambda x: x["ticker"])

    resultado = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": len(tickers),
        "tickers": [t["ticker"] for t in tickers],
        "detalles": tickers,
    }

    ruta = Path(__file__).parent.parent / "motor" / "universe_usa.json"
    ruta.parent.mkdir(exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] Generados {len(tickers)} tickers USA")
    print(f"[OK] Guardado en: {ruta}")
    print(f"\nPrimeros 10: {[t['ticker'] for t in tickers[:10]]}")


if __name__ == "__main__":
    main()