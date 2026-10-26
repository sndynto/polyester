---
name: polyester-trader
description: Automates trading workflows, order placement, and volume generation on Polyester DEX Testnet (testnet.polyester.com) with Single and Multi-Account support.
---

# Polyester Testnet Trading Skill (Multi-Account)

Skill ini memungkinkan AI Agent untuk mengelola dan mengeksekusi aktivitas trading di **Polyester DEX Testnet** secara otomatis untuk **banyak akun sekaligus (Multi-Account)**.

## 🚀 Kemampuan Skill
1. **Multi-Account & Proxy Support**: Mengeksekusi rotasi banyak akun testnet secara berurutan dengan jeda natural antar akun dan dukungan proxy.
2. **Pengecekan Saldo Real-Time**: Membaca saldo aset testnet (USDT, ETH, BTC, DOGE, SOL, AVAX) menggunakan API resmi.
3. **Auto-Trade & Volume Generator**: Menempatkan order beli (Buy) dan jual (Sell) bergantian antar pair aktif.
4. **Execution Safety**: Delay acak antar transaksi dan variasi nominal order ($7.5 - $14 USD).
5. **Auto-Cancel Open Orders**: Membatalkan pesanan gantung sebelum membuat order baru.

## 🛠️ Cara Eksekusi

```powershell
d:\Project\poalyster\venv\Scripts\python.exe d:\Project\poalyster\bot.py
```

## 📋 Konfigurasi Akun
- **Multi-Akun**: Masukkan daftar akun di `accounts.json` (lihat template `accounts.json.example`).
- **Single-Akun**: Konfigurasi otomatis diambil dari file `.env`.
