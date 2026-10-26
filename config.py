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

# Default trading pairs to cycle through
DEFAULT_PAIRS = [p.strip() for p in os.getenv("TRADING_PAIRS", "ETH-USDT,SOL-USDT,BTC-USDT,DOGE-USDT").split(",") if p.strip()]

# Trading parameters
MIN_DELAY = int(os.getenv("MIN_DELAY_SECONDS", "15"))
MAX_DELAY = int(os.getenv("MAX_DELAY_SECONDS", "45"))
TOTAL_CYCLES = int(os.getenv("TOTAL_CYCLES", "30"))  # Jumlah order per sesi

AUTO_CANCEL_OPEN = os.getenv("AUTO_CANCEL_OPEN_ORDERS", "true").lower() == "true"
