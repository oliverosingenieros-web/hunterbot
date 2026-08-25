import asyncio
import httpx
from selectolax.parser import HTMLParser

async def test_lidl():
    url = "https://www.lidl.es/es/search?query=batidora"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "es-ES,es;q=0.9",
    }
    print(f"Fetch {url}")
    async with httpx.AsyncClient(follow_redirects=True) as client:
        r = await client.get(url, headers=headers)
        print("Status:", r.status_code)
        
        parser = HTMLParser(r.text)
        articles = parser.css("article") or parser.css(".n-search__result-item") or parser.css(".product-grid-item") or parser.css("div[data-grid-item]") or parser.css(".product-list-item")
        
        print("Found items:", len(articles))
        for art in articles[:3]:
            title = art.css_first("h2, h3, .product-title, .title")
            price = art.css_first(".price, .m-price__price, .n-price")
            link = art.css_first("a")
            print("-", title.text(strip=True) if title else "No title", 
                  "|", price.text(strip=True) if price else "No price",
                  "|", link.attributes.get("href") if link else "No link")

async def test_vorwerk():
    url = "https://www.vorwerk.com/es/es/s/shop/productos/thermomix/c/tm-productos"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "es-ES,es;q=0.9",
    }
    print(f"Fetch {url}")
    async with httpx.AsyncClient(follow_redirects=True) as client:
        r = await client.get(url, headers=headers)
        print("Status:", r.status_code)
        
        parser = HTMLParser(r.text)
        articles = parser.css(".product-item") or parser.css(".vw-product-card") or parser.css("article") or parser.css(".product")
        print("Found items:", len(articles))
        for art in articles[:3]:
            title = art.css_first(".product-title, .title, h2, h3")
            price = art.css_first(".price, .vw-price")
            link = art.css_first("a")
            print("-", title.text(strip=True) if title else "No title", 
                  "|", price.text(strip=True) if price else "No price",
                  "|", link.attributes.get("href") if link else "No link")

if __name__ == "__main__":
    asyncio.run(test_lidl())
    asyncio.run(test_vorwerk())
