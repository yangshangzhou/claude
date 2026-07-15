# region imports
from AlgorithmImports import *
import numpy as np
# endregion

class MacroSignalLogger(QCAlgorithm):
    """
    ============================================================================
    测试3: 信号记录器 —— 不交易，只输出每月所有信号数值
    ============================================================================

    目的: 对照实际行情，人工判断每个信号是否"说对了"

    输出格式(每月):
    [2020-03-01] SCORE=+0.45 BULL | Rate=+1 Curve=+1 PMI=+0 Trend=-1
                SPY=280.50 | SPY_MA200=310.00 | SPY_above_MA200=True
                FedRate=1.75% | RateDir=CUTTING | YieldCurve=NORMAL
                60d_ret=+12.3% | Vol=18.5%

    对照: 2020年3月是COVID暴跌 → 如果信号还是BULL，说明信号"滞后"
         2022年加息周期 → 信号应该给出BEAR才算正确
         2023年AI爆发 → 信号应该迅速转BULL才有效

    ============================================================================
    """

    def initialize(self):
        self.set_start_date(2019, 1, 1)
        self.set_end_date(2026, 7, 14)
        self.set_cash(100000)
        self.set_warm_up(252)

        self.spy = self.add_equity("SPY", Resolution.DAILY).symbol
        self.set_benchmark(self.spy)

        self.tlt = self.add_equity("TLT", Resolution.DAILY).symbol
        self.shy = self.add_equity("SHY", Resolution.DAILY).symbol
        self.add_equity("XLI", Resolution.DAILY)
        self.add_equity("XLU", Resolution.DAILY)
        self.add_data(FredRate, "FEDFUNDS", Resolution.DAILY)

        self.schedule.on(
            self.date_rules.month_start("SPY"),
            self.time_rules.after_market_open("SPY", 90),
            self.log_all_signals
        )

        self.market_direction = "NEUTRAL"
        self.direction_score = 0.0
        self.rate_direction = "STEADY"
        self.yield_curve = "NORMAL"
        self.pmi_proxy = 50.0
        self.fed_rate = 0.05
        self.last_month = -1
        self.month_count = 0

        self.debug("="*60)
        self.debug("TEST 3: Signal Logger (No Trading)")
        self.debug("  Outputs all signal values monthly.")
        self.debug("  Compare with actual market to judge signal accuracy.")
        self.debug("="*60)
        self.debug(f'{"Month":>4s} {"Date":>12s} {"Score":>7s} {"Dir":>6s} '
                  f'{"RateS":>5s} {"CurveS":>6s} {"PMIS":>4s} {"TrendS":>6s} '
                  f'{"SPY":>8s} {"MA200":>8s} {"AboveMA":>7s} '
                  f'{"FedRate":>7s} {"RateDir":>14s} {"Curve":>14s} '
                  f'{"TLT/SHY":>8s} {"PMI":>6s} {"60dRtn":>7s} {"Vol":>6s}')

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
        tlt_price = tlt_hist['close'].iloc[-1]
        shy_price = shy_hist['close'].iloc[-1]

        self._tlt_shy_ratio = tlt_price / shy_price

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
            self._spy_price = 0
            self._ma200 = 0
            self._above_ma200 = False
            self._spy_60d_ret = 0
            self._spy_vol = 0
            return 0.0

        closes = spy_hist['close'].values
        self._spy_price = closes[-1]
        ma50 = closes[-50:].mean()
        self._ma200 = closes[-200:].mean()
        spot = closes[-1]

        self._above_ma200 = spot > self._ma200
        self._spy_60d_ret = spot / closes[-60] - 1 if len(closes) >= 60 else 0

        if len(closes) >= 20:
            rets = np.diff(np.log(closes[-20:]))
            self._spy_vol = np.std(rets) * np.sqrt(252)
        else:
            self._spy_vol = 0

        golden_cross = ma50 > self._ma200
        dist_from_ma200 = spot / self._ma200 - 1

        if golden_cross and self._above_ma200 and dist_from_ma200 > 0.03:
            return +1.0
        elif golden_cross and self._above_ma200:
            return +0.5
        elif not self._above_ma200 and not golden_cross:
            return -1.0
        elif not self._above_ma200:
            return -0.5
        else:
            return 0.0

    def log_all_signals(self):
        current_month = self.time.month
        if current_month == self.last_month:
            return
        self.last_month = current_month
        self.month_count += 1

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

        tlt_shy = getattr(self, '_tlt_shy_ratio', 0)

        self.debug(f'{self.month_count:>4d} {str(self.time.date()):>12s} {score:>+7.2f} {direction:>6s} '
                  f'{rate_signal:>+5.0f} {curve_signal:>+6.0f} {pmi_signal:>+4.0f} {trend_signal:>+6.0f} '
                  f'{self._spy_price:>8.1f} {self._ma200:>8.1f} {str(self._above_ma200):>7s} '
                  f'{self.fed_rate:>7.3f} {self.rate_direction:>14s} {self.yield_curve:>14s} '
                  f'{tlt_shy:>8.2f} {self.pmi_proxy:>6.0f} {self._spy_60d_ret:>+7.1%} {self._spy_vol:>6.1%}')

    def on_data(self, data):
        if self.fed_rate == 0.05:
            if "FEDFUNDS" in data and data["FEDFUNDS"] is not None:
                self.fed_rate = data["FEDFUNDS"].value / 100.0

    def on_end_of_day(self, symbol=None):
        pass


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
