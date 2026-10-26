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

# Ensure UTF-8 output on Windows terminal
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Color terminal helpers
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    MAGENTA = '\033[35m'
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
                def patched_try_next(self):
                    now = (time.time_ns() - skew_ns) // 1_000_000
                    with self._lock:
                        candidate = max(now, self._last_timestamp_ms + 1)
                        self._last_timestamp_ms = candidate
                        return candidate
                
                auth._SigningTimestampAllocator._try_next = patched_try_next
                log(f"Waktu disinkronkan dengan server (Kompensasi: {skew_seconds:+.2f}s)", Colors.GREEN)
    except Exception as e:
        log(f"Info sync waktu: {e}", Colors.YELLOW)

class TraderPersona:
    """Menciptakan profil trader acak yang unik untuk setiap akun agar tidak terdeteksi Sybil"""
    def __init__(self, account_name: str, all_pairs: list[str], base_cycles: int):
        self.account_name = account_name
        
        # 1. Jumlah transaksi diacak per akun (misal target 30 -> diacak jadi 22 s/d 38)
        variance = max(3, int(base_cycles * 0.25))
        self.total_cycles = random.randint(base_cycles - variance, base_cycles + variance)
        if self.total_cycles < 5:
            self.total_cycles = 5

        # 2. Seluruh pasangan koin diaktifkan dan diacak urutan variasinya
        self.preferred_pairs = list(all_pairs)
        random.shuffle(self.preferred_pairs)

        # 3. Rentang nominal USD diacak per akun (agar tidak ada pola nilai seragam)
        self.min_order_usd = round(random.uniform(6.5, 9.0), 2)
        self.max_order_usd = round(random.uniform(11.5, 18.0), 2)

        # 4. Rentang delay unik per akun
        self.min_delay = random.randint(config.MIN_DELAY, config.MIN_DELAY + 8)
        self.max_delay = random.randint(config.MAX_DELAY - 5, config.MAX_DELAY + 15)
        if self.min_delay >= self.max_delay:
            self.max_delay = self.min_delay + 10

        # 5. Gaya trading (Persentase jual kembali vs hold koin)
        self.sell_bias = random.choice([0.5, 0.6, 0.7])  # Random probabilitas

    def describe(self):
        sample_disp = ", ".join(self.preferred_pairs[:6]) + f" ... (+{len(self.preferred_pairs)-6} pair lainnya)" if len(self.preferred_pairs) > 6 else ", ".join(self.preferred_pairs)
        return (
            f"Persona: {self.total_cycles} Siklus | "
            f"Nominal: ${self.min_order_usd:.2f}-${self.max_order_usd:.2f} | "
            f"Jeda: {self.min_delay}-{self.max_delay}s | "
            f"Multi-Pair ({len(self.preferred_pairs)}): {sample_disp}"
        )

class AccountSession:
    def __init__(self, account_data: dict, base_cycles: int):
        self.name = account_data.get("name", "Akun")
        self.api_key_id = account_data.get("api_key_id", "").strip()
        self.api_private_key = account_data.get("api_private_key", "").strip()
        self.account_id = account_data.get("account_id", "").strip()
        self.proxy = account_data.get("proxy", "").strip()
        self.base_cycles = base_cycles
        
        self.client: AsyncPolyester | None = None
        self.enabled_pairs: dict[str, dict] = {}
        self.persona: TraderPersona | None = None
        self.total_tx_count = 0
        self.total_volume_usd = Decimal("0.0")
        self.auth_failed = False

    def is_valid(self) -> bool:
        return bool(self.api_key_id and self.api_private_key)

    async def initialize(self):
        log("Menghubungkan ke Polyester API...", Colors.CYAN, self.name)
        
        # Isolasi Proxy per Akun
        if self.proxy:
            os.environ["HTTP_PROXY"] = self.proxy
            os.environ["HTTPS_PROXY"] = self.proxy
            log(f"Proxy Terhubung: {self.proxy}", Colors.BLUE, self.name)
        else:
            os.environ.pop("HTTP_PROXY", None)
            os.environ.pop("HTTPS_PROXY", None)

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                self.client = AsyncPolyester(
                    api_key_id=self.api_key_id,
                    api_private_key=self.api_private_key,
                    environment=config.CUSTOM_TESTNET_ENV,
                    timeout=30.0
                )
                await self.client.wait_for_catalogs()
                break
            except Exception as e:
                if self.client:
                    await self.client.aclose()
                if attempt == max_retries:
                    log(f"Gagal memuat katalog setelah {max_retries}x percobaan: {e}", Colors.RED, self.name)
                    raise
                log(f"Koneksi/katalog lambat ({e}). Mencoba ulang ({attempt}/{max_retries}) dalam 3 detik...", Colors.YELLOW, self.name)
                await asyncio.sleep(3)

        spot_config = self.client.catalogs.spot_config or {}
        raw_pairs = spot_config.get("pairs", [])
        for p in raw_pairs:
            if p.get("status") == "PAIR_STATUS_ENABLED":
                symbol = p.get("symbol")
                self.enabled_pairs[symbol] = p

        # Inisialisasi Persona Anti-Sybil Unik untuk Akun ini
        available_target_pairs = [p for p in config.DEFAULT_PAIRS if p in self.enabled_pairs]
        if not available_target_pairs:
            available_target_pairs = list(self.enabled_pairs.keys())

        self.persona = TraderPersona(self.name, available_target_pairs, self.base_cycles)
        log(f"🛡️ Anti-Sybil Profil: {self.persona.describe()}", Colors.MAGENTA, self.name)

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
        except PolyesterAuthError as ae:
            self.auth_failed = True
            log(f"❌ Autentikasi Gagal: Kunci API / Private Key ditolak server ({ae})!", Colors.RED, self.name)
        except Exception as e:
            err_str = str(e)
            if "Unauthorized" in err_str or "SIGNATURE_INVALID" in err_str or "without server error details" in err_str:
                self.auth_failed = True
                log(f"❌ Autentikasi Gagal: Kunci API / Private Key tidak cocok ({err_str})!", Colors.RED, self.name)
            else:
                log(f"Info cek saldo: {e}", Colors.YELLOW, self.name)
        return balances

    def print_balances(self, balances: dict[str, Decimal]):
        if self.auth_failed:
            return
        log("--- Saldo Trading Account ---", Colors.BOLD, self.name)
        if not balances:
            log("  (Belum ada saldo terdeteksi. Pastikan sudah claim faucet di web!)", Colors.YELLOW, self.name)

        # Perkiraan nilai tukar kasar untuk menghitung Total Equity
        prices_usd = {
            "USDT": Decimal("1.0"),
            "USDC": Decimal("1.0"),
            "BTC": Decimal("68000.0"),
            "ETH": Decimal("2500.0"),
            "SOL": Decimal("165.0"),
            "DOGE": Decimal("0.145"),
            "AVAX": Decimal("26.0")
        }
        total_usd = Decimal("0.0")

        for asset, amt in balances.items():
            est_val = amt * prices_usd.get(asset, Decimal("0.0"))
            total_usd += est_val
            if est_val > Decimal("0.05") and asset != "USDT":
                log(f"  {asset}: {amt} (~${est_val:.2f} USD)", Colors.GREEN, self.name)
            else:
                log(f"  {asset}: {amt}", Colors.GREEN, self.name)

        if total_usd > Decimal("0.0"):
            log(f"  💰 Total Estimasi Equity Portofolio: ~${total_usd:.2f} USD (Sesuai web)", Colors.CYAN, self.name)
        log("-----------------------------", Colors.BOLD, self.name)

    async def cancel_all_open_orders(self, symbol: str | None = None):
        try:
            if symbol:
                await self.client.orders.cancel_all(symbol=symbol)
            else:
                await self.client.orders.cancel_all()
        except Exception:
            pass

    def calculate_order_qty(self, pair_info: dict, side: str, available_funds: Decimal, ob_price_ticks: int) -> tuple[str, Decimal]:
        min_qty_base = Decimal(str(pair_info.get("min_qty_base", "0.001")))
        step_size = Decimal(str(pair_info.get("step_size", "0.000001")))

        actual_price = Decimal(ob_price_ticks) / Decimal("1000000000")
        if actual_price <= 0:
            actual_price = Decimal("1.0")

        # Nominal acak spesifik sesuai rentang persona akun ini
        target_notional = Decimal(str(round(random.uniform(self.persona.min_order_usd, self.persona.max_order_usd), 2)))
        qty = target_notional / actual_price
        if qty < min_qty_base:
            qty = min_qty_base * Decimal("1.15")

        # Sesuaikan dengan step_size
        steps = (qty / step_size).quantize(Decimal("1"), rounding=ROUND_DOWN)
        final_qty = steps * step_size

        if final_qty < min_qty_base:
            final_qty = min_qty_base

        est_notional = final_qty * actual_price
        return str(final_qty), est_notional

    async def execute_trade_cycle(self, cycle_num: int, pair_symbol: str):
        log(f"[{cycle_num}/{self.persona.total_cycles}] Memulai trade di {pair_symbol}...", Colors.BOLD, self.name)

        if pair_symbol not in self.enabled_pairs:
            return

        pair_info = self.enabled_pairs[pair_symbol]
        base_asset = pair_info.get("baseAsset", "BASE")
        quote_asset = pair_info.get("quoteAsset", "USDT")

        if config.AUTO_CANCEL_OPEN:
            await self.cancel_all_open_orders(pair_symbol)
            await asyncio.sleep(1.2)

        try:
            ob = await self.client.orderbook.get(symbol=pair_symbol)
            if not ob.bids or not ob.asks:
                return
            best_bid = ob.bids[0]
            best_ask = ob.asks[0]
        except Exception as e:
            log(f"Gagal orderbook {pair_symbol}: {e}", Colors.RED, self.name)
            return

        await asyncio.sleep(0.8)
        balances = await self.get_balances()
        base_bal = balances.get(base_asset, Decimal("0"))
        quote_bal = balances.get(quote_asset, Decimal("0"))

        min_qty_base = Decimal(str(pair_info.get("min_qty_base", "0.001")))
        step_size = Decimal(str(pair_info.get("step_size", "0.000001")))

        bid_price_usd = Decimal(best_bid.price.ticks) / Decimal("1000000000")
        base_val_usd = base_bal * bid_price_usd

        # Jika saldo quote tidak cukup untuk buy dan saldo base tidak cukup untuk sell,
        # alihkan otomatis ke pair lain yang quote-nya memiliki saldo mencukupi (misal USDT)
        if base_val_usd < Decimal("5.5") and quote_bal < Decimal("5.5"):
            viable_pairs = [
                p for p in self.persona.preferred_pairs
                if p in self.enabled_pairs and balances.get(self.enabled_pairs[p].get("quoteAsset", ""), Decimal("0")) >= Decimal("5.5")
            ]
            if viable_pairs:
                fallback_pair = random.choice(viable_pairs)
                if fallback_pair != pair_symbol:
                    return await self.execute_trade_cycle(cycle_num, fallback_pair)
            log(f"Saldo belum mencukupi untuk trading di {pair_symbol}.", Colors.YELLOW, self.name)
            return

        # Tentukan side berdasarkan saldo & bobot persona unik
        if base_val_usd >= Decimal("5.5") and random.random() < self.persona.sell_bias:
            side = "sell"
            chosen_price = best_bid.price
            order_qty, notional = self.calculate_order_qty(pair_info, side, base_bal, best_bid.price.ticks)
            
            if Decimal(order_qty) > base_bal or base_val_usd < Decimal("16.0"):
                steps = (base_bal / step_size).quantize(Decimal("1"), rounding=ROUND_DOWN)
                order_qty = str(steps * step_size)
                notional = Decimal(order_qty) * bid_price_usd
        elif quote_bal >= Decimal("5.5"):
            side = "buy"
            chosen_price = best_ask.price
            order_qty, notional = self.calculate_order_qty(pair_info, side, quote_bal, best_ask.price.ticks)
        else:
            return

        log(f"Order: {side.upper()} {order_qty} {base_asset} @ ~${notional:.2f}", Colors.CYAN, self.name)

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
            log(f"Eksekusi Sukses! ID: {order_res.order_id} | Total Tx: {self.total_tx_count} | Vol: ~${self.total_volume_usd:.2f}", Colors.GREEN, self.name)
        except PolyesterApiError as ape:
            log(f"Pemberitahuan: {ape}", Colors.YELLOW, self.name)
        except Exception as e:
            log(f"Order gagal: {e}", Colors.RED, self.name)

    def has_tradable_balance(self, balances: dict[str, Decimal]) -> bool:
        if not balances:
            return False
        # USDT mencukupi minimum notional DEX ($5.0)
        if balances.get("USDT", Decimal("0")) >= Decimal("5.0"):
            return True
        # Atau ada token lain yang berpotensi bisa dijual
        for asset, amt in balances.items():
            if asset != "USDT" and amt > Decimal("0.0001"):
                return True
        return False

    async def run(self) -> str:
        await self.initialize()
        initial_balances = await self.get_balances()
        self.print_balances(initial_balances)

        if self.auth_failed:
            log("❌ Melewati akun ini karena API Key / Private Key tidak cocok (Bukan karena saldo kosong).", Colors.RED, self.name)
            if self.client:
                await self.client.aclose()
            return "Dilewati (Kunci Salah)"

        if not self.has_tradable_balance(initial_balances):
            log("⚠️ Saldo tidak mencukupi untuk trading (minimal $5.00 USDT atau token spot). Melewati akun ini (SKIP)...", Colors.YELLOW, self.name)
            if self.client:
                await self.client.aclose()
            return "Dilewati (Tanpa Saldo)"

        pairs = self.persona.preferred_pairs

        for i in range(1, self.persona.total_cycles + 1):
            pair = random.choice(pairs)
            try:
                await self.execute_trade_cycle(i, pair)
            except (KeyboardInterrupt, asyncio.CancelledError):
                raise
            except Exception as e:
                log(f"Kesalahan siklus {i}: {e}", Colors.RED, self.name)

            if i < self.persona.total_cycles:
                # Delay unik per transaksi sesuai profil akun
                delay = random.randint(self.persona.min_delay, self.persona.max_delay)
                log(f"Jeda acak {delay}s sebelum order berikutnya...", Colors.YELLOW, self.name)
                await asyncio.sleep(delay)

        final_balances = await self.get_balances()
        self.print_balances(final_balances)

        if self.client:
            await self.client.aclose()
        return "Sukses"

class MultiAccountManager:
    def __init__(self):
        self.accounts: list[dict] = []
        self.load_accounts()

    def load_accounts(self):
        accounts_file = "accounts.json"
        if os.path.exists(accounts_file):
            try:
                with open(accounts_file, "r") as f:
                    content = f.read().strip()
                if content:
                    data = json.loads(content)
                    if isinstance(data, list) and len(data) > 0:
                        self.accounts = [acc for acc in data if acc.get("api_key_id") and acc.get("api_private_key")]
                        if self.accounts:
                            log(f"Mode Multi-Akun Aktif: Ditemukan {len(self.accounts)} akun.", Colors.GREEN)
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

        # Acak urutan eksekusi akun agar urutan hariannya tidak monoton (Anti-Sybil Sequence)
        run_accounts = list(self.accounts)
        if len(run_accounts) > 1:
            random.shuffle(run_accounts)
            log("Urutan eksekusi akun diacak (Anti-Sybil Sequence Shuffle).", Colors.MAGENTA)

        summary_results = []
        total_accounts = len(run_accounts)

        log("=" * 65, Colors.BOLD)
        log(f"MEMULAI SESI TRADING UNTUK {total_accounts} AKUN (ANTI-SYBIL ACTIVE)", Colors.BOLD)
        log("=" * 65, Colors.BOLD)

        for idx, acc_data in enumerate(run_accounts, 1):
            acc_name = acc_data.get("name", f"Akun {idx}")
            log(f"\n{'='*20} [{idx}/{total_accounts}] MEMPROSES: {acc_name.upper()} {'='*20}", Colors.HEADER)

            session = AccountSession(acc_data, config.TOTAL_CYCLES)
            status_text = "Sukses"
            try:
                run_res = await session.run()
                if run_res:
                    status_text = run_res
                summary_results.append({
                    "name": acc_name,
                    "status": status_text,
                    "tx_count": session.total_tx_count,
                    "volume": session.total_volume_usd
                })
            except Exception as e:
                log(f"Gagal memproses {acc_name}: {e}", Colors.RED)
                status_text = "Gagal"
                summary_results.append({
                    "name": acc_name,
                    "status": "Gagal",
                    "tx_count": session.total_tx_count,
                    "volume": session.total_volume_usd
                })

            # Jeda acak antar akun (Anti-Sybil Inter-Account Cooldown)
            if idx < total_accounts:
                if "Dilewati" in status_text or status_text == "Gagal":
                    cooldown = 3
                    log(f"\nAkun selesai (status: {status_text}), lanjut ke akun berikutnya dalam {cooldown} detik...", Colors.YELLOW)
                else:
                    cooldown = random.randint(30, 85)
                    log(f"\n⏳ Anti-Sybil Cooldown: Menunggu jeda {cooldown} detik sebelum berpindah ke akun berikutnya...", Colors.YELLOW)
                await asyncio.sleep(cooldown)

        # Cetak Rekapitulasi Akhir
        print("\n" + "=" * 65)
        log("REKAPITULASI SESI TRADING SELURUH AKUN", Colors.GREEN)
        print("=" * 65)
        total_all_tx = 0
        total_all_vol = Decimal("0.0")
        for res in summary_results:
            log(f"  {res['name']:<15} | Status: {res['status']:<23} | Tx: {res['tx_count']} | Vol: ~${res['volume']:.2f}", Colors.BOLD)
            total_all_tx += res["tx_count"]
            total_all_vol += res["volume"]
        print("-" * 65)
        log(f"  TOTAL KESELURUHAN : Tx: {total_all_tx} | Total Volume: ~${total_all_vol:.2f}", Colors.HEADER)
        print("=" * 65 + "\n")

async def main():
    manager = MultiAccountManager()
    try:
        await manager.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        log("\nProses dihentikan oleh pengguna (Ctrl+C).", Colors.YELLOW)
    except Exception as e:
        log(f"\nFatal error: {e}", Colors.RED)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
