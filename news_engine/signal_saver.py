# signal_saver.py — Сохранение сигналов в signals_history/ (v2)
"""
Читает:
- data/final_strategy.json    ← LLM (selected + alternatives)
- data/scanner_signals.json   ← блоки, R:R, quality

Сохраняет:
- data/signals_history/{mode}/{date}.json

Изменения v2:
- entry_time = дата сигнала + фиксированное время (08:00 / 18:00)
- added_at = реальное время добавления

Логика:
1. Проверяет, есть ли файл за сегодня
2. Если есть — читает, объединяет (дедупликация по signal_id)
3. Обогащает каждый сигнал:
   - entry_zone (position_in_block, zone)
   - trigger_analysis (types, quality)
   - context (macro, phase, focus_sector)
4. Альтернативы — берём из сканера, если есть
5. Сохраняет

Использование:
    from signal_saver import save_signals
    save_signals(mode='morning')
"""

import os
import json
import re
import sys
import io
from datetime import datetime

# === AUTO-PATCHED LOGGING ===
import sys as _sys
import io as _io

# UTF-8 для stdout/stderr
if _sys.stdout.encoding and _sys.stdout.encoding.lower() != 'utf-8':
    _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace')
if _sys.stderr.encoding and _sys.stderr.encoding.lower() != 'utf-8':
    _sys.stderr = _io.TextIOWrapper(_sys.stderr.buffer, encoding='utf-8', errors='replace')

_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bat', 'run_log.txt')

def log(*args, **kwargs):
    """Печатает в консоль + пишет в bat/run_log.txt (UTF-8)."""
    msg = ' '.join(str(a) for a in args)
    print(*args, **kwargs)
    try:
        os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)
        with open(_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass
# === END AUTO-PATCHED ===

# 🔥 UTF-8 для stdout/stderr
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bat', 'run_log.txt')

def log(*args, **kwargs):
    """Печатает в консоль + пишет в bat/run_log.txt (UTF-8)."""
    msg = ' '.join(str(a) for a in args)
    print(*args, **kwargs)
    try:
        os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)
        with open(_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(SCRIPT_DIR, 'data')
SIGNALS_HISTORY_DIR = os.path.join(DATA_DIR, 'signals_history')

os.makedirs(SIGNALS_HISTORY_DIR, exist_ok=True)


# ==============================================================================
# ЗАГРУЗКА
# ==============================================================================

def load_json(filename, subdir=None):
    if subdir:
        filepath = os.path.join(DATA_DIR, subdir, filename)
    else:
        filepath = os.path.join(DATA_DIR, filename)
    
    if not os.path.exists(filepath):
        return None
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"   ⚠️ Ошибка чтения {filename}: {e}")
        return None


def load_existing_history(mode, date_str):
    """Загружает существующий файл signals_history/{mode}/{date}.json"""
    filepath = os.path.join(SIGNALS_HISTORY_DIR, mode, f'{date_str}.json')
    
    if not os.path.exists(filepath):
        return None
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


# ==============================================================================
# ENTRY ZONE
# ==============================================================================

def calc_entry_zone(entry_price, block_low, block_high):
    """Считает зону входа в блоке."""
    if block_low is None or block_high is None:
        return None
    
    if block_high <= block_low:
        return None
    
    width = block_high - block_low
    position = (entry_price - block_low) / width * 100
    
    # 🔥 Клампим на 0-100 (entry может быть вне блока)
    position = max(0, min(100, position))
    
    if position < 33:
        zone = "LOWER_THIRD"
    elif position < 66:
        zone = "MIDDLE_THIRD"
    else:
        zone = "UPPER_THIRD"
    
    if entry_price < block_low:
        entry_vs_block = "BELOW"
    elif entry_price > block_high:
        entry_vs_block = "ABOVE"
    else:
        entry_vs_block = "INSIDE"
    
    return {
        "position_in_block_pct": round(position, 1),
        "zone": zone,
        "distance_from_low_pct": round((entry_price - block_low) / entry_price * 100, 2),
        "distance_from_high_pct": round((block_high - entry_price) / entry_price * 100, 2),
        "entry_vs_block": entry_vs_block,
    }


# ==============================================================================
# TRIGGER ANALYSIS
# ==============================================================================

def parse_trigger(trigger_text, signal, macro_context):
    """Парсит текстовый trigger от LLM в структуру."""
    if not trigger_text:
        return None
    
    text_lower = trigger_text.lower()
    types = []
    
    # PRICE_ZONE: упоминание цены входа
    if any(kw in text_lower for kw in ['от ', 'уровень', 'цена', 'покупка от', 'шорт от', 'при ']):
        if re.search(r'\d+', trigger_text):
            types.append('PRICE_ZONE')
    
    # MACRO_CONFIRM: упоминание макро
    if any(kw in text_lower for kw in ['brent', 'нефт', 'imoex', 'ставк', 'цб']):
        types.append('MACRO_CONFIRM')
    
    # STOCH_EXTREME: проверяем Stoch сигнала
    stoch = signal.get('stoch')
    if stoch is not None:
        if stoch < 25 or stoch > 75:
            types.append('STOCH_EXTREME')
    
    # BLOCK_BOUNCE: упоминание блока
    if any(kw in text_lower for kw in ['блок', 'support', 'resistance', 'отскок']):
        types.append('BLOCK_BOUNCE')
    
    # Приоритет
    if 'PRICE_ZONE' in types:
        priority = 'PRICE_ZONE'
    elif 'MACRO_CONFIRM' in types:
        priority = 'MACRO_CONFIRM'
    elif types:
        priority = types[0]
    else:
        priority = 'OTHER'
    
    # Качество
    if len(types) >= 2:
        quality = 'STRONG'
    elif len(types) == 1:
        quality = 'NORMAL'
    else:
        quality = 'WEAK'
    
    return {
        'llm_text': trigger_text,
        'types_detected': types,
        'priority_type': priority,
        'quality': quality,
        'all_conditions_met': True,
    }


# ==============================================================================
# ПОИСК В СКАНЕРЕ
# ==============================================================================

def find_in_scanner(ticker, direction, scanner_signals):
    """Находит сигнал в scanner_signals.json."""
    if not scanner_signals or not scanner_signals.get('signals'):
        return None
    
    for s in scanner_signals['signals']:
        if s.get('ticker') == ticker and s.get('direction') == direction:
            return s
    
    return None


# ==============================================================================
# ДЕДУПЛИКАЦИЯ
# ==============================================================================

def calc_block_overlap(block1, block2):
    """Пересечение двух блоков в % от меньшего."""
    if not block1 or not block2:
        return 0
    
    low1, high1 = block1.get('low'), block1.get('high')
    low2, high2 = block2.get('low'), block2.get('high')
    
    if None in (low1, high1, low2, high2):
        return 0
    
    overlap_low = max(low1, low2)
    overlap_high = min(high1, high2)
    
    if overlap_high <= overlap_low:
        return 0
    
    overlap_size = overlap_high - overlap_low
    width1 = high1 - low1
    width2 = high2 - low2
    min_width = min(width1, width2)
    
    if min_width <= 0:
        return 0
    
    return overlap_size / min_width * 100


def check_duplicate(new_signal, existing_signals):
    """Дубликат = тот же тикер + направление + пересечение > 50%."""
    new_ticker = new_signal.get('ticker')
    new_direction = new_signal.get('direction')
    new_block = {
        'low': new_signal.get('block_low'),
        'high': new_signal.get('block_high'),
    }
    
    if new_block['low'] is None or new_block['high'] is None:
        return None
    
    for existing in existing_signals:
        if existing.get('ticker') != new_ticker:
            continue
        if existing.get('direction') != new_direction:
            continue
        
        existing_block = {
            'low': existing.get('block_low'),
            'high': existing.get('block_high'),
        }
        
        if existing_block['low'] is None or existing_block['high'] is None:
            continue
        
        overlap = calc_block_overlap(new_block, existing_block)
        if overlap > 50:
            return existing.get('signal_id')
    
    return None


# ==============================================================================
# ОБОГАЩЕНИЕ СИГНАЛА
# ==============================================================================

def enrich_signal(raw_signal, scanner_data, macro_context, macro_data,
                  entry_time, date_str, mode, source='selected'):
    """Обогащает сигнал."""
    ticker = raw_signal.get('ticker')
    direction = raw_signal.get('direction')
    
    if not ticker or not direction:
        return None
    
    scanner_signal = find_in_scanner(ticker, direction, scanner_data)
    
    entry = raw_signal.get('entry')
    stop = raw_signal.get('stop')
    target = raw_signal.get('target')
    size = raw_signal.get('size')
    
    # 🔥 Если entry = 0 или None — берём из сканера
    if not entry or entry == 0:
        if scanner_signal:
            entry = scanner_signal.get('price')
    
    # Если stop = 0 или None — из сканера
    if not stop or stop == 0:
        if scanner_signal:
            stop = scanner_signal.get('stop', {}).get('price')
    
    # Если target = 0 или None — из сканера
    if not target or target == 0:
        if scanner_signal:
            targets = scanner_signal.get('targets', [])
            if targets:
                target = targets[0].get('price')
    
    # 🔥 Если entry всё ещё 0/None — пропускаем сигнал
    if not entry or entry == 0:
        print(f"   ⚠️ {ticker} {direction}: entry = 0, пропускаем")
        return None
    
    # Из сканера
    block_low = None
    block_high = None
    stoch = None
    r_r = None
    quality = None
    final_rating = None
    
    if scanner_signal:
        entry_block = scanner_signal.get('entry_block', {})
        block_low = entry_block.get('low')
        block_high = entry_block.get('high')
        stoch = scanner_signal.get('stoch')
        r_r = scanner_signal.get('risk_reward')
        quality = scanner_signal.get('quality')
        final_rating = scanner_signal.get('final_rating')
    
    # Entry zone
    entry_zone = None
    if entry and block_low is not None and block_high is not None:
        entry_zone = calc_entry_zone(entry, block_low, block_high)
    
    # Trigger analysis
    trigger_text = raw_signal.get('trigger') or ''
    trigger_analysis = None
    if trigger_text:
        trigger_analysis = parse_trigger(trigger_text, {'stoch': stoch}, macro_context)
    
    # Context
    focus_sectors = macro_context.get('focus_sectors', {})
    
    try:
        from news_engine import TICKER_TO_SECTOR
        sector = TICKER_TO_SECTOR.get(ticker, 'unknown')
    except Exception:
        sector = 'unknown'
    
    focus_direction = focus_sectors.get(sector)
    
    context = {
        'market_phase': macro_context.get('market_phase'),
        'macro': {
            'brent': macro_data.get('brent'),
            'brent_moex': macro_data.get('brent_moex'),
            'imoex': macro_data.get('imoex'),
            'rvi': macro_data.get('rvi'),
            'usd_rub': macro_data.get('usd_rub'),
            'cny_rub': macro_data.get('cny_rub'),
            'cbr_rate': macro_data.get('cbr_rate'),
            'inflation': macro_data.get('inflation'),
            'macro_score': macro_context.get('macro_score'),
            'risk_level': macro_context.get('risk_level'),
            'imoex_position': macro_context.get('imoex_position'),
        },
        'focus_sector': sector,
        'focus_direction': focus_direction,
        'key_risks': macro_context.get('key_risks', []),
        'news_tone': macro_context.get('news_tone'),
        'critical_events': macro_context.get('critical_events', []),
        'news_summary': macro_context.get('news_summary'),
    }
    
    # signal_id
    date_compact = date_str.replace('-', '')
    signal_id = f"{ticker}_{date_compact}_{mode}_{direction}"
    if source == 'alternative':
        signal_id += '_alt'
    
    return {
        'signal_id': signal_id,
        'ticker': ticker,
        'direction': direction,
        
        'entry': entry,
        'entry_time': entry_time,
        'stop': stop,
        'target': target,
        'size': size,
        
        'source': source,
        
        'reason': raw_signal.get('reason'),
        'trigger': trigger_text,
        
        'block_low': block_low,
        'block_high': block_high,
        'stoch': stoch,
        'r_r': r_r,
        'quality': quality,
        'final_rating': final_rating,
        
        'entry_zone': entry_zone,
        'trigger_analysis': trigger_analysis,
        'context': context,
        
        'duplicate_of': None,
        'added_at': datetime.now().isoformat(),
    }


# ==============================================================================
# ОСНОВНАЯ ЛОГИКА
# ==============================================================================

def save_signals(mode='morning'):
    """Основная функция сохранения сигналов."""
    log(f"\n{'='*70}")
    log(f"💾 СОХРАНЕНИЕ СИГНАЛОВ ({mode.upper()})")
    log(f"{'='*70}")
    
    # 1. Загрузка
    log("\n📂 Загрузка данных...")
    strategy_data = load_json('final_strategy.json')
    scanner_data = load_json('scanner_signals.json')
    macro_data = load_json('macro_data.json') or {}
    
    if not strategy_data:
        log("❌ final_strategy.json не найден")
        return None
    
    log(f"   ✅ final_strategy.json загружен")
    if scanner_data:
        log(f"   ✅ scanner_signals.json ({len(scanner_data.get('signals', []))} сигналов)")
    else:
        log(f"   ⚠️ scanner_signals.json пуст")
    
    # 2. Мета
    macro_context = strategy_data.get('macro_context', {})
    strategy = strategy_data.get('strategy', {})
    # 🔥 Всегда берём сегодняшнюю дату (не из final_strategy.json)
    date_str = datetime.now().strftime('%Y-%m-%d')
    strategy_date = strategy_data.get('date')
    if strategy_date and strategy_date != date_str:
        log(f"   ⚠️ Дата в strategy ({strategy_date}) != сегодня ({date_str}) — используем сегодняшнюю")
    
    # 🔥 entry_time = дата сигнала + фиксированное время
    if mode == 'morning':
        entry_time = f"{date_str}T08:00:00+03:00"
    else:
        entry_time = f"{date_str}T18:00:00+03:00"
    
    log(f"\n📅 Дата: {date_str}")
    log(f"⏰ entry_time: {entry_time}")
    
    # 3. Проверка существующего файла
    existing = load_existing_history(mode, date_str)
    
    if existing:
        log(f"\n📄 Файл уже существует — объединяем")
        existing_signals = existing.get('signals', [])
        log(f"   Существующих сигналов: {len(existing_signals)}")
    else:
        log(f"\n📄 Создаём новый файл")
        existing_signals = []
    
    # 4. Обработка selected
    selected = strategy.get('selected', [])
    log(f"\n📊 Обработка selected ({len(selected)} сигналов)...")
    
    new_signals = []
    
    for i, raw in enumerate(selected, 1):
        signal = enrich_signal(raw, scanner_data, macro_context, macro_data,
                                entry_time, date_str, mode, source='selected')
        if not signal:
            continue
        
        ticker = signal['ticker']
        direction = signal['direction']
        
        # Проверка дубликата
        existing_for_ticker = [
            s for s in existing_signals + new_signals
            if s.get('ticker') == ticker and s.get('direction') == direction
        ]
        duplicate_of = check_duplicate(signal, existing_for_ticker)
        signal['duplicate_of'] = duplicate_of
        
        new_signals.append(signal)
        
        block_str = f"[{signal['block_low']}, {signal['block_high']}]" if signal['block_low'] else "нет блока"
        dup_str = f" ДУБЛИКАТ({duplicate_of})" if duplicate_of else ""
        log(f"   [{i}/{len(selected)}] {ticker} {direction} @ {signal['entry']} {block_str}{dup_str}")
    
    # 5. Обработка alternative_tickers
    alternatives = strategy.get('alternative_tickers', {})
    alt_count = 0
    
    if alternatives:
        log(f"\n📊 Обработка alternatives...")
        
        for direction in ['LONG', 'SHORT']:
            tickers = alternatives.get(direction, [])
            for ticker in tickers:
                # Уже есть в selected?
                already_exists = any(
                    s.get('ticker') == ticker and s.get('direction') == direction
                    for s in new_signals
                )
                if already_exists:
                    continue
                
                # Ищем в сканере
                scanner_signal = find_in_scanner(ticker, direction, scanner_data)
                if not scanner_signal:
                    log(f"   [alt] {ticker} {direction} — нет в сканере, пропускаем")
                    continue
                
                raw_alt = {
                    'ticker': ticker,
                    'direction': direction,
                    'entry': None,
                    'stop': None,
                    'target': None,
                    'size': None,
                    'reason': f'LLM предложил как альтернативу ({direction})',
                    'trigger': None,
                }
                
                signal = enrich_signal(raw_alt, scanner_data, macro_context, macro_data,
                                        entry_time, date_str, mode, source='alternative')
                if not signal:
                    continue
                
                # Проверка дубликата
                existing_for_ticker = [
                    s for s in existing_signals + new_signals
                    if s.get('ticker') == ticker and s.get('direction') == direction
                ]
                duplicate_of = check_duplicate(signal, existing_for_ticker)
                signal['duplicate_of'] = duplicate_of
                
                new_signals.append(signal)
                alt_count += 1
                
                log(f"   [alt] {ticker} {direction} @ {signal['entry']}")
    
    # 6. Дедупликация по signal_id
    all_signal_ids = {s.get('signal_id') for s in existing_signals}
    unique_new = [s for s in new_signals if s.get('signal_id') not in all_signal_ids]
    
    # 7. Объединение
    combined_signals = existing_signals + unique_new
    
    # 8. Финальный файл
    output = {
        'date': date_str,
        'mode': mode,
        'entry_time': entry_time,
        'created_at': existing.get('created_at') if existing else datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat(),
        
        'macro_context': macro_context,
        'strategy_summary': {
            'strategy_type': strategy.get('strategy'),
            'market_view': strategy.get('market_view'),
            'capital_allocation': strategy.get('capital_allocation'),
        },
        
        'signals': combined_signals,
    }
    
    # 9. Сохранение
    mode_dir = os.path.join(SIGNALS_HISTORY_DIR, mode)
    os.makedirs(mode_dir, exist_ok=True)
    
    filepath = os.path.join(mode_dir, f'{date_str}.json')
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    log(f"\n💾 Сохранено: {filepath}")
    log(f"   Всего сигналов: {len(combined_signals)}")
    log(f"   ├── selected: {len(selected)}")
    log(f"   ├── alternatives: {alt_count}")
    log(f"   └── добавлено новых: {len(unique_new)}")
    
    return output


# ==============================================================================
# ЗАПУСК
# ==============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['morning', 'evening'], default='morning')
    args = parser.parse_args()
    
    save_signals(mode=args.mode)