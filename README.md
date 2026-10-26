# 📈 Polyester DEX Trading Client (Multi-Account Support)

Klien otomatisasi eksekusi trading untuk platform **Polyester DEX** ([testnet.polyester.com](https://testnet.polyester.com/)).

Aplikasi ini mendukung **Single Account** maupun **Multi-Account** dengan fitur rotasi otomatis, manajemen saldo, dan dukungan proxy.

---

## 🚀 Fitur Unggulan

1. **Multi-Account Manager**:
   - Mendukung banyak akun sekaligus via file `accounts.json`.
   - Rotasi otomatis antar akun dengan jeda pendinginan (*cooldown delay*).
   - Dukungan proxy per akun (`http://user:pass@host:port`).
2. **Volume & Execution Engine**:
   - Menempatkan order beli (*Buy*) dan jual (*Sell*) secara bergantian pada pair aktif (`ETH-USDT`, `SOL-USDT`, `BTC-USDT`, `AVAX-USDT`, `DOGE-USDT`).
   - Akumulasi total transaksi (*Tx Count*) dan volume trading.
3. **Execution Safety**:
   - Random delay antar transaksi (15–45 detik).
   - Randomisasi ukuran lot/notional order ($7.5 – $14 USD per transaksi).
   - Memilih pair secara acak untuk menguji likuiditas.
4. **Auto-Cleanup Open Orders**:
   - Otomatis membatalkan pesanan gantung sebelum membuat order baru.
5. **Smart Balance Management**:
   - Otomatis menjual kembali aset base ke USDT jika saldo sudah cukup, sehingga saldo USDT tetap berputar.

---

## 👥 Cara Menambahkan Banyak Akun (Multi-Account)

Buka file `accounts.json` di folder proyek, lalu masukkan daftar akun Anda:

```json
[
  {
    "name": "Akun 1",
    "api_key_id": "ak_key_akun_1",
    "api_private_key": "private_key_akun_1",
    "account_id": "acc_xxxxxxxxxxxxxx",
    "proxy": ""
  },
  {
    "name": "Akun 2",
    "api_key_id": "ak_key_akun_2",
    "api_private_key": "private_key_akun_2",
    "account_id": "acc_akun_2",
    "proxy": "http://username:password@proxy_host:port"
  }
]
```
*(Catatan Keamanan: File `accounts.json` dan `.env` otomatis dilindungi oleh `.gitignore` sehingga tidak akan bocor ke GitHub).*

---

## ▶️ Cara Menjalankan

### Cara 1: Menggunakan File Batch
Cukup klik dua kali file **`start.bat`**.

### Cara 2: Melalui Terminal
```powershell
.\venv\Scripts\activate
python bot.py
```
