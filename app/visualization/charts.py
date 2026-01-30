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
