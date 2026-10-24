# analyze_hits.py — Анализ попаданий сигналов (Hit Rate) v5
"""
Изменения v5:
- Разделение статистики по source: selected vs alternative
- В сводке отдельно считаем Hit Rate для selected и alternative

Изменения v4:
- Проверка наличия свечей за горизонт
- Если свечей за target_date нет — метрики не считаются

Запуск:
    python analyze_hits.py
    python analyze_hits.py --mode morning
    python analyze_hits.py --mode evening
"""

import os
import sys
import io
import json
import argparse
from datetime import datetime, timedelta, time
import pandas as pd
import numpy as np
import requests
from dotenv import load_dotenv

import urllib3

# === AUTO-PATCHED LOGGING ===
import sys as _sys
import io as _io
from datetime import datetime as _dt

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
            f.write(f"[{_dt.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

# === END AUTO-PATCHED ===


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
ENV_PATH = os.path.join(ROOT_DIR, '.env')
DATA_DIR = os.path.join(SCRIPT_DIR, 'data')
SIGNALS_HISTORY_DIR = os.path.join(DATA_DIR, 'signals_history')
HITS_ANALYSIS_DIR = os.path.join(DATA_DIR, 'hits_analysis')

os.makedirs(HITS_ANALYSIS_DIR, exist_ok=True)
load_dotenv(ENV_PATH)

TINKOFF_TOKEN = os.getenv('TINKOFF_TOKEN', '')
if not TINKOFF_TOKEN:
    log("❌ TINKOFF_TOKEN не найден в .env")
    sys.exit(1)

HORIZONS = [1, 3, 5, 10]
LOOKBACK_DAYS = 1
MSK_OFFSET = timedelta(hours=3)
DEFAULT_ENTRY_HOUR = 10
DEFAULT_ENTRY_MINUTE = 0


# ==============================================================================
# FIGI
# ==============================================================================

def load_figi_map():
    filepath = os.path.join(ROOT_DIR, 'all_assets.json')
    if not os.path.exists(filepath):
        filepath = os.path.join(SCRIPT_DIR, 'all_assets.json')
    
    if not os.path.exists(filepath):
        log(f"❌ all_assets.json не найден")
        return {}
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        figi_map = {}
        for ticker, info in data.get('assets', {}).items():
            figi_map[ticker] = info.get('figi', '')
        
        log(f"📁 FIGI загружено: {len(figi_map)}")
        return figi_map
    except Exception as e:
        log(f"❌ Ошибка загрузки FIGI: {e}")
        return {}


# ==============================================================================
# TINKOFF API
# ==============================================================================

class TinkoffClient:
    def __init__(self, token):
        self.token = token
        self.base_url = 'https://invest-public-api.tinkoff.ru/rest'
    
    def get_candles(self, figi, from_dt_utc, to_dt_utc, interval):
        try:
            url = f'{self.base_url}/tinkoff.public.invest.api.contract.v1.MarketDataService/GetCandles'
            headers = {'Authorization': f'Bearer {self.token}'}
            data = {
                'figi': figi,
                'from': from_dt_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'to': to_dt_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'interval': interval,
            }
            
            response = requests.post(url, headers=headers, json=data,
                                     verify=False, timeout=30)
            
            if response.status_code != 200:
                return None
            
            result = response.json()
            candles = result.get('candles', [])
            
            if not candles:
                return None
            
            df = pd.DataFrame([{
                'time': pd.to_datetime(c['time']).tz_convert('Europe/Moscow').tz_localize(None),
                'open': int(c['open']['units']) + int(c['open']['nano']) / 1e9,
                'high': int(c['high']['units']) + int(c['high']['nano']) / 1e9,
                'low': int(c['low']['units']) + int(c['low']['nano']) / 1e9,
                'close': int(c['close']['units']) + int(c['close']['nano']) / 1e9,
                'volume': int(c['volume']),
            } for c in candles])
            
            return df
        except Exception:
            return None


# ==============================================================================
# ENTRY TIME
# ==============================================================================

def get_entry_datetime(signal, entry_date):
    """Возвращает datetime входа в МСК (naive)."""
    entry_time_str = signal.get('entry_time')
    
    if entry_time_str:
        try:
            clean = entry_time_str.replace('+03:00', '').replace('Z', '').replace('+00:00', '')
            if 'T' in clean:
                return datetime.fromisoformat(clean)
            if ':' in clean and len(clean) <= 5:
                h, m = map(int, clean.split(':'))
                return datetime.combine(entry_date, time(h, m))
        except Exception:
            pass
    
    return datetime.combine(entry_date, time(DEFAULT_ENTRY_HOUR, DEFAULT_ENTRY_MINUTE))


# ==============================================================================
# МЕТРИКИ
# ==============================================================================

def calc_hit_metrics(signal, daily_df, horizon_days, entry_date):
    if daily_df is None or len(daily_df) == 0:
        return None
    
    target_date = entry_date + timedelta(days=horizon_days)
    future = daily_df[daily_df['time'].dt.date >= target_date]
    
    if len(future) == 0:
        return None
    
    close_n = future.iloc[0]['close']
    entry = signal['entry']
    direction = signal['direction']
    
    if direction == 'LONG':
        hit = close_n > entry
        change_pct = (close_n - entry) / entry * 100
    else:
        hit = close_n < entry
        change_pct = (entry - close_n) / entry * 100
    
    return {
        'close': round(close_n, 4),
        'close_change_pct': round(change_pct, 2),
        'hit': bool(hit),
    }


def calc_mfe_mae(signal, hourly_df, horizon_days, entry_dt):
    if hourly_df is None or len(hourly_df) == 0:
        return None
    
    target_date = (entry_dt + timedelta(days=horizon_days)).date()
    period = hourly_df[
        (hourly_df['time'] >= entry_dt) &
        (hourly_df['time'].dt.date <= target_date)
    ]
    
    if len(period) == 0:
        return None
    
    entry = signal['entry']
    direction = signal['direction']
    max_high = period['high'].max()
    min_low = period['low'].min()
    
    if direction == 'LONG':
        mfe = max(0, max_high - entry)
        mae = max(0, entry - min_low)
    else:
        mfe = max(0, entry - min_low)
        mae = max(0, max_high - entry)
    
    return {
        'mfe_pct': round(mfe / entry * 100, 2),
        'mae_pct': round(mae / entry * 100, 2),
        'max_high': round(max_high, 4),
        'min_low': round(min_low, 4),
    }


def calc_block_metrics(signal, hourly_df, horizon_days, entry_dt):
    if hourly_df is None or len(hourly_df) == 0:
        return None
    
    target_date = (entry_dt + timedelta(days=horizon_days)).date()
    period = hourly_df[
        (hourly_df['time'] >= entry_dt) &
        (hourly_df['time'].dt.date <= target_date)
    ].reset_index(drop=True)
    
    if len(period) == 0:
        return None
    
    block_low = signal.get('block_low')
    block_high = signal.get('block_high')
    direction = signal['direction']
    
    if block_low is None or block_high is None:
        return None
    
    touch_count = 0
    in_block = False
    for _, candle in period.iterrows():
        if candle['low'] <= block_high and candle['high'] >= block_low:
            if not in_block:
                touch_count += 1
                in_block = True
        else:
            in_block = False
    
    false_breakout = False
    fb_depth_pct = 0
    
    if direction == 'LONG':
        for i, candle in period.iterrows():
            if candle['low'] < block_low:
                future = period.iloc[i+1:]
                if len(future) > 0 and (future['close'] > block_low).any():
                    false_breakout = True
                    fb_depth_pct = (block_low - candle['low']) / block_low * 100
                    break
    else:
        for i, candle in period.iterrows():
            if candle['high'] > block_high:
                future = period.iloc[i+1:]
                if len(future) > 0 and (future['close'] < block_high).any():
                    false_breakout = True
                    fb_depth_pct = (candle['high'] - block_high) / block_high * 100
                    break
    
    return {
        'block_touched': touch_count > 0,
        'block_touch_count': touch_count,
        'false_breakout': bool(false_breakout),
        'false_breakout_depth_pct': round(fb_depth_pct, 2),
    }


def calc_levels_metrics(signal, hourly_df, horizon_days, entry_dt):
    if hourly_df is None or len(hourly_df) == 0:
        return None
    
    target_date = (entry_dt + timedelta(days=horizon_days)).date()
    period = hourly_df[
        (hourly_df['time'] >= entry_dt) &
        (hourly_df['time'].dt.date <= target_date)
    ].reset_index(drop=True)
    
    if len(period) == 0:
        return None
    
    entry = signal['entry']
    target = signal.get('target')
    direction = signal['direction']
    
    if target is None:
        return None
    
    if direction == 'LONG':
        total_distance = target - entry
        levels = [entry + total_distance * i / 4 for i in range(1, 5)]
    else:
        total_distance = entry - target
        levels = [entry - total_distance * i / 4 for i in range(1, 5)]
    
    levels_reached = []
    hours_to_levels = {}
    
    for level_num, level_price in enumerate(levels, 1):
        for i, candle in period.iterrows():
            hit_level = False
            if direction == 'LONG' and candle['high'] >= level_price:
                hit_level = True
            elif direction == 'SHORT' and candle['low'] <= level_price:
                hit_level = True
            
            if hit_level:
                levels_reached.append(level_num)
                hours = (candle['time'] - entry_dt).total_seconds() / 3600
                hours_to_levels[f'hours_to_level_{level_num}'] = round(max(0, hours), 2)
                break
    
    return {
        'levels_reached': levels_reached,
        'levels_total': 4,
        'levels_reached_count': len(levels_reached),
        **hours_to_levels,
    }


def calc_stop_metrics(signal, min15_df, horizon_days, entry_dt):
    if min15_df is None or len(min15_df) == 0:
        return None
    
    target_date = (entry_dt + timedelta(days=horizon_days)).date()
    period = min15_df[
        (min15_df['time'] >= entry_dt) &
        (min15_df['time'].dt.date <= target_date)
    ].reset_index(drop=True)
    
    if len(period) == 0:
        return None
    
    stop = signal.get('stop')
    direction = signal['direction']
    
    if stop is None:
        return None
    
    stop_hit = False
    stop_hit_time = None
    stop_hit_hours = None
    
    for i, candle in period.iterrows():
        hit = False
        if direction == 'LONG' and candle['low'] <= stop:
            hit = True
        elif direction == 'SHORT' and candle['high'] >= stop:
            hit = True
        
        if hit:
            stop_hit = True
            stop_hit_time = candle['time'].isoformat()
            hours = (candle['time'] - entry_dt).total_seconds() / 3600
            stop_hit_hours = round(max(0, hours), 2)
            break
    
    return {
        'stop_hit': bool(stop_hit),
        'stop_hit_time': stop_hit_time,
        'stop_hit_hours': stop_hit_hours,
    }


# ==============================================================================
# АНАЛИЗ СИГНАЛА
# ==============================================================================

def analyze_signal(signal, figi_map, client):
    ticker = signal['ticker']
    entry_date_str = signal.get('date') or signal.get('entry_date')
    
    if not entry_date_str:
        return None
    
    try:
        entry_date = datetime.strptime(entry_date_str, '%Y-%m-%d').date()
    except:
        return None
    
    entry_dt = get_entry_datetime(signal, entry_date)
    
    figi = figi_map.get(ticker)
    if not figi:
        log(f"   ⚠️ {ticker}: FIGI не найден")
        return None
    
    entry_dt_utc = entry_dt - MSK_OFFSET
    from_dt_utc = entry_dt_utc - timedelta(days=LOOKBACK_DAYS)
    to_dt_utc = entry_dt_utc + timedelta(days=max(HORIZONS) + 2)
    
    daily_df = client.get_candles(figi, from_dt_utc, to_dt_utc, 'CANDLE_INTERVAL_DAY')
    hourly_df = client.get_candles(figi, from_dt_utc, to_dt_utc, 'CANDLE_INTERVAL_HOUR')
    min15_df = client.get_candles(figi, from_dt_utc, to_dt_utc, 'CANDLE_INTERVAL_15_MIN')
    
    if daily_df is None:
        log(f"   ⚠️ {ticker}: нет дневных свечей")
        return None
    
    max_daily_date = daily_df['time'].dt.date.max() if len(daily_df) > 0 else None
    
    results = {}
    for horizon in HORIZONS:
        key = f'{horizon}d'
        target_date = entry_date + timedelta(days=horizon)
        
        if max_daily_date is None or max_daily_date < target_date:
            continue
        
        results[key] = {}
        
        hit_data = calc_hit_metrics(signal, daily_df, horizon, entry_date)
        if hit_data:
            results[key].update(hit_data)
        
        mfe_mae = calc_mfe_mae(signal, hourly_df, horizon, entry_dt)
        if mfe_mae:
            results[key].update(mfe_mae)
        
        block_data = calc_block_metrics(signal, hourly_df, horizon, entry_dt)
        if block_data:
            results[key].update(block_data)
        
        levels_data = calc_levels_metrics(signal, hourly_df, horizon, entry_dt)
        if levels_data:
            results[key].update(levels_data)
        
        stop_data = calc_stop_metrics(signal, min15_df, horizon, entry_dt)
        if stop_data:
            results[key].update(stop_data)
    
    mfe_values = [results.get(f'{h}d', {}).get('mfe_pct', 0) or 0 for h in HORIZONS]
    mae_values = [results.get(f'{h}d', {}).get('mae_pct', 0) or 0 for h in HORIZONS]
    levels_values = [results.get(f'{h}d', {}).get('levels_reached_count', 0) or 0 for h in HORIZONS]
    
    best_horizon = None
    best_mfe = 0
    for h in HORIZONS:
        mfe = results.get(f'{h}d', {}).get('mfe_pct', 0) or 0
        if mfe > best_mfe:
            best_mfe = mfe
            best_horizon = f'{h}d'
    
    summary = {
        'hit_1d': results.get('1d', {}).get('hit'),
        'hit_3d': results.get('3d', {}).get('hit'),
        'hit_5d': results.get('5d', {}).get('hit'),
        'hit_10d': results.get('10d', {}).get('hit'),
        'max_mfe_pct': round(max(0, max(mfe_values)), 2),
        'max_mae_pct': round(max(mae_values), 2),
        'stop_hit': any(results.get(f'{h}d', {}).get('stop_hit', False) for h in HORIZONS),
        'false_breakout': any(results.get(f'{h}d', {}).get('false_breakout', False) for h in HORIZONS),
        'levels_reached_max': max(levels_values),
        'best_horizon': best_horizon,
    }
    
    return {
        'signal_id': signal.get('signal_id', f"{ticker}_{entry_date_str}_{signal['direction']}"),
        'ticker': ticker,
        'direction': signal['direction'],
        'date': entry_date_str,
        'mode': signal.get('mode'),
        'source': signal.get('source', 'selected'),   # 🔥 НОВОЕ
        
        'entry': signal['entry'],
        'entry_time': entry_dt.isoformat(),
        'stop': signal.get('stop'),
        'target': signal.get('target'),
        'block_low': signal.get('block_low'),
        'block_high': signal.get('block_high'),

        'r_r': signal.get('r_r'),
        'quality': signal.get('quality'),
        'final_rating': signal.get('final_rating'),
        
        'entry_zone': signal.get('entry_zone'),
        'trigger_analysis': signal.get('trigger_analysis'),
        'context': signal.get('context'),
        
        'results': results,
        'summary': summary,
    }


# ==============================================================================
# ЗАПУСК
# ==============================================================================

def load_signals(mode):
    mode_dir = os.path.join(SIGNALS_HISTORY_DIR, mode)
    
    if not os.path.exists(mode_dir):
        log(f"   ⚠️ Папка не найдена: {mode_dir}")
        return []
    
    signals = []
    for filename in sorted(os.listdir(mode_dir)):
        if not filename.endswith('.json'):
            continue
        
        filepath = os.path.join(mode_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if isinstance(data, dict) and 'signals' in data:
                for s in data['signals']:
                    s.setdefault('date', data.get('date'))
                    s.setdefault('mode', mode)
                    signals.append(s)
            elif isinstance(data, list):
                signals.extend(data)
        except Exception as e:
            log(f"   ⚠️ Ошибка чтения {filename}: {e}")
    
    return signals


def analyze_mode(mode, figi_map, client):
    log(f"\n{'='*70}")
    log(f"📊 РЕЖИМ: {mode.upper()}")
    log(f"{'='*70}")
    
    signals = load_signals(mode)
    
    if not signals:
        log(f"   Нет сигналов")
        return None
    
    log(f"   Сигналов: {len(signals)}")
    
    results = []
    for i, signal in enumerate(signals, 1):
        ticker = signal.get('ticker', '?')
        direction = signal.get('direction', '?')
        date = signal.get('date', '?')
        source = signal.get('source', 'selected')
        source_tag = 'alt' if source == 'alternative' else 'sel'
        
        log(f"   [{i}/{len(signals)}] [{source_tag}] {date} {ticker} {direction}...", end=" ", flush=True)
        
        analyzed = analyze_signal(signal, figi_map, client)
        if analyzed:
            results.append(analyzed)
            s = analyzed['summary']
            
            marks = []
            for h in HORIZONS:
                hit = s.get(f'hit_{h}d')
                if hit is None:
                    marks.append('?')
                elif hit:
                    marks.append('H')
                else:
                    marks.append('M')
            hit_marks = ''.join(marks)
            
            mfe = s.get('max_mfe_pct', 0)
            horizons_available = [k for k in analyzed['results'].keys()]
            
            log(f"✅ [{hit_marks}] MFE={mfe:+.1f}% | горизонты: {','.join(horizons_available) or '—'}")
        else:
            log(f"❌")
    
    output_file = os.path.join(HITS_ANALYSIS_DIR, f'{mode}_detailed.json')
    output = {
        'mode': mode,
        'timestamp': datetime.now().isoformat(),
        'total_signals': len(results),
        'results': results,
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    log(f"\n💾 Сохранено: {output_file}")
    
    # 🔥 Сводка с разделением по source
    if results:
        log(f"\n📊 БЫСТРАЯ СВОДКА ({mode}):")
        
        for source_filter, label in [('all', 'ВСЕ'), ('selected', 'SELECTED'), ('alternative', 'ALT')]:
            if source_filter == 'all':
                filtered = results
            else:
                filtered = [r for r in results if r.get('source') == source_filter]
            
            if not filtered:
                continue
            
            log(f"\n   📌 {label} ({len(filtered)} сигналов):")
            for h in HORIZONS:
                total_with_data = sum(1 for r in filtered if r['summary'].get(f'hit_{h}d') is not None)
                hits = sum(1 for r in filtered if r['summary'].get(f'hit_{h}d') is True)
                if total_with_data > 0:
                    log(f"      Hit {h}д: {hits}/{total_with_data} ({hits/total_with_data*100:.0f}%)")
                else:
                    log(f"      Hit {h}д: нет данных")
    
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['morning', 'evening', 'both'], default='both')
    args = parser.parse_args()
    
    log("="*70)
    log("📊 АНАЛИЗ ПОПАДАНИЙ СИГНАЛОВ (Hit Rate) v5")
    log(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("="*70)
    
    figi_map = load_figi_map()
    if not figi_map:
        log("❌ FIGI не загружены")
        return
    
    client = TinkoffClient(TINKOFF_TOKEN)
    
    modes = ['morning', 'evening'] if args.mode == 'both' else [args.mode]
    
    for mode in modes:
        analyze_mode(mode, figi_map, client)
    
    log("\n" + "="*70)
    log("✅ ГОТОВО")
    log("="*70)


if __name__ == "__main__":
    main()



