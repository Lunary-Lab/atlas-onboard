import sys
try:
    import pyotp
except ImportError:
    print("Please install pyotp: pip install pyotp")
    sys.exit(1)

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--generate-secret":
        # Using 64 characters (320 bits) which is highly secure and reliably supported by major authenticator apps
        print(pyotp.random_base32(length=64))
        sys.exit(0)

    if len(sys.argv) < 2:
        print("Usage: python generate_totp.py <TOTP_SECRET_KEY>")
        print("       python generate_totp.py --generate-secret")
        sys.exit(1)
    
    secret = sys.argv[1].replace(" ", "").upper()
    totp = pyotp.TOTP(secret)
    print(f"Your current TOTP code is: {totp.now()}")

if __name__ == "__main__":
    main()
