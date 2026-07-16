"""
fix_config_duplicates.py
========================
Script standalone para remover pws_station_id duplicados em cities/config.py.

NÃO importa cities.config (porque o config.py pode estar com erro de sintaxe).
Lê o ficheiro como texto, faz parse com regex e remove duplicatas.

Uso:
    python fix_config_duplicates.py
    python fix_config_duplicates.py --dry-run   # ver sem aplicar
"""

import argparse
import re
import shutil
from pathlib import Path
from datetime import datetime


def fix_config(config_path: Path, dry_run: bool = False) -> dict:
    """Remove pws_station_id duplicados em cada bloco CityConfig."""
    if not config_path.exists():
        return {"error": f"Ficheiro não encontrado: {config_path}"}

    src = config_path.read_text()

    # Pattern: cada bloco CityConfig começa com "name": CityConfig( e acaba em ),
    # Vamos processar linha a linha, detectando início/fim de blocos
    lines = src.split('\n')
    new_lines = []
    in_city_block = False
    seen_pws_in_block = False
    n_removed = 0
    n_blocks_processed = 0
    current_city_name = None

    for i, line in enumerate(lines):
        # Detectar início de bloco CityConfig
        # Padrão: "city_name": CityConfig(
        m_start = re.match(r'\s*"(\w+)": CityConfig\(', line)
        if m_start:
            in_city_block = True
            seen_pws_in_block = False
            current_city_name = m_start.group(1)
            n_blocks_processed += 1
            new_lines.append(line)
            continue

        # Detectar fim de bloco (linha com "),")
        if in_city_block and re.match(r'\s*\),\s*$', line):
            in_city_block = False
            current_city_name = None
            new_lines.append(line)
            continue

        # Dentro de bloco: verificar pws_station_id
        if in_city_block:
            m_pws = re.search(r'pws_station_id="([^"]+)"', line)
            if m_pws:
                if seen_pws_in_block:
                    # DUPLICADA — remover esta linha
                    n_removed += 1
                    print(f"  ✓ Removendo duplicada em {current_city_name}: {line.strip()}")
                    continue  # skip esta linha
                else:
                    # 1ª ocorrência — manter
                    seen_pws_in_block = True

            # Activar wu_history_path se for None (também corrige)
            # Procurar wu_history_path=None nesta linha
            if 'wu_history_path=None' in line:
                new_line = line.replace('wu_history_path=None', 'wu_history_path="pws"')
                if new_line != line:
                    print(f"  ✓ Activando wu_history_path em {current_city_name}: None → \"pws\"")
                    line = new_line

        new_lines.append(line)

    new_src = '\n'.join(new_lines)

    if new_src == src:
        return {
            "changed": False,
            "n_removed": 0,
            "n_blocks": n_blocks_processed,
            "message": "Nenhuma alteração necessária — config.py já está limpo."
        }

    if dry_run:
        return {
            "changed": True,
            "n_removed": n_removed,
            "n_blocks": n_blocks_processed,
            "dry_run": True,
            "message": f"[DRY-RUN] Removeria {n_removed} linhas duplicadas."
        }

    # Backup com timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = config_path.with_suffix(f".py.bak_{timestamp}")
    shutil.copy2(config_path, backup_path)

    # Escrever
    config_path.write_text(new_src)

    return {
        "changed": True,
        "n_removed": n_removed,
        "n_blocks": n_blocks_processed,
        "backup": str(backup_path),
        "message": f"✓ {n_removed} linhas duplicadas removidas em {n_blocks_processed} blocos."
    }


def verify_config(config_path: Path) -> bool:
    """Verifica se o config.py tem sintaxe válida."""
    import subprocess
    result = subprocess.run(
        ["python", "-c", "from cities.config import CITIES; print(f'OK: {len(CITIES)} cidades carregadas')"],
        capture_output=True, text=True, cwd=config_path.parent.parent,
    )
    print(result.stdout, end='')
    if result.stderr:
        print(result.stderr, end='')
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Remove pws_station_id duplicados em cities/config.py")
    parser.add_argument("--dry-run", action="store_true", help="Ver sem aplicar alterações")
    parser.add_argument("--config", type=str, default="cities/config.py",
                        help="Caminho do config.py (default: cities/config.py)")
    args = parser.parse_args()

    config_path = Path(args.config)
    print(f"\n🔧 A analisar {config_path}...")

    if args.dry_run:
        print("⚠ MODO DRY-RUN — não vou aplicar alterações\n")

    result = fix_config(config_path, dry_run=args.dry_run)
    print(f"\n{result['message']}")

    if result.get("backup"):
        print(f"Backup: {result['backup']}")

    if result.get("changed") and not args.dry_run:
        print(f"\n📋 A verificar sintaxe...")
        if verify_config(config_path):
            print("\n✅ config.py está válido e pronto a usar!")
            print("\nPróximos passos:")
            print("  1. Re-corre o discover:")
            print("     python discover_pws_from_wu_pages.py --apply")
            print("  2. Verifica resultado:")
            print("     python -c \"from cities.config import CITIES; [print(f'  {n:18s} wu={c.wu_history_path} pws={getattr(c, \\\"pws_station_id\\\", \\\"\\\")}') for n, c in CITIES.items()]\"")
        else:
            print("\n❌ config.py ainda tem erro de sintaxe. Verifica manualmente.")


if __name__ == "__main__":
    main()
