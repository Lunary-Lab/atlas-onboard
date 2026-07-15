import os
import sys

from src.atlas_onboard.security import encrypt_data

master_password = os.environ.get("ATLAS_ONBOARD_PASSWORD")
shared_secret = os.environ.get("ATLAS_ONBOARD_TWO_FACTOR_SECRET")

# Mock age key
plaintext_age_key = b"AGE-SECRET-KEY-1F0J9D227KJZ6U4RYQZX4NMTQXUWKXJ7HVTN7RFRWTYV7W6RQVQ0SDKW24R"

encrypted = encrypt_data(plaintext_age_key, master_password, shared_secret)

with open("age_key.enc", "wb") as f:
    f.write(encrypted)

print("Created age_key.enc with new credentials.")
