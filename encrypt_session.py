from cryptography.fernet import Fernet
import sys

# Generate key
key = Fernet.generate_key()
print(f"SECRET_KEY={key.decode()}")

with open("session.zip", "rb") as f:
    data = f.read()

fernet = Fernet(key)
encrypted = fernet.encrypt(data)

with open("session.enc", "wb") as f:
    f.write(encrypted)
print("Encrypted successfully to session.enc")
