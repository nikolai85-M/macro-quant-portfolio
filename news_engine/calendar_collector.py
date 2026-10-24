# calendar_collector.py — Сборщик календаря событий (v3)
"""
Собирает предстоящие события на 7-14 дней:
1. SmartLab — календарь (отчёты, дивиденды, ВОСА)
2. SmartLab — дивиденды (с датами "купить до")
3. ЦБ РФ — заседания по ставке
4. Росстат — публикации инфляции (недельные + месячные)
5. Ручной ввод — ОПЕК, ВВП, конференции

Сохраняет в data/calendar.json
"""

import os
import re
import json
import sys
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)  # ORDER BLOCK
ENV_PATH = os.path.join(SCRIPT_DIR, '.env')
DATA_DIR = os.path.join(SCRIPT_DIR, 'data')
OUTPUT_FILE = os.path.join(DATA_DIR, 'calendar.json')

# 🔥 Добавляем корень проекта в path — для rss_news_filter
sys.path.append(ROOT_DIR)

os.makedirs(DATA_DIR, exist_ok=True)
load_dotenv(ENV_PATH)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
}

HORIZON_DAYS = 7  # Основной горизонт
HORIZON_CBR = 30  # Заседания ЦБ ищем дальше (они редкие)


def safe_get(url, timeout=20, retries=3, quiet=False):
    import time
    for attempt in range(retries):
        try:
            return requests.get(url, headers=HEADERS, timeout=timeout)
        except requests.exceptions.Timeout:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
            else:
                if not quiet:
                    print(f"⚠️ таймаут", end=" ")
                return None
        except Exception as e:
            if not quiet:
                print(f"⚠️ {type(e).__name__}", end=" ")
            return None
    return None


# ==============================================================================
# 1. SMARTLAB — КАЛЕНДАРЬ СОБЫТИЙ
# ==============================================================================

def parse_date_dd_mm_yyyy(date_str):
    """Парсит дату '12.10.2026' → date"""
    try:
        return datetime.strptime(date_str.strip(), '%d.%m.%Y').date()
    except:
        return None


def classify_event(description):
    """Классифицирует событие по описанию."""
    desc_lower = description.lower()
    
    if 'дивиденд' in desc_lower or 'последний день с дивиденд' in desc_lower:
        return 'dividend', 'MEDIUM', 'Риск гэпа вниз для LONG'
    elif 'отчет' in desc_lower or 'результаты' in desc_lower or 'отчёт' in desc_lower:
        return 'report', 'MEDIUM', 'Волатильность на выходе'
    elif 'вос' in desc_lower or 'гос' in desc_lower or 'совет директор' in desc_lower:
        return 'meeting', 'LOW', 'Корпоративное событие'
    elif 'инфляц' in desc_lower or 'ипц' in desc_lower:
        return 'inflation', 'HIGH', 'КРИТИЧНО: влияет на ставку ЦБ'
    elif 'ставк' in desc_lower or 'цб' in desc_lower:
        return 'rate', 'HIGH', 'КРИТИЧНО: влияет на весь рынок'
    else:
        return 'other', 'LOW', ''


def get_smartlab_calendar():
    """Календарь событий SmartLab"""
    print(f"   📅 SmartLab календарь...", end=" ", flush=True)
    
    url = "https://smart-lab.ru/calendar/"
    response = safe_get(url, timeout=20)
    
    if not response or response.status_code != 200:
        print("❌")
        return []
    
    try:
        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table')
        
        today = datetime.now().date()
        horizon = today + timedelta(days=HORIZON_DAYS)
        
        events = []
        
        for table in tables:
            rows = table.find_all('tr')
            if not rows:
                continue
            
            # Заголовки
            headers_cells = rows[0].find_all(['th', 'td'])
            headers_text = [c.text.strip() for c in headers_cells]
            
            # Ищем таблицу с 'Дата' и 'Описание'
            if 'Дата' not in headers_text or 'Описание' not in headers_text:
                continue
            
            date_idx = headers_text.index('Дата')
            desc_idx = headers_text.index('Описание')
            
            for row in rows[1:]:
                cells = row.find_all(['td', 'th'])
                if len(cells) <= max(date_idx, desc_idx):
                    continue
                
                date_str = cells[date_idx].text.strip()
                description = cells[desc_idx].text.strip()
                
                if not date_str or not description:
                    continue
                
                date_obj = parse_date_dd_mm_yyyy(date_str)
                if not date_obj:
                    continue
                
                if not (today <= date_obj <= horizon):
                    continue
                
                # Классифицируем
                event_type, impact, note = classify_event(description)
                
                # Извлекаем тикер (первое слово до ':')
                ticker = None
                if ':' in description:
                    ticker = description.split(':')[0].strip()
                
                events.append({
                    'date': date_obj.strftime('%Y-%m-%d'),
                    'days_until': (date_obj - today).days,
                    'event': description,
                    'event_type': event_type,
                    'ticker': ticker,
                    'impact': impact,
                    'note': note,
                })
        
        print(f"✅ {len(events)}")
        return events
    
    except Exception as e:
        print(f"❌ {type(e).__name__}")
        return []


# ==============================================================================
# 2. SMARTLAB — ДИВИДЕНДЫ
# ==============================================================================

def get_smartlab_dividends():
    """Дивиденды с датами 'купить до'"""
    print(f"   💰 SmartLab дивиденды...", end=" ", flush=True)
    
    url = "https://smart-lab.ru/dividends/"
    response = safe_get(url, timeout=20)
    
    if not response or response.status_code != 200:
        print("❌")
        return []
    
    try:
        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table')
        
        today = datetime.now().date()
        horizon = today + timedelta(days=HORIZON_DAYS + 7)  # +7 дней для "купить до"
        
        events = []
        seen = set()
        
        for table in tables:
            rows = table.find_all('tr')
            if not rows:
                continue
            
            headers_cells = rows[0].find_all(['th', 'td'])
            headers_text = [c.text.strip() for c in headers_cells]
            
            # Ищем таблицу с дивидендами
            if 'Тикер' not in headers_text or 'Купить До' not in headers_text:
                continue
            
            ticker_idx = headers_text.index('Тикер')
            dividend_idx = headers_text.index('Дивиденд,руб') if 'Дивиденд,руб' in headers_text else None
            yield_idx = headers_text.index('Див.Дох.') if 'Див.Дох.' in headers_text else None
            buy_until_idx = headers_text.index('Купить До')
            registry_idx = headers_text.index('Дата закрытия реестра') if 'Дата закрытия реестра' in headers_text else None
            
            for row in rows[1:]:
                cells = row.find_all(['td', 'th'])
                if len(cells) <= buy_until_idx:
                    continue
                
                ticker = cells[ticker_idx].text.strip()
                buy_until_str = cells[buy_until_idx].text.strip()
                
                if not ticker or not buy_until_str:
                    continue
                
                buy_until = parse_date_dd_mm_yyyy(buy_until_str)
                if not buy_until:
                    continue
                
                if not (today <= buy_until <= horizon):
                    continue
                
                key = f"{ticker}_{buy_until}"
                if key in seen:
                    continue
                seen.add(key)
                
                event = {
                    'date': buy_until.strftime('%Y-%m-%d'),
                    'days_until': (buy_until - today).days,
                    'ticker': ticker,
                    'event': f'Дивиденд {ticker}: последний день покупки',
                    'event_type': 'dividend',
                    'impact': 'MEDIUM',
                    'note': 'Риск гэпа вниз для LONG',
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
                
                if registry_idx is not None:
                    registry_str = cells[registry_idx].text.strip()
                    registry = parse_date_dd_mm_yyyy(registry_str)
                    if registry:
                        event['registry_date'] = registry.strftime('%Y-%m-%d')
                
                events.append(event)
        
        print(f"✅ {len(events)}")
        return events
    
    except Exception as e:
        print(f"❌ {type(e).__name__}")
        return []


# ==============================================================================
# 3. ЦБ РФ — ЗАСЕДАНИЯ ПО СТАВКЕ
# ==============================================================================

def get_cbr_meetings():
    """Заседания ЦБ РФ — парсим общий календарь"""
    print(f"   🏦 ЦБ РФ заседания...", end=" ", flush=True)
    
    url = "https://www.cbr.ru/calendar/"
    response = safe_get(url, timeout=20)
    
    if not response or response.status_code != 200:
        print("❌")
        return []
    
    try:
        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table')
        
        today = datetime.now().date()
        horizon = today + timedelta(days=HORIZON_CBR)
        
        events = []
        seen_dates = set()
        
        for table in tables:
            rows = table.find_all('tr')
            if not rows:
                continue
            
            # Проверяем, есть ли в таблице "заседан" + "ставк"
            table_text = table.get_text().lower()
            if 'заседан' not in table_text:
                continue
            
            for row in rows:
                cells = row.find_all(['td', 'th'])
                row_text = ' '.join(c.text.strip() for c in cells)
                row_lower = row_text.lower()
                
                # Ищем "заседание" + "ставк"
                if 'заседан' not in row_lower:
                    continue
                if 'ставк' not in row_lower and 'ключев' not in row_lower:
                    continue
                
                # Ищем дату в строке
                dates = re.findall(r'(\d{2})\.(\d{2})\.(\d{4})', row_text)
                for d, m, y in dates:
                    try:
                        date_obj = datetime(int(y), int(m), int(d)).date()
                        if today <= date_obj <= horizon:
                            date_str = date_obj.strftime('%Y-%m-%d')
                            if date_str not in seen_dates:
                                seen_dates.add(date_str)
                                events.append({
                                    'date': date_str,
                                    'days_until': (date_obj - today).days,
                                    'event': 'Заседание ЦБ РФ по ключевой ставке',
                                    'event_type': 'rate',
                                    'impact': 'HIGH',
                                    'affected_sectors': ['finance', 'developers'],
                                    'note': 'Решение по ставке — влияет на весь рынок',
                                })
                    except:
                        continue
        
        print(f"✅ {len(events)}")
        return events
    
    except Exception as e:
        print(f"❌ {type(e).__name__}")
        return []


# ==============================================================================
# 4. РОССТАТ — ПУБЛИКАЦИИ ИНФЛЯЦИИ
# ==============================================================================

def get_rosstat_inflation_calendar():
    """
    Календарь публикаций инфляции Росстата.
    Публикации: еженедельно (среда) + ежемесячно.
    """
    print(f"   📊 Росстат инфляция...", end=" ", flush=True)
    
    # Росстат публикует недельную инфляцию каждую среду
    # Месячную — 6-10 рабочий день следующего месяца
    # Мы знаем расписание, поэтому генерируем его сами + пытаемся парсить
    
    today = datetime.now().date()
    horizon = today + timedelta(days=HORIZON_DAYS + 7)
    
    events = []
    
    # Еженедельная инфляция — каждая среда
    current = today
    while current <= horizon:
        if current.weekday() == 2:  # Среда
            events.append({
                'date': current.strftime('%Y-%m-%d'),
                'days_until': (current - today).days,
                'event': 'Росстат: недельная инфляция',
                'event_type': 'inflation',
                'impact': 'MEDIUM',
                'note': 'Рынок чувствителен к недельным данным',
            })
        current += timedelta(days=1)
    
    # Месячная инфляция — 8-10 число каждого месяца (приблизительно)
    # Ищем в следующие 2 месяца
    for month_offset in [0, 1]:
        target_month = today.month + month_offset
        target_year = today.year
        if target_month > 12:
            target_month -= 12
            target_year += 1
        
        # Примерная дата: 9 число следующего месяца
        try:
            report_date = datetime(target_year, target_month, 9).date()
            if today <= report_date <= horizon:
                events.append({
                    'date': report_date.strftime('%Y-%m-%d'),
                    'days_until': (report_date - today).days,
                    'event': f'Росстат: инфляция за {target_month-1 if target_month > 1 else 12} месяц',
                    'event_type': 'inflation',
                    'impact': 'HIGH',
                    'note': 'КРИТИЧНО: влияет на решение ЦБ по ставке',
                })
        except:
            pass
    
    # Попробуем также спарсить реальный календарь
    try:
        url = "https://rosstat.gov.ru/statistics/monitoring/sdds/calendar"
        response = safe_get(url, timeout=15, quiet=True)
        
        if response and response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            text = soup.get_text().lower()
            
            # Если страница доступна — можно уточнить, но пока оставим генерацию
    except:
        pass
    
    print(f"✅ {len(events)}")
    return events


# ==============================================================================
# 5. РУЧНОЙ ВВОД
# ==============================================================================

def get_manual_events():
    """Макро-события из ручного файла"""
    print(f"   📝 Ручные события...", end=" ", flush=True)
    
    manual_file = os.path.join(DATA_DIR, 'manual_events.json')
    
    if not os.path.exists(manual_file):
        template = {
            "events": [
                {
                    "date": "2026-10-15",
                    "event": "Пример: заседание ОПЕК",
                    "impact": "MEDIUM",
                    "affected_sectors": ["oil_gas"]
                }
            ],
            "note": "Заполнять вручную. ОПЕК, ВВП, крупные конференции, выборы"
        }
        with open(manual_file, 'w', encoding='utf-8') as f:
            json.dump(template, f, indent=2, ensure_ascii=False)
        print("⚠️ шаблон создан")
        return []
    
    try:
        with open(manual_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        today = datetime.now().date()
        horizon = today + timedelta(days=HORIZON_DAYS + 7)
        
        events = []
        for event in data.get('events', []):
            try:
                event_date = datetime.strptime(event['date'], '%Y-%m-%d').date()
                if today <= event_date <= horizon:
                    events.append({
                        'date': event['date'],
                        'days_until': (event_date - today).days,
                        'event': event['event'],
                        'event_type': 'manual',
                        'impact': event.get('impact', 'MEDIUM'),
                        'affected_sectors': event.get('affected_sectors', []),
                    })
            except:
                continue
        
        print(f"✅ {len(events)}")
        return events
    
    except Exception as e:
        print(f"⚠️ {type(e).__name__}")
        return []


# ==============================================================================
# ФОРМАТИРОВАНИЕ
# ==============================================================================

def format_for_llm(calendar_data):
    """Форматирует календарь для промпта LLM"""
    lines = [f"📅 КАЛЕНДАРЬ СОБЫТИЙ (на {HORIZON_DAYS} дней):"]
    lines.append("")
    
    # Объединяем все события
    all_events = []
    for key in ['smartlab_calendar', 'smartlab_dividends', 'cbr_meetings', 'rosstat_inflation', 'manual_events']:
        all_events.extend(calendar_data.get(key, []))
    
    if not all_events:
        lines.append("Предстоящих событий не найдено.")
        return '\n'.join(lines)
    
    # Сортируем по дате
    all_events.sort(key=lambda x: x['date'])
    
    # Группируем по дате
    by_date = {}
    for event in all_events:
        date_key = event['date']
        if date_key not in by_date:
            by_date[date_key] = []
        by_date[date_key].append(event)
    
    for date_str in sorted(by_date.keys()):
        events = by_date[date_str]
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        days_until = (date_obj - datetime.now().date()).days
        
        if days_until == 0:
            date_label = "СЕГОДНЯ"
        elif days_until == 1:
            date_label = "ЗАВТРА"
        else:
            date_label = f"через {days_until} дн."
        
        lines.append(f"📅 {date_str} ({date_label}):")
        
        for event in events:
            impact_emoji = {'HIGH': '🔴', 'MEDIUM': '🟡', 'LOW': '🟢'}.get(event.get('impact', 'LOW'), '⚪')
            event_text = event['event']
            
            # Дополнительные детали
            details = []
            if event.get('amount'):
                details.append(f"{event['amount']}₽")
            if event.get('yield_pct'):
                details.append(f"дох. {event['yield_pct']}%")
            if event.get('note'):
                details.append(event['note'])
            
            details_str = f" ({', '.join(details)})" if details else ""
            lines.append(f"   {impact_emoji} {event_text}{details_str}")
        
        lines.append("")
    
    return '\n'.join(lines)


# ==============================================================================
# ОСНОВНАЯ ЛОГИКА
# ==============================================================================

def collect_calendar():
    print("="*70)
    print("📅 СБОРЩИК КАЛЕНДАРЯ СОБЫТИЙ v3")
    print("="*70)
    print()
    
    today = datetime.now()
    horizon = today + timedelta(days=HORIZON_DAYS)
    
    print(f"📆 Период: {today.strftime('%Y-%m-%d')} → {horizon.strftime('%Y-%m-%d')}\n")
    
    calendar_data = {
        'generated': today.isoformat(),
        'horizon_days': HORIZON_DAYS,
        'period_start': today.strftime('%Y-%m-%d'),
        'period_end': horizon.strftime('%Y-%m-%d'),
    }
    
    print("📊 Сбор событий:")
    calendar_data['smartlab_calendar'] = get_smartlab_calendar()
    calendar_data['smartlab_dividends'] = get_smartlab_dividends()
    calendar_data['cbr_meetings'] = get_cbr_meetings()
    calendar_data['rosstat_inflation'] = get_rosstat_inflation_calendar()
    calendar_data['manual_events'] = get_manual_events()
    
    # 🔥 ДЕДУПЛИКАЦИЯ: по (date, ticker, event_type)
    seen = set()
    total = 0
    all_events = []
    
    # Порядок важен: сначала более важные источники
    source_order = [
        'cbr_meetings',       # ЦБ — самое важное
        'rosstat_inflation',  # Инфляция
        'smartlab_dividends', # Дивиденды с деталями
        'smartlab_calendar',  # Общие события
        'manual_events',      # Ручные
    ]
    
    for source_key in source_order:
        events = calendar_data[source_key]
        unique = []
        
        for event in events:
            # Ключ дедупликации
            date = event.get('date', '')
            ticker = event.get('ticker', '')
            event_type = event.get('event_type', '')
            event_text = event.get('event', '')[:40]  # Первые 40 символов
            
            # 🔥 Особый случай: дивиденды TATN/TATNP — считаем одним событием
            if event_type == 'dividend' and ticker:
                # Нормализуем тикер (TATNP → TATN для дедупликации дивидендов)
                base_ticker = ticker.replace('P', '').replace('_P', '') if ticker.endswith('P') else ticker
                dedup_key = (date, base_ticker, 'dividend')
            else:
                dedup_key = (date, ticker, event_type, event_text)
            
            if dedup_key not in seen:
                seen.add(dedup_key)
                unique.append(event)
        
        calendar_data[source_key] = unique
        total += len(unique)
        all_events.extend(unique)
    
    calendar_data['total_events'] = total
    calendar_data['all_events'] = sorted(all_events, key=lambda x: x['date'])
    
    return calendar_data


def save_calendar(calendar_data):
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(calendar_data, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Сохранено: {OUTPUT_FILE}")


# ==============================================================================
# ЗАПУСК
# ==============================================================================

if __name__ == "__main__":
    calendar_data = collect_calendar()
    
    print("\n" + "="*70)
    print(f"📅 ИТОГО СОБЫТИЙ: {calendar_data['total_events']}")
    print(f"   SmartLab календарь: {len(calendar_data['smartlab_calendar'])}")
    print(f"   SmartLab дивиденды: {len(calendar_data['smartlab_dividends'])}")
    print(f"   ЦБ РФ заседания: {len(calendar_data['cbr_meetings'])}")
    print(f"   Росстат инфляция: {len(calendar_data['rosstat_inflation'])}")
    print(f"   Ручные события: {len(calendar_data['manual_events'])}")
    print("="*70)
    print()
    
    print(format_for_llm(calendar_data))
    
    save_calendar(calendar_data)
    
    print("="*70)
    print("✅ Готово!")
    print("="*70)