"""
===============================================================================
CHART GENERATOR - Matplotlib Visualizations
===============================================================================

Genereert publicatie-waardige visualisaties voor COMCAM rapportages.

Alle charts worden geretourneerd als base64-encoded PNG strings die direct
in HTML <img> tags kunnen worden gebruikt.

STYLING:
- COMCAM huisstijl (donkerblauw primary)
- Clean, professionele look
- Duidelijke labels en legenda's

REFERENTIES:
- Matplotlib best practices
- Financial visualization guidelines
===============================================================================
"""

import io
import base64
from typing import Dict, List, Optional, Tuple, Any
import numpy as np

# Use non-interactive backend for server-side generation
import matplotlib
matplotlib.use('Agg')

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.ticker import FuncFormatter


class ChartGenerator:
    """
    Genereert visualisaties als base64-encoded PNG strings.

    Usage:
        generator = ChartGenerator()
        chart_base64 = generator.monte_carlo_fan_chart(
            years=np.arange(0, 16),
            percentiles={'p5': [...], 'p50': [...], 'p95': [...]}
        )

        # In HTML:
        # <img src="{chart_base64}" alt="Monte Carlo Chart" />
    """

    def __init__(self, style: str = "comcam"):
        """
        Initialize chart generator.

        Args:
            style: Visual style ("comcam", "minimal", "dark")
        """
        self.style = style
        self._setup_style()

    def _setup_style(self):
        """Configure matplotlib style."""
        # COMCAM huisstijl kleuren
        self.colors = {
            'primary': '#1E3A5F',      # Donkerblauw
            'secondary': '#4A90D9',    # Lichtblauw
            'success': '#28A745',      # Groen
            'warning': '#FFC107',      # Geel
            'danger': '#DC3545',       # Rood
            'gray': '#6C757D',
            'light_gray': '#E9ECEF',
            'dark': '#212529',
        }

        self.figsize = (10, 6)
        self.dpi = 150

        # Set matplotlib defaults
        plt.rcParams.update({
            'figure.facecolor': 'white',
            'axes.facecolor': 'white',
            'axes.edgecolor': self.colors['gray'],
            'axes.labelcolor': self.colors['dark'],
            'axes.titlesize': 14,
            'axes.labelsize': 12,
            'xtick.color': self.colors['dark'],
            'ytick.color': self.colors['dark'],
            'legend.fontsize': 10,
            'font.family': 'sans-serif',
            'grid.color': self.colors['light_gray'],
            'grid.linestyle': '-',
            'grid.linewidth': 0.5,
        })

    def _fig_to_base64(self, fig) -> str:
        """Convert matplotlib figure to base64 PNG string."""
        buf = io.BytesIO()
        fig.savefig(
            buf,
            format='png',
            dpi=self.dpi,
            bbox_inches='tight',
            facecolor='white',
            edgecolor='none'
        )
        buf.seek(0)
        img_base64 = base64.b64encode(buf.read()).decode('utf-8')
        plt.close(fig)
        return f"data:image/png;base64,{img_base64}"

    def _format_currency(self, x, pos=None) -> str:
        """Format number as Euro currency."""
        if abs(x) >= 1_000_000:
            return f'€{x/1_000_000:.1f}M'
        elif abs(x) >= 1_000:
            return f'€{x/1_000:.0f}k'
        return f'€{x:.0f}'

    def monte_carlo_fan_chart(
        self,
        years: np.ndarray,
        percentiles: Dict[str, np.ndarray],
        title: str = "Monte Carlo Simulatie - Cumulatieve Cashflow"
    ) -> str:
        """
        Generate fan chart with confidence intervals.

        Args:
            years: Array of years [0, 1, 2, ..., 15]
            percentiles: Dict with keys 'p5', 'p25', 'p50', 'p75', 'p95'
            title: Chart title

        Returns:
            Base64 encoded PNG string
        """
        fig, ax = plt.subplots(figsize=self.figsize)

        # Fill confidence bands
        ax.fill_between(
            years, percentiles['p5'], percentiles['p95'],
            alpha=0.2, color=self.colors['primary'],
            label='90% Betrouwbaarheidsinterval'
        )
        ax.fill_between(
            years, percentiles['p25'], percentiles['p75'],
            alpha=0.4, color=self.colors['primary'],
            label='50% Betrouwbaarheidsinterval'
        )

        # Median line
        ax.plot(
            years, percentiles['p50'],
            color=self.colors['primary'],
            linewidth=2.5,
            label='Mediaan (P50)'
        )

        # Break-even line
        ax.axhline(y=0, color=self.colors['gray'], linestyle='--', linewidth=1, alpha=0.7)

        # Find break-even point
        p50 = percentiles['p50']
        breakeven_idx = np.where(np.diff(np.sign(p50)))[0]
        if len(breakeven_idx) > 0:
            be_year = years[breakeven_idx[0]]
            ax.axvline(x=be_year, color=self.colors['success'], linestyle=':', linewidth=1.5)
            ax.annotate(
                f'Break-even: ~{be_year:.1f} jaar',
                xy=(be_year, 0),
                xytext=(be_year + 1, p50.max() * 0.2),
                fontsize=10,
                color=self.colors['success']
            )

        # Styling
        ax.set_xlabel('Jaren', fontsize=12)
        ax.set_ylabel('Cumulatieve Cashflow', fontsize=12)
        ax.set_title(title, fontsize=14, fontweight='bold', pad=15)
        ax.legend(loc='lower right', framealpha=0.9)
        ax.yaxis.set_major_formatter(FuncFormatter(self._format_currency))
        ax.grid(True, alpha=0.3)
        ax.set_xlim(years[0], years[-1])

        return self._fig_to_base64(fig)

    def npv_distribution_histogram(
        self,
        npv_values: np.ndarray,
        title: str = "NPV Distributie (Monte Carlo)"
    ) -> str:
        """
        Generate histogram of NPV distribution from Monte Carlo results.

        Args:
            npv_values: Array of NPV values from simulations
            title: Chart title

        Returns:
            Base64 encoded PNG string
        """
        fig, ax = plt.subplots(figsize=self.figsize)

        # Histogram
        n, bins, patches = ax.hist(
            npv_values, bins=50, density=True,
            alpha=0.7, color=self.colors['primary'],
            edgecolor='white', linewidth=0.5
        )

        # Color negative NPV bins red
        for patch, left_edge in zip(patches, bins[:-1]):
            if left_edge < 0:
                patch.set_facecolor(self.colors['danger'])

        # Statistics
        mean_npv = np.mean(npv_values)
        median_npv = np.median(npv_values)
        p5 = np.percentile(npv_values, 5)
        p95 = np.percentile(npv_values, 95)
        prob_positive = np.mean(npv_values > 0) * 100

        # Vertical lines for statistics
        ax.axvline(mean_npv, color=self.colors['secondary'], linestyle='-',
                   linewidth=2, label=f'Gemiddelde: {self._format_currency(mean_npv)}')
        ax.axvline(median_npv, color=self.colors['success'], linestyle='--',
                   linewidth=2, label=f'Mediaan: {self._format_currency(median_npv)}')
        ax.axvline(0, color='black', linestyle='-', linewidth=1)

        # Stats text box
        textstr = '\n'.join([
            f'P5: {self._format_currency(p5)}',
            f'P95: {self._format_currency(p95)}',
            f'Kans NPV>0: {prob_positive:.0f}%'
        ])
        props = dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor=self.colors['gray'])
        ax.text(0.95, 0.95, textstr, transform=ax.transAxes, fontsize=10,
                verticalalignment='top', horizontalalignment='right', bbox=props)

        # Styling
        ax.set_xlabel('NPV', fontsize=12)
        ax.set_ylabel('Dichtheid', fontsize=12)
        ax.set_title(title, fontsize=14, fontweight='bold', pad=15)
        ax.legend(loc='upper left', framealpha=0.9)
        ax.xaxis.set_major_formatter(FuncFormatter(self._format_currency))
        ax.grid(True, alpha=0.3, axis='y')

        return self._fig_to_base64(fig)

    def revenue_breakdown_stacked(
        self,
        scenarios: List[Dict],
        title: str = "Opbrengsten per Revenue Stream"
    ) -> str:
        """
        Generate stacked bar chart with revenue breakdown.

        Args:
            scenarios: List of dicts with 'size_kwh' and 'revenues' dict
            title: Chart title

        Returns:
            Base64 encoded PNG string
        """
        fig, ax = plt.subplots(figsize=(12, 6))

        sizes = [s['size_kwh'] for s in scenarios]
        x_pos = np.arange(len(sizes))

        # Get all revenue types
        all_revenue_types = set()
        for s in scenarios:
            all_revenue_types.update(s.get('revenues', {}).keys())
        revenue_types = sorted(list(all_revenue_types))

        # Color map
        colors_map = {
            'peak_shaving': self.colors['primary'],
            'self_consumption': self.colors['success'],
            'arbitrage': self.colors['secondary'],
            'imbalance': self.colors['warning'],
            'gopacs': '#9B59B6',
            'fcr': '#E74C3C',
            'afrr': '#1ABC9C',
        }

        # Plot stacked bars
        bottom = np.zeros(len(sizes))
        for rev_type in revenue_types:
            values = [s.get('revenues', {}).get(rev_type, 0) for s in scenarios]
            color = colors_map.get(rev_type, self.colors['gray'])
            label = rev_type.replace('_', ' ').title()
            ax.bar(x_pos, values, bottom=bottom, label=label, color=color, alpha=0.85)
            bottom += np.array(values)

        # Add total labels on top
        for i, total in enumerate(bottom):
            ax.annotate(
                self._format_currency(total),
                xy=(i, total),
                ha='center', va='bottom',
                fontsize=9, fontweight='bold'
            )

        # Styling
        ax.set_xticks(x_pos)
        ax.set_xticklabels([f'{s} kWh' for s in sizes])
        ax.set_xlabel('Batterijgrootte', fontsize=12)
        ax.set_ylabel('Jaarlijkse Opbrengst', fontsize=12)
        ax.set_title(title, fontsize=14, fontweight='bold', pad=15)
        ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1), framealpha=0.9)
        ax.yaxis.set_major_formatter(FuncFormatter(self._format_currency))
        ax.grid(True, alpha=0.3, axis='y')

        plt.tight_layout()
        return self._fig_to_base64(fig)

    def scenario_comparison_bar(
        self,
        scenarios: List[Dict],
        metric: str = "npv",
        title: str = "NPV per Batterijgrootte"
    ) -> str:
        """
        Compare scenarios with bar chart and error bars.

        Args:
            scenarios: List with 'size_kwh', '{metric}_mean', '{metric}_p25', '{metric}_p75'
            metric: Metric to compare ('npv', 'payback', 'savings')
            title: Chart title

        Returns:
            Base64 encoded PNG string
        """
        fig, ax = plt.subplots(figsize=self.figsize)

        sizes = [s['size_kwh'] for s in scenarios]
        means = [s.get(f'{metric}_mean', s.get(metric, 0)) for s in scenarios]

        # Error bars if available
        if f'{metric}_p25' in scenarios[0]:
            errors_low = [s[f'{metric}_mean'] - s[f'{metric}_p25'] for s in scenarios]
            errors_high = [s[f'{metric}_p75'] - s[f'{metric}_mean'] for s in scenarios]
        else:
            errors_low = errors_high = None

        # Determine colors based on value
        colors = [
            self.colors['success'] if m > 0 else self.colors['danger']
            for m in means
        ]

        x_pos = np.arange(len(sizes))
        bars = ax.bar(x_pos, means, color=colors, alpha=0.85)

        if errors_low and errors_high:
            ax.errorbar(
                x_pos, means,
                yerr=[errors_low, errors_high],
                fmt='none', color='black',
                capsize=5, capthick=2
            )

        # Add value labels
        for bar, mean in zip(bars, means):
            height = bar.get_height()
            va = 'bottom' if height >= 0 else 'top'
            offset = 3 if height >= 0 else -3
            ax.annotate(
                self._format_currency(mean),
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, offset),
                textcoords="offset points",
                ha='center', va=va,
                fontsize=10, fontweight='bold'
            )

        # Zero line
        ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)

        # Styling
        ax.set_xticks(x_pos)
        ax.set_xticklabels([f'{s} kWh' for s in sizes])
        ax.set_xlabel('Batterijgrootte', fontsize=12)
        ax.set_ylabel(metric.upper(), fontsize=12)
        ax.set_title(title, fontsize=14, fontweight='bold', pad=15)
        ax.yaxis.set_major_formatter(FuncFormatter(self._format_currency))
        ax.grid(True, alpha=0.3, axis='y')

        return self._fig_to_base64(fig)

    def growth_scenario_comparison(
        self,
        scenarios: Dict[str, Dict],
        battery_size: float,
        title: str = "Business Case bij Verschillende Groeiscenario's"
    ) -> str:
        """
        Compare growth scenarios side by side.

        Args:
            scenarios: Dict with scenario_name -> {npv, payback, annual_savings}
            battery_size: Battery size in kWh
            title: Chart title

        Returns:
            Base64 encoded PNG string
        """
        fig, axes = plt.subplots(1, 3, figsize=(15, 5))

        scenario_names = list(scenarios.keys())
        x_pos = np.arange(len(scenario_names))

        # NPV comparison
        npvs = [scenarios[s].get('npv', 0) for s in scenario_names]
        colors_npv = [self.colors['success'] if n > 0 else self.colors['danger'] for n in npvs]
        axes[0].bar(x_pos, npvs, color=colors_npv, alpha=0.85)
        axes[0].set_title('NPV per Scenario', fontweight='bold')
        axes[0].set_ylabel('NPV')
        axes[0].axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        axes[0].yaxis.set_major_formatter(FuncFormatter(self._format_currency))

        # Payback comparison
        paybacks = [scenarios[s].get('payback', 20) for s in scenario_names]
        axes[1].bar(x_pos, paybacks, color=self.colors['secondary'], alpha=0.85)
        axes[1].set_title('Terugverdientijd per Scenario', fontweight='bold')
        axes[1].set_ylabel('Jaren')
        axes[1].axhline(y=10, color=self.colors['warning'], linestyle='--',
                        linewidth=2, label='Benchmark: 10 jaar')
        axes[1].legend(loc='upper right')

        # Savings comparison
        savings = [scenarios[s].get('annual_savings', 0) for s in scenario_names]
        axes[2].bar(x_pos, savings, color=self.colors['success'], alpha=0.85)
        axes[2].set_title('Jaarlijkse Besparing per Scenario', fontweight='bold')
        axes[2].set_ylabel('€/jaar')
        axes[2].yaxis.set_major_formatter(FuncFormatter(self._format_currency))

        # Common styling
        for ax in axes:
            ax.set_xticks(x_pos)
            ax.set_xticklabels(scenario_names, rotation=15, ha='right')
            ax.grid(True, alpha=0.3, axis='y')

        plt.suptitle(f'{title} ({battery_size} kWh batterij)',
                     fontsize=14, fontweight='bold', y=1.02)
        plt.tight_layout()

        return self._fig_to_base64(fig)

    def sensitivity_tornado(
        self,
        base_npv: float,
        sensitivities: Dict[str, Tuple[float, float]],
        title: str = "Gevoeligheidsanalyse"
    ) -> str:
        """
        Generate tornado chart for sensitivity analysis.

        Args:
            base_npv: Base case NPV value
            sensitivities: Dict of parameter -> (npv_low, npv_high)
            title: Chart title

        Returns:
            Base64 encoded PNG string
        """
        fig, ax = plt.subplots(figsize=(10, 6))

        # Sort by impact (largest first)
        sorted_params = sorted(
            sensitivities.items(),
            key=lambda x: abs(x[1][1] - x[1][0]),
            reverse=True
        )

        params = [p[0] for p in sorted_params]
        lows = [p[1][0] - base_npv for p in sorted_params]
        highs = [p[1][1] - base_npv for p in sorted_params]

        y_pos = np.arange(len(params))

        # Plot bars
        ax.barh(y_pos, highs, align='center', color=self.colors['success'],
                alpha=0.8, label='Optimistisch')
        ax.barh(y_pos, lows, align='center', color=self.colors['danger'],
                alpha=0.8, label='Pessimistisch')

        # Base line
        ax.axvline(x=0, color='black', linestyle='-', linewidth=2)

        # Styling
        ax.set_yticks(y_pos)
        ax.set_yticklabels(params)
        ax.set_xlabel('Verandering in NPV', fontsize=12)
        ax.set_title(title, fontsize=14, fontweight='bold', pad=15)
        ax.legend(loc='lower right', framealpha=0.9)
        ax.xaxis.set_major_formatter(FuncFormatter(self._format_currency))
        ax.grid(True, alpha=0.3, axis='x')

        return self._fig_to_base64(fig)

    def sizing_recommendation_chart(
        self,
        recommendations: Dict[str, Dict],
        title: str = "Batterij Sizing Advies"
    ) -> str:
        """
        Compare minimum, optimal, and strategic recommendations.

        Args:
            recommendations: Dict with 'minimum', 'optimal', 'strategic' keys
            title: Chart title

        Returns:
            Base64 encoded PNG string
        """
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))

        labels = ['Minimum', 'Optimaal', 'Strategisch']
        tiers = ['minimum', 'optimal', 'strategic']

        sizes = [recommendations[t].get('size_kwh', 0) for t in tiers]
        npvs = [recommendations[t].get('npv', 0) for t in tiers]
        paybacks = [recommendations[t].get('payback', 20) for t in tiers]

        colors = [self.colors['gray'], self.colors['success'], self.colors['secondary']]
        x_pos = np.arange(len(labels))

        # NPV chart
        bars1 = axes[0].bar(x_pos, npvs, color=colors, alpha=0.85)
        axes[0].set_ylabel('NPV', fontsize=12)
        axes[0].set_title('NPV per Advies', fontweight='bold')
        axes[0].yaxis.set_major_formatter(FuncFormatter(self._format_currency))
        axes[0].axhline(y=0, color='black', linestyle='-', linewidth=0.5)

        # Add size labels
        for bar, size, npv in zip(bars1, sizes, npvs):
            axes[0].annotate(
                f'{size:.0f} kWh\n{self._format_currency(npv)}',
                xy=(bar.get_x() + bar.get_width() / 2, max(0, bar.get_height())),
                xytext=(0, 5),
                textcoords="offset points",
                ha='center', va='bottom',
                fontsize=10, fontweight='bold'
            )

        # Payback chart
        bars2 = axes[1].bar(x_pos, paybacks, color=colors, alpha=0.85)
        axes[1].set_ylabel('Terugverdientijd (jaren)', fontsize=12)
        axes[1].set_title('Terugverdientijd per Advies', fontweight='bold')
        axes[1].axhline(y=10, color=self.colors['warning'], linestyle='--',
                        linewidth=2, label='Benchmark: 10 jaar')
        axes[1].legend(loc='upper right')

        # Add payback labels
        for bar, payback in zip(bars2, paybacks):
            axes[1].annotate(
                f'{payback:.1f} jaar',
                xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                xytext=(0, 5),
                textcoords="offset points",
                ha='center', va='bottom',
                fontsize=10, fontweight='bold'
            )

        # Common styling
        for ax in axes:
            ax.set_xticks(x_pos)
            ax.set_xticklabels(labels)
            ax.grid(True, alpha=0.3, axis='y')

        plt.suptitle(title, fontsize=14, fontweight='bold', y=1.02)
        plt.tight_layout()

        return self._fig_to_base64(fig)

    def load_profile_comparison(
        self,
        timestamps: np.ndarray,
        original: np.ndarray,
        with_battery: np.ndarray,
        title: str = "Vermogensprofiel - Voor en Na Batterij"
    ) -> str:
        """
        Compare load profile before and after battery.

        Args:
            timestamps: Time points
            original: Original load values
            with_battery: Load values with battery
            title: Chart title

        Returns:
            Base64 encoded PNG string
        """
        fig, ax = plt.subplots(figsize=(12, 5))

        # Sample for readability (e.g., 1 week)
        sample_size = min(len(timestamps), 7 * 96)  # 7 days × 96 quarters

        x = np.arange(sample_size)

        # Fill areas
        ax.fill_between(x, original[:sample_size],
                        alpha=0.3, color=self.colors['danger'], label='Origineel')
        ax.fill_between(x, with_battery[:sample_size],
                        alpha=0.5, color=self.colors['success'], label='Met batterij')

        # Peak lines
        original_peak = np.max(original[:sample_size])
        new_peak = np.max(with_battery[:sample_size])

        ax.axhline(y=original_peak, color=self.colors['danger'], linestyle='--',
                   label=f'Originele piek: {original_peak:.0f} kW')
        ax.axhline(y=new_peak, color=self.colors['success'], linestyle='--',
                   label=f'Nieuwe piek: {new_peak:.0f} kW')

        # Styling
        ax.set_xlabel('Tijd (kwartieren)', fontsize=12)
        ax.set_ylabel('Vermogen (kW)', fontsize=12)
        ax.set_title(title, fontsize=14, fontweight='bold', pad=15)
        ax.legend(loc='upper right', framealpha=0.9)
        ax.grid(True, alpha=0.3)
        ax.set_xlim(0, sample_size)

        return self._fig_to_base64(fig)

    def profile_overview(
        self,
        profile_df,
        title: str = "Energieprofiel Overzicht"
    ) -> str:
        """
        Generate comprehensive profile overview with multiple subplots.

        Shows: daily pattern, weekly pattern, load duration curve, and peak analysis.
        """
        import pandas as pd

        fig = plt.figure(figsize=(16, 12))

        # Get data
        if 'afname_kwh' in profile_df.columns:
            load_kwh = profile_df['afname_kwh'].values
        else:
            load_kwh = profile_df['afname'].values

        load_kw = load_kwh * 4  # Convert to kW

        # Timestamps
        if 'timestamp' in profile_df.columns:
            timestamps = pd.to_datetime(profile_df['timestamp'])
            hours = timestamps.dt.hour + timestamps.dt.minute / 60
            weekdays = timestamps.dt.dayofweek
        else:
            hours = np.tile(np.repeat(np.arange(24), 4), len(load_kw) // 96 + 1)[:len(load_kw)]
            weekdays = np.tile(np.repeat(np.arange(7), 96), len(load_kw) // (7*96) + 1)[:len(load_kw)]

        # 1. Load Duration Curve (top left)
        ax1 = fig.add_subplot(2, 2, 1)
        sorted_load = np.sort(load_kw)[::-1]
        duration_percent = np.arange(len(sorted_load)) / len(sorted_load) * 100

        ax1.fill_between(duration_percent, sorted_load, alpha=0.3, color=self.colors['primary'])
        ax1.plot(duration_percent, sorted_load, color=self.colors['primary'], linewidth=2)

        # Add percentile markers
        for pct in [90, 95, 99]:
            val = np.percentile(load_kw, pct)
            idx = np.searchsorted(sorted_load[::-1], val)
            ax1.axhline(y=val, color=self.colors['warning'], linestyle='--', alpha=0.7)
            ax1.annotate(f'P{pct}: {val:.0f} kW', xy=(100-pct, val), fontsize=9)

        ax1.axhline(y=np.max(load_kw), color=self.colors['danger'], linestyle='-', linewidth=2)
        ax1.annotate(f'MAX: {np.max(load_kw):.0f} kW', xy=(0, np.max(load_kw)*1.02), fontsize=10, fontweight='bold')

        ax1.set_xlabel('Percentage van de tijd (%)')
        ax1.set_ylabel('Vermogen (kW)')
        ax1.set_title('Load Duration Curve', fontweight='bold')
        ax1.grid(True, alpha=0.3)
        ax1.set_xlim(0, 100)

        # 2. Daily Pattern (top right)
        ax2 = fig.add_subplot(2, 2, 2)

        # Group by hour
        hour_bins = np.floor(hours).astype(int)
        hourly_mean = np.array([load_kw[hour_bins == h].mean() for h in range(24)])
        hourly_max = np.array([load_kw[hour_bins == h].max() for h in range(24)])
        hourly_min = np.array([load_kw[hour_bins == h].min() for h in range(24)])
        hourly_p75 = np.array([np.percentile(load_kw[hour_bins == h], 75) for h in range(24)])
        hourly_p25 = np.array([np.percentile(load_kw[hour_bins == h], 25) for h in range(24)])

        x_hours = np.arange(24)
        ax2.fill_between(x_hours, hourly_min, hourly_max, alpha=0.1, color=self.colors['primary'], label='Min-Max')
        ax2.fill_between(x_hours, hourly_p25, hourly_p75, alpha=0.3, color=self.colors['primary'], label='P25-P75')
        ax2.plot(x_hours, hourly_mean, color=self.colors['primary'], linewidth=2.5, label='Gemiddeld')

        ax2.set_xlabel('Uur van de dag')
        ax2.set_ylabel('Vermogen (kW)')
        ax2.set_title('Dagelijks Patroon', fontweight='bold')
        ax2.legend(loc='upper right')
        ax2.grid(True, alpha=0.3)
        ax2.set_xlim(0, 23)
        ax2.set_xticks(range(0, 24, 3))

        # 3. Weekly Pattern (bottom left)
        ax3 = fig.add_subplot(2, 2, 3)

        day_names = ['Ma', 'Di', 'Wo', 'Do', 'Vr', 'Za', 'Zo']
        daily_mean = np.array([load_kw[weekdays == d].mean() for d in range(7)])
        daily_max = np.array([load_kw[weekdays == d].max() for d in range(7)])
        daily_p95 = np.array([np.percentile(load_kw[weekdays == d], 95) for d in range(7)])

        x_days = np.arange(7)
        width = 0.25
        ax3.bar(x_days - width, daily_mean, width, label='Gemiddeld', color=self.colors['primary'], alpha=0.8)
        ax3.bar(x_days, daily_p95, width, label='P95', color=self.colors['warning'], alpha=0.8)
        ax3.bar(x_days + width, daily_max, width, label='Maximum', color=self.colors['danger'], alpha=0.8)

        ax3.set_xlabel('Dag van de week')
        ax3.set_ylabel('Vermogen (kW)')
        ax3.set_title('Wekelijks Patroon', fontweight='bold')
        ax3.set_xticks(x_days)
        ax3.set_xticklabels(day_names)
        ax3.legend(loc='upper right')
        ax3.grid(True, alpha=0.3, axis='y')

        # 4. Peak Analysis Histogram (bottom right)
        ax4 = fig.add_subplot(2, 2, 4)

        # Create histogram
        n, bins, patches = ax4.hist(load_kw, bins=50, density=False, alpha=0.7,
                                     color=self.colors['primary'], edgecolor='white')

        # Color bins above P95 and P99
        p95 = np.percentile(load_kw, 95)
        p99 = np.percentile(load_kw, 99)
        for patch, left_edge in zip(patches, bins[:-1]):
            if left_edge >= p99:
                patch.set_facecolor(self.colors['danger'])
            elif left_edge >= p95:
                patch.set_facecolor(self.colors['warning'])

        ax4.axvline(p95, color=self.colors['warning'], linestyle='--', linewidth=2, label=f'P95: {p95:.0f} kW')
        ax4.axvline(p99, color=self.colors['danger'], linestyle='--', linewidth=2, label=f'P99: {p99:.0f} kW')
        ax4.axvline(np.max(load_kw), color='black', linestyle='-', linewidth=2, label=f'MAX: {np.max(load_kw):.0f} kW')

        ax4.set_xlabel('Vermogen (kW)')
        ax4.set_ylabel('Frequentie')
        ax4.set_title('Vermogensdistributie & Piekanalyse', fontweight='bold')
        ax4.legend(loc='upper right')
        ax4.grid(True, alpha=0.3, axis='y')

        # Add summary stats
        stats_text = f'Statistieken:\n'
        stats_text += f'Gem: {np.mean(load_kw):.0f} kW\n'
        stats_text += f'Std: {np.std(load_kw):.0f} kW\n'
        stats_text += f'Jaarverbruik: {np.sum(load_kwh)/1000:.0f} MWh'
        ax4.text(0.02, 0.98, stats_text, transform=ax4.transAxes, fontsize=9,
                verticalalignment='top', bbox=dict(boxstyle='round', facecolor='white', alpha=0.9))

        plt.suptitle(title, fontsize=16, fontweight='bold', y=1.02)
        plt.tight_layout()

        return self._fig_to_base64(fig)

    def peak_shaving_visualization(
        self,
        profile_df,
        battery_kwh: float,
        peak_threshold_kw: float,
        title: str = "Peak Shaving Analyse"
    ) -> str:
        """
        Visualize peak shaving potential with before/after comparison.
        """
        import pandas as pd

        fig, axes = plt.subplots(2, 2, figsize=(16, 10))

        # Get data
        if 'afname_kwh' in profile_df.columns:
            load_kwh = profile_df['afname_kwh'].values
        else:
            load_kwh = profile_df['afname'].values
        load_kw = load_kwh * 4

        # Simulate simple peak shaving
        battery_power_kw = battery_kwh  # 1C rate
        new_load_kw = load_kw.copy()
        battery_soc = np.zeros(len(load_kw))
        dispatch_actions = np.zeros(len(load_kw))

        soc = battery_kwh * 0.5  # Start at 50%
        for i in range(len(load_kw)):
            if load_kw[i] > peak_threshold_kw:
                # Discharge to shave peak
                needed_kw = load_kw[i] - peak_threshold_kw
                discharge_kw = min(needed_kw, battery_power_kw, soc * 4)
                new_load_kw[i] = load_kw[i] - discharge_kw
                soc -= discharge_kw * 0.25
                dispatch_actions[i] = -discharge_kw
            elif load_kw[i] < peak_threshold_kw * 0.7:
                # Charge during low load
                headroom_kw = peak_threshold_kw * 0.7 - load_kw[i]
                charge_kw = min(headroom_kw, battery_power_kw, (battery_kwh - soc) * 4)
                soc += charge_kw * 0.25 * 0.95
                dispatch_actions[i] = charge_kw
            battery_soc[i] = soc

        # 1. Week view - Original vs Shaved (top left)
        ax1 = axes[0, 0]
        week_samples = min(7 * 96, len(load_kw))
        x = np.arange(week_samples) / 96  # Days

        ax1.fill_between(x, load_kw[:week_samples], alpha=0.3, color=self.colors['danger'], label='Origineel')
        ax1.fill_between(x, new_load_kw[:week_samples], alpha=0.5, color=self.colors['success'], label='Na peak shaving')
        ax1.axhline(peak_threshold_kw, color=self.colors['warning'], linestyle='--', linewidth=2,
                   label=f'Drempel: {peak_threshold_kw:.0f} kW')

        ax1.set_xlabel('Dagen')
        ax1.set_ylabel('Vermogen (kW)')
        ax1.set_title('Week Vermogensprofiel', fontweight='bold')
        ax1.legend(loc='upper right')
        ax1.grid(True, alpha=0.3)

        # 2. Battery SOC and Dispatch (top right)
        ax2 = axes[0, 1]
        ax2_twin = ax2.twinx()

        ax2.fill_between(x, battery_soc[:week_samples], alpha=0.3, color=self.colors['secondary'])
        ax2.plot(x, battery_soc[:week_samples], color=self.colors['secondary'], linewidth=2, label='SOC (kWh)')
        ax2.set_ylabel('Batterij SOC (kWh)', color=self.colors['secondary'])
        ax2.set_ylim(0, battery_kwh * 1.1)

        # Dispatch actions
        charge_mask = dispatch_actions[:week_samples] > 0
        discharge_mask = dispatch_actions[:week_samples] < 0
        ax2_twin.bar(x[charge_mask], dispatch_actions[:week_samples][charge_mask],
                    width=1/96, color=self.colors['success'], alpha=0.6, label='Laden')
        ax2_twin.bar(x[discharge_mask], dispatch_actions[:week_samples][discharge_mask],
                    width=1/96, color=self.colors['danger'], alpha=0.6, label='Ontladen')
        ax2_twin.set_ylabel('Dispatch (kW)')
        ax2_twin.legend(loc='upper right')

        ax2.set_xlabel('Dagen')
        ax2.set_title('Batterij Status & Dispatch', fontweight='bold')
        ax2.grid(True, alpha=0.3)

        # 3. Peak Reduction Summary (bottom left)
        ax3 = axes[1, 0]

        original_peak = np.max(load_kw)
        new_peak = np.max(new_load_kw)
        reduction = original_peak - new_peak
        reduction_pct = (reduction / original_peak) * 100

        categories = ['Originele\nPiek', 'Nieuwe\nPiek', 'Reductie']
        values = [original_peak, new_peak, reduction]
        colors = [self.colors['danger'], self.colors['success'], self.colors['secondary']]

        bars = ax3.bar(categories, values, color=colors, alpha=0.85)

        for bar, val in zip(bars, values):
            ax3.annotate(f'{val:.0f} kW', xy=(bar.get_x() + bar.get_width()/2, bar.get_height()),
                        xytext=(0, 5), textcoords='offset points', ha='center', fontsize=12, fontweight='bold')

        ax3.set_ylabel('Vermogen (kW)')
        ax3.set_title(f'Piekreductie: {reduction:.0f} kW ({reduction_pct:.1f}%)', fontweight='bold')
        ax3.grid(True, alpha=0.3, axis='y')

        # 4. Monthly Cost Savings (bottom right)
        ax4 = axes[1, 1]

        # Calculate monthly peaks
        n_months = min(12, len(load_kw) // (30 * 96))
        monthly_original = []
        monthly_new = []

        for m in range(n_months):
            start = m * 30 * 96
            end = min((m + 1) * 30 * 96, len(load_kw))
            monthly_original.append(np.max(load_kw[start:end]))
            monthly_new.append(np.max(new_load_kw[start:end]))

        x_months = np.arange(n_months)
        width = 0.35
        ax4.bar(x_months - width/2, monthly_original, width, label='Origineel', color=self.colors['danger'], alpha=0.8)
        ax4.bar(x_months + width/2, monthly_new, width, label='Na peak shaving', color=self.colors['success'], alpha=0.8)

        ax4.set_xlabel('Maand')
        ax4.set_ylabel('Maandpiek (kW)')
        ax4.set_title('Maandelijkse Piekvermogen', fontweight='bold')
        ax4.set_xticks(x_months)
        ax4.set_xticklabels([f'M{i+1}' for i in range(n_months)])
        ax4.legend(loc='upper right')
        ax4.grid(True, alpha=0.3, axis='y')

        # Add savings annotation
        capacity_tariff = 5.20  # €/kW/month
        monthly_savings = np.array(monthly_original) - np.array(monthly_new)
        total_savings = np.sum(monthly_savings) * capacity_tariff
        ax4.text(0.02, 0.98, f'Jaarlijkse besparing:\n€{total_savings:,.0f}',
                transform=ax4.transAxes, fontsize=11, fontweight='bold',
                verticalalignment='top', bbox=dict(boxstyle='round', facecolor='white', alpha=0.9))

        plt.suptitle(f'{title} - {battery_kwh} kWh Batterij', fontsize=16, fontweight='bold', y=1.02)
        plt.tight_layout()

        return self._fig_to_base64(fig)

    def dispatch_heatmap(
        self,
        profile_df,
        dispatch_actions: Optional[np.ndarray] = None,
        title: str = "Dispatch Heatmap"
    ) -> str:
        """
        Create heatmap showing battery dispatch patterns by hour and day.
        """
        import pandas as pd

        fig, axes = plt.subplots(1, 2, figsize=(16, 6))

        # Get data
        if 'afname_kwh' in profile_df.columns:
            load_kwh = profile_df['afname_kwh'].values
        else:
            load_kwh = profile_df['afname'].values
        load_kw = load_kwh * 4

        if 'timestamp' in profile_df.columns:
            timestamps = pd.to_datetime(profile_df['timestamp'])
            hours = timestamps.dt.hour
            weekdays = timestamps.dt.dayofweek
        else:
            hours = np.tile(np.repeat(np.arange(24), 4), len(load_kw) // 96 + 1)[:len(load_kw)]
            weekdays = np.tile(np.repeat(np.arange(7), 96), len(load_kw) // (7*96) + 1)[:len(load_kw)]

        # Create load heatmap (24 hours x 7 days)
        load_matrix = np.zeros((24, 7))
        count_matrix = np.zeros((24, 7))

        for i in range(len(load_kw)):
            h = int(hours.iloc[i] if hasattr(hours, 'iloc') else hours[i])
            d = int(weekdays.iloc[i] if hasattr(weekdays, 'iloc') else weekdays[i])
            load_matrix[h, d] += load_kw[i]
            count_matrix[h, d] += 1

        load_matrix = np.divide(load_matrix, count_matrix, where=count_matrix > 0)

        # Plot load heatmap
        im1 = axes[0].imshow(load_matrix, cmap='YlOrRd', aspect='auto', origin='lower')
        axes[0].set_xlabel('Dag van de week')
        axes[0].set_ylabel('Uur van de dag')
        axes[0].set_title('Gemiddeld Vermogen (kW)', fontweight='bold')
        axes[0].set_xticks(range(7))
        axes[0].set_xticklabels(['Ma', 'Di', 'Wo', 'Do', 'Vr', 'Za', 'Zo'])
        axes[0].set_yticks(range(0, 24, 3))
        plt.colorbar(im1, ax=axes[0], label='kW')

        # Create peak frequency heatmap
        p95 = np.percentile(load_kw, 95)
        peak_matrix = np.zeros((24, 7))

        for i in range(len(load_kw)):
            h = int(hours.iloc[i] if hasattr(hours, 'iloc') else hours[i])
            d = int(weekdays.iloc[i] if hasattr(weekdays, 'iloc') else weekdays[i])
            if load_kw[i] >= p95:
                peak_matrix[h, d] += 1

        # Normalize by total weeks
        n_weeks = len(load_kw) / (7 * 96)
        peak_matrix = peak_matrix / n_weeks

        im2 = axes[1].imshow(peak_matrix, cmap='Reds', aspect='auto', origin='lower')
        axes[1].set_xlabel('Dag van de week')
        axes[1].set_ylabel('Uur van de dag')
        axes[1].set_title(f'Piekfrequentie (>P95: {p95:.0f} kW)', fontweight='bold')
        axes[1].set_xticks(range(7))
        axes[1].set_xticklabels(['Ma', 'Di', 'Wo', 'Do', 'Vr', 'Za', 'Zo'])
        axes[1].set_yticks(range(0, 24, 3))
        plt.colorbar(im2, ax=axes[1], label='Pieken per week')

        plt.suptitle(title, fontsize=14, fontweight='bold', y=1.02)
        plt.tight_layout()

        return self._fig_to_base64(fig)

    def monte_carlo_summary(
        self,
        npv_values: np.ndarray,
        payback_values: np.ndarray,
        battery_size: float,
        title: str = "Monte Carlo Simulatie Samenvatting"
    ) -> str:
        """
        Comprehensive Monte Carlo results visualization.
        """
        fig = plt.figure(figsize=(16, 10))

        # 1. NPV Distribution (top left)
        ax1 = fig.add_subplot(2, 2, 1)
        n, bins, patches = ax1.hist(npv_values, bins=50, density=True, alpha=0.7,
                                     color=self.colors['primary'], edgecolor='white')

        for patch, left_edge in zip(patches, bins[:-1]):
            if left_edge < 0:
                patch.set_facecolor(self.colors['danger'])

        mean_npv = np.mean(npv_values)
        ax1.axvline(mean_npv, color=self.colors['success'], linestyle='-', linewidth=2)
        ax1.axvline(0, color='black', linestyle='-', linewidth=1)

        prob_positive = np.mean(npv_values > 0) * 100
        ax1.set_title(f'NPV Distributie - {prob_positive:.0f}% kans positief', fontweight='bold')
        ax1.set_xlabel('NPV (€)')
        ax1.set_ylabel('Dichtheid')
        ax1.xaxis.set_major_formatter(FuncFormatter(self._format_currency))
        ax1.grid(True, alpha=0.3, axis='y')

        # 2. Payback Distribution (top right)
        ax2 = fig.add_subplot(2, 2, 2)

        # Filter out very long paybacks for better visualization
        valid_payback = payback_values[payback_values < 25]
        ax2.hist(valid_payback, bins=40, density=True, alpha=0.7,
                color=self.colors['secondary'], edgecolor='white')

        ax2.axvline(np.median(valid_payback), color=self.colors['success'], linestyle='-', linewidth=2,
                   label=f'Mediaan: {np.median(valid_payback):.1f} jaar')
        ax2.axvline(10, color=self.colors['warning'], linestyle='--', linewidth=2, label='Benchmark: 10 jaar')

        prob_10y = np.mean(payback_values <= 10) * 100
        ax2.set_title(f'Terugverdientijd - {prob_10y:.0f}% binnen 10 jaar', fontweight='bold')
        ax2.set_xlabel('Terugverdientijd (jaren)')
        ax2.set_ylabel('Dichtheid')
        ax2.legend(loc='upper right')
        ax2.grid(True, alpha=0.3, axis='y')

        # 3. Cumulative NPV over time (bottom left) - simulate
        ax3 = fig.add_subplot(2, 2, 3)

        # Generate cumulative cashflow percentiles
        years = np.arange(16)
        annual_savings = mean_npv / 15  # Rough estimate
        capex = battery_size * 600  # €600/kWh estimate

        p50_cumulative = -capex + annual_savings * years
        p5_cumulative = p50_cumulative * 0.7
        p95_cumulative = p50_cumulative * 1.3

        ax3.fill_between(years, p5_cumulative, p95_cumulative, alpha=0.2, color=self.colors['primary'])
        ax3.plot(years, p50_cumulative, color=self.colors['primary'], linewidth=2.5)
        ax3.axhline(0, color='black', linestyle='--', linewidth=1)

        ax3.set_xlabel('Jaren')
        ax3.set_ylabel('Cumulatieve Cashflow')
        ax3.set_title('Cumulatieve Cashflow met Onzekerheidsband', fontweight='bold')
        ax3.yaxis.set_major_formatter(FuncFormatter(self._format_currency))
        ax3.grid(True, alpha=0.3)

        # 4. Risk Metrics (bottom right)
        ax4 = fig.add_subplot(2, 2, 4)

        # Calculate risk metrics
        var_5 = np.percentile(npv_values, 5)
        cvar_5 = np.mean(npv_values[npv_values <= var_5])
        std_npv = np.std(npv_values)

        metrics = ['Gem. NPV', 'Mediaan NPV', 'Std. Dev.', 'VaR (5%)', 'CVaR (5%)']
        values = [mean_npv, np.median(npv_values), std_npv, var_5, cvar_5]
        colors_risk = [self.colors['success'], self.colors['success'], self.colors['gray'],
                       self.colors['warning'], self.colors['danger']]

        y_pos = np.arange(len(metrics))
        bars = ax4.barh(y_pos, values, color=colors_risk, alpha=0.8)

        ax4.set_yticks(y_pos)
        ax4.set_yticklabels(metrics)
        ax4.axvline(0, color='black', linestyle='-', linewidth=1)
        ax4.set_title('Risicometrieken', fontweight='bold')
        ax4.xaxis.set_major_formatter(FuncFormatter(self._format_currency))
        ax4.grid(True, alpha=0.3, axis='x')

        # Add value labels
        for bar, val in zip(bars, values):
            ax4.annotate(self._format_currency(val), xy=(bar.get_width(), bar.get_y() + bar.get_height()/2),
                        xytext=(5, 0), textcoords='offset points', va='center', fontsize=10)

        plt.suptitle(f'{title} - {battery_size} kWh Batterij', fontsize=16, fontweight='bold', y=1.02)
        plt.tight_layout()

        return self._fig_to_base64(fig)

    # =========================================================================
    # INDIVIDUAL CHARTS - Separate downloadable visualizations
    # =========================================================================

    def npv_distribution_single(
        self,
        npv_values: np.ndarray,
        battery_size: float,
        title: str = "NPV Distributie"
    ) -> str:
        """Single NPV distribution histogram - downloadable."""
        fig, ax = plt.subplots(figsize=self.figsize)

        n, bins, patches = ax.hist(npv_values, bins=50, density=True, alpha=0.7,
                                   color=self.colors['primary'], edgecolor='white')

        for patch, left_edge in zip(patches, bins[:-1]):
            if left_edge < 0:
                patch.set_facecolor(self.colors['danger'])

        mean_npv = np.mean(npv_values)
        median_npv = np.median(npv_values)
        prob_positive = np.mean(npv_values > 0) * 100

        ax.axvline(mean_npv, color=self.colors['success'], linestyle='-', linewidth=2,
                   label=f'Gemiddelde: {self._format_currency(mean_npv)}')
        ax.axvline(median_npv, color=self.colors['secondary'], linestyle='--', linewidth=2,
                   label=f'Mediaan: {self._format_currency(median_npv)}')
        ax.axvline(0, color='black', linestyle='-', linewidth=1)

        ax.set_title(f'{title} - {battery_size} kWh ({prob_positive:.0f}% kans positief)',
                     fontweight='bold', fontsize=14)
        ax.set_xlabel('NPV (€)', fontsize=12)
        ax.set_ylabel('Dichtheid', fontsize=12)
        ax.xaxis.set_major_formatter(FuncFormatter(self._format_currency))
        ax.legend(loc='upper right')
        ax.grid(True, alpha=0.3, axis='y')

        return self._fig_to_base64(fig)

    def payback_distribution_single(
        self,
        payback_values: np.ndarray,
        battery_size: float,
        title: str = "Terugverdientijd Distributie"
    ) -> str:
        """Single payback distribution histogram - downloadable."""
        fig, ax = plt.subplots(figsize=self.figsize)

        valid_payback = payback_values[payback_values < 25]
        ax.hist(valid_payback, bins=40, density=True, alpha=0.7,
                color=self.colors['secondary'], edgecolor='white')

        median_pb = np.median(valid_payback)
        prob_10y = np.mean(payback_values <= 10) * 100

        ax.axvline(median_pb, color=self.colors['success'], linestyle='-', linewidth=2,
                   label=f'Mediaan: {median_pb:.1f} jaar')
        ax.axvline(10, color=self.colors['warning'], linestyle='--', linewidth=2,
                   label='Benchmark: 10 jaar')

        ax.set_title(f'{title} - {battery_size} kWh ({prob_10y:.0f}% binnen 10 jaar)',
                     fontweight='bold', fontsize=14)
        ax.set_xlabel('Terugverdientijd (jaren)', fontsize=12)
        ax.set_ylabel('Dichtheid', fontsize=12)
        ax.legend(loc='upper right')
        ax.grid(True, alpha=0.3, axis='y')

        return self._fig_to_base64(fig)

    def risk_metrics_single(
        self,
        npv_values: np.ndarray,
        battery_size: float,
        title: str = "Risicometrieken"
    ) -> str:
        """Single risk metrics bar chart - downloadable."""
        fig, ax = plt.subplots(figsize=self.figsize)

        mean_npv = np.mean(npv_values)
        median_npv = np.median(npv_values)
        std_npv = np.std(npv_values)
        var_5 = np.percentile(npv_values, 5)
        cvar_5 = np.mean(npv_values[npv_values <= var_5])

        metrics = ['Gemiddelde NPV', 'Mediaan NPV', 'Standaarddeviatie', 'VaR (5%)', 'CVaR (5%)']
        values = [mean_npv, median_npv, std_npv, var_5, cvar_5]
        colors_risk = [self.colors['success'], self.colors['success'], self.colors['gray'],
                       self.colors['warning'], self.colors['danger']]

        y_pos = np.arange(len(metrics))
        bars = ax.barh(y_pos, values, color=colors_risk, alpha=0.8)

        ax.set_yticks(y_pos)
        ax.set_yticklabels(metrics)
        ax.axvline(0, color='black', linestyle='-', linewidth=1)
        ax.set_title(f'{title} - {battery_size} kWh', fontweight='bold', fontsize=14)
        ax.set_xlabel('Waarde (€)', fontsize=12)
        ax.xaxis.set_major_formatter(FuncFormatter(self._format_currency))
        ax.grid(True, alpha=0.3, axis='x')

        for bar, val in zip(bars, values):
            ax.annotate(self._format_currency(val),
                        xy=(bar.get_width(), bar.get_y() + bar.get_height()/2),
                        xytext=(5, 0), textcoords='offset points', va='center', fontsize=10)

        plt.tight_layout()
        return self._fig_to_base64(fig)

    def load_duration_curve_single(
        self,
        profile_df,
        title: str = "Load Duration Curve"
    ) -> str:
        """Single load duration curve - downloadable."""
        fig, ax = plt.subplots(figsize=self.figsize)

        if 'afname_kwh' in profile_df.columns:
            load_kwh = profile_df['afname_kwh'].values
        else:
            load_kwh = profile_df['afname'].values
        load_kw = load_kwh * 4

        sorted_load = np.sort(load_kw)[::-1]
        duration_percent = np.arange(len(sorted_load)) / len(sorted_load) * 100

        ax.fill_between(duration_percent, sorted_load, alpha=0.3, color=self.colors['primary'])
        ax.plot(duration_percent, sorted_load, color=self.colors['primary'], linewidth=2)

        for pct, color in [(90, self.colors['secondary']), (95, self.colors['warning']), (99, self.colors['danger'])]:
            val = np.percentile(load_kw, pct)
            ax.axhline(y=val, color=color, linestyle='--', alpha=0.7, label=f'P{pct}: {val:.0f} kW')

        ax.axhline(y=np.max(load_kw), color='black', linestyle='-', linewidth=2, label=f'MAX: {np.max(load_kw):.0f} kW')

        ax.set_title(title, fontweight='bold', fontsize=14)
        ax.set_xlabel('Percentage van de tijd (%)', fontsize=12)
        ax.set_ylabel('Vermogen (kW)', fontsize=12)
        ax.legend(loc='upper right')
        ax.grid(True, alpha=0.3)
        ax.set_xlim(0, 100)

        plt.tight_layout()
        return self._fig_to_base64(fig)

    def daily_pattern_single(
        self,
        profile_df,
        title: str = "Dagelijks Verbruikspatroon"
    ) -> str:
        """Single daily pattern chart - downloadable."""
        import pandas as pd
        fig, ax = plt.subplots(figsize=self.figsize)

        if 'afname_kwh' in profile_df.columns:
            load_kwh = profile_df['afname_kwh'].values
        else:
            load_kwh = profile_df['afname'].values
        load_kw = load_kwh * 4

        if 'timestamp' in profile_df.columns:
            timestamps = pd.to_datetime(profile_df['timestamp'])
            hours = timestamps.dt.hour + timestamps.dt.minute / 60
        else:
            hours = np.tile(np.repeat(np.arange(24), 4), len(load_kw) // 96 + 1)[:len(load_kw)]

        hour_bins = np.floor(hours).astype(int)
        hourly_mean = np.array([load_kw[hour_bins == h].mean() for h in range(24)])
        hourly_max = np.array([load_kw[hour_bins == h].max() for h in range(24)])
        hourly_min = np.array([load_kw[hour_bins == h].min() for h in range(24)])

        x_hours = np.arange(24)
        ax.fill_between(x_hours, hourly_min, hourly_max, alpha=0.2, color=self.colors['primary'], label='Min-Max bereik')
        ax.plot(x_hours, hourly_mean, color=self.colors['primary'], linewidth=2.5, label='Gemiddeld')

        ax.set_title(title, fontweight='bold', fontsize=14)
        ax.set_xlabel('Uur van de dag', fontsize=12)
        ax.set_ylabel('Vermogen (kW)', fontsize=12)
        ax.legend(loc='upper right')
        ax.grid(True, alpha=0.3)
        ax.set_xlim(0, 23)
        ax.set_xticks(range(0, 24, 3))

        plt.tight_layout()
        return self._fig_to_base64(fig)
