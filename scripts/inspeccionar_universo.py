import json

d = json.load(open('motor/universe_usa.json', encoding='utf-8'))

print(f"Total: {d['total']}")
print()
print("Primeros 30 tickers:")
print(', '.join(d['tickers'][:30]))
print()
print("Primer detalle:")
print(d['detalles'][0])
print()
largos = [t for t in d['tickers'] if len(t) >= 5]
print(f"Tickers con 5+ letras: {len(largos)}")
print(f"Primeros 20 largos: {largos[:20]}")
print()

# Detectar sufijos raros
sufijos = {}
for t in d['tickers']:
    if len(t) >= 4:
        ult = t[-1]
        sufijos[ult] = sufijos.get(ult, 0) + 1
print("Últimos caracteres (tickers de 4+ letras):")
for k, v in sorted(sufijos.items(), key=lambda x: -x[1])[:10]:
    print(f"  {k}: {v}")