# region imports
from AlgorithmImports import *
import numpy as np
# endregion

class TrendOnlyTest(QCAlgorithm):
    """
    ============================================================================
    R2-测试1: 纯趋势判断 —— 只用 SPY 均线系统，不用其他信号
    ============================================================================

    验证问题: "只用最直接的均线趋势，能不能比4信号组合更准？"

    逻辑:
    - SPY > MA200 且 MA50 > MA200 (金叉) → BULL → 全仓 SPY
    - SPY < MA200 且 MA50 < MA200 (死叉) → BEAR → 全现金
    - 其他情况 → NEUTRAL → 半仓 SPY

    对比基准: Test1 (4信号组合版) 61.17%
    如果纯趋势 > 61.17% → 其他3个信号在拖后腿
    如果纯趋势 < 61.17% → 多信号组合确实有价值
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

        self.schedule.on(
            self.date_rules.month_start("SPY"),
            self.time_rules.after_market_open("SPY", 90),
            self.monthly_check
        )

        self.last_month = -1

        self.debug("="*60)
        self.debug("R2-TEST1: Pure Trend Following (MA50/MA200 only)")
        self.debug("  SPY > MA200 & Golden Cross → BULL (100% SPY)")
        self.debug("  SPY < MA200 & Death Cross → BEAR (0% cash)")
        self.debug("  Otherwise → NEUTRAL (50% SPY)")
        self.debug("="*60)

    def get_trend_direction(self):
        """纯趋势判断：只用SPY均线"""
        spy_hist = self.history(self.spy, 250, Resolution.DAILY)
        if spy_hist.empty or len(spy_hist) < 200:
            return "NEUTRAL", 0.0

        closes = spy_hist['close'].values
        spot = closes[-1]
        ma50 = closes[-50:].mean()
        ma200_live = closes[-200:].mean()

        golden = ma50 > ma200_live
        above_ma200 = spot > ma200_live
        below_ma200 = spot < ma200_live

        if golden and above_ma200:
            direction = "BULL"
            score = +1.0
        elif not golden and below_ma200:
            direction = "BEAR"
            score = -1.0
        else:
            direction = "NEUTRAL"
            score = 0.0

        self.debug(f"[{self.time.date()}] TREND: {direction:>7s} | "
                  f"SPY=${spot:.1f} MA50=${ma50:.1f} MA200=${ma200_live:.1f} "
                  f"Golden={golden} AboveMA200={above_ma200}")

        return direction, score

    def monthly_check(self):
        current_month = self.time.month
        if current_month == self.last_month:
            return
        self.last_month = current_month

        direction, score = self.get_trend_direction()

        portfolio_value = self.portfolio.total_portfolio_value
        spy_price = self.securities["SPY"].price
        if spy_price <= 0:
            return

        current_spy_val = self.portfolio["SPY"].holdings_value

        if direction == "BULL":
            target_val = portfolio_value * 0.95
        elif direction == "BEAR":
            target_val = 0
        else:
            target_val = portfolio_value * 0.50

        diff = target_val - current_spy_val

        if abs(diff) > 500:
            if diff > 0:
                qty = int(diff / spy_price)
                if qty > 0:
                    self.market_order(self.spy, qty)
                    self.debug(f"  [BUY] SPY x{qty} @ ${spy_price:.2f}")
            else:
                qty = int(abs(diff) / spy_price)
                if qty > 0:
                    self.market_order(self.spy, -qty)
                    self.debug(f"  [SELL] SPY x{qty} @ ${spy_price:.2f}")

    def on_end_of_day(self, symbol=None):
        pass
