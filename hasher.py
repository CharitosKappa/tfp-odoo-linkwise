import streamlit_authenticator as stauth

passwords = ["oMChsPMq#4LhgyNc", "!A@5mz8b6Y3FtbKN", "g48$Dz3i#YpXsQj!"]

hashes = [stauth.Hasher.hash(pw) for pw in passwords]

for p, h in zip(passwords, hashes):
    print(p, "->", h)