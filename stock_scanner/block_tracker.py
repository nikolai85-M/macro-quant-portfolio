# block_tracker.py
# Трекер для блочной системы v2.2
# - Исправленная логика стопов (минимальный убыток)
# - Правильное отображение P&L (бумажный + зафиксированный)
# - Честный анализ по историческим свечам
# - Retry при ошибках API

import json
import os
import time
import pandas as pd
from datetime import datetime, timedelta
from position_tracker import DemoPositionTracker

class BlockDemoTracker(DemoPositionTracker):
    """
    Трекер для блочной системы (отдельные файлы)
    Версия 2.2 — исправленные стопы и P&L
    """
    
    def __init__(self, initial_capital=1_000_000):
        super().__init__(initial_capital)
        
        self.positions_file = 'data/positions_blocks.json'
        self.positions = []
        self.closed_positions = []
        self.load_positions()
    
    def load_positions(self):
        """Загружает позиции из файла"""
        if os.path.exists(self.positions_file):
            try:
                with open(self.positions_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.positions = data.get('positions', [])
                    self.closed_positions = data.get('closed_positions', [])
                    self.daily_pnl = data.get('daily_pnl', [])
                    print(f"[ФАЙЛ] Загружено {len(self.positions)} активных, {len(self.closed_positions)} закрытых")
            except Exception as e:
                print(f"[ОШИБКА] Загрузки: {e}")
        else:
            os.makedirs('data', exist_ok=True)
    
    def save_positions(self):
        """Сохраняет позиции в файл"""
        data = {
            'positions': self.positions,
            'closed_positions': self.closed_positions,
            'daily_pnl': self.daily_pnl
        }
        try:
            os.makedirs('data', exist_ok=True)
            with open(self.positions_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[ОШИБКА] Сохранения: {e}")
    
    def add_block_position(self, analysis, entry_price=None, entry_date=None):
        """
        Добавляет позицию на основе анализа блока
        """
        ticker = analysis['ticker']
        
        if self.has_active_position(ticker):
            print(f"[ПРЕДУПРЕЖДЕНИЕ] Позиция по {ticker} уже открыта")
            return None
        
        direction = 'LONG' if analysis['direction'] == 'UP' else 'SHORT'
        probability = analysis['probability']
        current_price = entry_price or analysis.get('current_price', 0)
        block_low = analysis['block_low']
        block_high = analysis['block_high']
        
        # 🔥 НОВАЯ ЛОГИКА СТОПОВ: минимальный убыток из двух вариантов
        if direction == 'LONG':
            # Вариант 1: стоп -2% от входа
            stop_2pct = current_price * 0.98
            
            # Вариант 2: стоп за блоком (-2% от нижней границы)
            stop_block = block_low * 0.98
            
            # Выбираем тот, что ВЫШЕ (ближе к цене, меньше убыток)
            if stop_block > stop_2pct:
                stop_loss = stop_block
                stop_type = 'block'
            else:
                stop_loss = stop_2pct
                stop_type = 'entry'
            
            take_profit_1 = current_price * 1.02
            take_profit_2 = current_price * 1.04
            take_profit_3 = current_price * 1.06
            
            distance_to_block = (current_price - block_high) / current_price * 100
            
        else:  # SHORT
            # Вариант 1: стоп +2% от входа
            stop_2pct = current_price * 1.02
            
            # Вариант 2: стоп за блоком (+2% от верхней границы)
            stop_block = block_high * 1.02
            
            # Выбираем тот, что НИЖЕ (ближе к цене, меньше убыток)
            if stop_block < stop_2pct:
                stop_loss = stop_block
                stop_type = 'block'
            else:
                stop_loss = stop_2pct
                stop_type = 'entry'
            
            take_profit_1 = current_price * 0.98
            take_profit_2 = current_price * 0.96
            take_profit_3 = current_price * 0.94
            
            distance_to_block = (block_low - current_price) / current_price * 100
        
        # Если есть TP1 из анализа — используем его, но не дальше 5%
        if analysis.get('tp1'):
            if direction == 'LONG':
                tp_from_analysis = analysis['tp1']['low']
                if tp_from_analysis > current_price:
                    potential_gain = (tp_from_analysis - current_price) / current_price * 100
                    if potential_gain <= 5:
                        take_profit_1 = tp_from_analysis
            else:
                tp_from_analysis = analysis['tp1']['high']
                if tp_from_analysis < current_price:
                    potential_gain = (current_price - tp_from_analysis) / current_price * 100
                    if potential_gain <= 5:
                        take_profit_1 = tp_from_analysis
        
        position = {
            'id': len(self.positions) + len(self.closed_positions) + 1,
            'ticker': ticker,
            'sector': analysis.get('sector', 'Неизвестно'),
            'direction': direction,
            'entry_date': entry_date or datetime.now().strftime('%Y-%m-%d %H:%M'),
            'entry_price': current_price,
            'current_price': current_price,
            'stop_loss': round(stop_loss, 2),
            'stop_type': stop_type,
            'take_profit_1': round(take_profit_1, 2),
            'take_profit_2': round(take_profit_2, 2),
            'take_profit_3': round(take_profit_3, 2),
            'probability': probability,
            'market_score': analysis.get('market_score', 50),
            'sector_score': analysis.get('sector_score', 50),
            'block_info': {
                'block_low': block_low,
                'block_high': block_high,
                'block_type': analysis['block_type'],
                'block_age': analysis.get('block_age', 30),
                'distance_to_entry': round(distance_to_block, 1),
                'reasons': analysis.get('reasons', [])
            },
            'market_context': {
                'trend': analysis.get('market_trend', 'NEUTRAL'),
                'score': analysis.get('market_score', 50),
                'phase': analysis.get('market_phase', 'NEUTRAL'),
                'drawdown': analysis.get('drawdown', 0)
            },
            'signal_params': {
                'type': analysis.get('signal_type', 'BOUNCE'),
                'potential': analysis.get('potential', 0),
                'stoch_rsi': analysis.get('stoch_rsi', 50),
                'trend_alignment': analysis.get('trend_alignment', 'neutral'),
                'score': analysis.get('score', 0)
            },
            'block_params': {
                'strength': analysis.get('block_strength', 'unknown'),
                'age': analysis.get('block_age', 0),
                'method': analysis.get('block_method', 'unknown')
            },
            'sector_context': {
                'name': analysis.get('sector', 'unknown'),
                'score': analysis.get('sector_score', 50),
                'bias': analysis.get('sector_bias', 'NEUTRAL')
            },
            'dividend_context': {},
            'status': 'ACTIVE',
            'quantity': 1000,
            'initial_quantity': 1000,
            'closed_parts': [],
            'tp1_closed': False,
            'tp2_closed': False,
            'tp3_hit': False,
            'stop_hit': False,
            'history': [{
                'date': entry_date or datetime.now().strftime('%Y-%m-%d %H:%M'),
                'price': current_price,
                'action': 'ENTRY',
                'probability': probability
            }]
        }
        
        # Дивидендный контекст
        div_info = analysis.get('dividend_info')
        if div_info:
            div_yield = (div_info['amount'] / current_price) * 100 if current_price > 0 else 0
            position['dividend_context'] = {
                'yield': round(div_yield, 2),
                'days_to_record': div_info.get('days_to_record'),
                'impact': analysis.get('dividend_impact', 'none'),
                'amount': div_info.get('amount', 0)
            }
        
        self.positions.append(position)
        self.save_positions()
        print(f"[OK] Добавлен блок {ticker} ({direction}) | Вероятность: {probability}% | Цена: {current_price:.2f} | Стоп: {stop_loss:.2f} ({stop_type})")
        return position
    
    def has_active_position(self, ticker):
        """Проверяет, есть ли активная позиция по тикеру"""
        for pos in self.positions:
            if pos['ticker'] == ticker and pos['status'] == 'ACTIVE':
                return True
        return False
    
    def update_position_from_history(self, position, token, max_retries=3):
        """
        Загружает исторические свечи с момента входа и проверяет стопы/тейки
        """
        for attempt in range(max_retries):
            try:
                from tinkoff.invest import Client, CandleInterval
                
                ticker = position['ticker']
                
                with Client(token) as client:
                    instruments = client.instruments.find_instrument(query=ticker)
                    if not instruments.instruments:
                        print(f"  ⚠️ {ticker}: не найден")
                        return position
                    
                    figi = None
                    for inst in instruments.instruments:
                        if inst.ticker.upper() == ticker.upper():
                            figi = inst.figi
                            break
                    
                    if not figi:
                        figi = instruments.instruments[0].figi
                    
                    entry_date = datetime.strptime(position['entry_date'], '%Y-%m-%d %H:%M')
                    
                    candles = client.market_data.get_candles(
                        figi=figi,
                        from_=entry_date - timedelta(days=1),
                        to=datetime.now(),
                        interval=CandleInterval.CANDLE_INTERVAL_HOUR
                    )
                    
                    if not candles.candles:
                        return position
                    
                    remaining_qty = position['quantity']
                    entry_price = position['entry_price']
                    direction = position['direction']
                    
                    stop_loss = position['stop_loss']
                    tp1 = position['take_profit_1']
                    tp2 = position['take_profit_2']
                    tp3 = position['take_profit_3']
                    
                    initial_qty = position['initial_quantity']
                    
                    for candle in candles.candles:
                        if remaining_qty <= 0:
                            break
                        
                        candle_time = candle.time
                        high = candle.high.units + candle.high.nano / 1e9
                        low = candle.low.units + candle.low.nano / 1e9
                        
                        if direction == 'LONG':
                            # Стоп-лосс
                            if low <= stop_loss:
                                if not position.get('stop_hit'):
                                    position['stop_hit'] = True
                                    position['stop_time'] = candle_time.strftime('%Y-%m-%d %H:%M')
                                    position['stop_price'] = stop_loss
                                    remaining_qty = 0
                                    print(f"    🛑 {ticker}: СТОП на {candle_time.strftime('%d.%m %H:%M')} по {stop_loss:.2f}")
                                    break
                            
                            # TP3
                            if not position.get('tp3_hit') and high >= tp3:
                                position['tp3_hit'] = True
                                position['tp3_time'] = candle_time.strftime('%Y-%m-%d %H:%M')
                                position['tp3_price'] = tp3
                                remaining_qty = 0
                                print(f"    🎯 {ticker}: TP3 на {candle_time.strftime('%d.%m %H:%M')} по {tp3:.2f}")
                                break
                            
                            # TP2
                            if not position.get('tp2_closed') and high >= tp2:
                                position['tp2_closed'] = True
                                position['tp2_time'] = candle_time.strftime('%Y-%m-%d %H:%M')
                                position['tp2_price'] = tp2
                                close_qty = remaining_qty * 0.5
                                remaining_qty -= close_qty
                                position['closed_parts'].append({
                                    'time': candle_time.strftime('%Y-%m-%d %H:%M'),
                                    'price': tp2,
                                    'qty': close_qty,
                                    'level': 'TP2'
                                })
                                print(f"    🎯 {ticker}: TP2 на {candle_time.strftime('%d.%m %H:%M')} по {tp2:.2f} (-50% остатка)")
                            
                            # TP1
                            if not position.get('tp1_closed') and high >= tp1:
                                position['tp1_closed'] = True
                                position['tp1_time'] = candle_time.strftime('%Y-%m-%d %H:%M')
                                position['tp1_price'] = tp1
                                close_qty = remaining_qty * 0.5
                                remaining_qty -= close_qty
                                position['closed_parts'].append({
                                    'time': candle_time.strftime('%Y-%m-%d %H:%M'),
                                    'price': tp1,
                                    'qty': close_qty,
                                    'level': 'TP1'
                                })
                                print(f"    🎯 {ticker}: TP1 на {candle_time.strftime('%d.%m %H:%M')} по {tp1:.2f} (-50% остатка)")
                        
                        else:  # SHORT
                            # Стоп-лосс
                            if high >= stop_loss:
                                if not position.get('stop_hit'):
                                    position['stop_hit'] = True
                                    position['stop_time'] = candle_time.strftime('%Y-%m-%d %H:%M')
                                    position['stop_price'] = stop_loss
                                    remaining_qty = 0
                                    print(f"    🛑 {ticker}: СТОП на {candle_time.strftime('%d.%m %H:%M')} по {stop_loss:.2f}")
                                    break
                            
                            # TP3
                            if not position.get('tp3_hit') and low <= tp3:
                                position['tp3_hit'] = True
                                position['tp3_time'] = candle_time.strftime('%Y-%m-%d %H:%M')
                                position['tp3_price'] = tp3
                                remaining_qty = 0
                                print(f"    🎯 {ticker}: TP3 на {candle_time.strftime('%d.%m %H:%M')} по {tp3:.2f}")
                                break
                            
                            # TP2
                            if not position.get('tp2_closed') and low <= tp2:
                                position['tp2_closed'] = True
                                position['tp2_time'] = candle_time.strftime('%Y-%m-%d %H:%M')
                                position['tp2_price'] = tp2
                                close_qty = remaining_qty * 0.5
                                remaining_qty -= close_qty
                                position['closed_parts'].append({
                                    'time': candle_time.strftime('%Y-%m-%d %H:%M'),
                                    'price': tp2,
                                    'qty': close_qty,
                                    'level': 'TP2'
                                })
                                print(f"    🎯 {ticker}: TP2 на {candle_time.strftime('%d.%m %H:%M')} по {tp2:.2f} (-50% остатка)")
                            
                            # TP1
                            if not position.get('tp1_closed') and low <= tp1:
                                position['tp1_closed'] = True
                                position['tp1_time'] = candle_time.strftime('%Y-%m-%d %H:%M')
                                position['tp1_price'] = tp1
                                close_qty = remaining_qty * 0.5
                                remaining_qty -= close_qty
                                position['closed_parts'].append({
                                    'time': candle_time.strftime('%Y-%m-%d %H:%M'),
                                    'price': tp1,
                                    'qty': close_qty,
                                    'level': 'TP1'
                                })
                                print(f"    🎯 {ticker}: TP1 на {candle_time.strftime('%d.%m %H:%M')} по {tp1:.2f} (-50% остатка)")
                    
                    # Обновляем статус
                    if remaining_qty <= 0:
                        position['status'] = 'CLOSED'
                        position['close_date'] = datetime.now().strftime('%Y-%m-%d %H:%M')
                        
                        # Считаем P&L с учётом частичных закрытий
                        total_pnl = 0
                        total_qty_closed = 0
                        
                        for part in position.get('closed_parts', []):
                            qty = part['qty']
                            price = part['price']
                            if direction == 'LONG':
                                part_pnl = (price - entry_price) / entry_price * 100
                            else:
                                part_pnl = (entry_price - price) / entry_price * 100
                            total_pnl += part_pnl * (qty / initial_qty)
                            total_qty_closed += qty
                        
                        remaining = initial_qty - total_qty_closed
                        if remaining > 0:
                            if position.get('stop_hit'):
                                close_price = position['stop_price']
                            elif position.get('tp3_hit'):
                                close_price = tp3
                            else:
                                close_price = candles.candles[-1].close.units + candles.candles[-1].close.nano / 1e9
                            
                            if direction == 'LONG':
                                final_pnl = (close_price - entry_price) / entry_price * 100
                            else:
                                final_pnl = (entry_price - close_price) / entry_price * 100
                            
                            total_pnl += final_pnl * (remaining / initial_qty)
                        
                        position['pnl_pct'] = round(total_pnl, 2)
                    
                    position['quantity'] = remaining_qty
                    
                    # Всегда обновляем текущую цену
                    if candles.candles:
                        last_candle = candles.candles[-1]
                        position['current_price'] = last_candle.close.units + last_candle.close.nano / 1e9
                    
                return position
                
            except Exception as e:
                error_msg = str(e)
                if 'UNAVAILABLE' in error_msg and attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 3
                    print(f"  🔄 {position['ticker']}: API недоступен, повтор через {wait_time}с...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"  ❌ Ошибка обновления {position['ticker']}: {e}")
                    return position
        
        return position
    
    def check_all_positions_history(self, token):
        """Проверяет все активные позиции по историческим данным"""
        print("\n[ПРОВЕРКА] Анализ исторических свечей...")
        print("-" * 100)
        
        closed_positions = []
        
        for position in self.positions:
            if position['status'] != 'ACTIVE':
                continue
            
            position = self.update_position_from_history(position, token)
            
            if position['status'] == 'CLOSED':
                closed_positions.append(position)
        
        for pos in closed_positions:
            self.positions.remove(pos)
            self.closed_positions.append(pos)
        
        self.save_positions()
        
        print("-" * 100)
        print(f"[OK] Проверено позиций: {len(self.positions) + len(closed_positions)}")
        print(f"   Активных: {len(self.positions)}")
        print(f"   Закрыто: {len(closed_positions)}")
    
    def update_all_current_prices(self, token):
        """Обновляет только current_price для всех активных позиций"""
        print("\n[ОБНОВЛЕНИЕ] Запрос текущих цен...")
        print("-" * 100)
        
        try:
            from tinkoff.invest import Client
            
            with Client(token) as client:
                for position in self.positions:
                    if position['status'] != 'ACTIVE':
                        continue
                    
                    ticker = position['ticker']
                    
                    try:
                        instruments = client.instruments.find_instrument(query=ticker)
                        if instruments.instruments:
                            figi = None
                            for inst in instruments.instruments:
                                if inst.ticker.upper() == ticker.upper():
                                    figi = inst.figi
                                    break
                            if not figi:
                                figi = instruments.instruments[0].figi
                            
                            last_price = client.market_data.get_last_prices(figi=[figi])
                            if last_price.last_prices:
                                price = last_price.last_prices[0].price.units + last_price.last_prices[0].price.nano / 1e9
                                old_price = position['current_price']
                                position['current_price'] = price
                                print(f"  ✅ {ticker}: {old_price:.2f} → {price:.2f}")
                    except Exception as e:
                        print(f"  ⚠️ {ticker}: не удалось получить цену - {str(e)[:40]}")
            
            self.save_positions()
            print("-" * 100)
            print("[OK] Цены обновлены")
            
        except Exception as e:
            print(f"[ОШИБКА] {e}")
    
    def update_prices_from_api(self, token):
        """Обновляет текущие цены и проверяет стопы/тейки по истории"""
        self.check_all_positions_history(token)
    
    def print_active_positions(self):
        """Вывод активных позиций с полным P&L"""
        if not self.positions:
            print("\n[ПУСТО] Нет активных позиций")
            return
        
        print("\n" + "="*100)
        print("[ДАННЫЕ] АКТИВНЫЕ ПОЗИЦИИ")
        print("="*100)
        
        for p in self.positions:
            entry_price = p['entry_price']
            current_price = p['current_price']
            direction = p['direction']
            remaining_qty = p['quantity']
            initial_qty = p['initial_quantity']
            
            # Бумажный P&L
            if direction == 'LONG':
                unrealized_pnl_pct = (current_price - entry_price) / entry_price * 100
            else:
                unrealized_pnl_pct = (entry_price - current_price) / entry_price * 100
            
            # Зафиксированный P&L
            realized_pnl_pct = 0
            if p.get('closed_parts'):
                for part in p['closed_parts']:
                    if direction == 'LONG':
                        part_pnl = (part['price'] - entry_price) / entry_price * 100
                    else:
                        part_pnl = (entry_price - part['price']) / entry_price * 100
                    realized_pnl_pct += part_pnl * (part['qty'] / initial_qty)
            
            # Итоговый P&L
            weighted_unrealized = unrealized_pnl_pct * (remaining_qty / initial_qty)
            total_pnl_pct = weighted_unrealized + realized_pnl_pct
            
            emoji = "✅" if total_pnl_pct >= 0 else "❌"
            
            print(f"\n{emoji} [{p['id']}] {direction} {p['ticker']} ({p['sector']})")
            print(f"   Вход: {p['entry_date']} @ {entry_price:.2f}")
            print(f"   Текущая: {current_price:.2f}")
            
            if p.get('closed_parts'):
                print(f"   P&L: {total_pnl_pct:+.2f}% (бумажн: {weighted_unrealized:+.2f}% + зафикс: {realized_pnl_pct:+.2f}%)")
            else:
                print(f"   P&L: {total_pnl_pct:+.2f}%")
            
            print(f"   Вероятность: {p.get('probability', 0)}%")
            print(f"   Блок: {p.get('block_info', {}).get('block_low', 0):.2f} - {p.get('block_info', {}).get('block_high', 0):.2f}")
            
            stop_type = p.get('stop_type', 'legacy')
            if stop_type == 'block':
                stop_info = " 📦"
            elif stop_type == 'entry':
                stop_info = " 📌"
            else:
                stop_info = ""
            print(f"   Стоп: {p['stop_loss']:.2f}{stop_info} | TP1: {p['take_profit_1']:.2f} | TP2: {p['take_profit_2']:.2f} | TP3: {p['take_profit_3']:.2f}")
            
            tp_status = []
            if p.get('tp1_closed'): tp_status.append("TP1✅")
            if p.get('tp2_closed'): tp_status.append("TP2✅")
            if p.get('tp3_hit'): tp_status.append("TP3✅")
            if tp_status:
                print(f"   Статус: {' '.join(tp_status)}")
            
            qty_pct = remaining_qty / initial_qty * 100
            if qty_pct < 100:
                print(f"   Остаток: {qty_pct:.0f}%")
    
    def print_block_statistics(self):
        """Статистика по блочным позициям"""
        if not self.closed_positions:
            print("\n[ПУСТО] Нет закрытых блочных позиций")
            return
        
        print("\n" + "="*100)
        print("[ДАННЫЕ] СТАТИСТИКА БЛОЧНОЙ СИСТЕМЫ")
        print("="*100)
        
        # По типу сигнала
        by_signal_type = {'BOUNCE': [], 'BREAKOUT': []}
        for pos in self.closed_positions:
            sig_type = pos.get('signal_params', {}).get('type', 'BOUNCE')
            pnl = pos.get('pnl_pct', 0)
            if sig_type in by_signal_type:
                by_signal_type[sig_type].append(pnl)
        
        print("\n[ДАННЫЕ] ПО ТИПУ СИГНАЛА:")
        for sig_type, pnls in by_signal_type.items():
            if pnls:
                win_rate = sum(1 for p in pnls if p > 0) / len(pnls) * 100
                avg_pnl = sum(pnls) / len(pnls)
                print(f"   {sig_type}: {len(pnls)} сделок, Win Rate: {win_rate:.1f}%, Средний: {avg_pnl:+.2f}%")
        
        # По тренду
        by_trend = {'with': [], 'against': [], 'neutral': []}
        for pos in self.closed_positions:
            trend = pos.get('signal_params', {}).get('trend_alignment', 'neutral')
            pnl = pos.get('pnl_pct', 0)
            if trend in by_trend:
                by_trend[trend].append(pnl)
        
        print("\n[ДАННЫЕ] ПО СОВПАДЕНИЮ С ТРЕНДОМ:")
        trend_names = {'with': '✅ По тренду', 'against': '⚠️ Против', 'neutral': '📊 Нейтрально'}
        for trend, pnls in by_trend.items():
            if pnls:
                win_rate = sum(1 for p in pnls if p > 0) / len(pnls) * 100
                avg_pnl = sum(pnls) / len(pnls)
                print(f"   {trend_names.get(trend, trend)}: {len(pnls)} сделок, Win Rate: {win_rate:.1f}%, Средний: {avg_pnl:+.2f}%")
        
        # По Score
        by_score = {'high': [], 'medium': [], 'low': []}
        for pos in self.closed_positions:
            score = pos.get('signal_params', {}).get('score', 0)
            pnl = pos.get('pnl_pct', 0)
            if score >= 70:
                by_score['high'].append(pnl)
            elif score >= 40:
                by_score['medium'].append(pnl)
            else:
                by_score['low'].append(pnl)
        
        print("\n[ДАННЫЕ] ПО SCORE:")
        score_names = {'high': '🔥 Высокий (≥70)', 'medium': '📊 Средний (40-69)', 'low': '⏳ Низкий (<40)'}
        for level, pnls in by_score.items():
            if pnls:
                win_rate = sum(1 for p in pnls if p > 0) / len(pnls) * 100
                avg_pnl = sum(pnls) / len(pnls)
                print(f"   {score_names[level]}: {len(pnls)} сделок, Win Rate: {win_rate:.1f}%, Средний: {avg_pnl:+.2f}%")
        
        # Общая статистика
        df = pd.DataFrame(self.closed_positions)
        if 'pnl_pct' in df.columns and len(df) > 0:
            total_pnl = df['pnl_pct'].sum()
            win_rate = len(df[df['pnl_pct'] > 0]) / len(df) * 100
            avg_pnl = df['pnl_pct'].mean()
            
            print(f"\n[ДАННЫЕ] ОБЩАЯ СТАТИСТИКА:")
            print(f"   Всего сделок: {len(df)}")
            print(f"   Win Rate: {win_rate:.1f}%")
            print(f"   Средний P&L: {avg_pnl:+.2f}%")
            print(f"   Суммарный P&L: {total_pnl:+.2f}%")
    
    def get_statistics(self):
        """Возвращает статистику трекера"""
        active = len(self.positions)
        closed = len(self.closed_positions)
        
        profitable = 0
        loss = 0
        total_pnl = 0
        
        for pos in self.closed_positions:
            pnl = pos.get('pnl_pct', 0)
            total_pnl += pnl
            if pnl > 0:
                profitable += 1
            else:
                loss += 1
        
        return {
            'active_positions': active,
            'closed_positions': closed,
            'profitable': profitable,
            'loss': loss,
            'total_pnl': round(total_pnl, 2)
        }
    
    def get_active_positions(self):
        return self.positions
    
    def get_closed_positions(self):
        return self.closed_positions


# ==============================================================================
# ЗАПУСК
# ==============================================================================
if __name__ == "__main__":
    print("[ЗАПУСК] БЛОЧНЫЙ ТРЕКЕР v2.2")
    tracker = BlockDemoTracker()
    
    while True:
        print("\n" + "="*60)
        print("[МЕНЮ] УПРАВЛЕНИЕ")
        print("="*60)
        print("1. Показать активные позиции")
        print("2. Показать статистику")
        print("3. Проверить стопы/тейки по истории")
        print("4. Обновить текущие цены")
        print("5. Кривая доходности")
        print("0. Выход")
        
        choice = input("\nВыберите действие: ")
        
        if choice == '1':
            tracker.print_active_positions()
        
        elif choice == '2':
            tracker.print_block_statistics()
        
        elif choice == '3':
            token = os.getenv('TINKOFF_TOKEN')
            if not token:
                token = input("Введите токен Tinkoff API: ")
            tracker.check_all_positions_history(token)
        
        elif choice == '4':
            token = os.getenv('TINKOFF_TOKEN')
            if not token:
                token = input("Введите токен Tinkoff API: ")
            tracker.update_all_current_prices(token)
        
        elif choice == '5':
            tracker.plot_equity_curve()
        
        elif choice == '0':
            print("[ВЫХОД] До свидания!")
            break