# scanner_clean.py — Чистый сканер с финальным рейтингом
"""
Находит сигналы по ордер-блокам (только LuxAlgo) + Stoch RSI.
Финальный рейтинг = близость к блоку (40%) + R:R (60%).
Сохраняет результат в data/scanner_signals.json для LLM.
"""

import os
import sys
import json
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import requests

# 🔥 Отключаем предупреждения SSL
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(SCRIPT_DIR, 'data')

os.makedirs(DATA_DIR, exist_ok=True)
sys.path.append(ROOT_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT_DIR, '.env'))


# ==============================================================================
# НАСТРОЙКИ
# ==============================================================================

STOCH_OVERSOLD = 25
STOCH_OVERBOUGHT = 75

ENTRY_DISTANCE_LUXALGO = 0.7  # дистанция до блока

STOP_OFFSET_PCT = 0.5          # стоп за границей блока

TARGETS_COUNT = 3
MIN_TARGET_DISTANCE_PCT = 1.0
MIN_RR = 1.5

# 🔥 Веса для финального рейтинга
RATING_PROXIMITY_WEIGHT = 0.4
RATING_RR_WEIGHT = 0.6


# ==============================================================================
# LUXALGO ORDER BLOCK DETECTOR
# ==============================================================================

class LuxAlgoOrderBlockDetector:
    """
    Точная реализация Order Block Detector [LuxAlgo] с TradingView.
    Особенности:
    - Пивот объёма определяется на length свечей НАЗАД (ta.pivothigh)
    - Координаты блока: свеча на length назад от пивота
    - Осциллятор на момент пивота
    """
    
    def __init__(self, length=5, bull_ext_last=3, bear_ext_last=3,
                 mitigation_method='Wick'):
        self.length = length
        self.bull_ext_last = bull_ext_last
        self.bear_ext_last = bear_ext_last
        self.mitigation_method = mitigation_method
    
    def find_volume_pivots(self, df):
        """
        Точная реализация ta.pivothigh(volume, length, length).
        Пивот на свече i-length, если volume[i-length] — строгий локальный максимум.
        Возвращает индексы свечей-пивотов.
        """
        volume = df['volume'].values
        length = self.length
        pivot_indices = []
        
        # Начинаем с 2*length, чтобы было достаточно данных
        for i in range(2 * length, len(volume)):
            pivot_idx = i - length  # ← пивот на length назад
            
            if pivot_idx < length:
                continue
            
            # Соседи слева: length свечей
            left = volume[pivot_idx - length:pivot_idx]
            # Соседи справа: length свечей
            right = volume[pivot_idx + 1:pivot_idx + length + 1]
            
            if len(left) < length or len(right) < length:
                continue
            
            current = volume[pivot_idx]
            
            # Строгое неравенство (как в TV)
            if current > np.max(left) and current > np.max(right):
                pivot_indices.append(pivot_idx)
        
        return pivot_indices
    
    def calculate_oscillator(self, df):
        """
        Точная реализация:
        os := high[length] > upper ? 0 : low[length] < lower ? 1 : os[1]
        
        upper = ta.highest(length) — максимум за последние length свечей (включая текущую)
        lower = ta.lowest(length) — минимум за последние length свечей
        """
        high = df['high'].values
        low = df['low'].values
        length = self.length
        
        os_values = np.zeros(len(df))
        
        for i in range(length, len(df)):
            # upper = highest за последние length свечей
            upper = np.max(high[max(0, i - length + 1):i + 1])
            # lower = lowest за последние length свечей
            lower = np.min(low[max(0, i - length + 1):i + 1])
            
            # high[i-length] — high свечи на length назад
            high_n_back = high[i - length] if i >= length else 0
            low_n_back = low[i - length] if i >= length else 0
            
            if high_n_back > upper:
                os_values[i] = 0
            elif low_n_back < lower:
                os_values[i] = 1
            else:
                os_values[i] = os_values[i-1] if i > 0 else 0
        
        return os_values
    
    def detect_blocks(self, df):
        """
        Точная реализация LuxAlgo.
        """
        bull_blocks = []
        bear_blocks = []
        
        pivot_indices = self.find_volume_pivots(df)
        os_values = self.calculate_oscillator(df)
        
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        time_values = df.index.values
        length = self.length
        
        # Targets для митигации
        if self.mitigation_method == 'Close':
            target_bull = pd.Series(close).rolling(window=length).min().values
            target_bear = pd.Series(close).rolling(window=length).max().values
        else:  # Wick
            target_bull = pd.Series(low).rolling(window=length).min().values
            target_bear = pd.Series(high).rolling(window=length).max().values
        
        for pivot_idx in pivot_indices:
            # 🔥 КРИТИЧНО: координаты блока на length свечей НАЗАД от пивота
            block_idx = pivot_idx - length
            
            if block_idx < 0 or block_idx >= len(df):
                continue
            
            if pivot_idx >= len(os_values):
                continue
            
            os_at_pivot = os_values[pivot_idx]
            
            # Бычий блок: phv and os == 1
            if os_at_pivot == 1:
                top = (high[block_idx] + low[block_idx]) / 2  # hl2[length]
                bottom = low[block_idx]
                
                block = {
                    'type': 'bull',
                    'top': float(top),
                    'bottom': float(bottom),
                    'avg': float((top + bottom) / 2),
                    'time': time_values[block_idx],
                    'index': block_idx,
                    'pivot_idx': pivot_idx,
                    'target': float(target_bull[pivot_idx]) if pivot_idx < len(target_bull) else None,
                    'mitigated': False,
                }
                bull_blocks.append(block)
            
            # Медвежий блок: phv and os == 0
            elif os_at_pivot == 0:
                top = high[block_idx]
                bottom = (high[block_idx] + low[block_idx]) / 2  # hl2[length]
                
                block = {
                    'type': 'bear',
                    'top': float(top),
                    'bottom': float(bottom),
                    'avg': float((top + bottom) / 2),
                    'time': time_values[block_idx],
                    'index': block_idx,
                    'pivot_idx': pivot_idx,
                    'target': float(target_bear[pivot_idx]) if pivot_idx < len(target_bear) else None,
                    'mitigated': False,
                }
                bear_blocks.append(block)
        
        # Митигация
        current_price = df['close'].iloc[-1]
        
        for block in bull_blocks:
            if current_price < block['bottom']:
                block['mitigated'] = True
        
        for block in bear_blocks:
            if current_price > block['top']:
                block['mitigated'] = True
        
        # Сортируем по свежести
        bull_blocks.sort(key=lambda x: x['pivot_idx'], reverse=True)
        bear_blocks.sort(key=lambda x: x['pivot_idx'], reverse=True)
        
        bull_blocks = bull_blocks[:self.bull_ext_last]
        bear_blocks = bear_blocks[:self.bear_ext_last]
        
        return bull_blocks, bear_blocks


# ==============================================================================
# FIGI LOADER
# ==============================================================================

class FigiLoader:
    def __init__(self, json_file=None):
        if json_file is None:
            json_file = os.path.join(ROOT_DIR, 'all_assets.json')
        self.json_file = json_file
        self.figi_map = {}
        self.assets_info = {}
        self.load_figi()
    
    def load_figi(self):
        try:
            with open(self.json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            assets = data.get('assets', {})
            for ticker, info in assets.items():
                self.figi_map[ticker] = info.get('figi', '')
                self.assets_info[ticker] = {
                    'name': info.get('name', ticker),
                    'figi': info.get('figi', ''),
                }
            
            print(f"📁 Загружено FIGI: {len(self.figi_map)}")
        except Exception as e:
            print(f"❌ Ошибка загрузки FIGI: {e}")
            sys.exit(1)
    
    def get_figi(self, ticker):
        return self.figi_map.get(ticker, '')
    
    def get_all_tickers(self):
        return list(self.figi_map.keys())


# ==============================================================================
# TINKOFF DATA LOADER (REST + verify=False)
# ==============================================================================

class TinkoffDataLoader:
    def __init__(self, token):
        self.token = token
    
    def get_historical_candles(self, figi, days=90):
        try:
            to_dt = datetime.now()
            from_dt = to_dt - timedelta(days=days)
            
            url = ('https://invest-public-api.tinkoff.ru/rest/'
                   'tinkoff.public.invest.api.contract.v1.MarketDataService/GetCandles')
            headers = {'Authorization': f'Bearer {self.token}'}
            data = {
                'figi': figi,
                'from': from_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'to': to_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'interval': 'CANDLE_INTERVAL_DAY'
            }
            
            response = requests.post(url, headers=headers, json=data,
                                     verify=False, timeout=15)
            
            if response.status_code != 200:
                return None
            
            result = response.json()
            candles = result.get('candles', [])
            
            if candles:
                df = pd.DataFrame([{
                    'date': pd.to_datetime(c['time']),
                    'open': int(c['open']['units']) + int(c['open']['nano']) / 1e9,
                    'high': int(c['high']['units']) + int(c['high']['nano']) / 1e9,
                    'low': int(c['low']['units']) + int(c['low']['nano']) / 1e9,
                    'close': int(c['close']['units']) + int(c['close']['nano']) / 1e9,
                    'volume': int(c['volume'])
                } for c in candles])
                return df
            return None
        except Exception:
            return None


# ==============================================================================
# ORDER BLOCK SCANNER
# ==============================================================================

class OrderBlockScanner:
    def __init__(self, tickers_to_scan=None, max_tickers=100):
        self.luxalgo_detector = LuxAlgoOrderBlockDetector(
            length=5, bull_ext_last=5, bear_ext_last=5, mitigation_method='Wick'
        )
        
        self.tinkoff_token = os.getenv('TINKOFF_TOKEN', '')
        if not self.tinkoff_token:
            print("❌ ОШИБКА: TINKOFF_TOKEN не найден в .env")
            sys.exit(1)
        
        print("\n📁 Загрузка FIGI...")
        self.figi_loader = FigiLoader()
        
        if tickers_to_scan:
            self.tickers = [t for t in tickers_to_scan if t in self.figi_loader.figi_map]
        else:
            all_tickers = self.figi_loader.get_all_tickers()
            self.tickers = all_tickers[:max_tickers]
        
        print(f"📊 Тикеров для сканирования: {len(self.tickers)}")
        
        self.tinkoff = TinkoffDataLoader(self.tinkoff_token)
        self.signals = []
    
    def calculate_stochastic(self, df, k_period=14, d_period=3):
        low_min = df['low'].rolling(window=k_period).min()
        high_max = df['high'].rolling(window=k_period).max()
        
        df['Stoch_K'] = 100 * ((df['close'] - low_min) / (high_max - low_min))
        df['Stoch_D'] = df['Stoch_K'].rolling(window=d_period).mean()
        return df
    
    def calculate_adx(self, df, period=14):
        high = df['high']
        low = df['low']
        close = df['close']
        
        up_move = high - high.shift()
        down_move = low.shift() - low
        
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
        
        tr = pd.concat([
            high - low,
            abs(high - close.shift()),
            abs(low - close.shift())
        ], axis=1).max(axis=1)
        
        atr = tr.rolling(window=period).mean()
        plus_di = 100 * (pd.Series(plus_dm).rolling(window=period).mean() / atr)
        minus_di = 100 * (pd.Series(minus_dm).rolling(window=period).mean() / atr)
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(window=period).mean()
        
        return adx.iloc[-1] if not pd.isna(adx.iloc[-1]) else 25
    
    def check_divergence(self, df, lookback=10):
        if len(df) < lookback:
            return None
        
        price = df['close'].values[-lookback:]
        stoch = df['Stoch_K'].values[-lookback:]
        
        if price[-1] < np.min(price[:-1]) and stoch[-1] > np.min(stoch[:-1]):
            return 'bullish'
        if price[-1] > np.max(price[:-1]) and stoch[-1] < np.max(stoch[:-1]):
            return 'bearish'
        return None
    
    def find_order_blocks_luxalgo(self, df):
        try:
            bull_blocks, bear_blocks = self.luxalgo_detector.detect_blocks(df)
        except Exception:
            return {'bull': [], 'bear': []}
        
        blocks = {'bull': [], 'bear': []}
        
        for block in bull_blocks:
            blocks['bull'].append({
                'type': 'bull', 'method': 'luxalgo',
                'high': float(block['top']),
                'low': float(block['bottom']),
                'start_idx': max(0, int(block['index']) - 2),
                'age': len(df) - int(block['index']),
                'mitigated': bool(block['mitigated']),
            })
        
        for block in bear_blocks:
            blocks['bear'].append({
                'type': 'bear', 'method': 'luxalgo',
                'high': float(block['top']),
                'low': float(block['bottom']),
                'start_idx': max(0, int(block['index']) - 2),
                'age': len(df) - int(block['index']),
                'mitigated': bool(block['mitigated']),
            })
        
        return blocks
    
    def check_price_to_blocks(self, price, blocks_luxalgo):
        result = {'near_bull': None, 'near_bear': None}
        
        for block in blocks_luxalgo['bull']:
            if block['mitigated']:
                continue
            if block['low'] <= price <= block['high']:
                result['near_bull'] = block
                break
            else:
                distance = min(abs(price - block['low']), abs(price - block['high'])) / price * 100
                if distance < ENTRY_DISTANCE_LUXALGO:
                    result['near_bull'] = block
                    break
        
        for block in blocks_luxalgo['bear']:
            if block['mitigated']:
                continue
            if block['low'] <= price <= block['high']:
                result['near_bear'] = block
                break
            else:
                distance = min(abs(price - block['low']), abs(price - block['high'])) / price * 100
                if distance < ENTRY_DISTANCE_LUXALGO:
                    result['near_bear'] = block
                    break
        
        return result
    
    def find_targets(self, price, direction, all_blocks):
        targets = []
        
        for block_type in ['bull', 'bear']:
            for block in all_blocks.get(block_type, []):
                if block['mitigated']:
                    continue
                
                block_mid = (block['high'] + block['low']) / 2
                
                if direction == 'SHORT':
                    if block_mid < price:
                        distance_pct = (price - block_mid) / price * 100
                        if distance_pct >= MIN_TARGET_DISTANCE_PCT:
                            targets.append({
                                'type': block['type'],
                                'high': round(block['high'], 2),
                                'low': round(block['low'], 2),
                                'price': round(block_mid, 2),
                                'distance_pct': round(distance_pct, 2),
                                'method': block['method'],
                            })
                else:
                    if block_mid > price:
                        distance_pct = (block_mid - price) / price * 100
                        if distance_pct >= MIN_TARGET_DISTANCE_PCT:
                            targets.append({
                                'type': block['type'],
                                'high': round(block['high'], 2),
                                'low': round(block['low'], 2),
                                'price': round(block_mid, 2),
                                'distance_pct': round(distance_pct, 2),
                                'method': block['method'],
                            })
        
        targets.sort(key=lambda x: x['distance_pct'])
        return targets[:TARGETS_COUNT]
    
    def calculate_signal_quality(self, df, signal_type, blocks_luxalgo, price_to_blocks):
        score = 0
        details = []
        
        current_stoch = df['Stoch_K'].iloc[-1] if not pd.isna(df['Stoch_K'].iloc[-1]) else 50
        
        # ADX
        try:
            adx = self.calculate_adx(df)
            if adx > 30:
                score += 15
                details.append(f"ADX={adx:.1f} (+15)")
            elif adx > 25:
                score += 10
                details.append(f"ADX={adx:.1f} (+10)")
            elif adx > 20:
                score += 5
                details.append(f"ADX={adx:.1f} (+5)")
        except:
            pass
        
        # Объём
        try:
            volume_sma = df['volume'].rolling(20).mean().iloc[-1]
            current_volume = df['volume'].iloc[-1]
            volume_ratio = current_volume / volume_sma if volume_sma > 0 else 1
            
            if volume_ratio > 2.0:
                score += 15
                details.append(f"Объём x{volume_ratio:.1f} (+15)")
            elif volume_ratio > 1.5:
                score += 10
                details.append(f"Объём x{volume_ratio:.1f} (+10)")
            elif volume_ratio > 1.2:
                score += 5
                details.append(f"Объём x{volume_ratio:.1f} (+5)")
        except:
            pass
        
        # Дивергенция
        divergence = self.check_divergence(df)
        if divergence:
            if (signal_type == 'LONG' and divergence == 'bullish') or \
               (signal_type == 'SHORT' and divergence == 'bearish'):
                score += 20
                details.append(f"{divergence} дивергенция (+20)")
        
        # Блок LuxAlgo
        if signal_type == 'LONG':
            if price_to_blocks['near_bull']:
                score += 10
                details.append("Блоки: LuxAlgo (+10)")
        else:
            if price_to_blocks['near_bear']:
                score += 10
                details.append("Блоки: LuxAlgo (+10)")
        
        # Экстремальность стохастика
        if signal_type == 'LONG':
            if current_stoch < 10:
                score += 15
                details.append(f"Stoch {current_stoch:.1f} <10 (+15)")
            elif current_stoch < 15:
                score += 10
                details.append(f"Stoch {current_stoch:.1f} <15 (+10)")
            elif current_stoch < 20:
                score += 5
                details.append(f"Stoch {current_stoch:.1f} <20 (+5)")
        else:
            if current_stoch > 90:
                score += 15
                details.append(f"Stoch {current_stoch:.1f} >90 (+15)")
            elif current_stoch > 85:
                score += 10
                details.append(f"Stoch {current_stoch:.1f} >85 (+10)")
            elif current_stoch > 80:
                score += 5
                details.append(f"Stoch {current_stoch:.1f} >80 (+5)")
        
        return score, details
    
    def calculate_proximity_score(self, price, block):
        """Оценивает близость цены к блоку (0-100)"""
        if block['low'] <= price <= block['high']:
            return 100
        
        if price > block['high']:
            distance = (price - block['high']) / price * 100
        else:
            distance = (block['low'] - price) / price * 100
        
        if distance <= 0.2:
            return 100
        elif distance <= 0.5:
            return 80
        elif distance <= 0.8:
            return 60
        elif distance <= 1.0:
            return 40
        else:
            return 20
    
    def calculate_rr_score(self, rr):
        """Оценивает R:R (0-100)"""
        if rr > 5:
            return 100
        elif rr > 3:
            return 80
        elif rr > 2:
            return 60
        elif rr > 1.5:
            return 40
        else:
            return 0
    
    def calculate_final_rating(self, signal):
        """Итоговый рейтинг = близость × 0.4 + R:R × 0.6"""
        proximity = signal.get('proximity_score', 50)
        rr = signal.get('rr_score', 50)
        return round(proximity * RATING_PROXIMITY_WEIGHT + rr * RATING_RR_WEIGHT, 1)
    
    def scan_ticker(self, ticker):
        try:
            figi = self.figi_loader.get_figi(ticker)
            if not figi:
                return None
            
            df = self.tinkoff.get_historical_candles(figi, days=120)
            if df is None or len(df) < 30:
                return None
            
            df = self.calculate_stochastic(df)
            
            current_price = df['close'].iloc[-1]
            current_stoch = df['Stoch_K'].iloc[-1] if not pd.isna(df['Stoch_K'].iloc[-1]) else 50
            
            # Фильтр битых данных
            if current_price <= 0:
                print(f"  ❌ {ticker}: цена {current_price} — битые данные")
                return None
            if current_stoch <= 0.1 or current_stoch >= 99.9:
                print(f"  ❌ {ticker}: Stoch {current_stoch} — экстремум")
                return None
            if pd.isna(current_price) or pd.isna(current_stoch):
                print(f"  ❌ {ticker}: NaN в данных")
                return None
            
            # Поиск блоков — только LuxAlgo
            blocks_luxalgo = self.find_order_blocks_luxalgo(df)
            
            all_blocks = {
                'bull': blocks_luxalgo['bull'],
                'bear': blocks_luxalgo['bear'],
            }
            
            price_to_blocks = self.check_price_to_blocks(current_price, blocks_luxalgo)
            
            # Отладка
            if current_stoch < STOCH_OVERSOLD:
                stoch_zone = 'LONG'
            elif current_stoch > STOCH_OVERBOUGHT:
                stoch_zone = 'SHORT'
            else:
                stoch_zone = None
            
            if stoch_zone:
                has_bull = price_to_blocks['near_bull'] is not None
                has_bear = price_to_blocks['near_bear'] is not None
                block_status = ''
                if stoch_zone == 'LONG':
                    block_status = '✅ есть бычий' if has_bull else '❌ НЕТ бычьего'
                else:
                    block_status = '✅ есть медвежий' if has_bear else '❌ НЕТ медвежьего'
                
                print(f"  🔍 {ticker} {stoch_zone} Stoch={current_stoch:.1f} | {block_status}")
            
            # Определяем сигнал
            signal = None
            
            if current_stoch < STOCH_OVERSOLD and price_to_blocks['near_bull']:
                entry_block = price_to_blocks['near_bull']
                signal = {
                    'ticker': ticker,
                    'direction': 'LONG',
                    'price': round(current_price, 2),
                    'stoch': round(current_stoch, 1),
                    'entry_block': {
                        'type': 'bull',
                        'high': round(entry_block['high'], 2),
                        'low': round(entry_block['low'], 2),
                        'method': 'luxalgo',
                    },
                }
            
            elif current_stoch > STOCH_OVERBOUGHT and price_to_blocks['near_bear']:
                entry_block = price_to_blocks['near_bear']
                signal = {
                    'ticker': ticker,
                    'direction': 'SHORT',
                    'price': round(current_price, 2),
                    'stoch': round(current_stoch, 1),
                    'entry_block': {
                        'type': 'bear',
                        'high': round(entry_block['high'], 2),
                        'low': round(entry_block['low'], 2),
                        'method': 'luxalgo',
                    },
                }
            
            if not signal:
                return None
            
            # Проверка блока
            entry_block = signal['entry_block']
            if entry_block['high'] <= 0 or entry_block['low'] <= 0:
                print(f"  ❌ {ticker}: блок с битыми данными")
                return None
            
            # Качество
            quality, quality_details = self.calculate_signal_quality(
                df, signal['direction'], blocks_luxalgo, price_to_blocks
            )
            signal['quality'] = quality
            signal['quality_details'] = quality_details
            
            # Стоп
            if signal['direction'] == 'SHORT':
                stop_price = signal['entry_block']['high'] * (1 + STOP_OFFSET_PCT / 100)
                stop_distance = (stop_price - current_price) / current_price * 100
            else:
                stop_price = signal['entry_block']['low'] * (1 - STOP_OFFSET_PCT / 100)
                stop_distance = (current_price - stop_price) / current_price * 100
            
            signal['stop'] = {
                'price': round(stop_price, 2),
                'distance_pct': round(stop_distance, 2),
            }
            
            # Флаг риска
            if signal['direction'] == 'SHORT':
                distance_to_top = (signal['entry_block']['high'] - current_price) / current_price * 100
                if distance_to_top < 0.3:
                    signal['at_risk'] = True
                    signal['risk_note'] = 'Цена у верхней границы блока — риск пробоя вверх'
                else:
                    signal['at_risk'] = False
            else:
                distance_to_bottom = (current_price - signal['entry_block']['low']) / current_price * 100
                if distance_to_bottom < 0.3:
                    signal['at_risk'] = True
                    signal['risk_note'] = 'Цена у нижней границы блока — риск пробоя вниз'
                else:
                    signal['at_risk'] = False
            
            # Цели
            targets = self.find_targets(current_price, signal['direction'], all_blocks)
            signal['targets'] = targets
            
            # R:R
            if targets and stop_distance > 0:
                first_target = targets[0]
                rr = first_target['distance_pct'] / stop_distance
                signal['risk_reward'] = round(rr, 2)
            else:
                signal['risk_reward'] = 0
            
            # Фильтр R:R
            if signal['risk_reward'] < MIN_RR:
                print(f"  ⛔ {ticker}: {signal['direction']} R:R={signal['risk_reward']:.2f} < {MIN_RR}")
                return None
            
            # 🔥 Близость к блоку
            signal['proximity_score'] = self.calculate_proximity_score(
                current_price, signal['entry_block']
            )
            signal['rr_score'] = self.calculate_rr_score(signal['risk_reward'])
            signal['final_rating'] = self.calculate_final_rating(signal)
            
            # Сценарий пробоя
            if signal['direction'] == 'SHORT':
                breakout_targets = [
                    t for t in self.find_targets(current_price, 'LONG', all_blocks)
                    if t['distance_pct'] < 5
                ]
                if breakout_targets:
                    signal['breakout_scenario'] = {
                        'direction': 'LONG',
                        'trigger': signal['entry_block']['high'],
                        'target': breakout_targets[0],
                    }
            else:
                breakout_targets = [
                    t for t in self.find_targets(current_price, 'SHORT', all_blocks)
                    if t['distance_pct'] < 5
                ]
                if breakout_targets:
                    signal['breakout_scenario'] = {
                        'direction': 'SHORT',
                        'trigger': signal['entry_block']['low'],
                        'target': breakout_targets[0],
                    }
            
            print(f"  ✅ {ticker}: {signal['direction']} ПРОШЁЛ! R:R={signal['risk_reward']:.2f} | Рейтинг={signal['final_rating']}")
            return signal
        
        except Exception:
            return None
    
    def scan_all(self):
        print("\n" + "="*70)
        print("🚀 СКАНЕР ОРДЕР-БЛОКОВ (чистая версия)")
        print("="*70)
        print(f"📊 Тикеров: {len(self.tickers)}")
        print(f"⏰ Время: {datetime.now().strftime('%H:%M:%S')}")
        print(f"⚙️ Stoch LONG < {STOCH_OVERSOLD}, SHORT > {STOCH_OVERBOUGHT}")
        print(f"⚙️ R:R минимум: {MIN_RR}")
        print(f"⚙️ Рейтинг: близость×{RATING_PROXIMITY_WEIGHT} + R:R×{RATING_RR_WEIGHT}")
        print("-"*70)
        
        signals_found = []
        
        for i, ticker in enumerate(self.tickers, 1):
            if i % 10 == 0 or i == len(self.tickers):
                print(f"  [{i}/{len(self.tickers)}]...")
            
            signal = self.scan_ticker(ticker)
            if signal:
                signals_found.append(signal)
        
        self.signals = signals_found
        self.save_signals_json()
        self.print_final_signals()
        
        return signals_found
    
    def save_signals_json(self):
        output = {
            'timestamp': datetime.now().isoformat(),
            'date': datetime.now().strftime('%Y-%m-%d'),
            'total_signals': len(self.signals),
            'signals': self.signals,
        }
        
        filepath = os.path.join(DATA_DIR, 'scanner_signals.json')
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 Сохранено: {filepath}")
    
    def print_final_signals(self):
        """Итоговый вывод с рейтингом"""
        if not self.signals:
            print("\n❌ Нет сигналов")
            return
        
        print("\n" + "="*100)
        print("🎯 ИТОГОВЫЙ ТОРГОВЫЙ ПЛАН (сортировка по рейтингу)")
        print("="*100)
        
        sorted_signals = sorted(
            self.signals,
            key=lambda x: x.get('final_rating', 0),
            reverse=True
        )
        
        print(f"\n{'#':3} | {'Тикер':8} | {'Напр':6} | {'Цена':10} | {'Stoch':7} | {'Кач':5} | {'R:R':6} | {'Близ':5} | {'Рейтинг':8}")
        print("-"*100)
        
        for i, s in enumerate(sorted_signals, 1):
            emoji = '🟢' if s['direction'] == 'LONG' else '🔴'
            print(f"{i:3} | {s['ticker']:8} | {emoji} {s['direction']:4} | {s['price']:10.2f} | "
                  f"{s['stoch']:7.1f} | {s['quality']:5} | {s['risk_reward']:6.2f} | "
                  f"{s['proximity_score']:5} | {s['final_rating']:8.1f}")
        
        print("\n" + "="*100)
        print(f"📊 ИТОГО: {len(self.signals)} сигналов")
        print("="*100)
        
        # Детали топ-5
        print("\n🏆 ТОП-5 СИГНАЛОВ (детально):")
        
        for i, s in enumerate(sorted_signals[:5], 1):
            print(f"\n{'─'*100}")
            emoji = '🟢' if s['direction'] == 'LONG' else '🔴'
            print(f"#{i} {emoji} {s['ticker']} — {s['direction']} | Рейтинг: {s['final_rating']}")
            print(f"{'─'*100}")
            
            block = s['entry_block']
            print(f"   📍 Цена: {s['price']}₽ | Stoch: {s['stoch']}")
            print(f"   📦 Блок: {block['low']} - {block['high']}₽ | Близость: {s['proximity_score']}/100")
            print(f"   ⭐ Качество: {s['quality']}/100")
            print(f"   🛑 Стоп: {s['stop']['price']}₽ ({s['stop']['distance_pct']:+.2f}%)")
            
            if s.get('targets'):
                print(f"   🎯 Цели:")
                for j, t in enumerate(s['targets'], 1):
                    print(f"      {j}. {t['price']}₽ ({t['distance_pct']:+.2f}%)")
            
            print(f"   💰 R:R = {s['risk_reward']} | R:R-балл: {s['rr_score']}/100")
            
            if s.get('at_risk'):
                print(f"   ⚠️ {s.get('risk_note', '')}")


# ==============================================================================
# ЗАПУСК
# ==============================================================================

if __name__ == "__main__":
    scanner = OrderBlockScanner(tickers_to_scan=None, max_tickers=100)
    scanner.scan_all()