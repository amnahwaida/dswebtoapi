def format_text(text: str) -> str:
    """
    Mengubah format teks:
    - Setiap karakter biasa ditambahkan '_' di belakangnya.
    - Setiap spasi diubah menjadi ' _'.
    """
    return "".join(" _" if char == " " else f"{char}_" for char in text)

def main():
    print("=== Program Pengubah Format Teks ===")
    while True:
        try:
            user_input = input("\nMasukkan teks (ketik 'exit' atau Ctrl+C untuk keluar): ")
            if user_input.strip().lower() == "exit":
                print("Terima kasih, program selesai.")
                break
            
            formatted = format_text(user_input)
            print("\nHasil Format:")
            print(formatted)
        except (KeyboardInterrupt, EOFError):
            print("\nTerima kasih, program selesai.")
            break

if __name__ == "__main__":
    main()
