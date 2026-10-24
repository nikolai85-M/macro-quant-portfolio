# ticker_news_collector.py — Сборщик новостей по тикерам (v3)
"""
Читает data/scanner_signals.json, берёт тикеры с сигналами.
Для каждого тикера собирает:
1. Общие новости (фильтр по тикеру из news_feed.json)
2. Новости с SmartLab forum (/forum/{ticker}/) ← НОВОЕ
3. Дивиденды (SmartLab /dividends/)

Сохраняет: data/ticker_news/{ticker}.json
"""

import os
import sys
import json
import re
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(SCRIPT_DIR, 'data')
TICKER_NEWS_DIR = os.path.join(DATA_DIR, 'ticker_news')

os.makedirs(TICKER_NEWS_DIR, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
}

NEWS_DAYS = 5

# Маппинг тикеров на ключевые слова
TICKER_KEYWORDS = {
    'LSRG': ['лср', 'группа лср', 'lsrg'],
    'GAZP': ['газпром', 'gazp'],
    'SBER': ['сбер', 'сбербанк', 'sber'],
    'LKOH': ['лукойл', 'lkoh'],
    'ROSN': ['роснефт', 'rosn'],
    'NVTK': ['новатэк', 'новатек', 'nvtk'],
    'YNDX': ['яндекс', 'yndx', 'yandex'],
    'OZON': ['озон', 'ozon'],
    'VTBR': ['втб', 'vtbr'],
    'MTSS': ['мтс', 'mtss'],
    'TATN': ['татнефт', 'tatn'],
    'TATNP': ['татнефт', 'татнфт'],
    'GMKN': ['норникел', 'норильск', 'gmkn'],
    'PLZL': ['полюс', 'plzl'],
    'CHMF': ['северстал', 'chmf'],
    'NLMK': ['нлмк', 'nlmk'],
    'MAGN': ['ммк', 'магнитогорск', 'magn'],
    'ALRS': ['алроса', 'alrs'],
    'AFLT': ['аэрофлот', 'aflt'],
    'MOEX': ['мосбирж', 'московская биржа', 'moex'],
    'HEAD': ['хэдхантер', 'headhunter', 'head'],
    'MBNK': ['мтс банк', 'mbnk'],
    'MTLRP': ['мечел', 'mtlr'],
    'RTKMP': ['ростелеком', 'rtkm'],
    'RASP': ['распадская', 'rasp'],
    'RUAL': ['русал', 'rual'],
    'AFKS': ['афк система', 'afks'],
    'BSPB': ['банк санкт-петербург', 'bspb'],
    'PIKK': ['пик', 'pikk', 'группа пик'],
    'SNGS': ['сургутнефтегаз', 'sngs'],
    'TRNFP': ['транснефть', 'trnfp'],
    'PHOR': ['фосагро', 'phor'],
    'IRAO': ['интеррао', 'irao'],
    'HYDR': ['русгидро', 'hydr'],
    'SELG': ['сегежа', 'selg'],
    'RENI': ['ренессанс', 'reni'],
    'POSI': ['позитив', 'posi'],
    'VKCO': ['вк', 'vkco', 'vkontakte'],
    'X5': ['x5', 'пятерочка', 'перекресток'],
    'FESH': ['федеральная сетев', 'fesh'],
    'FEES': ['россети', 'fees'],
    'HYDR': ['русгидро', 'hydr'],
    'ELFV': ['эл5-энерго', 'elfv'],
    'TGKA': ['тгк-1', 'tgka'],
    'NKNC': ['нижнекамскнефтехим', 'nknc'],
    'UWGN': ['овк', 'uwgn'],
}


def safe_get(url, timeout=15, retries=2):
    """GET с retry"""
    import time
    for attempt in range(retries):
        try:
            return requests.get(url, headers=HEADERS, timeout=timeout)
        except Exception:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                return None
    return None


# ==============================================================================
# 1. ЗАГРУЗКА ТИКЕРОВ ИЗ СКАНЕРА
# ==============================================================================

def load_scanner_tickers():
    filepath = os.path.join(DATA_DIR, 'scanner_signals.json')
    
    if not os.path.exists(filepath):
        print(f"❌ Не найден {filepath}")
        return []
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        signals = data.get('signals', [])
        tickers = list(set([s['ticker'] for s in signals]))
        return tickers
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return []


# ==============================================================================
# 2. ЗАГРУЗКА ОБЩИХ НОВОСТЕЙ
# ==============================================================================

def load_news_feed():
    filepath = os.path.join(DATA_DIR, 'news_feed.json')
    
    if not os.path.exists(filepath):
        print(f"   ⚠️ {filepath} не найден — запусти news_collector.py")
        return []
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        news = data.get('news', [])
        print(f"   📰 Общих новостей: {len(news)}")
        return news
    except Exception as e:
        print(f"   ⚠️ Ошибка: {e}")
        return []


# ==============================================================================
# 3. ФИЛЬТРАЦИЯ ОБЩИХ НОВОСТЕЙ ПО ТИКЕРУ
# ==============================================================================

def filter_news_for_ticker(news_list, ticker):
    if not news_list:
        return []
    
    keywords = TICKER_KEYWORDS.get(ticker, [ticker.lower()])
    
    filtered = []
    for n in news_list:
        title = n.get('title', '').lower()
        summary = n.get('summary', '').lower()
        source = n.get('source', '').lower()  # 🔥 источник
        full_text = f"{title} {summary} {source}"
        
        if any(kw in full_text for kw in keywords):
            filtered.append(n)
        # 🔥 Также проверяем тег источника
        elif ticker.lower() in source:
            filtered.append(n)
    
    return filtered


# ==============================================================================
# 4. НОВОСТИ С SMARTLAB FORUM
# ==============================================================================

def get_smartlab_forum_news(ticker):
    """
    Новости с форума SmartLab.
    URL: https://smart-lab.ru/forum/{ticker}/
    """
    url = f"https://smart-lab.ru/forum/{ticker.lower()}/"
    response = safe_get(url, timeout=20)
    
    if not response or response.status_code != 200:
        return []
    
    try:
        soup = BeautifulSoup(response.text, 'html.parser')
        
        news = []
        seen_titles = set()
        
        # Ищем ссылки на блоги/новости
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            text = link.text.strip()
            
            # Ссылки на блоги и новости (не навигация)
            if len(text) > 25 and ('/blog/' in href or '/news/' in href):
                # Пропускаем служебные ссылки
                if any(x in text.lower() for x in ['читать', 'далее', 'подробнее', 'все ']):
                    continue
                
                title_key = text[:60].lower()
                if title_key in seen_titles:
                    continue
                seen_titles.add(title_key)
                
                # Ищем текст поста рядом
                parent = link.find_parent(['article', 'div', 'li'])
                post_text = ''
                post_date = 'unknown'
                
                if parent:
                    # Берём текст родителя (ограничиваем 500 символов)
                    full_parent_text = parent.text.strip()
                    post_text = full_parent_text[:500]
                    
                    # Ищем дату
                    date_match = re.search(r'(\d{2}\.\d{2}\.\d{4})', full_parent_text)
                    if date_match:
                        post_date = date_match.group(1)
                
                news.append({
                    'title': text[:200],
                    'text': post_text,
                    'date': post_date,
                    'link': f"https://smart-lab.ru{href}" if href.startswith('/') else href,
                    'source': 'SmartLab Forum',
                })
                
                if len(news) >= 15:
                    break
        
        return news
    except Exception as e:
        return []


# ==============================================================================
# 5. ДИВИДЕНДЫ С SMARTLAB
# ==============================================================================

def get_dividends_from_smartlab(ticker):
    """Дивиденды с SmartLab /dividends/"""
    url = "https://smart-lab.ru/dividends/"
    response = safe_get(url, timeout=20)
    
    if not response or response.status_code != 200:
        return []
    
    try:
        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table')
        
        today = datetime.now().date()
        horizon = today + timedelta(days=30)
        
        events = []
        
        for table in tables:
            rows = table.find_all('tr')
            if not rows:
                continue
            
            headers_cells = rows[0].find_all(['th', 'td'])
            headers_text = [c.text.strip() for c in headers_cells]
            
            if 'Тикер' not in headers_text or 'Купить До' not in headers_text:
                continue
            
            ticker_idx = headers_text.index('Тикер')
            dividend_idx = headers_text.index('Дивиденд,руб') if 'Дивиденд,руб' in headers_text else None
            yield_idx = headers_text.index('Див.Дох.') if 'Див.Дох.' in headers_text else None
            buy_until_idx = headers_text.index('Купить До')
            
            for row in rows[1:]:
                cells = row.find_all(['td', 'th'])
                if len(cells) <= buy_until_idx:
                    continue
                
                row_ticker = cells[ticker_idx].text.strip().upper()
                if row_ticker != ticker:
                    continue
                
                buy_until_str = cells[buy_until_idx].text.strip()
                
                try:
                    buy_until = datetime.strptime(buy_until_str, '%d.%m.%Y').date()
                except:
                    continue
                
                if not (today <= buy_until <= horizon):
                    continue
                
                event = {
                    'date': buy_until.strftime('%Y-%m-%d'),
                    'days_until': (buy_until - today).days,
                    'type': 'Дивидендная отсечка',
                    'impact': 'риск гэпа вниз',
                }
                
                if dividend_idx is not None:
                    div_str = cells[dividend_idx].text.strip().replace(',', '.')
                    try:
                        event['amount'] = float(div_str)
                    except:
                        pass
                
                if yield_idx is not None:
                    yield_str = cells[yield_idx].text.strip().replace(',', '.').replace('%', '')
                    try:
                        event['yield_pct'] = float(yield_str)
                    except:
                        pass
                
                events.append(event)
        
        return events
    except Exception as e:
        return []


# ==============================================================================
# 6. СБОР ПО ОДНОМУ ТИКЕРУ
# ==============================================================================

def collect_for_ticker(ticker, all_news):
    """Собирает всё по одному тикеру"""
    print(f"\n📊 {ticker}:")
    
    result = {
        'ticker': ticker,
        'collected': datetime.now().strftime('%Y-%m-%d'),
        'period_days': NEWS_DAYS,
        'news': [],          # общие новости (отфильтрованные)
        'forum_news': [],    # новости с форума SmartLab
        'dividends': [],
        'summary': '',
    }
    
    # 1. Общие новости — фильтр по тикеру
    print(f"   📰 Общие RSS...", end=" ", flush=True)
    ticker_news = filter_news_for_ticker(all_news, ticker)
    result['news'] = ticker_news
    print(f"✅ {len(ticker_news)}")
    
    # 2. Новости с форума SmartLab
    print(f"   💬 SmartLab форум...", end=" ", flush=True)
    forum_news = get_smartlab_forum_news(ticker)
    result['forum_news'] = forum_news
    print(f"✅ {len(forum_news)}")
    
    # 3. Дивиденды
    print(f"   💰 Дивиденды...", end=" ", flush=True)
    dividends = get_dividends_from_smartlab(ticker)
    result['dividends'] = dividends
    print(f"✅ {len(dividends)}")
    
    # 4. Summary
    summary_parts = []
    
    total_news = len(ticker_news) + len(forum_news)
    if total_news > 0:
        summary_parts.append(f"Новостей: {total_news}")
    else:
        summary_parts.append("Новостей нет")
    
    if dividends:
        for d in dividends:
            amount = d.get('amount', '?')
            summary_parts.append(f"Дивиденды {amount}₽ через {d['days_until']} дней")
    else:
        summary_parts.append("Дивидендов нет")
    
    result['summary'] = f"{ticker}: " + " | ".join(summary_parts)
    
    return result


# ==============================================================================
# 7. СОХРАНЕНИЕ
# ==============================================================================

def save_ticker_news(ticker, data):
    filepath = os.path.join(TICKER_NEWS_DIR, f'{ticker}.json')
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return filepath


# ==============================================================================
# ЗАПУСК
# ==============================================================================

def main():
    print("="*70)
    print("📰 СБОРЩИК НОВОСТЕЙ ПО ТИКЕРАМ (v3)")
    print("="*70)
    print()
    
    # 1. Тикеры с сигналами
    tickers = load_scanner_tickers()
    if not tickers:
        print("❌ Нет тикеров для сбора")
        return
    
    print(f"📊 Тикеров с сигналами: {len(tickers)}")
    print(f"   {', '.join(tickers)}")
    print()
    
    # 2. Общие новости
    all_news = load_news_feed()
    
    print()
    print("-"*70)
    
    # 3. По каждому тикеру
    results = {}
    for ticker in tickers:
        data = collect_for_ticker(ticker, all_news)
        save_ticker_news(ticker, data)
        results[ticker] = data
    
    # 4. Итог
    print("\n" + "="*70)
    print("📊 ИТОГОВАЯ СВОДКА:")
    print("="*70)
    
    for ticker, data in results.items():
        rss_count = len(data['news'])
        forum_count = len(data['forum_news'])
        div_count = len(data['dividends'])
        print(f"   {ticker:8} | RSS: {rss_count:2} | Forum: {forum_count:2} | Див: {div_count:2} | {data['summary'][:40]}")
    
    print("\n" + "="*70)
    print(f"✅ Собрано по {len(results)} тикерам")
    print(f"💾 Сохранено в: {TICKER_NEWS_DIR}")
    print("="*70)


if __name__ == "__main__":
    main()