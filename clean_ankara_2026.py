#!/usr/bin/env python3
"""
Remove dados futuros (2026) do novo CSV de Ankara e retreina o modelo.
"""

import os
import shutil
from datetime import datetime
import subprocess

# Configurações
CITY = "ankara"
CUTOFF_DATE = "2026-01-01"  # Remover tudo >= 2026-01-01

def backup_file(filepath):
    """Faz backup do arquivo original."""
    backup_path = f"{filepath}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(filepath, backup_path)
    print(f"✅ Backup criado: {backup_path}")
    return backup_path

def clean_ankara_csv():
    """Remove dados futuros do CSV de Ankara."""
    csv_path = f"historic/{CITY}.csv"
    temp_path = f"historic/{CITY}_cleaned.csv"

    print(f"\n🔧 Limpando {CITY}.csv...")

    # Backup
    backup_file(csv_path)

    # Ler e filtrar
    lines_before = 0
    lines_after = 0
    removed_2026 = 0

    with open(csv_path, 'r') as f_in, open(temp_path, 'w') as f_out:
        for line in f_in:
            lines_before += 1

            # Pular linhas vazias
            if not line.strip():
                continue

            # Verificar se contém data de 2026
            if "2026-" in line:
                removed_2026 += 1
                continue

            f_out.write(line)
            lines_after += 1

    print(f"  Linhas antes: {lines_before}")
    print(f"  Linhas depois: {lines_after}")
    print(f"  Removidas (2026): {removed_2026} ({100*removed_2026/lines_before:.1f}%)")

    # Substituir original
    shutil.move(temp_path, csv_path)
    print(f"✅ {CITY}.csv limpo")

    return lines_after

def retrain_model():
    """Retreina o modelo de Ankara."""
    print(f"\n🤖 Retreinando modelo de {CITY}...")

    cmd = ["python", "train.py", "--city", CITY]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"✅ Modelo de {CITY} retreinado com sucesso")
        return True
    else:
        print(f"❌ Erro ao retreinar {CITY}:")
        print(result.stderr)
        return False

def recalibrate():
    """Recalibra o modelo de Ankara."""
    print(f"\n📊 Recalibrando {CITY}...")

    cmd = ["python", "calibrate.py", "--city", CITY, "--mode", "full", "--years", "5"]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"✅ Calibração de {CITY} concluída")
        return True
    else:
        print(f"❌ Erro na calibração de {CITY}:")
        print(result.stderr)
        return False

def main():
    print("=" * 60)
    print("LIMPANDO DADOS FUTUROS DE ANKARA E RETREINANDO")
    print("=" * 60)

    # 1. Limpar CSV
    clean_ankara_csv()

    # 2. Retreinar modelo
    if not retrain_model():
        print("\n⚠️  Erro no retreino, a continuar com calibração...")

    # 3. Recalibrar
    recalibrate()

    print("\n" + "=" * 60)
    print("PROCESSO CONCLUÍDO")
    print("=" * 60)

if __name__ == "__main__":
    main()
