import os
import dataclasses
from dotenv import load_dotenv
from polyester import POLYESTER_TESTNET_ENVIRONMENT, PolyesterEnvironment

load_dotenv()

# Gunakan domain api resmi yang valid untuk Polyester Testnet
CUSTOM_TESTNET_ENV: PolyesterEnvironment = dataclasses.replace(
    POLYESTER_TESTNET_ENVIRONMENT,
    api_url=os.getenv("POLYESTER_API_URL", "https://api.testnet.polyester.com"),
    websocket_url=os.getenv("POLYESTER_WS_URL", "wss://api.testnet.polyester.com"),
)

API_KEY_ID = os.getenv("POLYESTER_API_KEY_ID", "").strip()
API_PRIVATE_KEY = os.getenv("POLYESTER_API_PRIVATE_KEY", "").strip()
ACCOUNT_ID = os.getenv("POLYESTER_ACCOUNT_ID", "").strip()

# Default trading pairs to cycle through (Semua pair aktif di Polyester Testnet)
ALL_TESTNET_PAIRS = [
    "BTC-USDT", "ETH-USDT", "SOL-USDT", "DOGE-USDT", "AVAX-USDT",
    "BNB-USDT", "LTC-USDT", "BCH-USDT", "XRP-USDT", "TRX-USDT",
    "ETC-USDT", "POL-USDT", "HYPE-USDT", "USDC-USDT", "ETH-USDC",
    "SOL-USDC", "ETH-BTC", "XRP-BTC"
]
DEFAULT_PAIRS = [p.strip() for p in os.getenv("TRADING_PAIRS", ",".join(ALL_TESTNET_PAIRS)).split(",") if p.strip()]

# Trading parameters
MIN_DELAY = int(os.getenv("MIN_DELAY_SECONDS", "15"))
MAX_DELAY = int(os.getenv("MAX_DELAY_SECONDS", "45"))
TOTAL_CYCLES = int(os.getenv("TOTAL_CYCLES", "30"))  # Jumlah order per sesi

AUTO_CANCEL_OPEN = os.getenv("AUTO_CANCEL_OPEN_ORDERS", "true").lower() == "true"
