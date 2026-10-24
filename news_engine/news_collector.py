# news_collector.py — Сборщик рыночных новостей (v5)
"""
Собирает новости из:
- RSS: РИА Экономика, Интерфакс, РБК, Финам, ТАСС
- HTML: БКС Экспресс (через Playwright)

БКС пропускается БЕЗ фильтрации (это уже отфильтрованный источник).
RSS фильтруется по стоп-словам и рыночным триггерам.
"""

import os
import sys
import json
import re
import time
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
import feedparser
import requests
from bs4 import BeautifulSoup   # ← ДОБАВИТЬ

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)
OUTPUT_FILE = os.path.join(DATA_DIR, 'news_feed.json')


# ==============================================================================
# HEADERS И SAFE_GET (на верхнем уровне!)
# ==============================================================================

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
}


def safe_get(url, timeout=15, retries=2):
    """GET с retry"""
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
# RSS-ИСТОЧНИКИ
# ==============================================================================

RSS_SOURCES = {
    'РИА Новости': 'https://ria.ru/export/rss2/archive/index.xml',  # ← исправлено
    'Интерфакс': 'https://www.interfax.ru/rss.asp',
    'РБК': 'https://rssexport.rbc.ru/rbcnews/news/30/full.rss',
    'Финам': 'https://www.finam.ru/analysis/conews/rsspoint/',
    'ТАСС (рус)': 'https://tass.ru/rss/v2.xml',
}

BCS_URL = "https://bcs-express.ru/category"


# ==============================================================================
# БКС (через Playwright)
# ==============================================================================

def get_bcs_news(max_news=40, wait_seconds=12):
    """Загружает новости БКС через Playwright."""
    try:
        from playwright.sync_api import sync_playwright
        from bs4 import BeautifulSoup
    except ImportError:
        print("      ⚠️ Playwright не установлен, БКС пропущен")
        return []
    
    html = None
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='ru-RU',
        )
        page = context.new_page()
        
        try:
            page.goto(BCS_URL, timeout=60000, wait_until='domcontentloaded')
            time.sleep(wait_seconds)
            html = page.content()
        except Exception as e:
            print(f"      ⚠️ БКС ошибка: {e}")
        finally:
            browser.close()
    
    if not html:
        return []
    
    soup = BeautifulSoup(html, 'html.parser')
    news = []
    seen_links = set()
    
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        text = link.text.strip()
        
        if (len(text) > 30 and len(text) < 200 and
            '/novosti-i-analitika/' in href and
            href not in seen_links):
            
            if href.startswith('/'):
                href = 'https://bcs-express.ru' + href
            
            # Категория из URL
            category = 'БКС'
            if '/analitika-bks/' in href:
                category = 'БКС Аналитика'
            elif '/rossiyskiy-rynok/' in href:
                category = 'БКС Российский рынок'
            elif '/rynok-nefti/' in href:
                category = 'БКС Нефть'
            elif '/valyutnyy-rynok/' in href:
                category = 'БКС Валюта'
            elif '/mirovye-rynki/' in href:
                category = 'БКС Мировые рынки'
            elif '/torgovye-rekomendacii/' in href:
                category = 'БКС Рекомендации'
            elif '/novosti/' in href:
                category = 'БКС Новости'
            
            news.append({
                'source': category,
                'title': text,
                'summary': '',
                'link': href,
                'published': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'categories': ['bcs'],
            })
            seen_links.add(href)
            
            if len(news) >= max_news:
                break
    
    return news

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
    'MTLR': ['мечел', 'mtlr'],
    'RTKMP': ['ростелеком', 'rtkm'],
    'RTKM': ['ростелеком', 'rtkm'],
    'RASP': ['распадская', 'rasp'],
    'RUAL': ['русал', 'rual'],
    'AFKS': ['афк система', 'afks'],
    'BSPB': ['банк санкт-петербург', 'bspb'],
    'PIKK': ['пик', 'pikk', 'группа пик'],
    'SNGS': ['сургутнефтегаз', 'sngs'],
    'SNGSP': ['сургутнефтегаз', 'sngsp'],
    'TRNFP': ['транснефть', 'trnfp'],
    'PHOR': ['фосагро', 'phor'],
    'IRAO': ['интеррао', 'irao'],
    'HYDR': ['русгидро', 'hydr'],
    'SELG': ['сегежа', 'selg'],
    'RENI': ['ренессанс', 'reni'],
    'POSI': ['позитив', 'posi'],
    'VKCO': ['вк', 'vkco', 'vkontakte'],
    'X5': ['x5', 'пятерочка', 'перекресток'],
    'FEES': ['россети', 'fees'],
    'FESH': ['федеральная сетев', 'fesh'],
    'ELFV': ['эл5-энерго', 'elfv'],
    'TGKA': ['тгк-1', 'tgka'],
    'NKNC': ['нижнекамскнефтехим', 'nknc'],
    'UWGN': ['овк', 'uwgn'],
    'DATA': ['группа астра', 'data'],
    'FLOT': ['совкомфлот', 'flot'],
    'SIBN': ['газпром нефть', 'sibn'],
    'ENPG': ['эн+ групп', 'enpg'],
    'MSNG': ['мосэнерго', 'msng'],
    'UPRO': ['юнипро', 'upro'],
    'WUSH': ['вуш', 'whoosh', 'wush'],
    'MDMG': ['мать и дитя', 'mdmg'],
    'LSNGP': ['ленэнерго', 'lsngp'],
    'LSRG': ['лср', 'группа лср', 'lsrg'],
}

STOP_PHRASES = [
    'смартлаб >',
    'форумы >',
    'купить акции',
    'купить в фин',
    'купить в бкс',
    'число акций',
    'номинал акций',
    'капитализация',
    'факторы роста',
    'описание компании',
    'рейтинг акций',
    'облигации лср',
    'дивиденд ао',
    'p/e',
    'p/s',
    'p/bv',
    'ev/ebitda',
]

# ==============================================================================
# РЫНОЧНЫЕ ТРИГГЕРЫ
# ==============================================================================

MARKET_TRIGGERS = {
    'oil_gas': [
        'нефт', 'brent', 'urals', 'опек', 'opec', 'баррел', 'танкер',
        'газпром', 'роснефт', 'лукойл', 'новатэк', 'новатек', 'татнефт',
        'добыч', 'нефтепровод', 'спг', 'газопровод',
        'дизел', 'дизельн', 'бензин', 'топлив',
        'ормузск', 'суэц', 'нефтян',
    ],
    'rates': [
        'ключев', 'ставк', 'цб рф', 'центробанк', 'инфляц', 'дкп',
        'денежно-кредитн', 'регулятор', 'набиуллин',
    ],
    'market': [
        'imoex', 'мосбирж', 'ртс', 'дивиденд',
        'котировк', 'рубл', 'юан', 'курс доллар',
        'ipo', 'байбек', 'buyback', 'индекс мосбирж',
        'акци', 'торги', 'ликвидност',
    ],
    'sanctions': [
        'санкц', 'эмбарго', 'ofac', 'запрет на поставк',
        'заморозк активов', 'отключен от swift',
        'минфин сша', 'еврокомисс',
    ],
    'companies': [
        'отчёт', 'отчет', 'прибыл', 'выручк', 'ebitda', 'убыток',
        'дивиденд', 'совет директор', 'сделк',
        'поглощен', 'слиян', 'm&a',
        'сбер', 'газпром', 'лукойл', 'роснефт', 'новатэк',
        'яндекс', 'озон', 'втб', 'мтс', 'норникел', 'полюс',
    ],
    'macro': [
        'ввп', 'промпроизводств', 'безработиц', 'розничн',
        'потребительск', 'бюджет', 'платежн баланс',
        'дефицит бюджет', 'профицит',
    ],
}

# ==============================================================================
# СТОП-СЛОВА (расширенные)
# ==============================================================================

STOP_WORDS = [
    # Общеполитический мусор
    'певец', 'блогер', 'актер', 'актёр', 'звезда', 'клоун',
    'миротворец', 'миротворц', 'опг', 'арестовали',
    'мошенник', 'приговор', 'дтп', 'пожар',
    
    # Военные действия
    'днр', 'лнр', 'минобороны', 'фронт', 'продвижен',
    'наступлен', 'обстрел', 'беспилотник',
    'дрон', 'бпла', 'мобилизац', 'военкомат',
    'аэропорт', 'ограничения в аэропорт',
    
    # Культура/спорт
    'футбол', 'хокке', 'олимп', 'чемпионат', 'матч', 'турнир',
    'концерт', 'фестивал', 'премьера', 'фильм', 'сериал',
    'пловц', 'пловец', 'спортсмен', 'олимпиад',
    
    # Политика других стран
    'зеленск', 'хусит', 'саудовск', 'польск', 'польш',
    'франц', 'евродепутат', 'глюксманн',
    'израил', 'палестин', 'ливан', 'сирия',
    
    # Быт/социалка
    'алимент', 'пенси', 'налог', 'ндфл',
    'зарплат', 'магаданск',
]

# ==============================================================================
# ГЕО-ФИЛЬТР
# ==============================================================================

GEO_TRIGGERS = [
    'росси', 'рф', 'москв', 'рубл', 'цб',
    'сша', 'америк', 'трамп', 'байден',
    'ес', 'европ', 'евросоюз', 'еврокомисс',
    'китай', 'кнр',
    'нефт', 'brent', 'опек', 'газ',
    'imoex', 'мосбирж', 'ртс',
]

GEO_STOP = [
    'польш', 'польск', 'саудовск', 'хусит', 'иранск',
    'израил', 'палестин', 'ливан', 'сирия',
]


# ==============================================================================
# ФИЛЬТРАЦИЯ
# ==============================================================================

def is_mostly_cyrillic(text):
    if not text:
        return False
    cyrillic = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    latin = sum(1 for c in text if 'a' <= c.lower() <= 'z')
    total = cyrillic + latin
    if total == 0:
        return False
    return cyrillic / total > 0.5


def has_market_trigger(text):
    text_lower = text.lower()
    categories = []
    for category, keywords in MARKET_TRIGGERS.items():
        for kw in keywords:
            if kw in text_lower:
                categories.append(category)
                break
    return categories


def has_stop_word(text):
    text_lower = text.lower()
    for sw in STOP_WORDS:
        if sw in text_lower:
            return True, sw
    return False, None


def has_geo_stop(text):
    text_lower = text.lower()
    for gs in GEO_STOP:
        if gs in text_lower:
            return True, gs
    return False, None


def has_geo_trigger(text):
    text_lower = text.lower()
    return any(gt in text_lower for gt in GEO_TRIGGERS)


def is_relevant_news(title, summary, is_bcs=False):
    """Комплексная проверка релевантности."""
    full_text = f"{title} {summary}"
    
    # 1. Язык — только кириллица
    if not is_mostly_cyrillic(title):
        return False, [], "не русский"
    
    # 🔥 ДЛЯ БКС — пропускаем почти всё (уже отфильтрованный источник)
    if is_bcs:
        categories = has_market_trigger(full_text)
        if not categories:
            categories = ['bcs_general']
        return True, categories, "OK (БКС)"
    
    # === ДЛЯ RSS — полная фильтрация ===
    
    # 2. Стоп-слова
    has_stop, stop_word = has_stop_word(full_text)
    if has_stop:
        return False, [], f"стоп: {stop_word}"
    
    # 3. Гео-стоп
    has_geo_stop_flag, geo_stop = has_geo_stop(full_text)
    if has_geo_stop_flag:
        return False, [], f"гео-стоп: {geo_stop}"
    
    # 4. Рыночные триггеры
    categories = has_market_trigger(full_text)
    if not categories:
        return False, [], "нет триггеров"
    
    # 5. Гео-привязка
    if not has_geo_trigger(full_text):
        return False, [], "нет гео-привязки"
    
    # 6. Длина
    if len(title) < 25:
        return False, [], "короткий"
    
    return True, categories, "OK"


# ==============================================================================
# ПАРСИНГ RSS
# ==============================================================================

def parse_published_date(entry):
    for field in ['published', 'updated', 'pubDate']:
        if hasattr(entry, field):
            try:
                return parsedate_to_datetime(getattr(entry, field))
            except:
                pass
    return datetime.now()


def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def collect_rss_news(hours_back=120, max_per_source=50):  # 5 дней = 120 часов
    """Собирает новости из RSS-источников с таймаутом."""
    all_news = []
    cutoff_time = datetime.now() - timedelta(hours=hours_back)
    
    for source_name, url in RSS_SOURCES.items():
        print(f"   🔄 {source_name}...", end=" ", flush=True)
        
        try:
            # 🔥 Скачиваем через requests с timeout
            response = requests.get(
                url,
                timeout=15,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                                  'Chrome/120.0.0.0 Safari/537.36'
                }
            )
            
            if response.status_code != 200:
                print(f"❌ статус {response.status_code}")
                continue
            
            # Передаём контент в feedparser
            feed = feedparser.parse(response.content)
            
            if not feed.entries:
                print(f"⚠️ нет записей")
                continue
            
            accepted = 0
            for entry in feed.entries[:max_per_source]:
                try:
                    pub_date = parse_published_date(entry)
                    if pub_date.tzinfo is not None:
                        pub_date = pub_date.replace(tzinfo=None)
                    
                    if pub_date < cutoff_time:
                        continue
                    
                    title = clean_text(entry.get('title', ''))
                    summary = clean_text(entry.get('summary', entry.get('description', '')))
                    
                    if not title:
                        continue
                    
                    is_relevant, categories, reason = is_relevant_news(title, summary, is_bcs=False)
                    
                    if not is_relevant:
                        continue
                    
                    all_news.append({
                        'source': source_name,
                        'title': title,
                        'summary': summary[:500],
                        'link': entry.get('link', ''),
                        'published': pub_date.strftime('%Y-%m-%d %H:%M'),
                        'categories': categories,
                    })
                    accepted += 1
                except:
                    continue
            
            print(f"✅ {accepted}")
            
        except requests.exceptions.Timeout:
            print(f"❌ таймаут")
        except Exception as e:
            print(f"❌ {type(e).__name__}")
    
    return all_news
def collect_bcs_news():
    """Собирает новости БКС через Playwright."""
    print(f"   🔄 БКС Экспресс (Playwright)...")
    
    try:
        bcs_news = get_bcs_news(max_news=40, wait_seconds=12)
        
        accepted = 0
        filtered = []
        # 🔥 Ставим время на 1 минуту раньше — чтобы БКС шли В КОНЦЕ списка
        bcs_time = (datetime.now() - timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M')
        
        for n in bcs_news:
            is_relevant, categories, reason = is_relevant_news(
                n['title'], n['summary'], is_bcs=True
            )
            if is_relevant:
                n['categories'] = categories
                n['published'] = bcs_time  # ← одинаковое время, но раньше RSS
                filtered.append(n)
                accepted += 1
        
        print(f"      ✅ Принято: {accepted}")
        return filtered
    except Exception as e:
        print(f"      ❌ Ошибка: {e}")
        return []

def collect_all_news(hours_back=120):  # 5 дней
    """Собирает новости из ВСЕХ источников + форумы по тикерам из сканера"""
    
    # 1. RSS
    rss_news = collect_rss_news(hours_back=hours_back)
    
    # 2. БКС через Playwright
    bcs_news = collect_bcs_news()
    
    # 3. 🔥 SmartLab forum по тикерам из сканера
    ticker_news = []
    try:
        import json as _json
        scan_file = os.path.join(SCRIPT_DIR, 'data', 'scanner_signals.json')
        if os.path.exists(scan_file):
            with open(scan_file, 'r', encoding='utf-8') as f:
                scan_data = _json.load(f)
            tickers = list(set([s['ticker'] for s in scan_data.get('signals', [])]))
            
            print(f"\n   📊 Сканер: {len(tickers)} тикеров — собираем форумы...")
            for ticker in tickers:
                print(f"   💬 SmartLab {ticker}...", end=" ", flush=True)
                forum_news = get_smartlab_forum_news(ticker)
                ticker_news.extend(forum_news)
                print(f"✅ {len(forum_news)}")
    except Exception as e:
        print(f"   ⚠️ Ошибка сканера: {e}")
    
    # 4. Объединяем всё
    all_news = rss_news + bcs_news + ticker_news
    
    # Дедупликация
    seen = set()
    unique = []
    for n in all_news:
        key = n.get('title', '')[:60].lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(n)
    
    unique.sort(key=lambda x: x.get('published', ''), reverse=True)
    
    return unique

def get_smartlab_forum_news(ticker, days=10):
    """
    Простой парсер SmartLab forum.
    Логика:
    1. Загружаем HTML /forum/{ticker}/
    2. Находим ВСЕ текстовые блоки
    3. Фильтруем по ключу тикера (лср, lsrg)
    4. Фильтруем по стоп-фразам (навигация, справочники, реклама)
    5. Фильтруем по дате (последние days дней)
    6. Дедупликация
    7. Топ-20
    """
    url = f"https://smart-lab.ru/forum/{ticker.lower()}/"
    response = safe_get(url, timeout=20)
    
    if not response or response.status_code != 200:
        return []
    
    # Ключи для поиска
    keywords = TICKER_KEYWORDS.get(ticker, [ticker.lower()])
    
    # 🔥 Стоп-фразы (шум)
    STOP_PHRASES = [
        'смартлаб >', 'форумы >', 'котировки акций',
        'купить акции', 'купить в фин', 'купить в бкс',
        'купить в тинькофф', 'купить в сбер',
        'число акций', 'номинал ао', 'номинал ап',
        'капитализация', 'капит-я',
        'факторы роста', 'описание компании', 'рейтинг акций',
        'дивиденд ао', 'p/e', 'p/s', 'p/bv', 'ev/ebitda',
        'облигации лср', 'содержание сообщения',
        'политика конфиденциальности', 'финансовая отчетность',
        'о сайте', 'обратная связь', 'реклама на сайте',
        'пользовательское соглашение', 'правила форума',
    ]
    
    # Порог по дате
    cutoff = datetime.now() - timedelta(days=days)
    
    # Месяцы на русском
    months = {
        'января': 1, 'февраля': 2, 'марта': 3,
        'апреля': 4, 'мая': 5, 'июня': 6,
        'июля': 7, 'августа': 8, 'сентября': 9,
        'октября': 10, 'ноября': 11, 'декабря': 12,
    }
    
    def parse_russian_date(text):
        """Парсит дату вида '12 октября 2026, 12:31'"""
        match = re.search(
            r'(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|'
            r'июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})',
            text.lower()
        )
        if match:
            day = int(match.group(1))
            month = months.get(match.group(2), 1)
            year = int(match.group(3))
            try:
                return datetime(year, month, day)
            except:
                return None
        return None
    
    try:
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Находим ВСЕ текстовые блоки
        blocks = soup.find_all(['div', 'p', 'td', 'li', 'article'])
        
        news = []
        seen = set()
        
        for block in blocks:
            # Получаем текст блока
            text = block.get_text(separator=' ', strip=True)
            
            # Фильтр 1: длина
            if len(text) < 50 or len(text) > 2000:
                continue
            
            text_lower = text.lower()
            
            # Фильтр 2: ключ тикера
            if not any(kw in text_lower for kw in keywords):
                continue
            
            # 🔥 Фильтр 3: стоп-фразы
            if any(stop in text_lower for stop in STOP_PHRASES):
                continue
            
            # Фильтр 4: дата
            date_obj = parse_russian_date(text)
            
            # Если нет даты в тексте — ищем a_time рядом
            if not date_obj:
                time_elem = block.find('a', class_='a_time') if hasattr(block, 'find') else None
                if time_elem:
                    date_obj = parse_russian_date(time_elem.text.strip())
            
            # Если дата есть и она старая — пропускаем
            if date_obj and date_obj < cutoff:
                continue
            
            # Дедупликация
            dedup_key = text[:60].lower()
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            
            # Ищем ссылку
            link = ''
            link_elem = block.find('a', href=True) if hasattr(block, 'find') else None
            if link_elem:
                href = link_elem.get('href', '')
                if href.startswith('/'):
                    link = f"https://smart-lab.ru{href}"
                else:
                    link = href
            
            # Дата для сохранения
            if date_obj:
                published = date_obj.strftime('%Y-%m-%d %H:%M')
            else:
                published = datetime.now().strftime('%Y-%m-%d %H:%M')
            
            news.append({
                'source': f'SmartLab {ticker}',
                'title': text[:200],
                'summary': text[:500],
                'link': link,
                'published': published,
                'categories': ['ticker_news', ticker],
            })
            
            if len(news) >= 20:
                break
        
        return news
    except Exception as e:
        print(f"      ⚠️ {ticker}: {type(e).__name__}: {e}")
        return []

def format_for_llm(news_list, max_items=30):
    """Форматирует для промпта LLM."""
    if not news_list:
        return "Новостей за последние 24 часа не найдено."
    
    lines = []
    for i, news in enumerate(news_list[:max_items], 1):
        cats = ', '.join(news['categories'])
        lines.append(f"{i}. [{news['source']}, {news['published']}] ({cats})")
        lines.append(f"   {news['title']}")
        if news.get('summary') and len(news['summary']) > 80:
            lines.append(f"   {news['summary'][:300]}")
        lines.append("")
    
    return '\n'.join(lines)


def save_news_feed(news_list):
    macro_text = format_for_llm(news_list, max_items=50)
    
    output = {
        'timestamp': datetime.now().isoformat(),
        'total_news': len(news_list),
        'macro_text': macro_text,
        'news': news_list,   # 🔥 ВСЕ новости
    }
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 Сохранено: {OUTPUT_FILE}")


# ==============================================================================
# ЗАПУСК
# ==============================================================================

if __name__ == "__main__":
    print("="*70)
    print("📡 СБОРЩИК НОВОСТЕЙ v5 (5 источников + БКС без фильтра)")
    print("="*70)
    print()
    
    all_news = collect_all_news(hours_back=24)
    
    print(f"\n📊 ВСЕГО СОБРАНО: {len(all_news)} новостей")
    
    # Показываем топ-25
    print(f"\n{'='*70}")
    print(f"📰 ТОП-25 НОВОСТЕЙ:")
    print(f"{'='*70}")
    
    for i, news in enumerate(all_news[:25], 1):
        cats = ', '.join(news['categories'][:3])
        print(f"\n{i}. [{news['source']}] {news['published']}")
        print(f"   {news['title']}")
        print(f"   → {cats}")
    
    save_news_feed(all_news)
    
    print(f"\n{'='*70}")
    print(f"✅ Готово!")
    print(f"{'='*70}")