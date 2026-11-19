"""
=====================================================================
PATCH FASE 2 — polymarket_clob.py
=====================================================================
ADICIONA à classe ClobClient os métodos de redemption (redeemPositions).

Forma de aplicar (2 opções):

OPÇÃO A — MIXIN (recomendada, sem mexer no código existente):
  1. Copiar este ficheiro para a raiz do projeto.
  2. No topo do polymarket_clob.py, adicionar:
        from polymarket_clob_redeem_patch import RedeemMixin, \
               POLYGON_RPC, CONDITIONAL_TOKENS_ADDR, CTF_EXCHANGE_ADDR, REDEEM_ABI
  3. Mudar a declaração da classe:
        class ClobClient(RedeemMixin):
            ...

OPÇÃO B — CÓPIA MANUAL (colar dentro da classe existente):
  1. Copiar as constantes (POLYGON_RPC, etc.) para o topo do polymarket_clob.py
  2. Copiar os métodos _redeem_via_ctf_exchange, redeem_winning_position e
     redeem_all_winning_real_positions para dentro da classe ClobClient
     (atenção à indentação de 4 espaços).

Os métodos ficam disponíveis como client.redeem_winning_position(pos)
e client.redeem_all_winning_real_positions(dry_run=True).
=====================================================================
"""

# === Constantes a adicionar no topo do polymarket_clob.py ===
POLYGON_RPC = "https://polygon-rpc.com"
POLYGON_RPC_BACKUPS = [
    "https://polygon.llamarpc.com",
    "https://polygon.drpc.org",
]
CONDITIONAL_TOKENS_ADDR = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
CTF_EXCHANGE_ADDR = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

# ABI mínima para ConditionalTokens.redeemPositions + payoutNumerators
REDEEM_ABI = [
    {
        "inputs": [
            {"internalType": "bytes32", "name": "conditionId", "type": "bytes32"},
            {"internalType": "uint256[]", "name": "outcomeTokenCounts", "type": "uint256[]"}
        ],
        "name": "redeemPositions",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "conditionId", "type": "bytes32"}
        ],
        "name": "payoutNumerators",
        "outputs": [
            {"internalType": "uint256[]", "name": "", "type": "uint256[]"}
        ],
        "stateMutability": "view",
        "type": "function"
    }
]


class RedeemMixin:
    """Mixin a aplicar a ClobClient para adicionar capacidade de redemption.

    Requer que a classe base tenha: self.mode, self.log_dir, self.positions,
    e acesso a GAMMA_API + append_event (já existentes no polymarket_clob.py).
    """

    def _redeem_via_ctf_exchange(self, condition_id_bytes: bytes,
                                 outcome_counts: list,
                                 dry_run: bool = True) -> dict:
        """Chama redeemPositions no ConditionalTokens contract da Polygon.

        Retorna dict com: success, tx_hash (ou None), dry_run, error.
        """
        try:
            from web3 import Web3
            from eth_account import Account
        except ImportError as e:
            return {
                "success": False,
                "error": (
                    f"web3/eth_account não instalados: {e}. "
                    f"Instala com: pip install web3 eth-account"
                ),
                "dry_run": dry_run,
            }

        import os
        pk = os.environ.get("POLY_PRIVATE_KEY", "").strip()
        if not pk:
            return {"success": False,
                    "error": "POLY_PRIVATE_KEY não definida no env",
                    "dry_run": dry_run}

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "would_call": "ConditionalTokens.redeemPositions",
                "condition_id": "0x" + condition_id_bytes.hex(),
                "outcome_counts": outcome_counts,
                "contract": CONDITIONAL_TOKENS_ADDR,
            }

        # Tentar várias RPCs (rate-limit)
        w3 = None
        for rpc in [POLYGON_RPC] + POLYGON_RPC_BACKUPS:
            try:
                w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 15}))
                if w3.is_connected():
                    break
            except Exception:
                continue
        if w3 is None or not w3.is_connected():
            return {"success": False,
                    "error": "Sem conectividade a nenhuma RPC Polygon",
                    "dry_run": False}

        try:
            account = Account.from_key(pk)
            wallet = account.address

            ct = w3.eth.contract(
                address=Web3.to_checksum_address(CONDITIONAL_TOKENS_ADDR),
                abi=REDEEM_ABI,
            )

            # Pré-check: payoutNumerators deve estar setado (mercado resolvido)
            payouts = ct.functions.payoutNumerators(condition_id_bytes).call()
            if not any(p > 0 for p in payouts):
                return {
                    "success": False,
                    "error": (
                        "Mercado ainda não resolvido on-chain "
                        "(payoutNumerifiers todos zero)"
                    ),
                    "dry_run": False,
                }

            nonce = w3.eth.get_transaction_count(wallet)
            tx = ct.functions.redeemPositions(
                condition_id_bytes, outcome_counts
            ).build_transaction({
                "from": wallet,
                "nonce": nonce,
                "gas": 250_000,
                "gasPrice": w3.eth.gas_price,
                "chainId": 137,
            })
            signed = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)

            return {
                "success": receipt.status == 1,
                "tx_hash": tx_hash.hex(),
                "gas_used": receipt.gasUsed,
                "dry_run": False,
                "error": None if receipt.status == 1 else "tx reverted",
            }
        except Exception as e:
            return {"success": False,
                    "error": f"{type(e).__name__}: {e}",
                    "dry_run": False}

    def redeem_winning_position(self, position, dry_run: bool = True) -> dict:
        """Resgata uma posição REAL vencedora (redeemPositions no CTF).

        Pré-condições verificadas:
          - self.mode == TradingMode.REAL
          - position.mode == "real"
          - position.status == PositionStatus.WON
          - mercado resolvido oficialmente (Gamma + on-chain payoutNumerators)

        Em dry_run (default): não envia tx, só reporta o que faria.
        Em execução real: envia a tx, espera receipt, marca como redeemed.
        """
        from datetime import datetime as _dt

        # TradingMode é importado no polymarket_clob.py
        from polymarket_clob import TradingMode, PositionStatus, GAMMA_API
        from trade_ledger import append_event

        result = {
            "position_id": position.position_id,
            "market_slug": position.market_slug,
            "token_id": position.token_id,
            "shares": position.shares,
            "entry_ask": position.entry_ask,
            "dry_run": dry_run,
        }

        # Guards
        if self.mode != TradingMode.REAL:
            result.update(success=False,
                          skip_reason="ClobClient não está em modo REAL")
            return result
        if getattr(position, "mode", "") != "real":
            result.update(success=False,
                          skip_reason=f"position.mode='{getattr(position, 'mode', '')}' (não real)")
            return result
        if position.status != PositionStatus.WON:
            result.update(success=False,
                          skip_reason=f"position.status={position.status.value} (não WON)")
            return result
        if getattr(position, "redemption_completed", False):
            result.update(success=False,
                          skip_reason="já resgatada (redemption_completed=True)")
            return result

        # Verificar resolução oficial
        resolved, won = self.positions._check_resolution(position)
        if not resolved:
            result.update(success=False,
                          skip_reason="mercado ainda não resolvido oficialmente (Gamma)")
            return result
        if not won:
            result.update(success=False,
                          skip_reason="posição perdeu oficialmente — nada a resgatar")
            return result

        # Obter conditionId do mercado via Gamma
        condition_id_hex = None
        try:
            import requests
            r = requests.get(
                f"{GAMMA_API}/events",
                params={"slug": position.market_slug},
                timeout=15,
            )
            r.raise_for_status()
            ev = r.json()
            ev = ev[0] if isinstance(ev, list) and ev else ev
            import json as _json
            for m in ev.get("markets", []):
                tids = m.get("clobTokenIds", "[]")
                if isinstance(tids, str):
                    try:
                        tids = _json.loads(tids)
                    except Exception:
                        tids = []
                if position.token_id in (tids or []):
                    condition_id_hex = m.get("conditionId") or m.get("condition_id")
                    break
        except Exception as e:
            result.update(success=False,
                          error=f"Gamma fetch conditionId falhou: {e}")
            return result

        if not condition_id_hex:
            result.update(success=False,
                          skip_reason="conditionId não encontrado no Gamma para este mercado")
            return result

        # hex → bytes32
        try:
            if condition_id_hex.startswith("0x"):
                condition_id_hex = condition_id_hex[2:]
            condition_id_bytes = bytes.fromhex(condition_id_hex)
            if len(condition_id_bytes) != 32:
                raise ValueError(f"tamanho {len(condition_id_bytes)} != 32")
        except Exception as e:
            result.update(success=False,
                          error=f"conditionId inválido: {e}")
            return result

        # Mercados Polymarket Weather são binários: outcomeSlotCount=2
        redeem_result = self._redeem_via_ctf_exchange(
            condition_id_bytes, outcome_counts=[2], dry_run=dry_run,
        )

        if redeem_result.get("success"):
            ts = _dt.now().isoformat()
            position.redemption_completed = True
            position.last_updated = ts
            if redeem_result.get("tx_hash"):
                position.redemption_tx_hash = redeem_result["tx_hash"]
            self.positions._save()
            append_event({
                "event_type": "REDEEM",
                "position_id": position.position_id,
                "market_slug": position.market_slug,
                "token_id": position.token_id,
                "redeemed_at": ts,
                "shares": position.shares,
                "entry_ask": position.entry_ask,
                "tx_hash": redeem_result.get("tx_hash"),
                "gas_used": redeem_result.get("gas_used"),
                "dry_run": dry_run,
                "mode": "real",
            })
            result.update(
                success=True,
                tx_hash=redeem_result.get("tx_hash"),
                gas_used=redeem_result.get("gas_used"),
            )
        else:
            result.update(
                success=False,
                error=redeem_result.get("error", "redeem falhou"),
            )

        return result

    def redeem_all_winning_real_positions(self, dry_run: bool = True) -> list:
        """Itera todas as posições REAL WON não-redimidas e tenta resgatar.

        Retorna lista de resultados (um por posição tentada).
        """
        from polymarket_clob import TradingMode, PositionStatus
        results = []
        if self.mode != TradingMode.REAL:
            return [{"success": False,
                     "skip_reason": "ClobClient não está em modo REAL"}]

        for pos in self.positions.all_positions():
            if getattr(pos, "mode", "") != "real":
                continue
            if pos.status != PositionStatus.WON:
                continue
            if getattr(pos, "redemption_completed", False):
                continue
            r = self.redeem_winning_position(pos, dry_run=dry_run)
            results.append(r)
        return results
