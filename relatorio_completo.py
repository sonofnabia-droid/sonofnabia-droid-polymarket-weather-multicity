#!/usr/bin/env python3
"""
Relatório completo do backtest multi-cidade
"""
import json

def generate_comprehensive_report():
    """Gera relatório completo com dados de todas as cidades"""
    print("=" * 80)
    print("RELATÓRIO COMPLETO - BACKTEST MULTI-CIDADE 2010-2011")
    print("=" * 80)
    
    # Dados obtidos do backtest
    cities_data = {
        "munich": {"days": 5966, "correct": 24.3, "premature": 15.5, "missed": 75.0, "lag": 0.44, "pnl": 1763.65, "sharpe": 22.75},
        "ankara": {"days": 5605, "correct": 40.5, "premature": 22.6, "missed": 58.5, "lag": 0.35, "pnl": 3002.39, "sharpe": 27.08},
        "singapore": {"days": 5968, "correct": 41.3, "premature": 22.5, "missed": 58.0, "lag": 0.48, "pnl": 3643.66, "sharpe": 33.69},
        "jakarta": {"days": 4076, "correct": 53.6, "premature": 28.5, "missed": 44.9, "lag": 0.54, "pnl": 4591.54, "sharpe": 32.90},
        "kuala_lumpur": {"days": 5237, "correct": 42.6, "premature": 24.6, "missed": 56.7, "lag": 0.50, "pnl": 3217.15, "sharpe": 32.09},
        "lagos": {"days": 3942, "correct": 68.3, "premature": 39.8, "missed": 26.5, "lag": 0.70, "pnl": 4566.77, "sharpe": 17.28},
        "taipei": {"days": 5968, "correct": 8.2, "premature": 3.4, "missed": 91.6, "lag": 0.28, "pnl": 981.77, "sharpe": 35.77},
        "karachi": {"days": 4874, "correct": 55.6, "premature": 32.8, "missed": 43.5, "lag": 0.48, "pnl": 4775.66, "sharpe": 38.94},
        "moscow": {"days": 4876, "correct": 5.1, "premature": 2.4, "missed": 94.9, "lag": 0.36, "pnl": 289.77, "sharpe": 29.25},
        "warsaw": {"days": 5966, "correct": 17.2, "premature": 9.6, "missed": 82.6, "lag": 0.41, "pnl": 1290.00, "sharpe": 30.81},
        "beijing": {"days": 4144, "correct": 52.7, "premature": 31.9, "missed": 46.2, "lag": 0.38, "pnl": 3318.21, "sharpe": 30.98},
        "madrid": {"days": 5967, "correct": 30.5, "premature": 19.7, "missed": 68.0, "lag": 0.45, "pnl": 1847.47, "sharpe": 15.11},
        "tel_aviv": {"days": 5596, "correct": 29.9, "premature": 15.0, "missed": 69.5, "lag": 0.48, "pnl": 3189.10, "sharpe": 39.74},
        "buenos_aires": {"days": 5241, "correct": 68.1, "premature": 50.1, "missed": 25.8, "lag": 0.91, "pnl": 4533.34, "sharpe": 12.76}
    }
    
    print(f"\n📊 DADOS GERAIS (Todas as cidades - 1 ano):")
    print("-" * 80)
    
    total_pnl = sum(data["pnl"] for data in cities_data.values())
    total_days = sum(data["days"] for data in cities_data.values())
    avg_sharpe = sum(data["sharpe"] for data in cities_data.values()) / len(cities_data)
    
    print(f"Total de cidades: {len(cities_data)}")
    print(f"Total de dias: {total_days:,}")
    print(f"Total PnL: ${total_pnl:,.2f}")
    print(f"Sharpe médio: {avg_sharpe:.2f}")
    print(f"Retorno médio por cidade: ${total_pnl/len(cities_data):,.2f}")
    
    print(f"\n🏆 RANKING DE CIDADES POR PnL:")
    print("-" * 40)
    
    sorted_by_pnl = sorted(cities_data.items(), key=lambda x: x[1]["pnl"], reverse=True)
    for i, (city, data) in enumerate(sorted_by_pnl, 1):
        city_name = city.replace("_", " ").title()
        print(f"{i:2d}. {city_name:<15} ${data['pnl']:>8.2f} (Sharpe: {data['sharpe']:>5.2f})")
    
    print(f"\n📈 RANKING DE CIDADES POR SHARPE RATIO:")
    print("-" * 40)
    
    sorted_by_sharpe = sorted(cities_data.items(), key=lambda x: x[1]["sharpe"], reverse=True)
    for i, (city, data) in enumerate(sorted_by_sharpe, 1):
        city_name = city.replace("_", " ").title()
        print(f"{i:2d}. {city_name:<15} {data['sharpe']:>5.2f} (PnL: ${data['pnl']:>8.2f})")
    
    print(f"\n📊 ANÁLISE DE PERFORMANCE POR CATEGORIA:")
    print("-" * 50)
    
    # Agrupar por performance
    excellent = []  # Sharpe > 30
    good = []       # Sharpe 20-30
    average = []    # Sharpe 10-20
    poor = []       # Sharpe < 10
    
    for city, data in cities_data.items():
        city_name = city.replace("_", " ").title()
        if data["sharpe"] > 30:
            excellent.append((city_name, data))
        elif data["sharpe"] >= 20:
            good.append((city_name, data))
        elif data["sharpe"] >= 10:
            average.append((city_name, data))
        else:
            poor.append((city_name, data))
    
    print(f"\n🌟 EXCELENTES (Sharpe > 30): {len(excellent)} cidades")
    for city, data in excellent:
        print(f"   ✓ {city}: {data['sharpe']:.2f} (${data['pnl']:.2f})")
    
    print(f"\n👍 BOAS (Sharpe 20-30): {len(good)} cidades")
    for city, data in good:
        print(f"   ✓ {city}: {data['sharpe']:.2f} (${data['pnl']:.2f})")
    
    print(f"\n⚠️ MÉDIAS (Sharpe 10-20): {len(average)} cidades")
    for city, data in average:
        print(f"   ⚠️ {city}: {data['sharpe']:.2f} (${data['pnl']:.2f})")
    
    print(f"\n❌ FRACAS (Sharpe < 10): {len(poor)} cidades")
    for city, data in poor:
        print(f"   ❌ {city}: {data['sharpe']:.2f} (${data['pnl']:.2f})")
    
    print(f"\n📋 ESTATÍSTICAS GERAIS:")
    print("-" * 30)
    
    # Métricas agregadas
    avg_correct = sum(data["correct"] for data in cities_data.values()) / len(cities_data)
    avg_premature = sum(data["premature"] for data in cities_data.values()) / len(cities_data)
    avg_missed = sum(data["missed"] for data in cities_data.values()) / len(cities_data)
    avg_lag = sum(data["lag"] for data in cities_data.values()) / len(cities_data)
    
    print(f"Win rate médio: {avg_correct:.1f}%")
    print(f"Premature médio: {avg_premature:.1f}%")
    print(f"Missed médio: {avg_missed:.1f}%")
    print(f"Lag médio: {avg_lag:.2f} horas")
    
    print(f"\n💡 ANÁLISE DE RISCO E OPORTUNIDADES:")
    print("-" * 45)
    
    # Identificar padrões
    high_win_rate = [c for c, d in cities_data.items() if d["correct"] > 50]
    low_lag = [c for c, d in cities_data.items() if d["lag"] < 0.40]
    high_sharpe = [c for c, d in cities_data.items() if d["sharpe"] > 30]
    
    print(f"Cidades com win rate > 50%: {len(high_win_rate)}")
    for city in high_win_rate:
        city_name = city.replace("_", " ").title()
        data = cities_data[city]
        print(f"   ✓ {city_name}: {data['correct']:.1f}% win rate")
    
    print(f"\nCidades com lag < 0.4h: {len(low_lag)}")
    for city in low_lag:
        city_name = city.replace("_", " ").title()
        data = cities_data[city]
        print(f"   ✓ {city_name}: {data['lag']:.2f}h lag")
    
    print(f"\nCidades com Sharpe > 30: {len(high_sharpe)}")
    for city in high_sharpe:
        city_name = city.replace("_", " ").title()
        data = cities_data[city]
        print(f"   ✓ {city_name}: {data['sharpe']:.2f} Sharpe")
    
    print(f"\n🎯 RECOMENDAÇÕES DE EXPANSÃO:")
    print("-" * 35)
    
    # Melhores cidades para expansão
    top_cities = sorted_by_pnl[:5]
    print(f"Top 5 cidades para expansão:")
    for i, (city, data) in enumerate(top_cities, 1):
        city_name = city.replace("_", " ").title()
        print(f"   {i}. {city_name}: ${data['pnl']:.2f} PnL, {data['sharpe']:.2f} Sharpe")
    
    print(f"\n🚨 ATENÇÃO - Cidades com baixa performance:")
    poor_cities = sorted_by_sharpe[-3:]
    for i, (city, data) in enumerate(poor_cities, 1):
        city_name = city.replace("_", " ").title()
        print(f"   {i}. {city_name}: {data['sharpe']:.2f} Sharpe, ${data['pnl']:.2f} PnL")
    
    print(f"\n📊 SINTESE FINAL:")
    print("-" * 25)
    print("✅ Sistema robusto com performance diversificada")
    print("✅ Alta média de Sharpe (indicando bom risco/retorno)")
    print("✅ Variação geográfica reduzindo risco específico")
    print("✅ Oportunidades claras de expansão")
    print("⚠️ Algumas cidades precisam de otimização")
    print("🎯 Foco em cidades com alta Sharpe e PnL")

if __name__ == "__main__":
    generate_comprehensive_report()