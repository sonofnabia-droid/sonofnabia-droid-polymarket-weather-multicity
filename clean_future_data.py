#!/usr/bin/env python3
"""
Remove dados futuros (2026) dos arquivos históricos e retreina os modelos.
"""

import os
import shutil
from datetime import datetime
import subprocess
import sys

# Configurações
CITIES = ["dallas", "ankara"]
TODAY = datetime.now()
CUTOFF_DATE = "2026-01-01"  # Remover tudo >= 2026-01-01

def backup_file(filepath):
    """Faz backup do arquivo original."""
    backup_path = f"{filepath}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(filepath, backup_path)
    print(f"✅ Backup criado: {backup_path}")
    return backup_path

def clean_csv(city):
    """Remove dados futuros do CSV da cidade."""
    csv_path = f"historic/{city}.csv"
    temp_path = f"historic/{city}_cleaned.csv"

    print(f"\n🔧 Limpando {city}.csv...")

    # Backup
    backup_file(csv_path)

    # Ler e filtrar
    lines_before = 0
    lines_after = 0
    removed_2026 = 0

    with open(csv_path, 'r') as f_in, open(temp_path, 'w') as f_out:
        for line in f_in:
            lines_before += 1

            # Pular linhas vazias ou com erro
            if not line.strip():
                continue

            # Verificar se contém data de 2026
            if ",2026-" in line or line.startswith("2026"):
                removed_2026 += 1
                continue

            f_out.write(line)
            lines_after += 1

    print(f"  Linhas antes: {lines_before}")
    print(f"  Linhas depois: {lines_after}")
    print(f"  Removidas (2026): {removed_2026} ({100*removed_2026/lines_before:.1f}%)")

    # Substituir original
    shutil.move(temp_path, csv_path)
    print(f"✅ {city}.csv limpo")

def retrain_model(city):
    """Retreina o modelo da cidade."""
    print(f"\n🤖 Retreinando modelo de {city}...")

    cmd = ["python", "train.py", "--city", city]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"✅ Modelo de {city} retreinado com sucesso")
    else:
        print(f"❌ Erro ao retreinar {city}:")
        print(result.stderr)
        return False

    return True

def recalibrate(city):
    """Recalibra o modelo da cidade."""
    print(f"\n📊 Recalibrando {city}...")

    cmd = ["python", "calibrate.py", "--city", city, "--mode", "full", "--years", "5"]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"✅ Calibração de {city} concluída")
    else:
        print(f"❌ Erro na calibração de {city}:")
        print(result.stderr)
        return False

    return True

def main():
    print("=" * 60)
    print("LIMPANDO DADOS FUTUROS E RETREINANDO MODELOS")
    print("=" * 60)
    print(f"Data atual: {TODAY.strftime('%Y-%m-%d')}")
    print(f"Corte: Remover dados >= {CUTOFF_DATE}\n")

    for city in CITIES:
        print(f"\n{'='*60}")
        print(f"PROCESSANDO: {city.upper()}")
        print(f"{'='*60}")

        # 1. Limpar CSV
        clean_csv(city)

        # 2. Retreinar modelo
        if not retrain_model(city):
            print(f"\n⚠️  Erro no retreino de {city}, a continuar...")

        # 3. Recalibrar
        if not recalibrate(city):
            print(f"\n⚠️  Erro na calibração de {city}, a continuar...")

    print("\n" + "=" * 60)
    print("PROCESSO CONCLUÍDO")
    print("=" * 60)
    print("\n📋 Arquivos de backup criados em historic/")
    print("📋 Modelos retreinados em *_peak_model/")
    print("📋 Resultados da calibração no terminal")

if __name__ == "__main__":
    main()
