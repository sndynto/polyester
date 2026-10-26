import asyncio
import json
import os
import random
import sys
import time
import email.utils
from decimal import Decimal, ROUND_DOWN

import httpx
from polyester import AsyncPolyester, Price, format_ledger_u128
import polyester.auth as auth
from polyester.errors import PolyesterError, PolyesterAuthError, PolyesterApiError
import config

# Color terminal helpers
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

def log(msg: str, color: str = Colors.RESET, prefix: str = ""):
    timestamp = time.strftime("%H:%M:%S")
    tag = f"[{prefix}] " if prefix else ""
    print(f"{Colors.BOLD}[{timestamp}]{Colors.RESET} {tag}{color}{msg}{Colors.RESET}")

def sync_clock_with_server():
    """Sinkronisasi waktu lokal dengan server Polyester agar tidak terjadi error TIMESTAMP_SKEW"""
    try:
        r = httpx.get("https://api.testnet.polyester.com", timeout=5.0)
        server_date = r.headers.get("date")
        if server_date:
            server_ts = email.utils.parsedate_to_datetime(server_date).timestamp()
            skew_seconds = time.time() - server_ts
            skew_ns = int(skew_seconds * 1_000_000_000)
            
            if abs(skew_seconds) > 1.0:
                log(f"Clock skew terdeteksi: Jam PC Anda beda {skew_seconds:+.2f}s dari server.", Colors.YELLOW)
                log("Mengaktifkan kompensasi waktu otomatis...", Colors.CYAN)
                
                def patched_try_next(self):
                    now = (time.time_ns() - skew_ns) // 1_000_000
                    with self._lock:
                        candidate = max(now, self._last_timestamp_ms + 1)
                        self._last_timestamp_ms = candidate
                        return candidate
                
                auth._SigningTimestampAllocator._try_next = patched_try_next
                log("Waktu berhasil disinkronkan dengan server Polyester!", Colors.GREEN)
    except Exception as e:
        log(f"Info sync waktu: {e}", Colors.YELLOW)

class AccountSession:
    def __init__(self, account_data: dict, total_cycles: int):
        self.name = account_data.get("name", "Akun")
        self.api_key_id = account_data.get("api_key_id", "").strip()
        self.api_private_key = account_data.get("api_private_key", "").strip()
        self.account_id = account_data.get("account_id", "").strip()
        self.proxy = account_data.get("proxy", "").strip()
        self.total_cycles = total_cycles
        
        self.client: AsyncPolyester | None = None
        self.enabled_pairs: dict[str, dict] = {}
        self.total_tx_count = 0
        self.total_volume_usd = Decimal("0.0")

    def is_valid(self) -> bool:
        return bool(self.api_key_id and self.api_private_key)

    async def initialize(self):
        log("Menghubungkan ke Polyester Testnet API...", Colors.CYAN, self.name)
        
        # Set proxy jika ada
        if self.proxy:
            os.environ["HTTP_PROXY"] = self.proxy
            os.environ["HTTPS_PROXY"] = self.proxy
            log(f"Menggunakan Proxy: {self.proxy}", Colors.BLUE, self.name)
        else:
            os.environ.pop("HTTP_PROXY", None)
            os.environ.pop("HTTPS_PROXY", None)

        self.client = AsyncPolyester(
            api_key_id=self.api_key_id,
            api_private_key=self.api_private_key,
            default_account_id=self.account_id if self.account_id else None,
            environment=config.CUSTOM_TESTNET_ENV
        )

        try:
            await self.client.wait_for_catalogs()
        except Exception as e:
            log(f"Gagal memuat katalog: {e}", Colors.RED, self.name)
            raise

        spot_config = self.client.catalogs.spot_config or {}
        raw_pairs = spot_config.get("pairs", [])
        for p in raw_pairs:
            if p.get("status") == "PAIR_STATUS_ENABLED":
                symbol = p.get("symbol")
                self.enabled_pairs[symbol] = p

    async def get_balances(self) -> dict[str, Decimal]:
        balances = {}
        try:
            res = await self.client.balances.list()
            spot_config = self.client.catalogs.spot_config or {}
            assets = {a["ledgerId"]: a["asset"] for a in spot_config.get("assets", [])}
            
            for b in res.balances:
                avail_int = int(b.available)
                if avail_int > 0:
                    asset_name = assets.get(b.asset_id, f"ID_{b.asset_id}")
                    formatted_str = format_ledger_u128(avail_int)
                    balances[asset_name] = Decimal(formatted_str)
        except Exception as e:
            log(f"Info cek saldo: {e}", Colors.YELLOW, self.name)
        return balances

    def print_balances(self, balances: dict[str, Decimal]):
        log("--- Saldo Testnet Saat Ini ---", Colors.BOLD, self.name)
        if not balances:
            log("  (Belum ada saldo terdeteksi atau akun baru. Pastikan sudah claim faucet di web!)", Colors.YELLOW, self.name)
        for asset, amt in balances.items():
            log(f"  {asset}: {amt}", Colors.GREEN, self.name)
        log("-----------------------------", Colors.BOLD, self.name)

    async def cancel_all_open_orders(self, symbol: str | None = None):
        try:
            if symbol:
                await self.client.orders.cancel_all(symbol=symbol)
            else:
                await self.client.orders.cancel_all()
            log(f"Open orders dibersihkan {f'({symbol})' if symbol else '(semua)'}.", Colors.BLUE, self.name)
        except Exception:
            pass

    def calculate_order_qty(self, pair_info: dict, side: str, available_funds: Decimal, ob_price_ticks: int) -> tuple[str, Decimal]:
        min_qty_base = Decimal(str(pair_info.get("min_qty_base", "0.001")))
        step_size = Decimal(str(pair_info.get("step_size", "0.000001")))

        actual_price = Decimal(ob_price_ticks) / Decimal("1000000000")
        if actual_price <= 0:
            actual_price = Decimal("1.0")

        target_notional = Decimal(str(round(random.uniform(7.5, 14.0), 2)))
        qty = target_notional / actual_price
        if qty < min_qty_base:
            qty = min_qty_base * Decimal("1.1")

        steps = (qty / step_size).quantize(Decimal("1"), rounding=ROUND_DOWN)
        final_qty = steps * step_size

        if final_qty < min_qty_base:
            final_qty = min_qty_base

        est_notional = final_qty * actual_price
        return str(final_qty), est_notional

    async def execute_trade_cycle(self, cycle_num: int, pair_symbol: str):
        log(f"[{cycle_num}/{self.total_cycles}] Memulai trade di {pair_symbol}...", Colors.BOLD, self.name)

        if pair_symbol not in self.enabled_pairs:
            return

        pair_info = self.enabled_pairs[pair_symbol]
        base_asset = pair_info.get("baseAsset", "BASE")
        quote_asset = pair_info.get("quoteAsset", "USDT")

        if config.AUTO_CANCEL_OPEN:
            await self.cancel_all_open_orders(pair_symbol)
            await asyncio.sleep(0.5)

        try:
            ob = await self.client.orderbook.get(symbol=pair_symbol)
            if not ob.bids or not ob.asks:
                return
            best_bid = ob.bids[0]
            best_ask = ob.asks[0]
        except Exception as e:
            log(f"Gagal orderbook {pair_symbol}: {e}", Colors.RED, self.name)
            return

        balances = await self.get_balances()
        base_bal = balances.get(base_asset, Decimal("0"))
        quote_bal = balances.get(quote_asset, Decimal("0"))

        min_qty_base = Decimal(str(pair_info.get("min_qty_base", "0.001")))
        step_size = Decimal(str(pair_info.get("step_size", "0.000001")))

        bid_price_usd = Decimal(best_bid.price.ticks) / Decimal("1000000000")
        base_val_usd = base_bal * bid_price_usd

        if base_val_usd >= Decimal("5.5"):
            side = "sell"
            chosen_price = best_bid.price
            order_qty, notional = self.calculate_order_qty(pair_info, side, base_bal, best_bid.price.ticks)
            
            if Decimal(order_qty) > base_bal or base_val_usd < Decimal("15.0"):
                steps = (base_bal / step_size).quantize(Decimal("1"), rounding=ROUND_DOWN)
                order_qty = str(steps * step_size)
                notional = Decimal(order_qty) * bid_price_usd
        else:
            side = "buy"
            chosen_price = best_ask.price
            order_qty, notional = self.calculate_order_qty(pair_info, side, quote_bal, best_ask.price.ticks)

        log(f"Detail: {side.upper()} {order_qty} {base_asset} @ ~${notional:.2f}", Colors.CYAN, self.name)

        try:
            order_res = await self.client.orders.create(
                symbol=pair_symbol,
                side=side,
                order_type="limit",
                price=chosen_price,
                qty=order_qty,
                tif="gtc"
            )
            self.total_tx_count += 1
            self.total_volume_usd += notional
            log(f"Order Berhasil! ID: {order_res.order_id} | Total Tx: {self.total_tx_count} | Vol: ~${self.total_volume_usd:.2f}", Colors.GREEN, self.name)
        except PolyesterApiError as ape:
            log(f"Pemberitahuan: {ape}", Colors.YELLOW, self.name)
        except Exception as e:
            log(f"Order gagal: {e}", Colors.RED, self.name)

    async def run(self):
        await self.initialize()
        initial_balances = await self.get_balances()
        self.print_balances(initial_balances)

        pairs_to_trade = [p for p in config.DEFAULT_PAIRS if p in self.enabled_pairs]
        if not pairs_to_trade:
            pairs_to_trade = [p for p in ["DOGE-USDT", "ETH-USDT", "SOL-USDT", "BTC-USDT", "AVAX-USDT"] if p in self.enabled_pairs]

        for i in range(1, self.total_cycles + 1):
            pair = random.choice(pairs_to_trade)
            try:
                await self.execute_trade_cycle(i, pair)
            except Exception as e:
                log(f"Kesalahan siklus {i}: {e}", Colors.RED, self.name)

            if i < self.total_cycles:
                delay = random.randint(config.MIN_DELAY, config.MAX_DELAY)
                log(f"Menunggu {delay}s untuk trade berikutnya...", Colors.YELLOW, self.name)
                await asyncio.sleep(delay)

        final_balances = await self.get_balances()
        self.print_balances(final_balances)

        if self.client:
            await self.client.aclose()

class MultiAccountManager:
    def __init__(self):
        self.accounts: list[dict] = []
        self.load_accounts()

    def load_accounts(self):
        accounts_file = "accounts.json"
        if os.path.exists(accounts_file):
            try:
                with open(accounts_file, "r") as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        self.accounts = [acc for acc in data if acc.get("api_key_id") and acc.get("api_private_key")]
                        if self.accounts:
                            log(f"Mode Multi-Akun Aktif: Ditemukan {len(self.accounts)} akun di accounts.json.", Colors.GREEN)
                            return
            except Exception as e:
                log(f"Peringatan membaca accounts.json: {e}", Colors.YELLOW)

        # Fallback to single account from .env
        if config.API_KEY_ID and config.API_PRIVATE_KEY:
            self.accounts = [
                {
                    "name": "Akun Utama",
                    "api_key_id": config.API_KEY_ID,
                    "api_private_key": config.API_PRIVATE_KEY,
                    "account_id": config.ACCOUNT_ID,
                    "proxy": ""
                }
            ]
            log("Mode Single-Akun Aktif (Memuat dari .env).", Colors.CYAN)
        else:
            log("Tidak ada akun ditemukan di accounts.json maupun .env!", Colors.RED)

    async def run(self):
        if not self.accounts:
            log("Silakan masukkan akun di accounts.json atau .env!", Colors.RED)
            return

        sync_clock_with_server()

        summary_results = []
        total_accounts = len(self.accounts)

        log("=" * 60, Colors.BOLD)
        log(f"MEMULAI SESI TRADING POLYESTER UNTUK {total_accounts} AKUN", Colors.BOLD)
        log("=" * 60, Colors.BOLD)

        for idx, acc_data in enumerate(self.accounts, 1):
            acc_name = acc_data.get("name", f"Akun {idx}")
            log(f"\n>>> [{idx}/{total_accounts}] MEMPROSES {acc_name.upper()} <<<", Colors.HEADER)

            session = AccountSession(acc_data, config.TOTAL_CYCLES)
            try:
                await session.run()
                summary_results.append({
                    "name": acc_name,
                    "status": "Sukses",
                    "tx_count": session.total_tx_count,
                    "volume": session.total_volume_usd
                })
            except Exception as e:
                log(f"Gagal memproses {acc_name}: {e}", Colors.RED)
                summary_results.append({
                    "name": acc_name,
                    "status": f"Gagal ({e})",
                    "tx_count": session.total_tx_count,
                    "volume": session.total_volume_usd
                })

            # Jeda acak antar akun (Anti-Sybil Cooldown)
            if idx < total_accounts:
                cooldown = random.randint(15, 35)
                log(f"\nJeda antar akun: Menunggu {cooldown} detik sebelum pindah ke akun berikutnya (Anti-Sybil)...", Colors.YELLOW)
                await asyncio.sleep(cooldown)

        # Cetak Rekapitulasi Akhir
        print("\n" + "=" * 65)
        log("REKAPITULASI SESI TRADING SEMUA AKUN", Colors.GREEN)
        print("=" * 65)
        total_all_tx = 0
        total_all_vol = Decimal("0.0")
        for res in summary_results:
            log(f"  {res['name']:<15} | Status: {res['status']:<8} | Tx: {res['tx_count']} | Vol: ~${res['volume']:.2f}", Colors.BOLD)
            total_all_tx += res["tx_count"]
            total_all_vol += res["volume"]
        print("-" * 65)
        log(f"  TOTAL KESELURUHAN : Tx: {total_all_tx} | Total Volume: ~${total_all_vol:.2f}", Colors.HEADER)
        print("=" * 65 + "\n")

async def main():
    manager = MultiAccountManager()
    try:
        await manager.run()
    except KeyboardInterrupt:
        log("\nProses dihentikan oleh pengguna.", Colors.YELLOW)
    except Exception as e:
        log(f"\nFatal error: {e}", Colors.RED)

if __name__ == "__main__":
    asyncio.run(main())
