# region imports
from AlgorithmImports import *
import numpy as np
# endregion

class PureMacroSignalTest(QCAlgorithm):
    """
    ============================================================================
    测试1: 纯宏观方向判断 —— 只用4个信号判断 BULL/BEAR/NEUTRAL，只买卖 SPY
    ============================================================================

    目的: 验证"宏观方向判断"这个核心逻辑的对错

    逻辑:
    - BULL  → 全仓 SPY
    - BEAR  → 全部现金
    - NEUTRAL → 半仓 SPY

    如果这个版本也跑输 SPY Buy & Hold，说明"宏观择时"本身有问题
    如果这个版本跑赢或接近 SPY，说明宏观判断对，问题在行业轮动或仓位管理

    回测区间: 2019-2026
    对标: SPY Buy & Hold
    ============================================================================
    """

    def initialize(self):
        self.set_start_date(2019, 1, 1)
        self.set_end_date(2026, 7, 14)
        self.set_cash(100000)
        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, AccountType.MARGIN)
        self.set_warm_up(250)

        self.spy = self.add_equity("SPY", Resolution.DAILY).symbol
        self.set_benchmark(self.spy)

        # 债券ETF (用于判断利率环境)
        self.tlt = self.add_equity("TLT", Resolution.DAILY).symbol
        self.shy = self.add_equity("SHY", Resolution.DAILY).symbol

        # 行业ETF — 仅用于PMI代理信号
        self.add_equity("XLI", Resolution.DAILY)
        self.add_equity("XLU", Resolution.DAILY)

        # FRED宏观数据
        self.add_data(FredRate, "FEDFUNDS", Resolution.DAILY)

        # 定时任务
        self.schedule.on(
            self.date_rules.month_start("SPY"),
            self.time_rules.after_market_open("SPY", 90),
            self.monthly_macro_check
        )

        # 策略状态
        self.market_direction = "NEUTRAL"
        self.direction_score = 0.0
        self.rate_direction = "STEADY"
        self.yield_curve = "NORMAL"
        self.pmi_proxy = 50.0
        self.fed_rate = 0.05
        self.last_check_month = -1

        self.debug("="*60)
        self.debug("TEST 1: Pure Macro Direction Signal (SPY Only)")
        self.debug("  BULL  → 100% SPY")
        self.debug("  BEAR  → 0% SPY (Cash)")
        self.debug("  NEUTRAL → 50% SPY")
        self.debug("="*60)

    # ========================================================================
    #  宏观方向判断 (与原始策略完全一致)
    # ========================================================================
    def get_rate_direction_signal(self):
        tlt_hist = self.history(self.tlt, 120, Resolution.DAILY)
        shy_hist = self.history(self.shy, 120, Resolution.DAILY)

        if tlt_hist.empty or shy_hist.empty or len(tlt_hist) < 60:
            if self.fed_rate > 0.04:
                self.rate_direction = "HIKING"
                return -0.5
            elif self.fed_rate < 0.02:
                self.rate_direction = "CUTTING"
                return +0.5
            self.rate_direction = "STEADY"
            return 0.0

        tlt_ret_60 = tlt_hist['close'].iloc[-1] / tlt_hist['close'].iloc[-60] - 1
        shy_ret_60 = shy_hist['close'].iloc[-1] / shy_hist['close'].iloc[-60] - 1
        tlt_ret_20 = tlt_hist['close'].iloc[-1] / tlt_hist['close'].iloc[-20] - 1
        shy_ret_20 = shy_hist['close'].iloc[-1] / shy_hist['close'].iloc[-20] - 1

        bond_spread_60 = tlt_ret_60 - shy_ret_60
        bond_spread_20 = tlt_ret_20 - shy_ret_20

        if bond_spread_60 > 0.03:
            self.rate_direction = "CUTTING"
            return +1.0
        elif bond_spread_60 < -0.03:
            self.rate_direction = "HIKING"
            return -1.0
        elif bond_spread_20 > 0.01:
            self.rate_direction = "CUTTING_SOON"
            return +0.5
        elif bond_spread_20 < -0.01:
            self.rate_direction = "HIKING_SOON"
            return -0.5
        else:
            self.rate_direction = "STEADY"
            return 0.0

    def get_yield_curve_signal(self):
        tlt_hist = self.history(self.tlt, 250, Resolution.DAILY)
        shy_hist = self.history(self.shy, 250, Resolution.DAILY)

        if tlt_hist.empty or shy_hist.empty or len(tlt_hist) < 60:
            self.yield_curve = "UNKNOWN"
            return 0.0

        tlt_price = tlt_hist['close'].iloc[-1]
        shy_price = shy_hist['close'].iloc[-1]
        ratio = tlt_price / shy_price
        ratio_60 = tlt_hist['close'].iloc[-60] / shy_hist['close'].iloc[-60]
        ratio_change = ratio / ratio_60 - 1

        if ratio_change < -0.08:
            self.yield_curve = "INVERTED"
            return -1.0
        elif ratio_change < -0.03:
            self.yield_curve = "FLAT"
            return -0.5
        elif ratio_change > 0.03:
            self.yield_curve = "STEEPENING"
            return +1.0
        else:
            self.yield_curve = "NORMAL"
            return 0.0

    def get_pmi_signal(self):
        xli_symbol = self.securities["XLI"].symbol
        xlu_symbol = self.securities["XLU"].symbol
        xli_hist = self.history(xli_symbol, 120, Resolution.DAILY)
        xlu_hist = self.history(xlu_symbol, 120, Resolution.DAILY)

        if xli_hist.empty or xlu_hist.empty or len(xli_hist) < 60:
            self.pmi_proxy = 50.0
            return 0.0

        xli_ret_60 = xli_hist['close'].iloc[-1] / xli_hist['close'].iloc[-60] - 1
        xlu_ret_60 = xlu_hist['close'].iloc[-1] / xlu_hist['close'].iloc[-60] - 1
        xli_ret_20 = xli_hist['close'].iloc[-1] / xli_hist['close'].iloc[-20] - 1
        xlu_ret_20 = xlu_hist['close'].iloc[-1] / xlu_hist['close'].iloc[-20] - 1

        diff_60 = xli_ret_60 - xlu_ret_60
        diff_20 = xli_ret_20 - xlu_ret_20

        self.pmi_proxy = 50 + diff_60 * 100 + diff_20 * 50

        if diff_60 > 0.05 and diff_20 > 0.01:
            return +1.0
        elif diff_60 < -0.05 and diff_20 < -0.01:
            return -1.0
        elif diff_60 > 0.02:
            return +0.5
        elif diff_60 < -0.02:
            return -0.5
        else:
            return 0.0

    def get_trend_signal(self):
        spy_hist = self.history(self.spy, 250, Resolution.DAILY)
        if spy_hist.empty or len(spy_hist) < 200:
            return 0.0

        closes = spy_hist['close'].values
        ma50 = closes[-50:].mean()
        ma200 = closes[-200:].mean()
        spot = closes[-1]

        golden_cross = ma50 > ma200
        above_ma200 = spot > ma200
        dist_from_ma200 = spot / ma200 - 1

        if golden_cross and above_ma200 and dist_from_ma200 > 0.03:
            return +1.0
        elif golden_cross and above_ma200:
            return +0.5
        elif not above_ma200 and not golden_cross:
            return -1.0
        elif not above_ma200:
            return -0.5
        else:
            return 0.0

    def determine_market_direction(self):
        rate_signal = self.get_rate_direction_signal()
        curve_signal = self.get_yield_curve_signal()
        pmi_signal = self.get_pmi_signal()
        trend_signal = self.get_trend_signal()

        score = rate_signal * 0.40 + curve_signal * 0.25 + pmi_signal * 0.20 + trend_signal * 0.15

        if score > 0.20:
            direction = "BULL"
        elif score < -0.20:
            direction = "BEAR"
        else:
            direction = "NEUTRAL"

        self.market_direction = direction
        self.direction_score = score

        self.debug(f"\n[{self.time.date()}] DIRECTION: {direction} | Score: {score:+.2f} "
                  f"| Rate: {rate_signal:+.0f} Curve: {curve_signal:+.0f} "
                  f"PMI: {pmi_signal:+.0f} Trend: {trend_signal:+.0f}")
        return direction, score

    # ========================================================================
    #  交易执行: 纯SPY买卖
    # ========================================================================
    def monthly_macro_check(self):
        current_month = self.time.month
        if current_month == self.last_check_month:
            return
        self.last_check_month = current_month

        direction, score = self.determine_market_direction()

        portfolio_value = self.portfolio.total_portfolio_value
        spy_price = self.securities["SPY"].price
        if spy_price <= 0:
            return

        current_spy_val = self.portfolio["SPY"].holdings_value

        if direction == "BULL":
            # 全仓 SPY
            target_val = portfolio_value * 0.95
        elif direction == "BEAR":
            # 全部现金
            target_val = 0
        else:  # NEUTRAL
            # 半仓 SPY
            target_val = portfolio_value * 0.50

        diff = target_val - current_spy_val

        if abs(diff) > 500:  # 避免微小调仓
            if diff > 0:
                qty = int(diff / spy_price)
                if qty > 0:
                    self.market_order(self.spy, qty)
                    self.debug(f"  [BUY] SPY x{qty} @ ${spy_price:.2f} → Target: ${target_val:.0f}")
            else:
                qty = int(abs(diff) / spy_price)
                if qty > 0:
                    self.market_order(self.spy, -qty)
                    self.debug(f"  [SELL] SPY x{qty} @ ${spy_price:.2f} → Target: ${target_val:.0f}")

    def on_end_of_day(self, symbol=None):
        if symbol is None:
            self.plot("Test1", "Portfolio Value", self.portfolio.total_portfolio_value)
            self.plot("Test1", "Direction Score", self.direction_score)


# ========================================================================
#  FRED数据源
# ========================================================================
class FredRate(PythonData):
    def get_source(self, config, date, is_live_mode):
        return SubscriptionDataSource(
            "https://raw.githubusercontent.com/jamesmcmahon/fred-data/main/data/FEDFUNDS.csv",
            SubscriptionTransportMedium.REMOTE_FILE
        )

    def reader(self, config, line, date, is_live_mode):
        if line is None or line.strip() == "" or line.startswith("DATE"):
            return None
        data = line.split(',')
        if len(data) < 2:
            return None
        rate = FredRate()
        rate.symbol = config.symbol
        rate.time = datetime.strptime(data[0].strip(), "%Y-%m-%d")
        rate.value = float(data[1].strip())
        return rate
