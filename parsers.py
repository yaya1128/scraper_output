# -*- coding: utf-8 -*-
"""
集中实现：各站点 list_parser / detail_fetcher / detail_parser / normalize。
对外仅暴露 get_parsers(site_id)，由 registry 调用。
"""
import json
import re
from typing import Any, Callable, Dict, List, Optional

from bs4 import BeautifulSoup

from .base import extract_int_price, extract_currency, parse_list_generic


# === Balenciaga ===


def _balenciaga_parse_by_product_links(soup: BeautifulSoup, config: dict):
    """
    兜底：收集所有指向商品详情页的 a[href*='.html']，排除 searchajax/筛选链接，
    用链接文本或邻近 h2/h3 作为名称，父节点内价格文本解析价格。
    """
    list_cfg = config.get("list") or {}
    base_url = (config.get("base_url") or "").rstrip("/")
    brand = config.get("brand", "balenciaga")
    domain = "balenciaga.com"

    items = []
    for a in soup.select("a[href*='.html']"):
        href = a.get("href") or ""
        if "searchajax" in href or "prefn" in href:
            continue
        if domain not in href and not href.startswith("/"):
            continue
        if href.startswith("/"):
            product_link = f"{base_url}{href}" if base_url else href
        else:
            product_link = href

        name = a.get_text(strip=True) or "(no name)"
        parent = a.parent
        for _ in range(5):
            if not parent:
                break
            h = parent.find(["h2", "h3"])
            if h and h.get_text(strip=True):
                name = h.get_text(strip=True)
                break
            parent = getattr(parent, "parent", None)

        sale_price = None
        currency = None
        node = a.parent
        for _ in range(8):
            if not node:
                break
            price_el = node.find(attrs={"itemprop": "price"})
            if price_el:
                content_val = price_el.get("content")
                if content_val:
                    try:
                        sale_price = int(float(content_val))
                    except (ValueError, TypeError):
                        sale_price = extract_int_price(content_val)
                if sale_price is None:
                    sale_price = extract_int_price(price_el.get_text(strip=True))
                curr_el = node.find(attrs={"itemprop": "priceCurrency"})
                if curr_el:
                    currency = (curr_el.get("content") or curr_el.get_text(strip=True) or "").upper() or None
                if currency is None and node:
                    currency = extract_currency(price_el.get_text(strip=True))
                break
            node = getattr(node, "parent", None)
        if sale_price is None:
            price_text = None
            node = a.parent
            for _ in range(5):
                if not node:
                    break
                txt = node.get_text(separator=" ", strip=True)
                if re.search(r"RM\s*[\d,]+|€\s*[\d,]+|\$\s*[\d,]+", txt):
                    price_text = txt
                    break
                node = getattr(node, "parent", None)
            sale_price = extract_int_price(price_text) if price_text else None
            currency = extract_currency(price_text) if price_text else currency

        items.append({
            "product_name": name,
            "product_link": product_link,
            "sale_price": sale_price,
            "regular_price": sale_price,
            "currency": currency,
            "brand": brand,
            "product_id": None,
            "category": None,
        })
    seen = set()
    unique = []
    for it in items:
        link = it.get("product_link")
        if link and link not in seen:
            seen.add(link)
            unique.append(it)
    return unique


def balenciaga_list_parser(raw: BeautifulSoup, config: dict):
    items = parse_list_generic(raw, config)
    if not items:
        items = _balenciaga_parse_by_product_links(raw, config)
    return items


def balenciaga_detail_parser(raw: BeautifulSoup, config: dict):
    out = {}
    name_el = raw.select_one("h1.c-product__name") or raw.find(attrs={"itemprop": "name"})
    if name_el:
        out["product_name"] = name_el.get_text(strip=True)
    desc_el = raw.select_one("p.c-product__longdesc")
    if desc_el:
        out["product_description"] = desc_el.get_text(strip=True)
    img_el = raw.select_one("img.c-product__image") or raw.find("img", attrs={"itemprop": "image"})
    if img_el:
        out["image_url"] = img_el.get("src") or img_el.get("data-src") or None
    bread_links = raw.select(".c-breadcrumbs__link")
    for link in bread_links:
        span = link.find("span", attrs={"itemprop": "name"})
        if span and span.get_text(strip=True):
            out["category"] = span.get_text(strip=True).replace("&amp;", "&")
            break
    pid = None
    btn = raw.select_one("button[data-url*='pid=']")
    if btn:
        url_attr = btn.get("data-url") or ""
        m = re.search(r"pid=([A-Za-z0-9_-]+)", url_attr)
        if m:
            pid = m.group(1)
    if not pid and img_el:
        src = (img_el.get("src") or img_el.get("data-src") or "")
        m = re.search(r"/([A-Za-z0-9_-]+)_[A-Z]\.jpg", src)
        if m:
            pid = m.group(1)
    if pid:
        out["product_id"] = pid
    price_el = raw.find(attrs={"itemprop": "price"})
    if price_el:
        content_val = price_el.get("content")
        if content_val:
            try:
                out["sale_price"] = int(float(content_val))
            except (ValueError, TypeError):
                out["sale_price"] = extract_int_price(content_val)
        if out.get("sale_price") is None:
            out["sale_price"] = extract_int_price(price_el.get_text(strip=True))
    curr_el = raw.find(attrs={"itemprop": "priceCurrency"})
    if curr_el:
        out["currency"] = (curr_el.get("content") or curr_el.get_text(strip=True) or "").upper() or None
    return out


# === Chanel ===


def _chanel_extract_product_id_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    m = re.search(r"/p/([^/]+)/", url)
    return m.group(1) if m else None


def chanel_list_parser(raw: BeautifulSoup, config: dict) -> List[Dict[str, Any]]:
    list_cfg = config.get("list") or {}
    product_urls = list_cfg.get("product_urls")
    if product_urls and isinstance(product_urls, list):
        brand = config.get("brand", "chanel")
        items = []
        seen = set()
        for url in product_urls:
            url = (url or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            product_id = _chanel_extract_product_id_from_url(url)
            items.append({
                "product_link": url,
                "product_id": product_id,
                "product_name": "",
                "brand": brand,
            })
        return items
    return parse_list_generic(raw, config)


def chanel_detail_parser(soup: BeautifulSoup, config: dict) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    desc_el = soup.select_one('[data-test="strHeroSplittedCollectionName"]')
    if desc_el:
        desc = desc_el.get_text(strip=True)
        if desc:
            out["product_description"] = desc
    cat_el = soup.select_one('[data-test="strHeroSplittedProductName"]')
    if cat_el:
        cat = cat_el.get_text(strip=True)
        if cat:
            out["category"] = cat
    details_el = soup.select_one('[data-testid="strProductDetails"]')
    if details_el:
        for br in details_el.find_all("br"):
            br.replace_with("|||")
        text = details_el.get_text(strip=True)
        parts = [p.strip() for p in text.split("|||") if p.strip()]
        if len(parts) >= 1 and parts[0]:
            out["attributes"] = [{"name": "Material", "value": parts[0]}]
        if len(parts) >= 2 and parts[1]:
            colors = [c.strip() for c in parts[1].split(",") if c.strip()]
            out["color_list"] = colors
            out["color_count"] = len(colors)
    price_el = soup.select_one("#hero-splitted-price-product") or soup.select_one(
        '[data-test="strHeroSplittedProductPrice"] span'
    )
    if price_el:
        price_text = price_el.get_text(strip=True)
        out["sale_price"] = extract_int_price(price_text)
        out["currency"] = extract_currency(price_text)
        out["regular_price"] = out["sale_price"]
    img_el = (
        soup.select_one(".cc-hero-splitted__img-wrapper img")
        or soup.select_one(".cc-hero-splitted__img-low")
    )
    if img_el and img_el.get("src"):
        out["image_url"] = img_el["src"].strip()
    return out


def chanel_normalize(item: Dict[str, Any]) -> Dict[str, Any]:
    from core.normalize import default_normalize  # type: ignore[import-untyped]

    rec = default_normalize(item)
    if rec.get("regular_price") is None and rec.get("sale_price") is not None:
        rec["regular_price"] = rec["sale_price"]
    for key in ("rating", "rating_count", "raw"):
        rec.pop(key, None)
    return rec


# === Louis Vuitton ===


def louisvuitton_list_parser(raw: BeautifulSoup, config: dict):
    return parse_list_generic(raw, config)


def louisvuitton_detail_parser(raw: BeautifulSoup, config: dict):
    return {}


# === Lululemon ===


def lululemon_list_parser(raw: BeautifulSoup, config: dict) -> List[Dict[str, Any]]:
    products = []
    list_cfg = config.get("list") or {}
    selectors = list_cfg.get("selectors") or {}
    base_url = config.get("base_url", "https://shop.lululemon.com")

    product_tiles = raw.find_all("div", class_="product-tile")
    if not product_tiles:
        return []

    for product in product_tiles:
        try:
            name_tag = product.find("h3", class_="product-tile__product-name")
            product_name = name_tag.get_text(strip=True) if name_tag else None
            link_tag = product.find("a", class_="link")
            href = link_tag.get("href") if link_tag else None
            product_link = f"{base_url.rstrip('/')}{href}" if href and not href.startswith("http") else (href or None)

            sale_price, regular_price = None, None
            price_container = product.find("span", class_="price")
            if price_container:
                price_text = price_container.get_text(strip=True)
                if "Sale Price" in price_text:
                    parts = price_text.split("Regular Price")
                    sale_price = parts[0].replace("Sale Price", "").strip()
                    regular_price = parts[1].strip() if len(parts) > 1 else None
                elif "Regular Price" in price_text:
                    regular_price = price_text.replace("Regular Price", "").strip()
            sale_price = extract_int_price(sale_price)
            regular_price = extract_int_price(regular_price)

            color_count_tag = product.find("p", class_="product-tile__color-count")
            color_count = color_count_tag.get_text(strip=True) if color_count_tag else None
            attributes_tag = product.find("a", class_="link")
            attributes_json = attributes_tag.get("data-lulu-attributes") if attributes_tag else None
            attributes = json.loads(attributes_json) if attributes_json else {}
            product_id = (attributes.get("product") or {}).get("productID")
            category = None
            if product_link:
                match = re.search(r"/p/([^/]+)/", product_link)
                if match:
                    category = match.group(1)

            products.append({
                "product_name": product_name,
                "product_link": product_link,
                "sale_price": sale_price,
                "regular_price": regular_price,
                "color_count": color_count,
                "productID": product_id,
                "category": category,
                "brand": config.get("brand", "lululemon"),
            })
        except Exception as e:
            print(f"[lululemon] list item parse error: {e}")
            continue
    return products


def _lululemon_extract_json_ld(soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
    script_tag = soup.find("script", type="application/ld+json")
    if not script_tag or not script_tag.string:
        return None
    try:
        return json.loads(script_tag.string)
    except json.JSONDecodeError:
        return None


def _lululemon_extract_colors_from_detail(soup: BeautifulSoup) -> Optional[List[str]]:
    container = soup.find(attrs={"data-testid": "button-tile-group_group"})
    if not container:
        container = soup.find(attrs={"role": "radiogroup", "aria-label": re.compile(r"select\s*colou?r", re.I)})
    if not container:
        return None
    tiles = container.find_all(attrs={"data-testid": "button-tile"})
    if not tiles:
        tiles = container.find_all(attrs={"role": "radio"})
    if not tiles:
        return None
    colors = []
    for tile in tiles:
        name = tile.get("aria-label")
        if name and name.strip():
            colors.append(name.strip())
    return colors if colors else None


def _lululemon_extract_sale_price_product_description(html_content: str, json_ld_data: Dict[str, Any]) -> tuple:
    sku = (json_ld_data or {}).get("sku") or ""
    match = re.search(r'"whyWeMadeThisAttributes":\{.*?"text":"(.*?)".*?\}', html_content)
    product_description = match.group(1) if match else None
    match = re.search(rf'"id":\s*"{re.escape(sku)}".*?}}', html_content) if sku else None
    list_price, sale_price = None, None
    if match:
        prices = re.search(r'"list-price":"(?P<list_price>[\d.]+)".*?"sale-price":"(?P<sale_price>[\d.]+)"', match.group(0))
        if prices:
            list_price = prices.group("list_price")
            sale_price = prices.group("sale_price")
    return list_price, sale_price, product_description


def lululemon_detail_parser(raw: BeautifulSoup, config: dict) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        html_content = str(raw)
        json_ld_data = _lululemon_extract_json_ld(raw)
        if not json_ld_data:
            return {}
        list_price, sale_price, product_description = _lululemon_extract_sale_price_product_description(
            html_content, json_ld_data
        )
        rating_value = (json_ld_data.get("aggregateRating") or {}).get("ratingValue")
        rating = float(rating_value) if rating_value and rating_value != "null" else None
        rating_n = (json_ld_data.get("aggregateRating") or {}).get("reviewCount")
        image = json_ld_data.get("image")
        colors_list = _lululemon_extract_colors_from_detail(raw)
        return {
            "product_description": product_description,
            "sale_price": float(sale_price) if sale_price else None,
            "regular_price": float(list_price) if list_price else None,
            "image_url": image,
            "rating": rating,
            "rating_n": rating_n,
            "color_count": colors_list if isinstance(colors_list, list) else None,
            "color_count_number": len(colors_list) if colors_list else None,
        }
    except Exception as e:
        print(f"[lululemon] detail_parser error: {e}")
        return {}


# === Miu Miu ===


def miumiu_list_parser(raw: BeautifulSoup, config: dict):
    return parse_list_generic(raw, config)


def miumiu_detail_parser(raw: BeautifulSoup, config: dict):
    out = {}
    h1 = raw.select_one("h3 h1")
    if h1 and h1.get_text(strip=True):
        out["product_name"] = h1.get_text(strip=True)
    for div in raw.select("div.mt-2, div[class*='mt-']"):
        txt = div.get_text(strip=True)
        if txt and "Soon available online" in txt:
            out["attributes"] = ["Soon available online"]
            break
    if "attributes" not in out:
        out["attributes"] = []
    for p in raw.select("p"):
        if re.match(r"Color\s*:?", p.get_text(strip=True) or ""):
            next_p = p.find_next_sibling("p")
            if next_p:
                span = next_p.find("span")
                if span:
                    color_val = span.get_text(strip=True)
                    if color_val:
                        out["color_list"] = [color_val]
            break
    if "color_list" not in out:
        out["color_list"] = []
    return out


# === Prada ===


def prada_list_parser(raw: BeautifulSoup, config: dict):
    return parse_list_generic(raw, config)


def _prada_first_url_from_srcset(srcset: str) -> str:
    if not srcset or not srcset.strip():
        return ""
    part = srcset.strip().split(",")[0].strip()
    return part.split()[0].strip() if part else ""


def prada_detail_parser(raw: BeautifulSoup, config: dict):
    out = {}
    picture = raw.select_one("picture")
    if picture:
        for tag in picture.select("source[srcset], img[srcset]"):
            srcset = tag.get("srcset")
            if srcset:
                url = _prada_first_url_from_srcset(srcset)
                if url and "placeholder" not in url:
                    out["image_url"] = url
                    break
        if "image_url" not in out:
            img = picture.find("img", src=True)
            if img and img.get("src") and "placeholder" not in img.get("src", ""):
                out["image_url"] = img["src"]
    for p in raw.select("div p"):
        if (p.get_text(strip=True) or "").strip() == "Color":
            next_p = p.find_next_sibling("p")
            if next_p:
                color_val = next_p.get_text(strip=True)
                if color_val:
                    out["color_list"] = [color_val]
            break
    if "color_list" not in out:
        out["color_list"] = []
    out["attributes"] = []
    return out


# === YSL ===


def ysl_list_parser(raw: BeautifulSoup, config: dict) -> List[Dict[str, Any]]:
    return parse_list_generic(raw, config)


def ysl_detail_parser(soup: BeautifulSoup, config: dict) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    price_el = soup.select_one('[data-qa="pdp-mobile-price-field"]')
    if price_el:
        price_text = price_el.get_text(strip=True)
        out["sale_price"] = extract_int_price(price_text)
        out["currency"] = extract_currency(price_text)
        out["regular_price"] = out["sale_price"]

    color_el = soup.select_one("div.sc-15b44914-2 p") or soup.select_one("div.sc-4868c095-8")
    if color_el:
        color = color_el.get_text(strip=True)
        if color and color.lower() not in ("other colors",):
            out["color_list"] = [color]
            out["color_count"] = 1

    desc_el = soup.select_one("div.sc-15b44914-0 button.sc-15b44914-3") or soup.select_one(
        "button[data-imt-p]"
    )
    if desc_el:
        desc = desc_el.get_text(strip=True)
        if desc:
            out["product_description"] = desc

    img_el = (
        soup.select_one('div[data-theme="ysl"] button.sc-53f2741a-3 img')
        or soup.select_one('div[data-theme="ysl"] button[type="button"] img')
    )
    if img_el and img_el.get("src"):
        out["image_url"] = img_el["src"].strip()

    return out


def _ysl_first_capitalized_word(name: str) -> str:
    if not name or not isinstance(name, str):
        return ""
    words = name.split()
    for w in words:
        if w and w[0].isupper():
            return w
    return words[0] if words else ""


def ysl_normalize(item: Dict[str, Any]) -> Dict[str, Any]:
    from core.normalize import default_normalize

    rec = default_normalize(item)
    if rec.get("product_name"):
        rec["category"] = _ysl_first_capitalized_word(rec["product_name"])
    if rec.get("regular_price") is None and rec.get("sale_price") is not None:
        rec["regular_price"] = rec["sale_price"]
    for key in ("rating", "rating_count", "attributes", "raw"):
        rec.pop(key, None)
    return rec


# === get_parsers(site_id) ===


def get_parsers(site_id: str) -> Dict[str, Optional[Callable]]:
    """
    返回该站的 list_parser、detail_fetcher、detail_parser、normalize。
    未注册的站点或未实现的函数对应键为 None。
    """
    result: Dict[str, Optional[Callable]] = {
        "list_parser": None,
        "detail_fetcher": None,
        "detail_parser": None,
        "normalize": None,
    }
    if site_id == "balenciaga":
        result["list_parser"] = balenciaga_list_parser
        result["detail_parser"] = balenciaga_detail_parser
    elif site_id == "chanel":
        result["list_parser"] = chanel_list_parser
        result["detail_parser"] = chanel_detail_parser
        result["normalize"] = chanel_normalize
    elif site_id == "louisvuitton":
        result["list_parser"] = louisvuitton_list_parser
        result["detail_parser"] = louisvuitton_detail_parser
    elif site_id == "lululemon":
        result["list_parser"] = lululemon_list_parser
        result["detail_parser"] = lululemon_detail_parser
    elif site_id == "miumiu":
        result["list_parser"] = miumiu_list_parser
        result["detail_parser"] = miumiu_detail_parser
    elif site_id == "prada":
        result["list_parser"] = prada_list_parser
        result["detail_parser"] = prada_detail_parser
    elif site_id == "ysl":
        result["list_parser"] = ysl_list_parser
        result["detail_parser"] = ysl_detail_parser
        result["normalize"] = ysl_normalize
    if result["list_parser"] is None:
        raise ValueError(f"site_id={site_id} must provide list_parser in sites.parsers")
    return result


if __name__ == "__main__":
    # 直接跑时：依次跑所有站点，每个站点的 JSON 写入 output/{site_id}_parsers.json，终端只打摘要
    # 请在项目根目录执行: python3 -m sites.parsers  （cd scraper_pipeline 后）
    import asyncio
    import json
    import os

    from core.pipeline import run as run_pipeline

    SITE_IDS = ["chanel", "lululemon", "ysl", "balenciaga", "prada", "miumiu", "louisvuitton"]

    # 项目根目录下的 output
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    OUTPUT_DIR = os.path.join(_root, "output")

    async def _main():
        opts = {"fetch_detail": False, "output_dir": None}
        all_by_site = {}
        for site_id in SITE_IDS:
            try:
                products = await run_pipeline(site_id=site_id, opts=opts)
                all_by_site[site_id] = products
            except Exception as e:
                print(f"[parsers] {site_id} failed: {e}", file=__import__("sys").stderr)
                all_by_site[site_id] = []
        return all_by_site

    all_by_site = asyncio.run(_main())

    def _drop_none(d: dict) -> dict:
        return {k: v for k, v in d.items() if v is not None}

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for site_id, products in all_by_site.items():
        path = os.path.join(OUTPUT_DIR, f"{site_id}_parsers.json")
        body = {"products": [_drop_none(p) for p in products], "swatches": []}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False, indent=2)
        print(f"{site_id}: {len(products)} products -> {path}")
    print(f"Done. All JSON under {OUTPUT_DIR}")
