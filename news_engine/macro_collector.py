# macro_collector.py — Сборщик макро-данных (ФИНАЛЬНАЯ v9)
"""
Собирает:
- Текущие значения: ЦБ РФ, MOEX ISS, Yahoo Finance
- Историю за 2 года:
  - IMOEX: MOEX ISS (пагинация)
  - Brent: Yahoo Finance (BZ=F)
  - Золото: MOEX ISS (GLDRUBF)
  - USD/RUB, CNY/RUB, EUR/RUB: ЦБ РФ (XML_dynamic)

Формирует для LLM:
- Сводка за 2 года (min/max/avg/позиция/тренд)
- Последние 7 дней точками

Сохраняет:
- data/macro_data.json — текущие значения
- data/macro_history.json — история за 2 года
"""

import os
import json
import re
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(SCRIPT_DIR, '.env')
DATA_DIR = os.path.join(SCRIPT_DIR, 'data')
OUTPUT_CURRENT = os.path.join(DATA_DIR, 'macro_data.json')
OUTPUT_HISTORY = os.path.join(DATA_DIR, 'macro_history.json')

os.makedirs(DATA_DIR, exist_ok=True)
load_dotenv(ENV_PATH)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
}

HISTORY_START = "2024-10-01"


# ==============================================================================
# УТИЛИТА
# ==============================================================================

def safe_get(url, timeout=30, retries=3, backoff=2, quiet=False):
    """GET-запрос с retry."""
    import time
    for attempt in range(retries):
        try:
            return requests.get(url, headers=HEADERS, timeout=timeout)
        except requests.exceptions.Timeout:
            if attempt < retries - 1:
                wait = backoff * (attempt + 1)
                if not quiet:
                    print(f"   ⏳ Таймаут (попытка {attempt + 1}/{retries}), ждём {wait}с...")
                time.sleep(wait)
            else:
                if not quiet:
                    print(f"   ⚠️ Все попытки исчерпаны")
                return None
        except Exception as e:
            if not quiet:
                print(f"   ⚠️ Ошибка: {type(e).__name__}")
            return None
    return None


# ==============================================================================
# 1. ТЕКУЩИЕ ЗНАЧЕНИЯ
# ==============================================================================

def get_cbr_rates():
    url = "https://www.cbr.ru/scripts/XML_daily.asp"
    response = safe_get(url, timeout=20)
    if not response:
        print(f"   ❌ ЦБ РФ недоступен")
        return None
    
    try:
        response.encoding = 'windows-1251'
        import xml.etree.ElementTree as ET
        root = ET.fromstring(response.text)
        
        date_str = root.get('Date', '')
        rates = {'date': date_str}
        
        for valute in root.findall('Valute'):
            char_code = valute.find('CharCode').text
            value = float(valute.find('Value').text.replace(',', '.'))
            nominal = int(valute.find('Nominal').text)
            
            if char_code in ['USD', 'EUR', 'CNY']:
                rates[char_code] = value / nominal
        
        print(f"   ✅ ЦБ РФ: USD={rates.get('USD', 0):.2f}, "
              f"EUR={rates.get('EUR', 0):.2f}, "
              f"CNY={rates.get('CNY', 0):.4f}")
        return rates
    except Exception as e:
        print(f"   ❌ Ошибка: {type(e).__name__}")
        return None


def get_cbr_inflation_and_rate():
    url = "https://www.cbr.ru/hd_base/infl/"
    response = safe_get(url, timeout=20)
    if not response or response.status_code != 200:
        print(f"   ❌ ЦБ РФ инфляция недоступна")
        return None
    
    try:
        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table')
        
        for table in tables:
            rows = table.find_all('tr')
            if not rows:
                continue
            headers_row = [c.text.strip() for c in rows[0].find_all(['th', 'td'])]
            if 'Инфляция' not in ' '.join(headers_row):
                continue
            
            for row in rows[1:]:
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 3:
                    date_str = cells[0].text.strip()
                    rate_str = cells[1].text.strip().replace(',', '.').replace('%', '').strip()
                    inflation_str = cells[2].text.strip().replace(',', '.').replace('%', '').strip()
                    
                    try:
                        rate = float(rate_str)
                        inflation = float(inflation_str)
                        print(f"   ✅ ЦБ РФ: инфляция={inflation}%, ставка={rate}% ({date_str})")
                        return {'inflation': inflation, 'rate': rate, 'date': date_str}
                    except ValueError:
                        continue
        return None
    except Exception as e:
        print(f"   ⚠️ Ошибка: {type(e).__name__}")
        return None


def get_moex_index(secid):
    url = f"https://iss.moex.com/iss/engines/stock/markets/index/boards/SNDX/securities/{secid}.json"
    response = safe_get(url, timeout=20)
    if not response:
        return None
    
    try:
        data = response.json()
        marketdata = data.get('marketdata', {})
        columns = marketdata.get('columns', [])
        rows = marketdata.get('data', [])
        
        if rows and columns:
            row = rows[0]
            for col_name in ['CURRENTVALUE', 'LASTVALUE', 'MARKETPRICE']:
                if col_name in columns:
                    idx = columns.index(col_name)
                    value = row[idx]
                    if value is not None:
                        return float(value)
        return None
    except Exception:
        return None


def get_imoex():
    value = get_moex_index('IMOEX')
    if value:
        print(f"   ✅ IMOEX: {value:.2f}")
    else:
        print(f"   ⚠️ IMOEX не получен")
    return value


def get_rvi():
    for board in ['SNDX', 'RTSI']:
        url = f"https://iss.moex.com/iss/engines/stock/markets/index/boards/{board}/securities/RVI.json"
        response = safe_get(url, timeout=15, quiet=True)
        if not response:
            continue
        try:
            data = response.json()
            marketdata = data.get('marketdata', {})
            columns = marketdata.get('columns', [])
            rows = marketdata.get('data', [])
            
            if rows and columns:
                row = rows[0]
                for col_name in ['CURRENTVALUE', 'LASTVALUE']:
                    if col_name in columns:
                        idx = columns.index(col_name)
                        value = row[idx]
                        if value is not None:
                            print(f"   ✅ RVI: {float(value):.2f}")
                            return float(value)
        except:
            continue
    
    print(f"   ⚠️ RVI не получен")
    return None


def get_brent_current_moex():
    today = datetime.now().date()
    
    BRENT_SCHEDULE = [
        ('BRX6', datetime(2026, 11, 2).date()),
        ('BRZ6', datetime(2026, 12, 1).date()),
        ('BRF7', datetime(2027, 1, 4).date()),
        ('BRG7', datetime(2027, 2, 1).date()),
        ('BRH7', datetime(2027, 3, 1).date()),
        ('BRJ7', datetime(2027, 4, 1).date()),
        ('BRK7', datetime(2027, 5, 3).date()),
    ]
    
    active_ticker = None
    for ticker, expiry in BRENT_SCHEDULE:
        if (expiry - today).days > 3:
            active_ticker = ticker
            break
    
    if not active_ticker:
        return None
    
    url = f"https://iss.moex.com/iss/engines/futures/markets/forts/securities/{active_ticker}.json"
    response = safe_get(url, timeout=30)
    if not response:
        return None
    
    try:
        data = response.json()
        marketdata = data.get('marketdata', {})
        columns = marketdata.get('columns', [])
        rows = marketdata.get('data', [])
        
        if rows and columns:
            row = rows[0]
            for col_name in ['LAST', 'SETTLEPRICE', 'PREVSETTLEPRICE']:
                if col_name in columns:
                    idx = columns.index(col_name)
                    value = row[idx]
                    if value is not None and value > 10:
                        print(f"   ✅ Brent (MOEX {active_ticker}): ${float(value):.2f}")
                        return {'price': float(value), 'ticker': active_ticker}
        return None
    except Exception:
        return None


def get_gold_current_moex():
    """Золото через GLDRUBF (в рублях)"""
    url = "https://iss.moex.com/iss/engines/futures/markets/forts/securities/GLDRUBF.json"
    response = safe_get(url, timeout=30)
    if not response:
        return None
    
    try:
        data = response.json()
        marketdata = data.get('marketdata', {})
        columns = marketdata.get('columns', [])
        rows = marketdata.get('data', [])
        
        if rows and columns:
            row = rows[0]
            for col_name in ['LAST', 'SETTLEPRICE', 'PREVSETTLEPRICE']:
                if col_name in columns:
                    idx = columns.index(col_name)
                    value = row[idx]
                    if value is not None and value > 1000:
                        print(f"   ✅ Золото (MOEX GLDRUBF): {float(value):.2f}₽")
                        return {'price': float(value), 'ticker': 'GLDRUBF', 'currency': 'RUB'}
        return None
    except Exception:
        return None


def get_brent_current_yahoo():
    url = "https://query1.finance.yahoo.com/v8/finance/chart/BZ=F?range=5d&interval=1d"
    response = safe_get(url, timeout=20)
    if not response:
        return None
    
    try:
        data = response.json()
        chart = data.get('chart', {})
        result = chart.get('result', [])
        
        if result:
            r = result[0]
            closes = r.get('indicators', {}).get('quote', [{}])[0].get('close', [])
            valid = [c for c in closes if c is not None]
            if valid:
                print(f"   ✅ Brent (Yahoo ICE): ${valid[-1]:.2f}")
                return float(valid[-1])
        return None
    except Exception:
        return None


# ==============================================================================
# 2. ИСТОРИЯ
# ==============================================================================

def get_moex_history_paginated(engine, market, board, secid, from_date, to_date):
    all_rows = []
    cols = None
    start = 0
    
    for page in range(10):
        url = (f"https://iss.moex.com/iss/history/engines/{engine}/markets/{market}/"
               f"boards/{board}/securities/{secid}.json?"
               f"from={from_date}&till={to_date}&start={start}")
        
        response = safe_get(url, timeout=30, quiet=True)
        if not response:
            break
        
        try:
            data = response.json()
            history = data.get('history', {})
            if cols is None:
                cols = history.get('columns', [])
            rows = history.get('data', [])
            
            if not rows:
                break
            
            all_rows.extend(rows)
            
            if len(rows) < 100:
                break
            
            start += 100
        except Exception:
            break
    
    return cols, all_rows


def get_imoex_history():
    print(f"   📥 IMOEX (2 года)...", end=" ", flush=True)
    to_date = datetime.now().strftime('%Y-%m-%d')
    cols, rows = get_moex_history_paginated('stock', 'index', 'SNDX', 'IMOEX', HISTORY_START, to_date)
    
    if not rows or not cols:
        print("❌")
        return []
    
    date_idx = cols.index('TRADEDATE')
    close_idx = cols.index('CLOSE')
    history = [{'date': row[date_idx], 'value': row[close_idx]} for row in rows if row[close_idx]]
    print(f"✅ {len(history)} точек")
    return history


def get_gold_history():
    print(f"   📥 Золото (2 года)...", end=" ", flush=True)
    to_date = datetime.now().strftime('%Y-%m-%d')
    cols, rows = get_moex_history_paginated('futures', 'forts', 'RFUD', 'GLDRUBF', HISTORY_START, to_date)
    
    if not rows or not cols:
        print("❌")
        return []
    
    date_idx = cols.index('TRADEDATE')
    close_idx = cols.index('CLOSE')
    history = [{'date': row[date_idx], 'value': row[close_idx]} for row in rows if row[close_idx]]
    print(f"✅ {len(history)} точек")
    return history


def get_brent_history_yahoo():
    print(f"   📥 Brent (2 года, Yahoo)...", end=" ", flush=True)
    url = "https://query1.finance.yahoo.com/v8/finance/chart/BZ=F?range=2y&interval=1d"
    response = safe_get(url, timeout=30)
    
    if not response:
        print("❌")
        return []
    
    try:
        data = response.json()
        chart = data.get('chart', {})
        result = chart.get('result', [])
        
        if not result:
            print("❌")
            return []
        
        r = result[0]
        timestamps = r.get('timestamp', [])
        closes = r.get('indicators', {}).get('quote', [{}])[0].get('close', [])
        
        history = []
        for ts, close in zip(timestamps, closes):
            if close is not None:
                date_str = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
                history.append({'date': date_str, 'value': round(close, 2)})
        
        print(f"✅ {len(history)} точек")
        return history
    except Exception as e:
        print(f"❌ {type(e).__name__}")
        return []


def get_cbr_history(val_code):
    date_req1 = datetime.strptime(HISTORY_START, '%Y-%m-%d').strftime('%d/%m/%Y')
    date_req2 = datetime.now().strftime('%d/%m/%Y')
    url = f"https://www.cbr.ru/scripts/XML_dynamic.asp?date_req1={date_req1}&date_req2={date_req2}&VAL_NM_RQ={val_code}"
    
    response = safe_get(url, timeout=30)
    if not response:
        return []
    
    try:
        response.encoding = 'windows-1251'
        import xml.etree.ElementTree as ET
        root = ET.fromstring(response.text)
        
        history = []
        for record in root.findall('Record'):
            date_str = record.get('Date', '')
            value_elem = record.find('Value')
            nominal_elem = record.find('Nominal')
            
            if value_elem is not None and nominal_elem is not None:
                value = float(value_elem.text.replace(',', '.'))
                nominal = int(nominal_elem.text)
                
                try:
                    dt = datetime.strptime(date_str, '%d.%m.%Y')
                    iso_date = dt.strftime('%Y-%m-%d')
                except:
                    continue
                
                history.append({'date': iso_date, 'value': round(value / nominal, 4)})
        
        return history
    except Exception:
        return []


def get_usd_history():
    print(f"   📥 USD/RUB (2 года)...", end=" ", flush=True)
    history = get_cbr_history('R01235')
    print(f"✅ {len(history)} точек")
    return history


def get_cny_history():
    print(f"   📥 CNY/RUB (2 года)...", end=" ", flush=True)
    history = get_cbr_history('R01375')
    print(f"✅ {len(history)} точек")
    return history


def get_eur_history():
    print(f"   📥 EUR/RUB (2 года)...", end=" ", flush=True)
    history = get_cbr_history('R01239')
    print(f"✅ {len(history)} точек")
    return history


# ==============================================================================
# 3. СВОДКА ДЛЯ LLM
# ==============================================================================

def make_summary(history, name, current_value=None):
    if not history:
        return None
    
    values = [h['value'] for h in history if h['value'] is not None]
    if not values:
        return None
    
    min_val = min(values)
    max_val = max(values)
    avg_val = sum(values) / len(values)
    current = current_value if current_value else values[-1]
    
    if max_val > min_val:
        position = (current - min_val) / (max_val - min_val) * 100
        position = max(0, min(100, position))
    else:
        position = 50
    
    trend_30d = "UNKNOWN"
    change_30d_pct = 0
    if len(values) >= 30:
        recent = values[-30:]
        change_30d_pct = (recent[-1] - recent[0]) / recent[0] * 100
        
        if change_30d_pct > 5:
            trend_30d = "UP"
        elif change_30d_pct < -5:
            trend_30d = "DOWN"
        else:
            trend_30d = "SIDEWAYS"
    
    total_change = (values[-1] - values[0]) / values[0] * 100
    
    return {
        'name': name,
        'points': len(history),
        'period_start': history[0]['date'],
        'period_end': history[-1]['date'],
        'min': round(min_val, 4),
        'max': round(max_val, 4),
        'avg': round(avg_val, 4),
        'current': round(current, 4),
        'position_pct': round(position, 1),
        'trend_30d': trend_30d,
        'change_30d_pct': round(change_30d_pct, 2),
        'change_total_pct': round(total_change, 2),
        'recent_7d': history[-7:] if len(history) >= 7 else history,
    }


def format_history_for_llm(history, current):
    """Форматирует историю для промпта LLM (2 года + последние 7 дней)"""
    lines = ["📊 ИСТОРИЯ (2 ГОДА + ПОСЛЕДНИЕ 7 ДНЕЙ):"]
    lines.append("")
    
    summaries = []
    
    if history.get('brent', {}).get('history'):
        cur = current.get('brent')
        s = make_summary(history['brent']['history'], 'Brent', cur)
        if s:
            summaries.append(s)
    
    if history.get('imoex', {}).get('history'):
        cur = current.get('imoex')
        s = make_summary(history['imoex']['history'], 'IMOEX', cur)
        if s:
            summaries.append(s)
    
    if history.get('gold', {}).get('history'):
        cur = current.get('gold')
        s = make_summary(history['gold']['history'], 'Золото', cur)
        if s:
            summaries.append(s)
    
    if history.get('usd_rub', {}).get('history'):
        cur = current.get('usd_rub')
        s = make_summary(history['usd_rub']['history'], 'USD/RUB', cur)
        if s:
            summaries.append(s)
    
    if history.get('cny_rub', {}).get('history'):
        cur = current.get('cny_rub')
        s = make_summary(history['cny_rub']['history'], 'CNY/RUB', cur)
        if s:
            summaries.append(s)
    
    for s in summaries:
        lines.append(f"📈 {s['name']}:")
        lines.append(f"   Текущая: {s['current']}")
        lines.append(f"   Диапазон 2 года: {s['min']} - {s['max']}")
        lines.append(f"   Средняя за 2 года: {s['avg']}")
        lines.append(f"   Позиция в диапазоне: {s['position_pct']}% (0=min, 100=max)")
        lines.append(f"   Тренд за 30 дней: {s['trend_30d']} ({s['change_30d_pct']:+.2f}%)")
        lines.append(f"   Изменение за 2 года: {s['change_total_pct']:+.2f}%")
        
        if s.get('recent_7d'):
            lines.append(f"   Последние 7 дней:")
            for point in s['recent_7d']:
                lines.append(f"      {point['date']}: {point['value']}")
        
        lines.append("")
    
    return '\n'.join(lines)


def format_current_for_llm(data):
    lines = [f"📊 ТЕКУЩИЕ ДАННЫЕ НА {data.get('date', '')}:"]
    lines.append("")
    
    if data.get('brent'):
        lines.append(f"• Brent (мировая): ${data['brent']:.2f}")
    if data.get('brent_moex'):
        lines.append(f"• Brent (MOEX {data.get('brent_ticker', '')}): ${data['brent_moex']:.2f}")
    if data.get('gold'):
        lines.append(f"• Золото: {data['gold']:.2f}₽")
    if data.get('imoex'):
        lines.append(f"• IMOEX: {data['imoex']:.2f}")
    if data.get('rvi'):
        lines.append(f"• RVI: {data['rvi']:.2f}")
    if data.get('usd_rub'):
        lines.append(f"• USD/RUB: {data['usd_rub']:.2f}₽")
    if data.get('cny_rub'):
        lines.append(f"• CNY/RUB: {data['cny_rub']:.4f}₽")
    if data.get('cbr_rate'):
        lines.append(f"• Ставка ЦБ: {data['cbr_rate']}%")
    if data.get('inflation'):
        lines.append(f"• Инфляция: {data['inflation']}%")
    
    return '\n'.join(lines)


# ==============================================================================
# 4. ОСНОВНАЯ ЛОГИКА
# ==============================================================================

def load_history():
    if os.path.exists(OUTPUT_HISTORY):
        try:
            with open(OUTPUT_HISTORY, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}


def save_history(history):
    with open(OUTPUT_HISTORY, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def collect_history():
    print("="*70)
    print("📊 СБОРЩИК ИСТОРИИ (2 года)")
    print("="*70)
    print()
    
    history = load_history()
    need_full = 'imoex' not in history or len(history.get('imoex', {}).get('history', [])) < 100
    
    if need_full:
        print("🔄 Первый запуск — загружаем полную историю...\n")
        
        print("📈 Индексы и металлы (MOEX):")
        history['imoex'] = {'history': get_imoex_history()}
        history['gold'] = {'history': get_gold_history()}
        
        print("\n🛢️ Нефть (Yahoo Finance):")
        history['brent'] = {'history': get_brent_history_yahoo()}
        
        print("\n💱 Валюты (ЦБ РФ):")
        history['usd_rub'] = {'history': get_usd_history()}
        history['cny_rub'] = {'history': get_cny_history()}
        history['eur_rub'] = {'history': get_eur_history()}
        
        history['last_update'] = datetime.now().isoformat()
        save_history(history)
        
        print(f"\n💾 История сохранена: {OUTPUT_HISTORY}")
    else:
        print(f"✅ История уже есть (обновлено: {history.get('last_update', '?')})")
    
    return history


def collect_current():
    print("\n" + "="*70)
    print("📊 ТЕКУЩИЕ ЗНАЧЕНИЯ")
    print("="*70)
    print()
    
    data = {
        'timestamp': datetime.now().isoformat(),
        'date': datetime.now().strftime('%Y-%m-%d'),
    }
    
    print("💱 Курсы валют (ЦБ РФ)...")
    cbr_rates = get_cbr_rates()
    if cbr_rates:
        data['usd_rub'] = cbr_rates.get('USD')
        data['eur_rub'] = cbr_rates.get('EUR')
        data['cny_rub'] = cbr_rates.get('CNY')
    
    print("\n📊 Инфляция и ставка ЦБ РФ...")
    cbr_data = get_cbr_inflation_and_rate()
    if cbr_data:
        data['inflation'] = cbr_data['inflation']
        data['cbr_rate'] = cbr_data['rate']
        data['cbr_month'] = cbr_data['date']
    
    print("\n📈 IMOEX...")
    data['imoex'] = get_imoex()
    
    print("\n📊 RVI...")
    data['rvi'] = get_rvi()
    
    print("\n🛢️ Нефть Brent (MOEX)...")
    brent_moex = get_brent_current_moex()
    if brent_moex:
        data['brent_moex'] = brent_moex['price']
        data['brent_ticker'] = brent_moex['ticker']
    
    print("\n🛢️ Нефть Brent (Yahoo, мировая)...")
    brent_yahoo = get_brent_current_yahoo()
    if brent_yahoo:
        data['brent_yahoo'] = brent_yahoo
        data['brent'] = brent_yahoo
    
    print("\n🥇 Золото (MOEX)...")
    gold = get_gold_current_moex()
    if gold:
        data['gold'] = gold['price']
        data['gold_ticker'] = gold['ticker']
    
    return data


# ==============================================================================
# ЗАПУСК
# ==============================================================================

if __name__ == "__main__":
    history = collect_history()
    current = collect_current()
    
    with open(OUTPUT_CURRENT, 'w', encoding='utf-8') as f:
        json.dump(current, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Текущие данные: {OUTPUT_CURRENT}")
    
    print("\n" + "="*70)
    print("📊 ТЕКУЩИЕ ДАННЫЕ")
    print("="*70)
    print(format_current_for_llm(current))
    
    print("\n" + "="*70)
    print("📊 ИСТОРИЯ (СВОДКА + 7 ДНЕЙ)")
    print("="*70)
    print(format_history_for_llm(history, current))
    
    print("\n" + "="*70)
    print("✅ Готово!")
    print("="*70)