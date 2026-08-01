import asyncio
import aiohttp
import redis.asyncio as redis
import os

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
# Sumber proxy gratisan. Kalau mati, cari sendiri di GitHub, 菜鸟!
PROXY_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"
]

async def test_proxy(session, proxy):
    """Test apakah proxy sampah ini masih bisa connect ke target."""
    try:
        # Test ke httpbin dulu biar gak nge-ban target utama pas testing
        async with session.get("https://httpbin.org/ip", proxy=f"http://{proxy}", timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status == 200:
                return True
    except Exception:
        pass
    return False

async def main():
    r = redis.from_url(REDIS_URL)
    await r.delete("valid_proxies") # Bersihin proxy mati dari run sebelumnya
    
    async with aiohttp.ClientSession() as session:
        for source in PROXY_SOURCES:
            try:
                async with session.get(source, timeout=15) as resp:
                    text = await resp.text()
                    # Parse format IP:PORT
                    proxies = [p.strip() for p in text.split('\n') if p.strip() and ':' in p]
                    
                    print(f"操, lagi nyaring {len(proxies)} proxy dari {source}...")
                    # Test 500 proxy pertama secara concurrent biar cepat
                    tasks = [test_proxy(session, p) for p in proxies[:500]]
                    results = await asyncio.gather(*tasks)
                    
                    valid_proxies = [p for p, valid in zip(proxies[:500], results) if valid]
                    if valid_proxies:
                        await r.rpush("valid_proxies", *valid_proxies)
                        print(f"他妈 找到 {len(valid_proxies)} proxy yang masih hidup!")
            except Exception as e:
                print(f"Source {source} gagal: {e}")

    total = await r.llen("valid_proxies")
    print(f"Total proxy valid di Redis: {total}. Kalau 0, berarti koneksi VPS lo yang masalah.")

if __name__ == "__main__":
    asyncio.run(main())
