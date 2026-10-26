import base64
from polyester.auth import generate_ed25519_keypair

def main():
    public_bytes, private_bytes = generate_ed25519_keypair()
    
    pub_hex = public_bytes.hex()
    pub_b64 = base64.b64encode(public_bytes).decode()
    priv_hex = private_bytes.hex()
    
    print("=" * 65)
    print("      POLYESTER ED25519 KEYPAIR GENERATOR")
    print("=" * 65)
    print("\n[1] PUBLIC KEY (Masukkan / Tempel ini di Web testnet.polyester.com):")
    print(f"Hex    : {pub_hex}")
    print(f"Base64 : {pub_b64}")
    print("\n[2] PRIVATE KEY (Simpan ini di file .env sebagai POLYESTER_API_PRIVATE_KEY):")
    print(f"Hex    : {priv_hex}")
    print("\n" + "=" * 65)
    print("LANGKAH:")
    print("1. Buka https://testnet.polyester.com -> Settings / API Keys.")
    print("2. Buat API Key baru, lalu masukkan Public Key di atas.")
    print("3. Website akan memberikan 'API Key ID' (ak_...).")
    print("4. Masukkan 'API Key ID' tersebut dan Private Key di atas ke .env.")
    print("=" * 65)

if __name__ == "__main__":
    main()
