#!/usr/bin/env python3
"""
Remove dados futuros (2026) do novo CSV de Dallas, converte formato e retreina o modelo.
"""

import os
import shutil
import pandas as pd
from datetime import datetime
import subprocess

# Configurações
CITY = "dallas"
CUTOFF_DATE = "2026-01-01"  # Remover tudo >= 2026-01-01

def backup_file(filepath):
    """Faz backup do arquivo original."""
    backup_path = f"{filepath}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(filepath, backup_path)
    print(f"✅ Backup criado: {backup_path}")
    return backup_path

def clean_and_convert_dallas_csv():
    """Remove dados futuros do CSV de Dallas e converte para formato padrão."""
    csv_path = f"historic/{CITY}.csv"
    temp_path = f"historic/{CITY}_temp.csv"

    print(f"\n🔧 Limpando e convertendo {CITY}.csv...")

    # Backup
    backup_file(csv_path)

    # Ler o CSV
    df = pd.read_csv(csv_path)
    print(f"  Linhas antes: {len(df)}")
    print(f"  Colunas: {list(df.columns)}")

    # Converter timestamp para datetime (lidar com timezones mistas)
    df['timestamp_dt'] = pd.to_datetime(df['timestamp'], utc=True)

    # Remover dados de 2026
    before_2026 = len(df)
    df = df[df['timestamp_dt'].dt.year < 2026]
    after_2026 = len(df)
    removed = before_2026 - after_2026

    print(f"  Linhas depois (sem 2026): {len(df)}")
    print(f"  Removidas (2026): {removed} ({100*removed/before_2026:.1f}%)")

    # Converter para formato padrão (igual ao usado por train.py)
    df_output = pd.DataFrame({
        'date': df['timestamp_dt'].dt.strftime('%m/%d/%Y'),
        'time': df['timestamp_dt'].dt.strftime('%I:%M %p'),
        'timestamp_utc': df['timestamp_dt'].dt.strftime('%Y-%m-%d %H:%M:%S%z'),
        'temp_c': df['temp_c'],
        'dewpt_c': '',  # Não disponível no novo CSV
        'humidity_pct': df['humidity'],
        'pressure_hpa': df['pressure'],
        'wind_dir_deg': '',  # Não disponível
        'wind_dir_card': '',  # Não disponível
        'wind_speed_kmh': df['wind_kmh'],
        'wind_gust_kmh': '',  # Não disponível
        'precip_mm': df['precip_mm'],
        'wx_phrase': df['condition']
    })

    # Salvar no formato padrão
    df_output.to_csv(temp_path, index=False)
    print(f"✅ {CITY}.csv convertido para formato padrão")

    # Substituir original
    shutil.move(temp_path, csv_path)
    print(f"✅ {CITY}.csv atualizado")

    return len(df)

def retrain_model():
    """Retreina o modelo de Dallas."""
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
    """Recalibra o modelo de Dallas."""
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
    print("LIMPANDO DADOS FUTUROS DE DALLAS E RETREINANDO")
    print("=" * 60)

    # 1. Limpar e converter CSV
    clean_and_convert_dallas_csv()

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
