# position_tracker.py - ПОЛНАЯ ФИНАЛЬНАЯ ВЕРСИЯ С ЧАСТИЧНЫМ ЗАКРЫТИЕМ И УЛУЧШЕННОЙ СТАТИСТИКОЙ
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import os
import matplotlib.pyplot as plt
from collections import defaultdict
import requests
from tinkoff.invest import Client, CandleInterval
from tinkoff.invest.utils import now
from dotenv import load_dotenv
from sector_mapping import get_sector as get_sector_from_map

# Загружаем переменные окружения
load_dotenv()

class DemoPositionTracker:
    """
    Улучшенный трекер для демо-мониторинга позиций с разделением по режимам
    """
    def __init__(self, initial_capital=1_000_000, mode='standard', max_positions_per_ticker=1):
        self.initial_capital = initial_capital
        self.mode = mode
        self.max_positions_per_ticker = max_positions_per_ticker  # лимит на дубли
        self.positions = []
        self.closed_positions = []
        self.daily_pnl = []
        self.figi_map = {}
        
        # Разные файлы для разных режимов
        if mode == 'standard':
            self.positions_file = 'demo_positions.json'
        else:
            os.makedirs('data', exist_ok=True)
            self.positions_file = os.path.join('data', f'positions_{mode}.json')
        
        self.load_positions()
        self.load_figi_map()
        
    def load_positions(self):
        """Загружает позиции и проверяет стопы на исторических данных"""
        if os.path.exists(self.positions_file):
            try:
                with open(self.positions_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.positions = data.get('positions', [])
                    self.closed_positions = data.get('closed_positions', [])
                    self.daily_pnl = data.get('daily_pnl', [])
            except Exception:
                pass
            
            # Проверяем стопы при загрузке (без print, чтобы не ломать)
            positions_to_close = []
            for pos in self.positions:
                if pos['direction'] == 'LONG' and pos['current_price'] <= pos['stop_loss']:
                    positions_to_close.append(pos)
                elif pos['direction'] == 'SHORT' and pos['current_price'] >= pos['stop_loss']:
                    positions_to_close.append(pos)
            
            for pos in positions_to_close:
                try:
                    print(f"  🛑 Стоп сработал для {pos['ticker']} (исторически)")
                except:
                    pass
                self.close_position(pos['id'], pos['stop_loss'], datetime.now(), 'STOP_LOSS')
            
            # Обратная совместимость
            for pos in self.positions:
                if 'quantity' not in pos:
                    pos['quantity'] = 1000
                if 'initial_quantity' not in pos:
                    pos['initial_quantity'] = 1000
                if 'closed_parts' not in pos:
                    pos['closed_parts'] = []
                if 'tp1_closed' not in pos:
                    pos['tp1_closed'] = False
                if 'tp2_closed' not in pos:
                    pos['tp2_closed'] = False
            
            for pos in self.closed_positions:
                if 'quantity' not in pos:
                    pos['quantity'] = 1000
                if 'initial_quantity' not in pos:
                    pos['initial_quantity'] = 1000
                if 'closed_parts' not in pos:
                    pos['closed_parts'] = []
    
    def has_active_position(self, ticker):
        """Проверяет, есть ли уже активная позиция по данному тикеру"""
        return any(p['ticker'] == ticker and p['status'] == 'ACTIVE' for p in self.positions)
    
    def save_positions(self):
        """Сохраняет позиции в файл"""
        data = {
            'positions': self.positions,
            'closed_positions': self.closed_positions,
            'daily_pnl': self.daily_pnl
        }
        try:
            with open(self.positions_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
    
    def load_figi_map(self, json_file='all_assets.json'):
        """Загружает маппинг тикеров и FIGI из JSON файла"""
        try:
            if os.path.exists(json_file):
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                assets = data.get('assets', {})
                for ticker, info in assets.items():
                    self.figi_map[ticker] = info.get('figi', '')
        except Exception:
            pass
    
    def get_figi_for_ticker(self, ticker):
        """Получает FIGI по тикеру из загруженного маппинга"""
        return self.figi_map.get(ticker)
    
    def get_sector(self, ticker):
        """Определяет сектор по тикеру"""
        return get_sector_from_map(ticker)
    
    def add_position(self, signal, entry_price=None, entry_date=None, quantity=1000):
        """
        Добавляет новую позицию на основе сигнала с проверкой на дубли
        """
        ticker = signal['Тикер']
    
        # Проверка на дубли
        if self.has_active_position(ticker):
            return None
    
        if not entry_price:
            entry_price = signal['Цена']
        if not entry_date:
            entry_date = datetime.now().strftime('%Y-%m-%d %H:%M')
    
        if 'LONG' in signal['Сигнал']:
            direction = 'LONG'
            stop_loss = entry_price * 0.98
            take_profit_1 = entry_price * 1.02
            take_profit_2 = entry_price * 1.04
            take_profit_3 = entry_price * 1.08
        else:
            direction = 'SHORT'
            stop_loss = entry_price * 1.02
            take_profit_1 = entry_price * 0.98
            take_profit_2 = entry_price * 0.96
            take_profit_3 = entry_price * 0.92
    
        sector = get_sector_from_map(ticker)
        figi = self.get_figi_for_ticker(ticker)
        methods = signal.get('Методы', 'нет')
    
        position = {
            'id': len(self.positions) + len(self.closed_positions) + 1,
            'ticker': ticker,
            'figi': figi,
            'sector': sector,
            'direction': direction,
            'entry_date': entry_date,
            'entry_price': entry_price,
            'current_price': entry_price,
            'stop_loss': stop_loss,
            'take_profit_1': take_profit_1,
            'take_profit_2': take_profit_2,
            'take_profit_3': take_profit_3,
            'quality': signal.get('Качество', 0),
            'confirmation': signal.get('confirmation_score', 0),
            'market_note': signal.get('market_note', ''),
            'methods': methods,
            'mode': self.mode,
            'status': 'ACTIVE',
            'quantity': quantity,
            'initial_quantity': quantity,
            'closed_parts': [],
            'tp1_closed': False,
            'tp2_closed': False,
            'tp3_hit': False,
            'stop_hit': False,
            'history': [{
                'date': entry_date,
                'price': entry_price,
                'action': 'ENTRY',
                'quantity': quantity
            }]
        }
    
        self.positions.append(position)
        self.save_positions()
        try:
            print(f"✅ [{self.mode}] Позиция {position['id']} добавлена: {direction} {ticker} ({sector}) [методы: {methods}] @ {entry_price} (лот: {quantity})")
        except:
            pass
        return position
    
    def close_partial(self, position, price, date, percent, reason):
        """
        Частичное закрытие позиции
        """
        qty_to_close = int(position['quantity'] * percent)
        if qty_to_close == 0:
            return
        
        if position['direction'] == 'LONG':
            pnl_pct = (price - position['entry_price']) / position['entry_price'] * 100
        else:
            pnl_pct = (position['entry_price'] - price) / position['entry_price'] * 100
        
        position['closed_parts'].append({
            'date': date,
            'price': price,
            'qty': qty_to_close,
            'pnl_pct': round(pnl_pct, 2),
            'reason': reason
        })
        
        position['quantity'] -= qty_to_close
        
        position['history'].append({
            'date': date,
            'price': price,
            'action': f'PARTIAL_CLOSE_{reason}',
            'quantity': qty_to_close,
            'remaining': position['quantity']
        })
        
        try:
            print(f"   {reason} {position['ticker']}: закрыто {percent*100:.0f}% ({pnl_pct:+.2f}%), осталось {position['quantity']}")
        except:
            pass
        
        return pnl_pct
    
    def update_position(self, position_id, current_price, current_date=None):
        """Обновляет текущую цену позиции"""
        if not current_date:
            current_date = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        position = next((p for p in self.positions if p['id'] == position_id), None)
        if not position:
            return
        
        if current_price <= 0:
            return
        
        position['current_price'] = current_price
        position['history'].append({
            'date': current_date,
            'price': current_price,
            'action': 'UPDATE',
            'quantity': position['quantity']
        })
        
        if position['direction'] == 'LONG':
            pnl_pct = (current_price - position['entry_price']) / position['entry_price'] * 100
        else:
            pnl_pct = (position['entry_price'] - current_price) / position['entry_price'] * 100
        
        try:
            print(f"   📊 {position['ticker']}: {pnl_pct:+.2f}% (от входа), остаток {position['quantity']}")
        except:
            pass
        
        self.check_levels(position, current_price, current_date)
        self.save_positions()
    
    def check_levels(self, position, current_price, current_date):
        """Проверяет срабатывание стопов и тейков с частичным закрытием"""
        if position['direction'] == 'LONG':
            if current_price <= position['stop_loss'] and not position.get('stop_hit', False):
                position['stop_hit'] = True
                try:
                    print(f"   🛑 {position['ticker']}: достигнут стоп!")
                except:
                    pass
                self.close_position(position['id'], current_price, current_date, 'STOP_LOSS')
                return
            
            if current_price >= position['take_profit_1'] and not position.get('tp1_closed', False):
                self.close_partial(position, current_price, current_date, 0.3, 'TP1')
                position['tp1_closed'] = True
            
            elif current_price >= position['take_profit_2'] and not position.get('tp2_closed', False) and position.get('tp1_closed', False):
                self.close_partial(position, current_price, current_date, 0.3, 'TP2')
                position['tp2_closed'] = True
            
            elif current_price >= position['take_profit_3'] and not position.get('tp3_hit', False):
                position['tp3_hit'] = True
                try:
                    print(f"   🎯🎯🎯 {position['ticker']}: достигнут TP3!")
                except:
                    pass
                self.close_position(position['id'], current_price, current_date, 'TAKE_PROFIT_3')
        
        else:
            if current_price >= position['stop_loss'] and not position.get('stop_hit', False):
                position['stop_hit'] = True
                try:
                    print(f"   🛑 {position['ticker']}: достигнут стоп!")
                except:
                    pass
                self.close_position(position['id'], current_price, current_date, 'STOP_LOSS')
                return
            
            if current_price <= position['take_profit_1'] and not position.get('tp1_closed', False):
                self.close_partial(position, current_price, current_date, 0.3, 'TP1')
                position['tp1_closed'] = True
            
            elif current_price <= position['take_profit_2'] and not position.get('tp2_closed', False) and position.get('tp1_closed', False):
                self.close_partial(position, current_price, current_date, 0.3, 'TP2')
                position['tp2_closed'] = True
            
            elif current_price <= position['take_profit_3'] and not position.get('tp3_hit', False):
                position['tp3_hit'] = True
                try:
                    print(f"   🎯🎯🎯 {position['ticker']}: достигнут TP3!")
                except:
                    pass
                self.close_position(position['id'], current_price, current_date, 'TAKE_PROFIT_3')
    
    def close_position(self, position_id, exit_price, exit_date, reason):
        """Полное закрытие позиции с учетом частичных закрытий и взвешенной доходности"""
        position = next((p for p in self.positions if p['id'] == position_id), None)
        if not position:
            return
        
        entry_price = position['entry_price']
        
        if entry_price == 0:
            return
        
        # Рассчитываем итоговую взвешенную доходность
        total_weighted_pnl = 0
        
        for part in position.get('closed_parts', []):
            part_pnl = part['pnl_pct']
            part_qty = part['qty']
            part_weight = part_qty / position['initial_quantity']
            total_weighted_pnl += part_pnl * part_weight
        
        remaining_qty = position['quantity']
        if remaining_qty > 0:
            if position['direction'] == 'LONG':
                final_pnl = (exit_price - entry_price) / entry_price * 100
            else:
                final_pnl = (entry_price - exit_price) / entry_price * 100
            final_weight = remaining_qty / position['initial_quantity']
            total_weighted_pnl += final_pnl * final_weight
        
        days_held = (datetime.strptime(exit_date, '%Y-%m-%d %H:%M') - 
                    datetime.strptime(position['entry_date'], '%Y-%m-%d %H:%M')).days
        
        closed = position.copy()
        closed.update({
            'exit_date': exit_date,
            'exit_price': exit_price,
            'exit_reason': reason,
            'pnl_pct': round(total_weighted_pnl, 2),
            'pnl_abs': round(total_weighted_pnl / 100 * position['initial_quantity'] * entry_price, 2),
            'pnl_rub': round(total_weighted_pnl / 100 * position['initial_quantity'] * entry_price, 2),
            'status': 'CLOSED',
            'days_held': days_held,
            'final_quantity': remaining_qty
        })
        
        self.positions.remove(position)
        self.closed_positions.append(closed)
        
        exit_day = exit_date[:10]
        self.daily_pnl.append({
            'date': exit_day,
            'pnl': total_weighted_pnl,
            'ticker': position['ticker'],
            'reason': reason,
            'mode': self.mode
        })
        
        self.save_positions()
        
        try:
            parts_info = ""
            if position.get('closed_parts'):
                parts_summary = []
                for part in position['closed_parts']:
                    parts_summary.append(f"{part['reason']}({part['pnl_pct']:+.2f}%)")
                parts_info = f" [части: {', '.join(parts_summary)}]"
            print(f"{reason} [{self.mode}] Позиция {position_id} {position['ticker']} закрыта: {total_weighted_pnl:+.2f}%{parts_info} за {days_held} дн.")
        except:
            pass
    
    def update_prices_from_api(self, tinkoff_token=None):
        """Автоматическое обновление цен через Tinkoff API"""
        if not self.positions:
            return
        
        if not tinkoff_token:
            tinkoff_token = os.getenv('TINKOFF_TOKEN')
            if not tinkoff_token:
                return
        
        try:
            with Client(tinkoff_token) as client:
                for position in self.positions:
                    ticker = position['ticker']
                    figi = self.get_figi_for_ticker(ticker)
                    if not figi:
                        continue
                    try:
                        response = client.market_data.get_last_prices(figi=[figi])
                        if response.last_prices:
                            price = response.last_prices[0]
                            current_price = float(price.price.units) + float(price.price.nano) / 1e9
                            self.update_position(position['id'], current_price)
                    except Exception:
                        pass
        except Exception:
            pass
    
    def print_active_positions(self):
        """
        Вывод всех активных позиций с взвешенной доходностью портфеля
        """
        if not self.positions:
            print(f"\n📭 [{self.mode}] Нет активных позиций")
            return
    
        print("\n" + "="*100)
        print(f"📊 АКТИВНЫЕ ПОЗИЦИИ [{self.mode}]")
        print("="*100)
    
        total_weighted_pnl = 0
    
        for p in self.positions:
            if p['direction'] == 'LONG':
                pnl_pct = (p['current_price'] - p['entry_price']) / p['entry_price'] * 100
            else:
                pnl_pct = (p['entry_price'] - p['current_price']) / p['entry_price'] * 100
            
            position_weight = p['quantity'] / p['initial_quantity'] if p['initial_quantity'] > 0 else 1
            weighted_pnl = pnl_pct * position_weight
            total_weighted_pnl += weighted_pnl
        
            # Эмодзи для доходности
            if pnl_pct >= 8:
                emoji = "🔥🔥🔥"
            elif pnl_pct >= 4:
                emoji = "🔥🔥"
            elif pnl_pct >= 2:
                emoji = "🔥"
            elif pnl_pct >= 0:
                emoji = "✅"
            elif pnl_pct >= -2:
                emoji = "⚠️"
            else:
                emoji = "❌"
        
            # Статус тейков
            tp_status = []
            if p.get('tp3_hit', False):
                tp_status.append("🎯🎯🎯 TP3")
            elif p.get('tp2_closed', False):
                tp_status.append("🎯🎯 TP2")
            elif p.get('tp1_closed', False):
                tp_status.append("🎯 TP1")
        
            if not p.get('tp3_hit', False):
                if pnl_pct >= 4 and not p.get('tp2_closed', False):
                    tp_status.append("⚡ СЛЕДУЮЩИЙ: TP2")
                elif pnl_pct >= 2 and not p.get('tp1_closed', False):
                    tp_status.append("⚡ СЛЕДУЮЩИЙ: TP1")
        
            status_str = f" [{', '.join(tp_status)}]" if tp_status else ""
        
            remaining_pct = (p['quantity'] / p['initial_quantity'] * 100) if p['initial_quantity'] > 0 else 100
        
            print(f"\n{emoji} [{p['id']}] {p['direction']} {p['ticker']} ({p['sector']}){status_str}")
            print(f"   Вход: {p['entry_date']} @ {p['entry_price']:.2f}")
            print(f"   Текущая: {p['current_price']:.2f} ({pnl_pct:+.2f}%) | Остаток: {remaining_pct:.0f}% | Вес: {position_weight:.1f}x")
            print(f"   Качество: {p['quality']} | Подтверждение: {p['confirmation']}")
            print(f"   Методы: {p.get('methods', 'нет')}")
            print(f"   Стоп: {p['stop_loss']:.2f} | TP1: {p['take_profit_1']:.2f} | TP2: {p['take_profit_2']:.2f} | TP3: {p['take_profit_3']:.2f}")
            
            if p.get('closed_parts'):
                parts_str = []
                for part in p['closed_parts']:
                    parts_str.append(f"{part['reason']}({part['pnl_pct']:+.2f}%)")
                print(f"   📊 Частично закрыто: {', '.join(parts_str)}")
    
        print(f"\n📊 Суммарная взвешенная доходность портфеля [{self.mode}]: {total_weighted_pnl:+.2f}%")
    
    def print_statistics(self):
        """
        Расширенная статистика по закрытым позициям (с учетом весов)
        """
        if not self.closed_positions:
            print(f"\n📭 [{self.mode}] Нет закрытых позиций")
            return
        
        print("\n" + "="*100)
        print(f"📊 РАСШИРЕННАЯ СТАТИСТИКА ТОРГОВЛИ [{self.mode}]")
        print("="*100)
        
        df = pd.DataFrame(self.closed_positions)
        
        total_trades = len(df)
        winning_trades = len(df[df['pnl_pct'] > 0])
        losing_trades = len(df[df['pnl_pct'] <= 0])
        
        win_rate = winning_trades / total_trades * 100 if total_trades > 0 else 0
        avg_win = df[df['pnl_pct'] > 0]['pnl_pct'].mean() if winning_trades > 0 else 0
        avg_loss = df[df['pnl_pct'] < 0]['pnl_pct'].mean() if losing_trades > 0 else 0
        
        total_pnl = df['pnl_pct'].sum()
        max_win = df['pnl_pct'].max()
        max_loss = df['pnl_pct'].min()
        
        print(f"\n📈 ОБЩАЯ СТАТИСТИКА:")
        print(f"   Всего сделок: {total_trades}")
        print(f"   Прибыльных: {winning_trades} ({win_rate:.1f}%)")
        print(f"   Убыточных: {losing_trades} ({100-win_rate:.1f}%)")
        print(f"   Суммарная доходность: {total_pnl:+.2f}%")
        print(f"   Средняя прибыль: {avg_win:.2f}%")
        print(f"   Средний убыток: {avg_loss:.2f}%")
        print(f"   Макс. прибыль: {max_win:.2f}%")
        print(f"   Макс. убыток: {max_loss:.2f}%")
        
        expectancy = (win_rate/100 * avg_win) - ((1-win_rate/100) * abs(avg_loss))
        print(f"\n💰 Мат. ожидание на сделку: {expectancy:.2f}%")
        
        if avg_loss != 0:
            print(f"\n📊 ПРОФИЛЬ РИСК/ПРИБЫЛЬ:")
            print(f"   Средний R/R: {avg_win/abs(avg_loss):.2f}")
        
        partial_trades = [p for p in self.closed_positions if p.get('closed_parts')]
        if partial_trades:
            total_partials = sum(len(p.get('closed_parts', [])) for p in partial_trades)
            print(f"\n📊 ЧАСТИЧНЫЕ ЗАКРЫТИЯ:")
            print(f"   Сделок с частичным закрытием: {len(partial_trades)}")
            print(f"   Всего частичных закрытий: {total_partials}")
        
        print(f"\n🎯 ПРИЧИНЫ ЗАКРЫТИЯ:")
        reasons = df['exit_reason'].value_counts()
        for reason, count in reasons.items():
            reason_name = {
                'STOP_LOSS': 'Стоп-лосс',
                'TAKE_PROFIT_1': 'Тейк-профит 1 (2%)',
                'TAKE_PROFIT_2': 'Тейк-профит 2 (4%)',
                'TAKE_PROFIT_3': 'Тейк-профит 3 (8%)'
            }.get(reason, reason)
            pct = count / total_trades * 100
            print(f"   {reason_name}: {count} ({pct:.1f}%)")
        
        print(f"\n🏆 ТОП-3 ЛУЧШИХ СДЕЛОК:")
        top3 = df.nlargest(3, 'pnl_pct')[['ticker', 'direction', 'pnl_pct', 'exit_reason', 'days_held']]
        for _, row in top3.iterrows():
            print(f"   {row['ticker']} {row['direction']}: {row['pnl_pct']:+.2f}% за {row['days_held']} дн.")
        
        print(f"\n💔 ТОП-3 ХУДШИХ СДЕЛОК:")
        bottom3 = df.nsmallest(3, 'pnl_pct')[['ticker', 'direction', 'pnl_pct', 'exit_reason', 'days_held']]
        for _, row in bottom3.iterrows():
            print(f"   {row['ticker']} {row['direction']}: {row['pnl_pct']:+.2f}% за {row['days_held']} дн.")
    
    def plot_equity_curve(self):
        """Рисует кривую доходности"""
        if not self.closed_positions:
            print(f"\n📭 [{self.mode}] Нет данных для построения графика")
            return
        
        sorted_positions = sorted(self.closed_positions, key=lambda x: x['exit_date'])
        
        dates = []
        equity = [self.initial_capital]
        current = self.initial_capital
        
        for pos in sorted_positions:
            dates.append(pos['exit_date'][:10])
            pnl_abs = pos.get('pnl_abs', 0)
            current += pnl_abs
            equity.append(current)
        
        plt.figure(figsize=(12, 6))
        plt.plot(dates, equity[1:], 'b-', linewidth=2, label='Equity')
        plt.axhline(y=self.initial_capital, color='gray', linestyle='--', alpha=0.5)
        plt.title(f'Кривая доходности [{self.mode}]', fontsize=14, fontweight='bold')
        plt.xlabel('Дата')
        plt.ylabel('Капитал, ₽')
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        filename = f'equity_curve_{self.mode}_{datetime.now().strftime("%Y%m%d_%H%M")}.png'
        plt.savefig(filename, dpi=150)
        print(f"💾 График сохранен: {filename}")
        plt.show()
    
    def print_method_statistics(self):
        """Статистика по методам обнаружения блоков"""
        if not self.closed_positions:
            print(f"\n📭 [{self.mode}] Нет закрытых позиций для анализа методов")
            return
        
        print("\n" + "="*100)
        print(f"📊 СТАТИСТИКА ПО МЕТОДАМ ОБНАРУЖЕНИЯ БЛОКОВ [{self.mode}]")
        print("="*100)
        
        df = pd.DataFrame(self.closed_positions)
        method_stats = {}
        
        for _, row in df.iterrows():
            methods = row.get('methods', 'нет')
            pnl = row['pnl_pct']
            
            if methods not in method_stats:
                method_stats[methods] = {'trades': 0, 'wins': 0, 'total_pnl': 0}
            
            method_stats[methods]['trades'] += 1
            method_stats[methods]['total_pnl'] += pnl
            if pnl > 0:
                method_stats[methods]['wins'] += 1
        
        for methods, stats in method_stats.items():
            win_rate = stats['wins'] / stats['trades'] * 100
            avg_pnl = stats['total_pnl'] / stats['trades']
            
            emoji = "🤝" if methods == 'наш+LuxAlgo' else "🟢" if methods == 'наш' else "🟡" if methods == 'LuxAlgo' else "⚪"
            
            print(f"\n{emoji} Метод: {methods}")
            print(f"   Сделок: {stats['trades']}")
            print(f"   Прибыльных: {stats['wins']} ({win_rate:.1f}%)")
            print(f"   Средняя доходность: {avg_pnl:+.2f}%")
            print(f"   Суммарная доходность: {stats['total_pnl']:+.2f}%")
        
        if 'наш' in method_stats and 'LuxAlgo' in method_stats:
            print(f"\n📈 ВЫВОДЫ:")
            our_win = method_stats['наш']['wins'] / method_stats['наш']['trades'] * 100
            lux_win = method_stats['LuxAlgo']['wins'] / method_stats['LuxAlgo']['trades'] * 100
            
            if our_win > lux_win:
                print(f"   ✅ Наш метод эффективнее на {our_win - lux_win:.1f}%")
            elif lux_win > our_win:
                print(f"   ✅ LuxAlgo эффективнее на {lux_win - our_win:.1f}%")
            
            if 'наш+LuxAlgo' in method_stats:
                both_win = method_stats['наш+LuxAlgo']['wins'] / method_stats['наш+LuxAlgo']['trades'] * 100
                print(f"   🤝 При совпадении методов: {both_win:.1f}% прибыльных")


class DemoMode:
    """
    Режим демо-торговли для тестирования стратегии
    """
    def __init__(self, scanner, mode='standard'):
        self.scanner = scanner
        self.mode = mode
        self.tracker = DemoPositionTracker(mode=mode)
    
    def add_group_a_positions(self, quantity=1000):
        """Добавляет только сигналы группы А"""
        if not self.scanner.signals:
            print(f"❌ [{self.mode}] Нет сигналов для добавления")
            return 0
        
        group_a = [s for s in self.scanner.signals if s.get('group') == 'A']
        
        print("\n" + "="*100)
        print(f"🎯 ДОБАВЛЕНИЕ СИГНАЛОВ ГРУППЫ А [{self.mode}] ({len(group_a)} шт.)")
        print("="*100)
        
        added = 0
        for signal in group_a:
            pos = self.tracker.add_position(signal, quantity=quantity)
            if pos:
                added += 1
        
        print(f"\n✅ [{self.mode}] Добавлено {added} позиций из группы А")
        return added


#==============================================================================
# ОСНОВНОЕ МЕНЮ
#==============================================================================

if __name__ == "__main__":
    print("🚀 УЛУЧШЕННЫЙ ДЕМО-ТРЕКЕР С ЧАСТИЧНЫМ ЗАКРЫТИЕМ")
    print("="*60)
    
    print("\nВыберите режим:")
    print("1. Стандартный")
    print("2. Фундаментальный")
    print("3. Все режимы")
    
    mode_choice = input("Выберите (1/2/3): ").strip()
    
    if mode_choice == '1':
        tracker = DemoPositionTracker(mode='standard')
    elif mode_choice == '2':
        tracker = DemoPositionTracker(mode='fundamental')
    else:
        tracker = DemoPositionTracker(mode='all')
    
    while True:
        print("\n" + "="*60)
        print("📋 МЕНЮ УПРАВЛЕНИЯ")
        print("="*60)
        print("1. Показать активные позиции")
        print("2. Показать расширенную статистику")
        print("3. Добавить позицию вручную")
        print("4. Обновить цены (ручной ввод)")
        print("5. Кривая доходности")
        print("6. Анализ по группам качества")
        print("7. Экспорт в CSV")
        print("8. Обновить цены через API")
        print("9. Статистика по методам обнаружения")
        print("0. Выход")
        
        choice = input("\nВыберите действие: ")
        
        if choice == '1':
            token = os.getenv('TINKOFF_TOKEN')
            if token:
                tracker.update_prices_from_api(token)
            tracker.print_active_positions()
        
        elif choice == '2':
            token = os.getenv('TINKOFF_TOKEN')
            if token:
                tracker.update_prices_from_api(token)
            tracker.print_statistics()
        
        elif choice == '3':
            ticker = input("Тикер: ").upper()
            direction = input("Направление (LONG/SHORT): ").upper()
            price = float(input("Цена входа: "))
            quality = int(input("Качество сигнала (0-100): "))
            quantity = int(input("Количество акций (1000): ") or 1000)
            
            signal = {
                'Тикер': ticker,
                'Сигнал': f'{direction} СИГНАЛ',
                'Цена': price,
                'Качество': quality,
                'Методы': 'manual'
            }
            tracker.add_position(signal, quantity=quantity)
        
        elif choice == '4':
            if not tracker.positions:
                print("📭 Нет активных позиций")
                continue
                
            print("\nОбновление цен:")
            for pos in tracker.positions:
                new_price = input(f"{pos['ticker']} ({pos['current_price']:.2f}, остаток {pos['quantity']}): ")
                if new_price:
                    tracker.update_position(pos['id'], float(new_price))
        
        elif choice == '5':
            tracker.plot_equity_curve()
        
        elif choice == '8':
            token = os.getenv('TINKOFF_TOKEN')
            if not token:
                print("❌ TINKOFF_TOKEN не найден")
                token = input("Введите токен: ")
            tracker.update_prices_from_api(token)
        
        elif choice == '9':
            tracker.print_method_statistics()
        
        elif choice == '0':
            print("👋 Выход...")
            break