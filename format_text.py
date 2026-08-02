import re

def format_for_whatsapp(text: str) -> str:
    """
    Format teks Markdown dari DeepSeek agar optimal & rapi saat dikirim ke WhatsApp:
    1. Mengubah `# Header`, `## Header`, `### Header` -> `*Header*` (Bold WhatsApp).
    2. Mengubah `**bold**` atau `__bold__` -> `*bold*` (Bold WhatsApp).
    3. Mengubah `~~strikethrough~~` -> `~strikethrough~` (Strikethrough WhatsApp).
    4. Mengubah bullet points `-` atau `*` -> `• ` (Bullet WhatsApp).
    5. Merapikan spasi & baris kosong berlebih.
    """
    if not text:
        return ""
    
    # 1. Hapus sisa-sisa header pemikir / search noise DeepSeek jika ada
    text = re.sub(r'^(Thought for \d+ seconds|Read \d+ web pages|Searched \d+ sites).*\n?', '', text, flags=re.MULTILINE)
    
    # 2. Ubah Markdown Headers (# Header, ## Header, ### Header) menjadi *Header* (Bold WhatsApp)
    text = re.sub(r'^(#{1,6})\s+(.+)$', r'*\2*', text, flags=re.MULTILINE)
    
    # 3. Ubah Markdown Bold (**text** atau __text__) menjadi WhatsApp Bold (*text*)
    text = re.sub(r'\*\*(.*?)\*\*', r'*\1*', text)
    text = re.sub(r'__(.*?)__', r'*\1*', text)
    
    # 4. Ubah Markdown Strikethrough (~~text~~) menjadi WhatsApp Strikethrough (~text~)
    text = re.sub(r'~~(.*?)~~', r'~\1~', text)
    
    # 5. Ubah Bullet points (- atau *) menjadi titik bullet WhatsApp (• )
    text = re.sub(r'^[ \t]*[*\-]\s+', r'• ', text, flags=re.MULTILINE)
    
    # 6. Rapikan baris kosong berlebihan (maksimal 2 line break berturut-turut)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()

def format_text(text: str) -> str:
    return format_for_whatsapp(text)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        sample = " ".join(sys.argv[1:])
        print(format_for_whatsapp(sample))
    else:
        print("=== Utility Formatter WhatsApp ===")
        sample = "## Header Test\n- Poin 1 dengan **bold**\n- Poin 2 dengan ~~strikethrough~~"
        print("Input:")
        print(sample)
        print("\nHasil WhatsApp:")
        print(format_for_whatsapp(sample))
