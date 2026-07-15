# region imports
from AlgorithmImports import *
import numpy as np
# endregion

class PureSectorRotationTest(QCAlgorithm):
    """
    ============================================================================
    测试2: 纯行业轮动 —— 始终BULL，只用动量信号选行业，不存在宏观择时
    ============================================================================

    目的: 验证"行业动量轮动"这个逻辑是否能跑赢 SPY

    逻辑:
    - 不做宏观判断，永远BULL状态
    - 每月选动量最强的前5个行业ETF等权配置
    - 评分: 60日动量*0.4 + 20日动量*0.3 + 成交量变化*0.2 - 波动率*0.1

    如果这个版本跑赢 SPY → 轮动有效，原策略的拖累在宏观择时
    如果这个版本也跑输 SPY → 轮动本身无效，30000u200bu200e

    ============================================================================
    """

    def initialize(self):
        self.set_start_date(2019, 1, 1)
        self.set_end_date(2026, 7, 14)
        self.set_cash(100000)
        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, AccountType.MARGIN)
        self.set_warm_up(252)

        self.spy = self.add_equity("SPY", Resolution.DAILY).symbol
        self.set_benchmark(self.spy)

        self.sector_etfs = {
            "XLY": "可选消费", "XLP": "必需消费", "XLE": "能源",
            "XLF": "金融", "XLV": "医疗", "XLI": "工业",
            "XLK": "科技", "XLB": "材料", "XLU": "公用事业",
            "XLRE": "房地产", "XLC": "通信服务",
        }
        for sym in self.sector_etfs:
            self.add_equity(sym, Resolution.DAILY)

        self.schedule.on(
            self.date_rules.month_start("SPY"),
            self.time_rules.after_market_open("SPY", 90),
            self.monthly_rotation
        )

        self.max_positions = 5
        self.position_pct = 0.18
        self.stop_loss = 0.08
        self.entries = {}
        self.last_month = -1

        self.debug("="*60)
        self.debug("TEST 2: Pure Sector Rotation (Always BULL)")
        self.debug("  Top 5 momentum sectors, monthly rebalance")
        self.debug("="*60)

    def get_sector_momentum(self):
        signals = {}
        for sym in self.sector_etfs:
            symbol = self.securities[sym].symbol
            hist = self.history(symbol, 200, Resolution.DAILY)
            if hist.empty or len(hist) < 60:
                continue

            closes = hist['close'].values
            volumes = hist['volume'].values if 'volume' in hist.columns else None

            spot = closes[-1]
            mom_60 = spot / closes[-60] - 1 if len(closes) >= 60 else 0
            mom_20 = spot / closes[-20] - 1 if len(closes) >= 20 else 0

            above_ma200 = True
            if len(closes) >= 200:
                ma200 = closes[-200:].mean()
                above_ma200 = spot > ma200

            flow = 0
            if volumes is not None and len(volumes) >= 60:
                vol_20 = volumes[-20:].mean()
                vol_60 = volumes[-60:].mean()
                if vol_60 > 0:
                    flow = vol_20 / vol_60 - 1

            if len(closes) >= 20:
                rets = np.diff(np.log(closes[-20:]))
                vol = np.std(rets) * np.sqrt(252)
            else:
                vol = 0.25

            score = mom_60 * 0.4 + mom_20 * 0.3 + flow * 0.2 - vol * 0.1
            if not above_ma200:
                score -= 0.3

            signals[sym] = {
                'score': score,
                'mom_60': mom_60,
                'mom_20': mom_20,
                'flow': flow,
                'vol': vol,
            }

        return signals

    def monthly_rotation(self):
        current_month = self.time.month
        if current_month == self.last_month:
            return
        self.last_month = current_month

        signals = self.get_sector_momentum()
        if not signals:
            self.debug(f"[{self.time.date()}] No sector signals available (warm-up)")
            return

        ranked = sorted(signals.items(), key=lambda x: x[1]['score'], reverse=True)
        selected = ranked[:self.max_positions]

        self.debug(f"\n[{self.time.date()}] Top {self.max_positions} sectors:")
        for sym, sig in selected:
            self.debug(f"  {sym:5s} Score={sig['score']:+.3f} "
                      f"Mom60={sig['mom_60']:+.1%} Flow={sig['flow']:+.2f}")

        # 清仓不在选中的
        selected_set = set(s[0] for s in selected)
        for sym in list(self.entries.keys()):
            if sym not in selected_set and self.portfolio[sym].invested:
                self.liquidate(sym)
                self.debug(f"  [CLOSE] {sym}")
            if sym not in selected_set:
                self.entries.pop(sym, None)

        # 等权建仓
        weight = 1.0 / len(selected)
        for sym, sig in selected:
            self.enter_long(sym, sig, weight)

    def enter_long(self, sym, sig, weight):
        security = self.securities[sym]
        spot = security.price
        if spot <= 0:
            return

        target_value = self.position_pct * weight * self.portfolio.total_portfolio_value
        signal_mult = 0.5 + sig['score'] * 2
        signal_mult = max(0.3, min(1.5, signal_mult))
        target_value *= signal_mult

        quantity = int(target_value / spot)
        if quantity <= 0:
            return

        current_qty = self.portfolio[sym].quantity
        if current_qty < quantity:
            buy_qty = quantity - int(current_qty)
            self.market_order(sym, buy_qty)
            self.entries[sym] = spot
            self.debug(f"  [BUY] {sym} x{buy_qty} @ ${spot:.2f}")

    def on_data(self, data):
        pass

    # 每日止损
    def on_end_of_day(self, symbol=None):
        for sym in list(self.entries.keys()):
            if not self.portfolio[sym].invested:
                self.entries.pop(sym, None)
                continue
            entry = self.entries[sym]
            current = self.securities[sym].price
            if current <= 0:
                continue
            pnl = (current - entry) / entry
            if pnl < -0.08:
                self.liquidate(sym)
                self.entries.pop(sym, None)
                self.debug(f"[STOP] {sym}: {pnl:.1%}")
            elif pnl > 0.20:
                self.liquidate(sym)
                self.entries.pop(sym, None)
                self.debug(f"[PROFIT] {sym}: +{pnl:.1%}")

        if symbol is None:
            self.plot("Test2", "Portfolio Value", self.portfolio.total_portfolio_value)
